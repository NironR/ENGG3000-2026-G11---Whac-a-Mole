import ctypes
import os
import sys

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Assets")
MUSIC_FILES = {
    "Easy": os.path.join(ASSET_DIR, "Audio","background_easy.mp3"),
    "Medium": os.path.join(ASSET_DIR,"Audio", "background_medium.mp3"),
    "Hard": os.path.join(ASSET_DIR,"Audio", "background_hard.mp3"),
}
MUSIC_ALIASES = {
    "Easy": "music_easy",
    "Medium": "music_medium",
    "Hard": "music_hard",
}
WHACK_FILE = "mole_whack.mp3"
MUSIC_VOLUME = 500 # Range is 0 to 1000, where 1000 is max volume
WHACK_VOLUME = 800 # Range is 0 to 1000, where 1000 is max volume
WHACK_VOICES = 3 #Lets back to back whacks overlapping

_available = sys.platform == "win32"
_ready = False
_whack_index = 0
_current_alias = None
_opened = set()

if _available:
    _winmm = ctypes.windll.winmm

def _mci(command):
        """Send one MCI command. Returns 0 on success, an error code otherwise."""
        buf = ctypes.create_unicode_buffer(255)
        return _winmm.mciSendStringW(command, buf, 254, None)
#Preloading the music makes loading game slower but less delay when music switches up.
def _preload(filename, alias, volume):
    """Open a file once, ahead of time, so playing it later is instant."""
    path = os.path.join(ASSET_DIR,"Audio", filename)
    if not os.path.exists(path):
        print(f"Audio: {path} not found.")
        return
    if _mci(f'open "{path}" type mpegvideo alias {alias}') != 0:
        print(f"Audio: could not open {filename}.")
        return
    _mci(f"setaudio {alias} volume to {volume}")
    _opened.add(alias)

def init():
    """Load every sound up front. Call once at startup; safe to call again."""
    global _ready
    if _ready or not _available:
        return
    _ready = True

    for i in range(WHACK_VOICES):
        _preload(WHACK_FILE, f"whack{i}", WHACK_VOLUME)
    for difficulty, filename in MUSIC_FILES.items():
        _preload(filename, MUSIC_ALIASES[difficulty], MUSIC_VOLUME)
def play_music(difficulty):
    """Loop the track for this difficulty. Does nothing if it's already playing."""
    global _current_alias
    if not _available:
        return
    init()
    alias = MUSIC_ALIASES.get(difficulty, MUSIC_ALIASES ["Easy"])
    if alias == _current_alias:
        return
    previous = _current_alias
    _current_alias = alias
    if alias in _opened:
        _mci(f"seek {alias} to start") #Starts the new track
        _mci(f"play {alias} repeat")
       
    if previous in _opened:
        _mci (f"stop {previous}") # stops old track 


def stop_music():
    global _current_alias
    _current_alias = None
    if not _available:
        return
    for alias in MUSIC_ALIASES.values():
        if alias in _opened:
            _mci(f"stop {alias}")
            _mci(f"seek {alias} to start")
def play_whack():
    global _whack_index
    if not _available:
            return
    init()
    alias = f"whack{_whack_index}"
    _whack_index = (_whack_index + 1) % WHACK_VOICES
    if alias in _opened:
        _mci(f"seek {alias} to start")
        _mci(f"play {alias}")