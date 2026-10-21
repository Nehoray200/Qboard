"""Qboard Seamless Whiteboard Overlay Application (app.py)"""
from __future__ import annotations
import os, sys, time, json, logging, ctypes; from ctypes import wintypes
from datetime import datetime; from typing import Optional, Tuple, Dict, Any, List
import tkinter as tk; from tkinter import messagebox, filedialog
from PIL import Image, ImageTk, ImageDraw, ImageGrab
from processor import WhiteboardEnhancer, EnhancementParams, PRESETS, PRESET_INFO, detect_whiteboard_bbox
from capture import (LiveCaptureManager, find_zoom_window, init_dpi_awareness, enum_display_monitors,
                    MonitorInfo, bring_window_to_front, get_window_rect)
from ui.theme import (CLR_BG_ROOT, CLR_BG_TOOLBAR, CLR_BORDER, CLR_ACCENT, CLR_TEXT_MUTED,
                     FONT_FAMILY, FONT_BODY_BOLD, FONT_BADGE, set_window_capture_passthrough, set_window_click_through)
from ui.modals import WindowPickerModal, ScreenRegionSelector, ScreenPickerModal, BoardPointSelector
from ui.hotkeys import GlobalHotkeyManager, bind_local_shortcuts
from pipeline import FramePipeline

def _get_app_dir() -> str:
    for c in (os.path.join(os.environ.get("APPDATA") or "", "Qboard"), os.path.join(os.path.expanduser("~"), ".qboard"),
              os.path.join(os.getcwd(), ".qboard"), os.path.join(os.environ.get("APPDATA") or "", "ZoomPlus")):
        if c:
            try:
                os.makedirs(c, exist_ok=True)
                t = os.path.join(c, ".w"); open(t, "w").close(); os.remove(t); return c
            except Exception: pass
    return os.getcwd()
_app_data_dir = _get_app_dir()
try: logging.basicConfig(filename=os.path.join(_app_data_dir, "qboard.log"), level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
except Exception: pass
logger, _SETTINGS_FILE = logging.getLogger("qboard"), os.path.join(_app_data_dir, "settings.json")


class ZoomPlusApp:
    """Seamless, distraction-free Zoom whiteboard enhancement overlay."""

    def __init__(self, root: Optional[tk.Tk] = None, headless: bool = False) -> None:
        self.headless, self.root = headless, (tk.Tk() if root is None else root)
        init_dpi_awareness(); self.enhancer = WhiteboardEnhancer()
        self.capture_manager = LiveCaptureManager(mode="screen" if not self.headless else "demo")
        self.current_preset, self.current_params = "clean_board", PRESETS["clean_board"].copy()
        self.view_mode, self.split_ratio, self.loupe_enabled, self.crop_mode, self.is_paused = "enhanced", 0.50, False, False, False
        self.overlay_visible, self.settings_window = not self.headless, None
        self.active_source_type, self.active_monitor_index = ("screen" if not self.headless else "demo"), 0
        self.click_through_enabled, self._frame_seq, self._rendered_frame_seq = True, 0, -1
        self._last_locked_geometry, self._last_canvas_size, self._crop_start, self._drag_start, self._resize_start = None, (0, 0), None, None, None
        self._toast_message, self._toast_timer, self.current_frame_orig, self.current_frame_enhanced = None, None, None, None
        self.current_processed_frame, self.current_tk_photo, self.loupe_tk_photo = None, None, None
        self.canvas_layout, self.latest_metrics, self.preset_buttons, self.view_buttons, self.slider_widgets = (0, 0, 800, 450, 1.0), {}, {}, {}, {}

        self.root.title("Qboard Overlay"); self.root.configure(bg=CLR_BG_ROOT); self.root.overrideredirect(True); self.root.attributes("-topmost", True)
        set_window_capture_passthrough(self.root, True); set_window_click_through(self.root, True)
        self._init_variables(); self._build_ui(); self._bind_canvas_events(); bind_local_shortcuts(self)
        self.select_monitor(0) if not self.headless else self.snap_to_zoom_window()
        self.hotkey_mgr = GlobalHotkeyManager(self, poll_interval_ms=40)
        self.apply_preset("clean_board", update_sliders=True)
        if not self.headless: self.load_settings()
        self.pipeline = FramePipeline(self.capture_manager.capture_frame, lambda f: self.enhancer.enhance(f, self.current_params))
        if self.headless: self.root.withdraw()
        else: self.pipeline.start(); self.root.after(40, self._video_tick); self.hotkey_mgr.start()

    def _init_variables(self) -> None:
        p = self.current_params
        specs = [("contrast", p.contrast, "{:.2f}"), ("thickening", p.thickening, "{:.2f}"),
                 ("glare_removal", p.glare_removal, "{:.2f}"), ("white_threshold", p.white_threshold, "{:.3f}"),
                 ("ink_saturation", p.ink_saturation, "{:.3f}"), ("gamma", p.gamma, "{:.2f}"), ("sharpen", p.sharpen, "{:.1f}")]
        self._slider_map = {k: (tk.DoubleVar(value=v), tk.StringVar(value=f.format(v)), f) for k, v, f in specs}
        for k, (var, lbl, _) in self._slider_map.items(): setattr(self, f"var_{k}", var); setattr(self, f"lbl_{k}_val", lbl)
        self.var_fast_mode, self.var_preserve_instructor, self.var_invert_dark_mode = tk.BooleanVar(value=p.fast_mode), tk.BooleanVar(value=p.preserve_instructor), tk.BooleanVar(value=p.invert_dark_mode)
        self.var_denoise, self.var_simulate_live, self.var_trim_browser_header = tk.BooleanVar(value=p.denoise), tk.BooleanVar(value=self.capture_manager.simulate_live), tk.BooleanVar(value=False)
        self.var_exclude_capture, self.var_always_on_top, self.var_click_through = tk.BooleanVar(value=True), tk.BooleanVar(value=False), tk.BooleanVar(value=True)
        self.stat_source, self.stat_fps, self.stat_latency = tk.StringVar(value="מקור: מסך נוכחי"), tk.StringVar(value="⚡ 0.0 FPS"), tk.StringVar(value="⏱️ 0.0ms")
        self.stat_whiteness, self.stat_contrast, self.stat_sharpness = tk.StringVar(value="⚪ הלבנת רקע: --%"), tk.StringVar(value="📊 ניגודיות: --"), tk.StringVar(value="✨ חדות: --")
        self.stat_toast, self.preset_desc_var = tk.StringVar(value="🟢 Qboard מוכן לשידור"), tk.StringVar(value=PRESET_INFO["clean_board"]["desc_he"])

    def _build_ui(self) -> None:
        self.canvas = tk.Canvas(self.root, bg=CLR_BG_ROOT, highlightthickness=0, bd=0, cursor="arrow")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    def _bind_canvas_events(self) -> None:
        self.canvas.bind("<Configure>", lambda e: self._render_current_frame_to_canvas())
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press); self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release); self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", lambda e: self.canvas.delete("loupe"))

    def snap_to_zoom_window(self) -> bool:
        """Snap overlay geometry to match target Zoom window bounds exactly."""
        win = find_zoom_window()
        if win and win.width >= 200 and win.height >= 200:
            self.root.geometry(f"{win.width}x{win.height}+{win.rect[0]}+{win.rect[1]}"); return True
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w, h = min(1280, max(640, sw - 100)), min(720, max(480, sh - 100))
            self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        except Exception: self.root.geometry("1280x720+100+100")
        return False

    def snap_to_window(self, hwnd: int) -> bool:
        """Snap overlay geometry to match target window coordinates."""
        rect = get_window_rect(hwnd)
        if rect and (rect[2] - rect[0]) >= 200 and (rect[3] - rect[1]) >= 150:
            self.root.geometry(f"{rect[2]-rect[0]}x{rect[3]-rect[1]}+{rect[0]}+{rect[1]}"); return True
        return False

    def _on_canvas_press(self, event: tk.Event) -> None:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.crop_mode: self._crop_start = (event.x, event.y); self.canvas.delete("crop_box")
        elif event.x >= cw - 24 and event.y >= ch - 24: self._resize_start = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())
        elif event.y <= 38: self._drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        elif self.view_mode == "split": self._update_split_from_canvas_x(event.x)

    def _on_canvas_drag(self, event: tk.Event) -> None:
        if self.crop_mode and self._crop_start:
            self.canvas.delete("crop_box"); self.canvas.create_rectangle(*self._crop_start, event.x, event.y, outline=CLR_ACCENT, width=2, dash=(6, 4), tags="crop_box")
        elif self._resize_start:
            rx, ry, rw, rh = self._resize_start; self.root.geometry(f"{max(480, rw + (event.x_root - rx))}x{max(320, rh + (event.y_root - ry))}")
        elif self._drag_start:
            sx, sy, wx, wy = self._drag_start; self.root.geometry(f"+{wx + (event.x_root - sx)}+{wy + (event.y_root - sy)}")
        elif self.view_mode == "split": self._update_split_from_canvas_x(event.x)

    def _on_canvas_release(self, event: tk.Event) -> None:
        self._drag_start, self._resize_start = None, None
        if self.crop_mode and self._crop_start:
            sx, sy = self._crop_start; self._crop_start = None; self.canvas.delete("crop_box")
            ox, oy, dw, dh, _ = self.canvas_layout
            if dw > 0 and dh > 0:
                x1, y1 = max(0.0, min(1.0, (min(sx, event.x) - ox) / dw)), max(0.0, min(1.0, (min(sy, event.y) - oy) / dh))
                x2, y2 = max(0.0, min(1.0, (max(sx, event.x) - ox) / dw)), max(0.0, min(1.0, (max(sy, event.y) - oy) / dh))
                if (x2 - x1) >= 0.05 and (y2 - y1) >= 0.05:
                    self.set_board_crop((x1, y1, x2, y2)); self.show_toast(f"✂️ לוח נחתך ({int((x2-x1)*100)}% × {int((y2-y1)*100)}%)")
                else: self.show_toast("חיתוך קטן מדי - בוטל")
            self.crop_mode = False; self.canvas.config(cursor="arrow")

    def _on_canvas_motion(self, event: tk.Event) -> None:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.crop_mode: self.canvas.config(cursor="cross")
        elif event.x >= cw - 24 and event.y >= ch - 24: self.canvas.config(cursor="size_nw_se")
        elif event.y <= 38: self.canvas.config(cursor="fleur")
        elif self.view_mode == "split":
            ox, _, dw, _, _ = self.canvas_layout
            self.canvas.config(cursor="sb_h_double_arrow" if abs(event.x - (ox + int(dw * self.split_ratio))) < 15 else "arrow")
        else: self.canvas.config(cursor="arrow")
        if self.loupe_enabled and not self.crop_mode: self._render_loupe(event.x, event.y)
        else: self.canvas.delete("loupe")

    def _update_split_from_canvas_x(self, cx: int) -> None:
        ox, _, dw, _, _ = self.canvas_layout
        if dw > 10:
            self.split_ratio = max(0.05, min(0.95, (cx - ox) / float(dw)))
            if self.current_frame_orig and self.current_frame_enhanced:
                self.current_processed_frame = self.enhancer.create_comparison_view(self.current_frame_orig, self.current_frame_enhanced, self.split_ratio)
                self._render_current_frame_to_canvas()

    def _render_loupe(self, cx: int, cy: int) -> None:
        if self.current_processed_frame is None: return
        ox, oy, dw, dh, scale = self.canvas_layout
        if not (ox <= cx <= ox + dw and oy <= cy <= oy + dh): self.canvas.delete("loupe"); return
        fw, fh = self.current_processed_frame.size; fx, fy = max(0, min(fw - 1, int((cx - ox) / scale))), max(0, min(fh - 1, int((cy - oy) / scale)))
        dst_rad = 110; patch = self.current_processed_frame.crop((max(0, fx - 44), max(0, fy - 44), min(fw, fx + 44), min(fh, fy + 44))).resize((dst_rad * 2, dst_rad * 2), Image.Resampling.BILINEAR)
        mask = Image.new("L", (dst_rad * 2, dst_rad * 2), 0); ImageDraw.Draw(mask).ellipse((0, 0, dst_rad * 2 - 1, dst_rad * 2 - 1), fill=255)
        circle_img = Image.new("RGBA", (dst_rad * 2, dst_rad * 2), (0, 0, 0, 0)); circle_img.paste(patch.convert("RGBA"), (0, 0), mask=mask)
        self.loupe_tk_photo = ImageTk.PhotoImage(circle_img)
        self.canvas.delete("loupe"); self.canvas.create_image(cx, cy, image=self.loupe_tk_photo, tags="loupe")
        for r, col, w in [(dst_rad, CLR_ACCENT, 3), (dst_rad + 2, CLR_BG_ROOT, 1)]: self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=col, width=w, tags="loupe")
        self.canvas.create_line(cx - 16, cy, cx + 16, cy, fill=CLR_ACCENT, width=1, tags="loupe"); self.canvas.create_line(cx, cy - 16, cx, cy + 16, fill=CLR_ACCENT, width=1, tags="loupe")
        by = cy + dst_rad - 18; self.canvas.create_rectangle(cx - 24, by - 8, cx + 24, by + 8, fill=CLR_BG_TOOLBAR, outline=CLR_ACCENT, tags="loupe")
        self.canvas.create_text(cx, by, text="2.5x", fill=CLR_ACCENT, font=FONT_BADGE, tags="loupe")

    def _render_hud(self) -> None:
        self.canvas.delete("hud")
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 320: return
        text = "Qboard | F9: כיבוי | F4: זיהוי לוח | F5: נקודות | F6: עכבר | F7: מסך | F10: הגדרות"
        bw, bh = 600, 26; x2, y1 = cw - 10, 8; x1, y2 = max(10, x2 - bw), y1 + bh
        self.canvas.create_rectangle(x1, y1, x2, y2, fill="#0B0F19", outline="#1E293B", width=1, tags="hud")
        self.canvas.create_oval(x1 + 8, y1 + 9, x1 + 16, y1 + 17, fill="#10B981", outline="#10B981", tags="hud")
        self.canvas.create_text((x1 + x2) // 2 + 6, (y1 + y2) // 2, text=text, fill="#94A3B8", font=(FONT_FAMILY, 8, "bold"), tags="hud")
        for off in (4, 8, 12): self.canvas.create_line(cw - off, ch - 2, cw - 2, ch - off, fill="#334155", width=1, tags="hud")

    def _render_toast(self) -> None:
        self.canvas.delete("toast")
        if not self._toast_message or not self.canvas.winfo_exists(): return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 60 or ch < 60: return
        pw, ph = max(260, min(cw - 40, len(self._toast_message) * 10 + 44)), 36; x1, y1 = (cw - pw) // 2, ch - 54
        self.canvas.create_rectangle(x1, y1, x1 + pw, y1 + ph, fill="#0F172A", outline=CLR_ACCENT, width=1, tags="toast")
        self.canvas.create_text(x1 + pw // 2, y1 + ph // 2, text=self._toast_message, fill="#F8FAFC", font=FONT_BODY_BOLD, tags="toast")
        self.canvas.tag_raise("toast")

    def _hide_toast(self) -> None:
        self._toast_message, self._toast_timer = None, None
        if self.canvas.winfo_exists(): self.canvas.delete("toast")

    def show_toast(self, message: str) -> None:
        self._toast_message = message; self.stat_toast.set(message)
        if self._toast_timer and self.root.winfo_exists():
            try: self.root.after_cancel(self._toast_timer)
            except Exception: pass
            self._toast_timer = None
        self._render_toast()
        if not self.headless and self.root.winfo_exists(): self._toast_timer = self.root.after(2500, self._hide_toast)

    def process_single_frame(self) -> None:
        self._frame_seq += 1
        raw_frame = self.current_frame_orig if (not self.var_exclude_capture.get() and self.current_frame_orig is not None and self.capture_manager.mode in ("screen", "region", "fullscreen")) else self.capture_manager.capture_frame()
        self.current_frame_orig = raw_frame
        if self.view_mode == "original": self.current_frame_enhanced, self.current_processed_frame = None, raw_frame
        else:
            self.current_frame_enhanced = self.enhancer.enhance(raw_frame, self.current_params)
            self.current_processed_frame = self.enhancer.create_comparison_view(raw_frame, self.current_frame_enhanced, self.split_ratio) if self.view_mode == "split" else self.current_frame_enhanced

        if self.current_frame_orig and self.current_frame_enhanced and (self.capture_manager.frame_count % 15 == 0):
            m = self.enhancer.compute_metrics(self.current_frame_orig, self.current_frame_enhanced); self.latest_metrics = m
            self.stat_whiteness.set(f"⚪ הלבנת רקע: {m['background_whiteness_pct']}%"); self.stat_contrast.set(f"📊 ניגודיות: x{m['contrast_improvement']}")
            self.stat_sharpness.set(f"✨ חדות: x{m['sharpness_improvement']}")

        stats = self.capture_manager.get_stats(); self.stat_fps.set(f"⚡ {stats['fps']} FPS")
        self.stat_latency.set(f"⏱️ לכידה: {stats['latency_ms']:.1f}ms | עיבוד: {self.enhancer.last_processing_time_ms:.1f}ms")
        if not self.headless: self._render_current_frame_to_canvas()

    def _render_current_frame_to_canvas(self) -> None:
        if self.current_processed_frame is None or not self.canvas.winfo_exists(): return
        cw, ch, (iw, ih) = self.canvas.winfo_width(), self.canvas.winfo_height(), self.current_processed_frame.size
        if cw < 30 or ch < 30 or iw < 10 or ih < 10: return
        if getattr(self.enhancer, "last_frame_was_cached", False) and self._rendered_frame_seq == self._frame_seq and (cw, ch) == getattr(self, "_last_canvas_size", None) and self.view_mode == "enhanced":
            self._toast_message and self._render_toast(); return
        scale = max(0.01, min(cw / float(iw), ch / float(ih)))
        dw, dh = int(round(iw * scale)), int(round(ih * scale))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        self.canvas_layout = (ox, oy, dw, dh, scale)
        img_to_show = self.current_processed_frame if (dw, dh) == (iw, ih) else self.current_processed_frame.resize((dw, dh), Image.Resampling.BILINEAR)
        self.current_tk_photo = ImageTk.PhotoImage(img_to_show)
        self._rendered_frame_seq, self._last_canvas_size = self._frame_seq, (cw, ch)
        self.canvas.delete("video_frame"); self.canvas.delete("split_hud")
        self.canvas.create_image(ox, oy, anchor="nw", image=self.current_tk_photo, tags="video_frame")
        if self.view_mode == "split":
            sx, my = ox + int(dw * self.split_ratio), oy + dh // 2
            self.canvas.create_line(sx, oy, sx, oy + dh, fill=CLR_ACCENT, width=2, tags="split_hud")
            self.canvas.create_oval(sx - 12, my - 12, sx + 12, my + 12, fill=CLR_BG_TOOLBAR, outline=CLR_ACCENT, width=2, tags="split_hud")
            self.canvas.create_text(sx, my, text="↔", fill=CLR_ACCENT, font=(FONT_FAMILY, 9, "bold"), tags="split_hud")
            for bx, text, col, border in [(ox + 10, "📷 מקור לפני", CLR_TEXT_MUTED, CLR_BORDER), (ox + dw - 120, "✨ לוח משופר", CLR_ACCENT, CLR_ACCENT)]:
                self.canvas.create_rectangle(bx, oy + 10, bx + 110, oy + 36, fill=CLR_BG_TOOLBAR, outline=border, tags="split_hud")
                self.canvas.create_text(bx + 55, oy + 23, text=text, fill=col, font=FONT_BODY_BOLD, tags="split_hud")
        self._render_hud(); self._toast_message and self._render_toast()
        self.canvas.tag_raise("hud"); self.canvas.tag_raise("toast")

    def _video_tick(self) -> None:
        if not self.overlay_visible:
            if not self.headless and self.root.winfo_exists(): self.root.after(200, self._video_tick)
            return
        if not self.is_paused:
            item = self.pipeline.get_latest_frame()
            if item is not None:
                self.current_frame_orig, self.current_frame_enhanced = item
                self.current_processed_frame = self.enhancer.create_comparison_view(self.current_frame_orig, self.current_frame_enhanced, self.split_ratio) if self.view_mode == "split" else (self.current_frame_orig if self.view_mode == "original" else self.current_frame_enhanced)
                if not self.headless: self._render_current_frame_to_canvas()
                self.stat_fps.set(f"⚡ {self.pipeline.process_fps:.1f} FPS")
                self.stat_latency.set(f"⏱️ לכידה: {self.pipeline.last_capture_ms:.1f}ms | עיבוד: {self.pipeline.last_process_ms:.1f}ms")
            elif self.headless:
                try: self.process_single_frame()
                except Exception as e: logger.error(f"Frame error: {e}")
        if not self.headless and self.root.winfo_exists(): self.root.after(12, self._video_tick)

    def apply_preset(self, preset_name: str, update_sliders: bool = True) -> None:
        if preset_name not in PRESETS: return
        self.current_preset = preset_name; self.current_params = PRESETS[preset_name].copy()
        info = PRESET_INFO.get(preset_name, {}); self.preset_desc_var.set(info.get("desc_he", ""))
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_preset(preset_name)

        if update_sliders:
            p = self.current_params
            for k, (var, lbl, fmt) in self._slider_map.items(): v = getattr(p, k); var.set(v); lbl.set(fmt.format(v))
            self.var_preserve_instructor.set(p.preserve_instructor); self.var_invert_dark_mode.set(p.invert_dark_mode); self.var_denoise.set(p.denoise)
        if self.is_paused and self.current_frame_orig: self.process_single_frame()
        self.show_toast(f"הופעל פרופיל: {info.get('name_he', preset_name)}")

    def _on_slider_change(self, key: str, val_str: str, fmt: str, lbl_var: tk.StringVar) -> None:
        try:
            val = float(val_str); lbl_var.set(fmt.format(val)); setattr(self.current_params, key, val)
            if self.is_paused and self.current_frame_orig: self.process_single_frame()
        except Exception: pass

    def _on_toggle_change(self, key: str) -> None:
        if key == "exclude_capture": val = self.var_exclude_capture.get(); set_window_capture_passthrough(self.root, val); self.show_toast("👻 שקיפות ללכידה פעילה" if val else "⚠️ שקיפות ללכידה כבויה")
        elif key == "click_through": self.set_click_through_mode(self.var_click_through.get())
        elif key == "always_on_top": val = self.var_always_on_top.get(); self.root.attributes("-topmost", val); self.show_toast("📌 נעוץ מעל כל החלונות" if val else "🔓 ביטול נעיצה")
        elif key == "trim_browser_header": val = self.var_trim_browser_header.get(); self.capture_manager.trim_browser_header = val; self.show_toast("✂️ הסתרת כרטיסיות דפדפן פעילה" if val else "כרטיסיות דפדפן גלויות")
        elif hasattr(self.current_params, key): setattr(self.current_params, key, getattr(self, f"var_{key}").get())
        elif key == "simulate_live": self.capture_manager.simulate_live = self.var_simulate_live.get()

    def update_param_from_slider(self, key: str, val: float) -> None:
        if hasattr(self.current_params, key): setattr(self.current_params, key, val)
        if key in self._slider_map: var, lbl, fmt = self._slider_map[key]; var.set(val); lbl.set(fmt.format(val))

    def reset_to_defaults(self) -> None: self.apply_preset("clean_board", update_sliders=True); self.show_toast("🔄 אופסו כל הפרמטרים להגדרות המומלצות")
    def set_view_mode(self, mode: str) -> None:
        if mode in ("enhanced", "split", "original"): self.view_mode = mode; self.current_frame_orig and self.process_single_frame()

    def select_monitor(self, monitor_index: int = 0) -> None:
        mon = self.capture_manager.set_target_screen(monitor_index); self.snap_to_monitor(monitor_index)
        self.active_source_type, self.active_monitor_index, self.view_mode = "screen", mon.index, "enhanced"
        self.stat_source.set(f"מקור: מסך {mon.index + 1} ({mon.width}×{mon.height})"); self.show_toast(f"🖥️ הופעל על מסך {mon.index + 1} ({mon.width}×{mon.height}{' - ראשי' if mon.is_primary else ''})")
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_source()
        self.overlay_visible = True
        if not self.headless and self.root.winfo_exists(): self.root.deiconify(); self.root.lift()

    def snap_to_monitor(self, monitor_index: int) -> bool:
        mons = enum_display_monitors()
        if 0 <= monitor_index < len(mons):
            m = mons[monitor_index]; self.root.geometry(f"{m.width}x{m.height}+{m.rect[0]}+{m.rect[1]}"); return True
        return False

    def cycle_screen_source(self) -> None:
        mons = enum_display_monitors()
        if self.active_source_type != "screen": self.select_monitor(0)
        elif len(mons) > 1: self.select_monitor((self.active_monitor_index + 1) % len(mons))
        else: self.select_monitor(0); mons and self.show_toast(f"🖥️ מסך 1 פעיל ({mons[0].width}×{mons[0].height}) - לכידה חיה")
        self.overlay_visible = True
        if not self.headless and self.root.winfo_exists(): self.root.deiconify(); self.root.lift()

    def open_screen_picker(self) -> None:
        ScreenPickerModal(self.root, self._on_screen_picker_selected, current_source=self.active_source_type, current_index=self.active_monitor_index)

    def _on_screen_picker_selected(self, source_type: str, arg: Any = None) -> None:
        if source_type == "screen": self.select_monitor(arg if arg is not None else 0)
        elif source_type == "zoom": self.auto_detect_zoom()
        elif source_type == "window_picker": self.open_window_picker()
        elif source_type == "roi": self.open_screen_roi_selector()
        elif source_type == "demo": self.set_demo_mode()

    def auto_detect_zoom(self) -> bool:
        win = find_zoom_window()
        if win:
            self.active_source_type = "zoom"; self.capture_manager.set_target_window(win.hwnd)
            self.stat_source.set(f"מקור: זום - {win.title[:24]} ({win.width}×{win.height})"); self.show_toast(f"🎯 זוהה חלון זום: {win.title[:30]}")
        else: self.show_toast("⚠️ לא נמצא חלון זום פעיל")
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_source()
        return bool(win)

    def open_window_picker(self) -> None: WindowPickerModal(self.root, self._on_window_selected)
    def _on_window_selected(self, hwnd: int, title: str) -> None:
        bring_window_to_front(hwnd); self.snap_to_window(hwnd); self.active_source_type = "window"; self.capture_manager.set_target_window(hwnd)
        if any(b in title.lower() for b in ("chrome", "edge", "brave", "firefox")): self.capture_manager.trim_browser_header = self.var_trim_browser_header.get()
        self.root.lift(); self.root.attributes("-topmost", True); self.stat_source.set(f"מקור: {title[:24]}"); self.show_toast(f"🪟 חלון נבחר: {title[:24]} (לכידה ישירה)")
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_source()

    def open_screen_roi_selector(self) -> None: ScreenRegionSelector(self.root, self._on_region_selected)
    def _on_region_selected(self, bbox: Tuple[int, int, int, int]) -> None:
        self.active_source_type = "region"; self.capture_manager.set_region(bbox)
        self.stat_source.set(f"מקור: אזור מסך ({bbox[2]-bbox[0]}×{bbox[3]-bbox[1]})"); self.show_toast(f"📐 נבחר אזור: {bbox[2]-bbox[0]} × {bbox[3]-bbox[1]}")
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_source()

    def open_board_point_selector(self) -> None:
        self.root.withdraw(); self.root.after(80, lambda: BoardPointSelector(self.root, self._on_board_points_selected))

    def _on_board_points_selected(self, bbox: Tuple[int, int, int, int]) -> None:
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]; self._last_locked_geometry = f"{w}x{h}+{bbox[0]}+{bbox[1]}"
        self.capture_manager.set_region(bbox); self.capture_manager.set_board_crop(None); self.root.geometry(self._last_locked_geometry)
        self.active_source_type, self.view_mode, self.overlay_visible = "region", "enhanced", True
        if not self.headless and self.root.winfo_exists(): self.root.deiconify(); self.root.lift(); self.root.attributes("-topmost", True)
        set_window_click_through(self.root, self.click_through_enabled)
        self.stat_source.set(f"מקור: לוח נעול בנקודות ({w}×{h})"); self.show_toast(f"📍 הפילטר ננעל על הלוח בלבד! ({w}×{h}) - מהירות שיא")
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_source()
        self.save_settings()

    def auto_detect_board_region(self) -> Tuple[int, int, int, int] | None:
        if self.capture_manager.mode == "demo":
            raw = self.capture_manager.capture_frame(); w, h = raw.size; nx1, ny1, nx2, ny2 = self.enhancer.detect_whiteboard_bbox(raw)
            bx1, by1, bx2, by2 = int(nx1 * w), int(ny1 * h), int(nx2 * w), int(ny2 * h)
            self.set_board_crop((nx1, ny1, nx2, ny2)); self._last_locked_geometry = f"{bx2-bx1}x{by2-by1}+100+100"
            self.show_toast(f"🤖 הלוח זוהה אוטומטית בעיבוד תמונה! ({int((nx2-nx1)*100)}%×{int((ny2-ny1)*100)}%)"); return (bx1, by1, bx2, by2)
        rect = get_window_rect(self.capture_manager.hwnd) if (self.capture_manager.mode == "window" and self.capture_manager.hwnd) else None
        if not rect: mons = enum_display_monitors(); rect = mons[self.active_monitor_index].rect if mons and self.active_monitor_index < len(mons) else (0, 0, 1920, 1080)
        rx1, ry1, rx2, ry2 = rect
        try: ref = ImageGrab.grab(bbox=(rx1, ry1, rx2, ry2), all_screens=True)
        except Exception: ref = self.capture_manager.capture_frame()
        nx1, ny1, nx2, ny2 = self.enhancer.detect_whiteboard_bbox(ref)
        bx1, by1 = rx1 + int(nx1 * (rx2 - rx1)), ry1 + int(ny1 * (ry2 - ry1)); bx2, by2 = rx1 + int(nx2 * (rx2 - rx1)), ry1 + int(ny2 * (ry2 - ry1))
        self._on_board_points_selected((bx1, by1, bx2, by2)); self.show_toast(f"🤖 הלוח זוהה אוטומטית! ({bx2-bx1}×{by2-by1}) - פילטר ממוקד")
        return (bx1, by1, bx2, by2)

    def set_demo_mode(self) -> None:
        self.active_source_type = "demo"; self.capture_manager.set_mode("demo")
        self.stat_source.set("מקור: הדגמה חיה (1024x575)"); self.show_toast("🖼️ הופעל מצב הדגמה")
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.highlight_source()

    def load_custom_image(self) -> None:
        fp = filedialog.askopenfilename(title="בחר תמונת לוח", filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.webp")])
        if fp and os.path.isfile(fp):
            if self.capture_manager.load_demo_image(fp):
                self.capture_manager.set_mode("demo"); self.stat_source.set(f"מקור: {os.path.basename(fp)[:24]}"); self.show_toast(f"📂 נטענה: {os.path.basename(fp)}")
            else: messagebox.showerror("שגיאה", "טעינת הקובץ נכשלה.")

    def toggle_loupe(self) -> None:
        self.loupe_enabled = not self.loupe_enabled; self.loupe_enabled or self.canvas.delete("loupe")
        self.show_toast("🔍 זכוכית מגדלת 2.5x פעילה" if self.loupe_enabled else "זכוכית מגדלת כבויה")

    def toggle_crop_mode(self) -> None:
        self.crop_mode = not self.crop_mode; self.canvas.config(cursor="cross" if self.crop_mode else "arrow")
        if self.crop_mode: self.show_toast("✂️ גרור מלבן עם העכבר על גבי הלוח לבידוד אזור")

    def set_board_crop(self, crop_norm: Optional[Tuple[float, float, float, float]]) -> None: self.capture_manager.set_board_crop(crop_norm)
    def reset_board_crop(self) -> None: self.set_board_crop(None); self.show_toast("🔄 חיתוך הלוח בוטל - מוצג פריים מלא")
    def toggle_pause(self) -> None: self.is_paused = not self.is_paused; self.show_toast("⏸️ השידור הושהה" if self.is_paused else "▶️ שידור חי נמשך")

    def save_snapshot(self, out_dir: Optional[str] = None) -> str:
        captures_dir = out_dir if out_dir else os.path.join(os.getcwd(), "captures"); os.makedirs(captures_dir, exist_ok=True)
        filepath = os.path.join(captures_dir, f"zoom_board_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        raw = self.capture_manager.capture_frame()
        target = raw if self.view_mode == "original" else self.enhancer.enhance(raw, self.current_params.copy(fast_mode=False), max_process_width=2560)
        if self.view_mode == "split" and self.view_mode != "original": target = self.enhancer.create_comparison_view(raw, target, self.split_ratio)
        target.save(filepath, "PNG"); self.show_toast(f"📸 נשמר: {os.path.basename(filepath)}"); return os.path.abspath(filepath)

    def toggle_capture_passthrough(self) -> None: self.var_exclude_capture.set(not self.var_exclude_capture.get()); self._on_toggle_change("exclude_capture")
    def toggle_always_on_top(self) -> None: st = not self.var_always_on_top.get(); self.var_always_on_top.set(st); self.root.attributes("-topmost", st); self.show_toast("📌 נעוץ מעל כל החלונות" if st else "🔓 ביטול נעיצה")
    def toggle_trim_browser_header(self) -> None: st = not self.var_trim_browser_header.get(); self.var_trim_browser_header.set(st); self.capture_manager.trim_browser_header = st; self.show_toast("✂️ הסתרת כרטיסיות דפדפן פעילה" if st else "כרטיסיות דפדפן גלויות")
    def set_click_through_mode(self, enabled: bool) -> None: self.click_through_enabled = enabled; self.var_click_through.set(enabled); set_window_click_through(self.root, enabled); self.show_toast("🖱️ שקוף לזום: לחיצות ומקש רווח פעילים" if enabled else "✋ מצב עכבר: ניתן לגרור סרגל השוואה")
    def toggle_click_through(self) -> None: self.set_click_through_mode(not self.click_through_enabled)

    def hotkey_toggle_zoom_overlay(self) -> None:
        """Toggle clean whiteboard filter overlay on/off over Zoom."""
        if self.root.winfo_viewable() and self.overlay_visible:
            self.overlay_visible = False; self.root.withdraw()
            if self.settings_window and self.settings_window.winfo_exists():
                try: self.settings_window.withdraw()
                except Exception: pass
        else:
            self.overlay_visible = True
            if self.active_source_type == "region" and getattr(self, "_last_locked_geometry", None): self.root.geometry(self._last_locked_geometry)
            elif self.active_source_type == "screen": self.snap_to_monitor(self.active_monitor_index)
            elif self.active_source_type == "window" and self.capture_manager.hwnd: self.snap_to_window(self.capture_manager.hwnd)
            else: self.snap_to_zoom_window(); self.auto_detect_zoom()
            self.view_mode = "enhanced"; self.root.deiconify(); self.root.lift(); self.root.attributes("-topmost", True)
            set_window_click_through(self.root, self.click_through_enabled)
            if self.capture_manager.hwnd:
                try: ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(self.capture_manager.hwnd))
                except Exception: pass
            self.show_toast("✨ מסנן Qboard הופעל (F9 לכיבוי)")

    def toggle_settings_window(self) -> None:
        from ui.settings_window import SettingsWindow
        if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.on_close()
        else: sw = SettingsWindow.open_or_focus(self.root, self); sw.attributes("-topmost", True); sw.lift(); sw.focus_force()

    def cycle_next_preset(self) -> None:
        keys = ("clean_board", "ultra_bold", "color_markers", "dark_board")
        self.apply_preset(keys[(keys.index(self.current_preset) + 1) % len(keys)] if self.current_preset in keys else keys[0], update_sliders=True)
    def quick_snapshot(self) -> str:
        saved = self.save_snapshot(); self.show_toast(f"📸 נשמר צילום לוח [F8]: {os.path.basename(saved)}"); return saved
    def load_settings(self) -> None:
        if not os.path.exists(_SETTINGS_FILE): return
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f: d = json.load(f)
            if d.get("version") != 4: return
            if d.get("preset") in PRESETS: self.apply_preset(d["preset"], update_sliders=False)
            for k, v in d.get("sliders", {}).items():
                if k in self._slider_map: var, lbl, fmt = self._slider_map[k]; var.set(v); lbl.set(fmt.format(v)); setattr(self.current_params, k, v)
            for k, v in d.get("toggles", {}).items():
                if k != "exclude_capture" and hasattr(self, f"var_{k}"): getattr(self, f"var_{k}").set(v); self._on_toggle_change(k)
            if d.get("last_locked_geometry"): self._last_locked_geometry = d["last_locked_geometry"]
            if d.get("last_source_type") and d["last_source_type"] not in ("demo",): self.active_source_type = d["last_source_type"]
        except Exception as e: logger.warning(f"Settings load: {e}")
    def save_settings(self) -> None:
        if self.headless: return
        try:
            os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
            t_keys = ("fast_mode", "preserve_instructor", "invert_dark_mode", "denoise", "click_through", "trim_browser_header")
            d = {"version": 4, "preset": self.current_preset, "sliders": {k: self._slider_map[k][0].get() for k in self._slider_map},
                 "toggles": {k: getattr(self, f"var_{k}").get() for k in t_keys if hasattr(self, f"var_{k}")},
                 "last_source_type": self.active_source_type, "last_locked_geometry": self._last_locked_geometry}
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f: json.dump(d, f, indent=2)
        except Exception as e: logger.warning(f"Settings save: {e}")
    def quit_app(self) -> None:
        try: hasattr(self, "pipeline") and self.pipeline.stop(); self.save_settings(); self.hotkey_mgr.stop(); self.settings_window and self.settings_window.winfo_exists() and self.settings_window.destroy(); self.root.destroy()
        except Exception: pass
    def _on_escape(self) -> None:
        if self.crop_mode: self.toggle_crop_mode(); return
        if self.loupe_enabled: self.toggle_loupe(); return
        if self.settings_window and self.settings_window.winfo_exists():
            try: self.settings_window.on_close(); return
            except Exception: pass
        self.overlay_visible = False; self.root.withdraw()
    toggle_quick_launch, toggle_settings, cycle_preset, hotkey_quick_snapshot = hotkey_toggle_zoom_overlay, toggle_settings_window, cycle_next_preset, quick_snapshot
    def run(self) -> None: self.root.mainloop()
QboardApp = ZoomPlusApp
def run_self_test(*args, **kwargs) -> int: import tests_runner; return tests_runner.run_self_test(*args, **kwargs)
if __name__ == "__main__": sys.exit(run_self_test()) if "--self-test" in sys.argv else ZoomPlusApp().run()
