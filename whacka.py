import tkinter as tk
import random

# -------------------------
# Main Window
# -------------------------

root = tk.Tk()
root.title("Whack-a-Mole")
root.geometry("600x450")
root.resizable(True, True)


# -------------------------
# Game Variables
# -------------------------

score = 0
mole = None
mole_position = None
game_running = False

# Timer IDs
mole_timer = None
next_mole_timer = None

difficulty_settings = {
    "Easy": {
        "up_time": (1000, 1800),
        "wait_time": (800, 1500)
    },

}

current_difficulty = "Easy"

# -------------------------
#Grid tracking
# -------------------------
DESIGN_WIDTH = 600
DESIGN_HEIGHT = 380
ROOM_WIDTH_M = 2.0
ROOM_HEIGHT_M = ROOM_WIDTH_M * (DESIGN_HEIGHT / DESIGN_WIDTH)
GRID_ROWS =  2
GRID_COLS = 3
WHACK_RADISU_M = 0.15
cursor_x_m = 0.0
cursor_y_m = 0.0
def pixel_to_metres (px,py):
    x_m = (px / DESIGN_WIDTH) * ROOM_WIDTH_M
    y_m = (py / DESIGN_HEIGHT) * ROOM_HEIGHT_M
    return x_m, y_m
def get_grid_cell(x_m, y_m):
    col = int(x_m / (ROOM_WIDTH_M / GRID_COLS))
    row = int(y_m / (ROOM_HEIGHT_M / GRID_ROWS))
    col = max (0, min (col, GRID_COLS - 1))
    row = max (0, min (row, GRID_ROWS - 1))
    return row, col
def get_hole_grid_cell(px, py):
    return get_grid_cell (*pixel_to_metres(px, py))
    
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
    global game_running

    current_difficulty = difficulty
    score = 0
    game_running = True

    for widget in root.winfo_children():
        widget.destroy()

    create_game()


# -------------------------
# Create Game
# -------------------------

def create_game():

    global canvas
    global score_label
    global holes

    score_label = tk.Label(
        root,
        text="Score: 0",
        font=("Arial", 18, "bold")
    )
    score_label.pack(pady=5)

    canvas = tk.Canvas(
        root,
        width=DESIGN_WIDTH,
        height=DESIGN_HEIGHT,
        bg="lightgreen"
    )
    canvas.pack()

    holes = [
        (100, 100),
        (300, 100),
        (500, 100),
        (100, 280),
        (300, 280),
        (500, 280)
    ]

    # Draw holes
    for x, y in holes:

        canvas.create_oval(
            x - 45,
            y - 20,
            x + 45,
            y + 20,
            fill="black"
        )

    canvas.bind("<Motion>", track_cursor)

    # Start first mole
    schedule_next_mole()
# -------------------------
#Tracking Cursor
# -------------------------
def track_cursor(event):
    global cursor_x_m, cursor_y_m
    cursor_x_m, cursor_y_m = pixel_to_metres(event.x, event.y)
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
    global mole_position
    global mole_timer

    if not game_running:
        return

    # Safety check:
    # Make sure there isn't already a mole
    if mole is not None:
        return

    # Pick random hole
    mole_position = random.choice(holes)

    x, y = mole_position

    # Create mole
    mole = canvas.create_oval(
        x - 25,
        y - 40,
        x + 25,
        y + 10,
        fill="brown"
    )

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

    # Delete mole
    if mole is not None:

        canvas.delete(mole)
        mole = None

    mole_timer = None

    # Schedule ONE new mole
    schedule_next_mole()


# -------------------------
# Whack Mole
# -------------------------

def check_whack():

    global score
    global mole
    global mole_timer

    # No mole = nothing to hit
    if mole is None:
        return

    mole_x, mole_y = mole_position
    mole_cell = get_hole_grid_cell(mole_x, mole_y)
    cursor_cell = get_grid_cell(cursor_x_m, cursor_y_m)
    # Check whether click hit the mole
    if mole_cell == cursor_cell:


        # Increase score
        score += 1

        score_label.config(
            text="Score: " + str(score)
        )

        # IMPORTANT:
        # Cancel the mole's existing timer
        if mole_timer is not None:

            root.after_cancel(mole_timer)
            mole_timer = None

        # Make mole go down immediately
        canvas.delete(mole)
        mole = None

        # Schedule ONE new mole
        schedule_next_mole()

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
    if root.attributes("-fullscreen"):
        root.attributes("-fullscreen", False)
        return
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
        canvas.delete(mole)
        mole = None

    # Return to start menu
    start_menu()
# -------------------------
# Start
# -------------------------    
start_menu()
root.bind("<Escape>", return_to_menu)
root.bind("<F11>", toggle_fullscreen)
root.mainloop()