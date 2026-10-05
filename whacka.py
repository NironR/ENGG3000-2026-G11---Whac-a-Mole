import threading
import tkinter as tk
import random
import statistics
import time
import json
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
    from boxes import BOX_BT_ADDRS, find_port
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
successful_hits = 0
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
time_remaining = ROUND_DURATION;
HIT_TIME_BONUS = 1;

# -------------------------
# Leaderboard System
# -------------------------

LEADERBOARD_FILE = "leaderboard.json"
MAX_LEADERBOARD_ENTRIES = 5


def load_leaderboard():
    """Load saved leaderboard scores from the JSON file."""
    try:
        with open(LEADERBOARD_FILE, "r") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_leaderboard(leaderboard):
    """Save leaderboard scores to the JSON file."""
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(leaderboard, file, indent=4)


def add_leaderboard_score(player_name, player_score):
    """Add a new score and keep only the top five results."""

    leaderboard = load_leaderboard()

    leaderboard.append({
        "name": player_name,
        "score": player_score
    })

    # Highest score appears first
    leaderboard.sort(
        key=lambda entry: entry["score"],
        reverse=True
    )

    # Keep only the top five scores
    leaderboard = leaderboard[:MAX_LEADERBOARD_ENTRIES]

    save_leaderboard(leaderboard)

    return leaderboard

def display_leaderboard(parent):
    """Display the current top five leaderboard."""

    leaderboard = load_leaderboard()

    tk.Label(
        parent,
        text="TOP 5 LEADERBOARD",
        font=("Arial", 16, "bold")
    ).pack(pady=(15, 5))

    if not leaderboard:
        tk.Label(
            parent,
            text="No scores yet",
            font=("Arial", 12)
        ).pack()

        return

    for position, entry in enumerate(leaderboard, start=1):

        tk.Label(
            parent,
            text=f"{position}. {entry['name']} - {entry['score']}",
            font=("Arial", 12)
        ).pack()

# -------------------------
# Difficulty (combo-based)
# -------------------------
# Higher levels make the mole appear for a shorter time, reduce the
# Higher levels make the mole appear for a shorter time, reduce the
# waiting time between moles, and speed up the rise and fall animations.
difficulty_settings = {
    "Easy": {
        "up_time": (900, 1200),
        "wait_time": (700, 1000),
        "rise_time": 180,
        "fall_time": 160
    },
    "Medium": {
        "up_time": (600, 900),
        "wait_time": (450, 700),
        "rise_time": 145,
        "fall_time": 130
    },
    "Hard": {
        "up_time": (350, 600),
        "wait_time": (250, 450),
        "rise_time": 115,
        "fall_time": 105
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

    if successful_hits >= 20 or combo >= 5:
        current_difficulty = "Hard"
    elif successful_hits >= 8 or combo >= 3:
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
WHACK_RADIUS_M = 0.20 #Radius around the mole for a successful hit
cursor_x_m = 0.0
cursor_y_m = 0.0

holes = []  # hole Label widgets, in the same 2x3 order HOLE_LAYOUT_FRACTIONS used to define
DEFAULT_HOLE_PAD = 20  # grid padding at mole_scale == 1.0

arcade_background_source = None
arcade_background_photo = None
arcade_background_id = None
hud_score_id = None
hud_time_id = None

# Playfield corners as fractions of the arcade cabinet image.
# These define the perspective trapezoid containing the six holes.
PLAYFIELD_BACK_LEFT = (0.228, 0.504)
PLAYFIELD_BACK_RIGHT = (0.775, 0.504)
PLAYFIELD_FRONT_LEFT = (0.130, 0.675)
PLAYFIELD_FRONT_RIGHT = (0.871, 0.675)

mole_image_source = None
mole_image_photo = None
mole_image_id = None

mole_hit_image_source = None

mole_state = "hidden"
mole_visible_fraction = 0.0
mole_animation_timer = None
mole_active_started_at = None
mole_active_duration_ms = 0


MOLE_HIT_DURATION_MS = 225
MOLE_ANIMATION_STEPS = 12

hammer_image_source = None
hammer_image_photo = None
hammer_image_id = None
hammer_image_size = None

hammer_frame_photos = []
hammer_frame_index = 0
hammer_animation_timer = None

HAMMER_STRIKE_ANGLES = (0, -10, -22)
HAMMER_STRIKE_SEQUENCE = (1, 2, 1, 0)
HAMMER_STRIKE_FRAME_MS = 35

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

    if (
        mole is None
        or mole_state == "hidden"
        or mole_visible_fraction <= 0.0
    ):
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

    if mole_state == "hit":
        source_image = mole_hit_image_source
    else:
        source_image = mole_image_source

    source_width, source_height = source_image.size

    target_height = max(
        1,
        int(
            target_width *
            source_height /
            source_width
        )
    )

    resized_image = source_image.resize(
        (target_width, target_height),
        Image.Resampling.LANCZOS
    )

    visible_fraction = max(
        0.0,
        min(1.0, mole_visible_fraction)
    )

    visible_height = max(
        1,
        int(target_height * visible_fraction)
    )

    cropped_image = resized_image.crop(
        (
            0,
            0,
            target_width,
            visible_height
        )
    )

    mole_image_photo = ImageTk.PhotoImage(
        cropped_image
    )

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

def animate_mole_rise(step=0):
    global mole_state
    global mole_visible_fraction
    global mole_animation_timer
    global mole_timer
    global mole_active_started_at
    global mole_active_duration_ms

    if not game_running or mole is None:
        return

    if step >= MOLE_ANIMATION_STEPS:
        mole_state = "active"
        mole_visible_fraction = 1.0
        mole_animation_timer = None

        draw_mole_sprite()

        min_time, max_time = difficulty_settings[
            current_difficulty
        ]["up_time"]

        time_up = random.randint(
            min_time,
            max_time
        )

        mole_active_started_at = time.monotonic()
        mole_active_duration_ms = time_up

        mole_timer = root.after(
            time_up,
            hide_mole
        )

        check_whack()
        return

    mole_state = "rising"

    progress = (
        (step + 1) /
        MOLE_ANIMATION_STEPS
    )

    # Smooth the movement so the mole does not rise
    # in visibly equal, mechanical steps.
    mole_visible_fraction = (
        progress * progress * (3 - 2 * progress)
    )

    draw_mole_sprite()

    rise_duration = difficulty_settings[
        current_difficulty
    ]["rise_time"]

    frame_delay = max(
        1,
        rise_duration //
        MOLE_ANIMATION_STEPS
    )

    mole_animation_timer = root.after(
        frame_delay,
        lambda: animate_mole_rise(step + 1)
    )


def start_mole_fall():
    global mole_state
    global mole_animation_timer

    if mole is None:
        return

    mole_animation_timer = None
    mole_state = "falling"

    animate_mole_fall(0)


def animate_mole_fall(step=0):
    global mole
    global mole_state
    global mole_visible_fraction
    global mole_animation_timer

    if mole is None:
        return

    if step >= MOLE_ANIMATION_STEPS:
        mole = None
        mole_state = "hidden"
        mole_visible_fraction = 0.0
        mole_animation_timer = None

        draw_mole_sprite()

        if game_running:
            schedule_next_mole()

        return

    mole_state = "falling"

    progress = (
        step /
    MOLE_ANIMATION_STEPS
    )

    smooth_progress = (
        progress * progress * (3 - 2 * progress)
    )

    mole_visible_fraction = (
        1.0 - smooth_progress
    )

    draw_mole_sprite()

    fall_duration = difficulty_settings[
        current_difficulty
    ]["fall_time"]

    frame_delay = max(
        1,
        fall_duration //
        MOLE_ANIMATION_STEPS
    )

    mole_animation_timer = root.after(
        frame_delay,
        lambda: animate_mole_fall(step + 1)
    )

def draw_hammer_sprite():
    global hammer_image_photo
    global hammer_image_size
    global hammer_frame_photos

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

    target_size = (
        target_width,
        target_height
    )

    # Rebuild the cached hammer frames only when
    # the displayed hammer size changes.
    if hammer_image_size != target_size:
        resized_image = hammer_image_source.resize(
            target_size,
            Image.Resampling.LANCZOS
        )

        strike_centre = (
            target_width * HAMMER_STRIKE_X_FRACTION,
            target_height * HAMMER_STRIKE_Y_FRACTION
        )

        hammer_frame_photos = []

        for angle in HAMMER_STRIKE_ANGLES:
            rotated_image = resized_image.rotate(
                angle,
                resample=Image.Resampling.BICUBIC,
                center=strike_centre
            )

            hammer_frame_photos.append(
                ImageTk.PhotoImage(rotated_image)
            )

        hammer_image_size = target_size

    if not hammer_frame_photos:
        return

    frame_index = max(
        0,
        min(
            hammer_frame_index,
            len(hammer_frame_photos) - 1
        )
    )

    active_photo = hammer_frame_photos[
        frame_index
    ]

    if hammer_image_photo is not active_photo:
        hammer_image_photo = active_photo

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

def start_hammer_strike():
    global hammer_animation_timer
    global hammer_frame_index

    if hammer_animation_timer is not None:
        root.after_cancel(
            hammer_animation_timer
        )
        hammer_animation_timer = None

    hammer_frame_index = 0

    animate_hammer_strike()


def animate_hammer_strike(step=0):
    global hammer_frame_index
    global hammer_animation_timer

    if not game_running:
        hammer_frame_index = 0
        hammer_animation_timer = None
        return

    if step >= len(HAMMER_STRIKE_SEQUENCE):
        hammer_frame_index = 0
        hammer_animation_timer = None

        draw_hammer_sprite()
        return

    hammer_frame_index = HAMMER_STRIKE_SEQUENCE[
        step
    ]

    draw_hammer_sprite()

    hammer_animation_timer = root.after(
        HAMMER_STRIKE_FRAME_MS,
        lambda: animate_hammer_strike(
            step + 1
        )
    )

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

def draw_hud():
    if (
        hud_score_id is None
        or hud_time_id is None
    ):
        return

    image_x, image_y, image_width, image_height = (
        get_arcade_image_geometry()
    )

    score_x = image_x + image_width * 0.291
    score_y = image_y + image_height * 0.350

    time_x = image_x + image_width * 0.710
    time_y = image_y + image_height * 0.350

    font_size = max(
        10,
        int(image_height * 0.024)
    )

    if game_running:
        displayed_time = time_remaining
    else:
        displayed_time = ROUND_DURATION

    container.coords(
        hud_score_id,
        score_x,
        score_y
    )

    container.itemconfig(
        hud_score_id,
        text=str(score),
        fill="#F5A623",
        font=("Impact", font_size)
    )

    container.coords(
        hud_time_id,
        time_x,
        time_y
    )

    container.itemconfig(
        hud_time_id,
        text=str(displayed_time),
        fill = "#F5A623",
        font=("Impact", font_size)
    )

    container.tag_raise(hud_score_id)
    container.tag_raise(hud_time_id)

def redraw_playfield(event=None):
    draw_arcade_background()

    for hole in holes:
        draw_hole(hole)

    draw_mole_sprite()
    draw_hammer_sprite()
    draw_hud()

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

baud_rate = 115200
poll_timeout_s = 0.1   # a box answers well inside this; a missing one costs this much
port_retry_s = 3.0     # don't stall the sweep retrying a box that isn't plugged in

DEAD_ZONE_MM = 600           # spec v2.1: alarm when within 60cm of the screen
BOX_WALL_OFFSET_MM = 0       # how far the boxes sit out from the screen wall - measure and set
WARNING_DISTANCE_MM = DEAD_ZONE_MM - BOX_WALL_OFFSET_MM  # the same limit, as the boxes see it
warning_beep_interval = 0.5  # seconds, stops the beep machine-gunning
COLUMN_STICKINESS_MM = 150   # another box must be this much closer to steal the column

sensor_near_mm = WARNING_DISTANCE_MM
sensor_far_mm = sensor_near_mm + ROOM_HEIGHT_M * 1000
CURSOR_SMOOTHING = 0.4
MAX_MISSES = 3

latest_by_box = {}       # BOX_ID -> distance in mm, or None when that box sees nobody
box_links = {box_id: None for box_id in BOX_BT_ADDRS} if serial_available else {}
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
                return int(parts[2])
            except ValueError:
                return None
    return None


def connect_box(box_id, retry_after, connecting):
    port_name = find_port(box_id)
    try:
        if port_name is None:
            raise serial.SerialException("not paired with this PC")
        box_links[box_id] = serial.Serial(port_name, baud_rate, timeout=poll_timeout_s)
        print(f"Box {box_id} connected on {port_name}.")
    except serial.SerialException as e:
        retry_after[box_id] = time.monotonic() + port_retry_s
        print(f"Box {box_id} unavailable on {port_name}: {e}")
    finally:
        connecting.discard(box_id)


def serial_thread():
    if not serial_available:
        print("pySerial not available. Serial communication disabled.")
        return

    retry_after = {box_id: 0.0 for box_id in BOX_BT_ADDRS}
    misses = {box_id: 0 for box_id in BOX_BT_ADDRS}
    connecting = set()

    while True:
        for box_id in BOX_BT_ADDRS:
            if box_links[box_id] is None:
                if box_id not in connecting and time.monotonic() >= retry_after[box_id]:
                    connecting.add(box_id)
                    threading.Thread(target=connect_box, args=(box_id, retry_after, connecting),
                                     daemon=True).start()
                continue

            try:
                ser = box_links[box_id]
                ser.reset_input_buffer()
                ser.write(b"?")        # any byte means "your turn"
                reading = read_reading(ser, box_id)
            except serial.SerialException:
                print(f"Lost box {box_id} - will retry")
                try:
                    box_links[box_id].close()
                except Exception:
                    pass
                box_links[box_id] = None
                retry_after[box_id] = time.monotonic() + port_retry_s
                reading = None
                misses[box_id] = MAX_MISSES

            if reading is None:
                misses[box_id] += 1
                if misses[box_id] < MAX_MISSES:
                    continue
            else:
                misses[box_id] = 0

            with distance_lock:
                latest_by_box[box_id] = reading if reading is not None and reading >= 0 else None

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


def box_x_mm(box_id):
    return (box_id - 0.5) * (ROOM_WIDTH_M / GRID_COLS) * 1000


def trilaterate(seen, anchor_id):
    anchor_x = box_x_mm(anchor_id)
    # Only the anchor's neighbours: two objects in front of boxes 1 and 3 would
    ids = [k for k in seen
           if k == anchor_id
           or (abs(k - anchor_id) == 1
               and abs(seen[k] - seen[anchor_id]) < abs(box_x_mm(k) - anchor_x))]
    if len(ids) < 2:
        return None
    slope, intercept = statistics.linear_regression(
        [box_x_mm(k) for k in ids],
        [seen[k] ** 2 - box_x_mm(k) ** 2 for k in ids],
    )
    x = -slope / 2
    if intercept < x * x:
        return None
    return x, (intercept - x * x) ** 0.5


def _ranges_to(x, y):
    return {k: round(((x - box_x_mm(k)) ** 2 + y * y) ** 0.5) for k in (1, 2, 3)}


_spot = trilaterate(_ranges_to(500, 1300), 1)                   
assert abs(_spot[0] - 500) < 5 and abs(_spot[1] - 1300) < 5
_spot = trilaterate({**_ranges_to(500, 1300), 1: 550}, 2)       
assert abs(_spot[0] - 500) < 5 and abs(_spot[1] - 1300) < 5
assert trilaterate({2: 1300}, 2) is None                          
assert trilaterate({1: 550, 2: 1300}, 2) is None                  
assert trilaterate({1: 565, 2: 2210, 3: 545}, 3) is None          


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
        seen = {box_id: d for box_id, d in latest_by_box.items()
                if d is not None and d <= sensor_far_mm}

    # Alarm is a safety feature - it fires whether or not a game is running.
    proximity_alarm(in_dead_zone(seen))

    box_id = pick_box(seen, active_box_id)
    if box_id is not None and game_running:
        active_box_id = box_id
        spot = trilaterate(seen, box_id)
        if spot is not None:
            # Two or more boxes see you: their distances pin down x as well as y.
            target_x = max(0.0, min(ROOM_WIDTH_M, spot[0] / 1000))
            target_y = distance_to_metres(spot[1])
            source = "trilateration"
        else:
            # is how far down the grid you are.
            target_x = box_x_mm(box_id) / 1000
            target_y = distance_to_metres(seen[box_id])
            source = f"box {box_id}"

        cursor_x_m += CURSOR_SMOOTHING * (target_x - cursor_x_m)
        cursor_y_m += CURSOR_SMOOTHING * (target_y - cursor_y_m)

        coord_label.config(text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m ({source})")
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
    global successful_hits

    current_difficulty = difficulty
    score = 0
    combo = 0
    successful_hits = 0
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
    global game_running, time_remaining, time_remaining, rounder_timer_id
    game_running = True
    time_remaining = ROUND_DURATION
    schedule_next_mole()
    update_cursor_indicator()
    rounder_timer_id = root.after(1000, tick_round_timer)
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
    global hud_score_id
    global hud_time_id
    global mole_image_source
    global mole_image_photo
    global mole_image_id
    global mole_hit_image_source
    global hammer_image_source
    global hammer_image_photo
    global hammer_image_id
    global hammer_image_size
    global hammer_frame_photos
    global hammer_frame_index
    global hammer_animation_timer

    score_label = tk.Label(
        root,
        text="Score: 0 | Combo: 0 | Level: Easy",
        font=("Arial", 18, "bold")
    )
    timer_label = tk.Label(
        root,
        text=f"Time: {ROUND_DURATION}s",
        font=("arial", 14, "bold")
    )

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

    hud_score_id = container.create_text(
        0,
        0,
        text="0",
        fill="#F5A623",
        anchor="center"
    )

    hud_time_id = container.create_text(
        0,
        0,
        text=str(ROUND_DURATION),
        fill="#F5A623",
        anchor="center"
    )

    mole_image_source = Image.open(
        "Assets/Idle mole.png"
    ).convert("RGBA")

    mole_hit_image_source = Image.open(
        "Assets/Mole Hit.png"
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
    hammer_frame_photos = []
    hammer_frame_index = 0
    hammer_animation_timer = None
    hammer_image_id = container.create_image(
        0,
        0,
        anchor="nw",
        state="hidden"
    )

    holes = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
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
                "canvas_id": canvas_id,
                "x_m": (c + 0.5) * (ROOM_WIDTH_M / GRID_COLS),
                "y_m": (r + 0.5) * (ROOM_HEIGHT_M / GRID_ROWS)
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

    sensors_connected = any(link is not None for link in box_links.values())

    if game_running and not sensors_connected:

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

            if mole is not None and mole_image_id in container.find_overlapping(px, py, px, py):
                physical_position = (mole["x_m"], mole["y_m"])

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
    global mole_state
    global mole_visible_fraction

    if not game_running:
        return

    # Safety check:
    # Make sure there isn't already a mole
    if mole is not None:
        return

    if not holes:
        schedule_next_mole()
        return

    # Pick random hole; never spawns under player grid.
    cursor_cell = get_grid_cell(cursor_x_m, cursor_y_m)
    mole = random.choice([
        h for h in holes
        if (h["row"], h["col"]) != cursor_cell
    ])

    mole_state = "rising"
    mole_visible_fraction = 0.0
    mole_timer = None

    animate_mole_rise()

# -------------------------
# Hide Mole
# -------------------------

def hide_mole():
    global mole_timer
    global combo

    if mole is None:
        return

    if mole_state != "active":
        return

    # If the mole disappears without being hit,
    # the player's combo is broken
    combo = 0

    # Recalculate difficulty after combo is reset
    update_difficulty()

    # Update the display
    score_label.config(
        text=f"Score: {score} | Combo: {combo} | Level: {current_difficulty}"
    )

    draw_hud()

    mole_timer = None

    start_mole_fall()


# -------------------------
# Whack Mole
# -------------------------

def check_whack():

    global score
    global combo
    global mole
    global mole_timer
    global mole_state
    global mole_visible_fraction
    global mole_animation_timer
    global successful_hits
    global mole_active_started_at
    global mole_active_duration_ms
    global time_remaining

    # Only a fully raised, active mole can be hit
    if mole is None or mole_state != "active":
        return

    mole_x_m = mole["x_m"]
    mole_y_m = mole["y_m"]
    dx = cursor_x_m - mole_x_m
    dy = cursor_y_m - mole_y_m
    distance_m = (dx*dx+dy*dy)**0.5

    if distance_m <= WHACK_RADIUS_M:
        # Check how quickly the active mole was hit.
        elapsed_ms = (
            time.monotonic() -
            mole_active_started_at
        ) * 1000

        if mole_active_duration_ms > 0:
            reaction_fraction = (
                elapsed_ms /
                mole_active_duration_ms
            )
        else:
            reaction_fraction = 1.0

        reaction_fraction = max(
            0.0,
            min(1.0, reaction_fraction)
        )

        # Faster hits award more points.
        if reaction_fraction <= 0.25:
            points_earned = 100
        elif reaction_fraction <= 0.50:
            points_earned = 75
        elif reaction_fraction <= 0.75:
            points_earned = 50
        else:
            points_earned = 25

        score += points_earned * get_hit_points()
        successful_hits += 1

        # Increase combo after a consecutive successful hit
        combo += 1

        # Increase the remaining time by the hit time bonus, but do not exceed the maximum round duration
        time_remaining = min(ROUND_DURATION, time_remaining + HIT_TIME_BONUS)

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

        draw_hud()

        # IMPORTANT:
        # Cancel the mole's existing timer
        if mole_timer is not None:
            root.after_cancel(mole_timer)
            mole_timer = None

        start_hammer_strike()

        # Show the hit sprite before the mole falls
        mole_state = "hit"
        mole_visible_fraction = 1.0

        draw_mole_sprite()

        mole_animation_timer = root.after(
            MOLE_HIT_DURATION_MS,
            start_mole_fall
        )

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
    time_remaining -= 1
    timer_label.config(text=f"Time: {time_remaining}s")
    draw_hud()
    if time_remaining <= 0:
        end_round()
        return
    round_timer_id = root.after(1000, tick_round_timer)
    
def end_round():
    global game_running
    global mole
    global mole_timer
    global next_mole_timer
    global round_timer_id
    global mole_animation_timer
    global mole_state
    global mole_visible_fraction
    global hammer_animation_timer
    global hammer_frame_index

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

    if mole_animation_timer is not None:
        root.after_cancel(mole_animation_timer)
        mole_animation_timer = None

    if hammer_animation_timer is not None:
        root.after_cancel(hammer_animation_timer)
        hammer_animation_timer = None

    hammer_frame_index = 0

    if mole is not None:
        mole = None
        mole_state = "hidden"
        mole_visible_fraction = 0.0
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
    ).pack(pady=(20, 10))

    tk.Label(
        root,
        text=f"Final Score: {score}",
        font=("Arial", 20)
    ).pack(pady=5)

    # -------------------------
    # Player name entry
    # -------------------------

    tk.Label(
        root,
        text="Enter your name:",
        font=("Arial", 12)
    ).pack(pady=(10, 2))

    name_entry = tk.Entry(
        root,
        font=("Arial", 14),
        width=20
    )
    name_entry.pack(pady=5)

    message_label = tk.Label(
        root,
        text="",
        font=("Arial", 11)
    )
    message_label.pack()

    leaderboard_frame = tk.Frame(root)
    leaderboard_frame.pack()

    # Show scores already saved
    display_leaderboard(leaderboard_frame)

    def submit_score():

        player_name = name_entry.get().strip()

        if not player_name:
            message_label.config(
                text="Please enter a name."
            )
            return

        add_leaderboard_score(
            player_name,
            score
        )

        message_label.config(
            text="Score saved!"
        )

        # Stop the same score being submitted multiple times
        name_entry.config(state="disabled")
        save_button.config(state="disabled")

        # Refresh leaderboard
        for widget in leaderboard_frame.winfo_children():
            widget.destroy()

        display_leaderboard(leaderboard_frame)

    save_button = tk.Button(
        root,
        text="Save Score",
        font=("Arial", 12),
        command=submit_score
    )
    save_button.pack(pady=5)

    tk.Button(
        root,
        text="Play Again",
        font=("Arial", 16),
        width=15,
        command=lambda: start_game("Easy")
    ).pack(pady=5)

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
    global mole_animation_timer
    global mole_state
    global mole_visible_fraction
    global hammer_animation_timer
    global hammer_frame_index

    # Stop the game
    game_running = False

    # Cancel existing timers
    if mole_timer is not None:
        root.after_cancel(mole_timer)
        mole_timer = None

    if round_timer_id is not None:
        root.after_cancel(round_timer_id)
        round_timer_id = None

    if next_mole_timer is not None:
        root.after_cancel(next_mole_timer)
        next_mole_timer = None

    if mole_animation_timer is not None:
        root.after_cancel(mole_animation_timer)
        mole_animation_timer = None

    if hammer_animation_timer is not None:
        root.after_cancel(hammer_animation_timer)
        hammer_animation_timer = None

    hammer_frame_index = 0

    if mole is not None:
        mole = None
        mole_state = "hidden"
        mole_visible_fraction = 0.0
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