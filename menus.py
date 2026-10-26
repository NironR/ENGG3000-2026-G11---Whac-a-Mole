"""
menus.py (v3) - FULL-SCREEN menu screens plus a gate transition, drawn on the game canvas.

Screens: home, leaderboard, how to play, game over (with initials entry). Each one
covers the whole window (radial-gradient background, hazard-stripe bars top and
bottom, content scaled to the window). The home screen uses a two-column layout on
wide windows and a stacked one on tall windows.

transition(on_covered, on_done): two hazard-striped gates slide shut over whatever
is on screen, on_covered() runs while the screen is hidden (swap menu for game
here), then the gates slide open and on_done() runs.

Navigation: mouse, or Up/Down + Enter. move()/activate() are public so the
ultrasonic cursor can drive the menus later (e.g. dwell-to-select).

No dependency on the game file: the game passes callbacks in.
"""
import time
import tkinter as tk
from PIL import Image, ImageTk, ImageFilter, ImageEnhance

# Colours (hex RGB) used by every screen. Change these to re-theme the menus.
AMBER = "#FFB81C"  # main accent: titles, borders, button outline and highlight
ORANGE = "#FF8A1F"  # secondary accent: small headings
RED = "#FF6A1A"  # GAME OVER title and error messages
DARK = "#14110d"  # near-black: button fill, panels, gaps between stripes
GATE = "#1a1610"  # colour of the transition gates
PANEL_BG = "#1e1912"  # leaderboard row background
CREAM = "#FFE9B8"  # normal text
DIM = "#C9A55A"  # muted text (hints, high score)
DISPLAY = "Impact"   # same face as the in-game HUD; falls back to a default font if missing
BODY = "Arial"  # font for small body text
NAME_LENGTH = 3  # characters accepted in the initials box

# Gate transition timing, in milliseconds. Larger numbers = a slower, heavier transition. The whole
# start-of-game delay is CLOSE + HOLD + OPEN.
TRANSITION_CLOSE_MS = 380  # time for the gates to slide shut
TRANSITION_HOLD_MS = 70  # pause while fully shut (the menu-to-game swap happens here)
TRANSITION_OPEN_MS = 420  # time for the gates to slide open
TRANSITION_FRAME_MS = 15  # delay between animation frames (15 ms is about 66 per second)

# Edit freely; keep in sync with the game rules.
# Each string is one bullet point on the HOW TO PLAY screen (long lines wrap automatically). Keep
# them in step with the real game rules.
HELP_TIPS = [
    "Step up to a hole to aim. Your position moves the hammer.",
    "Whack a mole while it is up. Faster hits score more (100 down to 25).",
    "Chain hits for a combo: x2 from 3 in a row, x3 from 5.",
    "Every hit adds 1 second to the clock. A miss resets your combo.",
    "Stay at least 60 cm from the screen or the game will warn you.",
]


# Blurred, darkened copy of the cabinet picture used to fill any empty window space around the
# (letterboxed) cabinet. The game draws it behind the sharp cabinet image; it is not part of the
# menus themselves but lives here so both can share it.
class Backdrop:
    """
    Fills a canvas of ANY shape with a darkened, blurred, 'cover'-scaled copy of
    the cabinet art. Draw it behind the sharp, letterboxed cabinet image so the
    leftover space never shows as blank canvas.
    """

    # Loads the picture and pre-blurs a tiny copy of it. brightness 1.0 leaves it unchanged; lower
    # is darker (0.65 matches the room lighting).
    def __init__(self, path, brightness=0.65):
        source = Image.open(path).convert("RGB")
        small_w = 96   # blur at a tiny size: cheap, and upscaling looks smooth
        small_h = max(1, int(small_w * source.height / source.width))
        small = source.resize((small_w, small_h), Image.Resampling.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(3))
        self.small = ImageEnhance.Brightness(small).enhance(brightness)
        self.photo = None
        self._size = None

    # (Re)draws the fill at the canvas's current size: scales the tiny blurred image up to cover the
    # whole canvas, crops the overflow and puts it at the very bottom of the stacking order. The
    # result is cached per size, so calling it repeatedly is cheap.
    def draw(self, canvas, tag="backdrop"):
        w = max(canvas.winfo_width(), 1)
        h = max(canvas.winfo_height(), 1)
        if self._size != (w, h):
            sw, sh = self.small.size
            scale = max(w / sw, h / sh)              # cover: fill, then crop
            nw, nh = int(sw * scale) + 1, int(sh * scale) + 1
            img = self.small.resize((nw, nh), Image.Resampling.BICUBIC)
            left, top = (nw - w) // 2, (nh - h) // 2
            self.photo = ImageTk.PhotoImage(img.crop((left, top, left + w, top + h)))
            self._size = (w, h)
        items = canvas.find_withtag(tag)
        if items:
            canvas.itemconfig(items[0], image=self.photo)
            canvas.coords(items[0], 0, 0)
        else:
            canvas.create_image(0, 0, anchor="nw", image=self.photo, tags=tag)
        canvas.tag_lower(tag)


# Draws and runs every menu screen on the game canvas. Create ONE instance (the game does this in
# create_game). Then call show_home / show_leaderboard / show_help / show_game_over to open a
# screen, hide() to remove it, render() when the window is resized, transition() for the gate
# animation and banner() for READY/SET/GO.
class MenuManager:
    def __init__(self, canvas, get_rect, on_start, get_scores, submit_score, max_entries=5):
        """
        canvas                     -> the game canvas (shared with the game)
        get_rect()                 -> (x, y, w, h) of the cabinet image (used for the READY/SET/GO banner)
        on_start()                 -> begin a new game
        get_scores()               -> list of {"name":..., "score":...}, best first
        submit_score(name, score)  -> save a score
        """
        self.canvas = canvas
        self.get_rect = get_rect
        self.on_start = on_start
        self.get_scores = get_scores
        self.submit_score = submit_score
        self.max_entries = max_entries

        self.mole_source = None        # optional PIL RGBA image shown on the home screen
        self.clock = time.monotonic    # replaceable, for testing

        self.visible = False  # True while a menu screen is on the canvas
        self.transitioning = False  # True while the gates are moving (input is ignored)
        self.screen = "home"  # which screen: "home", "scores", "help" or "over"
        self.buttons = []  # clickable buttons on this screen: dicts of label, action, rect
        self.selected = 0  # index of the highlighted button (keyboard or hover)

        self.final_score = 0  # score shown on the game-over screen
        self.rank = 0  # 1-based place this score would take on the leaderboard
        self.qualifies = False  # True if the score is good enough to enter the top N
        self.new_high = False  # True if the score beats the best saved one
        self.saved = False  # True once initials were saved (hides the entry box)
        self.message = ""  # error text shown under the initials box
        self.entry = None  # the Tk Entry widget for initials (created on first use)
        self.entry_text = tk.StringVar(master=canvas)  # holds whatever is typed in the initials box
        self.entry_text.trace_add("write", self._clean_initials)

        self._w = self._h = 1  # canvas size at the last render
        self._bg_photo = None  # cached gradient background image
        self._bg_size = None  # the size that cached background was built for
        self._mole_photo = None  # cached resized mole picture for the home screen
        self._mole_key = None  # the size that mole picture was built for
        self._tr_token = 0  # bumped to cancel a transition that is in progress
        self._gate_off = 0.0  # how far the gates have travelled so far (pixels)
        self._gate_dist = 0.0  # total distance each gate travels to meet in the middle

        # Mouse hover/click and keyboard navigation. Every handler does nothing unless a menu is
        # visible, so these never affect gameplay.
        canvas.bind("<Motion>", self._on_motion, add="+")
        canvas.bind("<Button-1>", self._on_click, add="+")
        canvas.bind("<Up>", lambda e: self.move(-1), add="+")
        canvas.bind("<Down>", lambda e: self.move(1), add="+")
        canvas.bind("<Return>", lambda e: self.activate(), add="+")

    # ----- public API -------------------------------------------------

    # Opens the home screen.
    def show_home(self):
        self._open("home")

    # Opens the leaderboard screen.
    def show_leaderboard(self):
        self._open("scores")

    # Opens the how-to-play screen.
    def show_help(self):
        self._open("help")

    # Opens the game-over screen for `score`. First works out the rank, whether the score qualifies
    # for the leaderboard and whether it is a new high score (before anything is saved).
    def show_game_over(self, score):
        scores = self.get_scores()
        self.final_score = score
        self.saved = False
        self.message = ""
        self.entry_text.set("")
        self.rank = 1 + sum(1 for e in scores if e.get("score", 0) > score)
        self.qualifies = score > 0 and (
            len(scores) < self.max_entries
            or score > min(e.get("score", 0) for e in scores)
        )
        self.new_high = score > 0 and self.rank == 1
        self._open("over")

    # Removes the menu from the canvas. A running transition's gates are left alone so they can
    # finish.
    def hide(self):
        self.visible = False
        self.buttons = []
        self.canvas.delete("menu")
        self.canvas.config(cursor="")

    def render(self):
        """Redraw the screen. Call this from the game's own redraw so both resize together."""
        if not self.visible:
            return
        c = self.canvas
        w, h = max(c.winfo_width(), 1), max(c.winfo_height(), 1)
        self._w, self._h = w, h
        c.delete("menu")
        before = set(c.find_all())

        # Layers, bottom to top: gradient background, hazard-stripe bars, the current screen's
        # contents, then its buttons.
        self._background(c, w, h)
        band = h * 0.035
        self._stripes(0, 0, w, band)
        self._stripes(0, h - band, w, band)

        # `ph` is the usable height between the two stripe bars. Most sizes below are fractions of
        # it, so everything scales with the window.
        top, ph = band, h - 2 * band          # usable area between the stripe bars
        # `cw` is the width of the content column on the single-column screens. It is capped
        # relative to the height so rows and buttons do not stretch absurdly wide on ultra-wide
        # windows.
        cw = min(w * 0.86, ph * 1.25)         # content width for the single-column screens
        self.buttons = []
        draw = {"home": self._draw_home, "scores": self._draw_scores,
                "help": self._draw_help, "over": self._draw_over}[self.screen]
        draw(c, w / 2, top, ph, cw)
        self._draw_buttons(c, ph)

        for item in set(c.find_all()) - before:
            c.addtag_withtag("menu", item)
        c.tag_raise("menu")
        c.tag_raise("banner")
        c.tag_raise("gate")

    # Gate animation. The two gates slide shut over whatever is on screen, on_covered() runs while
    # it is hidden (the game swaps menu for playfield there), then the gates slide open and
    # on_done() runs. A new transition or any screen change cancels one in progress.
    def transition(self, on_covered, on_done=None):
        """Gates close over the screen -> on_covered() -> gates open -> on_done()."""
        self._cancel_transition()
        self.transitioning = True
        self._tr_token += 1
        token = self._tr_token
        c = self.canvas
        self._build_gates(max(c.winfo_width(), 1), max(c.winfo_height(), 1))

        # One animation frame; it re-schedules itself until the phase ends. `t` is progress from 0
        # to 1 measured by the clock (so the speed does not depend on frame rate) and `eased` makes
        # it start and finish gently.
        def run(phase, started):
            if token != self._tr_token:       # cancelled (e.g. Esc pressed)
                return
            duration = TRANSITION_CLOSE_MS if phase == "close" else TRANSITION_OPEN_MS
            t = min(1.0, (self.clock() - started) * 1000.0 / duration)
            eased = t * t * (3 - 2 * t)
            self._set_gates(eased if phase == "close" else 1.0 - eased)
            if t < 1.0:
                c.after(TRANSITION_FRAME_MS, lambda: run(phase, started))
            elif phase == "close":
                on_covered()
                c.tag_raise("gate")
                c.after(TRANSITION_HOLD_MS, lambda: run("open", self.clock()))
            else:
                self._end_transition()
                if on_done is not None:
                    on_done()

        run("close", self.clock())

    # Big centred word drawn on the playfield, used for READY / SET / GO!
    def banner(self, text):
        """Big centred word on the playfield, e.g. READY / SET / GO!"""
        c = self.canvas
        c.delete("banner")
        ix, iy, iw, ih = self.get_rect()
        x, y, size = ix + iw * 0.5, iy + ih * 0.60, ih * 0.10
        self._text(c, x, y + size * 0.06, text, size, "#8A2F00", tags="banner")
        self._text(c, x, y, text, size, AMBER, tags="banner")
        c.tag_raise("banner")
        c.tag_raise("gate")

    # Removes the READY/SET/GO word.
    def clear_banner(self):
        self.canvas.delete("banner")

    # Moves the highlight by `step` buttons (-1 = up, +1 = down), wrapping round at the ends. Public
    # so the sensor cursor can drive the menus later.
    def move(self, step):
        if self.visible and not self.transitioning and self.buttons:
            self.selected = (self.selected + step) % len(self.buttons)
            self._paint_buttons()

    # Presses the highlighted button (same as clicking it).
    def activate(self):
        if self.visible and not self.transitioning and self.buttons:
            self.buttons[self.selected]["action"]()

    # ----- plumbing ---------------------------------------------------

    # Shared by every show_* method: cancels any transition, switches to the new screen, draws it
    # and gives the canvas keyboard focus.
    def _open(self, screen):
        self._cancel_transition()
        self.screen = screen
        self.selected = 0
        self.visible = True
        self.render()
        self.canvas.focus_set()
        if self.screen == "over" and self._entry_visible():
            self.entry.focus_set()

    # Runs on every keystroke in the initials box: upper-cases, keeps letters and digits only and
    # trims to NAME_LENGTH characters.
    def _clean_initials(self, *_):
        text = self.entry_text.get()
        cleaned = "".join(ch for ch in text.upper() if ch.isalnum())[:NAME_LENGTH]
        if cleaned != text:
            self.entry_text.set(cleaned)

    # True while the initials box should be on screen.
    def _entry_visible(self):
        return (self.entry is not None and self.entry.winfo_exists()
                and self.qualifies and not self.saved)

    # Returns the index of the button under the point (x, y), or None.
    def _hit(self, x, y):
        for i, b in enumerate(self.buttons):
            bx0, by0, bx1, by1 = b["rect"]
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return i
        return None

    # Mouse moved: highlight the button underneath and show a hand cursor over buttons.
    def _on_motion(self, event):
        if not self.visible or self.transitioning:
            return
        i = self._hit(event.x, event.y)
        if i is not None and i != self.selected:
            self.selected = i
            self._paint_buttons()
        self.canvas.config(cursor="hand2" if i is not None else "")

    # Mouse clicked: run the action of the button under the pointer.
    def _on_click(self, event):
        if not self.visible or self.transitioning:
            return
        self.canvas.focus_set()
        i = self._hit(event.x, event.y)
        if i is not None:
            self.selected = i
            self.buttons[i]["action"]()   # may start a transition or replace the screen; touch nothing after

    # ----- transition gates ------------------------------------------

    # Creates the two gate doors just off-screen (left and right). Each door is a dark panel with a
    # hazard-striped edge that faces the middle. Everything is tagged "gate" (plus "gateL" or
    # "gateR") so it can be moved or deleted as a group.
    def _build_gates(self, w, h):
        c = self.canvas
        door = w / 2 + 2
        self._gate_dist = w / 2 + 1       # how far each door travels to meet in the middle
        self._gate_off = 0.0
        band = max(14, h * 0.07)
        for side, x0 in (("L", -door), ("R", w)):      # both start off-screen
            tags = ("gate", "gate" + side)
            x1 = x0 + door
            c.create_rectangle(x0, 0, x1, h, fill=GATE, outline="", tags=tags)
            for frac in (1 / 3, 2 / 3):
                c.create_rectangle(x0, h * frac - 1, x1, h * frac + 1,
                                   fill="#2a2218", outline="", tags=tags)
            bx0, bx1 = (x1 - band, x1) if side == "L" else (x0, x0 + band)
            c.create_rectangle(bx0, 0, bx1, h, fill=DARK, outline="", tags=tags)
            self._vstripes(bx0, bx1, h, tags)
            edge = x1 if side == "L" else x0
            c.create_rectangle(edge - 3, 0, edge + 3, h, fill=AMBER, outline="", tags=tags)
        c.tag_raise("gate")

    # Positions the gates for progress 0.0 (fully open, off-screen) to 1.0 (fully shut, meeting in
    # the middle) by moving them the difference since last time.
    def _set_gates(self, progress):
        c = self.canvas
        off = self._gate_dist * progress
        dx = off - self._gate_off
        if dx:
            c.move("gateL", dx, 0)
            c.move("gateR", -dx, 0)
        self._gate_off = off
        c.tag_raise("gate")

    # Removes the gates and re-enables input.
    def _end_transition(self):
        self.canvas.delete("gate")
        self.transitioning = False

    # Stops a transition immediately (its pending frames see the changed token and quit) and removes
    # the gates.
    def _cancel_transition(self):
        self._tr_token += 1
        if self.transitioning:
            self.canvas.delete("gate")
        self.transitioning = False

    # Draws the diagonal hazard stripes down a vertical strip (the edge of a gate).
    def _vstripes(self, x0, x1, h, tags):
        c = self.canvas
        bw = x1 - x0
        y = -bw
        while y < h:
            c.create_polygon([x0, y + bw, x1, y, x1, y + bw, x0, y + 2 * bw],
                             fill=AMBER, outline="", tags=tags)
            y += bw * 2

    # ----- drawing helpers -------------------------------------------

    # Draws one piece of text. `size` is in PIXELS (made negative for Tk), so text scales with the
    # window; never smaller than 8 px.
    def _text(self, c, x, y, text, size, color=CREAM, font=DISPLAY, anchor="center", **kw):
        c.create_text(x, y, text=text, fill=color, anchor=anchor,
                      font=(font, -max(8, int(size))), **kw)   # negative = pixels

    # Draws a big title with a darker copy offset slightly underneath as a drop shadow.
    def _title(self, c, x, y, text, size, color=AMBER, shadow="#A86B00"):
        self._text(c, x, y + size * 0.05, text, size, shadow)
        self._text(c, x, y, text, size, color)

    # Draws the full-window radial gradient (lighter in the middle, darker at the edges). It is
    # built small and scaled up for speed, and cached until the window size changes.
    def _background(self, c, w, h):
        if self._bg_size != (w, h):
            # Build the radial gradient small and upscale it: cheap, and smooth.
            sw, sh = max(2, w // 4), max(2, h // 4)
            mask = Image.radial_gradient("L").resize((sw, sh), Image.Resampling.BILINEAR)
            inner = Image.new("RGB", (sw, sh), (46, 35, 20))
            outer = Image.new("RGB", (sw, sh), (18, 15, 11))
            img = Image.composite(outer, inner, mask).resize((w, h), Image.Resampling.BICUBIC)
            self._bg_photo = ImageTk.PhotoImage(img)
            self._bg_size = (w, h)
        c.create_image(0, 0, anchor="nw", image=self._bg_photo)

    # Draws a horizontal hazard-stripe bar from x0 to x1 (used top and bottom of every screen).
    def _stripes(self, x0, y, x1, band):
        c = self.canvas
        c.create_rectangle(x0, y, x1, y + band, fill=DARK, outline="")
        step = band * 2
        x = x0 - band
        while x < x1:
            pts = [x, y + band, x + band, y, x + band + step / 2, y, x + step / 2, y + band]
            pts = [min(max(v, x0), x1) if i % 2 == 0 else v for i, v in enumerate(pts)]
            c.create_polygon(pts, fill=AMBER, outline="")
            x += step

    # Draws the home-screen hole with the mole peeking out. The hole is drawn first, then the mole,
    # then the front half of the hole is drawn OVER the mole's lower part so it looks as if it is
    # standing inside. `max_h` stops the mole growing up into the title above it.
    def _hole_and_mole(self, c, cx, cy, hole_w, max_h=None):
        """A hole with the mole peeking out of it (the hole's front lip is drawn over the mole)."""
        hole_h = hole_w * 0.34
        box = (cx - hole_w / 2, cy - hole_h / 2, cx + hole_w / 2, cy + hole_h / 2)
        rim = "#3a342b"
        c.create_oval(*box, fill="#000000", outline=rim, width=4)
        if self.mole_source is not None:
            mw = max(1, int(hole_w * 0.9))
            sw, sh = self.mole_source.size
            mh = max(1, int(mw * sh / sw))
            if max_h is not None and mh > max_h:      # keep clear of whatever is above
                mh = max(1, int(max_h))
                mw = max(1, int(mh * sw / sh))
            if self._mole_key != (mw, mh):
                self._mole_photo = ImageTk.PhotoImage(
                    self.mole_source.resize((mw, mh), Image.Resampling.LANCZOS))
                self._mole_key = (mw, mh)
            c.create_image(cx, cy + hole_h * 0.25, anchor="s", image=self._mole_photo)
        c.create_arc(*box, start=180, extent=180, style="pieslice", fill="#000000", outline="")
        c.create_arc(*box, start=180, extent=180, style="arc", outline=rim, width=4)

    # Lays out a vertical stack of buttons and records them in self.buttons (the drawing is done
    # later by _draw_buttons). specs = list of (label, action). Height is a fraction of the usable
    # height; width is `width_f` of the content width.
    def _add_buttons(self, specs, y_start, ph, pw, cx, height=0.085, width_f=0.62):
        bw, bh, gap = pw * width_f, ph * height, ph * 0.022
        for i, (label, action) in enumerate(specs):
            y = y_start + i * (bh + gap)
            self.buttons.append({"label": label, "action": action,
                                 "rect": (cx - bw / 2, y, cx + bw / 2, y + bh)})

    # Draws every recorded button. Their colours are set afterwards by _paint_buttons.
    def _draw_buttons(self, c, ph):
        for i, b in enumerate(self.buttons):
            bx0, by0, bx1, by1 = b["rect"]
            c.create_rectangle(bx0, by0, bx1, by1, outline=AMBER, width=3, tags=f"btnbox{i}")
            self._text(c, (bx0 + bx1) / 2, (by0 + by1) / 2, b["label"], (by1 - by0) * 0.46,
                       tags=f"btntxt{i}")
        self._paint_buttons()

    # Colours the buttons: the highlighted one solid amber, the rest outlined. Only recolours
    # existing items (no redraw), so hovering never steals focus from the initials box.
    def _paint_buttons(self):
        # Recolour only - no redraw - so hovering never steals focus from the initials box.
        for i in range(len(self.buttons)):
            sel = i == self.selected
            self.canvas.itemconfig(f"btnbox{i}", fill=AMBER if sel else DARK)
            self.canvas.itemconfig(f"btntxt{i}", fill=DARK if sel else AMBER)

    # ----- screens ----------------------------------------------------
    # top = top of the usable area, ph = its height, pw = content width (single column)

    # Home screen. On a wide window it is two columns: logo, title plate and mole on the left,
    # buttons and high score on the right. On a tall window everything stacks in one column.
    def _draw_home(self, c, cx, top, ph, pw):
        w, h = self._w, self._h
        # Wide (landscape) windows get two columns; narrower ones stack.
        wide = w >= h * 1.25
        # xl / xr are the centres of the left and right columns. The *_y values are heights as
        # fractions of the usable height `ph` (top of the area + fraction * ph). Edit these to move
        # things.
        if wide:      # two columns: logo + mole on the left, buttons on the right
            xl, xr = w * 0.29, w * 0.71
            title_y, plate_y, hole_y, hole_w = top + ph * 0.27, top + ph * 0.43, top + ph * 0.80, ph * 0.30
            tsize, plate_w = min(ph * 0.17, w * 0.08), min(w * 0.36, ph * 0.85)
            btn_cx, btn_y, btn_cw, btn_h = xr, top + ph * 0.26, min(w * 0.40, ph * 1.0), 0.12
            hs_x, hs_y = xr, top + ph * 0.78
        else:         # stacked
            xl = btn_cx = hs_x = w / 2
            title_y, plate_y, hole_y, hole_w = top + ph * 0.10, top + ph * 0.19, top + ph * 0.46, ph * 0.18
            tsize, plate_w = min(ph * 0.09, w * 0.13), min(w * 0.70, ph * 0.5)
            btn_y, btn_cw, btn_h = top + ph * 0.55, min(w * 0.80, ph * 0.70), 0.08
            hs_y = top + ph * 0.885

        self._title(c, xl, title_y, "ENGG3000", tsize)
        psize = min(ph * 0.06, plate_w * 0.13)
        c.create_rectangle(xl - plate_w / 2, plate_y - psize * 0.85,
                           xl + plate_w / 2, plate_y + psize * 0.85,
                           fill=DARK, outline=AMBER, width=3)
        self._text(c, xl, plate_y, "WHACK-A-MOLE", psize)
        hole_h = hole_w * 0.34
        mole_room = (hole_y + hole_h * 0.25) - (plate_y + psize * 0.85 + ph * 0.015)
        self._hole_and_mole(c, xl, hole_y, hole_w, max_h=mole_room)

        self._add_buttons([("START GAME", self.on_start),
                           ("LEADERBOARD", self.show_leaderboard),
                           ("HOW TO PLAY", self.show_help)],
                          btn_y, ph, btn_cw, btn_cx, height=btn_h, width_f=0.86)
        best = max((e.get("score", 0) for e in self.get_scores()), default=0)
        self._text(c, hs_x, hs_y, f"HIGH SCORE  {best}", ph * 0.045, DIM)
        self._text(c, w / 2, top + ph * 0.94, "Up/Down + Enter    F11 fullscreen    Esc menu",
                   ph * 0.024, DIM, BODY)

    # Leaderboard screen: up to max_entries rows (rank, name, score) with the top three in amber,
    # and a BACK button.
    def _draw_scores(self, c, cx, top, ph, pw):
        self._title(c, cx, top + ph * 0.10, "LEADERBOARD", ph * 0.085)
        self._text(c, cx, top + ph * 0.185, f"TOP {self.max_entries}", ph * 0.03, ORANGE)
        scores = self.get_scores()[: self.max_entries]
        row_h, y = ph * 0.075, top + ph * 0.24
        left, right = cx - pw * 0.42, cx + pw * 0.42
        if not scores:
            self._text(c, cx, y + row_h, "NO SCORES YET", ph * 0.04, DIM)
        for i, entry in enumerate(scores):
            ry = y + i * (row_h + ph * 0.01)
            mid = ry + row_h / 2
            color = AMBER if i < 3 else CREAM
            c.create_rectangle(left, ry, right, ry + row_h, fill=PANEL_BG, outline="")
            self._text(c, left + pw * 0.03, mid, f"#{i + 1}", ph * 0.04, color, anchor="w")
            self._text(c, left + pw * 0.2, mid, str(entry.get("name", "???")).upper(),
                       ph * 0.04, color, anchor="w")
            self._text(c, right - pw * 0.03, mid, str(entry.get("score", 0)),
                       ph * 0.04, color, anchor="e")
        self._add_buttons([("BACK", self.show_home)], top + ph * 0.78, ph, pw, cx)

    # How-to-play screen: one wrapped bullet per entry in HELP_TIPS, and a BACK button.
    def _draw_help(self, c, cx, top, ph, pw):
        self._title(c, cx, top + ph * 0.10, "HOW TO PLAY", ph * 0.085)
        for i, tip in enumerate(HELP_TIPS):
            self._text(c, cx - pw * 0.40, top + ph * (0.20 + i * 0.095), "- " + tip,
                       ph * 0.032, CREAM, BODY, anchor="nw", width=pw * 0.8, justify="left")
        self._add_buttons([("BACK", self.show_home)], top + ph * 0.78, ph, pw, cx)

    # Game-over screen. Top: the score box with a note (new high score / rank / try again). If the
    # score qualifies and has not been saved yet, an initials box and a SAVE SCORE button appear;
    # otherwise just PLAY AGAIN, LEADERBOARD and MAIN MENU.
    def _draw_over(self, c, cx, top, ph, pw):
        self._title(c, cx, top + ph * 0.10, "GAME OVER", ph * 0.10, RED, "#8A2F00")
        b0, b1 = top + ph * 0.19, top + ph * 0.45
        c.create_rectangle(cx - pw * 0.38, b0, cx + pw * 0.38, b1,
                           fill="#0b0907", outline=AMBER, width=3)
        self._text(c, cx, b0 + ph * 0.04, "YOUR SCORE", ph * 0.03, ORANGE)
        self._text(c, cx, (b0 + b1) / 2 + ph * 0.015, str(self.final_score), ph * 0.13, AMBER)
        if self.new_high:
            note = "NEW HIGH SCORE!"
        elif self.qualifies:
            note = f"RANK #{self.rank}"
        else:
            note = "TRY AGAIN"
        self._text(c, cx, b1 - ph * 0.03, note, ph * 0.03, CREAM)

        if self.qualifies and not self.saved:
            self._text(c, cx, top + ph * 0.49, "ENTER YOUR INITIALS", ph * 0.03, CREAM)
            if self.entry is None or not self.entry.winfo_exists():
                self.entry = tk.Entry(c, textvariable=self.entry_text, justify="center",
                                      bg="black", fg=AMBER, insertbackground=AMBER,
                                      relief="flat", highlightthickness=2,
                                      highlightbackground=AMBER, highlightcolor=ORANGE)
                self.entry.bind("<Return>", lambda e: (self._save(), "break")[1])
                self.entry.bind("<Down>", lambda e: self._leave_entry(1))
                self.entry.bind("<Up>", lambda e: self._leave_entry(-1))
            self.entry.config(font=(DISPLAY, -max(8, int(ph * 0.045))))
            c.create_window(cx, top + ph * 0.545, window=self.entry,
                            width=pw * 0.3, height=ph * 0.07)
            if self.message:
                self._text(c, cx, top + ph * 0.60, self.message, ph * 0.025, RED, BODY)
            self._add_buttons([("SAVE SCORE", self._save), ("PLAY AGAIN", self.on_start),
                               ("MAIN MENU", self.show_home)],
                              top + ph * 0.63, ph, pw, cx, height=0.075)
        else:
            if self.saved:
                self._text(c, cx, top + ph * 0.50, "SCORE SAVED", ph * 0.035, AMBER)
            self._add_buttons([("PLAY AGAIN", self.on_start),
                               ("LEADERBOARD", self.show_leaderboard),
                               ("MAIN MENU", self.show_home)],
                              top + ph * 0.58, ph, pw, cx)

    # ----- game-over actions -----------------------------------------

    # Up/Down pressed inside the initials box: hand focus back to the buttons and move the
    # highlight.
    def _leave_entry(self, step):
        self.canvas.focus_set()
        self.move(step)
        return "break"

    # Saves the score with the typed initials (refuses an empty box), then redraws the screen as
    # 'SCORE SAVED'. The actual saving is done by the submit_score callback the game supplied.
    def _save(self):
        name = self.entry_text.get().strip()

        if not name:
            self.message = "TYPE YOUR INITIALS FIRST"
            self.render()
            if self._entry_visible():
                self.entry.focus_set()
            return

        # Handle leaderboard saving errors
        try:
            self.submit_score(name, self.final_score)

        except OSError as error:
            print(f"Leaderboard save failed: {error}")

            self.message = "SAVE FAILED - TRY AGAIN"
            self.render()

            if self._entry_visible():
                self.entry.focus_set()
            return

        # Only mark as saved after successful file writing
        self.saved = True
        self.message = ""
        self.selected = 0
        self.render()
        self.canvas.focus_set()