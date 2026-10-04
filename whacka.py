import threading
import tkinter as tk
import random
import time
from PIL import Image, ImageTk


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
        "up_time": (900, 1200),   # Minimum, Maximum, longer number will make mole stay up longer
        "wait_time": (700, 1000), # randomly pick with minimum and maximum, lower wait time means mole disappear faster

    },
    "Medium": {
        "up_time": (600, 900),
        "wait_time": (450, 700),
    },
    "Hard": {
        "up_time": (350, 600),
        "wait_time": (250, 450),
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
WHACK_RADIUS_M = 0.20 #Radius around the mole for a successful hit
cursor_x_m = 0.0
cursor_y_m = 0.0

holes = []  # hole Label widgets, in the same 2x3 order HOLE_LAYOUT_FRACTIONS used to define
DEFAULT_HOLE_PAD = 20  # grid padding at mole_scale == 1.0

arcade_background_source = None
arcade_background_photo = None
arcade_background_id = None
# Playfield corners as fractions of the arcade cabinet image.
# These define the perspective trapezoid containing the six holes.
PLAYFIELD_BACK_LEFT = (0.228, 0.504)
PLAYFIELD_BACK_RIGHT = (0.775, 0.504)
PLAYFIELD_FRONT_LEFT = (0.130, 0.675)
PLAYFIELD_FRONT_RIGHT = (0.871, 0.675)

mole_image_source = None
mole_image_photo = None
mole_image_id = None

hammer_image_source = None
hammer_image_photo = None
hammer_image_id = None
hammer_image_size = None

HAMMER_WIDTH_FRACTION = 0.22

# Position of the striking head within Hammer.png.
# Fine-tune after visually testing the sprite.
HAMMER_STRIKE_X_FRACTION = 0.39
HAMMER_STRIKE_Y_FRACTION = 0.28

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

def get_hole_bounds(hole, scale):
    centre_x, centre_y = metres_to_canvas(
        hole["x_m"],
        hole["y_m"]
    )

    _, _, image_width, image_height = get_arcade_image_geometry()

    depth_fraction = hole["y_m"] / ROOM_HEIGHT_M

    hole_width_fraction = 0.154 + (0.208 - 0.154) * depth_fraction
    hole_height_fraction = 0.057 + (0.091 - 0.057) * depth_fraction

    hole_width = image_width * hole_width_fraction * scale
    hole_height = image_height * hole_height_fraction * scale

    x1 = centre_x - hole_width / 2
    y1 = centre_y - hole_height / 2
    x2 = centre_x + hole_width / 2
    y2 = centre_y + hole_height / 2

    return x1, y1, x2, y2


def draw_hole(hole):
    if hole["canvas_id"] is None:
        return

    x1, y1, x2, y2 = get_hole_bounds(hole, 1.0)

    container.coords(
        hole["canvas_id"],
        x1,
        y1,
        x2,
        y2
    )

    container.itemconfig(
        hole["canvas_id"],
        fill=""
    )

def draw_mole_sprite():
    global mole_image_photo

    if mole_image_id is None:
        return

    if mole is None:
        container.itemconfig(
            mole_image_id,
            state="hidden"
        )
        return

    x1, y1, x2, y2 = get_hole_bounds(
    mole,
    1.0
)

    hole_width = x2 - x1
    hole_height = y2 - y1

    target_width = max(
        1,
        int(hole_width * 0.9)
    )

    source_width, source_height = mole_image_source.size

    target_height = max(
        1,
        int(
            target_width *
            source_height /
            source_width
        )
    )

    resized_image = mole_image_source.resize(
        (target_width, target_height),
        Image.Resampling.LANCZOS
    )

    mole_image_photo = ImageTk.PhotoImage(resized_image)

    centre_x = (x1 + x2) / 2

    mole_bottom_y = (
        (y1 + y2) / 2 +
        hole_height * 0.25
    )

    container.coords(
        mole_image_id,
        centre_x,
        mole_bottom_y
    )

    container.itemconfig(
        mole_image_id,
        image=mole_image_photo,
        state="normal"
    )

def draw_hammer_sprite():
    global hammer_image_photo
    global hammer_image_size

    if hammer_image_id is None:
        return

    if not game_running:
        container.itemconfig(
            hammer_image_id,
            state="hidden"
        )
        return

    hammer_x, hammer_y = metres_to_canvas(
        cursor_x_m,
        cursor_y_m
    )

    _, _, image_width, _ = get_arcade_image_geometry()

    target_width = max(
        1,
        int(image_width * HAMMER_WIDTH_FRACTION)
    )

    source_width, source_height = hammer_image_source.size

    target_height = max(
        1,
        int(
            target_width *
            source_height /
            source_width
        )
    )

    target_size = (target_width, target_height)

    # Only resize the hammer when its required display size changes.
    if hammer_image_size != target_size:
        resized_image = hammer_image_source.resize(
            target_size,
            Image.Resampling.LANCZOS
        )

        hammer_image_photo = ImageTk.PhotoImage(
            resized_image
        )

        hammer_image_size = target_size

        container.itemconfig(
            hammer_image_id,
            image=hammer_image_photo
        )

    draw_x = (
        hammer_x -
        target_width * HAMMER_STRIKE_X_FRACTION
    )

    draw_y = (
        hammer_y -
        target_height * HAMMER_STRIKE_Y_FRACTION
    )

    container.coords(
        hammer_image_id,
        draw_x,
        draw_y
    )

    container.itemconfig(
        hammer_image_id,
        state="normal"
    )

    container.tag_raise(hammer_image_id)

def get_arcade_image_geometry():
    width = max(container.winfo_width(), 1)
    height = max(container.winfo_height(), 1)

    source_width, source_height = arcade_background_source.size

    scale = min(
        width / source_width,
        height / source_height
    )

    image_width = max(1, int(source_width * scale))
    image_height = max(1, int(source_height * scale))

    image_x = (width - image_width) / 2
    image_y = (height - image_height) / 2

    return image_x, image_y, image_width, image_height

def metres_to_canvas(x_m, y_m):
    image_x, image_y, image_width, image_height = get_arcade_image_geometry()

    x_fraction = x_m / ROOM_WIDTH_M
    y_fraction = y_m / ROOM_HEIGHT_M

    back_left_x, back_y = PLAYFIELD_BACK_LEFT
    back_right_x, _ = PLAYFIELD_BACK_RIGHT
    front_left_x, front_y = PLAYFIELD_FRONT_LEFT
    front_right_x, _ = PLAYFIELD_FRONT_RIGHT

    left_x = back_left_x + (
        front_left_x - back_left_x
    ) * y_fraction

    right_x = back_right_x + (
        front_right_x - back_right_x
    ) * y_fraction

    image_fraction_x = left_x + (
        right_x - left_x
    ) * x_fraction

    image_fraction_y = back_y + (
        front_y - back_y
    ) * y_fraction

    canvas_x = image_x + image_fraction_x * image_width
    canvas_y = image_y + image_fraction_y * image_height

    return canvas_x, canvas_y

def canvas_to_metres(px, py):
    image_x, image_y, image_width, image_height = get_arcade_image_geometry()

    image_fraction_x = (px - image_x) / image_width
    image_fraction_y = (py - image_y) / image_height

    back_left_x, back_y = PLAYFIELD_BACK_LEFT
    back_right_x, _ = PLAYFIELD_BACK_RIGHT
    front_left_x, front_y = PLAYFIELD_FRONT_LEFT
    front_right_x, _ = PLAYFIELD_FRONT_RIGHT

    playfield_height = front_y - back_y

    if playfield_height == 0:
        return None

    y_fraction = (
        image_fraction_y - back_y
    ) / playfield_height

    # Mouse is above or below the physical playfield
    if not 0.0 <= y_fraction <= 1.0:
        return None

    left_x = back_left_x + (
        front_left_x - back_left_x
    ) * y_fraction

    right_x = back_right_x + (
        front_right_x - back_right_x
    ) * y_fraction

    # Mouse is outside the left/right edges of the
    # perspective playfield
    if not left_x <= image_fraction_x <= right_x:
        return None

    playfield_width = right_x - left_x

    if playfield_width == 0:
        return None

    x_fraction = (
        image_fraction_x - left_x
    ) / playfield_width

    x_m = x_fraction * ROOM_WIDTH_M
    y_m = y_fraction * ROOM_HEIGHT_M

    return x_m, y_m

def draw_arcade_background():
    global arcade_background_photo

    if arcade_background_source is None or arcade_background_id is None:
        return

    width = max(container.winfo_width(), 1)
    height = max(container.winfo_height(), 1)

    _, _, new_width, new_height = get_arcade_image_geometry()

    resized_image = arcade_background_source.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS
    )

    arcade_background_photo = ImageTk.PhotoImage(resized_image)

    container.coords(
        arcade_background_id,
        width / 2,
        height / 2
    )

    container.itemconfig(
        arcade_background_id,
        image=arcade_background_photo
    )

    container.tag_lower(arcade_background_id)

def redraw_playfield(event=None):
    draw_arcade_background()

    for hole in holes:
        draw_hole(hole)

    draw_mole_sprite()
    draw_hammer_sprite()

    if game_running:
        update_cursor_indicator()

# --------------------------
# Serial Communication (Bluetooth)
#-------------------------

box_port = "COM6" #change to whichever port the bluetooth module is connected to
baud_rate = 115200
box_key = "1" #change to whichever box \

# TODO: calibrate against real measured bench-test readings (mm), once done, replace placeholder values w real readings
# when a person stands at the near edge of the play zone, and the far edge.
sensor_near_mm = 100 # placeholder value, change to real measured reading
sensor_far_mm = 1400 # placeholder value, change to real measured reading

latest_distance_mm = None
distance_lock = threading.Lock()

def serial_thread():
    global latest_distance_mm

    if not serial_available:
        print("pySerial not available. Serial communication disabled.")
        return

    try: 
        ser = serial.Serial(box_port, baud_rate, timeout=1)
        print(f"Connected to {box_port} at {baud_rate} baud.")
    except serial.SerialException as e:
        print(f"Error opening serial port {box_port}: {e}")
        return

    # Prevent warning beeps from playing too quickly in succession
    last_warning_beep = 0.00
    warning_beep_interval = 0.5 # seconds


    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()

            if not line:
                continue

            parts = line.split()
            if parts and parts[0] == "Sent:":
                parts = parts[1:]

            #--------------------------
            # Warning detection
            #--------------------------

            if (
                len(parts) == 2
                and parts[0] in (box_key, f"box{box_key}")
                and parts[1] == "WARNING"
            ):
                print ("WARNING: Player is within 50cm of sensor")

                current_time = time.monotonic()

                if current_time - last_warning_beep >= warning_beep_interval:
                    last_warning_beep = current_time

                    if winsound_available:
                        threading.Thread(
                            target=winsound.Beep,
                            args=(1000, 200),
                            daemon=True
                        ).start()
                continue
        

            if len(parts) == 3 and parts[0] in (box_key, f"box{box_key}") and parts[1] == "DIST":
                try:
                    with distance_lock:
                        latest_distance_mm = int(parts[2])
                except ValueError:
                    pass
        except serial.SerialException:
            print("Lost connection to box")
            break

def distance_to_metres(distance_mm):
    span = sensor_far_mm - sensor_near_mm
    fraction = (distance_mm - sensor_near_mm) / span
    fraction = max(0.0, min(1.0, fraction))
    return fraction * ROOM_HEIGHT_M

def poll_sensor():
    global cursor_x_m, cursor_y_m

    with distance_lock:
        distance = latest_distance_mm 

    if distance is not None and game_running:
        cursor_x_m = ROOM_WIDTH_M / 2
        cursor_y_m = distance_to_metres(distance)

        coord_label.config(text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m (sensor)")
        update_cursor_indicator()
        draw_hammer_sprite()
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
    global arcade_background_source
    global arcade_background_photo
    global arcade_background_id
    global mole_image_source
    global mole_image_photo
    global mole_image_id
    global hammer_image_source
    global hammer_image_photo
    global hammer_image_id
    global hammer_image_size

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

    arcade_background_source = Image.open(
        "Assets/Arcade Machine.png"
    ).convert("RGBA")

    arcade_background_photo = None

    arcade_background_id = container.create_image(
    0,
    0,
    anchor="center"
)

    mole_image_source = Image.open(
        "Assets/Idle mole.png"
    ).convert("RGBA")

    mole_image_photo = None

    mole_image_id = container.create_image(
        0,
        0,
        anchor="s",
        state="hidden"
    )

    hammer_image_source = Image.open(
        "Assets/Hammer.png"
    ).convert("RGBA")

    hammer_image_photo = None
    hammer_image_size = None

    hammer_image_id = container.create_image(
        0,
        0,
        anchor="nw",
        state="hidden"
    )

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

            physical_position = canvas_to_metres(px, py)

            if physical_position is not None:

                cursor_x_m, cursor_y_m = physical_position

                coord_label.config(
                    text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m"
            )

                update_cursor_indicator()
                draw_hammer_sprite()
                check_whack()

    # Check mouse position again in 5 ms
    root.after(5, poll_mouse)
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
    draw_mole_sprite()

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
        draw_mole_sprite()

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
        old_mole = mole
        mole = None
        draw_mole_sprite()

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
        draw_mole_sprite()
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
        draw_mole_sprite()

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
root.after(5, poll_mouse)
root.mainloop()