import ctypes
import os
import sys

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Assets", "Audio")

# Looping background tracks, one per difficulty plus "Menu" (used on every menu screen). Only one
# plays at a time: starting another track, or stop_music(), stops the current one.
MUSIC_FILES = {
    "Easy": "background_easy.mp3",
    "Medium": "background_medium.mp3",
    "Hard": "background_hard.mp3",
    "Menu": "Menu Music.mp3",
}
MUSIC_VOLUME = 500 # Range is 0 to 1000, where 1000 is max volume

# One-off sound effects.
#   file       - file name inside Assets/Audio.
#   volume     - 0 to 1000, like MUSIC_VOLUME.
#   voices     - how many copies are loaded so rapid repeats can overlap (1 = replays from the start).
#   default_ms - length assumed if Windows cannot report the real one.
EFFECTS = {
    "whack":    {"file": "mole_whack.mp3", "volume": 800, "voices": 3, "default_ms": 300},
    "golden":   {"file": "Golden Hammer wack.wav", "volume": 800, "voices": 3, "default_ms": 500},
    "gameover": {"file": "Game Over.wav", "volume": 800, "voices": 1, "default_ms": 3000},
    "iain":     {"file": "Iain Scream.wav", "volume": 900, "voices": 1, "default_ms": 2500},
    # Menu buttons: a tiny tick when the highlight moves, a two-note blip when one is pressed (two
    # variations; menus.py picks one at random so repeated presses don't sound identical)
    "hover":    {"file": "menu_hover.wav", "volume": 450, "voices": 2, "default_ms": 25},
    "press":    {"file": "menu_press.wav", "volume": 650, "voices": 2, "default_ms": 115},
    "press2":   {"file": "menu_press_2.wav", "volume": 650, "voices": 2, "default_ms": 115},
}

_available = sys.platform == "win32"
_ready = False
_current_alias = None
_opened = set()
_effect_voices = {}   # effect name -> aliases of its loaded voices
_effect_next = {}     # effect name -> which voice plays next
_effect_length = {}   # effect name -> length in milliseconds

if _available:
    _winmm = ctypes.windll.winmm

def _mci(command):
    """Send one MCI command. Returns (error code, text answer); code 0 means success."""
    buf = ctypes.create_unicode_buffer(255)
    code = _winmm.mciSendStringW(command, buf, 254, None)
    return code, buf.value

def _music_alias(track):
    return "music_" + (track if track in MUSIC_FILES else "Easy").lower()

def _open(filename, alias, volume):
    """Open a file once, ahead of time, so playing it later is instant. Tries the MP3-capable
    player first, then lets Windows pick one from the file type (which is what plays .wav files)."""
    path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(path):
        print(f"Audio: {path} not found.")
        return False
    if (_mci(f'open "{path}" type mpegvideo alias {alias}')[0]
            and _mci(f'open "{path}" alias {alias}')[0]):
        print(f"Audio: could not open {filename}.")
        return False
    _mci(f"setaudio {alias} volume to {volume}")
    _opened.add(alias)
    return True

#Preloading makes loading the game slower but there is no delay when a sound or track starts.
def init():
    """Load every sound up front. Call once at startup; safe to call again."""
    global _ready
    if _ready or not _available:
        return
    _ready = True

    for track, filename in MUSIC_FILES.items():
        _open(filename, _music_alias(track), MUSIC_VOLUME)

    for name, spec in EFFECTS.items():
        voices = [f"{name}{i}" for i in range(spec["voices"])
                  if _open(spec["file"], f"{name}{i}", spec["volume"])]
        if not voices:
            continue
        _effect_voices[name] = voices
        # Ask Windows how long it is, so callers can wait for it to finish before the next sound.
        code, text = _mci(f"status {voices[0]} length")
        _effect_length[name] = int(text) if code == 0 and text.strip().isdigit() and int(text) > 0 \
            else spec["default_ms"]

def play_music(track):
    """Loop this track ("Easy", "Medium", "Hard" or "Menu"). Does nothing if it's already playing."""
    global _current_alias
    if not _available:
        return
    init()
    alias = _music_alias(track)
    if alias == _current_alias:
        return
    previous = _current_alias
    _current_alias = alias
    if alias in _opened:
        _mci(f"seek {alias} to start") #Starts the new track
        _mci(f"play {alias} repeat")
    if previous in _opened:
        _mci(f"stop {previous}") # stops old track

def stop_music():
    global _current_alias
    _current_alias = None
    if not _available:
        return
    for track in MUSIC_FILES:
        alias = _music_alias(track)
        if alias in _opened:
            _mci(f"stop {alias}")
            _mci(f"seek {alias} to start")

def play_effect(name):
    """Play one of the EFFECTS from the start. Returns how long it lasts in milliseconds, or 0 if it
    cannot play (not Windows, file missing), so code that waits for the sound to finish simply
    carries on straight away."""
    if not _available:
        return 0
    init()
    voices = _effect_voices.get(name)
    if not voices:
        return 0
    index = _effect_next.get(name, 0) % len(voices)
    _effect_next[name] = (index + 1) % len(voices)
    _mci(f"seek {voices[index]} to start")
    _mci(f"play {voices[index]}")
    return _effect_length.get(name, 0)

def effect_length_ms(name):
    """Length of an effect in milliseconds (0 if it is not loaded)."""
    if not _available:
        return 0
    init()
    return _effect_length.get(name, 0)

def stop_effect(name):
    """Cut an effect off immediately (e.g. when a new game starts)."""
    if not _available:
        return
    for alias in _effect_voices.get(name, []):
        _mci(f"stop {alias}")
