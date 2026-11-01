import ctypes
import os
import sys

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Assets")
MUSIC_FILES = {
    "Easy": os.path.join(ASSET_DIR, "Audio","background_easy.mp3"),
    "Medium": os.path.join(ASSET_DIR,"Audio", "background_medium.mp3"),
    "Hard": os.path.join(ASSET_DIR,"Audio", "background_hard.mp3"),
    # Not a difficulty: the loop used on every menu screen. play_music("Menu") starts it, and
    # starting any other track (or stop_music) stops it, so tracks can never overlap.
    "Menu": os.path.join(ASSET_DIR,"Audio", "Menu Music.mp3"),
}
MUSIC_ALIASES = {
    "Easy": "music_easy",
    "Medium": "music_medium",
    "Hard": "music_hard",
    "Menu": "music_menu",
}
WHACK_FILE = "mole_whack.mp3"
MUSIC_VOLUME = 500 # Range is 0 to 1000, where 1000 is max volume
WHACK_VOLUME = 800 # Range is 0 to 1000, where 1000 is max volume
WHACK_VOICES = 3 #Lets back to back whacks overlapping

# One-off sound effects (everything except the normal mole whack above).
#   files    - file names inside Assets/Audio, tried in order; the first one that opens is used.
#              Iain's scream lists .wav and .mp3 after the .ogg because Windows' built-in player
#              (MCI) cannot always open .ogg files - convert it to .wav and it will be picked up.
#   volume   - 0 to 1000, like MUSIC_VOLUME.
#   voices   - how many copies are loaded so rapid repeats can overlap (1 = replays from the start).
#   default_ms - length assumed if Windows cannot report the real one.
EFFECTS = {
    "golden":   {"files": ["Golden Hammer wack.wav"], "volume": 800, "voices": 3, "default_ms": 500},
    "gameover": {"files": ["Game Over.wav"], "volume": 800, "voices": 1, "default_ms": 3000},
    "iain":     {"files": ["Iain Scream.ogg", "Iain Scream.wav", "Iain Scream.mp3"],
                 "volume": 900, "voices": 1, "default_ms": 2500},
}

_available = sys.platform == "win32"
_ready = False
_whack_index = 0
_current_alias = None
_opened = set()
_effect_voices = {}   # effect name -> aliases of its loaded voices
_effect_next = {}     # effect name -> which voice plays next
_effect_length = {}   # effect name -> length in milliseconds

if _available:
    _winmm = ctypes.windll.winmm

def _mci(command):
        """Send one MCI command. Returns 0 on success, an error code otherwise."""
        buf = ctypes.create_unicode_buffer(255)
        return _winmm.mciSendStringW(command, buf, 254, None)

def _mci_text(command):
    """Send one MCI command and return (error code, text answer), e.g. for 'status ... length'."""
    buf = ctypes.create_unicode_buffer(255)
    code = _winmm.mciSendStringW(command, buf, 254, None)
    return code, buf.value

def _open_audio(path, alias):
    """Open any audio file. Tries the MP3-capable player first, then lets Windows pick one
    from the file type (which is what plays .wav files). Returns True on success."""
    if _mci(f'open "{path}" type mpegvideo alias {alias}') == 0:
        return True
    return _mci(f'open "{path}" alias {alias}') == 0

def _preload_effect(name):
    """Load every voice of one effect from the first file name in its list that opens."""
    spec = EFFECTS[name]
    voices = []
    for i in range(spec["voices"]):
        alias = f"{name}{i}"
        for filename in spec["files"]:
            path = os.path.join(ASSET_DIR, "Audio", filename)
            if os.path.exists(path) and _open_audio(path, alias):
                _mci(f"setaudio {alias} volume to {spec['volume']}")
                voices.append(alias)
                _opened.add(alias)
                break
    if not voices:
        print(f"Audio: no playable file for '{name}' (tried {', '.join(spec['files'])}).")
        return
    _effect_voices[name] = voices
    # Ask Windows how long it is, so callers can wait for it to finish before the next sound.
    code, text = _mci_text(f"status {voices[0]} length")
    _effect_length[name] = int(text) if code == 0 and text.strip().isdigit() and int(text) > 0 \
        else spec["default_ms"]

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
    for name in EFFECTS:
        _preload_effect(name)
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

def play_effect(name):
    """Play one of the EFFECTS ("golden", "gameover", "iain") from the start.
    Returns how long it lasts in milliseconds, or 0 if it cannot play (not Windows, file missing),
    so code that waits for the sound to finish simply carries on straight away."""
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