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
root.geometry("600x450") #Size is per pixel
root.minsize(400,300)
root.resizable(True, True)# Horizontal, Vertical


# -------------------------
# Game Variables
# -------------------------

score = 0
mole = None
game_running = False

# Timer IDs
mole_timer = None
next_mole_timer = None
round_timer_id = None

# -------------------------
# Round Timer
# -------------------------
ROUND_DURATION = 60 #Timer in seconds
time_remaining = ROUND_DURATION
# -------------------------
# Difficulty (combo-based)
# -------------------------
# Higher levels make the mole appear for a shorter time, reduce the
# waiting time between moles, and shrink the mole's visible size.
difficulty_settings = {
    "Easy": {
        "up_time": (1800, 2500),   # Minimum, Maximum, longer number will make mole stay up longer
        "wait_time": (1200, 1800), # randomly pick with minimum and maximum, lower wait time means mole disappear faster
        "mole_scale": 1.0         # Normal mole size
    },
    "Medium": {
        "up_time": (1200, 1800),
        "wait_time": (800, 1200),
        "mole_scale": 0.8         # Mole is reduced to 80% of normal size
    },
    "Hard": {
        "up_time": (800, 1200),
        "wait_time": (500, 800),
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
# Combo-Based Scoring
# -------------------------
# Higher combos give the player more points.
# Combo 1-2 = 1 point
# Combo 3-4 = 2 points
# Combo 5+ = 3 points

def get_hit_points():
    if combo >= 5:
        return 3
    elif combo >= 3:
        return 2
    else:
        return 1

# -------------------------
#Grid tracking
# -------------------------
ROOM_WIDTH_M = 1.5
ROOM_HEIGHT_M = 1.4
GRID_ROWS =  2
GRID_COLS = 3
WHACK_RADIUS_M = 0.1501 #Circumference around the mole
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

def get_hole_bounds(hole, pad):
    width = max(container.winfo_width(), 1)
    height = max(container.winfo_height(), 1)

    cell_width = width / GRID_COLS
    cell_height = height / GRID_ROWS

    x1 = hole["col"] * cell_width + pad
    y1 = hole["row"] * cell_height + pad
    x2 = (hole["col"] + 1) * cell_width - pad
    y2 = (hole["row"] + 1) * cell_height - pad

    return x1, y1, x2, y2


def draw_hole(hole):
    if hole["canvas_id"] is None:
        return

    if hole is mole:
        mole_scale = difficulty_settings[current_difficulty]["mole_scale"]
        pad = int(DEFAULT_HOLE_PAD / mole_scale)
        colour = "brown"
    else:
        pad = DEFAULT_HOLE_PAD
        colour = "black"

    x1, y1, x2, y2 = get_hole_bounds(hole, pad)

    container.coords(hole["canvas_id"], x1, y1, x2, y2)
    container.itemconfig(hole["canvas_id"], fill=colour)


def redraw_playfield(event=None):
    for hole in holes:
        draw_hole(hole)

    if game_running:
        update_cursor_indicator()

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

DEAD_ZONE_MM = 600           # spec v2.1: alarm when within 60cm of the screen
BOX_WALL_OFFSET_MM = 0       # how far the boxes sit out from the screen wall - measure and set
WARNING_DISTANCE_MM = DEAD_ZONE_MM - BOX_WALL_OFFSET_MM  # the same limit, as the boxes see it
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
warning_label = None


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


def in_dead_zone(seen):
    """Any box sees someone in the dead zone - not just the box owning the cursor,
    which stickiness can leave on a box further away than the closest one."""
    return any(d <= WARNING_DISTANCE_MM for d in seen.values())


assert not in_dead_zone({})
assert not in_dead_zone({1: 900, 2: WARNING_DISTANCE_MM + 1})
assert in_dead_zone({1: 900, 2: WARNING_DISTANCE_MM - 50})   # box 2 alone is enough


def proximity_alarm(too_close):
    """Beep and cover the screen with a warning while someone is in the dead zone."""
    global last_warning_beep, warning_label

    if not too_close:
        if warning_label is not None and warning_label.winfo_exists():
            warning_label.place_forget()
        return

    # Every screen change destroys root's children, so the banner may be gone.
    if warning_label is None or not warning_label.winfo_exists():
        warning_label = tk.Label(
            root,
            text="TOO CLOSE!\nSTEP BACK",
            font=("Arial", 40, "bold"),
            fg="white",
            bg="red"
        )
    warning_label.place(relx=0.5, rely=0.5, anchor="center", relwidth=1.0, relheight=0.5)
    warning_label.lift()

    current_time = time.monotonic()
    if current_time - last_warning_beep < warning_beep_interval:
        return
    last_warning_beep = current_time

    print("WARNING: Player is within 60cm of the screen")
    if winsound_available:
        threading.Thread(target=winsound.Beep, args=(1000, 200), daemon=True).start()


def poll_sensor():
    global cursor_x_m, cursor_y_m, active_box_id

    with distance_lock:
        seen = {box_id: d for box_id, d in latest_by_box.items() if d is not None}

    # Alarm is a safety feature - it fires whether or not a game is running.
    proximity_alarm(in_dead_zone(seen))

    box_id = pick_box(seen, active_box_id)
    if box_id is not None and game_running:
        distance = seen[box_id]
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
    game_running = False

    for widget in root.winfo_children():
        widget.destroy()

    create_game()
    show_countdown(begin_round)

# -------------------------
# Countdown
# -------------------------
def show_countdown(on_complete):
    overlay= tk.Label(
        container,
        text="",
        font=("Arial", 48, "bold"),
        fg= "white",
        bg = "black"
    )
    overlay.place(relx=0.5, rely=0.5, anchor = "center")
    sequence = [ "Ready", "Set", "Go!"]
    def show_word(index):
        # If the player escaped back to the menu mid-countdown, the overlay
        # (and the whole game screen) has already been destroyed - bail out
        # instead of trying to configure a widget that no longer exists.
        if not overlay.winfo_exists():
            return
        if index >= len(sequence):
            overlay.destroy()
            on_complete()
            return
        overlay.config(text=sequence[index])
        root.after(700, lambda:show_word(index +1))
    show_word(0)
                   
                        
# -------------------------
# Begin Round (after the countdown)
# -------------------------
def begin_round():
    global game_running, time_remaining
    game_running = True
    time_remaining = ROUND_DURATION
    schedule_next_mole()
    update_cursor_indicator()
    tick_round_timer()
# -------------------------
# Create Game
# -------------------------

def create_game():

    global container
    global score_label
    global timer_label
    global coord_label
    global holes

    score_label = tk.Label(
        root,
        text="Score: 0 | Combo: 0 | Level: Easy",
        font=("Arial", 18, "bold")
    )
    score_label.pack(pady=5)
    timer_label = tk.Label(
        root,
        text=f"Time: {ROUND_DURATION}s",
        font=("arial", 14, "bold")
    )
    timer_label.pack(pady=2) #Adds 2 pixels between timer and score

    container = tk.Canvas(root, bg="lightgreen", highlightthickness=0)
    container.pack(fill=tk.BOTH, expand=True)

    holes = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            hole_x_m = (c + 0.5) * (ROOM_WIDTH_M / GRID_COLS)
            hole_y_m = (r + 0.5) * (ROOM_HEIGHT_M / GRID_ROWS)

            canvas_id = container.create_rectangle(
                0,
                0,
                0,
                0,
                fill="black",
                outline=""
            )

            holes.append({
                "row": r,
                "col": c,
                "x_m": hole_x_m,
                "y_m": hole_y_m,
                "canvas_id": canvas_id
            })

    coord_label = tk.Label(
        container,
        text="x=0.00m, y=0.00m",
        bg="lightgreen",
        fg="black",
        font=("Arial", 12, "bold")
    )
    coord_label.place(relx=0.01, rely=0.98, anchor="sw")

    container.bind("<Configure>", redraw_playfield)
    root.after(0, redraw_playfield)

    update_cursor_indicator()

# -------------------------
#Tracking Cursor
# -------------------------
def poll_mouse():
    global cursor_x_m, cursor_y_m

    if game_running:

        # Get mouse position on the whole screen
        mouse_x = root.winfo_pointerx()
        mouse_y = root.winfo_pointery()

        # Get the gameplay area's position on the whole screen
        container_x = container.winfo_rootx()
        container_y = container.winfo_rooty()

        # Convert the mouse position into coordinates
        # relative to the gameplay area
        px = mouse_x - container_x
        py = mouse_y - container_y

        width = container.winfo_width()
        height = container.winfo_height()

        # Only track the mouse while it is inside
        # the gameplay area
        if 0 <= px <= width and 0 <= py <= height:

            # Convert pixels into the 1.5m x 1.4m
            # physical play-space coordinates
            cursor_x_m, cursor_y_m = pixel_to_metres(px, py)

            coord_label.config(
                text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m"
            )

            print(
                f"cursor px=({px}, {py})  "
                f"m=({cursor_x_m:.2f}, {cursor_y_m:.2f})"
            )

            update_cursor_indicator()

            # Check whether the current position
            # is close enough to the active mole
            check_whack()

    # Check mouse position again in 20 ms
    root.after(20, poll_mouse)
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
    draw_hole(mole)

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

        old_mole = mole
        mole = None
        draw_hole(old_mole)

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

    mole_x_m = mole["x_m"]
    mole_y_m = mole["y_m"]
    dx = cursor_x_m - mole_x_m
    dy = cursor_y_m - mole_y_m
    distance_m = (dx*dx+dy*dy)**0.5
    if distance_m <= WHACK_RADIUS_M:
    # Check whether click hit the mole
    


        # Increase combo after a successful hit
        combo += 1

        # Calculate points based on the current combo
        points = get_hit_points()

        # Add the awarded points to the total score
        score += points

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
        old_mole = mole
        mole = None
        draw_hole(old_mole)

        # Schedule ONE new mole
        schedule_next_mole()

def update_cursor_indicator():
    if not holes or not game_running:
        return

    cursor_row, cursor_col = get_grid_cell(cursor_x_m, cursor_y_m)

    for hole in holes:
        if (
            hole["row"] == cursor_row
            and hole["col"] == cursor_col
        ):
            container.itemconfig(
                hole["canvas_id"],
                outline="red",
                width=4
            )
        else:
            container.itemconfig(
                hole["canvas_id"],
                outline="",
                width=0
            )


# -------------------------
# Round Timer
# -------------------------
def tick_round_timer():
    global round_timer_id, time_remaining
    if not game_running:
        return
    timer_label.config(text=f"Time: {time_remaining}s")
    if time_remaining <= 0:
        end_round()
        return
    time_remaining -= 1
    round_timer_id = root.after(1000, tick_round_timer)
    
def end_round():
    global game_running
    global mole
    global mole_timer
    global next_mole_timer
    global round_timer_id
    game_running = False
    if mole_timer is not None:
        root.after_cancel(mole_timer)
        mole_timer = None
    if next_mole_timer is not None:
        root.after_cancel(next_mole_timer)
        next_mole_timer = None
    if round_timer_id is not None:
        root.after_cancel(round_timer_id)
        round_timer_id = None
    if mole is not None:
        old_mole = mole
        mole = None
        draw_hole(old_mole)
    show_game_over()

# -------------------------
# Game Over
# -------------------------
def show_game_over():
    for widget in root.winfo_children():
        widget.destroy()
        
    tk.Label(
        root,
        text="GAME OVER",
        font=("Arial", 32, "bold")
    ).pack(pady=30)
    tk.Label(
        root,
        text=f"Final Score: {score}",
        font=("Arial", 20)
    ).pack(pady=10)
    tk.Button(
        root,
        text="Play Again",
        font=("Arial", 16),
        width=15,
        command=lambda:start_game(current_difficulty)
    ).pack(pady=10)
    tk.Button(
        root,
        text="Main Menu",
        font=("Arial", 14),
        width=15,
        command=start_menu
        ).pack(pady=5)
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
    global round_timer_id
    # Stop the game
    game_running = False

    # Cancel existing timers
    if mole_timer is not None:
        root.after_cancel(mole_timer)
        mole_timer = None

    if next_mole_timer is not None:
        root.after_cancel(next_mole_timer)
        next_mole_timer = None
        
    if round_timer_id is not None:
        root.after_cancel(round_timer_id)
        round_timer_id = None

    # Remove the current mole
    if mole is not None:
        old_mole = mole
        mole = None
        draw_hole(old_mole)

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
root.after(20, poll_mouse)
root.mainloop()