# =============================================================================
# ENGG3000 Whack-a-Mole  -  whacka.py  (main game file)
# =============================================================================
# WHAT THE GAME DOES
#   A mole pops up in one of six holes (2 rows x 3 columns). The player whacks it
#   by moving a hammer cursor onto that hole. The cursor is driven by EITHER the
#   ultrasonic sensor boxes (they measure where the player stands in the room)
#   OR the mouse (for testing, whenever no sensor box is connected).
#
# FILES THIS NEEDS (keep them in the same folder)
#   menus.py     all menu screens, the gate transition and the blurred backdrop
#   boxes.py     serial helpers for the sensor boxes (optional: no boxes = mouse mode)
#   Assets/      Arcade Machine.png, Idle mole.png, Mole Hit.png, Hammer.png
#   leaderboard.json is created next to this file the first time a score is saved.
#
# HOW TO READ THIS FILE (top to bottom)
#   1. Settings and game state (score, timers, difficulty, scoring)
#   2. Playfield geometry: the cabinet image, the hole grid, converting positions
#   3. Drawing: holes, mole, hammer, HUD, redrawing when the window is resized
#   4. Sensor input: serial thread, filtering, snapping the player to a hole
#   5. Game flow: menu -> countdown -> round -> game over, plus mouse input
#   6. Start-up code at the very bottom
#
# THREE COORDINATE SYSTEMS (the key idea)
#   metres (cursor_x_m, cursor_y_m)
#       Where the player / cursor is in the real play area. x runs left to right
#       (0 to ROOM_WIDTH_M), y runs front to back (0 to ROOM_HEIGHT_M). Sensors
#       and the mouse are BOTH converted to this, so the game rules never care
#       which one is in use.
#   image fractions (0.0 to 1.0)
#       Positions measured on the cabinet picture, e.g. the PLAYFIELD_* corners
#       and the HUD box positions. Being fractions, they stay correct when the
#       picture is scaled to any window size.
#   canvas pixels
#       Actual positions on screen, obtained from the other two by
#       get_arcade_image_geometry() and metres_to_canvas().
#   If you change the cabinet artwork only the image-fraction numbers need
#   re-measuring (set DEBUG_CALIBRATION = True to see whether they line up).
#
# TIMERS
#   Tk runs everything on one thread, so repeating jobs use root.after(ms, func).
#   The id it returns is kept (mole_timer, round_timer_id, ...) so the job can be
#   cancelled. end_round() and return_to_menu() must cancel every one of them,
#   otherwise a stale timer fires on top of the menu.
import math  # pi, used by the cursor smoothing filter
import os  # builds the path of leaderboard.json
import threading  # background sensor loop and beeps, keeps the window responsive
import tkinter as tk  # the GUI toolkit: window, canvas, labels
import random  # chooses which hole and how long a mole stays up
import statistics  # linear regression, used by trilaterate()
import time  # monotonic clock: reaction timing and sensor frame time
import json  # reads and writes leaderboard.json
import audio
audio.init()
from PIL import Image, ImageTk  # Pillow: load, resize and rotate sprites; convert them for Tk

# Menu screens + backdrop live in menus.py (keep it in the same folder as this file)
from menus import Backdrop, MenuManager

#import guard winsound for non-Windows platforms
# Optional: winsound only exists on Windows and is used to beep when the player stands too close. If
# it cannot be imported the game simply skips the beep.
try: 
    import winsound
    winsound_available = True
except ImportError:
    winsound_available = False

#--------------------------
#Serial import
#-------------------------
# Optional: pyserial and boxes.py talk to the ultrasonic sensor boxes. If they are missing the game
# still runs, controlled by the mouse.
try:
    import serial
    from boxes import BOX_IDS, find_port, open_port
    serial_available = True     
except ImportError:
    serial_available = False

# -------------------------
# Main Window
# -------------------------

root = tk.Tk()  # the main window; every widget lives inside it
root.title("Whack-a-Mole")
root.geometry("960x540") #Size is per pixel (16:9 to match the cabinet art)
root.minsize(640,360)  # smallest size the window can be dragged to
root.resizable(True, True)# Horizontal, Vertical

# -------------------------
# Game Variables
# -------------------------

score = 0  # points this round (reset in start_game)
successful_hits = 0  # moles hit this round; drives difficulty (8 = Medium, 20 = Hard)
mole = None  # hole record the current mole is in, or None if no mole is out
# True only DURING a round (not menus/countdown); most functions do nothing when False
game_running = False

# Timer IDs
mole_timer = None  # after() id: ends the mole's up-time (hide_mole)
next_mole_timer = None  # after() id: the pause before the next mole appears
round_timer_id = None  # after() id: the once-per-second round clock

# -------------------------
# Round Timer
# -------------------------
# Length of a round in seconds. It is also the ceiling the clock can climb back up to when hit
# bonuses are added.
ROUND_DURATION = 60 #Timer in seconds
# Seconds left in the current round. Counts down once a second in tick_round_timer(); the round ends
# at 0.
time_remaining = ROUND_DURATION;
# Seconds added to the clock for every successful hit (never above ROUND_DURATION). Set to 0 for a
# strict countdown.
HIT_TIME_BONUS = 1;

# -------------------------
# Leaderboard System
# -------------------------

# Stored next to this script so the leaderboard is the same wherever the game is launched from
LEADERBOARD_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "leaderboard.json"
)
# How many scores are kept and shown on the leaderboard. The leaderboard screen has room for about 5
# rows.
MAX_LEADERBOARD_ENTRIES = 5

saved_high_score = 0  # best saved score, shown in the cabinet's HIGH SCORE panel


# Reads leaderboard.json and returns a list of {'name': ..., 'score': ...}, best first. A missing or
# corrupt file gives an empty list, so the game never crashes because of it.
def load_leaderboard():
    """Load saved leaderboard scores from the JSON file."""
    try:
        with open(LEADERBOARD_FILE, "r") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return []


# Writes the whole leaderboard list back to leaderboard.json (overwrites the file).
def save_leaderboard(leaderboard):
    """Save leaderboard scores to the JSON file."""
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(leaderboard, file, indent=4)


# Adds one score, sorts best-first, trims to MAX_LEADERBOARD_ENTRIES and saves. Returns the new
# list. Reached from the game-over screen when the player saves their initials.
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


# Re-reads the best saved score into saved_high_score. The HUD's HIGH SCORE box reads that variable,
# so call this after anything changes the leaderboard (this avoids reading the file every time the
# HUD is drawn).
def refresh_high_score():
    """Re-read the best saved score for the HUD."""
    global saved_high_score

    saved_high_score = max(
        (entry.get("score", 0) for entry in load_leaderboard()),
        default=0
    )


# The save callback handed to MenuManager: saves the score, then refreshes the HUD's high score.
def submit_leaderboard_score(player_name, player_score):
    """Used by the game-over menu: save the score, then update the HUD's high score."""
    leaderboard = add_leaderboard_score(player_name, player_score)
    refresh_high_score()
    return leaderboard

# -------------------------
# Difficulty (combo-based)
# -------------------------
# Higher levels make the mole appear for a shorter time, reduce the
# waiting time between moles, and speed up the rise and fall animations.
# Settings for each difficulty level; all times are in milliseconds.
# up_time = (min, max): how long a mole stays up before lowering. Shorter = harder.
# wait_time = (min, max): pause between one mole dropping and the next appearing.
# rise_time / fall_time: how long the pop-up and drop animations take.
# A random value inside each range is chosen every time so the game is not predictable.
difficulty_settings = {
    "Easy": {
        "up_time": (3000, 4000),
        "wait_time": (1100, 1500),
        "rise_time": 350,
        "fall_time": 350
    },
    "Medium": {
        "up_time": (2000, 3000),
        "wait_time": (450, 700),
        "rise_time": 250,
        "fall_time": 250
    },
    "Hard": {
        "up_time": (1000, 2000),
        "wait_time": (250, 450),
        "rise_time": 150,
        "fall_time": 150
    },
}

# ---------------- Combo Difficulty System ----------------
# Tracks consecutive successful hits.
# A higher combo increases the difficulty more quickly.
# Combo 3 = Medium difficulty
# Combo 5 = Hard difficulty
# The combo resets when the player misses a mole.
# -----------------------------------------------------------
combo = 0  # consecutive hits without a miss; reset when a mole times out
current_difficulty = "Easy"  # key into difficulty_settings; set by update_difficulty()


# Chooses the difficulty level from total hits this round and the current combo; whichever condition
# is reached first wins. Change the numbers to make the game ramp up faster or slower.
def update_difficulty():
    global current_difficulty

    if successful_hits >= 20 or combo >= 5:  # Hard: 20 hits this round OR a 5-hit combo
        current_difficulty = "Hard"
    elif successful_hits >= 8 or combo >= 3:  # Medium: 8 hits OR a 3-hit combo
        current_difficulty = "Medium"
    else:
        current_difficulty = "Easy"

    if game_running:
        audio.play_music(current_difficulty)

# -------------------------
# Combo-Based Scoring
# -------------------------
# Higher combos give the player more points.
# Combo 1-2 = 1 point
# Combo 3-4 = 2 points
# Combo 5+ = 3 points

# Combo multiplier applied to every hit's base points (see check_whack): x1 normally, x2 from a
# 3-hit combo, x3 from a 5-hit combo.
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
# The real-world play area, in metres. The cursor is stored in these units so the same code works
# for the mouse and the sensors. The width is split into GRID_COLS columns (one sensor box per
# column); the height is the front-to-back distance the player can stand (it also sets sensor_far_mm
# in the sensor settings).
ROOM_WIDTH_M = 1.5  # left-to-right size of the play area, metres
ROOM_HEIGHT_M = 1.4  # front-to-back depth of the play area, metres
GRID_ROWS =  2  # rows of holes (changing it also needs new art and hole data)
GRID_COLS = 3  # columns of holes = number of sensor boxes
# How close (in metres) the cursor must be to a hole's centre to hit the mole there. Bigger =
# easier. Holes are 0.5 m apart sideways, so values near 0.25 or more would make neighbouring holes
# overlap.
WHACK_RADIUS_M = 0.20 #Radius around the mole for a successful hit
cursor_x_m = 0.0  # hammer position left-to-right, metres (0 = left edge)
cursor_y_m = 0.0  # hammer position front-to-back, metres (0 = back/top row)

# The six hole records, filled in by create_game(). Each is a dict with: row, col, canvas_id (an
# invisible rectangle used for the red cursor outline) and x_m / y_m (the hole's centre in metres).
holes = []  # the six hole records, top row first (filled in by create_game)
# Leftover from an older layout; nothing reads this any more.
DEFAULT_HOLE_PAD = 20  # grid padding at mole_scale == 1.0

# Handles to things on the canvas, and cached images. Tk drops an image from the screen if the
# program does not keep a reference to it, which is why each PhotoImage is stored in a variable.
arcade_background_source = None  # the cabinet PIL image, loaded once in create_game
arcade_background_photo = None  # resized Tk copy currently on screen (must be kept alive)
arcade_background_id = None  # canvas item id of the cabinet image
hud_score_id = None  # canvas item id of the SCORE number
hud_time_id = None  # canvas item id of the TIME number
hud_high_id = None  # canvas item id of the HIGH SCORE number

# Blurred fill drawn behind the cabinet so no blank canvas shows at any aspect ratio
backdrop = None

# Menu manager (created once in create_game, draws full-screen menus on the game canvas)
menus = None

# Set True to outline the playfield and every hole, to check the constants below against the art
DEBUG_CALIBRATION = False

# What the mouse does when the pointer leaves the playfield (mouse control only):
#   False = the pointer is ignored there and the hammer stays where it last was
#           (this is how the game originally behaved).
#   True  = the hammer sticks to the nearest edge of the playfield instead.
MOUSE_CLAMP_TO_PLAYFIELD = False

# Playfield corners as fractions of the arcade cabinet image.
# These define the perspective trapezoid containing the six holes.
# (Measured from the 1672x941 room-and-cabinet art "Assets/Arcade Machine.png".)
# Each corner is (x, y) as a fraction of the cabinet image's width and height (0.0 = left/top edge,
# 1.0 = right/bottom edge). BACK is the far edge of the playfield (top row of holes) and FRONT the
# near edge. The four corners form a trapezoid: every hole, mole and hammer position is placed
# inside it (metres_to_canvas) and mouse positions are mapped back out of it (canvas_to_metres). If
# you change the artwork re-measure these; changing a value shifts where everything is drawn and
# where the mouse lands.
PLAYFIELD_BACK_LEFT = (0.361, 0.486)
PLAYFIELD_BACK_RIGHT = (0.607, 0.486)
PLAYFIELD_FRONT_LEFT = (0.318, 0.656)
PLAYFIELD_FRONT_RIGHT = (0.650, 0.656)

mole_image_source = None  # idle mole PIL image, loaded in create_game
mole_image_photo = None  # Tk copy of the mole currently shown (must be kept alive)
mole_image_id = None  # canvas item id of the mole sprite

mole_hit_image_source = None  # PIL image shown for a moment after the mole is hit

# Resized mole frames, keyed by (is_hit, width, height), so the sprite isn't re-resized every animation step
mole_resize_cache = {}

# The mole is a small state machine:
# "hidden" -> "rising" (animate_mole_rise) -> "active" (fully up; can be hit; hide_mole fires if it
# times out) -> "falling" (animate_mole_fall) -> "hidden".
# A hit moves it from "active" to "hit" (hit sprite shown for MOLE_HIT_DURATION_MS) and then to
# "falling". Only an "active" mole can be hit.
mole_state = "hidden"
# 0.0 = fully hidden, 1.0 = fully out; the sprite is cropped to this height
mole_visible_fraction = 0.0
mole_animation_timer = None  # after() id of the current rise/fall/hit-display step
mole_active_started_at = None  # time the mole became fully up; used to time the reaction
mole_active_duration_ms = 0  # how long this mole stays up (ms), from difficulty_settings


MOLE_HIT_DURATION_MS = 225  # ms the hit sprite is shown before the mole drops
# frames in the rise/fall animation (more = smoother; duration comes from rise_time/fall_time)
MOLE_ANIMATION_STEPS = 12

hammer_image_source = None  # hammer PIL image, loaded in create_game
hammer_image_photo = None  # Tk image of the hammer frame on screen (must be kept alive)
hammer_image_id = None  # canvas item id of the hammer sprite
hammer_image_size = None  # (w, h) the cached frames were built for; rebuilt only if this changes

hammer_frame_photos = []  # pre-rotated frames, one per angle in HAMMER_STRIKE_ANGLES
hammer_frame_index = 0  # which frame is showing (0 = hammer at rest)
hammer_animation_timer = None  # after() id of the current swing step

HAMMER_STRIKE_ANGLES = (0, -10, -22)  # rotation of each frame in degrees (0 = at rest, negative = swung down)
HAMMER_STRIKE_SEQUENCE = (1, 2, 1, 0)  # order the frames play in one swing (indexes into the angles above)
HAMMER_STRIKE_FRAME_MS = 35  # ms each swing frame is shown (lower = snappier swing)

HAMMER_WIDTH_FRACTION = 0.105  # hammer width as a fraction of the IMAGE width (bigger = bigger hammer)

# Position of the striking head within Hammer.png.
# Fine-tune after visually testing the sprite.
# horizontal position of the hammer head inside Hammer.png (0 = left, 1 = right)
HAMMER_STRIKE_X_FRACTION = 0.39
# vertical position of the hammer head inside Hammer.png (0 = top, 1 = bottom)
HAMMER_STRIKE_Y_FRACTION = 0.28

# Converts a pixel position in the canvas to metres by simple proportion (ignores the cabinet image
# and its perspective). Only used by get_hole_grid_cell; gameplay positions use canvas_to_metres
# instead.
def pixel_to_metres (px,py):
    width = max (container.winfo_width(), 1)
    height = max(container.winfo_height(),1)
    x_m = (px / width) * ROOM_WIDTH_M
    y_m = (py / height) * ROOM_HEIGHT_M
    return x_m, y_m
# Which hole cell (row, col) a position in metres falls in: the play area is split evenly into
# GRID_ROWS x GRID_COLS cells, and out-of-range values are clamped into the grid. Decides where the
# red outline goes and keeps moles from spawning under the cursor.
def get_grid_cell(x_m, y_m):
    col = int(x_m / (ROOM_WIDTH_M / GRID_COLS))
    row = int(y_m / (ROOM_HEIGHT_M / GRID_ROWS))
    col = max (0, min (col, GRID_COLS - 1))
    row = max (0, min (row, GRID_ROWS - 1))
    return row, col
# Same as get_grid_cell but starts from canvas pixels.
def get_hole_grid_cell(px, py):
    return get_grid_cell (*pixel_to_metres(px, py))

# Centre of a Tk widget in pixels (leftover helper; not currently used).
def widget_pixel_center(widget):
    return (
        widget.winfo_x() + widget.winfo_width() / 2,
        widget.winfo_y() + widget.winfo_height() / 2
    )

# Returns the on-screen rectangle (x1, y1, x2, y2) of one hole. The centre comes from
# metres_to_canvas; the size grows from the back row to the front row (perspective: nearer holes
# look bigger). The mole sprite is sized from this rectangle and the red cursor outline is drawn on
# it. `scale` multiplies the size (1.0 = matches the art). The two fraction lines are measured from
# the artwork: re-measure them if you change the cabinet image.
def get_hole_bounds(hole, scale):
    centre_x, centre_y = metres_to_canvas(
        hole["x_m"],
        hole["y_m"]
    )

    _, _, image_width, image_height = get_arcade_image_geometry()

    depth_fraction = hole["y_m"] / ROOM_HEIGHT_M

    hole_width_fraction = 0.0689 + (0.0951 - 0.0689) * depth_fraction  # width / image width: 0.0689 at the back row, 0.0951 at the front
    hole_height_fraction = 0.0542 + (0.0840 - 0.0542) * depth_fraction  # height / image height: 0.0542 at the back row, 0.0840 at the front

    hole_width = image_width * hole_width_fraction * scale
    hole_height = image_height * hole_height_fraction * scale

    x1 = centre_x - hole_width / 2
    y1 = centre_y - hole_height / 2
    x2 = centre_x + hole_width / 2
    y2 = centre_y + hole_height / 2

    return x1, y1, x2, y2


# Positions one hole's invisible rectangle (used for the red cursor outline) and keeps it unfilled
# so the hole painted in the cabinet art shows through.
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

# Draws (or hides) the mole for the current mole_state. Steps: hide if there is no visible mole ->
# find the hole's rectangle -> pick the idle or hit image -> resize it to 90% of the hole width ->
# crop it to the visible fraction -> place it so it appears to come out of the hole.
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

    # Resizing images is slow, so each (image, size) is resized once and reused.
    cache_key = (mole_state == "hit", target_width, target_height)
    resized_image = mole_resize_cache.get(cache_key)

    if resized_image is None:
        if len(mole_resize_cache) > 12:
            mole_resize_cache.clear()

        resized_image = source_image.resize(
            (target_width, target_height),
            Image.Resampling.LANCZOS
        )
        mole_resize_cache[cache_key] = resized_image

    visible_fraction = max(
        0.0,
        min(1.0, mole_visible_fraction)
    )

    visible_height = max(
        1,
        int(target_height * visible_fraction)
    )

    # Keep only the top part of the sprite: that is what makes the mole look like it is rising out
    # of the hole.
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

    # The sprite's bottom edge sits a quarter of a hole-height below the hole's centre, so it looks
    # like it is standing inside the hole.
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

# One frame of the mole rising. Repeats (via after()) until MOLE_ANIMATION_STEPS frames are done;
# then the mole becomes "active", its up-time is picked from difficulty_settings and hide_mole is
# scheduled for when that runs out. check_whack() runs once at the end in case the cursor is already
# on this hole.
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


# Starts the drop animation (after a hit, or when the mole times out).
def start_mole_fall():
    global mole_state
    global mole_animation_timer

    if mole is None:
        return

    mole_animation_timer = None
    mole_state = "falling"

    animate_mole_fall(0)


# One frame of the mole dropping back into the hole. When it has finished, the mole is cleared and,
# if the round is still running, the next one is scheduled.
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

# Draws the hammer at the cursor position (hidden outside rounds). The rotated frames are rebuilt
# only when the on-screen size changes (hammer_image_size); each call just picks the frame for
# hammer_frame_index and positions it so the hammer head sits exactly on the cursor.
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

# Begins the swing animation (called when a mole is hit); restarts it if one is already playing.
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


# One step of the swing: shows the next frame from HAMMER_STRIKE_SEQUENCE and schedules the
# following step; returns the hammer to rest at the end.
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

# Where the cabinet image sits on the canvas, as (x, y, width, height) in pixels. The image is
# scaled to fit the window without stretching ('contain') and centred, so there can be empty bars at
# the sides or top/bottom (the blurred backdrop fills those). Everything that must line up with the
# art (holes, HUD, hammer, mouse mapping, READY/SET/GO banner) uses this one function, so the game
# keeps working at any window size or shape.
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

# Converts a position in metres (x across, y depth) to canvas pixels using the PLAYFIELD_*
# trapezoid: y decides how far between the back and front edge, then x is interpolated between that
# row's left and right edge. Used to place holes, moles and the hammer.
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

# The reverse of metres_to_canvas: converts a canvas pixel (the mouse) to metres inside the
# playfield trapezoid. With clamp=False (the default) it returns None when the point is outside the
# playfield, so the mouse is ignored there. With clamp=True the point is pushed to the nearest edge
# instead. poll_mouse passes MOUSE_CLAMP_TO_PLAYFIELD.
def canvas_to_metres(px, py, clamp=False):
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
        if not clamp:
            return None
        y_fraction = max(0.0, min(1.0, y_fraction))

    left_x = back_left_x + (
        front_left_x - back_left_x
    ) * y_fraction

    right_x = back_right_x + (
        front_right_x - back_right_x
    ) * y_fraction

    # Mouse is outside the left/right edges of the
    # perspective playfield
    if not left_x <= image_fraction_x <= right_x:
        if not clamp:
            return None
        image_fraction_x = max(left_x, min(right_x, image_fraction_x))

    playfield_width = right_x - left_x

    if playfield_width == 0:
        return None

    x_fraction = (
        image_fraction_x - left_x
    ) / playfield_width

    x_m = x_fraction * ROOM_WIDTH_M
    y_m = y_fraction * ROOM_HEIGHT_M

    return x_m, y_m

# Redraws the cabinet image at the current window size, then the blurred backdrop behind it. Called
# on every redraw.
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

    # Blurred fill behind the cabinet (covers the whole canvas at any aspect ratio),
    # with the sharp cabinet image sitting directly above it.
    backdrop.draw(container)
    container.tag_raise(arcade_background_id, "backdrop")

# Writes the SCORE, HIGH SCORE and TIME numbers into the cabinet's three display boxes. Positions
# are fractions of the image (re-measure them if you change the art) and the digit size scales with
# the image height. HIGH SCORE shows the best saved score, or the live score once the player beats
# it.
def draw_hud():
    if (
        hud_score_id is None
        or hud_time_id is None
        or hud_high_id is None
    ):
        return

    image_x, image_y, image_width, image_height = (
        get_arcade_image_geometry()
    )

    score_x = image_x + image_width * 0.404  # centre of the SCORE box (fraction of image width)
    score_y = image_y + image_height * 0.338  # height of the SCORE box (fraction of image height)

    high_x = image_x + image_width * 0.484  # centre of the HIGH SCORE box
    high_y = image_y + image_height * 0.338  # height of the HIGH SCORE box

    time_x = image_x + image_width * 0.565  # centre of the TIME box
    time_y = image_y + image_height * 0.338  # height of the TIME box

    # Digit size in points, scaled with the image so the numbers fit their boxes (0.020 = fraction
    # of image height; never below 10).
    font_size = max(
        10,
        int(image_height * 0.020)
    )

    if game_running:
        displayed_time = time_remaining
    else:
        displayed_time = ROUND_DURATION

    # The HIGH SCORE panel shows the best saved score, or the live score once it is beaten
    displayed_high = max(saved_high_score, score)

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
        hud_high_id,
        high_x,
        high_y
    )

    container.itemconfig(
        hud_high_id,
        text=str(displayed_high),
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
    container.tag_raise(hud_high_id)
    container.tag_raise(hud_time_id)

# Development aid, drawn only when DEBUG_CALIBRATION is True: outlines the playfield trapezoid
# (cyan) and every hole (magenta) over the art, so you can check whether the PLAYFIELD_* and hole-
# size numbers match the picture.
def draw_debug_overlay():
    """Outline the playfield trapezoid and every hole, to check the calibration constants."""
    container.delete("debug")

    image_x, image_y, image_width, image_height = get_arcade_image_geometry()

    points = []

    for fraction_x, fraction_y in (
        PLAYFIELD_BACK_LEFT,
        PLAYFIELD_BACK_RIGHT,
        PLAYFIELD_FRONT_RIGHT,
        PLAYFIELD_FRONT_LEFT
    ):
        points.append(image_x + fraction_x * image_width)
        points.append(image_y + fraction_y * image_height)

    container.create_polygon(
        points,
        outline="cyan",
        fill="",
        width=2,
        tags="debug"
    )

    for hole in holes:
        container.create_rectangle(
            *get_hole_bounds(hole, 1.0),
            outline="magenta",
            width=2,
            tags="debug"
        )

# Redraws everything that depends on the window size, in order: cabinet and backdrop, holes, mole,
# hammer, HUD, any open menu, then the optional debug overlay. Runs after a resize (through
# schedule_redraw) and when a round starts.
def redraw_playfield(event=None):
    draw_arcade_background()

    for hole in holes:
        draw_hole(hole)

    draw_mole_sprite()
    draw_hammer_sprite()
    draw_hud()

    if game_running:
        update_cursor_indicator()

    # Keep any open menu in step with the window when it is resized
    if menus is not None:
        menus.render()

    if DEBUG_CALIBRATION:
        draw_debug_overlay()

# Pending after() id of a scheduled redraw, so repeated resize events can cancel it.
redraw_job = None

# Resize events arrive dozens of times a second while the window is dragged, and redrawing the
# cabinet (a large image resize) each time would lag. This waits 30 ms of quiet and then redraws
# once.
def schedule_redraw(event=None):
    """<Configure> fires many times while a window is dragged, so wait for it to settle."""
    global redraw_job

    if redraw_job is not None:
        root.after_cancel(redraw_job)

    redraw_job = root.after(30, redraw_playfield)

# --------------------------
# Serial Communication (Bluetooth)
#-------------------------
# The boxes no longer talk on their own schedule. A box cannot tell its own
# ultrasonic click apart from a neighbour's scattering off the player, so only
# one may listen at a time. The PC does that sequencing here: asking one box,
# waiting for its answer, then asking the next. Unlike time slots on the boxes
# themselves this needs no shared clock - three ESP32s booted at different
# moments never agree on when a slot begins.

# Sensor and serial settings. All distances are in millimetres (mm) as reported by the sensor boxes.
baud_rate = 115200  # serial speed; must match the ESP32 firmware
poll_timeout_s = 0.1   # a box answers well inside this; a missing one costs this much
port_retry_s = 3.0     # don't stall the sweep retrying a box that isn't plugged in

DEAD_ZONE_MM = 600           # spec v2.1: alarm when within 60cm of the screen
BOX_WALL_OFFSET_MM = 0       # how far the boxes sit out from the screen wall - measure and set
WARNING_DISTANCE_MM = DEAD_ZONE_MM - BOX_WALL_OFFSET_MM  # the same limit, as the boxes see it
warning_beep_interval = 0.5  # seconds, stops the beep machine-gunning
COLUMN_STICKINESS_MM = 50  # a new box must be this much closer before the cursor changes column
ROW_HYSTERESIS_M = 0.08  # extra metres the player must move past a row boundary to change rows

sensor_near_mm = WARNING_DISTANCE_MM  # distance that maps to y = 0 m (back/top row of holes)
sensor_far_mm = sensor_near_mm + ROOM_HEIGHT_M * 1000  # distance that maps to y = ROOM_HEIGHT_M; farther readings are ignored
MAX_MISSES = 3  # empty/failed polls in a row before a box counts as seeing nobody
# a reading this far from the last one is a suspected glitch (see settle)
JUMP_MM = 300
CURSOR_STILL_HZ = 1.0  # smoothing when the player is still: lower = steadier but laggier
CURSOR_MOVE_GAIN = 5.0  # how fast smoothing relaxes with speed: higher = quicker catch-up
FRAME_MS = 16  # poll_sensor runs every 16 ms (about 60 times a second)
USE_TRILATERATION = False  # False: x = column of the nearest box. True: estimate x from 2 boxes

latest_by_box = {}       # BOX_ID -> distance in mm, or None when that box sees nobody
pending_by_box = {}  # a reading awaiting confirmation, per box (see settle)
box_links = {box_id: None for box_id in BOX_IDS} if serial_available else {}  # open serial connection (or None) for each box id
distance_lock = threading.Lock()  # guards latest_by_box: the serial thread writes it, the UI reads it
active_box_id = None     # which box currently owns the cursor
last_warning_beep = 0.00  # time of the last beep (for warning_beep_interval)
warning_label = None  # the red TOO CLOSE banner widget, created when first needed


# Reads up to 4 lines from one box looking for '<id> DIST <mm>'. Returns the distance in mm, or None
# on a timeout or garbage. (Negative values mean the box sees nobody; serial_thread turns those into
# None.)
def read_reading(ser, box_id):
    """One DIST reply from this box, or None. Skips WARNING and any stray line."""
    for _ in range(4):
        line = ser.readline()
        if not line:
            return None
        parts = line.decode("utf-8", errors="ignore").split()
        if len(parts) >= 3 and parts[0] == str(box_id) and parts[1] == "DIST":
            try:
                return int(parts[2])
            except ValueError:
                return None
    return None


# Finds and opens the serial port for one box. It runs in its own short-lived thread so a slow port
# search never stalls the polling loop. On failure it schedules a retry after port_retry_s.
def connect_box(box_id, retry_after, connecting):
    port_name = find_port(box_id)
    try:
        if port_name is None:
            raise serial.SerialException("no port answered as this box")
        box_links[box_id] = open_port(port_name, timeout=poll_timeout_s)
        print(f"Box {box_id} connected on {port_name}.")
    except serial.SerialException as e:
        retry_after[box_id] = time.monotonic() + port_retry_s
        print(f"Box {box_id} unavailable on {port_name}: {e}")
    finally:
        connecting.discard(box_id)


# Unique marker meaning 'no reading is waiting for confirmation'. None cannot be used because None
# already means 'this box sees nobody'.
_NOTHING_PENDING = object()


# True if two readings mean the same place: both None, or within JUMP_MM of each other.
def same_spot(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < JUMP_MM


# Glitch filter for one box's new reading. A reading close to the current value is accepted at once,
# and so is a first sighting that another box agrees with. Any other big change must be seen twice
# in a row before it replaces the current value (until then the old value is returned).
def settle(box_id, reading):
    current = latest_by_box.get(box_id)
    pending = pending_by_box.pop(box_id, _NOTHING_PENDING)
    if same_spot(reading, current):
        return reading
    if current is None and reading is not None and any(
            same_spot(reading, d) for b, d in latest_by_box.items()
            if b != box_id and d is not None):
        return reading
    if pending is not _NOTHING_PENDING and same_spot(reading, pending):
        return reading
    pending_by_box[box_id] = reading
    return current


# Smoothing filter ('One Euro'): removes jitter while the player stands still, but responds quickly
# when they move, because the smoothing strength adapts to the speed of movement (see
# CURSOR_STILL_HZ and CURSOR_MOVE_GAIN). One instance is used per axis.
class OneEuroFilter:
    def __init__(self, min_cutoff_hz, speed_gain, deriv_cutoff_hz=1.0):
        self.min_cutoff_hz = min_cutoff_hz
        self.speed_gain = speed_gain
        self.deriv_cutoff_hz = deriv_cutoff_hz
        self.value = None
        self.speed = 0.0

    # How much of the new value to blend in for a given cutoff frequency and time step. A bigger
    # alpha means less smoothing.
    @staticmethod
    def _alpha(cutoff_hz, dt):
        tau = 1 / (2 * math.pi * cutoff_hz)
        return 1 / (1 + tau / dt)

    # Feed in the newest target value and the seconds since the last call; returns the smoothed
    # value.
    def __call__(self, target, dt):
        if self.value is None or dt <= 0:
            self.value = target
            return target
        raw_speed = (target - self.value) / dt
        self.speed += self._alpha(self.deriv_cutoff_hz, dt) * (raw_speed - self.speed)
        cutoff = self.min_cutoff_hz + self.speed_gain * abs(self.speed)
        self.value += self._alpha(cutoff, dt) * (target - self.value)
        return self.value


# The row the cursor is currently snapped to (None before the first reading); used for the row
# hysteresis.
snapped_row = None


# Snaps a raw position to the exact centre of its hole cell, so the hammer jumps between holes
# instead of sliding. Changing row needs ROW_HYSTERESIS_M of extra movement, which stops flicker at
# row boundaries.
def snap_to_hole(x_m, y_m):
    global snapped_row
    row, col = get_grid_cell(x_m, y_m)
    row_h = ROOM_HEIGHT_M / GRID_ROWS
    if snapped_row is not None and row != snapped_row:
        boundary = (snapped_row + (1 if row > snapped_row else 0)) * row_h
        if abs(y_m - boundary) < ROW_HYSTERESIS_M:
            row = snapped_row
    snapped_row = row
    return (col + 0.5) * (ROOM_WIDTH_M / GRID_COLS), (row + 0.5) * row_h


# One smoothing filter per axis for the sensor-driven cursor.
cursor_filter_x = OneEuroFilter(CURSOR_STILL_HZ, CURSOR_MOVE_GAIN)
cursor_filter_y = OneEuroFilter(CURSOR_STILL_HZ, CURSOR_MOVE_GAIN)
# Time of the previous poll_sensor frame, used to work out the time step for the filters.
last_frame_at = time.monotonic()


# Background thread (so serial waits never freeze the window). It loops forever asking each box in
# turn for a distance, because only one box may listen at a time. It reconnects boxes that drop out,
# applies MAX_MISSES and settle(), and stores the results in latest_by_box for poll_sensor to read.
def serial_thread():
    if not serial_available:
        print("pySerial not available. Serial communication disabled.")
        return

    retry_after = {box_id: 0.0 for box_id in BOX_IDS}
    misses = {box_id: 0 for box_id in BOX_IDS}
    connecting = set()

    while True:
        for box_id in BOX_IDS:
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

            reading = settle(box_id, reading if reading is not None and reading >= 0 else None)
            with distance_lock:
                latest_by_box[box_id] = reading

        time.sleep(0.01)   # nothing answered: don't spin the CPU


# Converts a sensor distance (mm) to a depth in metres in the play area: 0 at sensor_near_mm up to
# ROOM_HEIGHT_M at sensor_far_mm, clamped to that range.
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


# Self-checks for pick_box, run at start-up. If one fails the game stops with an error, meaning an
# edit broke the box-selection logic.
assert pick_box({}, None) is None
assert pick_box({1: 900, 2: 800}, None) == 2   # nobody owns it yet: nearest wins
assert pick_box({1: 900, 2: 870}, 1) == 1
assert pick_box({1: 900, 2: 800}, 1) == 2
assert pick_box({1: 900, 2: 800}, 3) == 2      # owner dropped out: nearest wins


# True if box 1 is physically on the RIGHT of the play area, so box order is mirrored relative to
# the on-screen columns. Flip this if the cursor moves left when the player steps right.
MIRROR_BOXES = True


# Horizontal position (mm) of a box's column centre across the play area.
def box_x_mm(box_id):
    column = GRID_COLS + 1 - box_id if MIRROR_BOXES else box_id
    return (column - 0.5) * (ROOM_WIDTH_M / GRID_COLS) * 1000


# Estimates the player's (x, y) in mm from the distances seen by the anchor box and its immediate
# neighbours (circle intersection solved with a straight-line fit). Returns None when no consistent
# answer exists. Only used when USE_TRILATERATION is True.
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


# Test helper: the distances each box WOULD read for a player standing at (x, y). Used by the self-
# checks below.
def _ranges_to(x, y):
    return {k: round(((x - box_x_mm(k)) ** 2 + y * y) ** 0.5) for k in (1, 2, 3)}


# Self-checks for trilaterate, run at start-up. A failure here means the sensor maths was broken by
# an edit.
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

    # Created the first time it is needed (and recreated if it was ever destroyed).
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


# Runs every FRAME_MS. Each frame: (1) copy the latest box readings, (2) show or hide the TOO CLOSE
# alarm, (3) choose the box that owns the cursor, (4) convert its distance to a position, snap it to
# a hole and smooth it, (5) move the hammer and check for a hit. The cursor is only moved while a
# round is running.
def poll_sensor():
    global cursor_x_m, cursor_y_m, active_box_id, last_frame_at

    now = time.monotonic()
    dt, last_frame_at = now - last_frame_at, now

    with distance_lock:
        seen = {box_id: d for box_id, d in latest_by_box.items()
                if d is not None and d <= sensor_far_mm}

    proximity_alarm(game_running and in_dead_zone(seen))

    box_id = pick_box(seen, active_box_id)
    if box_id is not None and game_running:
        active_box_id = box_id
        spot = trilaterate(seen, box_id) if USE_TRILATERATION else None
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

        target_x, target_y = snap_to_hole(target_x, target_y)
        cursor_x_m = cursor_filter_x(target_x, dt)
        cursor_y_m = cursor_filter_y(target_y, dt)

        coord_label.config(text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m ({source})")
        update_cursor_indicator()
        draw_hammer_sprite()
        check_whack()

    root.after(FRAME_MS, poll_sensor)

# -------------------------
# Menu state helpers
# -------------------------
# The menus are full-screen scenes drawn on the one game canvas (see menus.py),
# so going to a menu no longer destroys the game screen. These helpers put the
# playfield back into its idle look first.

# Removes the red outline from every hole.
def clear_cursor_indicator():
    for hole in holes:
        container.itemconfig(
            hole["canvas_id"],
            outline="",
            width=0
        )


# Puts the playfield into its idle look just before a menu appears: refreshes the high score,
# removes any banner and outline, hides the hammer and redraws the HUD.
def enter_menu_state():
    refresh_high_score()
    menus.clear_banner()
    clear_cursor_indicator()
    draw_hammer_sprite()   # hides the hammer because game_running is False
    draw_hud()


# -------------------------
# Start Menu
# -------------------------

# Shows the home menu. Also cancels any countdown still running (by bumping countdown_token).
def start_menu():

    global game_running
    global countdown_token

    game_running = False
    countdown_token += 1   # cancels a countdown still ticking

    enter_menu_state()
    menus.show_home()

# -------------------------
# Start Game
# -------------------------

# Begins a new round. Resets score, combo and hits, then plays the gate transition. When the gates
# are shut the menu is swapped for the playfield (covered), when they open the READY/SET/GO
# countdown runs, and then begin_round() starts the round. `difficulty` is the starting level
# (normally "Easy"; it then changes with combo and hits).
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

    refresh_high_score()

    def covered():
        # The gates have shut over the menu: swap it for the playfield behind them
        menus.hide()
        redraw_playfield()

    # Gates close -> covered() -> gates open -> countdown
    menus.transition(covered, lambda: show_countdown(begin_round))

# -------------------------
# Countdown
# -------------------------
# Bumped whenever a countdown starts or is cancelled. A running countdown stops itself if its own
# token is out of date (for example Esc was pressed).
countdown_token = 0

# Shows READY, SET, GO! (700 ms each) and then calls on_complete. Stops quietly if it was cancelled.
def show_countdown(on_complete):
    global countdown_token

    countdown_token += 1
    token = countdown_token

    sequence = [ "READY", "SET", "GO!"]
    def show_word(index):
        # If the player escaped back to the menu mid-countdown (or started a new
        # game), this countdown is stale - bail out instead of carrying on.
        if token != countdown_token:
            return
        if index >= len(sequence):
            menus.clear_banner()
            on_complete()
            return
        menus.banner(sequence[index])
        root.after(700, lambda:show_word(index +1))
    show_word(0)
                   
                        
# -------------------------
# Begin Round (after the countdown)
# -------------------------
# Starts the round itself: sets the clock, schedules the first mole and starts the one-second timer.
def begin_round():
    global game_running, time_remaining, round_timer_id
    game_running = True
    time_remaining = ROUND_DURATION
    schedule_next_mole()
    update_cursor_indicator()
    round_timer_id = root.after(1000, tick_round_timer)
    audio.play_music(current_difficulty)
# -------------------------
# Create Game
# -------------------------
# Runs once at startup now: the canvas, sprites and menus all persist.

def create_game():

    global container
    global score_label
    global timer_label
    global coord_label
    global holes
    global arcade_background_source
    global arcade_background_photo
    global arcade_background_id
    global backdrop
    global menus
    global hud_score_id
    global hud_time_id
    global hud_high_id
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

    # These two labels are never displayed (they are never packed) but other functions still update
    # them. They are kept so that code keeps working.
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

    # THE game canvas. Everything (backdrop, cabinet, holes, sprites, HUD, menus) is drawn on it.
    # The dark background colour is what shows if the picture does not cover everything.
    container = tk.Canvas(root, bg="#14110d", highlightthickness=0)
    container.pack(fill=tk.BOTH, expand=True)

    # Blurred copy of the cabinet art drawn behind it to fill any empty window space.
    backdrop = Backdrop("Assets/Arcade Machine.png")

    # The menu system (menus.py). The game gives it callbacks rather than it importing the game: how
    # to start a game, read the scores and save a score.
    menus = MenuManager(
        container,
        get_arcade_image_geometry,
        on_start=lambda: start_game("Easy"),
        get_scores=load_leaderboard,
        submit_score=submit_leaderboard_score,
        max_entries=MAX_LEADERBOARD_ENTRIES
    )

    # Load the images ONCE here (not every round). File names are case-sensitive on some systems, so
    # match the Assets folder exactly.
    arcade_background_source = Image.open(
        "Assets/Arcade Machine.png"
    ).convert("RGBA")

    arcade_background_photo = None

    arcade_background_id = container.create_image(
    0,
    0,
    anchor="center"
)

    # Text items for the three HUD numbers. Their position, size and colour are set in draw_hud().
    hud_score_id = container.create_text(
        0,
        0,
        text="0",
        fill="#F5A623",
        anchor="center"
    )

    hud_high_id = container.create_text(
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

    menus.mole_source = mole_image_source   # shown peeking out of a hole on the home screen

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

    # Build the six hole records, top row first. x_m / y_m are the hole centres in metres: the
    # middle of each grid cell.
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

    # Small debug read-out of the cursor position in metres (bottom-left of the window).
    coord_label = tk.Label(
        container,
        text="x=0.00m, y=0.00m",
        bg="#14110d",
        fg="white",
        font=("Arial", 12, "bold")
    )
    coord_label.place(relx=0.01, rely=0.98, anchor="sw")

    # Redraw (debounced) whenever the window changes size.
    container.bind("<Configure>", schedule_redraw)
    root.after(0, redraw_playfield)

    update_cursor_indicator()

# -------------------------
#Tracking Cursor
# -------------------------
# Mouse control, used only when NO sensor box is connected. Runs every 5 ms during a round: converts
# the pointer to a position in the playfield (canvas_to_metres) and moves the cursor there. Outside
# the playfield the pointer is ignored, unless MOUSE_CLAMP_TO_PLAYFIELD is True.
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

            physical_position = canvas_to_metres(
                px,
                py,
                clamp=MOUSE_CLAMP_TO_PLAYFIELD
            )

            # If the pointer is over the mole sprite itself, treat it as being on that hole's
            # centre. This makes the mole easier to hit with the mouse.
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

# Waits a random time (the wait_time range for the current difficulty) and then calls show_mole.
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

# Picks a random hole, never the one the cursor is on, and starts the mole rising.
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

# Called when an active mole's up-time runs out without it being hit: breaks the combo, recalculates
# the difficulty, then the mole falls.
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

# Decides whether the cursor is hitting the mole. It runs whenever the cursor moves and when a mole
# finishes rising. A hit needs an ACTIVE mole and the cursor within WHACK_RADIUS_M of the hole
# centre. Points: the base score depends on reaction speed (how much of the mole's up-time was used)
# and is multiplied by the combo multiplier. A hit also adds the time bonus, raises combo and hit
# count, swings the hammer and shows the hit sprite.
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
        if reaction_fraction <= 0.25:  # hit within the first quarter of the up-time
            points_earned = 100
        elif reaction_fraction <= 0.50:  # within the first half
            points_earned = 75
        elif reaction_fraction <= 0.75:  # within the first three quarters
            points_earned = 50
        else:
            points_earned = 25

        successful_hits += 1

        # Increase combo after a consecutive successful hit
        combo += 1

        # Increase the remaining time by the hit time bonus, but do not exceed the maximum round duration
        time_remaining = min(ROUND_DURATION, time_remaining + HIT_TIME_BONUS)

        # Combo multiplies the reaction-time points (x1, x2, x3)
        score += points_earned * get_hit_points()

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
        audio.play_whack()
        # Show the hit sprite before the mole falls
        mole_state = "hit"
        mole_visible_fraction = 1.0

        draw_mole_sprite()

        mole_animation_timer = root.after(
            MOLE_HIT_DURATION_MS,
            start_mole_fall
        )

# Draws a thick red outline round the hole the cursor is over and removes it from the others. Only
# during a round.
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
# Runs once a second during a round: counts the clock down and ends the round at zero.
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
    
# Stops the round: cancels every timer, clears the mole, then shows the game-over screen. Anything
# that could still fire after the round must be cancelled here, or it would run on top of the menu.
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
    audio.stop_music()
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
# The game-over screen (score, rank, initials entry, buttons) is a full-screen
# menu drawn by menus.py.
# Hands over to the full-screen game-over menu with the final score.
def show_game_over():
    enter_menu_state()
    menus.show_game_over(score)

# Leftover helper that refreshes the debug read-out with the grid cell; it is not scheduled anywhere
# at the moment.
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
# F11: switches between fullscreen and windowed.
def toggle_fullscreen(event=None):
    is_full = root.attributes("-fullscreen")
    root.attributes("-fullscreen", not is_full)
# -------------------------
# Return to Menu
# -------------------------

# Esc: abandons the current round (cancelling every timer, as end_round does) and shows the home
# menu. No score is saved.
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
    audio.stop_music()
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
# START-UP (everything below runs once when the program launches)
# Start the sensor-reading thread. It is a daemon thread, so it ends when the window closes.
bt_thread = threading.Thread(target=serial_thread, daemon=True)
bt_thread.start() 

# Build the canvas, images and menus once, then show the home menu.
create_game()
start_menu()
# Keyboard shortcuts: Esc = back to the menu, F11 = fullscreen.
root.bind("<Escape>", return_to_menu)
root.bind("<F11>", toggle_fullscreen)

# Start the two input loops: sensors and mouse. The mouse loop does nothing while a sensor box is
# connected.
root.after(50, poll_sensor)
root.after(5, poll_mouse)
# Hand control to Tk. From here the game runs entirely from the scheduled callbacks above.
root.mainloop()

