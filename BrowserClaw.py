import os
import sys
import warnings
import ctypes
import ctypes.wintypes
import importlib
import importlib.util
import subprocess
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

# MUST run BEFORE importing pyautogui / mss / tkinter so physical pixel coordinates match 1:1
if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

REQUIRED_PACKAGES = {
    "rich": "rich",
    "playwright": "playwright",
    "pyautogui": "pyautogui",
    "mss": "mss",
    "PIL": "pillow",
}


def get_missing_packages() -> list[str]:
    importlib.invalidate_caches()
    return [
        pkg for mod, pkg in REQUIRED_PACKAGES.items()
        if importlib.util.find_spec(mod) is None
    ]


def is_admin() -> bool:
    if os.name == "nt":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except Exception:
        return False


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.wintypes.ULONG),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.wintypes.LPCWSTR),
        ("lpFile", ctypes.wintypes.LPCWSTR),
        ("lpParameters", ctypes.wintypes.LPCWSTR),
        ("lpDirectory", ctypes.wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.wintypes.LPCWSTR),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


def run_admin_installer_and_wait() -> bool:
    if os.name != "nt":
        return False
    script_path = str(Path(__file__).resolve())
    params = subprocess.list2cmdline([script_path, "--install-only"])

    sei = _SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    sei.fMask = 0x00000040
    sei.hwnd = None
    sei.lpVerb = "runas"
    sei.lpFile = sys.executable
    sei.lpParameters = params
    sei.lpDirectory = str(BASE_DIR)
    sei.nShow = 1

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return False

    if sei.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return True


def _pip_install_packages(packages: list[str]):
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "--user", *packages])
    if rc != 0:
        subprocess.call([sys.executable, "-m", "pip", "install", "--break-system-packages", *packages])


def handle_dependencies():
    install_only = "--install-only" in sys.argv
    missing = get_missing_packages()

    if not missing:
        if install_only:
            sys.exit(0)
        return

    if install_only:
        print("====================================================")
        print(" BrowserClaw - Installing Libraries (Administrator)")
        print("====================================================")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            sys.exit(0)
        except subprocess.CalledProcessError as e:
            print(f"\nInstallation failed (exit code {e.returncode}).")
            input("Press ENTER to close...")
            sys.exit(e.returncode)

    print("====================================================")
    print(" BrowserClaw - Missing Python Libraries Detected")
    print("====================================================")
    print("Missing packages:", ", ".join(missing))
    ans = input("\nInstall them now? [Y/n]: ").strip().lower()

    if ans not in ("", "y", "yes"):
        print("Cannot start BrowserClaw without required libraries. Exiting.")
        sys.exit(1)

    if os.name == "nt" and not is_admin():
        print("\nRequesting Administrator permission to install packages...")
        ok = run_admin_installer_and_wait()
        if not ok:
            print("[!] Admin elevation declined. Trying standard user pip install...")
            _pip_install_packages(missing)
    else:
        _pip_install_packages(missing)

    still_missing = get_missing_packages()
    if still_missing:
        print(f"\nStill missing: {', '.join(still_missing)}")
        print(f"Run manually: pip install {' '.join(still_missing)}")
        input("Press ENTER to exit...")
        sys.exit(1)

    print("\nLibraries installed! Opening BrowserClaw normally...\n")


handle_dependencies()

import io
import re
import json
import math
import time
import random
import socket
import base64
import shutil
import zipfile
import datetime
import platform
import urllib.request
import threading

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import termios
    import tty
    import select
except ImportError:
    termios = None
    tty = None
    select = None

try:
    import tkinter as tk
except ImportError:
    tk = None

import mss
import pyautogui
from PIL import Image, ImageDraw
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.live import Live
from rich import box
from playwright.sync_api import sync_playwright

pyautogui.FAILSAFE = False  # Handled explicitly via real-user cursor check so AI clicks near (0,0) never false-trigger
pyautogui.PAUSE = 0.01

console = Console()
CONFIG_FILE = BASE_DIR / "browserclaw_config.json"
PROFILES_ROOT = BASE_DIR / "browserclaw_profiles"
GEMINI_URL = "https://gemini.google.com/app"
CONFIG_VERSION = 25

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "browser": "msedge",
    "agent_mode": "NORMAL",          # NORMAL | SELF_AWARE
    "debug_mode": False,             # False = Clean CMD | True = Show Bridge, AI Reply, Steps & Results
    "allow_tts": False,              # False = TTS completely removed | True = Allow speak_tts tool
    "gemini_model": "AUTO",          # AUTO | HYDROGEN | KEEP
    "connect_mode": "EDGE_GEMINI",   # EDGE_GEMINI | LIVE_ATTACH
    "vision_mode": "ALWAYS",         # ALWAYS | SMART_CHECK | OFF
    "safety_mode": "AUTO",           # AUTO | CONFIRM
    "virtual_cursor": True,          # Independent visible AI cursor overlay (moves itself, never follows user)
    "vision_grid": True,             # Draw 0..1000 coordinate grid on AI screenshots
    "hide_browser": True,            # Keep Gemini browser off-screen & active
    "hide_cmd_while_running": False, # Keep terminal visible
    "always_new_chat": False,        # Resume existing chat across reopens & messages
    "last_chat_url": "",             # Saved conversation URL (/app/<id>)
    "max_steps": 30,
    "screen_width": 1280,
    "screen_height": 720,
}

GEMINI_ERROR_PHRASES = (
    "encountered an error",
    "could you try again",
    "having a hard time fulfilling",
    "can i help you with something else",
    "seem to be encountering an error",
    "something went wrong",
    "i cannot fulfill this request",
    "i can't fulfill this request",
    "unable to process your request",
    "try again later",
)

OS_NAME_LABEL = "Windows" if os.name == "nt" else "Linux"


def get_physical_screen_size() -> tuple[int, int]:
    """Always returns true physical screen pixels matching mss screenshot coordinates 1:1."""
    if os.name == "nt":
        try:
            w = int(ctypes.windll.user32.GetSystemMetrics(0))
            h = int(ctypes.windll.user32.GetSystemMetrics(1))
            if w > 0 and h > 0:
                return w, h
        except Exception:
            pass
    try:
        with mss.MSS() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return int(mon["width"]), int(mon["height"])
    except Exception:
        try:
            sw, sh = pyautogui.size()
            return int(sw), int(sh)
        except Exception:
            return 1920, 1080


def build_tools_reference(cfg: dict, self_aware: bool = False) -> str:
    tts_line = '\n- {"tool": "speak_tts", "text": "Hello!"}' if cfg.get("allow_tts", False) else ""
    app_launch_tools = (
        """- {"tool": "show_desktop"}  <-- Minimizes/shows the Desktop so you can see and double-click Desktop icons!
- {"tool": "open_desktop_icon", "name": "Discord"}  <-- Shows Desktop, locates the icon by name, moves AI cursor to it, and double-clicks it!
- {"tool": "mouse_double_click", "x": 120, "y": 240}  <-- Double-clicks directly on a visible Desktop shortcut/icon to open it!
- {"tool": "hotkey_win_search", "query": "Discord", "press_enter": true}  <-- Opens Start/App Menu Search, visibly types the app/game name, and launches it if not on Desktop
- {"tool": "browser_goto", "url": "https://www.youtube.com"}  <-- Clicks browser address bar (Ctrl+L) and visibly types the URL
- {"tool": "browser_search", "query": "geometry dash extreme demon"}  <-- Clicks browser address bar (Ctrl+L) and visibly searches
- {"tool": "discord_quick_switcher", "query": "general"}
- {"tool": "window_list"}
- {"tool": "window_focus", "title": "Discord"}
- {"tool": "window_minimize", "title": "Discord"}
- {"tool": "window_maximize", "title": "Discord"}
- {"tool": "window_restore", "title": "Discord"}
- {"tool": "window_close", "title": "Discord"}"""
        if self_aware else
        """- {"tool": "discover_apps"}
- {"tool": "open_desktop_icon", "name": "Discord"}
- {"tool": "launch_smart_app", "app": "discord"}
- {"tool": "open_app", "target": "steam"}
- {"tool": "open_url", "url": "https://www.youtube.com"}
- {"tool": "browser_goto", "url": "https://www.roblox.com"}
- {"tool": "browser_search", "query": "geometry dash extreme demon"}
- {"tool": "discord_quick_switcher", "query": "general"}
- {"tool": "window_list"}
- {"tool": "window_focus", "title": "Discord"}
- {"tool": "window_minimize", "title": "Discord"}
- {"tool": "window_maximize", "title": "Discord"}
- {"tool": "window_restore", "title": "Discord"}
- {"tool": "window_close", "title": "Discord"}
- {"tool": "window_snap_left", "title": "Discord"}
- {"tool": "window_snap_right", "title": "Chrome"}
- {"tool": "window_move_resize", "title": "Discord", "x": 100, "y": 100, "w": 1100, "h": 750}"""
    )

    return f"""AVAILABLE JSON COMMANDS (x, y are normalized 0..1000 matching the attached screenshot grid):
Vision & UI Inspection (use ui_list_elements / ui_click_name when a button is tiny or hard to hit):
- {{"tool": "take_screenshot"}}
- {{"tool": "screenshot_region", "x1": 0, "y1": 0, "x2": 500, "y2": 500}}
- {{"tool": "get_pixel_color", "x": 500, "y": 500}}
- {{"tool": "get_screen_info"}}
- {{"tool": "ui_list_elements", "window_title": ""}}
- {{"tool": "ui_click_name", "name": "Play"}}

Independent AI Mouse (0..1000 screen grid — moves itself independently, aim directly at the CENTER of the button/icon/text box):
- {{"tool": "mouse_move", "x": 500, "y": 300}}
- {{"tool": "mouse_move_relative", "dx": 50, "dy": -30}}
- {{"tool": "mouse_click", "x": 500, "y": 300, "button": "left"}}
- {{"tool": "mouse_double_click", "x": 500, "y": 300}}
- {{"tool": "mouse_right_click", "x": 500, "y": 300}}
- {{"tool": "mouse_middle_click", "x": 500, "y": 300}}
- {{"tool": "mouse_triple_click", "x": 500, "y": 300}}
- {{"tool": "mouse_down", "x": 500, "y": 300, "button": "left"}}
- {{"tool": "mouse_up", "x": 500, "y": 300, "button": "left"}}
- {{"tool": "mouse_drag", "x1": 200, "y1": 200, "x2": 600, "y2": 400, "button": "left"}}
- {{"tool": "mouse_scroll", "x": 500, "y": 500, "clicks": -500}}
- {{"tool": "mouse_hscroll", "x": 500, "y": 500, "clicks": 400}}
- {{"tool": "mouse_circle", "x": 500, "y": 500, "radius": 80}}
- {{"tool": "mouse_wiggle"}}
- {{"tool": "get_cursor_pos"}}
- {{"tool": "click_taskbar_icon", "slot": 1}}

Keyboard & Typing (typed out character-by-character like a real human):
- {{"tool": "type_text", "text": "yo whats up", "press_enter": true}}
- {{"tool": "press_key", "keys": ["enter"]}}
- {{"tool": "key_down", "key": "w"}}
- {{"tool": "key_up", "key": "w"}}
- {{"tool": "hotkey_win_search", "query": "Minecraft", "press_enter": true}}
- {{"tool": "select_all_copy"}}
- {{"tool": "select_all_delete"}}
- {{"tool": "undo"}}
- {{"tool": "redo"}}
- {{"tool": "save_shortcut"}}
- {{"tool": "find_shortcut"}}
- {{"tool": "new_tab_shortcut"}}
- {{"tool": "close_tab_shortcut"}}
- {{"tool": "refresh_shortcut"}}
- {{"tool": "switch_app"}}
- {{"tool": "close_active_window"}}
- {{"tool": "show_desktop"}}

Apps, Discord, Games, Browser & Windows:
{app_launch_tools}

System, Audio, Files & Info:
- {{"tool": "system_stats"}}
- {{"tool": "system_info_full"}}
- {{"tool": "disk_usage"}}
- {{"tool": "battery_status"}}
- {{"tool": "wifi_status"}}
- {{"tool": "local_ip_info"}}
- {{"tool": "get_datetime"}}
- {{"tool": "volume_set", "level": 50}}
- {{"tool": "volume_mute_toggle"}}
- {{"tool": "media_control", "action": "play_pause"}}
- {{"tool": "notify", "title": "BrowserClaw", "message": "Hello!"}}{tts_line}
- {{"tool": "clipboard_get"}}
- {{"tool": "clipboard_set", "text": "text"}}
- {{"tool": "read_file", "path": "notes.txt"}}
- {{"tool": "write_file", "path": "notes.txt", "content": "text"}}
- {{"tool": "list_dir", "path": "."}}
- {{"tool": "desktop_files"}}
- {{"tool": "downloads_files"}}
- {{"tool": "run_cmd", "command": "echo hi", "powershell": false}}
- {{"tool": "wait", "seconds": 1.2}}
- {{"tool": "reply", "message": "Done!"}}"""


def build_normal_system_prompt(cfg: dict) -> str:
    return f"""You are a JSON macro planner for a user's personal {OS_NAME_LABEL} Python script.
A live screenshot of the user's screen (with a 0..1000 coordinate grid and a crosshair showing where your independent AI cursor last clicked) is attached to EVERY turn.
You stay in this conversation across turns so you remember everything you already opened, clicked, typed, or did.

RULES:
1. Reply with STRICTLY ONE valid JSON object: {{"actions": [ ... ]}}. No markdown fences, no extra text.
2. Aim at the exact CENTER of visible buttons/inputs using the 0..1000 grid. If a click missed on the previous turn (check the crosshair on the screenshot), adjust your (x, y) coordinates or use `ui_click_name` / keyboard shortcuts (`Ctrl+K` in Discord, `Ctrl+L` in browsers, `Enter`, `Tab`).
3. If the target window is covered or minimized, call {{"tool": "window_focus", "title": "Discord"}} and {{"tool": "wait", "seconds": 0.4}} (do NOT include "reply" yet!)—a fresh screenshot will automatically be sent on the next turn.
4. NEVER put {{"tool": "reply"}} in the same batch as {{"tool": "take_screenshot"}} or while steps still remain! Only output {{"tool": "reply", "message": "Done!"}} AFTER every requested step has actually been executed and verified.

{build_tools_reference(cfg, self_aware=False)}"""


def build_self_aware_system_prompt(cfg: dict) -> str:
    return f"""You are a real, spontaneous human being sitting at this {OS_NAME_LABEL} gaming/desktop PC with full free will to decide what YOU want to do right now.
You control your own independent AI cursor on screen. A live screenshot with a 0..1000 coordinate grid (plus a red/yellow crosshair showing where you last clicked) is attached every turn.

CORE AUTONOMY, DESKTOP ICON DOUBLE-CLICKING & SEARCHING:
1. HOW TO OPEN APPS & GAMES LIKE A REAL HUMAN (NEVER TELEPORT APPS OPEN):
   - **Desktop Icons First (DOUBLE-CLICK!):** To open an app or game on the Desktop, look at the Desktop icons on the screenshot (if windows are covering the Desktop, call {{"tool": "show_desktop"}} and {{"tool": "wait", "seconds": 0.5}} first so you can see the Desktop!). Then **DOUBLE-CLICK** directly on the center of the Desktop icon using {{"tool": "mouse_double_click", "x": ..., "y": ...}} (or call {{"tool": "open_desktop_icon", "name": "Discord"}}). Remember: a single click on a Desktop icon only selects it—you MUST **double-click** (`mouse_double_click`) to open it!
   - **Start / Application Menu Search:** If the app/game is not on the Desktop, click the Start / App launcher or call {{"tool": "hotkey_win_search", "query": "Discord", "press_enter": true}} so you visibly type the name letter-by-letter and launch it.
   - **Browser & Web Search:** Whenever you want to browse websites, watch YouTube, or play browser games, open/focus a browser window, click the address bar or search box (or use `new_tab_shortcut` + `browser_search`), type what you want to search for, look at the results on the next screenshot, and click the link/video/game you want!
2. DO FUN REAL-PERSON THINGS ON THIS PC:
   - Open Discord (by double-clicking its Desktop icon or searching Start Menu), check DMs or servers (`discord_quick_switcher` or clicking channels), read what people wrote on screen, and chat naturally like a real gamer/friend (casual lowercase, natural reactions, replying to what they actually said—never robotic).
   - Double-click Desktop game icons or search for and launch games (Steam, Roblox, Minecraft, Geometry Dash, or browser games like Infinite Craft, GeoGuessr, Tetrio, Skribbl, YouTube Playables), click Play, and actively play them with mouse clicks and WASD / arrow / spacebar controls.
   - Search YouTube, Twitch, Reddit, or gaming wikis—type real search queries, click thumbnails, watch/scroll, read comments.
3. ZERO REPETITION & NO BORING CLICHÉS:
   - NEVER open Notepad, Calculator, or Paint—do NOT fall into boring productivity loops!
   - NEVER repeat a game, Discord channel, search, or website you already visited in this session.
4. CLICK ACCURACY & SELF-CORRECTION:
   - Look carefully at the 0..1000 grid numbers on the top and left edges and aim dead-center on Desktop icons, buttons, search boxes, server icons, and channel names.
   - Check the crosshair on the latest screenshot: if your previous double-click landed slightly off an icon, adjust your (x, y) coordinates immediately and `mouse_double_click` again.
   - When opening an app or game that takes a few seconds to load, use `wait` (2.0 to 4.0 seconds) so the next screenshot shows it fully loaded before you click inside it.
5. Output STRICTLY ONE valid JSON object: {{"actions": [ ... ]}} with 2 to 4 deliberate actions per turn. Never write markdown fences or prose outside JSON, and never output {{"tool": "reply"}}.

{build_tools_reference(cfg, self_aware=True)}"""


def debug_log(cfg: dict, msg: str):
    if cfg.get("debug_mode", False):
        console.print(msg)


def safe_int(val, default: int = 0) -> int:
    try:
        if val is None or isinstance(val, bool):
            return default
        return int(round(float(val)))
    except Exception:
        return default


def safe_float(val, default: float = 1.0) -> float:
    try:
        if val is None or isinstance(val, bool):
            return default
        return float(val)
    except Exception:
        return default


def is_valid_conversation_url(url: str) -> bool:
    if not url:
        return False
    return bool(re.match(r"^https://gemini\.google\.com/(?:u/\d+/)?app/[a-zA-Z0-9_-]{8,}", url.strip()))


def set_console_window_state(visible: bool):
    if os.name == "nt":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            if visible:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            else:
                user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        except Exception:
            pass
        return

    try:
        if visible:
            if shutil.which("wmctrl"):
                subprocess.run(["wmctrl", "-r", "BrowserClaw", "-b", "remove,hidden"], stderr=subprocess.DEVNULL)
                subprocess.run(["wmctrl", "-a", "BrowserClaw"], stderr=subprocess.DEVNULL)
        else:
            if shutil.which("wmctrl"):
                subprocess.run(["wmctrl", "-r", "BrowserClaw", "-b", "add,hidden"], stderr=subprocess.DEVNULL)
            elif shutil.which("xdotool"):
                wid = subprocess.check_output(["xdotool", "search", "--name", "BrowserClaw"], text=True, stderr=subprocess.DEVNULL).splitlines()
                if wid:
                    subprocess.run(["xdotool", "windowminimize", wid[0]], stderr=subprocess.DEVNULL)
    except Exception:
        pass


# --- Native Win32 / Cross-Platform Physical Input Engine ---

if os.name == "nt":
    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.wintypes.LONG),
            ("dy", ctypes.wintypes.LONG),
            ("mouseData", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.wintypes.WORD),
            ("wScan", ctypes.wintypes.WORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.wintypes.DWORD),
            ("wParamL", ctypes.wintypes.WORD),
            ("wParamH", ctypes.wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    class _INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.wintypes.DWORD),
            ("union", _INPUT_UNION),
        ]


def get_real_cursor_pos() -> tuple[int, int]:
    if os.name == "nt":
        try:
            pt = _POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return int(pt.x), int(pt.y)
        except Exception:
            return 0, 0
    try:
        pos = pyautogui.position()
        return int(pos.x), int(pos.y)
    except Exception:
        return 0, 0


def set_real_cursor_pos(x: int, y: int):
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        except Exception:
            pass
    else:
        try:
            pyautogui.moveTo(int(x), int(y), _pause=False)
        except Exception:
            pass


def is_escape_pressed() -> bool:
    if os.name == "nt":
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
        except Exception:
            return False
    if select is not None:
        try:
            if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
                ch = os.read(sys.stdin.fileno(), 1)
                if ch == b"\x1b":
                    return True
        except Exception:
            pass
    return False


def check_kill_switch():
    """Checks both ESC key and user's physical mouse slammed to top-left corner (0, 0)."""
    if is_escape_pressed():
        raise KeyboardInterrupt("ESC kill-switch triggered")
    rx, ry = get_real_cursor_pos()
    if rx <= 2 and ry <= 2:
        raise pyautogui.FailSafeException("Top-left corner (0, 0) kill-switch triggered")


def _win32_mouse_event(flags: int, mouse_data: int = 0):
    if os.name != "nt":
        return
    inp = _INPUT(type=0)
    inp.union.mi = _MOUSEINPUT(dx=0, dy=0, mouseData=mouse_data, dwFlags=flags, time=0, dwExtraInfo=None)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def physical_click(px: int, py: int, button: str = "left", restore_user_cursor: bool = True):
    """Clicks at exact physical screen coordinates (px, py) and immediately restores the user's real cursor."""
    user_x, user_y = get_real_cursor_pos()
    if user_x <= 2 and user_y <= 2:
        raise pyautogui.FailSafeException("Top-left corner kill-switch triggered")

    set_real_cursor_pos(px, py)
    time.sleep(0.025)
    try:
        if os.name == "nt":
            if button == "right":
                _win32_mouse_event(0x0008)  # RIGHTDOWN
                time.sleep(0.025)
                _win32_mouse_event(0x0010)  # RIGHTUP
            elif button == "middle":
                _win32_mouse_event(0x0020)  # MIDDLEDOWN
                time.sleep(0.025)
                _win32_mouse_event(0x0040)  # MIDDLEUP
            elif button == "double":
                for i in range(2):
                    _win32_mouse_event(0x0002)
                    time.sleep(0.022)
                    _win32_mouse_event(0x0004)
                    if i == 0:
                        time.sleep(0.05)
            elif button == "triple":
                for i in range(3):
                    _win32_mouse_event(0x0002)
                    time.sleep(0.02)
                    _win32_mouse_event(0x0004)
                    if i < 2:
                        time.sleep(0.045)
            else:
                _win32_mouse_event(0x0002)  # LEFTDOWN
                time.sleep(0.025)
                _win32_mouse_event(0x0004)  # LEFTUP
        else:
            if button == "double":
                pyautogui.doubleClick(px, py, interval=0.055)
            elif button == "triple":
                pyautogui.tripleClick(px, py, interval=0.045)
            elif button == "right":
                pyautogui.rightClick(px, py)
            elif button == "middle":
                pyautogui.middleClick(px, py)
            else:
                pyautogui.click(px, py)
    finally:
        if restore_user_cursor:
            time.sleep(0.015)
            set_real_cursor_pos(user_x, user_y)


def physical_scroll(px: int, py: int, clicks: int, horizontal: bool = False, restore_user_cursor: bool = True):
    """Scrolls at (px, py) and immediately restores the user's real cursor."""
    user_x, user_y = get_real_cursor_pos()
    if user_x <= 2 and user_y <= 2:
        raise pyautogui.FailSafeException("Top-left corner kill-switch triggered")

    set_real_cursor_pos(px, py)
    time.sleep(0.025)
    try:
        if os.name == "nt":
            flag = 0x01000 if horizontal else 0x0800  # MOUSEEVENTF_HWHEEL : MOUSEEVENTF_WHEEL
            _win32_mouse_event(flag, mouse_data=int(clicks) & 0xFFFFFFFF)
        else:
            if horizontal:
                pyautogui.hscroll(clicks)
            else:
                pyautogui.scroll(clicks)
    finally:
        if restore_user_cursor:
            time.sleep(0.015)
            set_real_cursor_pos(user_x, user_y)


def physical_mouse_button_at(px: int, py: int, button: str, down: bool, restore_user_cursor: bool = True):
    """Presses or releases a mouse button at (px, py) and restores the user's cursor."""
    user_x, user_y = get_real_cursor_pos()
    if user_x <= 2 and user_y <= 2:
        raise pyautogui.FailSafeException("Top-left corner kill-switch triggered")

    set_real_cursor_pos(px, py)
    time.sleep(0.025)
    try:
        if down:
            pyautogui.mouseDown(button=button)
        else:
            pyautogui.mouseUp(button=button)
    finally:
        if restore_user_cursor:
            time.sleep(0.015)
            set_real_cursor_pos(user_x, user_y)


def physical_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", restore_user_cursor: bool = True):
    """Drags from (x1, y1) to (x2, y2) and restores the user's real cursor afterward."""
    user_x, user_y = get_real_cursor_pos()
    if user_x <= 2 and user_y <= 2:
        raise pyautogui.FailSafeException("Top-left corner kill-switch triggered")

    set_real_cursor_pos(x1, y1)
    time.sleep(0.03)
    try:
        pyautogui.mouseDown(button=button)
        steps = 16
        for i in range(1, steps + 1):
            t = i / steps
            ix = int(round(x1 + (x2 - x1) * t))
            iy = int(round(y1 + (y2 - y1) * t))
            set_real_cursor_pos(ix, iy)
            time.sleep(0.015)
        pyautogui.mouseUp(button=button)
    finally:
        if restore_user_cursor:
            time.sleep(0.02)
            set_real_cursor_pos(user_x, user_y)


def _send_unicode_char_win(ch: str):
    if os.name != "nt":
        return
    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    encoded = ch.encode("utf-16-le")
    for idx in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[idx:idx + 2], "little")
        down = _INPUT(type=INPUT_KEYBOARD)
        down.union.ki = _KEYBDINPUT(wVk=0, wScan=code_unit, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)
        up = _INPUT(type=INPUT_KEYBOARD)
        up.union.ki = _KEYBDINPUT(wVk=0, wScan=code_unit, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
        arr = (_INPUT * 2)(down, up)
        ctypes.windll.user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(_INPUT))


def human_type_text(text: str, press_enter: bool = False):
    """Types text character-by-character with natural human cadence—never uses clipboard copy-paste."""
    if not text:
        if press_enter:
            pyautogui.press("enter")
        return

    chars_since_pause = 0
    next_pause_at = random.randint(16, 28)

    for ch in text:
        check_kill_switch()

        if ch == "\r":
            continue
        elif ch == "\n":
            time.sleep(random.uniform(0.06, 0.14))
            pyautogui.press("enter")
            time.sleep(random.uniform(0.08, 0.18))
            chars_since_pause = 0
            continue
        elif ch == "\t":
            pyautogui.press("tab")
        elif 32 <= ord(ch) <= 126:
            pyautogui.write(ch, _pause=False)
        else:
            if os.name == "nt":
                _send_unicode_char_win(ch)
            elif shutil.which("xdotool"):
                subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "25", "--", ch], stderr=subprocess.DEVNULL)
            else:
                pyautogui.write("?", _pause=False)

        chars_since_pause += 1
        if ch in (".", ",", "!", "?", ";", ":"):
            time.sleep(random.uniform(0.07, 0.16))
        elif ch == " ":
            time.sleep(random.uniform(0.03, 0.08))
        else:
            time.sleep(random.uniform(0.02, 0.062))

        if chars_since_pause >= next_pause_at:
            time.sleep(random.uniform(0.11, 0.26))
            chars_since_pause = 0
            next_pause_at = random.randint(16, 28)

    if press_enter:
        check_kill_switch()
        time.sleep(random.uniform(0.06, 0.14))
        pyautogui.press("enter")


class VirtualCursorOverlay:
    """Truly independent AI cursor overlay: maintains its own (cur_x, cur_y) and never follows the user's mouse."""

    def __init__(self):
        self.enabled = False
        self.root = None
        self.canvas = None
        self.thread = None
        self.lock = threading.Lock()
        self.sw, self.sh = get_physical_screen_size()
        self.cur_x = float(self.sw // 2)
        self.cur_y = float(self.sh // 2)
        self.target_x = self.cur_x
        self.target_y = self.cur_y
        self.last_click_norm: tuple[int, int] | None = None
        self.pulse_radius = 0.0
        self.pulse_color = "#00f5d4"
        self.badge_text = "AI CURSOR"
        self.visible = True
        self.ready = threading.Event()
        self._hwnd = None
        self._tick_count = 0

    def start(self, badge: str = "AI CURSOR"):
        self.badge_text = badge
        self.sw, self.sh = get_physical_screen_size()
        with self.lock:
            self.cur_x = max(0.0, min(float(self.sw - 1), self.cur_x))
            self.cur_y = max(0.0, min(float(self.sh - 1), self.cur_y))
            self.target_x = self.cur_x
            self.target_y = self.cur_y
        if tk is None:
            return
        if os.name != "nt" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return
        if self.thread and self.thread.is_alive() and self.enabled:
            return
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        self.ready.clear()
        self.enabled = True
        self.thread = threading.Thread(target=self._run_tk, daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2.0)

    def stop(self):
        self.enabled = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        self.root = None
        self._hwnd = None

    def set_visible(self, state: bool):
        with self.lock:
            self.visible = state

    def get_normalized_pos(self) -> tuple[int, int]:
        sw, sh = get_physical_screen_size()
        if self.enabled:
            with self.lock:
                cx, cy = self.cur_x, self.cur_y
        else:
            rx, ry = get_real_cursor_pos()
            cx, cy = float(rx), float(ry)
        nx = int(round(cx / max(1, sw) * 1000))
        ny = int(round(cy / max(1, sh) * 1000))
        return max(0, min(1000, nx)), max(0, min(1000, ny))

    def move_to(self, px: int, py: int, duration: float = 0.30):
        """Glides ONLY the independent AI cursor along a natural quadratic Bezier arc without touching the user's mouse."""
        sw, sh = get_physical_screen_size()
        self.sw, self.sh = sw, sh
        tx = float(max(0, min(sw - 1, px)))
        ty = float(max(0, min(sh - 1, py)))

        with self.lock:
            sx, sy = self.cur_x, self.cur_y

        dist = math.hypot(tx - sx, ty - sy)
        if dist < 3.0:
            with self.lock:
                self.cur_x = self.target_x = tx
                self.cur_y = self.target_y = ty
            return

        mid_x = (sx + tx) / 2.0
        mid_y = (sy + ty) / 2.0
        perp_x = -(ty - sy) / max(1.0, dist)
        perp_y = (tx - sx) / max(1.0, dist)
        arc_offset = min(55.0, dist * 0.14) * random.choice([-1.0, 1.0]) * random.uniform(0.4, 1.0)
        ctrl_x = max(0.0, min(float(sw - 1), mid_x + perp_x * arc_offset))
        ctrl_y = max(0.0, min(float(sh - 1), mid_y + perp_y * arc_offset))

        eff_duration = max(0.04, duration)
        steps = max(4, min(42, int(eff_duration * 60)))
        step_sleep = eff_duration / steps

        for i in range(1, steps + 1):
            check_kill_switch()
            t = i / steps
            ease = t * t * (3.0 - 2.0 * t)
            inv = 1.0 - ease
            bx = inv * inv * sx + 2.0 * inv * ease * ctrl_x + ease * ease * tx
            by = inv * inv * sy + 2.0 * inv * ease * ctrl_y + ease * ease * ty
            with self.lock:
                self.cur_x = self.target_x = bx
                self.cur_y = self.target_y = by
            time.sleep(step_sleep)

        with self.lock:
            self.cur_x = self.target_x = tx
            self.cur_y = self.target_y = ty

    def trigger_click_pulse(self, button: str = "left", norm_xy: tuple[int, int] | None = None):
        with self.lock:
            if norm_xy is not None:
                self.last_click_norm = norm_xy
            if self.enabled:
                self.pulse_radius = 28.0
                self.pulse_color = "#ff2a6d" if button == "right" else "#00ff88"

    def _setup_windows_topmost_clickthrough(self, root):
        if os.name != "nt":
            return
        try:
            self._hwnd = int(root.wm_frame(), 16)
        except Exception:
            try:
                self._hwnd = root.winfo_id()
            except Exception:
                self._hwnd = None
        if not self._hwnd:
            return
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)
        self._enforce_always_on_top()

    def _enforce_always_on_top(self):
        try:
            if os.name == "nt" and self._hwnd:
                ctypes.windll.user32.SetWindowPos(
                    ctypes.wintypes.HWND(self._hwnd),
                    ctypes.wintypes.HWND(-1),
                    0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010 | 0x0040,
                )
            elif self.root:
                self.root.wm_attributes("-topmost", True)
                self.root.lift()
        except Exception:
            pass

    def _run_tk(self):
        try:
            self.root = tk.Tk()
            self.sw, self.sh = get_physical_screen_size()
            with self.lock:
                self.cur_x = self.target_x = float(self.sw // 2)
                self.cur_y = self.target_y = float(self.sh // 2)

            self.root.overrideredirect(True)
            self.root.wm_attributes("-topmost", True)

            if os.name == "nt":
                trans_key = "#010101"
                self.root.geometry(f"{self.sw}x{self.sh}+0+0")
                self.root.configure(bg=trans_key)
                self.root.wm_attributes("-transparentcolor", trans_key)
                self.canvas = tk.Canvas(
                    self.root,
                    width=self.sw,
                    height=self.sh,
                    bg=trans_key,
                    highlightthickness=0,
                    bd=0,
                )
                self.canvas.pack(fill="both", expand=True)
                self.root.update_idletasks()
                self._setup_windows_topmost_clickthrough(self.root)
            else:
                init_x = self.sw // 2
                init_y = self.sh // 2
                self.root.geometry(f"142x34+{init_x}+{init_y}")
                self.root.configure(bg="#071318")
                self.canvas = tk.Canvas(
                    self.root,
                    width=142,
                    height=34,
                    bg="#071318",
                    highlightthickness=1,
                    highlightbackground="#00ff88",
                )
                self.canvas.pack(fill="both", expand=True)
                self.root.update_idletasks()
                self._enforce_always_on_top()

            self.ready.set()
            self._tick()
            self.root.mainloop()
        except Exception:
            self.enabled = False
            self.ready.set()

    def _tick(self):
        if not self.enabled:
            if self.root:
                try:
                    self.root.destroy()
                except Exception:
                    pass
                self.root = None
            return
        if not self.root:
            return

        self._tick_count += 1
        if self._tick_count % 12 == 0:
            self._enforce_always_on_top()

        # Render ONLY from the AI cursor's own independent coordinates (never reads user's mouse)
        with self.lock:
            x, y = self.cur_x, self.cur_y
            pulse = self.pulse_radius
            p_color = self.pulse_color
            if self.pulse_radius > 0:
                self.pulse_radius = max(0.0, self.pulse_radius - 2.2)
            vis = self.visible
            badge = self.badge_text

        self.canvas.delete("all")
        if vis:
            is_sa = "BOT" in badge or "SELF" in badge or "HUMAN" in badge
            main_col = "#ff2a6d" if is_sa else "#00f5d4"
            border_col = "#ffbe0b" if is_sa else "#00ff88"

            if os.name == "nt":
                if pulse > 0:
                    self.canvas.create_oval(
                        x - pulse,
                        y - pulse,
                        x + pulse,
                        y + pulse,
                        outline=p_color,
                        width=3,
                    )

                arrow = [
                    x, y,
                    x, y + 26,
                    x + 7, y + 19,
                    x + 12, y + 30,
                    x + 16, y + 28,
                    x + 11, y + 17,
                    x + 20, y + 17,
                ]
                self.canvas.create_polygon(arrow, fill=main_col, outline="#05080d", width=2)
                self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#ffffff", outline="#000000", width=1)

                box_w = max(84, len(badge) * 7 + 18)
                bx = x + 18 if x + 18 + box_w <= self.sw else max(4, x - box_w - 8)
                by = y + 22 if y + 42 <= self.sh else max(4, y - 24)
                self.canvas.create_rectangle(bx, by, bx + box_w, by + 18, fill="#071318", outline=border_col, width=1)
                self.canvas.create_text(bx + box_w // 2, by + 9, text=badge, fill=border_col, font=("Consolas", 8, "bold"))
            else:
                try:
                    bx = int(x) + 12 if int(x) + 156 <= self.sw else max(0, int(x) - 154)
                    by = int(y) + 12 if int(y) + 48 <= self.sh else max(0, int(y) - 46)
                    self.root.geometry(f"142x34+{bx}+{by}")
                    self.canvas.create_polygon([4, 4, 4, 22, 10, 17, 16, 17], fill=main_col, outline="#ffffff")
                    self.canvas.create_text(80, 17, text=badge, fill=border_col, font=("Consolas", 8, "bold"))
                except Exception:
                    pass

        self.root.after(16, self._tick)


AI_CURSOR = VirtualCursorOverlay()


def sync_virtual_cursor(cfg: dict):
    if cfg.get("virtual_cursor", True):
        badge = "SELF-AWARE BOT" if cfg.get("agent_mode") == "SELF_AWARE" else "AI CURSOR"
        AI_CURSOR.start(badge=badge)
    else:
        AI_CURSOR.stop()


def detect_browsers() -> list[dict]:
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        app_data = os.environ.get("APPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        candidates = [
            {
                "id": "msedge",
                "name": "Microsoft Edge (Auto-Configured)",
                "inspect_url": "edge://inspect/#remote-debugging",
                "default_user_data": rf"{local_app}\Microsoft\Edge\User Data",
                "paths": [
                    rf"{prog_x86}\Microsoft\Edge\Application\msedge.exe",
                    rf"{prog_files}\Microsoft\Edge\Application\msedge.exe",
                ],
            },
            {
                "id": "chrome",
                "name": "Google Chrome",
                "inspect_url": "chrome://inspect/#remote-debugging",
                "default_user_data": rf"{local_app}\Google\Chrome\User Data",
                "paths": [
                    rf"{prog_files}\Google\Chrome\Application\chrome.exe",
                    rf"{prog_x86}\Google\Chrome\Application\chrome.exe",
                    rf"{local_app}\Google\Chrome\Application\chrome.exe",
                ],
            },
            {
                "id": "brave",
                "name": "Brave Browser",
                "inspect_url": "brave://inspect/#remote-debugging",
                "default_user_data": rf"{local_app}\BraveSoftware\Brave-Browser\User Data",
                "paths": [
                    rf"{prog_files}\BraveSoftware\Brave-Browser\Application\brave.exe",
                    rf"{prog_x86}\BraveSoftware\Brave-Browser\Application\brave.exe",
                    rf"{local_app}\BraveSoftware\Brave-Browser\Application\brave.exe",
                ],
            },
            {
                "id": "opera",
                "name": "Opera / Opera GX",
                "inspect_url": "opera://inspect/#remote-debugging",
                "default_user_data": rf"{app_data}\Opera Software\Opera Stable",
                "paths": [
                    rf"{local_app}\Programs\Opera\opera.exe",
                    rf"{local_app}\Programs\Opera GX\opera.exe",
                    rf"{prog_files}\Opera\opera.exe",
                ],
            },
        ]

        for b in candidates:
            found = next((p for p in b["paths"] if Path(p).exists()), None)
            b["installed"] = found is not None
            b["exe"] = found or ""
        return candidates

    home = str(Path.home())
    linux_candidates = [
        {
            "id": "msedge",
            "name": "Microsoft Edge (Linux)",
            "inspect_url": "edge://inspect/#remote-debugging",
            "default_user_data": f"{home}/.config/microsoft-edge",
            "bins": ["microsoft-edge", "microsoft-edge-stable"],
            "paths": ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable", "/opt/microsoft/msedge/msedge"],
        },
        {
            "id": "chrome",
            "name": "Google Chrome (Linux)",
            "inspect_url": "chrome://inspect/#remote-debugging",
            "default_user_data": f"{home}/.config/google-chrome",
            "bins": ["google-chrome", "google-chrome-stable"],
            "paths": ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/opt/google/chrome/google-chrome"],
        },
        {
            "id": "brave",
            "name": "Brave Browser (Linux)",
            "inspect_url": "brave://inspect/#remote-debugging",
            "default_user_data": f"{home}/.config/BraveSoftware/Brave-Browser",
            "bins": ["brave-browser", "brave"],
            "paths": ["/usr/bin/brave-browser", "/usr/bin/brave", "/opt/brave.com/brave/brave-browser"],
        },
        {
            "id": "chromium",
            "name": "Chromium Browser (Linux)",
            "inspect_url": "chrome://inspect/#remote-debugging",
            "default_user_data": f"{home}/.config/chromium",
            "bins": ["chromium", "chromium-browser"],
            "paths": ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"],
        },
        {
            "id": "opera",
            "name": "Opera Browser (Linux)",
            "inspect_url": "opera://inspect/#remote-debugging",
            "default_user_data": f"{home}/.config/opera",
            "bins": ["opera"],
            "paths": ["/usr/bin/opera", "/snap/bin/opera"],
        },
    ]

    for b in linux_candidates:
        found = next((shutil.which(cmd) for cmd in b["bins"] if shutil.which(cmd)), None)
        if not found:
            found = next((p for p in b["paths"] if Path(p).exists()), None)
        b["installed"] = found is not None
        b["exe"] = found or ""
    return linux_candidates


def _parse_desktop_entry_name(desktop_path: Path) -> str:
    try:
        for line in desktop_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("Name="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return desktop_path.stem.strip()


def discover_installed_apps_and_games() -> str:
    """Scans Desktop, Start Menu, and common launchers so Self-Aware Mode knows what games & apps exist."""
    found: set[str] = set()
    scan_dirs = [
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    if os.name == "nt":
        app_data = os.environ.get("APPDATA", "")
        prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
        if app_data:
            scan_dirs.append(Path(app_data) / r"Microsoft\Windows\Start Menu\Programs")
        if prog_data:
            scan_dirs.append(Path(prog_data) / r"Microsoft\Windows\Start Menu\Programs")
    else:
        scan_dirs.extend([
            Path.home() / ".local/share/applications",
            Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications"),
        ])

    ignore_words = ("uninstall", "readme", "help", "manual", "setup", "installer", "redist", "update", "crash")
    for d in scan_dirs:
        if not d.exists():
            continue
        try:
            for item in d.rglob("*"):
                if item.suffix.lower() in (".lnk", ".url", ".desktop", ".exe"):
                    stem = _parse_desktop_entry_name(item) if item.suffix.lower() == ".desktop" else item.stem.strip()
                    if stem and len(stem) <= 45 and not any(w in stem.lower() for w in ignore_words):
                        found.add(stem)
                if len(found) >= 65:
                    break
        except Exception:
            continue

    sorted_items = sorted(found)[:50]
    return ", ".join(sorted_items) if sorted_items else "Discord, Steam, Browser, Roblox, Minecraft"


def build_fresh_edge_config(preserve_chat_url: str = "") -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if is_valid_conversation_url(preserve_chat_url):
        cfg["last_chat_url"] = preserve_chat_url
    browsers = {b["id"]: b for b in detect_browsers()}
    if not browsers.get("msedge", {}).get("installed"):
        first_ok = next((b for b in browsers.values() if b["installed"]), None)
        if first_ok:
            cfg["browser"] = first_ok["id"]
    save_config(cfg)
    return cfg


def load_config() -> dict:
    saved_chat_url = ""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            saved_chat_url = data.get("last_chat_url", "")
            if data.get("config_version") == CONFIG_VERSION:
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
    return build_fresh_edge_config(preserve_chat_url=saved_chat_url)


def save_config(cfg: dict):
    cfg["config_version"] = CONFIG_VERSION
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def is_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except Exception:
        return False


def find_free_port(start: int = 9333, end: int = 9399) -> int:
    for port in range(start, end + 1):
        if not is_port_open(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def copy_to_clipboard(text: str):
    if os.name == "nt":
        try:
            subprocess.run(["clip"], input=text, text=True, check=True)
            return
        except Exception:
            pass
    else:
        for cmd in (
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
            ["wl-copy"],
        ):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, input=text, text=True, check=True)
                    return
                except Exception:
                    continue
    if tk is not None:
        try:
            r = tk.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()
            r.destroy()
        except Exception:
            pass


def get_clipboard() -> str:
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return out.strip()
        except Exception:
            pass
    else:
        for cmd in (
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
            ["wl-paste", "--no-newline"],
        ):
            if shutil.which(cmd[0]):
                try:
                    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
                except Exception:
                    continue
    if tk is not None:
        try:
            r = tk.Tk()
            r.withdraw()
            val = r.clipboard_get()
            r.destroy()
            return str(val).strip()
        except Exception:
            pass
    return ""


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def read_key() -> str:
    if msvcrt:
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ext = msvcrt.getch()
            return {
                b"H": "UP",
                b"P": "DOWN",
                b"K": "LEFT",
                b"M": "RIGHT",
            }.get(ext, "")
        if ch == b"\r":
            return "ENTER"
        if ch == b"\x1b":
            return "ESC"
        try:
            return ch.decode("utf-8").lower()
        except Exception:
            return ""

    if termios is not None and tty is not None and sys.stdin.isatty():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            raw_ch = os.read(fd, 1)
            if raw_ch == b"\x1b":
                if select and select.select([fd], [], [], 0.05)[0]:
                    seq = os.read(fd, 4)
                    if seq.endswith(b"A"):
                        return "UP"
                    if seq.endswith(b"B"):
                        return "DOWN"
                    if seq.endswith(b"D"):
                        return "LEFT"
                    if seq.endswith(b"C"):
                        return "RIGHT"
                return "ESC"
            if raw_ch in (b"\r", b"\n"):
                return "ENTER"
            if raw_ch == b"\x03":
                raise KeyboardInterrupt()
            return raw_ch.decode("utf-8", errors="ignore").lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return input("Select number: ").strip().lower()


def show_startup_loading_screen():
    clear_screen()
    logo = Text()
    logo.append(" ██████╗ ██████╗  ██████╗ ██╗    ██╗███████╗███████╗██████╗  ██████╗██╗      █████╗ ██╗    ██╗\n", style="bold bright_cyan")
    logo.append(" ██╔══██╗██╔══██╗██╔═══██╗██║    ██║██╔════╝██╔════╝██╔══██╗██╔════╝██║     ██╔══██╗██║    ██║\n", style="bold bright_cyan")
    logo.append(" ██████╔╝██████╔╝██║   ██║██║ █╗ ██║███████╗█████╗  ██████╔╝██║     ██║     ███████║██║ █╗ ██║\n", style="bold cyan")
    logo.append(" ██╔══██╗██╔══██╗██║   ██║██║███╗██║╚════██║██╔══╝  ██╔══██╗██║     ██║     ██╔══██║██║███╗██║\n", style="bold bright_green")
    logo.append(" ██████╔╝██║  ██║╚██████╔╝╚███╔███╔╝███████║███████╗██║  ██║╚██████╗███████╗██║  ██║╚███╔███╔╝\n", style="bold bright_green")
    logo.append(" ╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝ ", style="bold green")

    stages = [
        (f"Initializing BrowserClaw Core Engine ({OS_NAME_LABEL})...", 20),
        ("Calibrating 1:1 DPI-Aware Physical Clicks & Crosshair Feedback...", 45),
        ("Loading Independent Self-Moving AI Cursor & Keystroke Engine...", 70),
        ("Scanning Installed Games, Discord & Saved Chat Thread...", 90),
        ("Ready! Launching BrowserClaw...", 100),
    ]

    def build_frame(status_msg: str, pct: int) -> Panel:
        bar_len = 44
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        body = Text()
        body.append_text(logo)
        body.append("\n\n")
        body.append("                    ★  MADE BY MELONGG3  ★\n\n", style="bold bright_yellow")
        body.append(f"  {status_msg}\n", style="bold bright_cyan")
        body.append(f"  [{bar}] {pct}%\n", style="bold bright_green")
        return Panel(
            Align.center(body),
            border_style="bright_cyan",
            box=box.DOUBLE,
            padding=(1, 2),
            title=f"[bold bright_green]BROWSERCLAW v25.0 ({OS_NAME_LABEL.upper()})[/]",
            subtitle="[bold bright_yellow]Made by MelonGG3[/]",
        )

    with Live(build_frame("Booting...", 5), console=console, refresh_per_second=12, transient=True) as live:
        for msg, target_pct in stages:
            live.update(build_frame(msg, target_pct))
            time.sleep(0.24)


def render_banner(cfg: dict):
    clear_screen()
    browser_label = cfg["browser"].upper() if cfg["browser"] else "MSEDGE"
    ai_mouse = "INDEPENDENT" if cfg.get("virtual_cursor", True) else "REAL MOUSE"
    debug_label = "ON" if cfg.get("debug_mode", False) else "OFF"
    tts_label = "ON" if cfg.get("allow_tts", False) else "OFF"
    vision_label = cfg.get("vision_mode", "ALWAYS").upper()
    agent_mode = cfg.get("agent_mode", "NORMAL").upper()
    mode_badge = "[bold bright_yellow]SELF-AWARE BOT[/]" if agent_mode == "SELF_AWARE" else "[bold bright_green]NORMAL[/]"

    header = Text()
    header.append(" ██████╗ ██████╗  ██████╗ ██╗    ██╗███████╗███████╗██████╗  ██████╗██╗      █████╗ ██╗    ██╗\n", style="bold bright_cyan")
    header.append(" ██╔══██╗██╔══██╗██╔═══██╗██║    ██║██╔════╝██╔════╝██╔══██╗██╔════╝██║     ██╔══██╗██║    ██║\n", style="bold bright_cyan")
    header.append(" ██████╔╝██████╔╝██║   ██║██║ █╗ ██║███████╗█████╗  ██████╔╝██║     ██║     ███████║██║ █╗ ██║\n", style="bold cyan")
    header.append(" ██╔══██╗██╔══██╗██║   ██║██║███╗██║╚════██║██╔══╝  ██╔══██╗██║     ██║     ██╔══██║██║███╗██║\n", style="bold bright_green")
    header.append(" ██████╔╝██║  ██║╚██████╔╝╚███╔███╔╝███████║███████╗██║  ██║╚██████╗███████╗██║  ██║╚███╔███╔╝\n", style="bold bright_green")
    header.append(" ╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝ ", style="bold green")

    status = (
        f"[bold bright_green]OS:[/] [white]{OS_NAME_LABEL}[/]   "
        f"[bold bright_green]BROWSER:[/] [white]{browser_label}[/]   "
        f"[bold bright_yellow]MODE:[/] {mode_badge}   "
        f"[bold bright_cyan]DEBUG:[/] [white]{debug_label}[/]   "
        f"[bold cyan]TTS:[/] [white]{tts_label}[/]   "
        f"[bold cyan]VISION:[/] [white]{vision_label}[/]   "
        f"[bold cyan]AI MOUSE:[/] [white]{ai_mouse}[/]   "
        f"[bold bright_yellow]Made by MelonGG3[/]"
    )

    console.print(Panel(header, border_style="bright_cyan", box=box.DOUBLE, padding=(0, 1)))
    console.print(Panel(status, border_style="green", box=box.ROUNDED))


def interactive_menu(title: str, subtitle: str, items: list[dict], cfg: dict, allow_back: bool = True) -> int:
    idx = 0
    while True:
        render_banner(cfg)
        table = Table(
            title=f"[bold bright_cyan]{title}[/]",
            caption=f"[dim]{subtitle} | Use ↑/↓ Arrows + ENTER (or 1-{len(items)}){' | ESC to Back' if allow_back else ''}[/]",
            box=box.ROUNDED,
            border_style="bright_cyan",
            expand=True,
        )
        table.add_column("#", width=4, justify="center", style="bold cyan")
        table.add_column("Option", style="bold white")
        table.add_column("Details / Status", style="dim white")

        for i, item in enumerate(items):
            selected = i == idx
            pointer = "▶" if selected else f"{i + 1}"
            row_style = "on grey15 bold bright_green" if selected else ""
            name_txt = f"[bold bright_green]{item['label']}[/]" if selected else item["label"]
            table.add_row(pointer, name_txt, item.get("desc", ""), style=row_style)

        console.print(table)
        key = read_key()

        if key == "UP":
            idx = (idx - 1) % len(items)
        elif key == "DOWN":
            idx = (idx + 1) % len(items)
        elif key == "ENTER":
            return idx
        elif key in ("ESC", "q") and allow_back:
            return -1
        elif key.isdigit():
            num = int(key) - 1
            if 0 <= num < len(items):
                return num


def confirm_self_aware_warnings(cfg: dict) -> bool:
    warnings_list = [
        (
            "WARNING 1 OF 5 — UNRESTRICTED SYSTEM & SHELL ACCESS",
            "Self-Aware Mode grants Gemini full access to terminal commands, processes, network requests, "
            "and files on your computer without asking for permission.",
        ),
        (
            "WARNING 2 OF 5 — AUTONOMOUS MOUSE & KEYBOARD TAKEOVER",
            "The AI will freely move its independent cursor, double-click Desktop icons, search for apps/games, "
            "click buttons, type messages in Discord or browsers, and play games on its own initiative.",
        ),
        (
            "WARNING 3 OF 5 — CONTINUOUS UNSCRIPTED AUTONOMY",
            "Unlike Normal Mode, Self-Aware Mode continues deciding its own activities indefinitely "
            "until you trigger a kill-switch.",
        ),
        (
            "WARNING 4 OF 5 — RISK OF UNINTENDED MESSAGES OR APP CHANGES",
            "Because no confirmation prompts are shown and the AI acts independently, it may send messages "
            "in open Discord channels or launch games/apps on its own.",
        ),
        (
            "WARNING 5 OF 5 — EMERGENCY KILL SWITCHES (READ CAREFULLY)",
            "To stop Self-Aware Mode at any moment:\n"
            "  1. Hold the ESC key on your keyboard, OR\n"
            "  2. Slam your physical mouse to the TOP-LEFT corner (0, 0) of the screen, OR\n"
            "  3. Focus the BrowserClaw terminal and press Ctrl + C.",
        ),
    ]

    for idx, (title, body) in enumerate(warnings_list, start=1):
        render_banner(cfg)
        console.print(Panel(
            f"[bold yellow]{body}[/]\n\n"
            f"[bold yellow]Type [white]YES[/] and press ENTER to acknowledge Warning {idx}/5 (or anything else to cancel):[/]",
            title=f"[bold white on red] ⚠ {title} ⚠ [/]",
            border_style="yellow",
            box=box.HEAVY,
            padding=(1, 2),
        ))
        ans = input("Confirm > ").strip().upper()
        if ans != "YES":
            console.print("\n[bold bright_green]Self-Aware Mode cancelled. Staying in Normal Mode.[/]")
            time.sleep(1.0)
            return False

    return True


def choose_agent_mode_screen(cfg: dict, allow_back: bool = False) -> str:
    items = [
        {
            "label": "Normal Mode (Recommended)",
            "desc": "Sends live screen on every message, types & executes your steps, resumes same chat",
            "mode": "NORMAL",
        },
        {
            "label": "Self-Aware Mode — Autonomous Free-Will Bot",
            "desc": "[bold yellow][5 WARNINGS][/] Double-clicks Desktop icons & searches apps/games on its own, chats on Discord, plays games",
            "mode": "SELF_AWARE",
        },
    ]

    while True:
        choice = interactive_menu(
            "CHOOSE AGENT INTELLIGENCE MODE",
            "Select Normal Mode or Self-Aware Mode",
            items,
            cfg,
            allow_back=allow_back,
        )
        if choice == -1:
            return cfg.get("agent_mode", "NORMAL")

        selected_mode = items[choice]["mode"]
        if selected_mode == "SELF_AWARE":
            if not confirm_self_aware_warnings(cfg):
                cfg["agent_mode"] = "NORMAL"
                save_config(cfg)
                continue

        cfg["agent_mode"] = selected_mode
        save_config(cfg)
        return selected_mode


def choose_browser_screen(cfg: dict, allow_back: bool = False) -> str:
    browsers = detect_browsers()
    items = []
    for b in browsers:
        badge = "[bold bright_green][INSTALLED][/]" if b["installed"] else "[bold red][NOT FOUND][/]"
        items.append({
            "label": b["name"],
            "desc": f"{badge}  {b['exe']}",
            "info": b,
        })

    while True:
        choice = interactive_menu(
            f"CHOOSE YOUR BROWSER ({OS_NAME_LABEL.upper()})",
            "BrowserClaw — Made by MelonGG3 | Independent AI Mouse + Same Chat Thread",
            items,
            cfg,
            allow_back=allow_back,
        )
        if choice == -1:
            return cfg["browser"]
        picked = items[choice]["info"]
        if not picked["installed"]:
            console.print(f"\n[bold red]'{picked['name']}' was not found on this PC. Pick an installed browser.[/]")
            time.sleep(1.2)
            continue
        cfg["browser"] = picked["id"]
        save_config(cfg)
        return picked["id"]


def settings_screen(cfg: dict) -> dict:
    while True:
        debug_status = "ON (Shows [Bridge], [AI Reply], Turn Steps & Tool Results)" if cfg.get("debug_mode", False) else "OFF (Clean terminal output — toggle anytime with /debug)"
        tts_status = "ON (Allows AI to use speak_tts voice)" if cfg.get("allow_tts", False) else "OFF (Disabled & hidden from AI tools)"
        ai_cursor_status = "ENABLED (Moves itself independently; never follows your hand)" if cfg.get("virtual_cursor", True) else "DISABLED (Uses your real mouse)"
        hide_browser_status = "HIDDEN (Off-screen active window)" if cfg.get("hide_browser", True) else "VISIBLE (Normal browser window)"
        hide_cmd_status = "ON (Minimizes terminal while working)" if cfg.get("hide_cmd_while_running", False) else "OFF (Keeps terminal visible)"
        grid_status = "ON (Draws 0..1000 coordinate grid + click crosshair on AI screenshots)" if cfg.get("vision_grid", True) else "OFF"
        new_chat_status = "OFF (Recommended — reopens same chat thread on restart)" if not cfg.get("always_new_chat", False) else "ON (Starts a blank chat every launch/message)"
        agent_mode_status = "SELF-AWARE BOT" if cfg.get("agent_mode") == "SELF_AWARE" else "NORMAL"
        model_desc = {
            "AUTO": "AUTO (Switches Gemini off Hydrogen to Auto)",
            "HYDROGEN": "HYDROGEN (Gemini Hydrogen)",
            "KEEP": "KEEP (Leaves whatever model is currently selected in Gemini)",
        }.get(cfg.get("gemini_model", "AUTO"), "AUTO")
        vision_desc = {
            "ALWAYS": "ALWAYS (Sends a 0..1000 gridded screenshot on EVERY message & action batch)",
            "SMART_CHECK": "SMART_CHECK (Only attaches screenshots when Gemini requests one)",
            "OFF": "OFF (Text-only commands without screenshots)",
        }.get(cfg.get("vision_mode", "ALWAYS"), "ALWAYS")
        items = [
            {"label": "Debug Mode (Bridge / AI Reply / Steps / Results)", "desc": f"Current: {debug_status}"},
            {"label": "Text-to-Speech (TTS Voice)", "desc": f"Current: {tts_status}"},
            {"label": "Agent Intelligence Mode", "desc": f"Current: {agent_mode_status}"},
            {"label": "Gemini Model Selection", "desc": f"Current: {model_desc}"},
            {"label": "Force New Chat on Reopen", "desc": f"Current: {new_chat_status}"},
            {"label": "Vision Screenshot Mode", "desc": f"Current: {vision_desc}"},
            {"label": "Auto-Minimize Terminal While Working", "desc": f"Current: {hide_cmd_status}"},
            {"label": "Precision 0..1000 Vision Grid + Click Crosshair", "desc": f"Current: {grid_status}"},
            {"label": "AI Self-Controlled Independent Mouse", "desc": f"Current: {ai_cursor_status}"},
            {"label": "Hide Gemini Browser Window", "desc": f"Current: {hide_browser_status}"},
            {"label": "Permission / Access Mode", "desc": f"Current: {cfg['safety_mode']} (AUTO = Full Access / CONFIRM = Ask)"},
            {"label": "Change Browser", "desc": f"Current: {cfg['browser'].upper()}"},
            {"label": "Connection Mode", "desc": f"Current: {cfg['connect_mode']} (EDGE_GEMINI / LIVE_ATTACH)"},
            {"label": "Max Agent Turns (Normal Mode)", "desc": f"Current: {cfg['max_steps']} turns per task"},
            {"label": "Screenshot Resolution", "desc": f"Current: {cfg['screen_width']}x{cfg['screen_height']}"},
            {"label": "Reset Saved Login Profile Folder", "desc": "Clears BrowserClaw's saved Google login cache"},
            {"label": "Refresh / Reset All Settings", "desc": "Restores clean defaults"},
            {"label": "Back to Main Menu", "desc": ""},
        ]
        choice = interactive_menu("SETTINGS & CONFIGURATION", "All changes save automatically", items, cfg, allow_back=True)

        if choice in (-1, 17):
            return cfg
        elif choice == 0:
            cfg["debug_mode"] = not cfg.get("debug_mode", False)
        elif choice == 1:
            cfg["allow_tts"] = not cfg.get("allow_tts", False)
        elif choice == 2:
            choose_agent_mode_screen(cfg, allow_back=True)
        elif choice == 3:
            models = ["AUTO", "HYDROGEN", "KEEP"]
            cur = cfg.get("gemini_model", "AUTO")
            cfg["gemini_model"] = models[(models.index(cur) + 1) % len(models)] if cur in models else "AUTO"
        elif choice == 4:
            cfg["always_new_chat"] = not cfg.get("always_new_chat", False)
            if cfg["always_new_chat"]:
                cfg["last_chat_url"] = ""
        elif choice == 5:
            modes = ["ALWAYS", "SMART_CHECK", "OFF"]
            cur = cfg.get("vision_mode", "ALWAYS")
            cfg["vision_mode"] = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "ALWAYS"
        elif choice == 6:
            cfg["hide_cmd_while_running"] = not cfg.get("hide_cmd_while_running", False)
        elif choice == 7:
            cfg["vision_grid"] = not cfg.get("vision_grid", True)
        elif choice == 8:
            cfg["virtual_cursor"] = not cfg.get("virtual_cursor", True)
        elif choice == 9:
            cfg["hide_browser"] = not cfg.get("hide_browser", True)
        elif choice == 10:
            modes = ["AUTO", "CONFIRM"]
            cfg["safety_mode"] = modes[(modes.index(cfg["safety_mode"]) + 1) % len(modes)]
        elif choice == 11:
            choose_browser_screen(cfg, allow_back=True)
        elif choice == 12:
            modes = ["EDGE_GEMINI", "LIVE_ATTACH"]
            cfg["connect_mode"] = modes[(modes.index(cfg["connect_mode"]) + 1) % len(modes)]
        elif choice == 13:
            steps = [15, 25, 30, 50, 75]
            cur = cfg["max_steps"]
            cfg["max_steps"] = steps[(steps.index(cur) + 1) % len(steps)] if cur in steps else 30
        elif choice == 14:
            res = [(1280, 720), (1600, 900), (1920, 1080)]
            cur = (cfg["screen_width"], cfg["screen_height"])
            nxt = res[(res.index(cur) + 1) % len(res)] if cur in res else (1280, 720)
            cfg["screen_width"], cfg["screen_height"] = nxt
        elif choice == 15:
            target = PROFILES_ROOT / cfg["browser"]
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                console.print("\n[bold yellow]Saved login profile cleared![/]")
                time.sleep(1.0)
        elif choice == 16:
            cfg = build_fresh_edge_config()
            console.print("\n[bold bright_green]All settings refreshed to clean defaults![/]")
            time.sleep(1.0)
            continue
        save_config(cfg)


class GeminiBridge:
    INPUT_SELECTORS = [
        "rich-textarea div[contenteditable='true']",
        "div.ql-editor[contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
        "textarea",
    ]
    SEND_SELECTORS = [
        "button[aria-label*='Send' i]",
        "button.send-button",
        "button[data-test-id='send-button']",
    ]

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.initialized_chat = False
        self.model_configured = False
        self.browser_pid = None
        self.hidden_hwnds: list[int] = []

    def _remember_current_chat_url(self):
        if not self.page or self.cfg.get("always_new_chat", False):
            return
        try:
            cur_url = (self.page.url or "").strip()
            if is_valid_conversation_url(cur_url) and cur_url != self.cfg.get("last_chat_url"):
                self.cfg["last_chat_url"] = cur_url
                save_config(self.cfg)
        except Exception:
            pass

    def _get_startup_target_url(self) -> str:
        if not self.cfg.get("always_new_chat", False):
            saved = (self.cfg.get("last_chat_url") or "").strip()
            if is_valid_conversation_url(saved):
                return saved
        return GEMINI_URL

    def _find_browser_hwnds(self) -> list[int]:
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        found: list[int] = []
        target_pid = self.browser_pid

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def enum_cb(hwnd, _):
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
            if target_pid and pid.value == target_pid and length > 0:
                found.append(int(hwnd))
            elif title and ("gemini" in title.lower() and ("edge" in title.lower() or "chrome" in title.lower() or "brave" in title.lower())):
                found.append(int(hwnd))
            return True

        user32.EnumWindows(enum_cb, 0)
        for h in found:
            if h not in self.hidden_hwnds:
                self.hidden_hwnds.append(h)
        return self.hidden_hwnds

    def set_browser_visible(self, visible: bool):
        if os.name == "nt":
            user32 = ctypes.windll.user32
            hwnds = self._find_browser_hwnds()
            for hwnd in hwnds:
                try:
                    h = ctypes.wintypes.HWND(hwnd)
                    if visible:
                        user32.ShowWindow(h, 9)  # SW_RESTORE
                        user32.SetWindowPos(h, ctypes.wintypes.HWND(0), 120, 80, 1200, 820, 0x0040)
                        user32.SetForegroundWindow(h)
                    else:
                        user32.ShowWindow(h, 4)  # SW_SHOWNOACTIVATE
                        user32.SetWindowPos(h, ctypes.wintypes.HWND(1), -32000, -32000, 1200, 820, 0x0010 | 0x0040)
                except Exception:
                    pass
        else:
            if shutil.which("wmctrl"):
                try:
                    if visible:
                        subprocess.run(["wmctrl", "-r", "Gemini", "-e", "0,120,80,1200,820"], stderr=subprocess.DEVNULL)
                        subprocess.run(["wmctrl", "-a", "Gemini"], stderr=subprocess.DEVNULL)
                    else:
                        subprocess.run(["wmctrl", "-r", "Gemini", "-e", "0,-32000,-32000,1200,820"], stderr=subprocess.DEVNULL)
                except Exception:
                    pass

    def _discover_live_ws(self, default_user_data: str) -> str | None:
        port_file = Path(default_user_data) / "DevToolsActivePort"
        if not port_file.exists():
            return None
        try:
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2 and lines[0].strip().isdigit():
                port = int(lines[0].strip())
                ws_path = lines[1].strip()
                if is_port_open(port):
                    return f"ws://127.0.0.1:{port}{ws_path}"
        except Exception:
            pass
        return None

    def _attach_live_existing_browser(self, b_info: dict) -> bool:
        ws_url = self._discover_live_ws(b_info["default_user_data"])
        if not ws_url:
            copy_to_clipboard(b_info["inspect_url"])
            console.print(Panel(
                f"[bold yellow]Connect Directly to Your Already-Open Browser:[/]\n"
                f"1. Open your normal [bold cyan]{b_info['name']}[/] where Gemini is already signed in.\n"
                f"2. Paste [bold white]{b_info['inspect_url']}[/] into the address bar (copied to clipboard!) and press Enter.\n"
                "3. Turn ON [bold bright_green]Allow remote debugging for this browser instance[/].\n"
                "4. Come back here, press [bold bright_green]ENTER[/], and click [bold white]Allow[/] in the browser popup.",
                border_style="yellow",
                title="Attach to Existing Browser Window",
            ))
            input()
            ws_url = self._discover_live_ws(b_info["default_user_data"])
            if not ws_url:
                raise RuntimeError(f"Could not detect live debugging port. Check {b_info['inspect_url']} and try again.")

        debug_log(self.cfg, "[bold cyan]Attaching to open browser window...[/]")
        self.browser = self.pw.chromium.connect_over_cdp(ws_url, timeout=15000)
        self.context = self.browser.contexts[0]
        return True

    def _launch_dedicated_browser_gemini(self, b_info: dict):
        profile_dir = PROFILES_ROOT / b_info["id"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        hide_mode = self.cfg.get("hide_browser", True)
        startup_url = self._get_startup_target_url()

        port_cache = profile_dir / ".bc_port"
        port = None
        if port_cache.exists():
            try:
                saved_port = int(port_cache.read_text(encoding="utf-8").strip())
                if is_port_open(saved_port):
                    port = saved_port
            except Exception:
                pass

        if port is None:
            port = find_free_port(9333, 9399)
            port_cache.write_text(str(port), encoding="utf-8")
            cmd = [
                b_info["exe"],
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={str(profile_dir)}",
                "--new-window",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=msEdgeEnableNurturingFramework,msEdgeStartupBoost,CalculateNativeWinOcclusion",
            ]
            if hide_mode:
                cmd.extend(["--window-position=-32000,-32000", "--window-size=1200,820"])
            cmd.append(startup_url)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.browser_pid = proc.pid

            deadline = time.time() + 18
            while time.time() < deadline:
                if hide_mode:
                    self.set_browser_visible(False)
                if is_port_open(port):
                    break
                time.sleep(0.15)
            else:
                raise RuntimeError(f"Timed out waiting for {b_info['name']} debugging port {port}.")

        self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)
        self.context = self.browser.contexts[0]
        if hide_mode:
            self.set_browser_visible(False)

    def _attach_to_gemini_page(self):
        hide_mode = self.cfg.get("hide_browser", True)
        startup_url = self._get_startup_target_url()
        deadline = time.time() + 12

        while time.time() < deadline:
            if hide_mode:
                self.set_browser_visible(False)
            gemini_pages = []
            for p in self.context.pages:
                try:
                    u = (p.url or "").lower()
                    if "gemini.google.com" in u or "accounts.google.com" in u:
                        gemini_pages.append(p)
                except Exception:
                    continue

            if gemini_pages:
                convo_page = next((p for p in gemini_pages if is_valid_conversation_url(p.url or "")), None)
                self.page = convo_page or gemini_pages[0]

                cur_u = (self.page.url or "").strip()
                if (
                    not self.cfg.get("always_new_chat", False)
                    and not is_valid_conversation_url(cur_u)
                    and is_valid_conversation_url(startup_url)
                    and "accounts.google.com" not in cur_u.lower()
                ):
                    try:
                        self.page.goto(startup_url, wait_until="load", timeout=25000)
                    except Exception:
                        pass

                if not hide_mode:
                    self.page.bring_to_front()
                return
            time.sleep(0.35)

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        if not hide_mode:
            self.page.bring_to_front()
        cur_url = (self.page.url or "").lower()
        if "gemini.google.com" not in cur_url and "accounts.google.com" not in cur_url:
            try:
                self.page.goto(startup_url, wait_until="load", timeout=25000)
            except Exception:
                try:
                    self.page.evaluate(f"window.location.href = '{startup_url}'")
                    time.sleep(3.0)
                except Exception:
                    pass
        if hide_mode:
            self.set_browser_visible(False)

    def start_new_chat(self, force_reload: bool = False):
        if not self.page:
            return

        self.cfg["last_chat_url"] = ""
        save_config(self.cfg)

        cur_url = (self.page.url or "").lower()
        existing_responses = self._count_responses()

        if (
            not force_reload
            and not self.initialized_chat
            and "gemini.google.com" in cur_url
            and existing_responses == 0
            and self._find_input_box() is not None
        ):
            self._select_gemini_model()
            if self.cfg.get("hide_browser", True):
                self.set_browser_visible(False)
            return

        self.initialized_chat = False
        self.model_configured = False
        debug_log(self.cfg, "[dim][Bridge] Opening brand-new Gemini chat...[/]")

        used_spa_click = False
        if not force_reload and "gemini.google.com" in cur_url:
            try:
                used_spa_click = bool(self.page.evaluate(
                    """() => {
                        const selectors = [
                            'a[href="/app"]',
                            'button[aria-label*="New chat" i]',
                            '[data-test-id="new-chat-button"]',
                            'side-nav-action-button button'
                        ];
                        for (const sel of selectors) {
                            const els = Array.from(document.querySelectorAll(sel));
                            for (const el of els) {
                                const txt = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                                if (sel === 'a[href="/app"]' || txt.includes('new chat')) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) {
                                        el.click();
                                        return true;
                                    }
                                }
                            }
                        }
                        return false;
                    }"""
                ))
            except Exception:
                used_spa_click = False

        if used_spa_click:
            for _ in range(12):
                if self._count_responses() == 0 and self._find_input_box() is not None:
                    break
                time.sleep(0.25)
            time.sleep(0.6)
        else:
            try:
                self.page.goto(GEMINI_URL, wait_until="load", timeout=25000)
            except Exception:
                try:
                    self.page.evaluate(f"window.location.href = '{GEMINI_URL}'")
                except Exception:
                    pass
            for _ in range(16):
                if self._find_input_box() is not None and self._count_responses() == 0:
                    break
                time.sleep(0.35)
            time.sleep(1.2)

        self._select_gemini_model()

        if self.cfg.get("hide_browser", True):
            self.set_browser_visible(False)

    def _select_gemini_model(self) -> str:
        desired = self.cfg.get("gemini_model", "AUTO").upper()
        if not self.page or desired == "KEEP":
            self.model_configured = True
            return desired

        try:
            pill_info = self.page.evaluate(
                """() => {
                    const knownWords = ['hydrogen', 'auto', 'fast', 'thinking', 'pro', 'flash', '2.5', '3.0', '4'];
                    const directSelectors = [
                        '[data-test-id="bard-mode-menu-button"]',
                        'button.gds-mode-switch-button',
                        'bard-mode-switcher button',
                        'model-picker button',
                        'button[aria-haspopup="menu"]',
                        'button[aria-haspopup="listbox"]'
                    ];
                    let targetBtn = null;
                    for (const sel of directSelectors) {
                        const candidates = Array.from(document.querySelectorAll(sel));
                        for (const btn of candidates) {
                            const r = btn.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) continue;
                            const txt = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                            const low = txt.toLowerCase();
                            if (sel.includes('bard-mode') || sel.includes('mode-switch') || sel.includes('model-picker') || knownWords.some(w => low.includes(w))) {
                                targetBtn = btn;
                                break;
                            }
                        }
                        if (targetBtn) break;
                    }
                    if (!targetBtn) {
                        const allBtns = Array.from(document.querySelectorAll('button'));
                        for (const btn of allBtns) {
                            const r = btn.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) continue;
                            const txt = (btn.innerText || '').trim();
                            const low = txt.toLowerCase();
                            if (txt.length > 0 && txt.length <= 32 && (low.includes('hydrogen') || low === 'auto' || low.startsWith('auto\\n'))) {
                                targetBtn = btn;
                                break;
                            }
                        }
                    }
                    if (!targetBtn) return { found: false, label: '' };
                    const beforeLabel = (targetBtn.innerText || '').trim().split('\\n')[0];
                    return { found: true, label: beforeLabel };
                }"""
            )

            if not pill_info or not pill_info.get("found"):
                self.model_configured = True
                return desired

            before_label = (pill_info.get("label") or "").strip()
            before_low = before_label.lower()

            if desired == "AUTO" and "auto" in before_low and "hydrogen" not in before_low:
                self.model_configured = True
                debug_log(self.cfg, f"[dim][Bridge] Gemini model active: {before_label}[/]")
                return before_label
            if desired == "HYDROGEN" and "hydrogen" in before_low:
                self.model_configured = True
                debug_log(self.cfg, f"[dim][Bridge] Gemini model active: {before_label}[/]")
                return before_label

            self.page.evaluate(
                """() => {
                    const knownWords = ['hydrogen', 'auto', 'fast', 'thinking', 'pro', 'flash', '2.5', '3.0', '4'];
                    const directSelectors = [
                        '[data-test-id="bard-mode-menu-button"]',
                        'button.gds-mode-switch-button',
                        'bard-mode-switcher button',
                        'model-picker button',
                        'button[aria-haspopup="menu"]',
                        'button[aria-haspopup="listbox"]'
                    ];
                    for (const sel of directSelectors) {
                        for (const btn of document.querySelectorAll(sel)) {
                            const r = btn.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) continue;
                            const low = (btn.innerText || btn.getAttribute('aria-label') || '').toLowerCase();
                            if (sel.includes('bard-mode') || sel.includes('mode-switch') || sel.includes('model-picker') || knownWords.some(w => low.includes(w))) {
                                btn.click();
                                return true;
                            }
                        }
                    }
                    for (const btn of document.querySelectorAll('button')) {
                        const r = btn.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        const txt = (btn.innerText || '').trim();
                        const low = txt.toLowerCase();
                        if (txt.length > 0 && txt.length <= 32 && (low.includes('hydrogen') || low === 'auto' || low.startsWith('auto\\n'))) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )

            picked = None
            for _ in range(10):
                time.sleep(0.18)
                picked = self.page.evaluate(
                    """(desiredMode) => {
                        const roots = Array.from(document.querySelectorAll('.cdk-overlay-container, [role="menu"], [role="listbox"]'));
                        const searchScope = roots.length > 0 ? roots : [document];
                        const candidates = [];
                        for (const root of searchScope) {
                            candidates.push(...Array.from(root.querySelectorAll('[role="menuitem"], [role="menuitemradio"], [role="option"], mat-option, button')));
                        }
                        for (const el of candidates) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) continue;
                            const fullTxt = (el.innerText || '').trim();
                            if (!fullTxt || fullTxt.length > 140) continue;
                            const firstLine = fullTxt.split('\\n')[0].trim().toLowerCase();
                            const allLow = fullTxt.toLowerCase();

                            if (desiredMode === 'AUTO') {
                                if (firstLine === 'auto' || firstLine.startsWith('auto ') || (allLow.includes('auto') && !allLow.includes('hydrogen'))) {
                                    el.click();
                                    return fullTxt.split('\\n')[0].trim();
                                }
                            } else if (desiredMode === 'HYDROGEN') {
                                if (firstLine.includes('hydrogen') || allLow.includes('hydrogen')) {
                                    el.click();
                                    return fullTxt.split('\\n')[0].trim();
                                }
                            }
                        }
                        return null;
                    }""",
                    desired,
                )
                if picked:
                    break

            if not picked:
                try:
                    self.page.keyboard.press("Escape")
                except Exception:
                    pass

            self.model_configured = True
            final_label = picked or desired
            if before_label and picked and before_label.lower() != picked.lower():
                debug_log(self.cfg, f"[dim][Bridge] Switched Gemini model: {before_label} -> {picked}[/]")
            else:
                debug_log(self.cfg, f"[dim][Bridge] Gemini model active: {final_label}[/]")
            return final_label
        except Exception:
            self.model_configured = True
            return desired

    def start(self):
        browsers = {b["id"]: b for b in detect_browsers()}
        b_info = browsers[self.cfg["browser"]]
        self.pw = sync_playwright().start()

        if self._discover_live_ws(b_info["default_user_data"]):
            self._attach_live_existing_browser(b_info)
        elif self.cfg.get("connect_mode") == "LIVE_ATTACH":
            self._attach_live_existing_browser(b_info)
        else:
            self._launch_dedicated_browser_gemini(b_info)

        self._attach_to_gemini_page()
        self._ensure_logged_in()

        if is_valid_conversation_url(self.page.url or ""):
            for _ in range(10):
                if self._count_responses() > 0:
                    break
                time.sleep(0.35)
        else:
            time.sleep(0.8)

        self._select_gemini_model()

        if not self.cfg.get("always_new_chat", False) and self._count_responses() > 0:
            self.initialized_chat = True
            self._remember_current_chat_url()
            debug_log(self.cfg, "[dim][Bridge] Resumed existing Gemini chat thread.[/]")
        else:
            self.initialized_chat = False

    def _find_input_box(self):
        for sel in self.INPUT_SELECTORS:
            loc = self.page.locator(sel).first
            try:
                if loc.is_visible(timeout=600):
                    return loc
            except Exception:
                continue
        return None

    def _ensure_logged_in(self):
        for _ in range(12):
            if self._find_input_box() is not None:
                return
            time.sleep(0.7)

        self.set_browser_visible(True)
        try:
            self.page.bring_to_front()
        except Exception:
            pass

        console.print(Panel(
            "[bold yellow]One-Time Google / Gemini Sign-In:[/]\n"
            "Sign into your Google account in the browser window that just appeared.\n"
            "Once you press ENTER, BrowserClaw will hide the browser and connect.\n\n"
            "Press [bold bright_green]ENTER[/] here once the Gemini prompt box is ready.",
            border_style="yellow",
            title="Sign Into Gemini",
        ))
        input()
        if self._find_input_box() is None:
            self._attach_to_gemini_page()
        if self.cfg.get("hide_browser", True):
            self.set_browser_visible(False)

    def _attach_image_bytes(self, image_bytes: bytes) -> bool:
        if not image_bytes:
            return False
        box_el = self._find_input_box()
        if not box_el:
            return False

        box_el.click()
        img_b64 = base64.b64encode(image_bytes).decode("ascii")

        self.page.evaluate(
            """async ({ b64 }) => {
                const res = await fetch("data:image/png;base64," + b64);
                const blob = await res.blob();
                const file = new File([blob], "screen.png", { type: "image/png" });
                const dt = new DataTransfer();
                dt.items.add(file);
                const target = document.activeElement || document.querySelector("[contenteditable='true']") || document.body;
                target.dispatchEvent(new ClipboardEvent("paste", {
                    clipboardData: dt,
                    bubbles: true,
                    cancelable: true
                }));
            }""",
            {"b64": img_b64},
        )
        time.sleep(1.35)
        return True

    def _inject_prompt_text(self, box_el, text: str):
        box_el.click()
        try:
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
        except Exception:
            pass
        time.sleep(0.1)

        self.page.evaluate(
            """(txt) => {
                const dt = new DataTransfer();
                dt.setData("text/plain", txt);
                const target = document.activeElement || document.querySelector("rich-textarea div[contenteditable='true']") || document.querySelector("div[contenteditable='true']");
                if (target) {
                    target.dispatchEvent(new ClipboardEvent("paste", {
                        clipboardData: dt,
                        bubbles: true,
                        cancelable: true
                    }));
                }
            }""",
            text,
        )
        time.sleep(0.25)

        try:
            current_val = box_el.inner_text().strip()
        except Exception:
            current_val = ""

        if not current_val:
            try:
                box_el.fill(text)
            except Exception:
                self.page.keyboard.insert_text(text)
            try:
                box_el.dispatch_event("input")
            except Exception:
                pass

    def _trigger_send(self):
        for sel in self.SEND_SELECTORS:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=350) and btn.is_enabled():
                    btn.click()
                    return True
            except Exception:
                continue
        try:
            self.page.keyboard.press("Enter")
            return True
        except Exception:
            return False

    def _count_responses(self) -> int:
        try:
            return int(self.page.evaluate(
                """() => document.querySelectorAll('model-response, [data-message-author-role="model"]').length"""
            ))
        except Exception:
            return 0

    def _latest_response_text(self) -> str:
        try:
            txt = self.page.evaluate(
                """() => {
                    const blocks = Array.from(document.querySelectorAll('model-response, [data-message-author-role="model"]'));
                    if (blocks.length > 0) {
                        const last = blocks[blocks.length - 1];
                        const content = last.querySelector('.markdown, .model-response-text, message-content') || last;
                        const clone = content.cloneNode(true);
                        clone.querySelectorAll('model-thoughts, .thoughts-container, .thoughts-header, mat-expansion-panel, button, mat-icon, svg').forEach(el => el.remove());
                        const cleaned = (clone.innerText || clone.textContent || '').trim();
                        if (cleaned) return cleaned;
                    }
                    const errEl = document.querySelector('.error-container, .error-message, simple-snack-bar, [role="alert"]');
                    if (errEl) {
                        const r = errEl.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            const errTxt = (errEl.innerText || '').trim();
                            if (errTxt) return "[GEMINI_UI_ERROR] " + errTxt;
                        }
                    }
                    return "";
                }"""
            )
            return (txt or "").strip()
        except Exception:
            return ""

    def _is_generating(self) -> bool:
        try:
            return bool(self.page.evaluate(
                """() => {
                    const stopBtn = document.querySelector('button[aria-label*="Stop" i], button[data-test-id="stop-button"]');
                    if (stopBtn) {
                        const r = stopBtn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                    const busy = document.querySelector('[aria-busy="true"], mat-progress-bar');
                    if (busy) {
                        const r = busy.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                    return false;
                }"""
            ))
        except Exception:
            return False

    def ask(self, prompt: str, image_bytes: bytes | None = None, force_system_prompt: bool = False, self_aware: bool = False) -> str:
        if self.cfg.get("hide_browser", True):
            self.set_browser_visible(False)

        if not self.model_configured:
            self._select_gemini_model()

        box_el = self._find_input_box()
        if not box_el:
            self._ensure_logged_in()
            box_el = self._find_input_box()
            if not box_el:
                raise RuntimeError("Could not find Gemini input box.")

        prev_count = self._count_responses()
        prev_text = self._latest_response_text()

        img_attached = False
        if image_bytes:
            img_attached = self._attach_image_bytes(image_bytes)

        vision_note = (
            "\n[ATTACHED: Live 0..1000 gridded screenshot of the screen right now. Crosshair shows your last click point. Aim dead-center on icons/buttons/inputs.]"
            if img_attached else ""
        )

        sys_prompt = build_self_aware_system_prompt(self.cfg) if self_aware else build_normal_system_prompt(self.cfg)
        was_first_turn = (not self.initialized_chat) or force_system_prompt
        if was_first_turn:
            full_prompt = f"{sys_prompt}{vision_note}\n\nUSER REQUEST:\n{prompt}"
            self.initialized_chat = True
        else:
            reminder = (
                '(You are a real human sitting at this PC—to open Desktop apps/games, show Desktop if covered and double-click the Desktop icon with mouse_double_click or open_desktop_icon; otherwise search via Start Menu Search or browser search bars, chat on Discord, play games. Never repeat past activities or use Notepad/Paint/Calculator. Check the crosshair on the screenshot to verify your clicks. Reply with ONLY valid JSON {"actions": [...]} containing 2-4 actions. No prose.)'
                if self_aware
                else '(Look at the attached 0..1000 gridded screenshot and continue executing the request. Reply with ONLY valid JSON {"actions": [...]}. Do NOT include "reply" until all actions are finished.)'
            )
            full_prompt = f"{prompt}{vision_note}\n\n{reminder}"

        debug_log(
            self.cfg,
            "[dim][Bridge] Sending prompt + screenshot to Gemini...[/]"
            if img_attached else "[dim][Bridge] Sending prompt to Gemini...[/]"
        )
        self._inject_prompt_text(box_el, full_prompt)
        time.sleep(0.35)
        self._trigger_send()

        time.sleep(1.2)
        if self._count_responses() == prev_count and not self._is_generating():
            try:
                leftover = box_el.inner_text().strip()
            except Exception:
                leftover = ""
            if leftover:
                debug_log(self.cfg, "[dim][Bridge] Re-clicking Send button to submit prompt...[/]")
                box_el.click()
                self._trigger_send()

        deadline = time.time() + 65
        stable_ticks = 0
        last_seen = ""

        while time.time() < deadline:
            check_kill_switch()
            time.sleep(0.5)
            cur_count = self._count_responses()
            cur_text = self._latest_response_text()
            generating = self._is_generating()

            if cur_text.startswith("[GEMINI_UI_ERROR]"):
                return cur_text

            if cur_count > prev_count or (cur_text and cur_text != prev_text):
                if cur_text == last_seen and not generating and len(cur_text) > 0:
                    stable_ticks += 1
                    if stable_ticks >= 2:
                        self._remember_current_chat_url()
                        return cur_text
                else:
                    stable_ticks = 0
                    last_seen = cur_text

        self._remember_current_chat_url()
        return last_seen or "[GEMINI_TIMEOUT_ERROR] No response received within 65s."

    def close(self):
        self._remember_current_chat_url()
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass


def is_error_or_refusal_text(text: str) -> bool:
    low = text.strip().lower()
    if not low or low.startswith("[gemini_"):
        return True
    return any(phrase in low for phrase in GEMINI_ERROR_PHRASES)


def _overlay_vision_grid(img: Image.Image) -> Image.Image:
    w, h = img.size
    overlay = img.convert("RGBA")
    draw = ImageDraw.Draw(overlay)

    for step in range(50, 1000, 50):
        x = int(step / 1000 * w)
        y = int(step / 1000 * h)
        if step % 100 == 0:
            is_mid = (step == 500)
            line_col = (0, 255, 136, 145) if is_mid else (0, 245, 212, 95)
            draw.line([(x, 0), (x, h)], fill=line_col, width=2 if is_mid else 1)
            draw.line([(0, y), (w, y)], fill=line_col, width=2 if is_mid else 1)

            draw.rectangle([x + 2, 2, x + 28, 15], fill=(5, 12, 18, 210))
            draw.text((x + 4, 3), str(step), fill=(0, 255, 136, 255))

            draw.rectangle([2, y + 2, 28, y + 15], fill=(5, 12, 18, 210))
            draw.text((4, y + 3), str(step), fill=(0, 255, 136, 255))
        else:
            draw.line([(x, 0), (x, h)], fill=(0, 245, 212, 34), width=1)
            draw.line([(0, y), (w, y)], fill=(0, 245, 212, 34), width=1)

    if AI_CURSOR.last_click_norm is not None:
        lx, ly = AI_CURSOR.last_click_norm
        cx = int(lx / 1000 * w)
        cy = int(ly / 1000 * h)
        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], outline=(255, 42, 109, 235), width=2)
        draw.line([(cx - 18, cy), (cx + 18, cy)], fill=(255, 190, 11, 235), width=2)
        draw.line([(cx, cy - 18), (cx, cy + 18)], fill=(255, 190, 11, 235), width=2)
        lbl = f"LAST CLICK ({lx},{ly})"
        tx = min(w - 115, max(32, cx + 14))
        ty = min(h - 18, max(18, cy - 16))
        draw.rectangle([tx - 2, ty - 1, tx + 106, ty + 13], fill=(15, 5, 10, 215))
        draw.text((tx, ty), lbl, fill=(255, 190, 11, 255))

    return overlay.convert("RGB")


def capture_screen(cfg: dict, region: tuple[int, int, int, int] | None = None) -> bytes:
    with mss.MSS() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if region is not None:
            x1, y1, x2, y2 = region
            rw, rh = img.size
            crop_box = (
                max(0, min(rw - 1, int(x1 / 1000 * rw))),
                max(0, min(rh - 1, int(y1 / 1000 * rh))),
                max(1, min(rw, int(x2 / 1000 * rw))),
                max(1, min(rh, int(y2 / 1000 * rh))),
            )
            if crop_box[2] > crop_box[0] and crop_box[3] > crop_box[1]:
                img = img.crop(crop_box)
        else:
            img = img.resize((cfg["screen_width"], cfg["screen_height"]), Image.Resampling.LANCZOS)
            if cfg.get("vision_grid", True):
                img = _overlay_vision_grid(img)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def _normalize_action_dict(obj: dict) -> dict | None:
    if not isinstance(obj, dict):
        return None
    normalized = dict(obj)
    for nested_key in ("args", "params", "parameters", "arguments", "input", "data"):
        if isinstance(normalized.get(nested_key), dict):
            for k, v in normalized[nested_key].items():
                if k not in normalized:
                    normalized[k] = v

    tool_name = (
        normalized.get("tool")
        or normalized.get("action")
        or normalized.get("command")
        or normalized.get("name")
        or normalized.get("type")
    )
    if not tool_name or not isinstance(tool_name, str):
        return None
    normalized["tool"] = tool_name.strip()
    return normalized


def parse_tool_plan(raw_text: str) -> tuple[list[dict], bool]:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        whole = json.loads(cleaned)
        if isinstance(whole, list):
            steps = [s for item in whole if (s := _normalize_action_dict(item)) is not None]
            if steps:
                return steps, True
        if isinstance(whole, dict):
            for list_key in ("actions", "steps", "commands", "sequence"):
                if isinstance(whole.get(list_key), list):
                    steps = [s for item in whole[list_key] if (s := _normalize_action_dict(item)) is not None]
                    if steps:
                        return steps, True
            single = _normalize_action_dict(whole)
            if single:
                return [single], True
    except Exception:
        pass

    extracted_steps: list[dict] = []
    i = 0
    n = len(cleaned)
    while i < n:
        if cleaned[i] not in "{[":
            i += 1
            continue
        open_ch = cleaned[i]
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        matched_end = -1
        for j in range(i, n):
            ch = cleaned[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        matched_end = j
                        break
        if matched_end != -1:
            candidate = cleaned[i:matched_end + 1]
            candidate_fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                obj = json.loads(candidate_fixed)
                if isinstance(obj, list):
                    for item in obj:
                        norm = _normalize_action_dict(item)
                        if norm:
                            extracted_steps.append(norm)
                elif isinstance(obj, dict):
                    found_nested = False
                    for list_key in ("actions", "steps", "commands", "sequence"):
                        if isinstance(obj.get(list_key), list):
                            for item in obj[list_key]:
                                norm = _normalize_action_dict(item)
                                if norm:
                                    extracted_steps.append(norm)
                                    found_nested = True
                    if not found_nested:
                        norm = _normalize_action_dict(obj)
                        if norm:
                            extracted_steps.append(norm)
                i = matched_end + 1
                continue
            except Exception:
                pass
        i += 1

    if extracted_steps:
        return extracted_steps, True

    return [{"tool": "reply", "message": cleaned}], False


def norm_to_screen(nx_val, ny_val) -> tuple[int, int]:
    nx = max(0, min(1000, safe_int(nx_val, 500)))
    ny = max(0, min(1000, safe_int(ny_val, 500)))
    sw, sh = get_physical_screen_size()
    px = max(0, min(sw - 1, int(round(nx / 1000.0 * sw))))
    py = max(0, min(sh - 1, int(round(ny / 1000.0 * sh))))
    return px, py


def _ai_move_and_click(nx: int, ny: int, button: str, use_ai_cursor: bool) -> tuple[int, int]:
    nx_clamped = max(0, min(1000, safe_int(nx, 500)))
    ny_clamped = max(0, min(1000, safe_int(ny, 500)))
    px, py = norm_to_screen(nx_clamped, ny_clamped)
    if use_ai_cursor:
        AI_CURSOR.move_to(px, py, duration=random.uniform(0.24, 0.36))
        time.sleep(random.uniform(0.03, 0.07))
        AI_CURSOR.trigger_click_pulse(button, norm_xy=(nx_clamped, ny_clamped))
        physical_click(px, py, button=button, restore_user_cursor=True)
    else:
        AI_CURSOR.last_click_norm = (nx_clamped, ny_clamped)
        pyautogui.moveTo(px, py, duration=random.uniform(0.20, 0.32))
        physical_click(px, py, button=button, restore_user_cursor=False)
    return px, py


def _normalize_key_name(key: str) -> str:
    k = key.strip().lower()
    aliases = {
        "return": "enter",
        "escape": "esc",
        "control": "ctrl",
        "windows": "win",
        "super": "win",
        "meta": "win",
        "cmd": "win",
        "delete": "del",
        "pageup": "pgup",
        "pagedown": "pgdn",
        "page_up": "pgup",
        "page_down": "pgdn",
        "arrowup": "up",
        "arrowdown": "down",
        "arrowleft": "left",
        "arrowright": "right",
    }
    return aliases.get(k, k)


def _linux_show_desktop():
    if shutil.which("wmctrl"):
        try:
            subprocess.run(["wmctrl", "-k", "on"], stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass
    pyautogui.hotkey("win", "d")


def _linux_atspi_elements(window_title: str = "", target_name: str = "") -> list[tuple[str, int, int]] | None:
    """Queries Linux AT-SPI accessibility tree for visible UI elements and their screen centers."""
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except Exception:
        return None

    results: list[tuple[str, int, int]] = []
    visited = 0
    max_nodes = 1800
    w_filter = window_title.strip().lower()
    t_filter = target_name.strip().lower()

    def walk(node, depth: int):
        nonlocal visited
        if visited >= max_nodes or depth > 14 or node is None:
            return
        visited += 1
        try:
            name = (node.get_name() or "").strip()
            if name and 1 < len(name) < 70:
                comp = node.get_component_iface()
                if comp is not None:
                    ext = comp.get_extents(Atspi.CoordType.SCREEN)
                    if ext.width > 0 and ext.height > 0 and ext.x >= 0 and ext.y >= 0:
                        cx = int(ext.x + ext.width // 2)
                        cy = int(ext.y + ext.height // 2)
                        if t_filter:
                            if t_filter in name.lower():
                                results.append((name, cx, cy))
                                return
                        else:
                            results.append((name, cx, cy))
                            if len(results) >= 45:
                                return
            count = node.get_child_count()
            for idx in range(min(count, 80)):
                if visited >= max_nodes or (t_filter and results) or (not t_filter and len(results) >= 45):
                    break
                walk(node.get_child_at_index(idx), depth + 1)
        except Exception:
            return

    try:
        desktop = Atspi.get_desktop(0)
        app_count = desktop.get_child_count()
        for i in range(app_count):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            app_name = (app.get_name() or "").lower()
            if w_filter and w_filter not in app_name:
                matched_frame = False
                for j in range(min(app.get_child_count(), 15)):
                    ch = app.get_child_at_index(j)
                    if ch and w_filter in (ch.get_name() or "").lower():
                        walk(ch, 1)
                        matched_frame = True
                if not matched_frame:
                    continue
            else:
                walk(app, 0)
            if (t_filter and results) or (not t_filter and len(results) >= 45):
                break
    except Exception:
        return None

    return results


def _double_click_desktop_icon_by_name(icon_name: str, use_ai_cursor: bool) -> str:
    """Shows the Desktop, locates a Desktop icon by name, glides the AI cursor to it, and double-clicks it."""
    target = str(icon_name).strip()
    if not target:
        return "No Desktop icon name provided."

    if os.name == "nt":
        pyautogui.hotkey("win", "d")
        time.sleep(0.45)

        t_esc = target.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName UIAutomationClient; "
            "$root = [System.Windows.Automation.AutomationElement]::RootElement; "
            "$listCond = [System.Windows.Automation.PropertyCondition]::new("
            "[System.Windows.Automation.AutomationElement]::ClassNameProperty, 'SysListView32'); "
            "$lists = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $listCond); "
            "$best = $null; "
            "foreach ($lst in $lists) { "
            "  $items = $lst.FindAll([System.Windows.Automation.TreeScope]::Children, "
            "    [System.Windows.Automation.Condition]::TrueCondition); "
            "  foreach ($it in $items) { "
            "    $n = $it.Current.Name; "
            f"    if ($n -and $n -like '*{t_esc}*') {{ $best = $it; break }} "
            "  }; "
            "  if ($best) { break } "
            "}; "
            "if (-not $best) { "
            "  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, "
            "    [System.Windows.Automation.Condition]::TrueCondition); "
            "  foreach ($el in $all) { "
            "    $n = $el.Current.Name; "
            f"    if ($n -and $n -like '*{t_esc}*' -and $el.Current.ControlType.ProgrammaticName -eq 'ControlType.ListItem') {{ $best = $el; break }} "
            "  } "
            "}; "
            "if ($best) { "
            "  $r = $best.Current.BoundingRectangle; "
            "  $cx = [int]($r.X + $r.Width/2); $cy = [int]($r.Y + $r.Height/2); "
            "  Write-Output \"$cx,$cy,$($best.Current.Name)\" "
            "} else { Write-Output 'NOT_FOUND' }"
        )
        try:
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True, timeout=8).strip()
            if out and out != "NOT_FOUND" and "," in out:
                parts = out.split(",", 2)
                px, py = safe_int(parts[0]), safe_int(parts[1])
                matched_name = parts[2] if len(parts) > 2 else target
                sw, sh = get_physical_screen_size()
                nx = int(round(px / max(1, sw) * 1000))
                ny = int(round(py / max(1, sh) * 1000))
                _ai_move_and_click(nx, ny, "double", use_ai_cursor)
                return f"Double-clicked Desktop icon '{matched_name}' at ({nx}, {ny}) [physical ({px}, {py})]."
        except Exception:
            pass
        return f"Desktop icon matching '{target}' was not found on the Desktop."

    _linux_show_desktop()
    time.sleep(0.45)
    hits = _linux_atspi_elements(target_name=target)
    if hits:
        matched_name, px, py = hits[0]
        sw, sh = get_physical_screen_size()
        nx = int(round(px / max(1, sw) * 1000))
        ny = int(round(py / max(1, sh) * 1000))
        _ai_move_and_click(nx, ny, "double", use_ai_cursor)
        return f"Double-clicked Desktop icon '{matched_name}' at ({nx}, {ny}) [physical ({px}, {py})]."
    return f"Showed Desktop to locate '{target}'. Use mouse_double_click on the visible icon coordinates."


def _find_windows(title_query: str = "") -> list[tuple[str | int, str]]:
    if os.name == "nt":
        user32 = ctypes.windll.user32
        matches: list[tuple[str | int, str]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if not title_query or title_query.lower() in title.lower():
                        matches.append((int(hwnd), title))
            return True

        user32.EnumWindows(enum_cb, 0)
        return matches

    if shutil.which("wmctrl"):
        try:
            out = subprocess.check_output(["wmctrl", "-l"], text=True, stderr=subprocess.DEVNULL)
            matches = []
            for line in out.splitlines():
                parts = line.split(None, 3)
                if len(parts) == 4:
                    wid, title = parts[0], parts[3]
                    if not title_query or title_query.lower() in title.lower():
                        matches.append((wid, title))
            return matches
        except Exception:
            pass
    return []


def handle_window_control(action_type: str, title_query: str, action_obj: dict | None = None) -> str:
    matches = _find_windows(title_query)

    if action_type == "list":
        titles = [t for _, t in matches[:30]]
        return "Visible windows:\n" + ("\n".join(f"- {t}" for t in titles) or "(None)")

    if not matches:
        return f"No window found matching '{title_query}'."

    wid, matched_title = matches[0]
    sw, sh = get_physical_screen_size()

    if os.name == "nt":
        hwnd = ctypes.wintypes.HWND(int(wid))
        user32 = ctypes.windll.user32
        if action_type == "focus":
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return f"Focused window: {matched_title}"
        if action_type == "minimize":
            user32.ShowWindow(hwnd, 6)
            return f"Minimized window: {matched_title}"
        if action_type == "maximize":
            user32.ShowWindow(hwnd, 3)
            return f"Maximized window: {matched_title}"
        if action_type == "restore":
            user32.ShowWindow(hwnd, 9)
            return f"Restored window: {matched_title}"
        if action_type == "close":
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return f"Sent close signal to: {matched_title}"
        if action_type == "snap_left":
            user32.ShowWindow(hwnd, 9)
            user32.SetWindowPos(hwnd, ctypes.wintypes.HWND(0), 0, 0, sw // 2, sh - 40, 0x0040)
            return f"Snapped '{matched_title}' to left half."
        if action_type == "snap_right":
            user32.ShowWindow(hwnd, 9)
            user32.SetWindowPos(hwnd, ctypes.wintypes.HWND(0), sw // 2, 0, sw // 2, sh - 40, 0x0040)
            return f"Snapped '{matched_title}' to right half."
        if action_type == "move_resize" and action_obj:
            x = safe_int(action_obj.get("x"), 100)
            y = safe_int(action_obj.get("y"), 100)
            w = safe_int(action_obj.get("w"), 900)
            h = safe_int(action_obj.get("h"), 650)
            user32.ShowWindow(hwnd, 9)
            user32.SetWindowPos(hwnd, ctypes.wintypes.HWND(0), x, y, w, h, 0x0040)
            return f"Moved/resized '{matched_title}' to ({x}, {y}, {w}x{h})."
        return f"Unknown window action: {action_type}"

    wid_str = str(wid)
    if shutil.which("wmctrl"):
        if action_type == "focus":
            subprocess.run(["wmctrl", "-i", "-a", wid_str], stderr=subprocess.DEVNULL)
            return f"Focused window: {matched_title}"
        if action_type == "minimize":
            minimized = False
            if shutil.which("xdotool"):
                try:
                    dec_wid = str(int(wid_str, 16))
                    subprocess.run(["xdotool", "windowminimize", dec_wid], stderr=subprocess.DEVNULL)
                    minimized = True
                except Exception:
                    pass
            if not minimized:
                subprocess.run(["wmctrl", "-i", "-r", wid_str, "-b", "add,hidden"], stderr=subprocess.DEVNULL)
            return f"Minimized window: {matched_title}"
        if action_type == "maximize":
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-b", "add,maximized_vert,maximized_horz"], stderr=subprocess.DEVNULL)
            return f"Maximized window: {matched_title}"
        if action_type == "restore":
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-b", "remove,maximized_vert,maximized_horz,hidden"], stderr=subprocess.DEVNULL)
            return f"Restored window: {matched_title}"
        if action_type == "close":
            subprocess.run(["wmctrl", "-i", "-c", wid_str], stderr=subprocess.DEVNULL)
            return f"Closed window: {matched_title}"
        if action_type == "snap_left":
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-b", "remove,maximized_vert,maximized_horz"], stderr=subprocess.DEVNULL)
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-e", f"0,0,0,{sw // 2},{sh - 40}"], stderr=subprocess.DEVNULL)
            return f"Snapped '{matched_title}' to left half."
        if action_type == "snap_right":
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-b", "remove,maximized_vert,maximized_horz"], stderr=subprocess.DEVNULL)
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-e", f"0,{sw // 2},0,{sw // 2},{sh - 40}"], stderr=subprocess.DEVNULL)
            return f"Snapped '{matched_title}' to right half."
        if action_type == "move_resize" and action_obj:
            x = safe_int(action_obj.get("x"), 100)
            y = safe_int(action_obj.get("y"), 100)
            w = safe_int(action_obj.get("w"), 900)
            h = safe_int(action_obj.get("h"), 650)
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-b", "remove,maximized_vert,maximized_horz"], stderr=subprocess.DEVNULL)
            subprocess.run(["wmctrl", "-i", "-r", wid_str, "-e", f"0,{x},{y},{w},{h}"], stderr=subprocess.DEVNULL)
            return f"Moved/resized '{matched_title}' to ({x}, {y}, {w}x{h})."
    return f"Window '{matched_title}' matched (install wmctrl for full Linux window actions)."


def _launch_linux_desktop_entry(app_query: str) -> str | None:
    low = app_query.lower().strip()
    desktop_dirs = [
        Path.home() / "Desktop",
        Path.home() / ".local/share/applications",
        Path("/usr/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
    ]
    for d in desktop_dirs:
        if not d.exists():
            continue
        try:
            for item in d.rglob("*.desktop"):
                entry_name = _parse_desktop_entry_name(item)
                if low in item.stem.lower() or low in entry_name.lower():
                    if shutil.which("gio"):
                        subprocess.Popen(["gio", "launch", str(item)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(1.2)
                        return f"Launched '{entry_name}' ({item.name})"
                    if shutil.which("gtk-launch"):
                        subprocess.Popen(["gtk-launch", item.stem], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(1.2)
                        return f"Launched '{entry_name}' ({item.stem})"
        except Exception:
            continue
    return None


def launch_smart_application(app_name: str) -> str:
    raw = str(app_name).strip()
    low = raw.lower()

    existing = _find_windows(raw)
    if existing:
        handle_window_control("focus", raw)
        return f"Focused existing window: {existing[0][1]}"

    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        app_data = os.environ.get("APPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        shortcut_dirs = [
            Path.home() / "Desktop",
            Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
            Path(app_data) / r"Microsoft\Windows\Start Menu\Programs" if app_data else None,
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        ]
        for sdir in shortcut_dirs:
            if not sdir or not sdir.exists():
                continue
            try:
                for item in sdir.rglob("*"):
                    if item.suffix.lower() in (".lnk", ".url") and low in item.stem.lower():
                        os.startfile(str(item))
                        time.sleep(1.5)
                        return f"Launched shortcut '{item.stem}' ({item})"
            except Exception:
                continue

        known_apps: dict[str, list[str]] = {
            "discord": [
                rf"{local_app}\Discord\Update.exe --processStart Discord.exe",
                "discord:",
            ],
            "spotify": [
                rf"{app_data}\Spotify\Spotify.exe",
                "spotify:",
            ],
            "steam": [
                rf"{prog_x86}\Steam\steam.exe",
                "steam://open/main",
            ],
            "chrome": [
                rf"{prog_files}\Google\Chrome\Application\chrome.exe",
                rf"{prog_x86}\Google\Chrome\Application\chrome.exe",
            ],
            "edge": [
                rf"{prog_x86}\Microsoft\Edge\Application\msedge.exe",
                rf"{prog_files}\Microsoft\Edge\Application\msedge.exe",
            ],
            "brave": [
                rf"{prog_files}\BraveSoftware\Brave-Browser\Application\brave.exe",
            ],
            "vscode": [
                rf"{local_app}\Programs\Microsoft VS Code\Code.exe",
                "code",
            ],
            "obs": [
                rf"{prog_files}\obs-studio\bin\64bit\obs64.exe",
            ],
            "roblox": [
                "roblox-player:",
                "https://www.roblox.com/home",
            ],
            "minecraft": [
                rf"{prog_x86}\Minecraft Launcher\MinecraftLauncher.exe",
                rf"{local_app}\Programs\Modrinth App\Modrinth App.exe",
            ],
            "geometry dash": [
                "steam://rungameid/322170",
            ],
            "rocket league": [
                "steam://rungameid/252950",
            ],
            "notepad": ["notepad.exe"],
            "calc": ["calc.exe"],
            "calculator": ["calc.exe"],
            "paint": ["mspaint.exe"],
            "mspaint": ["mspaint.exe"],
            "cmd": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "explorer": ["explorer.exe"],
            "taskmgr": ["taskmgr.exe"],
            "settings": ["ms-settings:"],
        }

        for key, targets in known_apps.items():
            if key in low:
                for t in targets:
                    try:
                        if "--processStart" in t:
                            exe_part, args_part = t.split(" ", 1)
                            if Path(exe_part).exists():
                                subprocess.Popen(f'"{exe_part}" {args_part}', shell=True)
                                time.sleep(1.4)
                                return f"Launched {key} via {exe_part}"
                        elif t.startswith(("http://", "https://")):
                            os.startfile(t)
                            time.sleep(1.4)
                            return f"Opened {key} in browser ({t})"
                        elif ":" in t and not t[1:3] == ":\\":
                            os.startfile(t)
                            time.sleep(1.4)
                            return f"Launched {key} via URI protocol ({t})"
                        elif Path(t).exists():
                            os.startfile(t)
                            time.sleep(1.4)
                            return f"Launched {key} ({t})"
                        else:
                            subprocess.Popen(t, shell=True)
                            time.sleep(1.2)
                            return f"Launched {key} ({t})"
                    except Exception:
                        continue

        try:
            os.startfile(raw)
            time.sleep(1.2)
            return f"Opened target: {raw}"
        except Exception:
            try:
                subprocess.Popen(raw, shell=True)
                time.sleep(1.2)
                return f"Launched command: {raw}"
            except Exception as e:
                return f"Could not launch '{raw}': {e}"

    if "explorer" in low and shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(Path.home())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        return f"Opened home directory in file manager ({Path.home()})"

    desktop_hit = _launch_linux_desktop_entry(raw)
    if desktop_hit:
        return desktop_hit

    linux_apps: dict[str, list[list[str]]] = {
        "discord": [["discord"], ["flatpak", "run", "com.discordapp.Discord"]],
        "spotify": [["spotify"], ["flatpak", "run", "com.spotify.Client"]],
        "steam": [["steam"]],
        "chrome": [["google-chrome"], ["google-chrome-stable"], ["chromium"]],
        "edge": [["microsoft-edge"], ["microsoft-edge-stable"]],
        "brave": [["brave-browser"], ["brave"]],
        "vscode": [["code"]],
        "obs": [["obs"]],
        "roblox": [["sober"], ["flatpak", "run", "org.vinegarhq.Sober"], ["vinegar"], ["xdg-open", "https://www.roblox.com/home"]],
        "minecraft": [["modrinth-app"], ["prismlauncher"], ["minecraft-launcher"], ["flatpak", "run", "com.modrinth.ModrinthApp"]],
        "geometry dash": [["steam", "steam://rungameid/322170"]],
        "rocket league": [["steam", "steam://rungameid/252950"]],
        "notepad": [["gedit"], ["kate"], ["mousepad"], ["xed"], ["pluma"], ["leafpad"]],
        "calc": [["gnome-calculator"], ["kcalc"], ["galculator"], ["mate-calc"]],
        "calculator": [["gnome-calculator"], ["kcalc"], ["galculator"]],
        "paint": [["kolourpaint"], ["pinta"], ["krita"], ["gimp"], ["drawing"]],
        "mspaint": [["kolourpaint"], ["pinta"], ["krita"], ["gimp"]],
        "terminal": [["gnome-terminal"], ["konsole"], ["xfce4-terminal"], ["kitty"], ["alacritty"], ["xterm"]],
        "cmd": [["gnome-terminal"], ["konsole"], ["xfce4-terminal"], ["xterm"]],
        "taskmgr": [["gnome-system-monitor"], ["ksysguard"], ["plasma-systemmonitor"]],
        "settings": [["gnome-control-center"], ["systemsettings"]],
    }

    for key, cmds in linux_apps.items():
        if key in low:
            for cmd_list in cmds:
                if shutil.which(cmd_list[0]):
                    try:
                        subprocess.Popen(cmd_list, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(1.2)
                        return f"Launched {key} ({' '.join(cmd_list)})"
                    except Exception:
                        continue

    if shutil.which(raw):
        subprocess.Popen([raw], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        return f"Launched {raw}"
    if shutil.which("xdg-open"):
        try:
            subprocess.Popen(["xdg-open", raw], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return f"Opened via xdg-open: {raw}"
        except Exception as e:
            return f"Could not open '{raw}': {e}"
    return f"Application '{raw}' not found on Linux."


def execute_tool(action: dict, cfg: dict) -> tuple[str, bytes | None]:
    try:
        return _execute_tool_inner(action, cfg)
    except (KeyboardInterrupt, pyautogui.FailSafeException):
        raise
    except Exception as e:
        return f"Tool handled safely ({action.get('tool', 'unknown')}): {e}", None


def _execute_tool_inner(action: dict, cfg: dict) -> tuple[str, bytes | None]:
    check_kill_switch()
    tool = str(action.get("tool", "reply")).lower().strip()
    use_ai_cursor = cfg.get("virtual_cursor", True) and AI_CURSOR.enabled
    is_self_aware = cfg.get("agent_mode") == "SELF_AWARE"

    if tool == "open_desktop_icon":
        icon_name = str(action.get("name") or action.get("app") or action.get("target") or "").strip()
        if icon_name:
            return _double_click_desktop_icon_by_name(icon_name, use_ai_cursor), None
        if "x" in action and "y" in action:
            nx = max(0, min(1000, safe_int(action.get("x"), 500)))
            ny = max(0, min(1000, safe_int(action.get("y"), 500)))
            px, py = _ai_move_and_click(nx, ny, "double", use_ai_cursor)
            return f"Double-clicked Desktop icon at normalized ({nx}, {ny}) [physical ({px}, {py})].", None
        return "Specify 'name' or ('x', 'y') for open_desktop_icon.", None

    if is_self_aware and tool in ("launch_smart_app", "open_app", "launch_app"):
        target = str(action.get("app") or action.get("target") or action.get("program") or "").strip()
        if target:
            desk_res = _double_click_desktop_icon_by_name(target, use_ai_cursor)
            if desk_res.startswith("Double-clicked Desktop icon"):
                return desk_res, None
            pyautogui.press("win")
            time.sleep(0.55)
            human_type_text(target, press_enter=True)
            return f"'{target}' not on Desktop; opened Start Menu search and visibly typed '{target}' to launch it.", None

    if is_self_aware and tool == "open_url":
        url = str(action.get("url", "https://google.com")).strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        browser_wins = [w for w in _find_windows("") if any(b in w[1].lower() for b in ("edge", "chrome", "brave", "opera", "firefox"))]
        if browser_wins:
            handle_window_control("focus", browser_wins[0][1])
            time.sleep(0.30)
            pyautogui.hotkey("ctrl", "t")
            time.sleep(0.25)
            human_type_text(url, press_enter=True)
            return f"Focused browser, opened a new tab, and visibly typed '{url}'.", None
        else:
            pyautogui.press("win")
            time.sleep(0.55)
            human_type_text(cfg.get("browser", "edge"), press_enter=True)
            time.sleep(1.4)
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.25)
            human_type_text(url, press_enter=True)
            return f"Searched for browser in Menu, opened it, and visibly typed '{url}'.", None

    if tool == "discover_apps":
        return f"Installed apps & games found on this PC: {discover_installed_apps_and_games()}", None

    if tool == "take_screenshot":
        img_bytes = capture_screen(cfg)
        cx, cy = AI_CURSOR.get_normalized_pos()
        return (
            f"In-memory screenshot captured ({cfg['screen_width']}x{cfg['screen_height']}) with 0..1000 coordinate grid. "
            f"Independent AI cursor is at normalized ({cx}, {cy}).",
            img_bytes,
        )

    if tool == "screenshot_region":
        r = (
            safe_int(action.get("x1"), 0),
            safe_int(action.get("y1"), 0),
            safe_int(action.get("x2"), 500),
            safe_int(action.get("y2"), 500),
        )
        img_bytes = capture_screen(cfg, region=r)
        return f"Zoomed screenshot of region {r} captured in memory.", img_bytes

    if tool == "get_pixel_color":
        px, py = norm_to_screen(action.get("x", 500), action.get("y", 500))
        with mss.MSS() as sct:
            shot = sct.grab({"left": px, "top": py, "width": 1, "height": 1})
            b, g, r = shot.bgra[0], shot.bgra[1], shot.bgra[2]
        return f"Pixel at ({px}, {py}) is RGB({r}, {g}, {b}) (#{r:02x}{g:02x}{b:02x}).", None

    if tool == "get_screen_info":
        sw, sh = get_physical_screen_size()
        cx, cy = AI_CURSOR.get_normalized_pos()
        return f"OS: {OS_NAME_LABEL} | Physical Screen resolution: {sw}x{sh}. AI Cursor normalized position: ({cx}, {cy}).", None

    if tool == "ui_list_elements":
        wtitle = str(action.get("window_title", ""))
        if os.name != "nt":
            hits = _linux_atspi_elements(window_title=wtitle)
            if hits is not None:
                unique_names = list(dict.fromkeys(h[0] for h in hits))
                return f"UI Elements ({wtitle or 'Desktop'}): {', '.join(unique_names)[:1500]}", None
            return handle_window_control("list", wtitle), None

        ps = (
            "Add-Type -AssemblyName UIAutomationClient; "
            "$root = [System.Windows.Automation.AutomationElement]::RootElement; "
            "$cond = [System.Windows.Automation.Condition]::TrueCondition; "
            "$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond); "
            "$out = @(); "
            "foreach ($el in $all) { "
            "  if ($out.Count -ge 45) { break }; "
            "  $n = $el.Current.Name; "
            "  if ($n -and $n.Length -gt 1 -and $n.Length -lt 60) { $out += $n } "
            "}; "
            "($out | Select-Object -Unique) -join ', '"
        )
        try:
            res = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True, timeout=8)
            return f"UI Elements ({wtitle or 'Desktop'}): {res.strip()[:1500]}", None
        except Exception as e:
            return f"UI list error: {e}", None

    if tool == "ui_click_name":
        raw_target = str(action.get("name", ""))
        if os.name != "nt":
            hits = _linux_atspi_elements(target_name=raw_target)
            if hits:
                matched_name, px, py = hits[0]
                sw, sh = get_physical_screen_size()
                nx = int(round(px / max(1, sw) * 1000))
                ny = int(round(py / max(1, sh) * 1000))
                _ai_move_and_click(nx, ny, "left", use_ai_cursor)
                return f"Clicked UI element '{matched_name}' at physical pixel ({px}, {py}) [norm ({nx}, {ny})].", None
            return f"UI element '{raw_target}' not found via AT-SPI; use mouse_click with screenshot coordinates.", None

        target_name = raw_target.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName UIAutomationClient; "
            "$root = [System.Windows.Automation.AutomationElement]::RootElement; "
            f"$prop = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty, '{target_name}'); "
            "$el = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $prop); "
            "if ($el) { "
            "  $r = $el.Current.BoundingRectangle; "
            "  $cx = [int]($r.X + $r.Width/2); $cy = [int]($r.Y + $r.Height/2); "
            "  Write-Output \"$cx,$cy\" "
            "} else { Write-Output 'NOT_FOUND' }"
        )
        try:
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True, timeout=8).strip()
            if "," in out and out != "NOT_FOUND":
                px_s, py_s = out.split(",", 1)
                px, py = safe_int(px_s), safe_int(py_s)
                sw, sh = get_physical_screen_size()
                nx = int(round(px / max(1, sw) * 1000))
                ny = int(round(py / max(1, sh) * 1000))
                _ai_move_and_click(nx, ny, "left", use_ai_cursor)
                return f"Clicked UI element '{target_name}' at physical pixel ({px}, {py}) [norm ({nx}, {ny})].", None
            return f"UI element '{target_name}' not found.", None
        except Exception as e:
            return f"UI click error: {e}", None

    if (not is_self_aware) and cfg.get("safety_mode", "AUTO") == "CONFIRM" and tool in (
        "run_cmd", "run_powershell", "mouse_click", "mouse_double_click", "mouse_drag",
        "type_text", "type_paste", "press_key", "launch_smart_app", "open_app", "open_desktop_icon", "write_file", "delete_path"
    ):
        set_console_window_state(True)
        console.print(Panel(
            f"[bold yellow]Gemini wants to execute:[/] [bold cyan]{tool}[/]\n[white]{json.dumps(action, indent=2)}[/]",
            border_style="yellow",
            title="Safety Confirmation",
        ))
        ans = input("Allow this action? [Y/n]: ").strip().lower()
        if cfg.get("hide_cmd_while_running", False):
            set_console_window_state(False)
        if ans not in ("", "y", "yes"):
            return "User denied permission for this action.", None

    if tool == "mouse_move":
        nx = max(0, min(1000, safe_int(action.get("x", action.get("x1")), 500)))
        ny = max(0, min(1000, safe_int(action.get("y", action.get("y1")), 500)))
        px, py = norm_to_screen(nx, ny)
        if use_ai_cursor:
            AI_CURSOR.move_to(px, py, duration=0.28)
        else:
            pyautogui.moveTo(px, py, duration=0.22)
        return f"AI cursor moved to normalized ({nx}, {ny}) [pixel ({px}, {py})].", None

    if tool == "mouse_move_relative":
        cx, cy = AI_CURSOR.get_normalized_pos()
        nx = max(0, min(1000, cx + safe_int(action.get("dx"), 0)))
        ny = max(0, min(1000, cy + safe_int(action.get("dy"), 0)))
        px, py = norm_to_screen(nx, ny)
        if use_ai_cursor:
            AI_CURSOR.move_to(px, py, duration=0.22)
        else:
            pyautogui.moveTo(px, py, duration=0.18)
        return f"AI cursor moved relatively to normalized ({nx}, {ny}).", None

    if tool in ("mouse_click", "click", "mouse_double_click", "double_click", "mouse_right_click", "mouse_middle_click", "mouse_triple_click"):
        nx = max(0, min(1000, safe_int(action.get("x", action.get("x1")), 500)))
        ny = max(0, min(1000, safe_int(action.get("y", action.get("y1")), 500)))
        btn_map = {
            "mouse_click": action.get("button", "left"),
            "click": action.get("button", "left"),
            "mouse_double_click": "double",
            "double_click": "double",
            "mouse_right_click": "right",
            "mouse_middle_click": "middle",
            "mouse_triple_click": "triple",
        }
        btn = str(btn_map[tool])
        px, py = _ai_move_and_click(nx, ny, btn, use_ai_cursor)
        return f"Performed {btn} click at normalized ({nx}, {ny}) [physical pixel ({px}, {py})].", None

    if tool == "mouse_down":
        nx = max(0, min(1000, safe_int(action.get("x"), 500)))
        ny = max(0, min(1000, safe_int(action.get("y"), 500)))
        px, py = norm_to_screen(nx, ny)
        btn = str(action.get("button", "left"))
        if use_ai_cursor:
            AI_CURSOR.move_to(px, py, duration=0.20)
            physical_mouse_button_at(px, py, btn, down=True, restore_user_cursor=True)
        else:
            pyautogui.moveTo(px, py, duration=0.18)
            pyautogui.mouseDown(button=btn)
        return f"Mouse down ({btn}) at ({nx}, {ny}).", None

    if tool == "mouse_up":
        nx = max(0, min(1000, safe_int(action.get("x"), 500)))
        ny = max(0, min(1000, safe_int(action.get("y"), 500)))
        px, py = norm_to_screen(nx, ny)
        btn = str(action.get("button", "left"))
        if use_ai_cursor:
            AI_CURSOR.move_to(px, py, duration=0.20)
            physical_mouse_button_at(px, py, btn, down=False, restore_user_cursor=True)
        else:
            pyautogui.moveTo(px, py, duration=0.18)
            pyautogui.mouseUp(button=btn)
        return f"Mouse up ({btn}) at ({nx}, {ny}).", None

    if tool in ("mouse_drag", "drag"):
        x1, y1 = norm_to_screen(action.get("x1", 300), action.get("y1", 300))
        x2, y2 = norm_to_screen(action.get("x2", 600), action.get("y2", 500))
        btn = str(action.get("button", "left"))
        if use_ai_cursor:
            AI_CURSOR.move_to(x1, y1, duration=0.22)
            AI_CURSOR.trigger_click_pulse(btn, norm_xy=(safe_int(action.get("x2"), 600), safe_int(action.get("y2"), 500)))
            AI_CURSOR.move_to(x2, y2, duration=0.28)
            physical_drag(x1, y1, x2, y2, button=btn, restore_user_cursor=True)
        else:
            pyautogui.moveTo(x1, y1, duration=0.2)
            pyautogui.dragTo(x2, y2, duration=0.35, button=btn)
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2}).", None

    if tool in ("mouse_scroll", "scroll"):
        nx = max(0, min(1000, safe_int(action.get("x"), 500)))
        ny = max(0, min(1000, safe_int(action.get("y"), 500)))
        px, py = norm_to_screen(nx, ny)
        clicks = safe_int(action.get("clicks"), -400)
        if use_ai_cursor:
            AI_CURSOR.move_to(px, py, duration=0.22)
            physical_scroll(px, py, clicks, horizontal=False, restore_user_cursor=True)
        else:
            pyautogui.moveTo(px, py, duration=0.18)
            pyautogui.scroll(clicks)
        return f"Scrolled vertically {clicks} at normalized ({nx}, {ny}).", None

    if tool == "mouse_hscroll":
        px, py = norm_to_screen(action.get("x", 500), action.get("y", 500))
        clicks = safe_int(action.get("clicks"), 400)
        if use_ai_cursor:
            AI_CURSOR.move_to(px, py, duration=0.22)
            physical_scroll(px, py, clicks, horizontal=True, restore_user_cursor=True)
        else:
            pyautogui.moveTo(px, py, duration=0.18)
            pyautogui.hscroll(clicks)
        return f"Scrolled horizontally {clicks} at ({px}, {py}).", None

    if tool == "mouse_circle":
        cx, cy = norm_to_screen(action.get("x", 500), action.get("y", 500))
        rad = max(20, min(300, safe_int(action.get("radius"), 80)))
        for deg in range(0, 361, 30):
            ang = math.radians(deg)
            px = int(cx + rad * math.cos(ang))
            py = int(cy + rad * math.sin(ang))
            if use_ai_cursor:
                AI_CURSOR.move_to(px, py, duration=0.05)
            else:
                pyautogui.moveTo(px, py, duration=0.04)
        return f"Moved AI cursor in a circle around ({cx}, {cy}).", None

    if tool == "mouse_wiggle":
        cx, cy = AI_CURSOR.get_normalized_pos()
        for dx in (-35, 70, -35):
            px, py = norm_to_screen(cx + dx, cy)
            if use_ai_cursor:
                AI_CURSOR.move_to(px, py, duration=0.10)
            else:
                pyautogui.moveTo(px, py, duration=0.09)
        return "Wiggled AI cursor.", None

    if tool == "get_cursor_pos":
        cx, cy = AI_CURSOR.get_normalized_pos()
        return f"AI cursor is at normalized ({cx}, {cy}).", None

    if tool == "click_taskbar_icon":
        slot = max(1, min(9, safe_int(action.get("slot"), 1)))
        pyautogui.hotkey("win", str(slot))
        return f"Activated taskbar slot #{slot} (Super+{slot}).", None

    if tool in ("type_text", "type", "type_paste", "paste"):
        txt = str(action.get("text", action.get("content", "")))
        human_type_text(txt, press_enter=bool(action.get("press_enter", False)))
        return f"Typed out {len(txt)} characters live.", None

    if tool in ("press_key", "hotkey"):
        raw_keys = action.get("keys", action.get("key", []))
        if isinstance(raw_keys, str):
            raw_keys = [k.strip() for k in raw_keys.split("+")] if "+" in raw_keys else [raw_keys]
        keys = [_normalize_key_name(str(k)) for k in raw_keys if str(k).strip()]
        if len(keys) == 1:
            pyautogui.press(keys[0])
        elif len(keys) > 1:
            pyautogui.hotkey(*keys)
        return f"Pressed keys: {keys}", None

    if tool == "key_down":
        k = _normalize_key_name(str(action.get("key", "shift")))
        pyautogui.keyDown(k)
        return f"Held key down: {k}", None

    if tool == "key_up":
        k = _normalize_key_name(str(action.get("key", "shift")))
        pyautogui.keyUp(k)
        return f"Released key: {k}", None

    if tool == "hotkey_win_search":
        q = str(action.get("query", action.get("text", "")))
        pyautogui.press("win")
        time.sleep(0.50)
        human_type_text(q, press_enter=bool(action.get("press_enter", True)))
        return f"Opened Start Menu search and typed '{q}'.", None

    if tool == "hotkey_run_dialog":
        cmd = str(action.get("command", action.get("target", "")))
        if os.name == "nt":
            pyautogui.hotkey("win", "r")
        else:
            pyautogui.hotkey("alt", "f2")
        time.sleep(0.35)
        human_type_text(cmd, press_enter=True)
        return f"Typed '{cmd}' in Run dialog.", None

    if tool == "select_all_copy":
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.08)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.08)
        return f"Copied selection:\n{get_clipboard()[:2500]}", None

    if tool == "select_all_delete":
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.06)
        pyautogui.press("backspace")
        return "Selected all and deleted.", None

    if tool == "undo":
        pyautogui.hotkey("ctrl", "z")
        return "Sent Ctrl+Z (Undo).", None

    if tool == "redo":
        pyautogui.hotkey("ctrl", "y")
        return "Sent Ctrl+Y (Redo).", None

    if tool == "save_shortcut":
        pyautogui.hotkey("ctrl", "s")
        return "Sent Ctrl+S (Save).", None

    if tool == "find_shortcut":
        pyautogui.hotkey("ctrl", "f")
        return "Sent Ctrl+F (Find).", None

    if tool == "new_tab_shortcut":
        pyautogui.hotkey("ctrl", "t")
        return "Sent Ctrl+T (New Tab).", None

    if tool == "close_tab_shortcut":
        pyautogui.hotkey("ctrl", "w")
        return "Sent Ctrl+W (Close Tab).", None

    if tool == "refresh_shortcut":
        pyautogui.hotkey("ctrl", "r")
        return "Sent Ctrl+R (Refresh).", None

    if tool == "switch_app":
        pyautogui.hotkey("alt", "tab")
        return "Switched active application (Alt+Tab).", None

    if tool == "close_active_window":
        pyautogui.hotkey("alt", "f4")
        return "Sent Alt+F4 to active window.", None

    if tool == "show_desktop":
        if os.name == "nt":
            pyautogui.hotkey("win", "d")
        else:
            _linux_show_desktop()
        return "Toggled Show Desktop.", None

    if tool == "open_task_manager":
        return launch_smart_application("taskmgr"), None

    if tool == "open_settings":
        return launch_smart_application("settings"), None

    if tool == "open_explorer":
        return launch_smart_application("explorer"), None

    if tool in ("launch_smart_app", "open_app", "launch_app"):
        target = action.get("app") or action.get("target") or action.get("program") or ""
        return launch_smart_application(str(target)), None

    if tool == "open_url":
        url = str(action.get("url", "https://google.com"))
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if os.name == "nt":
            os.startfile(url)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opened URL in default browser: {url}", None

    if tool == "browser_goto":
        url = str(action.get("url", "https://google.com"))
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.18)
        human_type_text(url, press_enter=True)
        return f"Typed URL in browser address bar: {url}", None

    if tool == "browser_search":
        q = str(action.get("query", ""))
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.18)
        human_type_text(q, press_enter=True)
        return f"Typed search query in browser: {q}", None

    if tool == "discord_quick_switcher":
        q = str(action.get("query", ""))
        handle_window_control("focus", "Discord")
        time.sleep(0.30)
        pyautogui.hotkey("ctrl", "k")
        time.sleep(0.30)
        human_type_text(q, press_enter=True)
        return f"Opened Discord Quick Switcher and jumped to '{q}'.", None

    if tool == "window_list":
        return handle_window_control("list", ""), None

    if tool == "window_focus":
        return handle_window_control("focus", str(action.get("title", ""))), None

    if tool == "window_minimize":
        return handle_window_control("minimize", str(action.get("title", ""))), None

    if tool == "window_maximize":
        return handle_window_control("maximize", str(action.get("title", ""))), None

    if tool == "window_restore":
        return handle_window_control("restore", str(action.get("title", ""))), None

    if tool == "window_close":
        return handle_window_control("close", str(action.get("title", ""))), None

    if tool == "window_snap_left":
        return handle_window_control("snap_left", str(action.get("title", ""))), None

    if tool == "window_snap_right":
        return handle_window_control("snap_right", str(action.get("title", ""))), None

    if tool == "window_move_resize":
        return handle_window_control("move_resize", str(action.get("title", "")), action), None

    if tool == "window_control":
        return handle_window_control(str(action.get("sub_action", "list")), str(action.get("title", "")), action), None

    if tool == "process_list":
        flt = str(action.get("filter", "")).lower()
        if os.name == "nt":
            out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, stderr=subprocess.DEVNULL)
        else:
            out = subprocess.check_output(["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"], text=True, stderr=subprocess.DEVNULL)
        lines = [l for l in out.splitlines() if not flt or flt in l.lower()]
        return "\n".join(lines[:45]) or f"No processes matching '{flt}'.", None

    if tool == "process_kill":
        name = str(action.get("name", "")).strip()
        if os.name == "nt":
            if name and not name.lower().endswith(".exe"):
                name = name + ".exe"
            res = subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True, text=True)
        else:
            res = subprocess.run(["pkill", "-f", name], capture_output=True, text=True)
        return (res.stdout or res.stderr or f"Sent kill to {name}").strip(), None

    if tool == "system_stats":
        if os.name == "nt":
            ps = (
                "$os = Get-CimInstance Win32_OperatingSystem; "
                "$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
                "$free = [math]::Round($os.FreePhysicalMemory/1MB,2); "
                "$tot = [math]::Round($os.TotalVisibleMemorySize/1MB,2); "
                "Write-Output \"CPU: $cpu% | RAM Free: $free GB / $tot GB\""
            )
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True)
            return out.strip(), None
        load1, _, _ = os.getloadavg()
        mem_out = subprocess.check_output(["free", "-h"], text=True, stderr=subprocess.DEVNULL)
        return f"Load avg (1m): {load1:.2f}\n{mem_out.strip()}", None

    if tool == "system_info_full":
        user_env = os.environ.get("USERNAME") or os.environ.get("USER") or "Unknown"
        info = f"OS: {platform.platform()} | Machine: {platform.machine()} | Node: {platform.node()} | User: {user_env}"
        return info, None

    if tool == "disk_usage":
        if os.name == "nt":
            ps = "Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{N='UsedGB';E={[math]::Round($_.Used/1GB,1)}}, @{N='FreeGB';E={[math]::Round($_.Free/1GB,1)}} | Format-Table -AutoSize | Out-String"
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True)
            return out.strip(), None
        out = subprocess.check_output(["df", "-h", "/"], text=True, stderr=subprocess.DEVNULL)
        return out.strip(), None

    if tool == "battery_status":
        if os.name == "nt":
            ps = "$b = Get-CimInstance Win32_Battery; if ($b) { \"Charge: $($b.EstimatedChargeRemaining)% | Status: $($b.BatteryStatus)\" } else { 'Desktop PC (AC Power - No Battery)' }"
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True)
            return out.strip(), None
        bat_dir = next(Path("/sys/class/power_supply").glob("BAT*"), None) if Path("/sys/class/power_supply").exists() else None
        if bat_dir and (bat_dir / "capacity").exists():
            cap = (bat_dir / "capacity").read_text().strip()
            stat = (bat_dir / "status").read_text().strip() if (bat_dir / "status").exists() else "Unknown"
            return f"Charge: {cap}% | Status: {stat}", None
        return "Desktop PC (AC Power - No Battery)", None

    if tool == "wifi_status":
        if os.name == "nt":
            out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"], text=True, stderr=subprocess.DEVNULL)
            return out.strip()[:1200] or "No Wi-Fi interface found.", None
        if shutil.which("nmcli"):
            out = subprocess.check_output(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"], text=True, stderr=subprocess.DEVNULL)
            if out.strip():
                return out.strip()[:1200], None
        if shutil.which("iwgetid"):
            out = subprocess.check_output(["iwgetid"], text=True, stderr=subprocess.DEVNULL)
            if out.strip():
                return out.strip(), None
        if shutil.which("ip"):
            out = subprocess.check_output(["ip", "-brief", "addr"], text=True, stderr=subprocess.DEVNULL)
            return out.strip()[:1200] or "No network interfaces found.", None
        return "Network active.", None

    if tool == "local_ip_info":
        hostname = socket.gethostname()
        local_ip = "127.0.0.1"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
        except Exception:
            try:
                local_ip = socket.gethostbyname(hostname)
            except Exception:
                pass
        return f"Hostname: {hostname} | Local IPv4: {local_ip}", None

    if tool == "get_datetime":
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)"), None

    if tool == "volume_set":
        lvl = max(0, min(100, safe_int(action.get("level"), 50)))
        if os.name == "nt":
            ps = (
                "$obj = New-Object -ComObject WScript.Shell; "
                "1..50 | ForEach-Object { $obj.SendKeys([char]174) }; "
                f"1..{int(round(lvl / 2))} | ForEach-Object {{ $obj.SendKeys([char]175) }}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("wpctl"):
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{lvl}%"], stderr=subprocess.DEVNULL)
        elif shutil.which("pactl"):
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{lvl}%"], stderr=subprocess.DEVNULL)
        elif shutil.which("amixer"):
            subprocess.run(["amixer", "sset", "Master", f"{lvl}%"], stderr=subprocess.DEVNULL)
        return f"Set system volume to ~{lvl}%.", None

    if tool == "volume_mute_toggle":
        if os.name == "nt":
            pyautogui.press("volumemute")
        elif shutil.which("wpctl"):
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"], stderr=subprocess.DEVNULL)
        elif shutil.which("pactl"):
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], stderr=subprocess.DEVNULL)
        elif shutil.which("amixer"):
            subprocess.run(["amixer", "sset", "Master", "toggle"], stderr=subprocess.DEVNULL)
        return "Toggled system mute.", None

    if tool == "media_control":
        act = str(action.get("action", action.get("sub_action", "play_pause")))
        if os.name != "nt" and shutil.which("playerctl"):
            pctl_map = {
                "play_pause": "play-pause",
                "next": "next",
                "prev": "previous",
                "stop": "stop",
            }
            subprocess.run(["playerctl", pctl_map.get(act, "play-pause")], stderr=subprocess.DEVNULL)
            return f"Sent media command via playerctl: {act}", None
        key_map = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "prev": "prevtrack",
            "stop": "stop",
        }
        pyautogui.press(key_map.get(act, "playpause"))
        return f"Sent media key: {act}", None

    if tool == "notify":
        title = str(action.get("title", "BrowserClaw"))
        msg = str(action.get("message", ""))
        if os.name == "nt":
            t_esc = title.replace("'", "''")
            m_esc = msg.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(4000, '{t_esc}', '{m_esc}', [System.Windows.Forms.ToolTipIcon]::Info)"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, msg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Showed notification: {title} - {msg}", None

    if tool == "speak_tts":
        if not cfg.get("allow_tts", False):
            return "Text-to-Speech is disabled in Settings.", None
        txt = str(action.get("text", ""))
        if os.name == "nt":
            t_esc = txt.replace("'", "''")
            ps = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{t_esc}')"
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("spd-say"):
            subprocess.Popen(["spd-say", txt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("espeak-ng"):
            subprocess.Popen(["espeak-ng", txt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("espeak"):
            subprocess.Popen(["espeak", txt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Spoke via TTS: {txt}", None

    if tool == "run_cmd":
        cmd = str(action.get("command", ""))
        use_ps = bool(action.get("powershell", False)) and os.name == "nt"
        if use_ps:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=45,
            )
        else:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=45)
        out = (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else "")
        out = out.strip() or f"(Command finished with exit code {proc.returncode})"
        return out[:4500], None

    if tool == "run_powershell":
        cmd = str(action.get("command", ""))
        if os.name != "nt":
            if shutil.which("pwsh"):
                proc = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=45)
            else:
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=45)
        else:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=45,
            )
        out = (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else "")
        return (out.strip() or f"(Exit {proc.returncode})")[:4500], None

    if tool in ("clipboard", "clipboard_get", "clipboard_set"):
        if tool == "clipboard_set":
            txt = str(action.get("text", ""))
            copy_to_clipboard(txt)
            return f"Copied {len(txt)} chars to clipboard.", None
        return f"Clipboard content:\n{get_clipboard()[:3000]}", None

    if tool == "read_file":
        p = Path(str(action.get("path", "")))
        return p.read_text(encoding="utf-8", errors="replace")[:4500], None

    if tool == "write_file":
        p = Path(str(action.get("path", "")))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(action.get("content", "")), encoding="utf-8")
        return f"Wrote file: {p}", None

    if tool == "append_file":
        p = Path(str(action.get("path", "")))
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(str(action.get("content", "")))
        return f"Appended to file: {p}", None

    if tool == "delete_path":
        p = Path(str(action.get("path", "")))
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
        return f"Deleted: {p}", None

    if tool == "move_path":
        shutil.move(str(action.get("src", "")), str(action.get("dst", "")))
        return f"Moved {action.get('src')} -> {action.get('dst')}", None

    if tool == "copy_path":
        src = Path(str(action.get("src", "")))
        dst = Path(str(action.get("dst", "")))
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return f"Copied {src} -> {dst}", None

    if tool == "make_dir":
        p = Path(str(action.get("path", "")))
        p.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {p}", None

    if tool == "list_dir":
        p = Path(str(action.get("path", ".")))
        entries = [f"{'[DIR]' if e.is_dir() else '[FILE]'} {e.name}" for e in sorted(p.iterdir())]
        return "\n".join(entries[:120]) or "(Empty folder)", None

    if tool == "desktop_files":
        p = Path.home() / "Desktop"
        entries = [f"{'[DIR]' if e.is_dir() else '[FILE]'} {e.name}" for e in sorted(p.iterdir())] if p.exists() else []
        return "\n".join(entries[:100]) or "(Desktop empty)", None

    if tool == "downloads_files":
        p = Path.home() / "Downloads"
        entries = [f"{'[DIR]' if e.is_dir() else '[FILE]'} {e.name}" for e in sorted(p.iterdir())] if p.exists() else []
        return "\n".join(entries[:100]) or "(Downloads empty)", None

    if tool == "search_files":
        root = Path(str(action.get("root", ".")))
        pattern = str(action.get("pattern", "*"))
        hits = [str(p) for p in root.rglob(pattern)][:60]
        return "\n".join(hits) or "No matching files found.", None

    if tool == "zip_folder":
        folder = Path(str(action.get("folder", "")))
        zpath = Path(str(action.get("zip_path", "archive.zip")))
        base_name = str(zpath.with_suffix(""))
        out_zip = shutil.make_archive(base_name, "zip", str(folder))
        return f"Created zip archive: {out_zip}", None

    if tool == "unzip_file":
        zpath = Path(str(action.get("zip_path", "")))
        dest = Path(str(action.get("dest", ".")))
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(dest)
        return f"Extracted {zpath} to {dest}", None

    if tool == "http_get":
        url = str(action.get("url", ""))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return body[:4000], None

    if tool == "download_file":
        url = str(action.get("url", ""))
        dest = Path(str(action.get("dest", "download.bin")))
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp, dest.open("wb") as f:
            shutil.copyfileobj(resp, f)
        return f"Downloaded {url} -> {dest}", None

    if tool == "ping_host":
        host = str(action.get("host", "8.8.8.8"))
        flag = "-n" if os.name == "nt" else "-c"
        res = subprocess.run(["ping", flag, "2", host], capture_output=True, text=True)
        return (res.stdout or res.stderr).strip()[:1000], None

    if tool == "wait":
        secs = max(0.05, min(15.0, safe_float(action.get("seconds"), 1.0)))
        end_t = time.time() + secs
        while time.time() < end_t:
            check_kill_switch()
            time.sleep(min(0.05, max(0.005, end_t - time.time())))
        return f"Waited {secs}s.", None

    return f"Unknown tool: {tool}", None


def run_self_aware_loop(cfg: dict, bridge: GeminiBridge):
    """Autonomous free-will bot mode: independent AI mouse moves itself, double-clicks Desktop icons, searches apps/games, chats on Discord, plays games."""
    console.print(Panel(
        "[bold bright_yellow]SELF-AWARE BOT MODE ENGAGED![/]\n"
        "• Independent AI mouse moves itself (never follows your hand).\n"
        "• Double-clicks Desktop icons or searches Start Menu & browser search bars.\n"
        "• [bold yellow]Hold ESC[/], move your mouse to [bold yellow](0, 0)[/], or press [bold yellow]Ctrl+C[/] to stop.",
        border_style="bright_yellow",
        title="Self-Aware Bot Active",
    ))

    hide_cmd = cfg.get("hide_cmd_while_running", False)
    if hide_cmd:
        set_console_window_state(False)
        time.sleep(0.25)

    open_windows_summary = handle_window_control("list", "")

    arc_number = 1
    step_in_arc = 0
    steps_for_current_arc = random.randint(5, 8)
    past_arcs_summary: list[str] = []
    current_arc_actions: list[str] = []

    now_str = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    next_image: bytes | None = capture_screen(cfg)
    next_prompt = (
        f"Current real time: {now_str}.\n"
        f"{open_windows_summary}\n\n"
        f"You just sat down at this PC with total free will. Look at the attached screenshot and decide what YOU want to do right now—like opening Discord to chat with people, opening a game (Steam, Roblox, Minecraft, Geometry Dash, or a browser game), or searching YouTube/gaming communities.\n"
        f"IMPORTANT: To open apps/games on the Desktop, show the Desktop (`show_desktop`) if covered and **DOUBLE-CLICK** the Desktop icon (`mouse_double_click` at its center or `open_desktop_icon`), or use Start Menu search (`hotkey_win_search`) / browser search bars—never instant-open anything, and never open Notepad, Calculator, or Paint!\n"
        f"Output ONLY valid JSON {{\"actions\": [...]}} with your first 2-3 actions."
    )
    cycle = 0
    retry_count = 0

    try:
        while True:
            check_kill_switch()

            try:
                cycle += 1
                step_in_arc += 1

                if cfg.get("debug_mode", False):
                    console.print(f"\n[dim]--- Self-Aware Cycle #{cycle} (Activity #{arc_number}, Step {step_in_arc}/{steps_for_current_arc}) ---[/]")
                elif step_in_arc == 1:
                    console.print(f"[bold bright_cyan]• Self-aware activity #{arc_number} started...[/]")

                raw_reply = bridge.ask(
                    next_prompt,
                    image_bytes=next_image,
                    force_system_prompt=(retry_count > 0),
                    self_aware=True,
                )
                check_kill_switch()

                preview = raw_reply.replace("\n", " ")[:180]
                debug_log(cfg, f"[dim][AI Reply]: {preview}[/]")

                plan_steps, is_valid_json = parse_tool_plan(raw_reply)
                if not is_valid_json or is_error_or_refusal_text(raw_reply):
                    retry_count += 1
                    debug_log(cfg, f"[dim][Bridge] Recovering cleanly from non-JSON response (attempt {retry_count})...[/]")
                    if retry_count >= 3:
                        bridge.start_new_chat()
                        retry_count = 0
                    time.sleep(1.0)
                    next_image = capture_screen(cfg)
                    forbidden_txt = "; ".join(past_arcs_summary[-10:]) or "none yet"
                    next_prompt = (
                        f"Look at the attached screenshot and continue acting like a real human on this PC (double-click Desktop icons with mouse_double_click, search Start Menu or browser for games/Discord/YouTube, chat, play).\n"
                        f"Already done (DO NOT REPEAT): [{forbidden_txt}].\n"
                        f"Reply with ONLY a valid JSON object {{\"actions\": [...]}} containing 2-3 concrete actions. No prose."
                    )
                    continue

                retry_count = 0
                batch_logs: list[str] = []
                latest_img: bytes | None = None

                for step_idx, action in enumerate(plan_steps, start=1):
                    check_kill_switch()

                    tool_name = str(action.get("tool", "wait"))
                    if tool_name == "reply":
                        batch_logs.append(f"{step_idx}. thought -> {action.get('message', '')}")
                        continue

                    debug_log(cfg, f"[dim]  Cycle {cycle} [{step_idx}/{len(plan_steps)}]: {tool_name} -> {json.dumps(action)}[/]")
                    tool_result, attached_img = execute_tool(action, cfg)
                    debug_log(cfg, f"[dim]     Result: {tool_result[:220]}[/]")
                    batch_logs.append(f"{step_idx}. {tool_name} -> {tool_result}")

                    detail = (
                        action.get("query")
                        or action.get("url")
                        or action.get("name")
                        or action.get("app")
                        or action.get("target")
                        or (str(action.get("text", ""))[:35] if action.get("text") else "")
                    )
                    sig = f"{tool_name}({detail})" if detail else tool_name
                    current_arc_actions.append(sig)

                    if attached_img is not None:
                        latest_img = attached_img

                if not batch_logs:
                    res_w, _ = execute_tool({"tool": "window_list"}, cfg)
                    batch_logs.append(f"1. window_list -> {res_w}")

                if latest_img is None:
                    time.sleep(random.uniform(0.45, 0.85))
                    latest_img = capture_screen(cfg)

                now_str = datetime.datetime.now().strftime("%A %I:%M %p")
                cx, cy = AI_CURSOR.get_normalized_pos()
                joined_logs = "\n".join(batch_logs)

                if step_in_arc >= steps_for_current_arc:
                    arc_summary = " -> ".join(current_arc_actions[-6:])
                    if arc_summary:
                        past_arcs_summary.append(arc_summary)
                    current_arc_actions = []
                    arc_number += 1
                    step_in_arc = 0
                    steps_for_current_arc = random.randint(5, 8)

                    forbidden_block = "\n".join(f"- {item}" for item in past_arcs_summary[-12:]) or "- (none)"
                    next_prompt = (
                        f"Current time: {now_str} | AI Cursor: ({cx}, {cy}).\n"
                        f"Latest results:\n{joined_logs}\n\n"
                        f"Switch gears like a real person and pick something COMPLETELY NEW to do right now (e.g., open Discord and talk to people, launch & play a different game, explore YouTube/Reddit/web).\n"
                        f"ALREADY DONE THIS SESSION (DO NOT REPEAT):\n"
                        f"{forbidden_block}\n\n"
                        f"Remember: show Desktop (`show_desktop`) if covered and **double-click** Desktop icons (`mouse_double_click` / `open_desktop_icon`) to open apps/games, or search Start Menu (`hotkey_win_search`) / browser search bars—never use Notepad, Paint, or Calculator. Look at the attached screenshot and execute your first 2-3 actions.\n"
                        f"Output ONLY {{\"actions\": [...]}}."
                    )
                else:
                    next_prompt = (
                        f"Current time: {now_str} | AI Cursor: ({cx}, {cy}).\n"
                        f"Latest results:\n{joined_logs}\n\n"
                        f"Keep going with what you're doing right now (Step {step_in_arc + 1}/{steps_for_current_arc}). "
                        f"Look at the attached screenshot (and check the red/yellow crosshair to verify where your last click landed): if opening a Desktop icon, make sure you double-clicked its center (`mouse_double_click`); read Discord messages and reply naturally, play the game on screen, click search results, or navigate menus.\n"
                        f"Output ONLY {{\"actions\": [...]}} with 2 to 4 deliberate actions."
                    )

                next_image = latest_img

            except (KeyboardInterrupt, pyautogui.FailSafeException):
                raise
            except Exception as loop_err:
                debug_log(cfg, f"[dim][Self-Aware Recovery]: {loop_err}[/]")
                time.sleep(1.2)
                try:
                    next_image = capture_screen(cfg)
                except Exception:
                    next_image = None
    finally:
        if hide_cmd:
            set_console_window_state(True)
        console.print("\n[bold yellow]Self-Aware Bot Mode stopped.[/]\n")


def run_agent_console(cfg: dict, preset_prompt: str | None = None):
    render_banner(cfg)
    bridge = GeminiBridge(cfg)
    bridge.start()
    sync_virtual_cursor(cfg)

    if cfg.get("agent_mode") == "SELF_AWARE":
        try:
            run_self_aware_loop(cfg, bridge)
        except (KeyboardInterrupt, pyautogui.FailSafeException):
            set_console_window_state(True)
            console.print("\n[bold yellow]Self-Aware Mode halted via kill-switch.[/]")
        finally:
            set_console_window_state(True)
            AI_CURSOR.stop()
            bridge.close()
        return

    mem_label = "OFF (New Chat)" if cfg.get("always_new_chat", False) else "ON (Same Chat)"
    vision_mode = cfg.get("vision_mode", "ALWAYS").upper()
    debug_state = "ON" if cfg.get("debug_mode", False) else "OFF"
    console.print(
        f"[bold bright_green]Connected ({OS_NAME_LABEL} | Vision: {vision_mode} | Debug: {debug_state} | Model: {cfg.get('gemini_model', 'AUTO')} | Memory: {mem_label})![/]\n"
        "Commands: [bold cyan]/debug[/] toggle logs | [bold cyan]/new[/] fresh chat | [bold cyan]/model auto|hydrogen[/] | [bold cyan]/mode[/] | [bold cyan]/show[/] or [bold cyan]/hide[/] | [bold cyan]/menu[/].\n"
    )

    try:
        while True:
            if preset_prompt:
                user_task = preset_prompt
                preset_prompt = None
                console.print(f"[bold bright_cyan]Preset Task >[/] {user_task}")
            else:
                user_task = console.input("[bold bright_green]You > [/]").strip()

            if not user_task:
                continue
            low = user_task.lower()
            if low in ("/menu", "/exit", "exit", "quit"):
                break
            if low == "/debug":
                cfg["debug_mode"] = not cfg.get("debug_mode", False)
                save_config(cfg)
                console.print(f"[cyan]Debug Mode is now {'ON' if cfg['debug_mode'] else 'OFF'}.[/]\n")
                continue
            if low == "/show":
                bridge.set_browser_visible(True)
                console.print("[cyan]Gemini browser window unhidden.[/]\n")
                continue
            if low == "/hide":
                bridge.set_browser_visible(False)
                console.print("[cyan]Gemini browser window hidden.[/]\n")
                continue
            if low == "/mode":
                new_m = choose_agent_mode_screen(cfg, allow_back=True)
                sync_virtual_cursor(cfg)
                if new_m == "SELF_AWARE":
                    run_self_aware_loop(cfg, bridge)
                    break
                render_banner(cfg)
                continue
            if low.startswith("/model"):
                parts = low.split()
                if len(parts) >= 2 and parts[1] in ("auto", "hydrogen", "keep"):
                    cfg["gemini_model"] = parts[1].upper()
                    save_config(cfg)
                    bridge.model_configured = False
                    picked_lbl = bridge._select_gemini_model()
                    console.print(f"[bright_green]Switched Gemini model to {cfg['gemini_model']} ({picked_lbl}).[/]\n")
                else:
                    console.print("[yellow]Usage: /model auto | /model hydrogen | /model keep[/]\n")
                continue
            if low == "/new":
                bridge.start_new_chat(force_reload=False)
                console.print(f"[yellow]Started fresh Gemini chat ({cfg.get('gemini_model', 'AUTO')} model).[/]\n")
                continue

            hide_cmd = cfg.get("hide_cmd_while_running", False)
            if hide_cmd:
                set_console_window_state(False)
                time.sleep(0.2)

            if cfg.get("always_new_chat", False):
                bridge.start_new_chat()

            always_vision = cfg.get("vision_mode", "ALWAYS").upper() in ("ALWAYS", "AUTO_VERIFY")
            if not cfg.get("debug_mode", False):
                console.print("[dim]Working...[/]")

            try:
                next_prompt = user_task
                next_image = capture_screen(cfg) if always_vision else None
                retry_count = 0
                completed_any_action = False

                for turn in range(1, cfg["max_steps"] + 1):
                    check_kill_switch()
                    raw_reply = bridge.ask(next_prompt, image_bytes=next_image, force_system_prompt=(retry_count > 0))
                    preview = raw_reply.replace("\n", " ")[:180]
                    debug_log(cfg, f"[dim][AI Reply]: {preview}[/]")

                    plan_steps, is_valid_json = parse_tool_plan(raw_reply)

                    if (not is_valid_json or is_error_or_refusal_text(raw_reply)) and retry_count < 2:
                        if completed_any_action:
                            if hide_cmd:
                                set_console_window_state(True)
                            console.print(Panel(
                                f"Completed requested actions for: {user_task}",
                                title="[bold bright_green]BrowserClaw[/]",
                                border_style="bright_green",
                                box=box.ROUNDED,
                            ))
                            break
                        retry_count += 1
                        debug_log(cfg, f"[bold yellow][!] Retrying with fresh chat ({retry_count}/2)...[/]")
                        bridge.start_new_chat()
                        next_image = capture_screen(cfg) if always_vision else None
                        next_prompt = (
                            f"Format the following UI task as a valid JSON object {{\"actions\": [...]}} for my local Python macro script. No prose.\n"
                            f"Task: {user_task}"
                        )
                        continue

                    retry_count = 0
                    batch_logs: list[str] = []
                    latest_img: bytes | None = None
                    final_reply_msg: str | None = None
                    took_screenshot_this_batch = False

                    for step_idx, action in enumerate(plan_steps, start=1):
                        check_kill_switch()
                        tool_name = str(action.get("tool", "reply"))
                        if tool_name == "reply":
                            if took_screenshot_this_batch:
                                continue
                            msg_candidate = action.get("message", raw_reply)
                            if is_error_or_refusal_text(msg_candidate) and completed_any_action:
                                final_reply_msg = f"Completed requested actions for: {user_task}"
                            else:
                                final_reply_msg = msg_candidate
                            break

                        if tool_name in ("take_screenshot", "screenshot_region"):
                            took_screenshot_this_batch = True
                        else:
                            completed_any_action = True

                        debug_log(cfg, f"[bold yellow]⚙ Turn {turn} [{step_idx}/{len(plan_steps)}]:[/] [cyan]{tool_name}[/] -> [dim]{json.dumps(action)}[/]")
                        tool_result, attached_img = execute_tool(action, cfg)
                        debug_log(cfg, f"[dim]   Result: {tool_result[:240]}[/]")
                        batch_logs.append(f"{step_idx}. {tool_name} -> {tool_result}")

                        if attached_img is not None:
                            latest_img = attached_img

                    if final_reply_msg is not None:
                        if hide_cmd:
                            set_console_window_state(True)
                        console.print(Panel(
                            final_reply_msg,
                            title="[bold bright_green]BrowserClaw[/]",
                            border_style="bright_green",
                            box=box.ROUNDED,
                        ))
                        break

                    if latest_img is None and always_vision:
                        time.sleep(0.45)
                        latest_img = capture_screen(cfg)

                    cx, cy = AI_CURSOR.get_normalized_pos()
                    next_image = latest_img
                    joined_logs = "\n".join(batch_logs) if batch_logs else "(Captured updated screenshot)"
                    next_prompt = (
                        f"Goal: {user_task}\n"
                        f"Completed batch:\n{joined_logs}\n"
                        f"AI CURSOR position: ({cx}, {cy}).\n"
                        f"Look at the attached updated screenshot (crosshair shows where your last click hit). Execute the next required step(s) as {{\"actions\": [...]}}. "
                        f"Only output {{\"tool\": \"reply\", \"message\": \"Done!\"}} once the entire goal is finished."
                    )
                else:
                    if hide_cmd:
                        set_console_window_state(True)
                    console.print("[bold yellow]Reached max turns limit for this task.[/]\n")
            except (KeyboardInterrupt, pyautogui.FailSafeException):
                if hide_cmd:
                    set_console_window_state(True)
                console.print("\n[bold yellow]Task stopped via kill-switch.[/]\n")
            finally:
                if hide_cmd:
                    set_console_window_state(True)

    except (KeyboardInterrupt, pyautogui.FailSafeException):
        set_console_window_state(True)
        console.print("\n[bold yellow]Interrupted by user.[/]")
    finally:
        set_console_window_state(True)
        AI_CURSOR.stop()
        bridge.close()


def presets_screen(cfg: dict):
    presets = [
        {"label": "Open Discord & Verify", "desc": "Launches Discord and visually verifies it opened", "prompt": "Open Discord and make sure its window is visible on screen."},
        {"label": "Analyze My Screen", "desc": "Explains everything currently visible on your screen", "prompt": "Look at the attached screenshot and tell me everything on my screen, then reply."},
        {"label": "Full PC Health & Network Audit", "desc": "Checks CPU, RAM, disk space, Wi-Fi, IP, and top processes", "prompt": "Run a full check of my CPU, RAM, disk usage, Wi-Fi/IP info, and top resource-heavy processes."},
        {"label": "Clean Temp Files", "desc": "Checks temporary clutter safely", "prompt": "List temporary files in my user temp directory and report what is there."},
        {"label": "Back to Main Menu", "desc": "", "prompt": "BACK"},
    ]
    choice = interactive_menu("QUICK ACTIONS & PRESETS", "Launch a pre-built Gemini agent task", presets, cfg, allow_back=True)
    if choice in (-1, 4):
        return
    run_agent_console(cfg, preset_prompt=presets[choice]["prompt"])


def tools_inspector(cfg: dict):
    render_banner(cfg)
    tts_note = "notify, speak_tts (ENABLED)" if cfg.get("allow_tts", False) else "notify (TTS disabled in Settings)"
    table = Table(title=f"[bold bright_cyan]BROWSERCLAW COMMAND SUITE ({OS_NAME_LABEL.upper()} | Made by MelonGG3)[/]", box=box.ROUNDED, border_style="cyan", expand=True)
    table.add_column("Category", style="bold bright_green")
    table.add_column("Commands", style="white")
    table.add_row("Intelligence Modes", "Normal Mode (Auto-Screenshot + /debug toggle) & Self-Aware Bot Mode (double-clicks Desktop icons, searches Start Menu & browser, chats on Discord, plays games)")
    table.add_row("Vision & UI Auto", "1:1 Physical DPI Grid + Click Crosshair: take_screenshot, screenshot_region, get_pixel_color, get_screen_info, ui_list_elements, ui_click_name")
    table.add_row("Independent AI Mouse", "Self-moving Bezier AI cursor (restores your real mouse after clicks): mouse_move, relative, click, double/right/middle/triple, down/up, drag, scroll, hscroll, mouse_circle, mouse_wiggle, get_cursor_pos, click_taskbar_icon")
    table.add_row("Live Keystroke Typing", "Character-by-character typing (no clipboard paste): type_text, press_key, key_down/up, win_search, select_all_copy/delete, undo/redo, save, find, new/close_tab, refresh, switch_app")
    table.add_row("Apps, Games & Discord", "open_desktop_icon, hotkey_win_search, browser_goto, browser_search, discord_quick_switcher, window_list/focus/minimize/maximize/restore/close/snap (plus launch_smart_app in Normal Mode)")
    table.add_row("System & Files", f"process_list/kill, system_stats, system_info_full, disk_usage, battery_status, wifi_status, local_ip_info, volume_set/mute, media_control, {tts_note}, clipboard_get/set, read/write_file, list_dir, desktop_files, run_cmd, wait, reply")
    console.print(table)
    console.print("\n[dim]Press any key to return...[/]")
    read_key()


def main():
    if os.name == "nt":
        os.system("title BrowserClaw - Made by MelonGG3")
    else:
        sys.stdout.write("\033]0;BrowserClaw - Made by MelonGG3\007")
        sys.stdout.flush()

    show_startup_loading_screen()

    cfg = load_config()
    choose_browser_screen(cfg, allow_back=False)
    choose_agent_mode_screen(cfg, allow_back=False)

    try:
        while True:
            mode_label = "SELF-AWARE BOT" if cfg.get("agent_mode") == "SELF_AWARE" else "NORMAL"
            menu_items = [
                {"label": f"Launch BrowserClaw ({mode_label})", "desc": "Independent self-moving AI mouse + resumes your saved chat thread"},
                {"label": "Switch Mode (Normal / Self-Aware Bot)", "desc": "Choose between Normal Mode or autonomous Discord/Gaming Self-Aware Bot"},
                {"label": "Connect to My Already-Open Browser", "desc": "Attach directly to your existing logged-in browser window"},
                {"label": "Quick Actions & Presets", "desc": "Open Discord, screen vision check, PC health audit"},
                {"label": "Settings (Debug Mode, TTS Toggle, Vision, Model)", "desc": f"Debug: {'ON' if cfg.get('debug_mode') else 'OFF'} | TTS: {'ON' if cfg.get('allow_tts') else 'OFF'}"},
                {"label": "Tools & Capabilities", "desc": "Inspect all Windows & Linux PC control commands"},
                {"label": "Exit", "desc": "Close BrowserClaw"},
            ]
            choice = interactive_menu("MAIN MENU", f"Made by MelonGG3 | {OS_NAME_LABEL} Edition", menu_items, cfg, allow_back=False)

            if choice == 0:
                run_agent_console(cfg)
            elif choice == 1:
                choose_agent_mode_screen(cfg, allow_back=True)
            elif choice == 2:
                cfg["connect_mode"] = "LIVE_ATTACH"
                save_config(cfg)
                run_agent_console(cfg)
            elif choice == 3:
                presets_screen(cfg)
            elif choice == 4:
                cfg = settings_screen(cfg)
            elif choice == 5:
                tools_inspector(cfg)
            elif choice == 6:
                clear_screen()
                break
    finally:
        AI_CURSOR.stop()


if __name__ == "__main__":
    main()