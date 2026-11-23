🐾 BrowserClaw — The Web-Driven Sequel to OpenClaw
Sequel to OpenClaw on the Web • Multi-AI Friendly • 0..1000 Vision Grid • Independent AI Cursor • Windows & Linux

BrowserClaw is a web-powered sequel to OpenClaw, bringing autonomous desktop and browser control directly through your web AI sessions instead of relying on paid API keys or local LLM setups. It supports multiple AI models/options in your browser and pairs live gridded screenshots with a self-moving AI cursor overlay, human-paced typing, window/app/Discord controls, and system/file tools across Windows and Linux.

✨ Key Highlights
🌐 Web Sequel to OpenClaw: Built as the next step for OpenClaw-style desktop automation on the web—connects via Playwright CDP to web AI interfaces across Edge, Chrome, Brave, Opera/Opera GX, and Chromium without needing API keys, supporting both a dedicated browser profile and attaching to an already-open browser window (LIVE_ATTACH).

🤖 Multiple AI Options: Not locked to a single AI—supports switching between available web AI model modes/options (such as AUTO, HYDROGEN, or KEEP) right from the menu or /model command.

🎯 1:1 DPI-Aware Vision + 0..1000 Coordinate Grid: Captures live screenshots scaled to your target resolution, overlays a 0..1000 coordinate grid, and marks your last click with a crosshair so coordinates stay accurate.

🖱️ Independent AI Cursor (VirtualCursorOverlay): Renders an always-on-top, click-through AI cursor that glides along quadratic Bezier curves with click pulse animations—moving independently without dragging your real mouse cursor around.

🧠 Two Intelligence Modes:

Normal Mode: Executes multi-turn JSON action plans ({"actions": [...]}) for your prompts with /debug, /new, /model, /mode, /show, /hide, and /menu commands.

Self-Aware Bot Mode: Autonomous loop that plans multi-step activity arcs, avoids repeating past actions, double-clicks Desktop icons or searches apps/browsers, chats in Discord, and plays games—protected by a 5-warning confirmation flow and instant kill-switches (ESC, top-left (0, 0) mouse corner, or Ctrl+C).

⌨️ Human-Paced Input & Window Control: Types character-by-character with natural pauses (plus Unicode/Linux fallbacks), controls windows (focus, minimize, maximize, restore, close, snap_left, snap_right, move_resize), launches apps/desktop icons, and uses discord_quick_switcher, browser_goto, and browser_search.

🛠️ System, File, Shell & Media Tools: Includes process inspection/killing, CPU/RAM/disk/battery/Wi-Fi/IP stats, volume/media controls, notifications, optional TTS (speak_tts), clipboard helpers, file/archive operations, HTTP/ping utilities, and run_cmd / run_powershell.

📦 Auto-Dependency Setup & Session Persistence: Automatically detects and installs missing packages (rich, playwright, pyautogui, mss, pillow), remembers your saved chat thread URL (last_chat_url), and keeps your config clean.

🚀 Quick Start
Run python BrowserClaw.py (missing Python packages will be prompted to install automatically).

Choose your browser and intelligence mode (NORMAL or SELF_AWARE).

Sign into your web AI account on first launch if prompted, then enter a task or preset!

⚠️ Kill-Switches
Stop execution immediately at any time by:

Holding ESC

Moving your physical mouse into the top-left corner (0, 0)

Pressing Ctrl + C in the terminal
