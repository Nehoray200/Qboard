"""
Zoom+ Studio Hotkeys & Shortcut Management (ui/hotkeys.py)
==========================================================
Clean, modular hotkey orchestration for Zoom+:
1. GlobalHotkeyManager: Low-latency background polling (~25 Hz) of Windows
   GetAsyncKeyState with state edge-detection (F5-F10, Ctrl+Alt shortcuts).
2. bind_local_shortcuts: In-app Tkinter keyboard shortcut event bindings.
"""

from __future__ import annotations

import ctypes
from typing import Dict, Any, Optional
import tkinter as tk

# Virtual Key Codes (Windows API)
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12  # Shift, Ctrl, Alt
VK_A, VK_B, VK_M, VK_O, VK_Q, VK_S, VK_T, VK_Z = 0x41, 0x42, 0x4D, 0x4F, 0x51, 0x53, 0x54, 0x5A
VK_F4, VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10 = 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79


class GlobalHotkeyManager:
    """
    Encapsulates Windows GetAsyncKeyState polling with rising-edge detection.
    Allows students and instructors to control Zoom+ while watching live lectures
    in Zoom full-screen without leaving their meeting window or conflicting with
    Zoom and Chrome native shortcuts.
    """

    def __init__(self, app: Any, poll_interval_ms: int = 40) -> None:
        self.app = app
        self.poll_interval_ms = poll_interval_ms
        self._running = False
        self._after_id: Optional[str] = None

        # Rising edge tracking dictionary
        self._key_states: Dict[str, bool] = {
            "quit": False,
            "toggle": False,
            "settings": False,
            "snapshot": False,
            "screen": False,
            "clickthrough": False,
            "board_points": False,
            "auto_board": False,
        }

    def start(self) -> None:
        """Start polling loop if app is not headless."""
        if getattr(self.app, "headless", False):
            return
        self._running = True
        self._schedule_next()

    def stop(self) -> None:
        """Stop background polling and cancel pending callbacks."""
        self._running = False
        if self._after_id and hasattr(self.app, "root") and self.app.root.winfo_exists():
            try:
                self.app.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _schedule_next(self) -> None:
        if not self._running:
            return
        if hasattr(self.app, "root") and self.app.root.winfo_exists():
            self._after_id = self.app.root.after(self.poll_interval_ms, self.poll)

    def _is_down(self, vk: int) -> bool:
        """Check if high bit of GetAsyncKeyState is set (key currently pressed)."""
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return False

    def poll(self) -> None:
        """Check keyboard states, trigger actions on key-down edge, and reschedule."""
        if not hasattr(self.app, "root") or not self.app.root.winfo_exists():
            self._running = False
            return

        try:
            ctrl_down = self._is_down(VK_CONTROL)
            alt_down = self._is_down(VK_MENU)
            shift_down = self._is_down(VK_SHIFT)

            f4_down = self._is_down(VK_F4)
            f5_down = self._is_down(VK_F5)
            f6_down = self._is_down(VK_F6)
            f7_down = self._is_down(VK_F7)
            f8_down = self._is_down(VK_F8)
            f9_down = self._is_down(VK_F9)
            f10_down = self._is_down(VK_F10)

            a_down = self._is_down(VK_A)
            b_down = self._is_down(VK_B)
            m_down = self._is_down(VK_M)
            o_down = self._is_down(VK_O)
            q_down = self._is_down(VK_Q)
            s_down = self._is_down(VK_S)
            t_down = self._is_down(VK_T)
            z_down = self._is_down(VK_Z)

            # 1. Quit Zoom+: Ctrl + Alt + Q
            state_quit = ctrl_down and alt_down and q_down
            if state_quit and not self._key_states["quit"]:
                self._dispatch_quit()
            self._key_states["quit"] = state_quit

            # 2. Toggle Zoom+ Overlay: Ctrl + Alt + Z or F9
            state_toggle = (ctrl_down and alt_down and z_down) or (f9_down and not ctrl_down and not alt_down)
            if state_toggle and not self._key_states["toggle"]:
                self._dispatch_toggle()
            self._key_states["toggle"] = state_toggle

            # 3. Toggle Floating Settings Window: Ctrl + Alt + O or F10
            state_settings = (ctrl_down and alt_down and o_down) or (f10_down and not ctrl_down and not alt_down)
            if state_settings and not self._key_states["settings"]:
                self._dispatch_settings()
            self._key_states["settings"] = state_settings

            # 4. Quick Snapshot: Ctrl + Alt + S or F8
            state_snapshot = (ctrl_down and alt_down and s_down) or (f8_down and not ctrl_down and not alt_down)
            if state_snapshot and not self._key_states["snapshot"]:
                self._dispatch_snapshot()
            self._key_states["snapshot"] = state_snapshot

            # 5. Cycle Screen/Monitor: Ctrl + Alt + M or F7
            state_screen = (ctrl_down and alt_down and m_down) or (f7_down and not ctrl_down and not alt_down)
            if state_screen and not self._key_states["screen"]:
                self._dispatch_screen()
            self._key_states["screen"] = state_screen

            # 6. Click-Through Toggle: Ctrl + Alt + T or F6
            state_ct = (ctrl_down and alt_down and t_down) or (f6_down and not ctrl_down and not alt_down)
            if state_ct and not self._key_states["clickthrough"]:
                self._dispatch_clickthrough()
            self._key_states["clickthrough"] = state_ct

            # 7. Select Board Points: Ctrl + Alt + B or F5 (without Shift)
            state_points = (ctrl_down and alt_down and b_down) or (
                f5_down and not shift_down and not ctrl_down and not alt_down
            )
            if state_points and not self._key_states["board_points"]:
                self._dispatch_board_points()
            self._key_states["board_points"] = state_points

            # 8. Auto-Detect Whiteboard: F4 or Ctrl + Alt + A or Shift + F5
            state_auto_board = (
                (ctrl_down and alt_down and a_down)
                or (f4_down and not ctrl_down and not alt_down)
                or (f5_down and shift_down and not ctrl_down and not alt_down)
            )
            if state_auto_board and not self._key_states["auto_board"]:
                self._dispatch_auto_board()
            self._key_states["auto_board"] = state_auto_board

        except Exception:
            pass

        if self._running:
            self._schedule_next()

    def _dispatch_toggle(self) -> None:
        if hasattr(self.app, "hotkey_toggle_zoom_overlay"):
            self.app.hotkey_toggle_zoom_overlay()

    def _dispatch_settings(self) -> None:
        if hasattr(self.app, "toggle_settings_window"):
            self.app.toggle_settings_window()

    def _dispatch_snapshot(self) -> None:
        if hasattr(self.app, "hotkey_quick_snapshot"):
            self.app.hotkey_quick_snapshot()

    def _dispatch_screen(self) -> None:
        if hasattr(self.app, "cycle_screen_source"):
            self.app.cycle_screen_source()

    def _dispatch_clickthrough(self) -> None:
        if hasattr(self.app, "toggle_click_through"):
            self.app.toggle_click_through()

    def _dispatch_board_points(self) -> None:
        if hasattr(self.app, "open_board_point_selector"):
            self.app.open_board_point_selector()

    def _dispatch_auto_board(self) -> None:
        if hasattr(self.app, "auto_detect_board_region"):
            self.app.auto_detect_board_region()

    def _dispatch_quit(self) -> None:
        if hasattr(self.app, "quit_app"):
            self.app.quit_app()
        elif hasattr(self.app, "root"):
            try:
                if self.app.root.winfo_exists():
                    self.app.root.destroy()
            except Exception:
                pass


def bind_local_shortcuts(app: Any) -> None:
    """
    Bind in-app Tkinter keyboard shortcuts on `app.root`.
    Handles focused interactions: space (pause), Ctrl+S (snapshot), Escape, view modes (1/2/3),
    loupe (L), and crop mode (C). Global function keys and shortcuts are managed exclusively
    by GlobalHotkeyManager to prevent double-execution.
    """
    root: tk.Tk = app.root

    def _on_escape(e: tk.Event) -> None:
        if hasattr(app, "_on_escape"):
            app._on_escape()
        else:
            if getattr(app, "crop_mode", False) and hasattr(app, "toggle_crop_mode"):
                app.toggle_crop_mode()
            if getattr(app, "loupe_enabled", False) and hasattr(app, "toggle_loupe"):
                app.toggle_loupe()

    # Streaming pause/resume
    root.bind("<space>", lambda e: app.toggle_pause() if hasattr(app, "toggle_pause") else None)

    # In-app snapshot shortcut
    for k in ("<Control-s>", "<Control-S>"):
        root.bind(k, lambda e: app.hotkey_quick_snapshot() if hasattr(app, "hotkey_quick_snapshot") else None)

    # Escape key: exit crop/loupe or trigger app escape handler
    root.bind("<Escape>", _on_escape)

    # View modes: 1=enhanced, 2=split, 3=original
    root.bind("<Key-1>", lambda e: app.set_view_mode("enhanced") if hasattr(app, "set_view_mode") else None)
    root.bind("<Key-2>", lambda e: app.set_view_mode("split") if hasattr(app, "set_view_mode") else None)
    root.bind("<Key-3>", lambda e: app.set_view_mode("original") if hasattr(app, "set_view_mode") else None)

    # Tools & navigation
    for k in ("<Key-l>", "<Key-L>"):
        root.bind(k, lambda e: app.toggle_loupe() if hasattr(app, "toggle_loupe") else None)
    for k in ("<Key-c>", "<Key-C>"):
        root.bind(k, lambda e: app.toggle_crop_mode() if hasattr(app, "toggle_crop_mode") else None)
