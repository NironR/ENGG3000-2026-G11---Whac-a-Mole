import ctypes
import os
import sys

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Assets")
MUSIC_FILES = {
    "Easy": os.path.join(ASSET_DIR, "background_easy.mp3"),
    "Medium": os.path.join(ASSET_DIR, "background_medium.mp3"),
    "Hard": os.path.join(ASSET_DIR, "background_hard.mp3"),
}
WHACK_FILE = "mole_whack.mp3"
MUSIC_VOLUME = 500 # Range is 0 to 1000, where 1000 is max volume
WHACK_VOLUME = 800 # Range is 0 to 1000, where 1000 is max volume
WHACK_VOICES = 3 #Lets back to back whacks overlapping

_available = sys.platform == "win32"
_ready = False
_current_track = None
_whack_index = 0
if _available:
    _winmm = ctypes.windll.winmm

    def _mci(command):
        """Send one MCI command. Returns 0 on success, an error code otherwise."""
        buf = ctypes.create_unicode_buffer(255)
        return _winmm.mciSendStringW(command, buf, 254, None)
def _open (path, alias):
    return _mci(f'open "{path}" type mpegvideo alias {alias}')

def init():
    """Preload the whack sound so the first hit doesn't have a delay."""
    global _ready
    if _ready or not _available:
        return _ready

    path = os.path.join(ASSET_DIR, WHACK_FILE)
    if not os.path.exists(path):
        print(f"Warning: {path} not found, whack sound will not play.")
        return False
    
    for i in range (WHACK_VOICES):
            _open(path, f"whack{i}")
            if _open(path, f"whack{i}") != 0:
                print(f"Warning: failed to open {path} for whack sound.")
                return False
            _mci(f"Setaudio whack{i} volume to {WHACK_VOLUME}")
    _ready = True
    return True
def play_music(difficulty):
    """Loop the track for this difficulty. Does nothing if it's already playing."""
    global _current_track
    if not _available:
        return

    filename = MUSIC_FILES.get(difficulty, MUSIC_FILES["Easy"])
    if filename == _current_track:
        return  # already playing, don't restart it on every hit

    _mci("close music")  # harmless if nothing is open
    _current_track = filename  # set first so a failure doesn't retry on every hit

    path = os.path.join(ASSET_DIR, filename)
    if not os.path.exists(path):
        print(f"Audio: {path} not found.")
        return
    if _open(path, "music") != 0:
        print(f"Audio: could not open {filename}.")
        return

    _mci(f"setaudio music volume to {MUSIC_VOLUME}")
    _mci("play music repeat")


def stop_music():
    global _current_track
    _current_track = None
    if _available:
        _mci("stop music")
        _mci("close music")
def play_whack():
    global _whack_index
    if not init():
        return
    alias = f"whack{_whack_index}"
    _whack_index = (_whack_index + 1) % WHACK_VOICES
    _mci(f"seek {alias} to start")
    _mci(f"play {alias}")