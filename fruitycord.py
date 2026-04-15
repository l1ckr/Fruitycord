#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

                                  
                                                       

Fruitycord — Discord Rich Presence for FL Studio 25 on macOS
GitHub: https://github.com/l1ckr/Fruitycord

──────────────────────────────────────────────────────────────────────────

HOW TO INSTALL DEPENDENCIES:
  pip install pypresence

HOW TO RUN:
  python3 fruitycord.py

HOW TO RUN AT LOGIN (via launchd):
  1. Save fruitycord.plist (template at the bottom) to
     ~/Library/LaunchAgents/com.fruitycord.plist
  2. Run: launchctl load ~/Library/LaunchAgents/com.fruitycord.plist

HOW TO MAKE .APP (see instructions below)
  pip install py2app
  py2applet --make-setup fruitycord.py
  python setup.py py2app
──────────────────────────────────────────────────────────────────────────
"""

# ╔══════════════════════════════════════════════════════════════════╗
# ║                       SETTINGS — EDIT HERE                       ║
# ╚══════════════════════════════════════════════════════════════════╝

CLIENT_ID = "1492974703906652301"  # Application ID from Discord Developer Portal

# Rich Presence update interval (seconds). Less than 15 may get rate-limited by Discord.
UPDATE_INTERVAL = 15

# Top line in Rich Presence
DETAILS_TEXT = "Working in FL Studio 2025"

# Text shown when project name cannot be detected
UNKNOWN_PROJECT = "Unknown"

# Large image key (must match the asset name you uploaded in Discord)
LARGE_IMAGE_KEY = "flstudio"
LARGE_IMAGE_TEXT = "FL Studio 25"

# Small icon (optional — upload asset with key "apple" in Discord)
SMALL_IMAGE_KEY = "apple"
SMALL_IMAGE_TEXT = "macOS"

# Possible process names for FL Studio on macOS
FL_PROCESS_NAMES = ["FL Studio", "OsxFL", "FLStudio"]

# FL Studio project file extensions
FL_PROJECT_EXTENSIONS = (".flp", ".zip")

# ══════════════════════════════════════════════════════════════════
#   Everything below this line is the core code.
#   Only edit if you know what you're doing.
# ══════════════════════════════════════════════════════════════════

import os
import re
import sys
import time
import signal
import subprocess
import logging
import traceback
from datetime import datetime
from typing import Optional

# ── Dependency check ─────────────────────────────────────────────
try:
    from pypresence import Presence
    # Handle different pypresence versions
    try:
        from pypresence import InvalidID
    except ImportError:
        try:
            from pypresence.exceptions import InvalidID
        except ImportError:
            InvalidID = Exception
    try:
        from pypresence import PyPresenceException
    except ImportError:
        try:
            from pypresence.exceptions import PyPresenceException
        except ImportError:
            PyPresenceException = Exception
except ImportError:
    print(
        "\n[✗] pypresence library is not installed.\n"
        "    Run: pip install pypresence\n"
    )
    sys.exit(1)

# ── Logger ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fruitycord")


# ════════════════════════════════════════════════════════════════
#  BLOCK 1 — Finding FL Studio process
# ════════════════════════════════════════════════════════════════

def find_fl_studio_pid() -> Optional[int]:
    """
    Searches for the FL Studio process among running applications.
    Checks several possible process names (FL_PROCESS_NAMES).
    Returns PID (int) or None if FL Studio is not running.
    """
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,comm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid_str, comm = parts
            for name in FL_PROCESS_NAMES:
                if name.lower() in comm.lower():
                    try:
                        return int(pid_str)
                    except ValueError:
                        continue
    except Exception as e:
        log.debug("Error searching for process: %s", e)
    return None


# ════════════════════════════════════════════════════════════════
#  BLOCK 2 — Getting project name
# ════════════════════════════════════════════════════════════════

def get_project_via_lsof(pid: int) -> Optional[str]:
    """
    PRIMARY METHOD: reads open files via lsof.
    Looks for .flp or .zip files.
    Returns filename without extension or None.

    IMPORTANT: On macOS FL Studio often closes the file descriptor
    shortly after loading the project into memory.
    """
    try:
        result = subprocess.run(
            ["lsof", "-p", str(pid), "-Fn"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        candidates = []
        for line in result.stdout.splitlines():
            if not line.startswith("n"):
                continue
            path = line[1:].strip()
            if not path.startswith("/"):
                continue
            lower = path.lower()
            for ext in FL_PROJECT_EXTENSIONS:
                if lower.endswith(ext):
                    candidates.append(path)
                    log.debug("lsof found candidate: %s", path)
                    break

        if not candidates:
            log.debug("lsof: no .flp files found in open descriptors (pid=%d)", pid)
            return None

        best = max(candidates, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
        basename = os.path.basename(best)
        for ext in FL_PROJECT_EXTENSIONS:
            if basename.lower().endswith(ext):
                basename = basename[: -len(ext)]
                break
        return basename if basename else None

    except FileNotFoundError:
        log.warning("lsof not found. Install Xcode Command Line Tools: xcode-select --install")
    except subprocess.TimeoutExpired:
        log.debug("lsof timed out — skipping")
    except Exception as e:
        log.debug("lsof error: %s", e)
    return None


def get_project_via_spotlight() -> Optional[str]:
    """
    FALLBACK METHOD: finds the most recently used .flp via Spotlight (mdfind).

    Filters by kMDItemLastUsedDate (last time the file was opened), NOT mtime
    (last save). A project opened today but saved days ago would be missed
    by an mtime filter — LastUsedDate updates on open regardless of saving.
    """
    try:
        # Filter by last opened date (7-day window) — survives unsaved sessions
        result = subprocess.run(
            [
                "mdfind",
                "-onlyin", os.path.expanduser("~"),
                'kMDItemFSExtension == "flp" && kMDItemLastUsedDate >= $time.today(-7)',
            ],
            capture_output=True,
            text=True,
            timeout=6,
        )
        candidates = []
        for line in result.stdout.splitlines():
            path = line.strip()
            if not path or not os.path.exists(path):
                continue
            candidates.append(path)
            log.debug("Spotlight candidate: %s", path)

        if not candidates:
            log.debug("Spotlight: no .flp files opened in the last 7 days")
            return None

        # Among candidates, pick the most recently saved (mtime)
        best_path = max(candidates, key=lambda p: os.path.getmtime(p))
        log.debug("Spotlight found: %s", best_path)
        return os.path.splitext(os.path.basename(best_path))[0]

    except FileNotFoundError:
        log.debug("mdfind not found — Spotlight unavailable")
    except subprocess.TimeoutExpired:
        log.debug("mdfind timed out — skipping")
    except Exception as e:
        log.debug("Spotlight error: %s", e)
    return None


def get_project_via_applescript() -> Optional[str]:
    """
    FALLBACK METHOD: reads window title via AppleScript / Accessibility API.
    """
    # Approach 1: System Events window title
    script_window = """
    tell application "System Events"
        set flApp to first process whose name contains "FL Studio" or name contains "OsxFL"
        if exists flApp then
            try
                set winName to name of front window of flApp
                return winName
            end try
        end if
    end tell
    return ""
    """
    title = _run_applescript(script_window)
    if title:
        parsed = _parse_project_from_title(title)
        if parsed:
            return parsed

    # Approach 2: AXDocument attribute
    script_axdoc = """
    tell application "System Events"
        set flApp to first process whose name contains "FL Studio" or name contains "OsxFL"
        if exists flApp then
            try
                tell flApp
                    set axDoc to value of attribute "AXDocument" of front window
                    return axDoc
                end tell
            end try
        end if
    end tell
    return ""
    """
    ax_doc = _run_applescript(script_axdoc)
    if ax_doc and ax_doc.startswith("file://"):
        from urllib.parse import unquote
        path = unquote(ax_doc.replace("file://", ""))
        basename = os.path.basename(path)
        for ext in FL_PROJECT_EXTENSIONS:
            if basename.lower().endswith(ext):
                return basename[: -len(ext)]

    return None


def _run_applescript(script: str) -> Optional[str]:
    """Runs AppleScript and returns stdout as string (or None on error)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        return output if output else None
    except subprocess.TimeoutExpired:
        log.debug("AppleScript timed out — skipping")
    except Exception as e:
        log.debug("AppleScript error: %s", e)
    return None


def _parse_project_from_title(title: str) -> Optional[str]:
    """
    Extracts project name from window title.
    Examples: "MyBeat.flp — FL Studio 25", "MyBeat — FL Studio"
    """
    cleaned = re.sub(r"FL\s*Studio\s*\d*", "", title, flags=re.IGNORECASE)
    cleaned = re.sub(r"[-–—|]+", "", cleaned).strip()
    for ext in FL_PROJECT_EXTENSIONS:
        if cleaned.lower().endswith(ext):
            cleaned = cleaned[: -len(ext)]
    return cleaned.strip() if cleaned.strip() else None


def get_project_name(pid: int) -> str:
    """
    Main project name resolver.
    Priority order:
      1. lsof
      2. AppleScript / Accessibility
      3. Spotlight
      4. UNKNOWN_PROJECT fallback
    """
    name = get_project_via_lsof(pid)
    if name:
        log.info("Project found (lsof): %s", name)
        return name

    name = get_project_via_applescript()
    if name:
        log.info("Project found (AppleScript): %s", name)
        return name

    name = get_project_via_spotlight()
    if name:
        log.info("Project found (Spotlight): %s", name)
        return name

    log.debug("Project name could not be determined — using fallback")
    return UNKNOWN_PROJECT


# ════════════════════════════════════════════════════════════════
#  BLOCK 3 — Rich Presence
# ════════════════════════════════════════════════════════════════

class FruitycordPresence:
    """
    Manages Discord connection and Rich Presence updates.
    Handles automatic reconnection.
    """

    def __init__(self):
        self.rpc: Optional[Presence] = None
        self.connected = False
        self.session_start: Optional[int] = None
        self._last_project: Optional[str] = None
        self._cached_project: Optional[str] = None

    def connect(self) -> bool:
        """Connects to Discord IPC."""
        if self.rpc is not None:
            try:
                self.rpc.close()
            except Exception:
                pass
            self.rpc = None
        self.connected = False

        try:
            self.rpc = Presence(CLIENT_ID)
            self.rpc.connect()
            self.connected = True
            log.info("✓ Connected to Discord (CLIENT_ID=%s)", CLIENT_ID)
            return True
        except FileNotFoundError:
            log.warning("Discord is not running or IPC socket unavailable")
        except InvalidID:
            log.error("✗ Invalid CLIENT_ID: «%s» — check Discord Developer Portal!", CLIENT_ID)
        except Exception as e:
            log.warning("Connection error: %s — %s", type(e).__name__, e)
        self.connected = False
        return False

    def disconnect(self):
        """Safely closes Discord connection."""
        if self.rpc:
            try:
                self.rpc.clear()
            except Exception:
                pass
            try:
                self.rpc.close()
            except Exception:
                pass
            log.info("Disconnected from Discord")
        self.connected = False
        self.rpc = None

    def update(self, pid: int, project: str):
        """Updates Rich Presence in Discord."""
        if project != self._last_project:
            self.session_start = int(time.time())
            if project != UNKNOWN_PROJECT:
                log.info("▶ New project: %s", project)
            else:
                log.info("▶ Project not detected (showing fallback)")
            self._last_project = project

        kwargs = dict(
            details=DETAILS_TEXT,
            state=f"Project: {project}",
            start=self.session_start,
            large_image=LARGE_IMAGE_KEY,
            large_text=LARGE_IMAGE_TEXT,
        )
        if SMALL_IMAGE_KEY:
            kwargs["small_image"] = SMALL_IMAGE_KEY
            kwargs["small_text"] = SMALL_IMAGE_TEXT

        try:
            self.rpc.update(**kwargs)
            log.info("✓ Rich Presence updated [%s]", project)
        except Exception as e:
            log.warning("✗ Failed to update Presence: %s — %s", type(e).__name__, e)
            self.disconnect()

    def clear(self):
        """Clears Rich Presence when FL Studio is closed."""
        if self.rpc and self.connected:
            try:
                self.rpc.clear()
                log.info("Rich Presence cleared (FL Studio closed)")
            except Exception:
                pass
        self.session_start = None
        self._last_project = None
        self._cached_project = None


# ════════════════════════════════════════════════════════════════
#  BLOCK 4 — Main loop
# ════════════════════════════════════════════════════════════════

def main():
    if CLIENT_ID == "APPLICATION_ID_HERE":
        print(
            "\n╔══════════════════════════════════════════════════════╗\n"
            "║  Please set your CLIENT_ID at the top of the script!  ║\n"
            "║  Go to: https://discord.com/developers/applications   ║\n"
            "╚══════════════════════════════════════════════════════╝\n"
        )
        sys.exit(1)

    print(
        "\n"
        "  ┌─────────────────────────────────────────────┐\n"
        "  │ Fruitycord — FL Studio 25 Rich Presence 1.0 │\n"
        "  │  Press Ctrl+C to exit                       │\n"
        "  └─────────────────────────────────────────────┘\n"
    )

    presence = FruitycordPresence()

    def handle_exit(sig, frame):
        print("\n\nExiting...")
        presence.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    fl_was_running = False
    waiting_logged = False
    reconnect_fails = 0

    while True:
        pid = find_fl_studio_pid()
        fl_running = pid is not None

        if fl_was_running and not fl_running:
            log.info("FL Studio closed")
            presence.clear()
            fl_was_running = False
            waiting_logged = False
            reconnect_fails = 0

        if fl_running:
            if not fl_was_running:
                log.info("FL Studio detected (pid=%d)", pid)
                fl_was_running = True
                waiting_logged = False
                presence._last_project = None
                presence._cached_project = None

            if not presence.connected:
                if not presence.connect():
                    reconnect_fails += 1
                    delay = min(15 * (2 ** min(reconnect_fails - 1, 2)), 60)
                    log.info("Retrying connection in %d sec (attempt %d)...", delay, reconnect_fails)
                    time.sleep(delay)
                    continue
                reconnect_fails = 0

            detected = get_project_name(pid)
            if detected != UNKNOWN_PROJECT:
                if detected != presence._cached_project:
                    log.info("Project detected: %s", detected)
                    presence._cached_project = detected
            project = presence._cached_project or UNKNOWN_PROJECT
            presence.update(pid, project)

        else:
            if not waiting_logged:
                log.info("Waiting for FL Studio... (updating every %ds)", UPDATE_INTERVAL)
                waiting_logged = True

        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()


# ══════════════════════════════════════════════════════════════════
#  LAUNCHD PLIST TEMPLATE (for auto-start at login)
#  Save as ~/Library/LaunchAgents/com.fruitycord.plist
#  (replace /FULL/PATH/TO/fruitycord.py)
#
# <?xml version="1.0" encoding="UTF-8"?>
# <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
#   "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
# <plist version="1.0">
# <dict>
#     <key>Label</key>
#     <string>com.fruitycord</string>
#     <key>ProgramArguments</key>
#     <array>
#         <string>/usr/bin/python3</string>
#         <string>/FULL/PATH/TO/fruitycord.py</string>
#     </array>
#     <key>RunAtLoad</key>
#     <true/>
#     <key>KeepAlive</key>
#     <true/>
#     <key>StandardOutPath</key>
#     <string>/tmp/fruitycord.log</string>
#     <key>StandardErrorPath</key>
#     <string>/tmp/fruitycord.err</string>
# </dict>
# </plist>
# ══════════════════════════════════════════════════════════════════