"""Live view of what each sensor box sees, laid over the game grid.

Bench tool, like bt_test.py: run it instead of the game to see why the cursor
goes where it does. `py sensor_view.py` uses USB (and shows each box's two
sensors separately); `py sensor_view.py --bt` uses Bluetooth only.

The room numbers below are copied from whacka.py - keep them in step.
"""
import threading
import time
import tkinter as tk

import serial

from boxes import BOX_IDS, find_port, open_port

ROOM_WIDTH_M = 1.5
ROOM_HEIGHT_M = 1.4
GRID_ROWS = 2
GRID_COLS = 3
WARNING_DISTANCE_MM = 600
SENSOR_FAR_MM = WARNING_DISTANCE_MM + ROOM_HEIGHT_M * 1000
MIRROR_BOXES = True

SCALE = 300              # pixels per metre
PAD = 40
W = int(ROOM_WIDTH_M * SCALE) + 2 * PAD
H = int(ROOM_HEIGHT_M * SCALE) + 2 * PAD + 110

# BOX_ID -> {"dist": mm or -1, "d1": mm, "d2": mm, "port": str, "at": time of last reply}
state = {b: {"dist": None, "d1": None, "d2": None, "port": None, "at": 0.0} for b in BOX_IDS}
lock = threading.Lock()


def parse(line):
    """"2 DIST 750" over Bluetooth, "2 DIST 750  (d1=740 d2=760)" over USB."""
    parts = line.split()
    if len(parts) < 3 or parts[1] != "DIST" or not parts[0].isdigit():
        return None
    try:
        out = {"box": int(parts[0]), "dist": int(parts[2])}
    except ValueError:
        return None
    for p in parts[3:]:
        key, _, val = p.strip("()").partition("=")
        if key in ("d1", "d2") and val.lstrip("-").isdigit():
            out[key] = int(val)
    return out


def poll_thread():
    links = {}
    while True:
        for b in BOX_IDS:
            if b not in links:
                port = find_port(b)
                if port is None:
                    continue
                try:
                    links[b] = open_port(port, timeout=0.2)
                except serial.SerialException:
                    continue
                with lock:
                    state[b]["port"] = port
            ser = links[b]
            try:
                ser.reset_input_buffer()
                ser.write(b"?")    # one box at a time, same as the game
                reading = parse(ser.readline().decode("utf-8", errors="ignore"))
            except serial.SerialException:
                ser.close()
                del links[b]
                with lock:
                    state[b]["port"] = None
                continue
            if reading and reading["box"] == b:
                with lock:
                    state[b].update(reading, at=time.monotonic())
        time.sleep(0.01)


def mm_to_y_m(mm):
    """Same mapping as whacka.distance_to_metres."""
    fraction = (mm - WARNING_DISTANCE_MM) / (SENSOR_FAR_MM - WARNING_DISTANCE_MM)
    return max(0.0, min(1.0, fraction)) * ROOM_HEIGHT_M


def box_x_m(b):
    """Same as whacka.box_x_mm, in metres."""
    column = GRID_COLS + 1 - b if MIRROR_BOXES else b
    return (column - 0.5) * ROOM_WIDTH_M / GRID_COLS


def px(x_m, y_m):
    return PAD + x_m * SCALE, PAD + y_m * SCALE


def draw():
    canvas.delete("all")
    col_w = ROOM_WIDTH_M / GRID_COLS
    row_h = ROOM_HEIGHT_M / GRID_ROWS

    with lock:
        snap = {b: dict(s) for b, s in state.items()}
    now = time.monotonic()
    # What the game counts as "seen": a real reading inside the play area.
    seen = {b: s["dist"] for b, s in snap.items()
            if s["dist"] is not None and 0 <= s["dist"] <= SENSOR_FAR_MM and now - s["at"] < 1}
    winner = min(seen, key=seen.get) if seen else None

    if winner is not None:
        row = min(int(mm_to_y_m(seen[winner]) / row_h), GRID_ROWS - 1)
        x0, y0 = px(box_x_m(winner) - col_w / 2, row * row_h)
        canvas.create_rectangle(x0, y0, x0 + col_w * SCALE, y0 + row_h * SCALE,
                                fill="#ffe08a", outline="")

    for r in range(GRID_ROWS + 1):
        canvas.create_line(*px(0, r * row_h), *px(ROOM_WIDTH_M, r * row_h), fill="#888")
    for c in range(GRID_COLS + 1):
        canvas.create_line(*px(c * col_w, 0), *px(c * col_w, ROOM_HEIGHT_M), fill="#888")
    canvas.create_text(W / 2, PAD - 25, text="SCREEN WALL (boxes here)", fill="#555")

    for i, b in enumerate(BOX_IDS):
        s = snap[b]
        cx = box_x_m(b)
        bx, by = px(cx, 0)
        canvas.create_rectangle(bx - 14, by - 12, bx + 14, by + 2, fill="#444")
        canvas.create_text(bx, by - 5, text=str(b), fill="white")

        stale = now - s["at"] > 1
        if b in seen:
            ex, ey = px(cx, mm_to_y_m(seen[b]))
            colour = "#d33" if b == winner else "#36c"
            canvas.create_line(bx, by + 2, ex, ey, fill=colour, width=3)
            canvas.create_oval(ex - 9, ey - 9, ex + 9, ey + 9, fill=colour, outline="")

        if s["port"] is None:
            status = "not connected"
        elif stale:
            status = f"{s['port']}: no reply"
        elif s["dist"] is None or s["dist"] < 0:
            status = f"{s['port']}: sees nothing"
        elif s["dist"] > SENSOR_FAR_MM:
            status = f"{s['port']}: {s['dist']} mm (beyond play area - ignored)"
        else:
            status = f"{s['port']}: {s['dist']} mm" + ("  <- GAME USES THIS" if b == winner else "")
        if s["d1"] is not None and not stale:
            status += f"   [d1={s['d1']}  d2={s['d2']}]"
        canvas.create_text(PAD, H - 95 + i * 22, anchor="w", text=f"Box {b}  {status}",
                           font=("Consolas", 10))

    root.after(100, draw)


root = tk.Tk()
root.title("Sensor view")
canvas = tk.Canvas(root, width=W, height=H, bg="white")
canvas.pack()
threading.Thread(target=poll_thread, daemon=True).start()
draw()
root.mainloop()
