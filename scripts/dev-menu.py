#!/usr/bin/env python3
"""Dev helper: press O to open localhost, U for selective KV upload."""

import subprocess
import sys
import webbrowser
from pathlib import Path

# Ports (match your setup)
FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"
SCRIPT_DIR = Path(__file__).resolve().parent


def getch_unix():
    """Read single keypress on Unix/macOS."""
    import tty
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1).lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def getch_win():
    """Read single keypress on Windows."""
    import msvcrt
    return msvcrt.getch().decode(errors="ignore").lower()


def getch():
    """Single keypress, or fallback to input() when not a TTY."""
    if not sys.stdin.isatty():
        try:
            return input("  Choice: ").strip().lower()[:1] or "q"
        except (EOFError, KeyboardInterrupt):
            return "q"
    try:
        if sys.platform == "win32":
            return getch_win()
        return getch_unix()
    except Exception:
        return input("  Choice: ").strip().lower()[:1] or "q"


def open_localhost():
    webbrowser.open(FRONTEND_URL)
    print("  Opened", FRONTEND_URL)


def run_upload():
    upload_script = SCRIPT_DIR / "upload-to-kv.py"
    subprocess.run([sys.executable, str(upload_script)], cwd=SCRIPT_DIR.parent)
    input("\n  Press Enter to return to menu...")


def main():
    print("\n  Similarity Browser — Dev Menu\n")
    print("  O  Open localhost:5173 in browser")
    print("  U  Upload runs to KV (selective)")
    print("  B  Open backend health (localhost:8000)")
    print("  Q  Quit\n")

    while True:
        print("  Press key: ", end="", flush=True)
        try:
            ch = getch()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break

        print(ch)

        if ch in ("q", "\x1b"):  # q or Escape
            print("  Bye.\n")
            break
        elif ch == "o":
            open_localhost()
        elif ch == "u":
            run_upload()
        elif ch == "b":
            webbrowser.open(BACKEND_URL)
            print("  Opened", BACKEND_URL)


if __name__ == "__main__":
    main()
