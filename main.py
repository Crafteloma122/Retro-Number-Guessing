import json
import math
import datetime
import hashlib
import os
import random
import shutil
import struct
import sys
from pathlib import Path

import pygame

# NUMBER//GUESSER - a self-contained Pygame arcade game.
# All sound effects and the looping chiptune are generated at runtime.

pygame.mixer.pre_init(44100, -16, 1, 512)
pygame.init()
W, H, FPS = 1000, 680, 60
pygame.display.set_caption("NUMBER//GUESSER")
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
ROOT = Path(__file__).resolve().parent

# Stable per-user save location: progress survives replacing/extracting the ZIP.
if os.name == "nt":
    _data_home = Path(os.environ.get("APPDATA", str(Path.home()))) / "NumberGuesser"
else:
    _data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "number-guesser"
SAVE = _data_home / "player_data.json"
LEGACY_SAVE = ROOT / "data" / "player_data.json"
SAVE_ERROR = ""
try:
    SAVE.parent.mkdir(parents=True, exist_ok=True)
except OSError:
    SAVE = ROOT / "data" / "player_data.json"
    SAVE.parent.mkdir(parents=True, exist_ok=True)

BG = (12, 15, 32)
PANEL = (23, 29, 57)
PANEL2 = (32, 40, 76)
WHITE = (242, 245, 255)
MUTED = (151, 164, 194)
CYAN = (67, 226, 231)
PURPLE = (177, 108, 255)
GREEN = (91, 232, 154)
ORANGE = (255, 177, 91)
RED = (255, 103, 126)
YELLOW = (255, 222, 108)

MODE_BASE_COLORS = {"EASY": GREEN, "MEDIUM": ORANGE, "HARD": PURPLE,
                    "BLITZ": CYAN, "SURVIVAL": YELLOW}
MODES = {
    "EASY":     {"max": 100,  "tries": 10, "range": (20, 40), "color": GREEN},
    "MEDIUM":   {"max": 500,  "tries": 15, "range": (40, 60), "color": ORANGE},
    "HARD":     {"max": 1000, "tries": 20, "range": (60, 80), "color": PURPLE},
    "BLITZ":    {"max": 250,  "tries": 7,  "range": (60, 90), "color": CYAN,
                 "special": True, "description": "A high-pressure round with only 7 attempts."},
    "SURVIVAL": {"max": 1000, "tries": 9,  "range": (100, 140), "color": YELLOW,
                 "special": True, "description": "High rewards. Only 9 attempts."},
    "DAILY":    {"max": 300,  "tries": 12, "range": (75, 110), "color": (255, 120, 210),
                 "description": "A changing challenge each day."},
}

# Bank coins use their own reward/penalty bands, independently of score multipliers.
# Tougher modes pay more on a win and risk a larger (but capped) loss.
BANK_REWARD_RANGES = {
    "EASY": (10, 18),
    "MEDIUM": (16, 28),
    "HARD": (24, 40),
    "BLITZ": (22, 38),
    "SURVIVAL": (32, 50),
    "DAILY": (25, 45),
}
BANK_LOSS_RANGES = {
    "EASY": (2, 5),
    "MEDIUM": (4, 8),
    "HARD": (6, 12),
    "BLITZ": (7, 13),
    "SURVIVAL": (10, 18),
    "DAILY": (5, 10),
}

DAILY_CHALLENGES = [
    {"id": "CLASSIC", "name": "CLASSIC SIGNAL", "max": 300, "tries": 12,
     "reward_range": (75, 110), "parity": None,
     "description": "Find the secret number from 1 to 300."},
    {"id": "ODD_SIGNAL", "name": "ODD SIGNAL", "max": 399, "tries": 12,
     "reward_range": (85, 125), "parity": "ODD",
     "description": "The secret number is ODD."},
    {"id": "EVEN_SIGNAL", "name": "EVEN SIGNAL", "max": 400, "tries": 12,
     "reward_range": (85, 125), "parity": "EVEN",
     "description": "The secret number is EVEN."},
    {"id": "QUICKFIRE", "name": "QUICKFIRE", "max": 500, "tries": 8,
     "reward_range": (110, 160), "parity": None,
     "description": "Only 8 attempts. Make every guess count."},
    {"id": "NARROW_WINDOW", "name": "NARROW WINDOW", "max": 150, "tries": 7,
     "reward_range": (100, 145), "parity": None,
     "description": "A smaller range, but only 7 attempts."},
    {"id": "LONG_SHOT", "name": "LONG SHOT", "max": 1000, "tries": 14,
     "reward_range": (130, 180), "parity": None,
     "description": "A huge range: find the number from 1 to 1,000."},
]

def daily_challenge_for_date(target_date):
    """Return a shared daily variant; variants are random-looking and never repeat on adjacent days."""
    anchor_day = datetime.date(2020, 1, 1)
    if target_date < anchor_day:
        seed_text = "NUMBER-GUESSER-DAILY-VARIANT-" + target_date.isoformat()
        index = int(hashlib.sha256(seed_text.encode()).hexdigest()[:12], 16) % len(DAILY_CHALLENGES)
        return dict(DAILY_CHALLENGES[index])

    previous_index = -1
    day = anchor_day
    index = 0
    while day <= target_date:
        options = [i for i in range(len(DAILY_CHALLENGES)) if i != previous_index]
        seed_text = "NUMBER-GUESSER-DAILY-VARIANT-" + day.isoformat()
        digest = int(hashlib.sha256(seed_text.encode()).hexdigest()[:12], 16)
        index = options[digest % len(options)]
        previous_index = index
        day += datetime.timedelta(days=1)
    return dict(DAILY_CHALLENGES[index])

DAILY_CHALLENGE = daily_challenge_for_date(datetime.date.today())

def apply_daily_config(challenge):
    """Update the daily mode's range, attempts, and reward band for the chosen variant."""
    MODES["DAILY"].update({
        "max": challenge["max"],
        "tries": challenge["tries"],
        "range": challenge["reward_range"],
        "description": challenge["description"],
        "color": (255, 120, 210),
    })

apply_daily_config(DAILY_CHALLENGE)

_CURRENT_DAILY_DATE = datetime.date.today()
def refresh_daily_if_needed():
    """Refresh daily challenge and completion state when safe after midnight."""
    global DAILY_CHALLENGE, _CURRENT_DAILY_DATE
    if state == "GAME":
        return
    today_date = datetime.date.today()
    if today_date == _CURRENT_DAILY_DATE:
        return
    previous_date = _CURRENT_DAILY_DATE
    today = today_date.isoformat()
    try:
        saved_date = datetime.date.fromisoformat(data.get("daily_date", ""))
        consecutive = (today_date - saved_date).days == 1
    except (ValueError, TypeError):
        consecutive = False
    if not (consecutive and data.get("daily_completed", False)):
        data["daily_streak"] = 0
    data["daily_date"] = today
    data["daily_completed"] = today in data.setdefault("daily_attempt_dates", [])
    DAILY_CHALLENGE = daily_challenge_for_date(today_date)
    apply_daily_config(DAILY_CHALLENGE)
    _CURRENT_DAILY_DATE = today_date
    save_data()

THEMES = {
    "DEFAULT": {"name": "Neon Core", "price": 0,
        "palette": {"BG": (12, 15, 32), "PANEL": (23, 29, 57), "PANEL2": (32, 40, 76),
                    "CYAN": (67, 226, 231), "PURPLE": (177, 108, 255), "GREEN": (91, 232, 154),
                    "ORANGE": (255, 177, 91), "RED": (255, 103, 126), "YELLOW": (255, 222, 108)}},
    "ARCTIC": {"name": "Arctic Glow", "price": 300,
        "palette": {"BG": (7, 20, 38), "PANEL": (15, 42, 66), "PANEL2": (25, 60, 88),
                    "CYAN": (115, 230, 255), "PURPLE": (128, 177, 255), "GREEN": (126, 255, 218),
                    "ORANGE": (255, 211, 140), "RED": (255, 120, 150), "YELLOW": (255, 246, 170)}},
    "SUNSET": {"name": "Sunset Drive", "price": 375,
        "palette": {"BG": (32, 14, 30), "PANEL": (54, 23, 47), "PANEL2": (76, 32, 57),
                    "CYAN": (255, 143, 119), "PURPLE": (255, 106, 166), "GREEN": (168, 235, 122),
                    "ORANGE": (255, 184, 95), "RED": (255, 91, 117), "YELLOW": (255, 218, 120)}},
    "FOREST": {"name": "Forest Circuit", "price": 420,
        "palette": {"BG": (8, 24, 26), "PANEL": (16, 43, 43), "PANEL2": (24, 60, 57),
                    "CYAN": (100, 235, 190), "PURPLE": (143, 185, 255), "GREEN": (143, 242, 135),
                    "ORANGE": (255, 194, 115), "RED": (255, 116, 119), "YELLOW": (239, 231, 130)}},
    "GOLD": {"name": "Golden Hour", "price": 480,
        "palette": {"BG": (24, 21, 12), "PANEL": (46, 38, 20), "PANEL2": (67, 54, 26),
                    "CYAN": (121, 224, 221), "PURPLE": (196, 148, 255), "GREEN": (176, 232, 123),
                    "ORANGE": (255, 188, 79), "RED": (255, 111, 105), "YELLOW": (255, 220, 100)}},
    "VIOLET": {"name": "Cosmic Violet", "price": 540,
        "palette": {"BG": (19, 12, 38), "PANEL": (37, 23, 67), "PANEL2": (54, 34, 88),
                    "CYAN": (96, 232, 255), "PURPLE": (199, 135, 255), "GREEN": (118, 244, 178),
                    "ORANGE": (255, 173, 112), "RED": (255, 104, 160), "YELLOW": (255, 225, 135)}},
}
WIN_EFFECTS = {
    "RING": {"name": "Pulse Ring", "price": 0, "description": "The classic expanding ring."},
    "STARBURST": {"name": "Starburst", "price": 360, "description": "A radiant burst of arcade light."},
    "CONFETTI": {"name": "Confetti Party", "price": 480, "description": "A celebration of flying confetti."},
}
SPECIAL_MODE_PRICES = {"BLITZ": 540, "SURVIVAL": 900}
SHOP_CATEGORIES = ["THEMES", "WIN EFFECTS", "ITEMS", "SPECIAL MODES"]

DEFAULT = {"score": 0, "personal_best": 0, "games": 0, "wins": 0,
           "losses": 0, "streak": 0, "best_streak": 0, "achievements": [],
           "coins": 0, "lifetime_points": 0, "xp": 0, "level": 1, "lifetime_coins_earned": 0,
           "lifetime_coins_spent": 0, "mode_stats": {}, "attempts_total": 0,
           "daily_date": "", "daily_completed": False, "daily_attempt_dates": [], "daily_streak": 0,
           "daily_best_streak": 0, "owned_themes": ["DEFAULT"],
           "active_theme": "DEFAULT", "owned_effects": ["RING"],
           "active_effect": "RING", "inventory": {"hints": 0}, "unlocked_modes": []}

def default_data():
    # Build fresh nested values every time; reset/load must not mutate DEFAULT lists.
    d = DEFAULT.copy()
    d["achievements"] = []
    d["owned_themes"] = ["DEFAULT"]
    d["owned_effects"] = ["RING"]
    d["inventory"] = {"hints": 0}
    d["unlocked_modes"] = []
    d["daily_attempt_dates"] = []
    d["mode_stats"] = {}
    return d

def preserve_corrupt_save(candidate):
    """Keep a damaged save before falling back to defaults."""
    try:
        if not candidate.is_file() or candidate.stat().st_size == 0:
            return
        backup = candidate.with_name("player_data.corrupt.json")
        if backup.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = candidate.with_name(f"player_data.corrupt-{stamp}.json")
        shutil.copy2(candidate, backup)
        print(f"[SAVE WARNING] Corrupt save preserved at: {backup}")
    except OSError as exc:
        print(f"[SAVE WARNING] Could not preserve corrupt save {candidate}: {exc}")

def load_data():
    # Prefer the stable user-data file. Migrate the old project-local file once.
    for candidate in (SAVE, LEGACY_SAVE):
        try:
            with candidate.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                preserve_corrupt_save(candidate)
                continue
            d = default_data()
            d.update(loaded)
            for key in ("score", "personal_best", "games", "wins", "losses", "streak",
                        "best_streak", "coins", "lifetime_points", "xp", "level",
                        "lifetime_coins_earned", "lifetime_coins_spent", "attempts_total",
                        "daily_streak", "daily_best_streak"):
                try:
                    d[key] = max(0, int(d.get(key, 0)))
                except (TypeError, ValueError):
                    d[key] = 0
            for key in ("achievements", "owned_themes", "owned_effects", "unlocked_modes"):
                value = d.get(key, [])
                d[key] = list(dict.fromkeys(str(v) for v in value)) if isinstance(value, (list, tuple)) else []
            d["inventory"] = d.get("inventory") if isinstance(d.get("inventory"), dict) else {}
            try:
                d["inventory"] = {"hints": max(0, int(d["inventory"].get("hints", 0)))}
            except (TypeError, ValueError):
                d["inventory"] = {"hints": 0}
            d["mode_stats"] = d.get("mode_stats") if isinstance(d.get("mode_stats"), dict) else {}
            d["daily_date"] = str(d.get("daily_date", ""))
            d["daily_completed"] = bool(d.get("daily_completed", False))
            raw_attempt_dates = d.get("daily_attempt_dates", [])
            if not isinstance(raw_attempt_dates, (list, tuple, set)):
                raw_attempt_dates = []
            normalized_attempt_dates = []
            for value in raw_attempt_dates:
                try:
                    normalized_attempt_dates.append(datetime.date.fromisoformat(str(value)).isoformat())
                except (ValueError, TypeError):
                    continue
            d["daily_attempt_dates"] = list(dict.fromkeys(normalized_attempt_dates))
            d["level"] = max(1, d["level"])
            d["daily_streak"] = max(0, d["daily_streak"])
            d["daily_best_streak"] = max(0, d["daily_best_streak"])
            # Migrate a current-day completion from older save files into the attempt ledger.
            today = datetime.date.today().isoformat()
            if d["daily_date"] == today and d["daily_completed"] and today not in d["daily_attempt_dates"]:
                d["daily_attempt_dates"].append(today)
            if d["daily_date"] != today:
                # Keep a streak only if yesterday's challenge was completed.
                try:
                    previous_day = datetime.date.fromisoformat(d["daily_date"])
                    is_next_day = (datetime.date.today() - previous_day).days == 1
                except (ValueError, TypeError):
                    is_next_day = False
                if not (is_next_day and d["daily_completed"]):
                    d["daily_streak"] = 0
                d["daily_date"] = today
                d["daily_completed"] = today in d["daily_attempt_dates"]
            else:
                d["daily_completed"] = d["daily_completed"] or today in d["daily_attempt_dates"]
            if d.get("active_theme") not in THEMES or d.get("active_theme") not in d["owned_themes"]:
                d["active_theme"] = "DEFAULT"
            if d.get("active_effect") not in WIN_EFFECTS or d.get("active_effect") not in d["owned_effects"]:
                d["active_effect"] = "RING"
            d["owned_themes"] = [v for v in d["owned_themes"] if v in THEMES] or ["DEFAULT"]
            d["owned_effects"] = [v for v in d["owned_effects"] if v in WIN_EFFECTS] or ["RING"]
            d["unlocked_modes"] = [v for v in d["unlocked_modes"] if v in SPECIAL_MODE_PRICES]
            if candidate == LEGACY_SAVE and candidate != SAVE:
                try:
                    tmp = SAVE.with_suffix(".tmp")
                    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
                    tmp.replace(SAVE)
                except (OSError, TypeError, ValueError):
                    pass
            return d
        except json.JSONDecodeError:
            preserve_corrupt_save(candidate)
            continue
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return default_data()


def save_data():
    global SAVE_ERROR
    try:
        SAVE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SAVE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(SAVE)
        SAVE_ERROR = ""
        return True
    except (OSError, TypeError, ValueError) as exc:
        SAVE_ERROR = str(exc)
        print(f"[SAVE ERROR] Could not save progress to {SAVE}: {exc}")
        return False

data = load_data()

def apply_theme(theme_id):
    """Apply a saved theme to the existing global palette."""
    global BG, PANEL, PANEL2, CYAN, PURPLE, GREEN, ORANGE, RED, YELLOW
    palette = THEMES.get(theme_id, THEMES["DEFAULT"])["palette"]
    BG, PANEL, PANEL2 = palette["BG"], palette["PANEL"], palette["PANEL2"]
    CYAN, PURPLE, GREEN = palette["CYAN"], palette["PURPLE"], palette["GREEN"]
    ORANGE, RED, YELLOW = palette["ORANGE"], palette["RED"], palette["YELLOW"]
    MODE_BASE_COLORS.update({"EASY": GREEN, "MEDIUM": ORANGE, "HARD": PURPLE,
                             "BLITZ": CYAN, "SURVIVAL": YELLOW})
    for mode_key, color in MODE_BASE_COLORS.items():
        MODES[mode_key]["color"] = color

apply_theme(data["active_theme"])

# ----------------------- AUDIO -----------------------
class Audio:
    def __init__(self):
        self.music_on = True
        self.sfx_on = True
        self.music_volume = 0.16
        self.sfx_volume = 0.38
        self.sounds = {}
        self.timer = 0
        self.step = 0
        self.notes = [220, 330, 262, 392, 330, 440, 294, 392]
        if pygame.mixer.get_init():
            self.sounds = {
                "click": self.sequence([660], .045, .20),
                "select": self.sequence([440, 660], .06, .19),
                "higher": self.sequence([290, 380, 490], .065, .22),
                "lower": self.sequence([500, 390, 280], .065, .22),
                "bad": self.sequence([180, 145], .09, .18),
                "win": self.sequence([523, 659, 784, 1047], .11, .28),
                "epic": self.sequence([392, 523, 659, 784, 1047, 1318], .11, .32),
                "lose": self.sequence([440, 370, 294, 220], .12, .22),
                "coin": self.sequence([880, 1175], .05, .18),
                "unlock": self.sequence([659, 784, 988, 1318], .08, .24),
            }

    def sequence(self, notes, duration=.08, volume=.25):
        sr = 44100
        raw = bytearray()
        for freq in notes:
            n = int(sr * duration)
            for i in range(n):
                fade = min(1, i / 180) * min(1, (n-i) / 600)
                sample = math.sin(2 * math.pi * freq * i / sr)
                raw.extend(struct.pack("<h", int(32767 * volume * fade * sample)))
            raw.extend(b"\0\0" * 350)
        try:
            return pygame.mixer.Sound(buffer=bytes(raw))
        except pygame.error:
            return None

    def play(self, name):
        s = self.sounds.get(name)
        if self.sfx_on and s:
            s.set_volume(self.sfx_volume)
            s.play()

    def update(self, dt, state):
        if not self.music_on or not pygame.mixer.get_init():
            return
        self.timer += dt
        interval = .20 if state == "GAME" else .29
        if self.timer >= interval:
            self.timer = 0
            freq = self.notes[self.step % len(self.notes)]
            if state == "GAME":
                freq = int(freq * 1.25)
            s = self.sequence([freq], interval * .7, self.music_volume)
            if s:
                s.play()
            self.step += 1

audio = Audio()

# ----------------------- DRAWING -----------------------
F = {
    "xs": pygame.font.SysFont("consolas", 14),
    "sm": pygame.font.SysFont("consolas", 18),
    "md": pygame.font.SysFont("consolas", 24, bold=True),
    "lg": pygame.font.SysFont("consolas", 38, bold=True),
    "xl": pygame.font.SysFont("consolas", 53, bold=True),
}

def text(s, x, y, size="sm", color=WHITE, center=False):
    image = F[size].render(str(s), True, color)
    r = image.get_rect()
    r.center = (x, y) if center else r.center
    if not center:
        r.topleft = (x, y)
    screen.blit(image, r)
    return r

def panel(rect, border=(53, 66, 111), fill=PANEL, radius=15, width=1):
    pygame.draw.rect(screen, fill, rect, border_radius=radius)
    if width:
        pygame.draw.rect(screen, border, rect, width, border_radius=radius)

def btn(key, label, rect, accent=CYAN, fill=PANEL2):
    r = pygame.Rect(rect)
    hover = r.collidepoint(pygame.mouse.get_pos())
    pygame.draw.rect(screen, fill, r, border_radius=12)
    edge = accent if hover else (61, 73, 112)
    pygame.draw.rect(screen, edge, r, 2 if hover else 1, border_radius=12)
    if hover:
        glow = pygame.Surface((r.width + 10, r.height + 10), pygame.SRCALPHA)
        pulse = int(18 + 14 * (math.sin(ANIM_TIME * 5) + 1) / 2)
        pygame.draw.rect(glow, (*accent, pulse), glow.get_rect(), border_radius=15)
        screen.blit(glow, (r.x - 5, r.y - 5))
    text(label, r.centerx, r.centery, "sm", WHITE, True)
    hitboxes[key] = r

# Small star particles drift gently through the background. Their positions
# persist between frames, so the whole backdrop feels alive without distracting
# from the game UI.
STARS = [
    {"x": random.randrange(W), "y": random.randrange(H),
     "r": random.choice((1, 1, 1, 2, 2, 3)),
     "speed": random.uniform(7.0, 25.0),
     "drift": random.uniform(-5.0, 5.0),
     "phase": random.uniform(0.0, math.tau),
     "twinkle": random.uniform(1.2, 3.5)}
    for _ in range(78)
]


def background(dt=0.0):
    screen.fill(BG)
    line_color = tuple(min(255, channel + 4) for channel in BG)
    for y in range(0, H, 5):
        pygame.draw.line(screen, line_color, (0, y), (W, y))

    # Move each star smoothly; use dt so animation speed stays consistent
    # across different frame rates. Twinkle brightness is intentionally subtle.
    for star in STARS:
        star["x"] += star["drift"] * dt
        star["y"] -= star["speed"] * dt * (1.12 if state == "GAME" else 0.78)
        star["phase"] += star["twinkle"] * dt
        if star["y"] < -4:
            star["y"] = H + random.randrange(4, 45)
            star["x"] = random.randrange(W)
        if star["x"] < -4:
            star["x"] = W + 3
        elif star["x"] > W + 4:
            star["x"] = -3

        shimmer = (math.sin(star["phase"]) + 1.0) / 2.0
        brightness = int(118 + shimmer * 117)
        color = (brightness, brightness, min(255, brightness + 7))
        pos = (int(star["x"]), int(star["y"]))
        pygame.draw.circle(screen, color, pos, star["r"])
        # A few of the larger stars get a faint cross-shaped sparkle.
        if star["r"] >= 3 and shimmer > 0.82:
            pygame.draw.line(screen, (155, 166, 205),
                             (pos[0] - 4, pos[1]), (pos[0] + 4, pos[1]))
            pygame.draw.line(screen, (155, 166, 205),
                             (pos[0], pos[1] - 4), (pos[0], pos[1] + 4))

    # Subtle animated scanline accent adds depth without obscuring text.
    scan_y = int((ANIM_TIME * 42) % H)
    pygame.draw.line(screen, (20, 30, 58), (0, scan_y), (W, scan_y), 1)
    pygame.draw.line(screen, (43, 57, 98), (38, 75), (W-38, 75))

def header(label):
    text("NUMBER//GUESSER", 48, 29, "md", CYAN)
    # Right-align the screen label. Drawing it twice used to leave a clipped
    # duplicate at the far-right edge.
    tag = F["xs"].render(label, True, MUTED)
    screen.blit(tag, (W - 48 - tag.get_width(), 29))

def toast_draw(dt):
    """Draw queued achievement banners at the top, and ordinary notices below."""
    global toast, toast_time, toast_kind, achievement_queue

    if toast_time <= 0 and achievement_queue:
        name = achievement_queue.pop(0)
        toast = name
        toast_kind = "achievement"
        toast_time = 3.4

    if toast_time <= 0:
        return

    toast_time = max(0, toast_time - dt)
    if toast_kind == "achievement":
        # A compact gold banner at the top of the game. The achievement name
        # is included, and queued unlocks each get their own full notification.
        r = pygame.Rect(40, 82, 300, 42)
        panel(r, YELLOW, (48, 39, 22), 10, 2)
        text("*** NEW ACHIEVEMENT! ***", r.centerx, r.y + 12, "xs", YELLOW, True)
        text(toast, r.centerx, r.y + 29, "xs", WHITE, True)
    else:
        r = pygame.Rect(180, H-47, W-360, 32)
        panel(r, CYAN, (27, 47, 69), 8)
        text(toast, r.centerx, r.centery, "xs", WHITE, True)

def notify(s):
    global toast, toast_time, toast_kind
    toast, toast_time, toast_kind = s, 2.7, "normal"

hitboxes = {}
state = "MENU"
mode = "EASY"
secret = 0
tries_left = 0
tries_used = 0
guess = ""
feedback = "Choose a difficulty and find the secret number."
feedback_color = MUTED
base_roll = 0
result = ""
result_points = 0
result_message = ""
toast = ""
toast_time = 0
toast_kind = "normal"
achievement_queue = []
input_active = True
achievements_new = []
known_low = 1
known_high = MODES[mode]["max"]
coins_earned_this_round = 0
coins_lost_this_round = 0
shop_category = "THEMES"
WIN_PARTICLES = []
COIN_PARTICLES = []
FLOATING_TEXT = []
ANIM_TIME = 0.0
round_is_daily = False
round_daily_date = ""
result_coin_animation_started = False

# The reward roll is a short, non-skippable reveal animation.
POINT_ROLL_MS = 2000
COIN_ANIMATION_DELAY_MS = 750
points_revealed = False
points_roll_started = 0
music_slider_dragging = False

HIGHER = ["HIGHER! Give that number a lift.", "TOO LOW! Climb up a little.",
          "UP YOU GO! Try a bigger number.", "HIGHER! That guess needs a boost."]
LOWER = ["LOWER! Bring it back down.", "TOO HIGH! That one overshot.",
         "DOWN YOU GO! Try a smaller number.", "LOWER! Come back to earth."]
WIN_LINES = ["VICTORY IS YOURS!", "YOU GOT IT, CHALLENGER!", "NICE WORK!"]
EPIC_LINES = ["ABSOLUTELY LEGENDARY!", "YOU READ THE MATRIX!", "THAT WAS A MASTERCLASS!"]
PERFECT_LINES = ["PERFECTLY PLAYED!", "NOW THAT'S SKILL!", "A CLEAN WIN!"]
LOSE_LINES = ["THE NUMBER GOT AWAY THIS TIME.", "THE ARCADE BOSS WINS THIS ROUND.",
              "EVERY RUN IS PRACTICE. TRY AGAIN!"]

def unlock(name):
    global achievement_queue
    if name not in data["achievements"]:
        data["achievements"].append(name)
        achievements_new.append(name)
        achievement_queue.append(name)
        audio.play("unlock")
        save_data()

def start_round(which):
    global mode, secret, tries_left, tries_used, guess, feedback, feedback_color
    global base_roll, state, result, result_points, known_low, known_high
    global coins_earned_this_round, coins_lost_this_round
    global WIN_PARTICLES, round_is_daily, round_daily_date
    global DAILY_CHALLENGE, result_coin_animation_started
    if which in SPECIAL_MODE_PRICES and which not in data["unlocked_modes"]:
        notify("Unlock this special mode in the Shop first.")
        return
    mode = which
    today = datetime.date.today().isoformat()
    if data.get("daily_date") != today:
        try:
            previous_day = datetime.date.fromisoformat(data.get("daily_date", ""))
            is_next_day = (datetime.date.today() - previous_day).days == 1
        except ValueError:
            is_next_day = False
        if not (is_next_day and data.get("daily_completed", False)):
            data["daily_streak"] = 0
        data["daily_date"] = today
        data["daily_completed"] = today in data.setdefault("daily_attempt_dates", [])
        save_data()
    if which == "DAILY" and (data.get("daily_completed", False) or today in data.setdefault("daily_attempt_dates", [])):
        data["daily_completed"] = True
        notify("Daily challenge already completed. Come back tomorrow!")
        return
    round_is_daily = which == "DAILY"
    round_daily_date = today if round_is_daily else ""
    if round_is_daily:
        DAILY_CHALLENGE = daily_challenge_for_date(datetime.date.today())
        apply_daily_config(DAILY_CHALLENGE)
    cfg = MODES[mode]
    if round_is_daily:
        today = datetime.date.today().isoformat()
        seed_text = f"NUMBER-GUESSER-DAILY-{today}-{DAILY_CHALLENGE['id']}"
        seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:12], 16)
        daily_rng = random.Random(seed)
        if DAILY_CHALLENGE.get("parity") == "ODD":
            secret = daily_rng.choice(list(range(1, cfg["max"] + 1, 2)))
        elif DAILY_CHALLENGE.get("parity") == "EVEN":
            secret = daily_rng.choice(list(range(2, cfg["max"] + 1, 2)))
        else:
            secret = daily_rng.randint(1, cfg["max"])
    else:
        secret = random.randint(1, cfg["max"])
    tries_left, tries_used, guess = cfg["tries"], 0, ""
    known_low, known_high = 1, cfg["max"]
    feedback, feedback_color = "Type your guess and press ENTER.", MUTED
    base_roll = random.randint(*cfg["range"])
    result, result_points, coins_earned_this_round = "", 0, 0
    coins_lost_this_round = 0
    result_coin_animation_started = False
    WIN_PARTICLES = []
    state = "GAME"
    audio.play("select")

def round_multiplier():
    """Rewards special modes for their intended challenge without changing classics."""
    if mode == "BLITZ":
        return 4 if tries_used <= 2 else 2 if tries_used <= 4 else 1
    if mode == "SURVIVAL":
        return 3 if tries_used <= 3 else 2 if tries_used <= 6 else 1
    return 3 if tries_used <= 3 else 2 if tries_used <= 6 else 1

def prepare_win_particles():
    global WIN_PARTICLES
    palette = [CYAN, PURPLE, GREEN, ORANGE, YELLOW, WHITE]
    WIN_PARTICLES = []
    for _ in range(52):
        WIN_PARTICLES.append({
            "angle": random.uniform(math.pi, 2 * math.pi),
            "speed": random.uniform(75, 245),
            "size": random.choice((2, 3, 4, 5)),
            "color": random.choice(palette),
            "spin": random.uniform(-8, 8),
        })

def xp_for_level(level):
    """XP threshold for the next level; grows steadily, not exponentially."""
    return 100 + max(0, level - 1) * 50

def award_xp(amount):
    old_level = data.get("level", 1)
    data["xp"] = max(0, int(data.get("xp", 0))) + max(0, int(amount))
    while data["xp"] >= xp_for_level(data.get("level", 1)):
        data["xp"] -= xp_for_level(data.get("level", 1))
        data["level"] = data.get("level", 1) + 1
    if data["level"] > old_level:
        notify(f"LEVEL UP! You reached level {data['level']}!")
        audio.play("unlock")

def spawn_coin_animation(amount):
    """Play the bank reward burst on the right, away from the points total."""
    global COIN_PARTICLES, FLOATING_TEXT
    anchor_x, anchor_y = W - 145, 454
    for _ in range(min(18, max(6, amount // 12))):
        COIN_PARTICLES.append({"x": anchor_x + random.randint(-16, 16), "y": anchor_y,
            "vx": random.uniform(-95, 95), "vy": random.uniform(-165, -65),
            "life": random.uniform(.7, 1.25), "age": 0.0})
    FLOATING_TEXT.append({"text": f"+{amount:,} BANK COINS", "x": anchor_x, "y": anchor_y - 22,
                          "age": 0.0, "life": 1.5, "color": YELLOW})

def update_animations(dt):
    for particle in COIN_PARTICLES[:]:
        particle["age"] += dt
        particle["x"] += particle["vx"] * dt
        particle["y"] += particle["vy"] * dt
        particle["vy"] += 250 * dt
        if particle["age"] >= particle["life"]:
            COIN_PARTICLES.remove(particle)
    for item in FLOATING_TEXT[:]:
        item["age"] += dt
        item["y"] -= 28 * dt
        if item["age"] >= item["life"]:
            FLOATING_TEXT.remove(item)

def draw_animations():
    for particle in COIN_PARTICLES:
        pygame.draw.circle(screen, YELLOW, (int(particle["x"]), int(particle["y"])), 3)
        pygame.draw.circle(screen, WHITE, (int(particle["x"])-1, int(particle["y"])-1), 1)
    for item in FLOATING_TEXT:
        fade = max(0.15, 1 - item["age"] / item["life"])
        c = tuple(int(ch * fade) for ch in item["color"])
        text(item["text"], int(item["x"]), int(item["y"]), "md", c, True)

def finish(won):
    global state, result, result_points, result_message
    global points_revealed, points_roll_started, coins_earned_this_round
    global coins_lost_this_round, round_is_daily, round_daily_date
    coins_lost_this_round = 0
    # Tie a daily attempt to the date it started, even if the round crosses midnight.
    today = datetime.date.today().isoformat()
    daily_first_attempt = False
    if round_is_daily:
        challenge_date = round_daily_date or today
        attempt_dates = data.setdefault("daily_attempt_dates", [])
        daily_first_attempt = challenge_date not in attempt_dates
        if challenge_date not in attempt_dates:
            attempt_dates.append(challenge_date)
        data["daily_completed"] = True

    data["games"] += 1
    data["attempts_total"] = data.get("attempts_total", 0) + tries_used
    ms = data.setdefault("mode_stats", {}).setdefault(mode, {"games": 0, "wins": 0, "attempts": 0})
    ms["games"] = int(ms.get("games", 0)) + 1
    ms["attempts"] = int(ms.get("attempts", 0)) + tries_used
    if won:
        data["wins"] += 1
        ms["wins"] = int(ms.get("wins", 0)) + 1
        data["streak"] += 1
        data["best_streak"] = max(data["best_streak"], data["streak"])
        mult = round_multiplier()
        result_points = base_roll * mult
        result = "VICTORY"
        result_message = random.choice(EPIC_LINES if mult >= 3 else PERFECT_LINES if mult == 2 else WIN_LINES)
        audio.play("epic" if mult >= 3 else "win")
        data["score"] += result_points
        data["lifetime_points"] += result_points
        data["personal_best"] = max(data["personal_best"], data["score"])
        # Roll bank coins from a mode-specific band so rewards feel predictable,
        # fair, and separate from the score multiplier.
        coins_earned_this_round = random.randint(*BANK_REWARD_RANGES[mode])
        data["coins"] += coins_earned_this_round
        data["lifetime_coins_earned"] = data.get("lifetime_coins_earned", 0) + coins_earned_this_round
        xp_gain = max(10, result_points // 4) + max(0, MODES[mode]["tries"] - tries_used) * 2
        if round_is_daily:
            xp_gain += 35
            if daily_first_attempt:
                data["daily_streak"] = data.get("daily_streak", 0) + 1
                data["daily_best_streak"] = max(data.get("daily_best_streak", 0), data["daily_streak"])
                daily_bonus = 100
                data["coins"] += daily_bonus
                coins_earned_this_round += daily_bonus
                data["lifetime_coins_earned"] = data.get("lifetime_coins_earned", 0) + daily_bonus
        award_xp(xp_gain)
        prepare_win_particles()
        if data["wins"] == 1: unlock("First Victory")
        if tries_used <= 3: unlock("Quick Thinker")
        if mode == "HARD": unlock("Risk Taker")
        if data["score"] >= 1000: unlock("Point Collector")
        if data["streak"] >= 3: unlock("On Fire")
        if data["streak"] >= 5: unlock("Unstoppable")
    else:
        data["losses"] += 1
        data["streak"] = 0
        award_xp(8)
        if round_is_daily:
            data["daily_streak"] = 0
            data["daily_completed"] = True  # Daily is one attempt per calendar day, win or lose.
        penalty = base_roll
        result_points = -min(data["score"], penalty)
        data["score"] = max(0, data["score"] - penalty)
        # A loss also costs a small, difficulty-based number of bank coins.
        # Never allow a negative bank balance: the deduction is capped by what remains.
        requested_coin_penalty = random.randint(*BANK_LOSS_RANGES[mode])
        coins_lost_this_round = min(data.get("coins", 0), requested_coin_penalty)
        data["coins"] = max(0, data.get("coins", 0) - coins_lost_this_round)
        result = "DEFEAT"
        result_message = random.choice(LOSE_LINES)
        audio.play("lose")
    save_data()
    state = "RESULTS"
    points_revealed = False
    points_roll_started = pygame.time.get_ticks()

def submit():
    global guess, tries_left, tries_used, feedback, feedback_color
    global known_low, known_high
    if not guess.strip():
        feedback, feedback_color = "Type a number first.", ORANGE
        audio.play("bad")
        return
    try:
        n = int(guess)
    except ValueError:
        feedback, feedback_color = "Numbers only, challenger!", ORANGE
        audio.play("bad")
        return
    if not 1 <= n <= MODES[mode]["max"]:
        feedback, feedback_color = f"Choose a number from 1 to {MODES[mode]['max']}.", ORANGE
        audio.play("bad")
        return
    tries_used += 1
    tries_left -= 1
    guess = ""
    if n == secret:
        feedback, feedback_color = "CORRECT! YOU FOUND THE NUMBER!", GREEN
        finish(True)
    elif tries_left == 0:
        if n < secret:
            known_low = max(known_low, n + 1)
        else:
            known_high = min(known_high, n - 1)
        feedback, feedback_color = "NO ATTEMPTS LEFT!", RED
        finish(False)
    elif n < secret:
        known_low = max(known_low, n + 1)
        feedback, feedback_color = random.choice(HIGHER), CYAN
        audio.play("higher")
    else:
        known_high = min(known_high, n - 1)
        feedback, feedback_color = random.choice(LOWER), PURPLE
        audio.play("lower")

def use_hint():
    global known_low, known_high, feedback, feedback_color
    hints = data["inventory"]["hints"]
    if hints <= 0:
        notify("No hints left. Buy a Hint Pack in the Shop between rounds.")
        audio.play("bad")
        return
    span = known_high - known_low + 1
    if span <= 3:
        notify("Your known range is already tiny - save that hint!")
        audio.play("bad")
        return
    data["inventory"]["hints"] -= 1
    if random.random() < 0.5:
        parity = "EVEN" if secret % 2 == 0 else "ODD"
        feedback = f"SMART HINT: THE SECRET IS {parity}."
    else:
        new_size = max(2, int(math.ceil(span * 0.35)))
        new_low = max(known_low, secret - new_size // 2)
        new_high = min(known_high, new_low + new_size - 1)
        new_low = max(known_low, new_high - new_size + 1)
        known_low, known_high = new_low, new_high
        feedback = f"SMART HINT: BETWEEN {known_low} AND {known_high}."
    feedback_color = YELLOW
    audio.play("unlock")
    save_data()

def draw_menu():
    header("RETRO ARCADE / V8.3")
    text("GUESS THE", W//2, 112, "lg", WHITE, True)
    text("NUMBER.", W//2, 164, "xl", CYAN, True)
    text(f"LEVEL {data.get('level', 1)}   |   XP {data.get('xp', 0)}/{xp_for_level(data.get('level', 1))}", W//2, 211, "sm", YELLOW, True)
    panel((315, 258, 370, 78), (40, 125, 144), (19, 39, 62))
    text("CURRENT SCORE", 335, 270, "xs", MUTED)
    text(f"{data['score']:,}", 335, 294, "md", GREEN)
    best_label = F["xs"].render(f"BEST: {data['personal_best']:,}", True, YELLOW)
    screen.blit(best_label, best_label.get_rect(topright=(665, 315)))
    btn("play", "[>] PLAY", (290, 373, 200, 54), CYAN, (27, 62, 78))
    btn("daily", "DAILY CHALLENGE", (510, 373, 200, 54), (255, 120, 210))
    btn("stats", "STATISTICS", (330, 443, 160, 48), PURPLE)
    btn("ach", "ACHIEVEMENTS", (510, 443, 160, 48), YELLOW)
    btn("settings", "AUDIO SETTINGS", (275, 505, 175, 45), CYAN)
    btn("shop", "SHOP / ITEMS", (465, 505, 175, 45), GREEN)
    btn("quit", "QUIT", (655, 505, 120, 45), RED)
    daily_status = "USED - COME BACK TOMORROW" if data.get("daily_completed") else "+100 COINS FOR YOUR FIRST DAILY WIN"
    text(f"DAILY: {DAILY_CHALLENGE['name']}  |  {daily_status}",
         W//2, 579, "xs", GREEN if data.get("daily_completed") else (255, 120, 210), True)
    text(f"DAILY STREAK: {data.get('daily_streak', 0)}", W//2, 605, "xs", MUTED, True)

def draw_difficulty():
    header("SELECT YOUR CHALLENGE")
    text("CHOOSE YOUR MODE", W//2, 116, "lg", WHITE, True)
    text("Bigger ranges bring bigger rewards - and bigger risks.", W//2, 160, "sm", MUTED, True)
    for name, y in [("EASY", 190), ("MEDIUM", 325), ("HARD", 460)]:
        cfg = MODES[name]; c = cfg["color"]
        panel((145, y, 710, 108), c, (21, 26, 52), 16, 2)
        text(name, 175, y+17, "md", c)
        text(f"NUMBER RANGE  1 - {cfg['max']}", 175, y+58, "sm", WHITE)
        text(f"{cfg['tries']} ATTEMPTS", 490, y+26, "sm", WHITE)
        text(f"{cfg['range'][0]}-{cfg['range'][1]} BASE POINTS", 490, y+60, "xs", MUTED)
        btn("mode_"+name, "SELECT", (730, y+30, 100, 46), c)
    btn("back", "< BACK TO MENU", (48, 610, 190, 42), MUTED)
    btn("special_modes", "SPECIAL MODES >", (700, 610, 250, 42), YELLOW)

def draw_game():
    cfg = MODES[mode]
    header(f"DAILY: {DAILY_CHALLENGE['name']}" if mode == "DAILY" else f"{mode} MODE")
    text(f"RANGE  1 - {cfg['max']}", 65, 94, "sm", cfg["color"])
    t = F["sm"].render(f"ATTEMPTS LEFT  {tries_left}/{cfg['tries']}", True, WHITE)
    screen.blit(t, (W-65-t.get_width(), 94))
    bar = pygame.Rect(65, 126, W-130, 8)
    pygame.draw.rect(screen, (43, 49, 79), bar, border_radius=4)
    frac = tries_left / cfg["tries"]
    col = GREEN if frac > .5 else ORANGE if frac > .25 else RED
    pygame.draw.rect(screen, col, (bar.x, bar.y, int(bar.width*frac), bar.height), border_radius=4)
    panel((160, 158, 680, 130), (51, 67, 111), (19, 24, 49), 18)
    text(DAILY_CHALLENGE["description"] if mode == "DAILY" else "A SECRET NUMBER IS WAITING...",
         W//2, 190, "sm", MUTED, True)
    text("What is your guess?", W//2, 238, "lg", WHITE, True)
    box = pygame.Rect(300, 314, 400, 64)
    pygame.draw.rect(screen, (8, 12, 30), box, border_radius=12)
    pygame.draw.rect(screen, CYAN, box, 2, border_radius=12)
    text(guess if guess else "Type a number...", box.centerx, box.centery,
         "md" if guess else "sm", WHITE if guess else (91, 104, 140), True)
    btn("guess", "GUESS  ↵", (390, 393, 220, 50), CYAN, (24, 62, 77))
    text(feedback, W//2, 473, "sm", feedback_color, True)
    panel((270, 526, 460, 44), (42, 51, 86), (20, 25, 51), 10)
    text(f"YOUR SCORE: {data['score']:,}", W//2, 548, "sm", GREEN, True)
    text(f"COINS: {data['coins']:,}", 65, 600, "xs", YELLOW)
    text(f"LV {data.get('level', 1)}  XP {data.get('xp', 0)}/{xp_for_level(data.get('level', 1))}", 265, 600, "xs", CYAN)
    # A round must be completed to prevent leaving mid-game to dodge a loss.
    text("FINISH THE ROUND TO RETURN TO MENU", W//2, 624, "xs", (112, 126, 160), True)
    btn("hint", f"HINT ({data['inventory']['hints']})", (645, 605, 145, 40), YELLOW)
    btn("game_sfx", f"SFX: {'ON' if audio.sfx_on else 'OFF'}", (812, 605, 140, 40), YELLOW)

def draw_special_modes():
    header("SPECIAL MODES")
    text("EXTRA CHALLENGES, EXTRA REWARDS", W//2, 112, "lg", WHITE, True)
    text("Unlock modes with coins in the Shop, then play them whenever you like.",
         W//2, 151, "sm", MUTED, True)
    cards = [
        ("BLITZ", 195, "1-250  |  7 ATTEMPTS  |  60-90 BASE POINTS",
         "x4 for guesses 1-2, x2 for guesses 3-4."),
        ("SURVIVAL", 365, "1-1000  |  9 ATTEMPTS  |  100-140 BASE POINTS",
         "High-risk round. x3 for the first 3 guesses."),
    ]
    for name, y, line1, line2 in cards:
        unlocked = name in data["unlocked_modes"]
        color = MODES[name]["color"] if unlocked else MUTED
        panel((105, y, 790, 130), color, (21, 26, 52), 16, 2)
        text(name, 135, y+18, "md", color)
        text(line1, 135, y+55, "sm", WHITE)
        text(line2, 135, y+85, "xs", MUTED)
        if unlocked:
            btn("special_play_"+name, "PLAY MODE", (720, y+42, 145, 48), color)
        else:
            price = SPECIAL_MODE_PRICES[name]
            btn("special_buy_"+name, f"UNLOCK {price}", (720, y+42, 145, 48), YELLOW)
    btn("special_back", "< BACK TO DIFFICULTY", (48, 610, 255, 42), MUTED)
    btn("special_shop", "OPEN SHOP", (790, 610, 160, 42), GREEN)

def shop_catalog(category):
    if category == "THEMES":
        return [{"id": k, "name": v["name"], "price": v["price"],
                 "desc": "Change game colors.", "kind": "theme"}
                for k, v in THEMES.items()]
    if category == "WIN EFFECTS":
        return [{"id": k, "name": v["name"], "price": v["price"],
                 "desc": "New victory animation.", "kind": "effect"}
                for k, v in WIN_EFFECTS.items()]
    if category == "ITEMS":
        return [
            {"id": "HINT_PACK", "name": "Hint Pack x3", "price": 150,
             "desc": "Adds 3 hints.", "kind": "item"},
            {"id": "HINT_CRATE", "name": "Hint Crate x10", "price": 390,
             "desc": "Adds 10 hints; best value.", "kind": "item"},
        ]
    if category == "SPECIAL MODES":
        return [{"id": k, "name": k.title(), "price": price,
                 "desc": "Fast pace, 7 attempts." if k == "BLITZ" else "High reward, 9 tries.", "kind": "mode"}
                for k, price in SPECIAL_MODE_PRICES.items()]
    return []

def shop_item_state(item):
    item_id, kind = item["id"], item["kind"]
    if kind == "theme":
        owned = item_id in data["owned_themes"]
        if not owned: return f"BUY {item['price']}"
        return "EQUIPPED" if item_id == data["active_theme"] else "EQUIP"
    if kind == "effect":
        owned = item_id in data["owned_effects"]
        if not owned: return f"BUY {item['price']}"
        return "EQUIPPED" if item_id == data["active_effect"] else "EQUIP"
    if kind == "mode":
        return "UNLOCKED" if item_id in data["unlocked_modes"] else f"BUY {item['price']}"
    return f"BUY {item['price']}"

def draw_shop():
    header("ARCADE SHOP")
    text("MAKE YOUR POINTS COUNT", W//2, 100, "lg", WHITE, True)
    bank = F["sm"].render(f"BANK {data['coins']:,}", True, YELLOW)
    screen.blit(bank, bank.get_rect(topright=(950, 105)))
    for i, category in enumerate(SHOP_CATEGORIES):
        x = 70 + i*215
        accent = CYAN if category == shop_category else MUTED
        btn("shop_tab_"+category, category, (x, 142, 195, 40), accent,
            (27, 49, 72) if category == shop_category else PANEL2)
    items = shop_catalog(shop_category)
    for i, item in enumerate(items):
        col, row = i % 2, i // 2
        x, y = 70 + col*435, 202 + row*108
        owned = (item["id"] in data["owned_themes"] if item["kind"] == "theme" else
                 item["id"] in data["owned_effects"] if item["kind"] == "effect" else
                 item["id"] in data["unlocked_modes"] if item["kind"] == "mode" else False)
        active = ((item["kind"] == "theme" and item["id"] == data["active_theme"]) or
                  (item["kind"] == "effect" and item["id"] == data["active_effect"]))
        accent = GREEN if active else CYAN if owned else (65, 78, 116)
        panel((x, y, 405, 94), accent, (20, 26, 52), 12, 2 if active else 1)
        text(item["name"], x+14, y+12, "sm", WHITE)
        text(item["desc"], x+14, y+50, "xs", MUTED)
        action = shop_item_state(item)
        action_color = GREEN if action in ("EQUIPPED", "UNLOCKED") else YELLOW if action == "EQUIP" else CYAN
        btn("shop_item_"+item["id"], action, (x+258, y+25, 132, 42), action_color)
    btn("shop_back", "< BACK TO MENU", (48, 590, 205, 44), MUTED)

def buy_shop_item(item_id):
    item = next((entry for category in SHOP_CATEGORIES for entry in shop_catalog(category)
                 if entry["id"] == item_id), None)
    if item is None:
        return
    kind, item_id, price = item["kind"], item["id"], item["price"]
    if kind == "theme" and item_id in data["owned_themes"]:
        data["active_theme"] = item_id
        apply_theme(item_id)
        notify(f"Theme equipped: {THEMES[item_id]['name']}.")
        audio.play("select")
    elif kind == "effect" and item_id in data["owned_effects"]:
        data["active_effect"] = item_id
        notify(f"Win effect equipped: {WIN_EFFECTS[item_id]['name']}.")
        audio.play("select")
    elif kind == "mode" and item_id in data["unlocked_modes"]:
        notify(f"{item['name']} is already unlocked.")
        return
    else:
        if data["coins"] < price:
            notify(f"Not enough coins. You need {price - data['coins']} more.")
            audio.play("bad")
            return
        data["coins"] -= price
        data["lifetime_coins_spent"] = data.get("lifetime_coins_spent", 0) + price
        if kind == "theme":
            data["owned_themes"].append(item_id)
            data["active_theme"] = item_id
            apply_theme(item_id)
            notify(f"Theme unlocked and equipped: {THEMES[item_id]['name']}!")
            audio.play("unlock")
        elif kind == "effect":
            data["owned_effects"].append(item_id)
            data["active_effect"] = item_id
            notify(f"Win effect unlocked: {WIN_EFFECTS[item_id]['name']}!")
            audio.play("unlock")
        elif kind == "item":
            amount = 3 if item_id == "HINT_PACK" else 10
            data["inventory"]["hints"] += amount
            notify(f"Purchased {amount} hints. Total: {data['inventory']['hints']}.")
            audio.play("coin")
        elif kind == "mode":
            data["unlocked_modes"].append(item_id)
            notify(f"{item['name']} mode unlocked! Find it under Special Modes.")
            audio.play("unlock")
    save_data()

def draw_win_effect(age):
    """Draw the currently equipped, deterministic win celebration."""
    if result != "VICTORY" or age < 0:
        return
    center = (W//2, 298)
    effect = data.get("active_effect", "RING")
    if effect == "RING":
        duration = 1100
        progress = min(1.0, age / duration)
        radius = 38 + int(progress * 105)
        alpha = max(0, int(255 * (1.0 - progress)))
        if alpha > 0:
            glow = pygame.Surface((W, H), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 255, 255, alpha), center, radius, width=4)
            screen.blit(glow, (0, 0))
    elif effect == "STARBURST":
        progress = min(1.0, age / 1450)
        radius = 12 + int(progress * 155)
        shrink = max(0.0, 1.0 - progress)
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(24):
            angle = math.tau * i / 24
            inner = max(0, radius - 26)
            outer = radius + (i % 3) * 7
            color = [CYAN, PURPLE, GREEN, YELLOW][i % 4]
            alpha = int(220 * shrink)
            pygame.draw.line(overlay, (*color, alpha),
                (center[0] + int(math.cos(angle)*inner), center[1] + int(math.sin(angle)*inner)),
                (center[0] + int(math.cos(angle)*outer), center[1] + int(math.sin(angle)*outer)), 3)
        screen.blit(overlay, (0, 0))
    elif effect == "CONFETTI":
        if age >= 1650:
            return
        t = age / 1000
        fade = max(0.0, 1.0 - age / 1650)
        gravity = 175
        for particle in WIN_PARTICLES:
            vx = math.cos(particle["angle"]) * particle["speed"]
            vy = math.sin(particle["angle"]) * particle["speed"]
            x = center[0] + vx*t
            y = center[1] + vy*t + 0.5*gravity*t*t
            if -12 <= x <= W+12 and -12 <= y <= H+12:
                size = particle["size"]
                rect = pygame.Rect(int(x), int(y), size*2, size)
                dimmed = tuple(int(channel * fade) for channel in particle["color"])
                pygame.draw.rect(screen, dimmed, rect, border_radius=1)

def draw_results():
    global points_revealed, result_coin_animation_started
    header("ROUND COMPLETE")
    won = result == "VICTORY"
    color = GREEN if won else RED
    elapsed = pygame.time.get_ticks() - points_roll_started
    rolling = elapsed < POINT_ROLL_MS
    if not rolling and (not won or elapsed >= POINT_ROLL_MS + COIN_ANIMATION_DELAY_MS):
        points_revealed = True
    if not rolling:
        if (won and not result_coin_animation_started
                and elapsed >= POINT_ROLL_MS + COIN_ANIMATION_DELAY_MS):
            # Let the final points total land before the separate bank-coin feedback.
            spawn_coin_animation(coins_earned_this_round)
            result_coin_animation_started = True

    text("VICTORY!" if won else "GAME OVER", W//2, 105, "xl", color, True)
    text(result_message, W//2, 157, "sm", WHITE, True)
    panel((225, 190, 550, 230), color, (20, 26, 52), 20, 2)
    text(f"SECRET NUMBER: {secret}", W//2, 218, "sm", MUTED, True)

    if rolling:
        low, high = MODES[mode]["range"]
        elapsed_now = pygame.time.get_ticks()
        step = max(1, (elapsed_now - points_roll_started) // 65)
        shown_base = random.randint(low, high) if step % 2 == 0 else low + (step * 7) % (high-low+1)
        text("ROLLING YOUR BASE REWARD..." if won else "CALCULATING ROUND PENALTY...",
             W//2, 260, "xs", YELLOW, True)
        text(f"{shown_base} POINTS", W//2, 298, "lg", WHITE, True)
        sweep = (elapsed * 0.36) % 360
        orbit_x = W//2 + int(142 * math.cos(math.radians(sweep)))
        orbit_y = 298 + int(29 * math.sin(math.radians(sweep)))
        pygame.draw.circle(screen, WHITE, (orbit_x, orbit_y), 4)
        text("PLEASE WAIT - REVEAL IN PROGRESS", W//2, 348, "xs", MUTED, True)
    else:
        age = max(0, elapsed - POINT_ROLL_MS)
        draw_win_effect(age)
        text("BASE REWARD REVEALED!" if won else "PENALTY REVEALED!",
             W//2, 260, "xs", YELLOW, True)
        text(f"{base_roll} POINTS", W//2, 298, "lg", WHITE, True)
        if won:
            mult = round_multiplier()
            text(f"MULTIPLIER: x{mult}", W//2, 340, "sm", YELLOW, True)
            text(f"+{result_points:,} POINTS", W//2, 382, "md", GREEN, True)
            text(f"+{coins_earned_this_round:,} BANK COINS", W//2, 405, "xs", YELLOW, True)
        else:
            text(f"-{abs(result_points):,} POINTS", W//2, 370, "md", RED, True)
            text(f"-{coins_lost_this_round:,} BANK COINS", W//2, 400, "xs", ORANGE, True)
        text(f"BANK BALANCE: {data['coins']:,}", W//2, 432, "xs", YELLOW, True)

    if points_revealed:
        text(f"CURRENT SCORE: {data['score']:,}", W//2, 462, "md", CYAN, True)
        text(f"STREAK: {data['streak']}     BEST STREAK: {data['best_streak']}",
             W//2, 497, "sm", MUTED, True)
    else:
        message = ("BANK COINS FOLLOW AFTER YOUR POINTS..."
                   if not rolling and won else "YOUR TOTAL WILL APPEAR AFTER THE REVEAL")
        text(message, W//2, 475, "xs", MUTED, True)

    if points_revealed:
        if round_is_daily:
            # Daily is one attempt per date, whether won or lost: no replay button.
            btn("result_menu", "MAIN MENU", (395, 550, 210, 50), PURPLE)
        else:
            btn("again", "PLAY AGAIN", (265, 550, 210, 50), CYAN, (25, 66, 78))
            btn("result_menu", "MAIN MENU", (505, 550, 210, 50), PURPLE)
    else:
        if round_is_daily:
            panel((395, 550, 210, 50), (58, 66, 93), (26, 30, 50), 12)
            text("MAIN MENU", 500, 575, "sm", (91, 99, 126), True)
        else:
            panel((265, 550, 210, 50), (58, 66, 93), (26, 30, 50), 12)
            panel((505, 550, 210, 50), (58, 66, 93), (26, 30, 50), 12)
            text("PLAY AGAIN", 370, 575, "sm", (91, 99, 126), True)
            text("MAIN MENU", 610, 575, "sm", (91, 99, 126), True)
        text("Navigation unlocks after the result is revealed.", W//2, 622, "xs", MUTED, True)

def draw_stats():
    header("PLAYER STATISTICS")
    text("YOUR ARCADE RECORD", W//2, 96, "lg", WHITE, True)
    games = max(0, int(data.get("games", 0)))
    wins = max(0, int(data.get("wins", 0)))
    win_rate = (wins / games * 100) if games else 0.0
    avg_attempts = data.get("attempts_total", 0) / games if games else 0.0
    cards = [
        ("CURRENT SCORE", f"{data['score']:,}", GREEN),
        ("PERSONAL BEST", f"{data['personal_best']:,}", YELLOW),
        ("GAMES PLAYED", games, CYAN),
        ("WIN RATE", f"{win_rate:.1f}%", GREEN),
        ("WINS / LOSSES", f"{wins} / {data['losses']}", PURPLE),
        ("AVG. ATTEMPTS", f"{avg_attempts:.1f}", CYAN),
        ("COIN BALANCE", f"{data['coins']:,}", YELLOW),
        ("LIFETIME POINTS", f"{data['lifetime_points']:,}", CYAN),
        ("LIFETIME COINS EARNED", f"{data.get('lifetime_coins_earned', 0):,}", GREEN),
        ("LIFETIME COINS SPENT", f"{data.get('lifetime_coins_spent', 0):,}", ORANGE),
        ("PLAYER LEVEL", str(data.get("level", 1)), YELLOW),
        ("BEST DAILY STREAK", str(data.get("daily_best_streak", 0)), (255, 120, 210)),
    ]
    for i, (label, value, color) in enumerate(cards):
        x, y = 55+(i%3)*300, 130+(i//3)*88
        panel((x, y, 280, 72), color, (22, 28, 56), 12)
        text(label, x+12, y+8, "xs", MUTED)
        text(value, x+12, y+33, "md", color)
    text("MODE RECORDS  (WINS / GAMES)", W//2, 493, "sm", WHITE, True)
    mode_names = ("EASY", "MEDIUM", "HARD", "BLITZ", "SURVIVAL", "DAILY")
    for i, name in enumerate(mode_names):
        st = data.get("mode_stats", {}).get(name, {})
        games_for_mode = int(st.get("games", 0) or 0)
        wins_for_mode = int(st.get("wins", 0) or 0)
        rate = 100 * wins_for_mode / games_for_mode if games_for_mode else 0
        value = f"{name}  {wins_for_mode}/{games_for_mode}  ({rate:.0f}%)" if games_for_mode else f"{name}  --"
        col, row = i % 3, i // 3
        text(value, 205 + col * 295, 520 + row * 27, "xs", MUTED, True)
    btn("stats_back", "< BACK TO MENU", (48, 600, 205, 42), MUTED)
    btn("reset", "RESET SAVE DATA", (730, 600, 220, 42), RED)

def draw_achievements():
    header("ACHIEVEMENT VAULT")
    text("UNLOCK YOUR LEGACY", W//2, 112, "lg", WHITE, True)
    achievements = [
        ("First Victory", "Win your first round."),
        ("Quick Thinker", "Win in 3 guesses or fewer."),
        ("Risk Taker", "Win a Hard round."),
        ("Point Collector", "Reach 1,000 total points."),
        ("On Fire", "Win 3 rounds in a row."),
        ("Unstoppable", "Win 5 rounds in a row."),
    ]
    for i, (name, desc) in enumerate(achievements):
        x, y = 95+(i%2)*420, 175+(i//2)*115
        unlocked = name in data["achievements"]
        c = YELLOW if unlocked else (67, 75, 108)
        panel((x, y, 390, 90), c, (22, 28, 56), 13)
        text(("* " if unlocked else "  ")+name, x+18, y+15, "sm", c)
        text(desc, x+18, y+52, "xs", MUTED)
        status = F["xs"].render("UNLOCKED" if unlocked else "LOCKED", True, GREEN if unlocked else MUTED)
        screen.blit(status, status.get_rect(topright=(x+374, y+12)))
    btn("ach_back", "< BACK TO MENU", (48, 570, 205, 46), MUTED)

def draw_settings():
    header("AUDIO SETTINGS")
    text("TUNE YOUR ARCADE", W//2, 130, "lg", WHITE, True)
    panel((205, 190, 590, 300), (55, 69, 112), (22, 28, 56), 18)
    text("BACKGROUND MUSIC", 250, 230, "md", CYAN)
    btn("music_toggle", "ON" if audio.music_on else "OFF", (640, 215, 100, 44), CYAN)
    text("SOUND EFFECTS", 250, 300, "md", PURPLE)
    btn("sfx_toggle", "ON" if audio.sfx_on else "OFF", (640, 285, 100, 44), PURPLE)
    text(f"MUSIC VOLUME  {int(audio.music_volume*200)}%", 250, 360, "sm", MUTED)
    track = pygame.Rect(250, 405, 490, 6)
    pygame.draw.line(screen, (68, 81, 121), track.midleft, track.midright, 5)
    knob_x = 250 + int(490*audio.music_volume/.5)
    pygame.draw.line(screen, CYAN, track.midleft, (knob_x, track.centery), 5)
    pygame.draw.circle(screen, WHITE, (knob_x, track.centery), 9)
    text("Drag the slider smoothly to adjust volume.", W//2, 447, "xs", MUTED, True)
    btn("settings_back", "< BACK TO MENU", (48, 570, 205, 46), MUTED)

def draw_reset():
    header("CONFIRM RESET")
    panel((200, 220, 600, 220), RED, (28, 24, 48), 20, 2)
    text("RESET ALL PROGRESS?", W//2, 270, "lg", RED, True)
    text("Score, statistics, and achievements will be deleted.", W//2, 320, "sm", WHITE, True)
    text("This cannot be undone.", W//2, 350, "sm", MUTED, True)
    btn("confirm_reset", "YES, RESET", (275, 375, 190, 45), RED)
    btn("cancel_reset", "CANCEL", (535, 375, 190, 45), CYAN)

def set_music_volume_from_x(x):
    # Clamp the knob to the slider ends; 0.0-0.5 maps to 0-100% UI volume.
    audio.music_volume = max(0.0, min(0.5, ((x - 250) / 490) * 0.5))

def click(pos):
    global state, data, music_slider_dragging, shop_category
    if state == "RESULTS" and not points_revealed:
        return
    for key, rect in list(hitboxes.items()):
        if rect.collidepoint(pos):
            audio.play("click")
            if key == "play": state = "DIFFICULTY"
            elif key == "daily":
                if data.get("daily_completed", False):
                    notify("Daily challenge already completed. Come back tomorrow!")
                else:
                    start_round("DAILY")
            elif key.startswith("mode_"): start_round(key[5:])
            elif key == "back": state = "MENU"
            elif key == "stats": state = "STATS"
            elif key == "ach": state = "ACHIEVEMENTS"
            elif key == "settings": state = "SETTINGS"
            elif key == "shop": shop_category = "THEMES"; state = "SHOP"
            elif key == "quit": pygame.event.post(pygame.event.Event(pygame.QUIT))
            elif key == "guess": submit()
            elif key == "hint": use_hint()
            elif key == "game_sfx": audio.sfx_on = not audio.sfx_on
            elif key == "again": start_round(mode)
            elif key == "result_menu": state = "MENU"
            elif key in ("stats_back", "ach_back", "settings_back"): state = "MENU"
            elif key == "shop_back": state = "MENU"
            elif key.startswith("shop_tab_"):
                shop_category = key[len("shop_tab_"):]
            elif key.startswith("shop_item_"):
                buy_shop_item(key[len("shop_item_"):])
            elif key == "special_modes": state = "SPECIAL_MODES"
            elif key == "special_back": state = "DIFFICULTY"
            elif key == "special_shop": shop_category = "SPECIAL MODES"; state = "SHOP"
            elif key.startswith("special_play_"): start_round(key[len("special_play_"):])
            elif key.startswith("special_buy_"):
                shop_category = "SPECIAL MODES"
                state = "SHOP"
                notify("Unlock special modes here with your coins.")
            elif key == "music_toggle": audio.music_on = not audio.music_on
            elif key == "sfx_toggle": audio.sfx_on = not audio.sfx_on
            elif key == "reset": state = "RESET"
            elif key == "confirm_reset":
                data = default_data()
                data["daily_date"] = datetime.date.today().isoformat()
                apply_theme("DEFAULT")
                save_data()
                state = "STATS"
                notify("Save data reset.")
            elif key == "cancel_reset": state = "STATS"
            return
    if state == "SETTINGS" and pygame.Rect(240, 390, 510, 36).collidepoint(pos):
        music_slider_dragging = True
        set_music_volume_from_x(pos[0])

running = True
while running:
    refresh_daily_if_needed()
    dt = min(0.05, clock.tick(FPS)/1000)
    ANIM_TIME += dt
    update_animations(dt)
    audio.update(dt, state)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            if state == "GAME" and tries_used > 0:
                finish(False)
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if state == "SETTINGS" and pygame.Rect(240, 390, 510, 36).collidepoint(event.pos):
                music_slider_dragging = True
                set_music_volume_from_x(event.pos[0])
            else:
                click(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            music_slider_dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if music_slider_dragging and state == "SETTINGS":
                set_music_volume_from_x(event.pos[0])
        elif event.type == pygame.KEYDOWN:
            if state == "GAME":
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): submit()
                elif event.key == pygame.K_BACKSPACE: guess = guess[:-1]
                # Escape is intentionally ignored during a live round.
                elif event.unicode.isdigit() and len(guess) < 5: guess += event.unicode
            elif state == "RESULTS" and not points_revealed:
                pass
            elif event.key == pygame.K_ESCAPE:
                if state != "MENU": state = "MENU"


    hitboxes = {}
    background(dt)
    if state == "MENU": draw_menu()
    elif state == "DIFFICULTY": draw_difficulty()
    elif state == "GAME": draw_game()
    elif state == "RESULTS": draw_results()
    elif state == "STATS": draw_stats()
    elif state == "ACHIEVEMENTS": draw_achievements()
    elif state == "SETTINGS": draw_settings()
    elif state == "RESET": draw_reset()
    elif state == "SHOP": draw_shop()
    elif state == "SPECIAL_MODES": draw_special_modes()
    draw_animations()
    toast_draw(dt)
    if SAVE_ERROR:
        text("WARNING: PROGRESS COULD NOT BE SAVED", W//2, H-12, "xs", RED, True)
    pygame.display.flip()

save_data()
pygame.quit()
sys.exit()
