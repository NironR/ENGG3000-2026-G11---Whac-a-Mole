import threading
import tkinter as tk
import random

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
mole_position = None
game_running = False

# Timer IDs
mole_timer = None
next_mole_timer = None

difficulty_settings = {
    "Easy": {
        "up_time": (600, 1200), # Longer number will make mole stay up longer
        "wait_time": (400, 900) # How fast mole will appear
    },

}

current_difficulty = "Easy"

# -------------------------
#Grid tracking
# -------------------------
DESIGN_WIDTH = 600
DESIGN_HEIGHT = 380
ROOM_WIDTH_M = 1.5
ROOM_HEIGHT_M = 1.4
GRID_ROWS =  2
GRID_COLS = 3
WHACK_RADIUS_M = 0.1501
cursor_x_m = 0.0
cursor_y_m = 0.0
HOLE_LAYOUT_FRACTIONS= [
     (1/6,1/4),
     (3/6, 1/4),
     (5/6, 1/4),
     (1/6, 3/4),
     (3/6, 3/4),
     (5/6, 3/4),

]
holes = []
hole_radius_x=45
hole_radius_y=20
mole_radius_x = 25
mole_radius_y_up = 40
mole_radius_y_down = 10
last_canvas_size = (0,0)

def pixel_to_metres (px,py):
    width = max (canvas.winfo_width(), 1)
    height = max(canvas.winfo_height(),1)
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

# --------------------------
# Serial Communication (Bluetooth)
#-------------------------

box_port = "COM6" #change to whichever port the bluetooth module is connected to
baud_rate = 115200
box_key = "box1" #change to whichever box \

# TODO: calibrate against real measured bench-test readings (mm), once done, replace placeholder values w real readings
# when a person stands at the near edge of the play zone, and the far edge.
sensor_near_mm = 100 # placeholder value, change to real measured reading
sensor_far_mm = 1400 # placeholder value, change to real measured reading

latest_distance_mm = None
distance_lock = threading.Lock()

    
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
    global coord_label

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
        bg="lightgreen",
        highlightthickness=0
    )
    canvas.pack(fill=tk.BOTH, expand=True)

    coord_label = canvas.create_text(
        10,10,
        anchor="sw",
        text="x=0.00m, y=0.00m",
        fill="black",
        font=("Arial", 12, "bold")
    )
        


    canvas.bind("<Motion>", track_cursor)
    canvas.bind("<Configure>", on_canvas_resize)

    # Start first mole
    schedule_next_mole()
    
# -------------------------
#Resize
# -------------------------    
def layout_hole():
    global holes, hole_radius_x, hole_radius_y
    global mole_radius_x, mole_radius_y_up, mole_radius_y_down
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    if width <= 50 or height <= 50:
        return
    
    scale = min (width/ DESIGN_WIDTH, height / DESIGN_HEIGHT)
    hole_radius_x = 45*scale
    hole_radius_y = 20*scale
    mole_radius_x = 25*scale
    mole_radius_y_up = 40*scale
    mole_radius_y_down = 10*scale
    canvas.delete("hole")
    holes = []
    for fx,fy in HOLE_LAYOUT_FRACTIONS:
        x = fx*width
        y = fy*height
        holes.append((x,y))
        canvas.create_oval(
            x-hole_radius_x,
            y - hole_radius_y,
            x+hole_radius_x,
            y+hole_radius_y,
            fill = "black",
            tags="hole"
            )
        canvas.coords(coord_label, 10, height -10)
        canvas.tag_raise(coord_label)
def on_canvas_resize(event):
    global last_canvas_size, mole, mole_timer, next_mole_timer
    new_size = (event.width, event.height)
    if new_size == last_canvas_size:
        return
    last_canvas_size = new_size
    
    if mole is not None:
        canvas.delete(mole)
        mole = None
        
    if mole_timer is not None:
        root.after_cancel(mole_timer)
        mole_timer = None
    if next_mole_timer is not None:
        root.after_cancel(next_mole_timer)
        next_mole_timer = None
    layout_hole()
    if game_running:
        schedule_next_mole()
# -------------------------
#Tracking Cursor
# -------------------------
def track_cursor(event):
    global cursor_x_m, cursor_y_m
    cursor_x_m, cursor_y_m = pixel_to_metres(event.x, event.y)
    canvas.itemconfig(coord_label, text=f"x={cursor_x_m:.2f}m y={cursor_y_m:.2f}m")
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
    if not holes:
        schedule_next_mole()
        return
    # Pick random hole
    mole_position = random.choice(holes)

    x, y = mole_position

    # Create mole
    mole = canvas.create_oval(
        x - mole_radius_x,
        y - mole_radius_y_up,
        x+mole_radius_x,
        y+mole_radius_y_down,
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
    mole_x_m, mole_y_m = pixel_to_metres(mole_x,mole_y)
    dx = cursor_x_m - mole_x_m
    dy = cursor_y_m - mole_y_m
    distance_m = (dx*dx+dy*dy)**0.5
    if distance_m <= WHACK_RADIUS_M:
    # Check whether click hit the mole
    


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
