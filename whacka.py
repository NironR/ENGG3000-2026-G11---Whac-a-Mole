import threading
import tkinter as tk
import random
import time


#import guard winsound for non-Windows platforms
try: 
    import winsound
    winsound_available = True
except ImportError:
    winsound_available = False

#--------------------------
#Serial import
#-------------------------
try:
    import serial
    serial_available = True
except ImportError:
    serial_available = False

# -------------------------
# Main Window
# -------------------------

root = tk.Tk()
root.title("Whack-a-Mole")
root.geometry("600x450")
root.minsize(400,300)
root.resizable(True, True)


# -------------------------
# Game Variables
# -------------------------

score = 0
mole = None
game_running = False

# Timer IDs
mole_timer = None
next_mole_timer = None

# -------------------------
# Difficulty (combo-based)
# -------------------------
# Higher levels make the mole appear for a shorter time, reduce the
# waiting time between moles, and shrink the mole's visible size.
difficulty_settings = {
    "Easy": {
        "up_time": (900, 1200),   # Longer number will make mole stay up longer
        "wait_time": (700, 1000), # How fast mole will appear
        "mole_scale": 1.0         # Normal mole size
    },
    "Medium": {
        "up_time": (600, 900),
        "wait_time": (450, 700),
        "mole_scale": 0.8         # Mole is reduced to 80% of normal size
    },
    "Hard": {
        "up_time": (350, 600),
        "wait_time": (250, 450),
        "mole_scale": 0.6         # Mole is reduced to 60% of normal size
    },
}

# ---------------- Combo Difficulty System ----------------
# Tracks consecutive successful hits.
# A higher combo increases the difficulty more quickly.
# Combo 3 = Medium difficulty
# Combo 5 = Hard difficulty
# The combo resets when the player misses a mole.
# -----------------------------------------------------------
combo = 0
current_difficulty = "Easy"


def update_difficulty():
    global current_difficulty

    if score >= 20 or combo >= 5:
        current_difficulty = "Hard"
    elif score >= 8 or combo >= 3:
        current_difficulty = "Medium"
    else:
        current_difficulty = "Easy"

# -------------------------
#Grid tracking
# -------------------------
ROOM_WIDTH_M = 1.5
ROOM_HEIGHT_M = 1.4
GRID_ROWS =  2
GRID_COLS = 3
WHACK_RADIUS_M = 0.1501
cursor_x_m = 0.0
cursor_y_m = 0.0

holes = []  # hole Label widgets, in the same 2x3 order HOLE_LAYOUT_FRACTIONS used to define
DEFAULT_HOLE_PAD = 20  # grid padding at mole_scale == 1.0

def pixel_to_metres (px,py):
    width = max (container.winfo_width(), 1)
    height = max(container.winfo_height(),1)
    x_m = (px / width) * ROOM_WIDTH_M
    y_m = (py / height) * ROOM_HEIGHT_M
    return x_m, y_m
def get_grid_cell(x_m, y_m):
    col = int(x_m / (ROOM_WIDTH_M / GRID_COLS))
    row = int(y_m / (ROOM_HEIGHT_M / GRID_ROWS))
    col = max (0, min (col, GRID_COLS - 1))
    row = max (0, min (row, GRID_ROWS - 1))
    return row, col
def get_hole_grid_cell(px, py):
    return get_grid_cell (*pixel_to_metres(px, py))

def widget_pixel_center(widget):
    return (
        widget.winfo_x() + widget.winfo_width() / 2,
        widget.winfo_y() + widget.winfo_height() / 2
    )

# --------------------------
# Serial Communication (Bluetooth)
#-------------------------
# The boxes no longer talk on their own schedule. A box cannot tell its own
# ultrasonic click apart from a neighbour's scattering off the player, so only
# one may listen at a time. The PC does that sequencing here: asking one box,
# waiting for its answer, then asking the next. Unlike time slots on the boxes
# themselves this needs no shared clock - three ESP32s booted at different
# moments never agree on when a slot begins.

box_ports = {          # BOX_ID -> COM port. Box 1 is the left column, 3 the right.
    1: "COM6",
    2: "COM7",
    3: "COM8",
}
baud_rate = 115200
poll_timeout_s = 0.1   # a box answers well inside this; a missing one costs this much
port_retry_s = 3.0     # don't stall the sweep retrying a box that isn't plugged in

WARNING_DISTANCE_MM = 500    # brief: audible alarm within 50cm of the screen
warning_beep_interval = 0.5  # seconds, stops the beep machine-gunning
COLUMN_STICKINESS_MM = 150   # another box must be this much closer to steal the column

# TODO: calibrate against real measured bench-test readings (mm), once done, replace placeholder values w real readings
# when a person stands at the near edge of the play zone, and the far edge.
sensor_near_mm = 100 # placeholder value, change to real measured reading
sensor_far_mm = 1400 # placeholder value, change to real measured reading

latest_by_box = {}       # BOX_ID -> distance in mm, or None when that box sees nobody
distance_lock = threading.Lock()
active_box_id = None     # which box currently owns the cursor
last_warning_beep = 0.00


def read_reading(ser, box_id):
    """One DIST reply from this box, or None. Skips WARNING and any stray line."""
    for _ in range(4):
        parts = ser.readline().decode("utf-8", errors="ignore").split()
        if len(parts) == 3 and parts[0] == str(box_id) and parts[1] == "DIST":
            try:
                value = int(parts[2])
            except ValueError:
                return None
            return value if value >= 0 else None   # -1 = box looked, saw nothing
    return None


def serial_thread():
    if not serial_available:
        print("pySerial not available. Serial communication disabled.")
        return

    ports = {box_id: None for box_id in box_ports}
    retry_after = {box_id: 0.0 for box_id in box_ports}

    while True:
        for box_id, port_name in box_ports.items():
            if ports[box_id] is None:
                if time.monotonic() < retry_after[box_id]:
                    continue
                try:
                    ports[box_id] = serial.Serial(port_name, baud_rate, timeout=poll_timeout_s)
                    print(f"Box {box_id} connected on {port_name}.")
                except serial.SerialException as e:
                    retry_after[box_id] = time.monotonic() + port_retry_s
                    print(f"Box {box_id} unavailable on {port_name}: {e}")
                    continue

            try:
                ser = ports[box_id]
                ser.reset_input_buffer()
                ser.write(b"?")        # any byte means "your turn"
                reading = read_reading(ser, box_id)
            except serial.SerialException:
                print(f"Lost box {box_id} - will retry")
                try:
                    ports[box_id].close()
                except Exception:
                    pass
                ports[box_id] = None
                retry_after[box_id] = time.monotonic() + port_retry_s
                reading = None

            with distance_lock:
                latest_by_box[box_id] = reading

        time.sleep(0.01)   # nothing answered: don't spin the CPU


def distance_to_metres(distance_mm):
    span = sensor_far_mm - sensor_near_mm
    fraction = (distance_mm - sensor_near_mm) / span
    fraction = max(0.0, min(1.0, fraction))
    return fraction * ROOM_HEIGHT_M


def pick_box(seen, current):
    """Nearest box wins, but `current` keeps the column until another is clearly
    closer - a player is wider than the gap between columns, so without this the
    cursor flickers between two boxes whenever they stand on a boundary."""
    if not seen:
        return None
    nearest = min(seen, key=seen.get)
    if current in seen and seen[current] <= seen[nearest] + COLUMN_STICKINESS_MM:
        return current
    return nearest


assert pick_box({}, None) is None
assert pick_box({1: 900, 2: 800}, None) == 2   # nobody owns it yet: nearest wins
assert pick_box({1: 900, 2: 800}, 1) == 1      # 100mm closer isn't enough to steal it
assert pick_box({1: 900, 2: 700}, 1) == 2      # 200mm closer is
assert pick_box({1: 900, 2: 800}, 3) == 2      # owner dropped out: nearest wins


def nearest_box():
    """The box seeing the player, and its distance."""
    with distance_lock:
        seen = {box_id: d for box_id, d in latest_by_box.items() if d is not None}

    box_id = pick_box(seen, active_box_id)
    return (box_id, seen[box_id]) if box_id is not None else (None, None)


def sound_proximity_alarm(distance_mm):
    global last_warning_beep

    if distance_mm > WARNING_DISTANCE_MM:
        return

    current_time = time.monotonic()
    if current_time - last_warning_beep < warning_beep_interval:
        return
    last_warning_beep = current_time

    print("WARNING: Player is within 50cm of sensor")
    if winsound_available:
        threading.Thread(target=winsound.Beep, args=(1000, 200), daemon=True).start()


def poll_sensor():
    global cursor_x_m, cursor_y_m, active_box_id

    box_id, distance = nearest_box()

    if box_id is not None:
        # Alarm is a safety feature - it fires whether or not a game is running.
        sound_proximity_alarm(distance)

    if box_id is not None and game_running:
        active_box_id = box_id
        # BOX_ID is the column: which box sees you is your left/centre/right cell,
        # and that box's distance is how far down the grid you are.
        cursor_x_m = (box_id - 0.5) * (ROOM_WIDTH_M / GRID_COLS)
        cursor_y_m = distance_to_metres(distance)

        coord_label.config(text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m (box {box_id})")
        update_cursor_indicator()
        check_whack()

    root.after(50, poll_sensor)


# -------------------------
# Start Menu
# -------------------------


def start_menu():

    global game_running

    game_running = False

    for widget in root.winfo_children():
        widget.destroy()

    title = tk.Label(
        root,
        text="WHACK-A-MOLE",
        font=("Arial", 32, "bold")
    )
    title.pack(pady=50)



    tk.Button(
        root,
        text="Start",
        font=("Arial", 16),
        width=15,
        command=lambda: start_game("Easy")
    ).pack(pady=10)
    tk.Label(
        root,
        text = "F11: Fullscreen Esc: Menu",
        font=("Arial", 10),
        fg="gray"
        ).pack(pady=5)

# -------------------------
# Start Game
# -------------------------

def start_game(difficulty):

    global current_difficulty
    global score
    global combo
    global game_running

    current_difficulty = difficulty
    score = 0
    combo = 0
    game_running = True

    for widget in root.winfo_children():
        widget.destroy()

    create_game()


# -------------------------
# Create Game
# -------------------------

def create_game():

    global container
    global score_label
    global coord_label
    global holes

    score_label = tk.Label(
        root,
        text="Score: 0 | Combo: 0 | Level: Easy",
        font=("Arial", 18, "bold")
    )
    score_label.pack(pady=5)

    container = tk.Frame(root, bg="lightgreen")
    container.pack(fill=tk.BOTH, expand=True)

    for c in range(GRID_COLS):
        container.grid_columnconfigure(c, weight=1, uniform="col")
    for r in range(GRID_ROWS):
        container.grid_rowconfigure(r, weight=1, uniform="row")

    holes = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            hole = tk.Label(container, bg="black", highlightthickness=0)
            hole.grid(row=r, column=c, sticky="nsew", padx=DEFAULT_HOLE_PAD, pady=DEFAULT_HOLE_PAD)
            holes.append(hole)

    coord_label = tk.Label(
        container,
        text="x=0.00m, y=0.00m",
        bg="lightgreen",
        fg="black",
        font=("Arial", 12, "bold")
    )
    coord_label.place(relx=0.01, rely=0.98, anchor="sw")

    container.bind("<Motion>", track_cursor)

    # Start first mole
    schedule_next_mole()
    update_cursor_indicator()

# -------------------------
#Tracking Cursor
# -------------------------
def track_cursor(event):
    global cursor_x_m, cursor_y_m
    cursor_x_m, cursor_y_m = pixel_to_metres(event.x, event.y)
    coord_label.config(text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m")
    update_cursor_indicator()
    check_whack()
    print(f"cursor px=({event.x}, {event.y})  m=({cursor_x_m:.2f}, {cursor_y_m:.2f})")
# -------------------------
# Schedule Next Mole
# -------------------------

def schedule_next_mole():

    global next_mole_timer

    if not game_running:
        return

    min_time, max_time = difficulty_settings[current_difficulty]["wait_time"]
    wait_time = random.randint(min_time, max_time)

    next_mole_timer = root.after(
        wait_time,
        show_mole
    )


# -------------------------
# Show Mole
# -------------------------

def show_mole():

    global mole
    global mole_timer

    if not game_running:
        return

    # Safety check:
    # Make sure there isn't already a mole
    if mole is not None:
        return
    if not holes:
        schedule_next_mole()
        return
    # Pick random hole
    mole = random.choice(holes)
    mole.config(bg="brown")

    # Shrink the mole's visible area for higher difficulties -- there's no
    # oval radius to resize without Canvas, so padding stands in for it:
    # more padding around the widget means less of the cell is filled.
    mole_scale = difficulty_settings[current_difficulty]["mole_scale"]
    scaled_pad = int(DEFAULT_HOLE_PAD / mole_scale)
    mole.grid_configure(padx=scaled_pad, pady=scaled_pad)

    # Decide how long mole stays up
    min_time, max_time = difficulty_settings[current_difficulty]["up_time"]

    time_up = random.randint(
        min_time,
        max_time
    )

    # Start mole's timer
    mole_timer = root.after(
        time_up,
        hide_mole
    )
    check_whack()

# -------------------------
# Hide Mole
# -------------------------

def hide_mole():

    global mole
    global mole_timer
    global combo

    # If the mole disappears without being hit,
    # the player's combo is broken
    if mole is not None:

        combo = 0

        # Recalculate difficulty after combo is reset
        update_difficulty()

        # Update the display
        score_label.config(
            text=f"Score: {score} | Combo: {combo} | Level: {current_difficulty}"
        )

        mole.grid_configure(padx=DEFAULT_HOLE_PAD, pady=DEFAULT_HOLE_PAD)
        mole.config(bg="black")
        mole = None

    mole_timer = None

    # Schedule ONE new mole
    schedule_next_mole()


# -------------------------
# Whack Mole
# -------------------------

def check_whack():

    global score
    global combo
    global mole
    global mole_timer

    # No mole = nothing to hit
    if mole is None:
        return

    mole_x, mole_y = widget_pixel_center(mole)
    mole_x_m, mole_y_m = pixel_to_metres(mole_x,mole_y)
    dx = cursor_x_m - mole_x_m
    dy = cursor_y_m - mole_y_m
    distance_m = (dx*dx+dy*dy)**0.5
    if distance_m <= WHACK_RADIUS_M:
    # Check whether click hit the mole
    


        # Increase score after a successful hit
        score += 1

        # Increase combo after a consecutive successful hit
        combo += 1

        # Check whether the difficulty level should increase
        update_difficulty()

        # Display the current score and difficulty level
        score_label.config(
            text=f"Score: {score} | Combo: {combo} | Level: {current_difficulty}"
        )

        # IMPORTANT:
        # Cancel the mole's existing timer
        if mole_timer is not None:

            root.after_cancel(mole_timer)
            mole_timer = None

        # Make mole go down immediately
        mole.grid_configure(padx=DEFAULT_HOLE_PAD, pady=DEFAULT_HOLE_PAD)
        mole.config(bg="black")
        mole = None

        # Schedule ONE new mole
        schedule_next_mole()

def update_cursor_indicator():
    if not holes or not game_running:
        return

    cursor_cell = get_grid_cell(cursor_x_m, cursor_y_m)
    target_hole = next(
        (hole for hole in holes if get_hole_grid_cell(*widget_pixel_center(hole)) == cursor_cell),
        None
    )

    for hole in holes:
        hole.config(highlightthickness=0)

    if target_hole is not None:
        target_hole.config(highlightthickness=4, highlightbackground="red", highlightcolor="red")

def update_coord_display():
    if game_running:
        grid_row, grid_col = get_hole_grid_cell(cursor_x_m, cursor_y_m)
        coord_label.config(
            text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m (grid: {grid_row},{grid_col})"
        )
    root.after(50, update_coord_display)

# -------------------------
# Fullscreen Toggle
# -------------------------
def toggle_fullscreen(event=None):
    is_full = root.attributes("-fullscreen")
    root.attributes("-fullscreen", not is_full)
# -------------------------
# Return to Menu
# -------------------------

def return_to_menu(event=None):
    global game_running
    global mole
    global mole_timer
    global next_mole_timer
    # Stop the game
    game_running = False

    # Cancel existing timers
    if mole_timer is not None:
        root.after_cancel(mole_timer)
        mole_timer = None

    if next_mole_timer is not None:
        root.after_cancel(next_mole_timer)
        next_mole_timer = None

    # Remove the current mole
    if mole is not None:
        mole.config(bg="black")
        mole = None

    # Return to start menu
    start_menu()
# -------------------------
# Start
# -------------------------  
bt_thread = threading.Thread(target=serial_thread, daemon=True)
bt_thread.start() 

start_menu()
root.bind("<Escape>", return_to_menu)
root.bind("<F11>", toggle_fullscreen)
root.after(50, poll_sensor)
root.mainloop()