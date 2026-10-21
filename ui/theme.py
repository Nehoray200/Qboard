"""
Zoom+ Studio UI Theme & Visual Styling (ui/theme.py)
====================================================
Comprehensive Dark Slate Studio design system for Zoom+ desktop client.
Includes color palettes, typographic scales, native Windows 10/11 DWM
immersive dark title bars, anti-mirror capture passthrough affinity,
and flat button widget factories.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Tuple, Any, Optional

import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------------------
# Visual Theme & Color Palette (Dark Slate Studio)
# ---------------------------------------------------------------------------

CLR_BG_ROOT = "#0B0F19"       # Deepest studio canvas background
CLR_BG_TOOLBAR = "#0F172A"    # Slate 900
CLR_BG_PANEL = "#1E293B"      # Slate 800 control panel & cards
CLR_BG_CARD = "#162032"       # Slate 850 sub-containers
CLR_BG_INPUT = "#0B1120"      # Very dark input backgrounds
CLR_BORDER = "#334155"        # Slate 700 borders
CLR_BORDER_LIGHT = "#475569"  # Slate 600 borders

CLR_ACCENT = "#38BDF8"        # Sky 400 sky-blue accent
CLR_ACCENT_HOVER = "#0284C7"  # Sky 600
CLR_ACCENT_ACTIVE = "#0EA5E9" # Sky 500
CLR_ACCENT_BG = "#0369A1"     # Dark sky blue for active buttons

CLR_TEXT_PRIMARY = "#F8FAFC"  # Crisp Slate 50 white
CLR_TEXT_SECONDARY = "#CBD5E1"# Slate 300
CLR_TEXT_MUTED = "#94A3B8"    # Slate 400
CLR_TEXT_SUBTLE = "#64748B"   # Slate 500

CLR_SUCCESS = "#10B981"       # Emerald 500
CLR_WARNING = "#F59E0B"       # Amber 500
CLR_DANGER = "#EF4444"        # Red 500


# ---------------------------------------------------------------------------
# Typographic Scale
# ---------------------------------------------------------------------------

FONT_FAMILY = "Segoe UI"
FONT_TITLE = (FONT_FAMILY, 14, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 10)
FONT_HEADING = (FONT_FAMILY, 11, "bold")
FONT_BODY = (FONT_FAMILY, 9)
FONT_BODY_BOLD = (FONT_FAMILY, 9, "bold")
FONT_BADGE = (FONT_FAMILY, 8, "bold")
FONT_MONO = ("Consolas", 9)


# ---------------------------------------------------------------------------
# Windows DWM Window Customization APIs
# ---------------------------------------------------------------------------

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def apply_dark_title_bar(window: tk.Tk | tk.Toplevel) -> None:
    """
    Enable native immersive dark mode for Windows 10/11 title bars.
    Queries DwmSetWindowAttribute with DWMWA_USE_IMMERSIVE_DARK_MODE.
    """
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        if not hwnd:
            return
        value = ctypes.c_int(2)
        # 20 for Windows 11 / Windows 10 20H1+, 19 for older Windows 10 builds
        for attr in (20, 19):
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
            if res == 0:
                break
    except Exception:
        pass


def set_window_capture_passthrough(
    window: tk.Tk | tk.Toplevel,
    exclude_from_capture: bool = True,
) -> bool:
    """
    Set Windows DWM capture affinity to WDA_EXCLUDEFROMCAPTURE (0x00000011).
    When enabled, Windows 10 (2004+) and Windows 11 DWM completely hides this window
    from screen capture APIs (ImageGrab.grab, BitBlt, Windows Graphics Capture).
    The window remains 100% interactive and visible to the human user, allowing Zoom+
    to sit directly on top of the Zoom meeting window with zero hall-of-mirrors feedback.
    """
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        if not hwnd:
            return False
        affinity = wintypes.DWORD(WDA_EXCLUDEFROMCAPTURE if exclude_from_capture else WDA_NONE)
        res = ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), affinity)
        return bool(res)
    except Exception:
        return False


def set_window_click_through(window: tk.Tk | tk.Toplevel, enable: bool = True) -> bool:
    """Enable or disable mouse/input click-through (WS_EX_TRANSPARENT | WS_EX_LAYERED)."""
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        if not hwnd:
            return False
        GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x00000020, 0x00080000
        get_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
        set_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)
        style = get_long(wintypes.HWND(hwnd), GWL_EXSTYLE)
        new_style = (style | WS_EX_TRANSPARENT | WS_EX_LAYERED) if enable else (style & ~WS_EX_TRANSPARENT)
        set_long(wintypes.HWND(hwnd), GWL_EXSTYLE, new_style)
        SWP_FLAGS = 0x0002 | 0x0001 | 0x0004 | 0x0020  # NOMOVE | NOSIZE | NOZORDER | FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, SWP_FLAGS)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Custom Styled Widget Helpers
# ---------------------------------------------------------------------------

def make_flat_button(
    parent: tk.Widget,
    text: str,
    command: Any,
    bg: str = CLR_BG_PANEL,
    fg: str = CLR_TEXT_PRIMARY,
    hover_bg: str = CLR_BORDER,
    hover_fg: str = CLR_TEXT_PRIMARY,
    font: Tuple[str, int, str] | Tuple[str, int] = FONT_BODY_BOLD,
    padx: int = 10,
    pady: int = 5,
    border: int = 1,
    relief: str = "solid",
) -> tk.Button:
    """
    Create a sleek, flat dark-themed button with dynamic hover feedback.
    Maintains `_default_bg`, `_default_fg`, `_current_bg`, and `_current_fg`
    attributes so active states are preserved on mouse leave.
    """
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=hover_bg,
        activeforeground=hover_fg,
        font=font,
        padx=padx,
        pady=pady,
        bd=border,
        relief=relief,
        highlightthickness=0,
        cursor="hand2",
    )

    def on_enter(e: tk.Event) -> None:
        if btn["state"] != "disabled":
            btn.config(bg=hover_bg, fg=hover_fg)

    def on_leave(e: tk.Event) -> None:
        if btn["state"] != "disabled":
            # Check if this button was dynamically set to an active color
            current_bg = getattr(btn, "_current_bg", bg)
            current_fg = getattr(btn, "_current_fg", fg)
            btn.config(bg=current_bg, fg=current_fg)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    btn._default_bg = bg
    btn._default_fg = fg
    btn._current_bg = bg
    btn._current_fg = fg
    return btn


def configure_studio_styles(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    """
    Configure ttk theme styles for dark mode Treeview, Scrollbars, and controls.
    """
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "DarkPicker.Treeview",
        background=CLR_BG_PANEL,
        foreground=CLR_TEXT_PRIMARY,
        fieldbackground=CLR_BG_PANEL,
        font=FONT_BODY,
        rowheight=28,
        borderwidth=0,
    )
    style.configure(
        "DarkPicker.Treeview.Heading",
        background=CLR_BG_TOOLBAR,
        foreground=CLR_ACCENT,
        font=FONT_BODY_BOLD,
        relief="flat",
        padding=4,
    )
    style.map(
        "DarkPicker.Treeview",
        background=[("selected", CLR_ACCENT_HOVER)],
        foreground=[("selected", "#FFFFFF")],
    )
    return style
