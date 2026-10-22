"""
Qboard Desktop Application (app.py)
===================================
Main application overlay controller for real-time Zoom & desktop whiteboard enhancement.
Orchestrates live screen capture, core image enhancement, interactive overlays,
and system hotkeys.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox, filedialog
from typing import Optional, Tuple, Dict, Any, List
from PIL import Image, ImageTk

# DPI awareness initialization
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

from core import (
    WhiteboardEnhancer,
    EnhancementParams,
    PRESETS,
    PRESET_INFO,
    detect_whiteboard_bbox,
)
from capture import (
    LiveCaptureManager,
    find_zoom_window,
    init_dpi_awareness,
    enum_display_monitors,
    MonitorInfo,
    bring_window_to_front,
    get_window_rect,
)
from services import SettingsManager, SnapshotService
from pipeline import FramePipeline
from ui.theme import (
    CLR_BG_ROOT,
    CLR_ACCENT,
    set_window_capture_passthrough,
    set_window_click_through,
)
from ui.canvas_renderer import CanvasRenderer
from ui.modals import (
    WindowPickerModal,
    ScreenRegionSelector,
    ScreenPickerModal,
    BoardPointSelector,
)
from ui.hotkeys import GlobalHotkeyManager, bind_local_shortcuts

logger = logging.getLogger("qboard")


class ZoomPlusApp:
    """Seamless, distraction-free Zoom whiteboard enhancement overlay."""

    def __init__(self, root: Optional[tk.Tk] = None, headless: bool = False) -> None:
        self.headless = headless
        self.root = tk.Tk() if root is None else root
        init_dpi_awareness()

        # Core engine and capture services
        self.enhancer = WhiteboardEnhancer()
        self.capture_manager = LiveCaptureManager(
            mode="screen" if not self.headless else "demo"
        )
        self.settings_manager = SettingsManager()

        # State variables
        self.current_preset: str = "clean_board"
        self.current_params: EnhancementParams = PRESETS["clean_board"].copy()
        self.view_mode: str = "enhanced"
        self.split_ratio: float = 0.50
        self.loupe_enabled: bool = False
        self.crop_mode: bool = False
        self.is_paused: bool = False
        self.overlay_visible: bool = not self.headless
        self.settings_window: Optional[Any] = None
        self.active_source_type: str = "screen" if not self.headless else "demo"
        self.active_monitor_index: int = 0
        self.click_through_enabled: bool = True

        # Frame sequence & rendering tracking
        self._frame_seq: int = 0
        self._rendered_frame_seq: int = -1
        self._last_locked_geometry: Optional[str] = None
        self._last_canvas_size: Optional[Tuple[int, int]] = (0, 0)
        self._crop_start: Optional[Tuple[int, int]] = None
        self._drag_start: Optional[Tuple[int, int, int, int]] = None
        self._resize_start: Optional[Tuple[int, int, int, int]] = None
        self._toast_message: Optional[str] = None
        self._toast_timer: Optional[str] = None

        # Frames
        self.current_frame_orig: Optional[Image.Image] = None
        self.current_frame_enhanced: Optional[Image.Image] = None
        self.current_processed_frame: Optional[Image.Image] = None

        # Metrics and widget maps
        self.latest_metrics: Dict[str, float] = {}
        self.preset_buttons: Dict[str, Any] = {}
        self.view_buttons: Dict[str, Any] = {}
        self.slider_widgets: Dict[str, Any] = {}

        # Configure root window
        self.root.title("Qboard Overlay")
        self.root.configure(bg=CLR_BG_ROOT)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        set_window_capture_passthrough(self.root, True)
        set_window_click_through(self.root, True)

        # Initialize UI and components
        self._init_variables()
        self._build_ui()
        self.renderer = CanvasRenderer(self.canvas)
        self._bind_canvas_events()
        bind_local_shortcuts(self)

        if not self.headless:
            self.select_monitor(0)
        else:
            self.snap_to_zoom_window()

        self.hotkey_mgr = GlobalHotkeyManager(self, poll_interval_ms=40)
        self.apply_preset("clean_board", update_sliders=True)

        if not self.headless:
            self.load_settings()

        if self.headless:
            self.root.withdraw()
        else:
            self.root.after(50, self._video_tick)
            self.hotkey_mgr.start()

    # --- Property bridges for CanvasRenderer compatibility ---

    @property
    def canvas_layout(self) -> Tuple[int, int, int, int, float]:
        return self.renderer.canvas_layout

    @canvas_layout.setter
    def canvas_layout(self, val: Tuple[int, int, int, int, float]) -> None:
        self.renderer.canvas_layout = val

    @property
    def current_tk_photo(self) -> Optional[ImageTk.PhotoImage]:
        return self.renderer.current_tk_photo

    @current_tk_photo.setter
    def current_tk_photo(self, val: Optional[ImageTk.PhotoImage]) -> None:
        self.renderer.current_tk_photo = val

    @property
    def loupe_tk_photo(self) -> Optional[ImageTk.PhotoImage]:
        return self.renderer.loupe_tk_photo

    @loupe_tk_photo.setter
    def loupe_tk_photo(self, val: Optional[ImageTk.PhotoImage]) -> None:
        self.renderer.loupe_tk_photo = val

    # --- Initialization helpers ---

    def _init_variables(self) -> None:
        p = self.current_params
        specs = [
            ("contrast", p.contrast, "{:.2f}"),
            ("thickening", p.thickening, "{:.2f}"),
            ("glare_removal", p.glare_removal, "{:.2f}"),
            ("shadow_suppression", getattr(p, "shadow_suppression", 0.85), "{:.2f}"),
            ("white_threshold", p.white_threshold, "{:.3f}"),
            ("ink_saturation", p.ink_saturation, "{:.3f}"),
            ("gamma", p.gamma, "{:.2f}"),
            ("sharpen", p.sharpen, "{:.1f}"),
        ]
        self._slider_map = {
            k: (tk.DoubleVar(value=v), tk.StringVar(value=f.format(v)), f)
            for k, v, f in specs
        }
        for k, (var, lbl, _) in self._slider_map.items():
            setattr(self, f"var_{k}", var)
            setattr(self, f"lbl_{k}_val", lbl)

        self.var_fast_mode = tk.BooleanVar(value=p.fast_mode)
        self.var_preserve_instructor = tk.BooleanVar(value=p.preserve_instructor)
        self.var_invert_dark_mode = tk.BooleanVar(value=p.invert_dark_mode)
        self.var_denoise = tk.BooleanVar(value=p.denoise)
        self.var_simulate_live = tk.BooleanVar(value=self.capture_manager.simulate_live)
        self.var_trim_browser_header = tk.BooleanVar(value=False)
        self.var_exclude_capture = tk.BooleanVar(value=True)
        self.var_always_on_top = tk.BooleanVar(value=False)
        self.var_click_through = tk.BooleanVar(value=True)

        self.stat_source = tk.StringVar(value="מקור: מסך נוכחי")
        self.stat_fps = tk.StringVar(value="⚡ 0.0 FPS")
        self.stat_latency = tk.StringVar(value="⏱️ 0.0ms")
        self.stat_whiteness = tk.StringVar(value="⚪ הלבנת רקע: --%")
        self.stat_contrast = tk.StringVar(value="📊 ניגודיות: --")
        self.stat_sharpness = tk.StringVar(value="✨ חדות: --")
        self.stat_toast = tk.StringVar(value="🟢 Qboard מוכן לשידור")
        self.preset_desc_var = tk.StringVar(
            value=PRESET_INFO["clean_board"]["desc_he"]
        )

    def _build_ui(self) -> None:
        self.canvas = tk.Canvas(
            self.root,
            bg=CLR_BG_ROOT,
            highlightthickness=0,
            bd=0,
            cursor="arrow",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    def _bind_canvas_events(self) -> None:
        self.canvas.bind("<Configure>", lambda e: self._render_current_frame_to_canvas())
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", lambda e: self.canvas.delete("loupe"))

    # --- Canvas Mouse Interaction ---

    def _on_canvas_press(self, event: tk.Event) -> None:
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if self.crop_mode:
            self._crop_start = (event.x, event.y)
            self.canvas.delete("crop_box")
        elif event.x >= cw - 24 and event.y >= ch - 24:
            self._resize_start = (
                event.x_root,
                event.y_root,
                self.root.winfo_width(),
                self.root.winfo_height(),
            )
        elif event.y <= 38:
            self._drag_start = (
                event.x_root,
                event.y_root,
                self.root.winfo_x(),
                self.root.winfo_y(),
            )
        elif self.view_mode == "split":
            self._update_split_from_canvas_x(event.x)

    def _on_canvas_drag(self, event: tk.Event) -> None:
        if self.crop_mode and self._crop_start:
            self.canvas.delete("crop_box")
            self.canvas.create_rectangle(
                *self._crop_start,
                event.x,
                event.y,
                outline=CLR_ACCENT,
                width=2,
                dash=(6, 4),
                tags="crop_box",
            )
        elif self._resize_start:
            rx, ry, rw, rh = self._resize_start
            self.root.geometry(
                f"{max(480, rw + (event.x_root - rx))}x{max(320, rh + (event.y_root - ry))}"
            )
        elif self._drag_start:
            sx, sy, wx, wy = self._drag_start
            self.root.geometry(f"+{wx + (event.x_root - sx)}+{wy + (event.y_root - sy)}")
        elif self.view_mode == "split":
            self._update_split_from_canvas_x(event.x)

    def _on_canvas_release(self, event: tk.Event) -> None:
        self._drag_start = None
        self._resize_start = None
        if self.crop_mode and self._crop_start:
            sx, sy = self._crop_start
            self._crop_start = None
            self.canvas.delete("crop_box")
            ox, oy, dw, dh, _ = self.canvas_layout
            if dw > 0 and dh > 0:
                x1 = max(0.0, min(1.0, (min(sx, event.x) - ox) / dw))
                y1 = max(0.0, min(1.0, (min(sy, event.y) - oy) / dh))
                x2 = max(0.0, min(1.0, (max(sx, event.x) - ox) / dw))
                y2 = max(0.0, min(1.0, (max(sy, event.y) - oy) / dh))
                if (x2 - x1) >= 0.05 and (y2 - y1) >= 0.05:
                    self.set_board_crop((x1, y1, x2, y2))
                    self.show_toast(
                        f"✂️ לוח נחתך ({int((x2-x1)*100)}% × {int((y2-y1)*100)}%)"
                    )
                else:
                    self.show_toast("חיתוך קטן מדי - בוטל")
            self.crop_mode = False
            self.canvas.config(cursor="arrow")

    def _on_canvas_motion(self, event: tk.Event) -> None:
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if self.crop_mode:
            self.canvas.config(cursor="cross")
        elif event.x >= cw - 24 and event.y >= ch - 24:
            self.canvas.config(cursor="size_nw_se")
        elif event.y <= 38:
            self.canvas.config(cursor="fleur")
        elif self.view_mode == "split":
            ox, _, dw, _, _ = self.canvas_layout
            split_pos = ox + int(dw * self.split_ratio)
            if abs(event.x - split_pos) < 15:
                self.canvas.config(cursor="sb_h_double_arrow")
            else:
                self.canvas.config(cursor="arrow")
        else:
            self.canvas.config(cursor="arrow")

        if self.loupe_enabled and not self.crop_mode:
            self.renderer.render_loupe(self.current_processed_frame, event.x, event.y)
        else:
            self.canvas.delete("loupe")

    def _update_split_from_canvas_x(self, cx: int) -> None:
        ox, _, dw, _, _ = self.canvas_layout
        if dw > 10:
            self.split_ratio = max(0.05, min(0.95, (cx - ox) / float(dw)))
            if self.current_frame_orig and self.current_frame_enhanced:
                self.current_processed_frame = self.enhancer.create_comparison_view(
                    self.current_frame_orig,
                    self.current_frame_enhanced,
                    self.split_ratio,
                )
                self._render_current_frame_to_canvas()

    # --- Toast & Rendering ---

    def show_toast(self, message: str) -> None:
        self._toast_message = message
        self.stat_toast.set(message)
        if self._toast_timer and self.root.winfo_exists():
            try:
                self.root.after_cancel(self._toast_timer)
            except Exception:
                pass
            self._toast_timer = None
        self.renderer.render_toast(message)
        if not self.headless and self.root.winfo_exists():
            self._toast_timer = self.root.after(2500, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_message = None
        self._toast_timer = None
        if self.canvas.winfo_exists():
            self.canvas.delete("toast")

    def _render_current_frame_to_canvas(self) -> None:
        self.renderer.render_frame(
            processed_frame=self.current_processed_frame,
            frame_seq=self._frame_seq,
            view_mode=self.view_mode,
            split_ratio=self.split_ratio,
            toast_message=self._toast_message,
            last_frame_was_cached=getattr(self.enhancer, "last_frame_was_cached", False),
        )

    # --- Video Loop ---

    def process_single_frame(self) -> None:
        self._frame_seq += 1
        raw_frame = self.capture_manager.capture_frame()
        self.current_frame_orig = raw_frame

        if self.view_mode == "original":
            self.current_frame_enhanced = None
            self.current_processed_frame = raw_frame
        else:
            self.current_frame_enhanced = self.enhancer.enhance(
                raw_frame, self.current_params
            )
            if self.view_mode == "split":
                self.current_processed_frame = self.enhancer.create_comparison_view(
                    raw_frame, self.current_frame_enhanced, self.split_ratio
                )
            else:
                self.current_processed_frame = self.current_frame_enhanced

        if (
            self.current_frame_orig
            and self.current_frame_enhanced
            and (self.capture_manager.frame_count % 15 == 0)
        ):
            m = self.enhancer.compute_metrics(
                self.current_frame_orig, self.current_frame_enhanced
            )
            self.latest_metrics = m
            self.stat_whiteness.set(f"⚪ הלבנת רקע: {m['background_whiteness_pct']}%")
            self.stat_contrast.set(f"📊 ניגודיות: x{m['contrast_improvement']}")
            self.stat_sharpness.set(f"✨ חדות: x{m['sharpness_improvement']}")

        stats = self.capture_manager.get_stats()
        self.stat_fps.set(f"⚡ {stats['fps']} FPS")
        self.stat_latency.set(
            f"⏱️ לכידה: {stats['latency_ms']:.1f}ms | עיבוד: {self.enhancer.last_processing_time_ms:.1f}ms"
        )

        if not self.headless:
            self._render_current_frame_to_canvas()

    def _pipeline_capture_fn(self) -> Optional[Image.Image]:
        return self.capture_manager.capture_frame()

    def _pipeline_process_fn(self, raw_frame: Image.Image) -> Optional[Image.Image]:
        if self.view_mode == "original":
            return raw_frame
        enhanced = self.enhancer.enhance(raw_frame, self.current_params)
        if self.view_mode == "split":
            return self.enhancer.create_comparison_view(
                raw_frame, enhanced, self.split_ratio
            )
        return enhanced

    def _video_tick(self) -> None:
        if not self.overlay_visible:
            if not self.headless and self.root.winfo_exists():
                self.root.after(200, self._video_tick)
            return

        if not self.is_paused:
            try:
                self.process_single_frame()
            except Exception as e:
                logger.error(f"Frame error: {e}")

        if not self.headless and self.root.winfo_exists():
            self.root.after(16, self._video_tick)

    # --- Presets & Parameters ---

    def apply_preset(self, preset_name: str, update_sliders: bool = True) -> None:
        if preset_name not in PRESETS:
            return
        self.current_preset = preset_name
        self.current_params = PRESETS[preset_name].copy()
        info = PRESET_INFO.get(preset_name, {})
        self.preset_desc_var.set(info.get("desc_he", ""))

        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_preset(preset_name)

        if update_sliders:
            p = self.current_params
            for k, (var, lbl, fmt) in self._slider_map.items():
                v = getattr(p, k)
                var.set(v)
                lbl.set(fmt.format(v))
            self.var_preserve_instructor.set(p.preserve_instructor)
            self.var_invert_dark_mode.set(p.invert_dark_mode)
            self.var_denoise.set(p.denoise)

        if self.is_paused and self.current_frame_orig:
            self.process_single_frame()

        self.show_toast(f"הופעל פרופיל: {info.get('name_he', preset_name)}")

    def cycle_next_preset(self) -> None:
        keys = ("clean_board", "ultra_bold", "color_markers", "dark_board", "custom")
        if self.current_preset in keys:
            next_idx = (keys.index(self.current_preset) + 1) % len(keys)
            next_key = keys[next_idx]
        else:
            next_key = keys[0]
        self.apply_preset(next_key, update_sliders=True)

    def update_param_from_slider(self, key: str, val: float) -> None:
        if hasattr(self.current_params, key):
            setattr(self.current_params, key, val)
        if key in self._slider_map:
            var, lbl, fmt = self._slider_map[key]
            var.set(val)
            lbl.set(fmt.format(val))

    def _on_slider_change(self, key: str, val_str: str, fmt: str, lbl_var: tk.StringVar) -> None:
        try:
            val = float(val_str)
            lbl_var.set(fmt.format(val))
            setattr(self.current_params, key, val)
            if self.is_paused and self.current_frame_orig:
                self.process_single_frame()
        except Exception:
            pass

    def _on_toggle_change(self, key: str) -> None:
        if key == "exclude_capture":
            val = self.var_exclude_capture.get()
            if not val:
                self.capture_manager.anti_mirror_frozen = True
                set_window_capture_passthrough(self.root, False)
                self.show_toast("✂️ מניעת צילום כבויה (הפריים הוקפא למניעת שכפול מסך)")
            else:
                self.capture_manager.anti_mirror_frozen = False
                set_window_capture_passthrough(self.root, True)
                self.show_toast("👻 מניעת צילום עצמי פעילה")
        elif key == "click_through":
            self.set_click_through_mode(self.var_click_through.get())
        elif key == "always_on_top":
            val = self.var_always_on_top.get()
            self.root.attributes("-topmost", val)
            self.show_toast("📌 נעוץ מעל כל החלונות" if val else "🔓 ביטול נעיצה")
        elif key == "trim_browser_header":
            val = self.var_trim_browser_header.get()
            self.capture_manager.trim_browser_header = val
            self.show_toast(
                "✂️ הסתרת כרטיסיות דפדפן פעילה" if val else "כרטיסיות דפדפן גלויות"
            )
        elif hasattr(self.current_params, key):
            setattr(self.current_params, key, getattr(self, f"var_{key}").get())
        elif key == "simulate_live":
            self.capture_manager.simulate_live = self.var_simulate_live.get()

    def reset_to_defaults(self) -> None:
        self.apply_preset("clean_board", update_sliders=True)
        self.show_toast("🔄 אופסו כל הפרמטרים להגדרות המומלצות")

    def set_view_mode(self, mode: str) -> None:
        if mode in ("enhanced", "split", "original"):
            self.view_mode = mode
            if self.current_frame_orig:
                self.process_single_frame()

    # --- Windows & Monitors Snapping ---

    def snap_to_zoom_window(self) -> bool:
        win = find_zoom_window()
        if win and win.width >= 200 and win.height >= 200:
            self.root.geometry(f"{win.width}x{win.height}+{win.rect[0]}+{win.rect[1]}")
            return True
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = min(1280, max(640, sw - 100))
            h = min(720, max(480, sh - 100))
            self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        except Exception:
            self.root.geometry("1280x720+100+100")
        return False

    def snap_to_window(self, hwnd: int) -> bool:
        rect = get_window_rect(hwnd)
        if rect and (rect[2] - rect[0]) >= 200 and (rect[3] - rect[1]) >= 150:
            self.root.geometry(f"{rect[2]-rect[0]}x{rect[3]-rect[1]}+{rect[0]}+{rect[1]}")
            return True
        return False

    def snap_to_monitor(self, monitor_index: int) -> bool:
        mons = enum_display_monitors()
        if 0 <= monitor_index < len(mons):
            m = mons[monitor_index]
            self.root.geometry(f"{m.width}x{m.height}+{m.rect[0]}+{m.rect[1]}")
            return True
        return False

    def select_monitor(self, monitor_index: int = 0) -> None:
        self.capture_manager.set_region(None)
        self.capture_manager.set_board_crop(None)
        mon = self.capture_manager.set_target_screen(monitor_index)
        self.snap_to_monitor(monitor_index)
        self.active_source_type = "screen"
        self.active_monitor_index = mon.index
        self.view_mode = "enhanced"
        self.stat_source.set(f"מקור: מסך {mon.index + 1} ({mon.width}×{mon.height})")
        self.show_toast(
            f"🖥️ הופעל על מסך {mon.index + 1} ({mon.width}×{mon.height}{' - ראשי' if mon.is_primary else ''})"
        )
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_source()
        self.overlay_visible = True
        if not self.headless and self.root.winfo_exists():
            self.root.deiconify()
            self.root.lift()

    def cycle_screen_source(self) -> None:
        mons = enum_display_monitors()
        if self.active_source_type != "screen":
            self.select_monitor(0)
        elif len(mons) > 1:
            self.select_monitor((self.active_monitor_index + 1) % len(mons))
        else:
            self.select_monitor(0)
            if mons:
                self.show_toast(f"🖥️ מסך 1 פעיל ({mons[0].width}×{mons[0].height}) - לכידה חיה")
        self.overlay_visible = True
        if not self.headless and self.root.winfo_exists():
            self.root.deiconify()
            self.root.lift()

    def open_screen_picker(self) -> None:
        ScreenPickerModal(
            self.root,
            self._on_screen_picker_selected,
            current_source=self.active_source_type,
            current_index=self.active_monitor_index,
        )

    def _on_screen_picker_selected(self, source_type: str, arg: Any = None) -> None:
        if source_type == "screen":
            self.select_monitor(arg if arg is not None else 0)
        elif source_type == "zoom":
            self.auto_detect_zoom()
        elif source_type == "window_picker":
            self.open_window_picker()
        elif source_type == "roi":
            self.open_screen_roi_selector()
        elif source_type == "demo":
            self.set_demo_mode()

    def auto_detect_zoom(self) -> bool:
        win = find_zoom_window()
        if win:
            self.active_source_type = "zoom"
            self.capture_manager.set_target_window(win.hwnd)
            self.stat_source.set(f"מקור: זום - {win.title[:24]} ({win.width}×{win.height})")
            self.show_toast(f"🎯 זוהה חלון זום: {win.title[:30]}")
        else:
            self.show_toast("⚠️ לא נמצא חלון זום פעיל")
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_source()
        return bool(win)

    def open_window_picker(self) -> None:
        WindowPickerModal(self.root, self._on_window_selected)

    def _on_window_selected(self, hwnd: int, title: str) -> None:
        bring_window_to_front(hwnd)
        self.snap_to_window(hwnd)
        self.active_source_type = "window"
        self.capture_manager.set_target_window(hwnd)
        if any(b in title.lower() for b in ("chrome", "edge", "brave", "firefox")):
            self.capture_manager.trim_browser_header = self.var_trim_browser_header.get()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.stat_source.set(f"מקור: {title[:24]}")
        self.show_toast(f"🪟 חלון נבחר: {title[:24]} (לכידה ישירה)")
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_source()

    def open_screen_roi_selector(self) -> None:
        ScreenRegionSelector(self.root, self._on_region_selected)

    def _on_region_selected(self, bbox: Tuple[int, int, int, int]) -> None:
        self.active_source_type = "region"
        self.capture_manager.set_region(bbox)
        self.stat_source.set(f"מקור: אזור מסך ({bbox[2]-bbox[0]}×{bbox[3]-bbox[1]})")
        self.show_toast(f"📐 נבחר אזור: {bbox[2]-bbox[0]} × {bbox[3]-bbox[1]}")
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_source()

    def open_board_point_selector(self) -> None:
        self.root.withdraw()
        self.root.after(80, lambda: BoardPointSelector(self.root, self._on_board_points_selected))

    def _on_board_points_selected(self, bbox: Tuple[int, int, int, int]) -> None:
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        self._last_locked_geometry = f"{w}x{h}+{bbox[0]}+{bbox[1]}"
        self.capture_manager.set_region(bbox)
        self.capture_manager.set_board_crop(None)
        self.root.geometry(self._last_locked_geometry)
        self.active_source_type = "region"
        self.view_mode = "enhanced"
        self.overlay_visible = True
        if not self.headless and self.root.winfo_exists():
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
        set_window_click_through(self.root, self.click_through_enabled)
        self.stat_source.set(f"מקור: לוח נעול בנקודות ({w}×{h})")
        self.show_toast(f"📍 הפילטר ננעל על הלוח בלבד! ({w}×{h}) - מהירות שיא")
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_source()
        self.save_settings()

    def auto_detect_board_region(self) -> Optional[Tuple[int, int, int, int]]:
        if self.capture_manager.mode == "demo":
            raw = self.capture_manager.capture_frame()
            w, h = raw.size
            nx1, ny1, nx2, ny2 = self.enhancer.detect_whiteboard_bbox(raw)
            bx1, by1, bx2, by2 = int(nx1 * w), int(ny1 * h), int(nx2 * w), int(ny2 * h)
            self.set_board_crop((nx1, ny1, nx2, ny2))
            self._last_locked_geometry = f"{bx2-bx1}x{by2-by1}+100+100"
            self.show_toast(
                f"🤖 הלוח זוהה אוטומטית בעיבוד תמונה! ({int((nx2-nx1)*100)}%×{int((ny2-ny1)*100)}%)"
            )
            return (bx1, by1, bx2, by2)

        rect = None
        if self.capture_manager.mode == "window" and self.capture_manager.hwnd:
            rect = get_window_rect(self.capture_manager.hwnd)
        if not rect:
            mons = enum_display_monitors()
            if mons and self.active_monitor_index < len(mons):
                rect = mons[self.active_monitor_index].rect
            else:
                rect = (0, 0, 1920, 1080)

        rx1, ry1, rx2, ry2 = rect
        try:
            from PIL import ImageGrab
            ref = ImageGrab.grab(bbox=(rx1, ry1, rx2, ry2), all_screens=True)
        except Exception:
            ref = self.capture_manager.capture_frame()

        nx1, ny1, nx2, ny2 = self.enhancer.detect_whiteboard_bbox(ref)
        bx1 = rx1 + int(nx1 * (rx2 - rx1))
        by1 = ry1 + int(ny1 * (ry2 - ry1))
        bx2 = rx1 + int(nx2 * (rx2 - rx1))
        by2 = ry1 + int(ny2 * (ry2 - ry1))
        self._on_board_points_selected((bx1, by1, bx2, by2))
        self.show_toast(f"🤖 הלוח זוהה אוטומטית! ({bx2-bx1}×{by2-by1}) - פילטר ממוקד")
        return (bx1, by1, bx2, by2)

    def set_demo_mode(self) -> None:
        self.active_source_type = "demo"
        self.capture_manager.set_mode("demo")
        self.stat_source.set("מקור: הדגמה חיה (1024x575)")
        self.show_toast("🖼️ הופעל מצב הדגמה")
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.highlight_source()

    def load_custom_image(self) -> None:
        fp = filedialog.askopenfilename(
            title="בחר תמונת לוח",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.webp")],
        )
        if fp and os.path.isfile(fp):
            if self.capture_manager.load_demo_image(fp):
                self.capture_manager.set_mode("demo")
                self.stat_source.set(f"מקור: {os.path.basename(fp)[:24]}")
                self.show_toast(f"📂 נטענה: {os.path.basename(fp)}")
            else:
                messagebox.showerror("שגיאה", "טעינת הקובץ נכשלה.")

    # --- Tooling, Crop & Loupe ---

    def toggle_loupe(self) -> None:
        self.loupe_enabled = not self.loupe_enabled
        if not self.loupe_enabled:
            self.canvas.delete("loupe")
        self.show_toast(
            "🔍 זכוכית מגדלת 2.5x פעילה" if self.loupe_enabled else "זכוכית מגדלת כבויה"
        )

    def toggle_crop_mode(self) -> None:
        self.crop_mode = not self.crop_mode
        self.canvas.config(cursor="cross" if self.crop_mode else "arrow")
        if self.crop_mode:
            self.show_toast("✂️ גרור מלבן עם העכבר על גבי הלוח לבידוד אזור")

    def set_board_crop(self, crop_norm: Optional[Tuple[float, float, float, float]]) -> None:
        self.capture_manager.set_board_crop(crop_norm)

    def reset_board_crop(self) -> None:
        self.set_board_crop(None)
        self.show_toast("🔄 חיתוך הלוח בוטל - מוצג פריים מלא")

    def toggle_pause(self) -> None:
        if getattr(self.capture_manager, "anti_mirror_frozen", False):
            self.exit_snipping_tool_mode()
            return
        self.is_paused = not self.is_paused
        if hasattr(self, "pipeline"):
            if self.is_paused:
                self.pipeline.pause()
            else:
                self.pipeline.resume()
        self.show_toast("⏸️ השידור הושהה" if self.is_paused else "▶️ שידור חי נמשך")

    # --- Snipping Tool & Anti-Mirror Safeguards ---

    def enter_snipping_tool_mode(self) -> None:
        self.capture_manager.anti_mirror_frozen = True
        self.is_paused = True
        if hasattr(self, "pipeline"):
            self.pipeline.pause()
        set_window_capture_passthrough(self.root, False)
        self.show_toast(
            "✂️ מסך הוקפא וגלוי ל-Win+Shift+S! לחץ רווח או F11 לחזרה לשידור חי"
        )

    def exit_snipping_tool_mode(self) -> None:
        set_window_capture_passthrough(self.root, True)
        self.capture_manager.anti_mirror_frozen = False
        self.is_paused = False
        if hasattr(self, "pipeline"):
            self.pipeline.resume()
        self.show_toast("▶️ הגנת מניעת צילום שוחזרה - שידור חי נמשך")

    def toggle_snipping_tool_mode(self) -> None:
        if getattr(self.capture_manager, "anti_mirror_frozen", False):
            self.exit_snipping_tool_mode()
        else:
            self.enter_snipping_tool_mode()

    def toggle_capture_passthrough(self) -> None:
        self.var_exclude_capture.set(not self.var_exclude_capture.get())
        self._on_toggle_change("exclude_capture")

    def toggle_always_on_top(self) -> None:
        st = not self.var_always_on_top.get()
        self.var_always_on_top.set(st)
        self.root.attributes("-topmost", st)
        self.show_toast("📌 נעוץ מעל כל החלונות" if st else "🔓 ביטול נעיצה")

    def toggle_trim_browser_header(self) -> None:
        st = not self.var_trim_browser_header.get()
        self.var_trim_browser_header.set(st)
        self.capture_manager.trim_browser_header = st
        self.show_toast(
            "✂️ הסתרת כרטיסיות דפדפן פעילה" if st else "כרטיסיות דפדפן גלויות"
        )

    def set_click_through_mode(self, enabled: bool) -> None:
        self.click_through_enabled = enabled
        self.var_click_through.set(enabled)
        set_window_click_through(self.root, enabled)
        self.show_toast(
            "🖱️ שקוף לזום: לחיצות ומקש רווח פעילים"
            if enabled
            else "✋ מצב עכבר: ניתן לגרור סרגל השוואה"
        )

    def toggle_click_through(self) -> None:
        self.set_click_through_mode(not self.click_through_enabled)

    # --- Snapshots & Exports ---

    def save_composite_snapshot(self, out_dir: Optional[str] = None) -> str:
        return SnapshotService.save_composite_snapshot(self, out_dir)

    def save_snapshot(self, out_dir: Optional[str] = None) -> str:
        return self.save_composite_snapshot(out_dir)

    def quick_snapshot(self) -> str:
        saved = self.save_snapshot()
        self.show_toast(f"📸 נשמר צילום לוח [F8]: {os.path.basename(saved)}")
        return saved

    def open_captures_folder(self) -> None:
        SnapshotService.open_captures_folder()
        self.show_toast("📁 נפתחה תיקיית הצילומים captures/")

    # --- Hotkey Actions & Overlays ---

    def hotkey_toggle_zoom_overlay(self) -> None:
        if self.root.winfo_viewable() and self.overlay_visible:
            self.overlay_visible = False
            self.root.withdraw()
            if self.settings_window and self.settings_window.winfo_exists():
                try:
                    self.settings_window.withdraw()
                except Exception:
                    pass
        else:
            self.overlay_visible = True
            if self.active_source_type == "region" and getattr(self, "_last_locked_geometry", None):
                self.root.geometry(self._last_locked_geometry)
            elif self.active_source_type == "screen":
                self.snap_to_monitor(self.active_monitor_index)
            elif self.active_source_type == "window" and self.capture_manager.hwnd:
                self.snap_to_window(self.capture_manager.hwnd)
            else:
                self.snap_to_zoom_window()
                self.auto_detect_zoom()

            self.view_mode = "enhanced"
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            set_window_click_through(self.root, self.click_through_enabled)

            if self.capture_manager.hwnd:
                try:
                    ctypes.windll.user32.SetForegroundWindow(
                        wintypes.HWND(self.capture_manager.hwnd)
                    )
                except Exception:
                    pass
            self.show_toast("✨ מסנן Qboard הופעל (F9 לכיבוי)")

    def toggle_settings_window(self) -> None:
        from ui.settings_window import SettingsWindow
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.on_close()
        else:
            sw = SettingsWindow.open_or_focus(self.root, self)
            sw.attributes("-topmost", True)
            sw.lift()
            sw.focus_force()

    def save_custom_preset(self) -> None:
        self.settings_manager.save_custom_preset(self)
        self.show_toast("💾 ההגדרות נשמרו בהצלחה כפרופיל מותאם אישית לפעם הבאה!")
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.select_preset("custom")

    def load_settings(self) -> None:
        self.settings_manager.load_settings(self)

    def save_settings(self) -> None:
        self.settings_manager.save_settings(self)

    def quit_app(self) -> None:
        try:
            self.save_settings()
            if hasattr(self, "pipeline"):
                self.pipeline.stop()
            self.hotkey_mgr.stop()
            if self.settings_window and self.settings_window.winfo_exists():
                self.settings_window.destroy()
            self.root.destroy()
        except Exception:
            pass

    def _on_escape(self) -> None:
        if self.crop_mode:
            self.toggle_crop_mode()
            return
        if self.loupe_enabled:
            self.toggle_loupe()
            return
        if self.settings_window and self.settings_window.winfo_exists():
            try:
                self.settings_window.on_close()
                return
            except Exception:
                pass
        self.overlay_visible = False
        self.root.withdraw()

    # Aliases
    toggle_quick_launch = hotkey_toggle_zoom_overlay
    toggle_settings = toggle_settings_window
    cycle_preset = cycle_next_preset
    hotkey_quick_snapshot = quick_snapshot

    def run(self) -> None:
        self.root.mainloop()


QboardApp = ZoomPlusApp


def run_self_test(*args: Any, **kwargs: Any) -> int:
    import tests_runner
    return tests_runner.run_self_test(*args, **kwargs)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    else:
        ZoomPlusApp().run()
