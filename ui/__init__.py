"""
Zoom+ Modular UI Package (ui)
=============================
Modular desktop user interface for Zoom+ Pro Studio:
- theme: Dark Slate design system, DWM attributes, buttons, typography
- modals: Window picker, screen picker, ROI selector & board points selector
- hotkeys: Global system-wide hotkeys & in-app keyboard shortcuts
- settings_window: Floating modern settings panel & preset manager
"""

from __future__ import annotations

from ui import theme, modals, hotkeys, settings_window

from ui.theme import (
    CLR_BG_ROOT,
    CLR_BG_TOOLBAR,
    CLR_BG_PANEL,
    CLR_BG_CARD,
    CLR_BG_INPUT,
    CLR_BORDER,
    CLR_BORDER_LIGHT,
    CLR_ACCENT,
    CLR_ACCENT_HOVER,
    CLR_ACCENT_ACTIVE,
    CLR_ACCENT_BG,
    CLR_TEXT_PRIMARY,
    CLR_TEXT_SECONDARY,
    CLR_TEXT_MUTED,
    CLR_TEXT_SUBTLE,
    CLR_SUCCESS,
    CLR_WARNING,
    CLR_DANGER,
    FONT_FAMILY,
    FONT_TITLE,
    FONT_SUBTITLE,
    FONT_HEADING,
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_BADGE,
    FONT_MONO,
    WDA_NONE,
    WDA_EXCLUDEFROMCAPTURE,
    apply_dark_title_bar,
    set_window_capture_passthrough,
    set_window_click_through,
    copy_image_to_clipboard,
    open_folder_in_explorer,
    make_flat_button,
    configure_studio_styles,
)

from ui.modals import (
    WindowPickerModal,
    ScreenRegionSelector,
    BoardPointSelector,
    ScreenPickerModal,
)

from ui.hotkeys import (
    GlobalHotkeyManager,
    bind_local_shortcuts,
)

from ui.settings_window import (
    SettingsWindow,
)

__all__ = [
    "theme",
    "modals",
    "hotkeys",
    "settings_window",
    # Theme exports
    "CLR_BG_ROOT",
    "CLR_BG_TOOLBAR",
    "CLR_BG_PANEL",
    "CLR_BG_CARD",
    "CLR_BG_INPUT",
    "CLR_BORDER",
    "CLR_BORDER_LIGHT",
    "CLR_ACCENT",
    "CLR_ACCENT_HOVER",
    "CLR_ACCENT_ACTIVE",
    "CLR_ACCENT_BG",
    "CLR_TEXT_PRIMARY",
    "CLR_TEXT_SECONDARY",
    "CLR_TEXT_MUTED",
    "CLR_TEXT_SUBTLE",
    "CLR_SUCCESS",
    "CLR_WARNING",
    "CLR_DANGER",
    "FONT_FAMILY",
    "FONT_TITLE",
    "FONT_SUBTITLE",
    "FONT_HEADING",
    "FONT_BODY",
    "FONT_BODY_BOLD",
    "FONT_BADGE",
    "FONT_MONO",
    "WDA_NONE",
    "WDA_EXCLUDEFROMCAPTURE",
    "apply_dark_title_bar",
    "set_window_capture_passthrough",
    "set_window_click_through",
    "copy_image_to_clipboard",
    "open_folder_in_explorer",
    "make_flat_button",
    "configure_studio_styles",
    # Modals exports
    "WindowPickerModal",
    "ScreenRegionSelector",
    "BoardPointSelector",
    "ScreenPickerModal",
    # Hotkeys exports
    "GlobalHotkeyManager",
    "bind_local_shortcuts",
    # Settings window exports
    "SettingsWindow",
]
