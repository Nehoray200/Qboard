"""
Qboard Settings & Board Enhancement Dialog (ui/settings_window.py)
=================================================================
Dedicated, clean floating settings modal dialog for Qboard:
- Keeps lecture video 100% distraction-free and maximized over Zoom.
- Quick keyboard access (F10 / Alt+O / Escape).
- 5 one-click presets, 7 real-time sliders, and 6 advanced quality toggles.
- Dark Slate Studio aesthetic matching Windows 10/11 immersive dark mode.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional, Tuple

from processor import PRESETS, PRESET_INFO
from capture import enum_display_monitors, MonitorInfo
from ui.theme import (
    CLR_BG_TOOLBAR, CLR_BG_PANEL, CLR_BG_CARD, CLR_BG_INPUT, CLR_BORDER,
    CLR_ACCENT, CLR_ACCENT_BG, CLR_ACCENT_HOVER, CLR_TEXT_PRIMARY,
    CLR_TEXT_SECONDARY, CLR_TEXT_MUTED, FONT_FAMILY, FONT_SUBTITLE,
    FONT_HEADING, FONT_BODY, FONT_BODY_BOLD, FONT_MONO,
    apply_dark_title_bar, set_window_capture_passthrough, make_flat_button,
)

SLIDERS_META = [
    ("contrast", "ניגודיות והדגשת דיו (Contrast)", 0.5, 4.0, 0.05, "{:.2f}", 1.65),
    ("thickening", "עיבוי עצמים וכתב (Thickening)", 0.0, 2.0, 0.05, "{:.2f}", 0.15),
    ("glare_removal", "ניקוי בוהק והשתקפויות (Glare)", 0.0, 1.0, 0.02, "{:.2f}", 0.90),
    ("shadow_suppression", "סינון צלליות מרצה (Shadow Filter)", 0.0, 1.5, 0.05, "{:.2f}", 0.85),
    ("white_threshold", "סף הלבנת לוח (White Thresh)", 0.002, 0.060, 0.001, "{:.3f}", 0.012),
    ("ink_saturation", "רוויית עומק טוש (Ink Saturation)", 0.03, 0.22, 0.005, "{:.3f}", 0.145),
    ("gamma", "תיקון גאמה (Gamma)", 0.5, 2.5, 0.05, "{:.2f}", 1.12),
    ("sharpen", "חידוד קצוות וטקסט (Sharpness Boost)", 0.0, 4.0, 0.1, "{:.1f}", 1.25),
]

TOGGLES_META = [
    ("fast_mode", "⚡ מצב מהירות שיא (Turbo FPS)", False),
    ("click_through", "🖱️ שקיפות ללחיצות (מאפשר לדבר במקש רווח בזום)", True),
    ("exclude_capture", "👻 מניעת צילום עצמי (שקוף ללכידה)", True),
    ("always_on_top", "📌 נעוץ מעל כל החלונות (Always on Top)", False),
    ("trim_browser_header", "✂️ הסתרת כרטיסיות דפדפן (טאבים עליונים)", False),
    ("preserve_instructor", "שימור דמות המרצה וצבעים טבעיים", True),
    ("invert_dark_mode", "מצב לוח כהה (Dark Mode Blackboard)", False),
    ("denoise", "הפחתת רעשי מצלמה (Denoise)", True),
]


class SettingsWindow(tk.Toplevel):
    """Floating dark-slate dialog for fine-tuning whiteboard enhancement parameters."""

    def __init__(self, parent: Optional[tk.Widget] = None, app: Optional[Any] = None) -> None:
        if app is None and parent is not None and hasattr(parent, "root"):
            self.app, toplevel_parent = parent, parent.root
        elif app is not None:
            self.app, toplevel_parent = app, (parent if isinstance(parent, tk.Widget) else getattr(app, "root", None))
        else:
            self.app, toplevel_parent = None, (parent if isinstance(parent, tk.Widget) else None)

        super().__init__(toplevel_parent)
        self.title("Qboard | הגדרות וכוונון איכות לוח")
        self.geometry("440x680")
        self.minsize(420, 560)
        self.configure(bg=CLR_BG_TOOLBAR)

        apply_dark_title_bar(self)
        set_window_capture_passthrough(self, True)

        if toplevel_parent and toplevel_parent.winfo_exists():
            self.transient(toplevel_parent)
            try:
                px = toplevel_parent.winfo_rootx() + (toplevel_parent.winfo_width() - 440) // 2
                py = toplevel_parent.winfo_rooty() + (toplevel_parent.winfo_height() - 680) // 2
                self.geometry(f"+{max(10, px)}+{max(10, py)}")
            except Exception: pass

        self.attributes("-topmost", True); self.lift(); self.focus_force()
        try: ctypes.windll.user32.BringWindowToTop(wintypes.HWND(self.winfo_id()))
        except Exception: pass

        self.preset_buttons: Dict[str, tk.Button] = {}; self.monitor_buttons: Dict[int, tk.Button] = {}
        self.source_buttons: Dict[str, tk.Button] = {}; self.slider_widgets: Dict[str, tk.Scale] = {}
        self._slider_vars: Dict[str, Tuple[tk.DoubleVar, tk.StringVar, str]] = {}; self._toggle_vars: Dict[str, tk.BooleanVar] = {}

        self._init_state_vars()
        self._build_ui()
        self._init_bindings()

        if self.app is not None:
            self.app.settings_window = self

        self.highlight_preset(getattr(self.app, "current_preset", "clean_board") if self.app else "clean_board")
        self.highlight_source()

    def _init_state_vars(self) -> None:
        p = getattr(self.app, "current_params", None) if self.app else None
        for key, _, _, _, _, fmt, default_val in SLIDERS_META:
            var = getattr(self.app, f"var_{key}") if (self.app and hasattr(self.app, f"var_{key}")) else tk.DoubleVar(value=getattr(p, key, default_val) if p else default_val)
            lbl = getattr(self.app, f"lbl_{key}_val") if (self.app and hasattr(self.app, f"lbl_{key}_val")) else tk.StringVar(value=fmt.format(var.get()))
            self._slider_vars[key] = (var, lbl, fmt)

        for key, _, default_st in TOGGLES_META:
            t_var = getattr(self.app, f"var_{key}") if (self.app and hasattr(self.app, f"var_{key}")) else tk.BooleanVar(value=bool(getattr(p, key, default_st) if p else default_st))
            self._toggle_vars[key] = t_var

        self.preset_desc_var = getattr(self.app, "preset_desc_var", None) or tk.StringVar(value=PRESET_INFO.get("clean_board", {}).get("desc_he", ""))

    def _init_bindings(self) -> None:
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", lambda e: self.on_close())

    def _build_ui(self) -> None:
        # 1. Header
        header = tk.Frame(self, bg=CLR_BG_TOOLBAR, padx=14, pady=10, bd=1, relief="solid")
        header.pack(fill=tk.X, side=tk.TOP)
        make_flat_button(header, text="✕", command=self.on_close, bg=CLR_BG_CARD, fg=CLR_TEXT_MUTED, hover_bg=CLR_BORDER, hover_fg="#FFFFFF", font=FONT_HEADING, padx=8, pady=2).pack(side=tk.LEFT)
        t_box = tk.Frame(header, bg=CLR_BG_TOOLBAR)
        t_box.pack(side=tk.RIGHT)
        tk.Label(t_box, text="⚙️ הגדרות וכוונון איכות לוח", font=FONT_HEADING, bg=CLR_BG_TOOLBAR, fg=CLR_TEXT_PRIMARY).pack(anchor="e")
        tk.Label(t_box, text="שליטה מתקדמת (F10 / Ctrl+Alt+O | יציאה: Ctrl+Alt+Q)", font=(FONT_FAMILY, 8), bg=CLR_BG_TOOLBAR, fg=CLR_TEXT_MUTED).pack(anchor="e")

        # 2. Sticky Footer
        footer = tk.Frame(self, bg=CLR_BG_TOOLBAR, padx=14, pady=10, bd=1, relief="solid")
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        make_flat_button(footer, text="✕ סגור וחזור לווידאו הנקי", command=self.on_close, bg=CLR_ACCENT_BG, fg="#FFFFFF", hover_bg=CLR_ACCENT_HOVER, hover_fg="#FFFFFF", font=FONT_BODY_BOLD, padx=12, pady=9).pack(fill=tk.X)

        # 3. Middle Scrollable Canvas
        mid = tk.Frame(self, bg=CLR_BG_PANEL)
        mid.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(mid, bg=CLR_BG_PANEL, bd=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.canvas.yview)
        self.content_frame = tk.Frame(self.canvas, bg=CLR_BG_PANEL, padx=14, pady=10)

        self.content_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        c_win = self.canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(c_win, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        def _on_wheel(e: tk.Event) -> None:
            if self.winfo_exists():
                self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self.bind("<MouseWheel>", _on_wheel)
        self.canvas.bind("<MouseWheel>", _on_wheel)
        self.content_frame.bind("<MouseWheel>", _on_wheel)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_source_section(self.content_frame)
        self._build_presets_section(self.content_frame)
        self._build_sliders_section(self.content_frame)
        self._build_toggles_section(self.content_frame)
        self._build_reset_section(self.content_frame)

    def _build_source_section(self, parent: tk.Widget) -> None:
        card = tk.LabelFrame(parent, text="  מקור לכידה ובחירת מסך  ", font=FONT_BODY_BOLD, bg=CLR_BG_PANEL, fg=CLR_ACCENT, bd=1, relief="solid", padx=10, pady=8)
        card.pack(fill=tk.X, pady=(0, 10))

        for m in enum_display_monitors():
            lbl = f"🖥️ מסך {m.index + 1}{' (ראשי)' if m.is_primary else ''} [{m.width}×{m.height}]"
            btn = make_flat_button(
                card, text=lbl, command=lambda idx=m.index: self._select_screen(idx),
                bg=CLR_BG_CARD, fg=CLR_TEXT_PRIMARY, hover_bg=CLR_BORDER, font=FONT_BODY_BOLD, padx=8, pady=5
            )
            btn.pack(fill=tk.X, pady=2)
            self.monitor_buttons[m.index] = btn

        btn_points = make_flat_button(
            card, text="📍 בחירת נקודות הלוח (F5 / Ctrl+Alt+B)",
            command=lambda: self.app.open_board_point_selector() if self.app and hasattr(self.app, "open_board_point_selector") else None,
            bg=CLR_ACCENT_BG, fg=CLR_ACCENT, hover_bg=CLR_ACCENT_HOVER, font=FONT_BODY_BOLD, padx=8, pady=5
        )
        btn_points.pack(fill=tk.X, pady=(4, 2))

        btn_auto = make_flat_button(
            card, text="🤖 זיהוי לוח אוטומטי (F4 / Ctrl+Alt+A)",
            command=lambda: self.app.auto_detect_board_region() if self.app and hasattr(self.app, "auto_detect_board_region") else None,
            bg=CLR_BG_CARD, fg=CLR_TEXT_PRIMARY, hover_bg=CLR_BORDER, font=FONT_BODY_BOLD, padx=8, pady=2
        )
        btn_auto.pack(fill=tk.X, pady=(2, 4))

        grid = tk.Frame(card, bg=CLR_BG_PANEL)
        grid.pack(fill=tk.X, pady=(6, 2))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        actions = [
            ("🎯 חלון זום", "zoom"),
            ("🪟 בחירת חלון...", "window"),
            ("📐 גזירת אזור (ROI)", "region"),
            ("🖼️ תמונת הדגמה", "demo"),
        ]
        for i, (label, key) in enumerate(actions):
            r, c = divmod(i, 2)
            btn = make_flat_button(
                grid, text=label, command=lambda k=key: self._select_quick_source(k),
                bg=CLR_BG_CARD, fg=CLR_TEXT_PRIMARY, hover_bg=CLR_BORDER, font=FONT_BODY, padx=6, pady=5
            )
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            self.source_buttons[key] = btn

    def _select_screen(self, idx: int) -> None:
        if self.app and hasattr(self.app, "select_monitor"): self.app.select_monitor(idx)
        self.highlight_source()

    def _select_quick_source(self, key: str) -> None:
        if self.app:
            if key == "zoom" and hasattr(self.app, "auto_detect_zoom"): self.app.auto_detect_zoom()
            elif key == "window" and hasattr(self.app, "open_window_picker"): self.app.open_window_picker()
            elif key == "region" and hasattr(self.app, "open_screen_roi_selector"): self.app.open_screen_roi_selector()
            elif key == "demo" and hasattr(self.app, "set_demo_mode"): self.app.set_demo_mode()
        self.highlight_source()

    def _build_presets_section(self, parent: tk.Widget) -> None:
        card = tk.LabelFrame(parent, text="  פרופילים מוכנים (Presets)  ", font=FONT_BODY_BOLD, bg=CLR_BG_PANEL, fg=CLR_ACCENT, bd=1, relief="solid", padx=10, pady=8)
        card.pack(fill=tk.X, pady=(0, 10))

        for key in ("clean_board", "ultra_bold", "color_markers", "dark_board", "raw_contrast"):
            info = PRESET_INFO.get(key, {})
            text = f"{info.get('icon', '✨')}  {info.get('name_he', key)}"
            btn = make_flat_button(card, text=text, command=lambda k=key: self.select_preset(k), bg=CLR_BG_CARD, fg=CLR_TEXT_PRIMARY, hover_bg=CLR_BORDER, font=FONT_BODY_BOLD, padx=8, pady=6)
            btn.pack(fill=tk.X, pady=2)
            self.preset_buttons[key] = btn

        d_box = tk.Frame(card, bg=CLR_BG_INPUT, padx=8, pady=6, bd=1, relief="solid")
        d_box.pack(fill=tk.X, pady=(8, 2))
        tk.Label(d_box, textvariable=self.preset_desc_var, font=FONT_SUBTITLE, bg=CLR_BG_INPUT, fg=CLR_TEXT_SECONDARY, wraplength=340, justify=tk.RIGHT).pack(fill=tk.X)

    def _build_sliders_section(self, parent: tk.Widget) -> None:
        card = tk.LabelFrame(parent, text="  כוונון עיבוד תמונה בזמן אמת  ", font=FONT_BODY_BOLD, bg=CLR_BG_PANEL, fg=CLR_ACCENT, bd=1, relief="solid", padx=10, pady=8)
        card.pack(fill=tk.X, pady=(0, 10))

        for key, title, min_val, max_val, step, fmt, _ in SLIDERS_META:
            var, lbl_var, _ = self._slider_vars[key]
            s_frame = tk.Frame(card, bg=CLR_BG_PANEL, pady=3)
            s_frame.pack(fill=tk.X)
            t_row = tk.Frame(s_frame, bg=CLR_BG_PANEL)
            t_row.pack(fill=tk.X)
            tk.Label(t_row, textvariable=lbl_var, font=FONT_MONO, bg=CLR_BG_CARD, fg=CLR_ACCENT, padx=6, pady=1, bd=1, relief="solid").pack(side=tk.LEFT)
            tk.Label(t_row, text=title, font=FONT_BODY, bg=CLR_BG_PANEL, fg=CLR_TEXT_PRIMARY).pack(side=tk.RIGHT)

            scale = tk.Scale(
                s_frame, from_=min_val, to=max_val, resolution=step, orient=tk.HORIZONTAL, variable=var,
                command=lambda val, k=key, f=fmt, lv=lbl_var: self._on_slider_change(k, val, f, lv),
                bg=CLR_BG_PANEL, troughcolor=CLR_BG_INPUT, activebackground=CLR_ACCENT, highlightthickness=0, bd=0, showvalue=False, sliderlength=18, sliderrelief="flat"
            )
            scale.pack(fill=tk.X, pady=(2, 4))
            self.slider_widgets[key] = scale

    def _build_toggles_section(self, parent: tk.Widget) -> None:
        card = tk.LabelFrame(parent, text="  אפשרויות מתקדמות  ", font=FONT_BODY_BOLD, bg=CLR_BG_PANEL, fg=CLR_ACCENT, bd=1, relief="solid", padx=10, pady=8)
        card.pack(fill=tk.X, pady=(0, 10))

        for key, text, _ in TOGGLES_META:
            tk.Checkbutton(
                card, text=text, variable=self._toggle_vars[key], command=lambda k=key: self._on_toggle_change(k),
                bg=CLR_BG_PANEL, fg=CLR_TEXT_PRIMARY, selectcolor=CLR_BG_INPUT, activebackground=CLR_BG_PANEL, activeforeground=CLR_ACCENT,
                font=FONT_BODY, anchor="e", justify=tk.RIGHT, pady=3
            ).pack(fill=tk.X)

    def _build_reset_section(self, parent: tk.Widget) -> None:
        btn_reset = make_flat_button(
            parent, text="🔄 איפוס להגדרות מומלצות (Reset)", command=self.reset_to_defaults,
            bg=CLR_BG_CARD, fg=CLR_ACCENT, hover_bg=CLR_BORDER, font=FONT_BODY_BOLD, padx=12, pady=8
        )
        btn_reset.pack(fill=tk.X, pady=(4, 10))

    def select_preset(self, preset_name: str) -> None:
        if preset_name not in PRESETS: return
        if self.app is not None and hasattr(self.app, "apply_preset"):
            self.app.apply_preset(preset_name, update_sliders=True)
        params = PRESETS[preset_name]
        for key, (var, lbl, fmt) in self._slider_vars.items():
            if hasattr(params, key):
                val = getattr(params, key); var.set(val); lbl.set(fmt.format(val))
        for key in ("preserve_instructor", "invert_dark_mode", "denoise", "fast_mode"):
            if hasattr(params, key) and key in self._toggle_vars:
                self._toggle_vars[key].set(getattr(params, key))
        self.highlight_preset(preset_name)
        self.preset_desc_var.set(PRESET_INFO.get(preset_name, {}).get("desc_he", ""))

    def highlight_preset(self, preset_name: str) -> None:
        for key, btn in self.preset_buttons.items():
            is_active = (key == preset_name)
            bg = CLR_ACCENT_BG if is_active else CLR_BG_CARD
            fg = "#FFFFFF" if is_active else CLR_TEXT_PRIMARY
            btn.config(bg=bg, fg=fg)
            btn._current_bg = bg
            btn._current_fg = fg

    def highlight_source(self) -> None:
        act_type = getattr(self.app, "active_source_type", "demo") if self.app else "demo"
        act_idx = getattr(self.app, "active_monitor_index", 0) if self.app else 0
        for idx, btn in self.monitor_buttons.items():
            is_active = (act_type == "screen" and act_idx == idx)
            bg, fg = (CLR_ACCENT_BG, "#FFFFFF") if is_active else (CLR_BG_CARD, CLR_TEXT_PRIMARY)
            btn.config(bg=bg, fg=fg); btn._current_bg, btn._current_fg = bg, fg
        for key, btn in self.source_buttons.items():
            is_active = (act_type == key)
            bg, fg = (CLR_ACCENT_BG, "#FFFFFF") if is_active else (CLR_BG_CARD, CLR_TEXT_PRIMARY)
            btn.config(bg=bg, fg=fg); btn._current_bg, btn._current_fg = bg, fg

    def _on_slider_change(self, key: str, val_str: str, fmt: str, lbl_var: tk.StringVar) -> None:
        try:
            val = float(val_str)
            lbl_var.set(fmt.format(val))
            if self.app is not None:
                if hasattr(self.app, "_on_slider_change"):
                    self.app._on_slider_change(key, val_str, fmt, lbl_var)
                elif hasattr(self.app, "current_params"):
                    setattr(self.app.current_params, key, val)
        except Exception:
            pass

    def _on_toggle_change(self, key: str) -> None:
        if self.app is None:
            return
        if key == "click_through":
            val = self._toggle_vars["click_through"].get()
            if hasattr(self.app, "set_click_through_mode"): self.app.set_click_through_mode(val)
            elif hasattr(self.app, "var_click_through"): self.app.var_click_through.set(val)
            return
        if key == "trim_browser_header":
            val = self._toggle_vars["trim_browser_header"].get()
            if hasattr(self.app, "capture_manager"): self.app.capture_manager.trim_browser_header = val
            if hasattr(self.app, "var_trim_browser_header"): self.app.var_trim_browser_header.set(val)
            if hasattr(self.app, "show_toast"): self.app.show_toast("✂️ הסתרת כרטיסיות דפדפן פעילה" if val else "כרטיסיות דפדפן גלויות")
            return
        if key == "fast_mode":
            val = self._toggle_vars["fast_mode"].get()
            if hasattr(self.app, "enhancer") and hasattr(self.app.enhancer, "fast_mode"): self.app.enhancer.fast_mode = val
            if hasattr(self.app, "fast_mode"): self.app.fast_mode = val
            if hasattr(self.app, "current_params") and hasattr(self.app.current_params, "fast_mode"): self.app.current_params.fast_mode = val
            if hasattr(self.app, "show_toast"): self.app.show_toast("⚡ מצב מהירות שיא (Turbo FPS) פעיל" if val else "מהירות שיא כבויה (איכות מקסימלית)")
            return

        if hasattr(self.app, "_on_toggle_change"):
            self.app._on_toggle_change(key)
        elif hasattr(self.app, "current_params") and hasattr(self.app.current_params, key):
            var = self._toggle_vars.get(key)
            if var:
                setattr(self.app.current_params, key, var.get())

    def reset_to_defaults(self) -> None:
        if self.app is not None and hasattr(self.app, "reset_to_defaults"):
            self.app.reset_to_defaults()
        self.select_preset("clean_board")

    def on_close(self) -> None:
        if self.app is not None:
            if getattr(self.app, "settings_window", None) is self:
                self.app.settings_window = None
            if hasattr(self.app, "save_settings"):
                self.app.save_settings()
        self.destroy()

    @classmethod
    def open_or_focus(cls, parent: Optional[tk.Widget] = None, app: Optional[Any] = None) -> "SettingsWindow":
        target_app = app if app is not None else (parent if hasattr(parent, "root") else None)
        if target_app and getattr(target_app, "settings_window", None):
            try:
                w = target_app.settings_window
                if w.winfo_exists():
                    w.deiconify(); w.attributes("-topmost", True); w.lift(); w.focus_force()
                    try: ctypes.windll.user32.BringWindowToTop(wintypes.HWND(w.winfo_id()))
                    except Exception: pass
                    return w
            except Exception: pass
        win = cls(parent, app)
        if target_app: target_app.settings_window = win
        return win

    @classmethod
    def toggle(cls, parent: Optional[tk.Widget] = None, app: Optional[Any] = None) -> Optional["SettingsWindow"]:
        target_app = app if app is not None else (parent if hasattr(parent, "root") else None)
        if target_app and getattr(target_app, "settings_window", None):
            try:
                if target_app.settings_window.winfo_exists():
                    target_app.settings_window.on_close()
                    return None
            except Exception:
                pass
        return cls.open_or_focus(parent, app)
