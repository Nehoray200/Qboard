"""
Qboard Real-Time Whiteboard Enhancement Application (main.py)
============================================================
Main application launcher for Qboard Pro Studio.

Usage:
    python main.py             # Launch full desktop GUI studio
    python main.py --self-test # Run automated headless self-test suite
"""

import sys
import ctypes

# Initialize Windows Per-Monitor DPI awareness BEFORE any GUI module (Tkinter) is loaded
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from app import ZoomPlusApp
from tests_runner import run_self_test


def main() -> None:
    if "--self-test" in sys.argv:
        exit_code = run_self_test()
        sys.exit(exit_code)
    else:
        app = ZoomPlusApp(headless=False)
        app.run()


if __name__ == "__main__":
    main()
