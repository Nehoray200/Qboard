"""
Qboard Live Capture Engine
Production-grade real-time screen and window capture module for Windows.
Supports Zoom window tracking, desktop ROI selection, fullscreen grab,
multi-monitor capture, and realistic live test mode with camera sensor simulation.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import math
import os
import time
from typing import Any, Tuple

from PIL import Image, ImageEnhance, ImageGrab

# --- 1. Windows DPI Awareness Initialization ---

def init_dpi_awareness() -> bool:
    """Configure Windows process DPI awareness to match physical display pixels."""
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except Exception:
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except Exception:
        return False

# Initialize DPI awareness as early as possible
_DPI_AWARE = init_dpi_awareness()

# --- 2. Window Rect & Extended Frame Bounds (DWM) ---

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
PW_RENDERFULLCONTENT = 2
SW_RESTORE = 9

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]

def bring_window_to_front(hwnd: int) -> bool:
    """Bring target window to the top of Z-order and set foreground focus; restores if minimized."""
    if not hwnd or not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)):
        return False
    try:
        h = wintypes.HWND(hwnd)
        if ctypes.windll.user32.IsIconic(h):
            ctypes.windll.user32.ShowWindow(h, SW_RESTORE)
        ctypes.windll.user32.BringWindowToTop(h)
        ctypes.windll.user32.SetForegroundWindow(h)
        return True
    except Exception:
        return False

def capture_window_direct(hwnd: int) -> Image.Image | None:
    """Directly capture window surface via Win32 PrintWindow with PW_RENDERFULLCONTENT (2)."""
    if not hwnd or not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)):
        return None
    rect = get_window_rect(hwnd)
    if not rect:
        return None
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    if w <= 0 or h <= 0:
        return None

    hdc_screen, hdc_mem, hbmp, old_bmp = None, None, None, None
    try:
        hdc_screen = ctypes.windll.user32.GetDC(None)
        if not hdc_screen:
            return None
        hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)
        if not hdc_mem:
            return None

        bmi = BITMAPINFOHEADER()
        bmi.biSize, bmi.biWidth, bmi.biHeight = ctypes.sizeof(BITMAPINFOHEADER), w, -h
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        p_bits = ctypes.c_void_p()
        hbmp = ctypes.windll.gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(p_bits), None, 0)
        if not hbmp or not p_bits.value:
            return None

        old_bmp = ctypes.windll.gdi32.SelectObject(hdc_mem, hbmp)
        res = ctypes.windll.user32.PrintWindow(wintypes.HWND(hwnd), hdc_mem, PW_RENDERFULLCONTENT)
        if not res:
            return None

        buf = ctypes.string_at(p_bits.value, w * h * 4)
        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        return img if img.getbbox() is not None else None
    except Exception:
        return None
    finally:
        if hdc_mem and old_bmp:
            ctypes.windll.gdi32.SelectObject(hdc_mem, old_bmp)
        if hbmp:
            ctypes.windll.gdi32.DeleteObject(hbmp)
        if hdc_mem:
            ctypes.windll.gdi32.DeleteDC(hdc_mem)
        if hdc_screen:
            ctypes.windll.user32.ReleaseDC(None, hdc_screen)

def get_window_rect(hwnd: int) -> Tuple[int, int, int, int] | None:
    """
    Return physical screen coordinates (left, top, right, bottom) of a window.
    Uses DwmGetWindowAttribute with DWMWA_EXTENDED_FRAME_BOUNDS to exclude drop-shadow margins.
    Falls back to GetWindowRect if DWM call is unavailable.
    """
    if not hwnd or not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)) or ctypes.windll.user32.IsIconic(wintypes.HWND(hwnd)):
        return None

    rect = wintypes.RECT()
    try:
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS), ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if hr == 0 and rect.right > rect.left and rect.bottom > rect.top:
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass

    try:
        if ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            if rect.right > rect.left and rect.bottom > rect.top:
                return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass

    return None

# --- 3. Window Information Dataclass & Enumeration ---

@dataclass
class WindowInfo:
    hwnd: int
    title: str
    rect: Tuple[int, int, int, int]  # (left, top, right, bottom)
    width: int
    height: int
    is_zoom: bool

    def __repr__(self) -> str:
        tag = "[ZOOM]" if self.is_zoom else "[WIN]"
        return f"{tag} hwnd={self.hwnd} size={self.width}x{self.height} title={self.title!r}"

ZOOM_KEYWORDS = ("zoom", "meeting", "webinar", "sharing", "share", "זום", "פגישה", "שיתוף", "zoom workplace", "zoom meeting")
IGNORED_WINDOW_TITLES = {"Program Manager", "Windows Input Experience", "Default IME", "MSCTFIME UI", "Settings"}

def is_zoom_title(title: str) -> bool:
    """Check if window title matches Zoom keywords (multilingual)."""
    t_lower = title.lower()
    if "qboard" in t_lower or "zoom+" in t_lower or "משפר לוח" in title:
        return False
    return any(k in t_lower for k in ZOOM_KEYWORDS)

def list_capturable_windows() -> list[WindowInfo]:
    """
    Enumerate all capturable desktop application windows.
    Filters out Zoom+ process, tiny windows (<200x150), empty titles, and cloaked windows.
    Sorts Zoom windows first, followed by remaining windows descending by area.
    """
    windows: list[WindowInfo] = []
    current_pid = os.getpid()
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_proc(hwnd: int, _lparam: int) -> bool:
        try:
            win_pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(win_pid))
            if win_pid.value == current_pid:
                return True
        except Exception:
            pass

        if not ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd)) or ctypes.windll.user32.IsIconic(wintypes.HWND(hwnd)):
            return True

        try:
            cloaked = wintypes.DWORD()
            hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_CLOAKED), ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            )
            if hr == 0 and cloaked.value != 0:
                return True
        except Exception:
            pass

        length = ctypes.windll.user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
        if length == 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(wintypes.HWND(hwnd), buf, length + 1)
        title = buf.value.strip()

        if not title or title in IGNORED_WINDOW_TITLES:
            return True
        if "qboard" in title.lower() or "zoom+" in title.lower() or "משפר לוח" in title:
            return True

        rect = get_window_rect(hwnd)
        if not rect:
            return True

        width, height = rect[2] - rect[0], rect[3] - rect[1]
        if width < 200 or height < 150:
            return True

        windows.append(WindowInfo(hwnd=hwnd, title=title, rect=rect, width=width, height=height, is_zoom=is_zoom_title(title)))
        return True

    cb = WNDENUMPROC(enum_proc)
    ctypes.windll.user32.EnumWindows(cb, 0)
    windows.sort(key=lambda w: (not w.is_zoom, -(w.width * w.height)))
    return windows

def find_zoom_window() -> WindowInfo | None:
    """Find and return the most likely active Zoom meeting window."""
    for win in list_capturable_windows():
        if win.is_zoom:
            return win
    return None

# --- 4. Monitor Information Dataclass & Enumeration ---

@dataclass
class MonitorInfo:
    index: int
    name: str
    rect: Tuple[int, int, int, int]  # (left, top, right, bottom)
    width: int
    height: int
    is_primary: bool

    def __repr__(self) -> str:
        tag = "[PRIMARY]" if self.is_primary else "[MONITOR]"
        return f"{tag} #{self.index} {self.width}x{self.height} rect={self.rect} name={self.name!r}"


class RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD), ('rcMonitor', RECT), ('rcWork', RECT),
        ('dwFlags', wintypes.DWORD), ('szDevice', wintypes.WCHAR * 32)
    ]


def enum_display_monitors() -> list[MonitorInfo]:
    """
    Enumerate all physical display monitors.
    Returns list of MonitorInfo sorted with primary monitor first (index 0).
    Falls back to primary virtual screen metrics if enumeration fails.
    """
    monitors: list[MonitorInfo] = []
    try:
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
        )

        def _enum_proc(h_monitor: int, _hdc: int, _lprect: Any, _lparam: int) -> bool:
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if ctypes.windll.user32.GetMonitorInfoW(h_monitor, ctypes.byref(mi)):
                r = mi.rcMonitor
                rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
                monitors.append(
                    MonitorInfo(
                        index=len(monitors),
                        name=str(mi.szDevice).strip() or f"DISPLAY{len(monitors) + 1}",
                        rect=rect,
                        width=rect[2] - rect[0],
                        height=rect[3] - rect[1],
                        is_primary=bool(mi.dwFlags & 1),
                    )
                )
            return True

        cb = MONITORENUMPROC(_enum_proc)
        res = ctypes.windll.user32.EnumDisplayMonitors(None, None, cb, 0)
        if res and monitors:
            monitors.sort(key=lambda m: (not m.is_primary, m.name))
            for idx, m in enumerate(monitors):
                m.index = idx
            return monitors
    except Exception:
        pass

    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
        h = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        w = w if w > 0 else 1920
        h = h if h > 0 else 1080
    except Exception:
        w, h = 1920, 1080

    return [MonitorInfo(index=0, name="PRIMARY", rect=(0, 0, w, h), width=w, height=h, is_primary=True)]

# --- 5. Live Capture Manager ---

class LiveCaptureManager:
    """
    High-performance capture manager supporting 5 modes:
      - 'demo': Uses sample_zoom.png with optional live webcam sensor breathing/jitter.
      - 'window': Dynamically tracks and grabs a specific window hwnd.
      - 'region': Grabs an arbitrary screen ROI bounding box (left, top, right, bottom).
      - 'fullscreen': Grabs the primary desktop display.
      - 'screen': Grabs a specific physical display monitor by index.
    """

    SUPPORTED_MODES = ("demo", "window", "region", "fullscreen", "screen")

    def __init__(
        self,
        mode: str = "demo",
        hwnd: int | None = None,
        region_bbox: Tuple[int, int, int, int] | None = None,
        board_crop_norm: Tuple[float, float, float, float] | None = None,
        demo_image_path: str | None = None,
        simulate_live: bool = True,
        selected_monitor_index: int = 0,
        trim_browser_header: bool = False,
    ) -> None:
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode {mode!r}. Must be one of {self.SUPPORTED_MODES}")

        self.mode = mode
        self.hwnd = hwnd
        self.region_bbox = region_bbox
        self.board_crop_norm = board_crop_norm
        self.simulate_live = simulate_live
        self.selected_monitor_index = selected_monitor_index
        self.trim_browser_header = trim_browser_header
        self.anti_mirror_frozen: bool = False

        if self.mode == "screen" and self.region_bbox is None:
            self.set_target_screen(self.selected_monitor_index)

        self.demo_image_path = demo_image_path or self._resolve_default_demo_image()
        self._demo_base_img: Image.Image | None = None
        self._load_demo_image()

        self.current_fps: float = 0.0
        self.last_capture_ms: float = 0.0
        self.frame_count: int = 0
        self._last_frame_time: float = 0.0
        self.last_frame: Image.Image | None = None
        self._fallback_cache: dict[str, Image.Image] = {}

    def _resolve_default_demo_image(self) -> str:
        """Locate sample_zoom.png in current workspace or parent directories."""
        candidates = [
            "sample_zoom.png",
            os.path.join(os.path.dirname(__file__), "sample_zoom.png"),
            os.path.join(os.getcwd(), "sample_zoom.png"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return "sample_zoom.png"

    def _create_synthetic_whiteboard(self) -> Image.Image:
        w, h = 1024, 576; im = Image.new("RGB", (w, h), (180, 185, 190)); from PIL import ImageDraw; d = ImageDraw.Draw(im)
        d.rectangle([0, 0, w, 120], fill=(210, 214, 218)); d.rectangle([0, 115, w, 125], fill=(120, 125, 130))
        bx1, by1, bx2, by2 = 40, 140, 984, 510; d.rectangle([bx1-4, by1-4, bx2+4, by2+4], fill=(70, 75, 80)); d.rectangle([bx1, by1, bx2, by2], fill=(215, 220, 225))
        for xs in (280, 680):
            for dx in range(-25, 26): cv = int(220 + max(0, 1.0 - abs(dx) / 25.0) * 25); d.line([(xs + dx, by1 + 10), (xs + dx, by2 - 10)], fill=(cv, cv, cv))
        for y in range(165, 485, 28):
            d.rectangle([95, y, 460, y + 6], fill=(115, 120, 128)); d.rectangle([520, y, 920, y + 6], fill=(115, 120, 128))
        ink = (90, 95, 105); d.text((80, 170), "Runtime Complexity Analysis: T(n) = 2T(n/2) + O(n)", fill=ink)
        d.text((80, 235), "=> Master Theorem Case 2: T(n) = O(n log n)", fill=ink); d.text((520, 170), "FindMax(A, n) Algorithm Loop Analysis", fill=ink)
        d.text((520, 235), "Example Array: [ 2, -3, 50, 4 ] => max = 50", fill=ink); return im

    def _load_demo_image(self) -> None:
        """Load or synthetically generate base demo image."""
        if self.demo_image_path and os.path.isfile(self.demo_image_path):
            try:
                with Image.open(self.demo_image_path) as img:
                    self._demo_base_img = img.convert("RGB"); return
            except Exception: pass
        self._demo_base_img = self._create_synthetic_whiteboard()

    def load_demo_image(self, path: str) -> bool:
        """Update demo image source at runtime."""
        if os.path.isfile(path):
            try:
                with Image.open(path) as img:
                    self._demo_base_img = img.convert("RGB")
                    self.demo_image_path = path
                    return True
            except Exception:
                return False
        return False

    def set_mode(
        self,
        mode: str,
        hwnd: int | None = None,
        region_bbox: Tuple[int, int, int, int] | None = None,
    ) -> None:
        """Switch capture mode and update target parameters."""
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unknown mode {mode!r}. Must be one of {self.SUPPORTED_MODES}")
        self.mode = mode
        if hwnd is not None:
            self.hwnd = hwnd
        if region_bbox is not None:
            self.region_bbox = region_bbox
        elif self.mode == "screen" and self.region_bbox is None:
            self.set_target_screen(self.selected_monitor_index)

    def set_target_window(self, hwnd: int) -> None:
        """Set target window hwnd and switch mode to 'window'."""
        self.hwnd = hwnd
        self.mode = "window"

    def set_target_screen(self, monitor_index: int = 0) -> MonitorInfo:
        """Select physical display monitor by index and switch mode to 'screen'."""
        monitors = enum_display_monitors()
        clamped_index = max(0, min(monitor_index, len(monitors) - 1))
        self.selected_monitor_index = clamped_index
        target = monitors[clamped_index]
        self.region_bbox = target.rect
        self.mode = "screen"
        return target

    def set_region(self, bbox: Tuple[int, int, int, int]) -> None:
        """Set capture region bounding box (left, top, right, bottom) and switch mode to 'region'."""
        self.region_bbox = bbox
        self.mode = "region"

    def set_board_crop(self, crop_norm: Tuple[float, float, float, float] | None) -> None:
        """Set or clear normalized whiteboard crop box: (x1, y1, x2, y2)."""
        if crop_norm is None:
            self.board_crop_norm = None
            return

        x1, y1, x2, y2 = crop_norm
        x1, y1 = max(0.0, min(1.0, float(x1))), max(0.0, min(1.0, float(y1)))
        x2, y2 = max(0.0, min(1.0, float(x2))), max(0.0, min(1.0, float(y2)))
        self.board_crop_norm = (x1, y1, x2, y2) if (x2 - x1 >= 0.05 and y2 - y1 >= 0.05) else None

    def _get_placeholder_frame(self, message: str) -> Image.Image:
        """Generate a clean placeholder frame when capture target is unavailable."""
        if message in self._fallback_cache:
            return self._fallback_cache[message].copy()
        img = Image.new("RGB", (960, 540), (30, 32, 38))
        self._fallback_cache[message] = img
        return img.copy()

    def _capture_demo_frame(self) -> Image.Image:
        """Produce demo frame with subtle live sensor jitter/breathing."""
        if self._demo_base_img is None:
            self._load_demo_image()
        base = self._demo_base_img
        if base is None:
            return self._get_placeholder_frame("Demo frame missing")
        if not self.simulate_live:
            return base.copy()

        now = time.time()
        w, h = base.size
        shift_x = int(1.5 + 1.5 * math.sin(now * 1.7))
        shift_y = int(1.5 + 1.5 * math.cos(now * 1.3))
        crop_box = (shift_x, shift_y, w - (3 - shift_x), h - (3 - shift_y))
        frame = base.crop(crop_box).resize((w, h), Image.Resampling.BILINEAR)
        lum_factor = 1.0 + 0.007 * math.sin(now * 2.5)
        return ImageEnhance.Brightness(frame).enhance(lum_factor)

    def _capture_window_frame(self) -> Image.Image:
        """Capture specified window hwnd rect dynamically."""
        target_hwnd = self.hwnd
        if target_hwnd is None:
            zoom_win = find_zoom_window()
            if zoom_win:
                target_hwnd = zoom_win.hwnd
                self.hwnd = target_hwnd

        if target_hwnd is None:
            return self.last_frame.copy() if self.last_frame is not None else self._get_placeholder_frame("No window selected")

        rect = get_window_rect(target_hwnd)
        if not rect:
            return self.last_frame.copy() if self.last_frame is not None else self._get_placeholder_frame("Window minimized or closed")

        frame = capture_window_direct(target_hwnd)
        if frame is None:
            try:
                bring_window_to_front(target_hwnd)
                grabbed = ImageGrab.grab(bbox=rect, all_screens=True)
                if grabbed.width > 0 and grabbed.height > 0:
                    frame = grabbed
            except Exception:
                pass

        if frame is not None and frame.width > 0 and frame.height > 0:
            if self.trim_browser_header and frame.height > 120:
                frame = frame.crop((0, min(82, frame.height - 60), frame.width, frame.height))
            return frame

        return self.last_frame.copy() if self.last_frame is not None else self._get_placeholder_frame("Window capture failed")

    def _capture_region_frame(self) -> Image.Image:
        """Capture fixed screen region bounding box."""
        if not self.region_bbox:
            return ImageGrab.grab(all_screens=True)

        left, top, right, bottom = self.region_bbox
        if right <= left or bottom <= top:
            return ImageGrab.grab(all_screens=True)

        try:
            frame = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
            if frame.width > 0 and frame.height > 0:
                return frame
        except Exception:
            pass

        return self.last_frame.copy() if self.last_frame is not None else self._get_placeholder_frame("Region grab failed")

    def _capture_screen_frame(self) -> Image.Image:
        """Capture selected physical monitor frame."""
        if self.region_bbox:
            try:
                frame = ImageGrab.grab(bbox=self.region_bbox, all_screens=True)
                if frame.width > 0 and frame.height > 0:
                    return frame
            except Exception:
                pass
        return self._capture_fullscreen_frame()

    def _capture_fullscreen_frame(self) -> Image.Image:
        """Capture full screen display."""
        for kw in ({"all_screens": True}, {}):
            try:
                return ImageGrab.grab(**kw)
            except Exception:
                pass
        return self.last_frame.copy() if self.last_frame is not None else self._get_placeholder_frame("Fullscreen capture failed")

    def _apply_board_crop(self, frame: Image.Image) -> Image.Image:
        """Apply sub-ROI whiteboard crop if enabled."""
        if not self.board_crop_norm:
            return frame

        w, h = frame.size
        x1, y1, x2, y2 = self.board_crop_norm
        px1, py1 = max(0, min(w - 1, int(x1 * w))), max(0, min(h - 1, int(y1 * h)))
        px2, py2 = max(px1 + 10, min(w, int(x2 * w))), max(py1 + 10, min(h, int(y2 * h)))

        if px2 > px1 and py2 > py1:
            return frame.crop((px1, py1, px2, py2))
        return frame

    def capture_full_background(self) -> Image.Image:
        """
        Capture the entire underlying desktop screen or target window background
        without whiteboard sub-ROI cropping.
        Under WDA_EXCLUDEFROMCAPTURE, this captures the clean desktop/Zoom video
        underneath Qboard without UI occlusions.
        """
        if self.mode == "demo":
            if self._demo_base_img is None:
                self._load_demo_image()
            return self._demo_base_img.copy() if self._demo_base_img else self._create_synthetic_whiteboard()

        if self.mode == "window" and self.hwnd:
            direct = capture_window_direct(self.hwnd)
            if direct is not None and direct.width > 0 and direct.height > 0:
                return direct
            rect = get_window_rect(self.hwnd)
            if rect:
                try:
                    grabbed = ImageGrab.grab(bbox=rect, all_screens=True)
                    if grabbed.width > 0 and grabbed.height > 0:
                        return grabbed
                except Exception:
                    pass



        try:
            return ImageGrab.grab(all_screens=True)
        except Exception:
            return self.last_frame.copy() if self.last_frame is not None else self._get_placeholder_frame("Background capture failed")

    def capture_frame(self) -> Image.Image:
        """
        Capture and return a single frame according to the active mode and ROI crop.
        Updates FPS and capture latency metrics.
        Never raises fatal exceptions; gracefully falls back on errors.
        """
        if self.anti_mirror_frozen and self.last_frame is not None:
            return self.last_frame.copy()

        t0 = time.perf_counter()

        if self.mode == "demo":
            frame = self._capture_demo_frame()
        elif self.mode == "window":
            frame = self._capture_window_frame()
        elif self.mode == "region":
            frame = self._capture_region_frame()
        elif self.mode == "fullscreen":
            frame = self._capture_fullscreen_frame()
        elif self.mode == "screen":
            frame = self._capture_screen_frame()
        else:
            frame = self._capture_demo_frame()

        frame = self._apply_board_crop(frame)

        t1 = time.perf_counter()
        self.last_capture_ms = (t1 - t0) * 1000.0

        now = time.time()
        if self._last_frame_time > 0:
            dt = now - self._last_frame_time
            if dt > 0.0001:
                instant_fps = 1.0 / dt
                if self.current_fps == 0.0:
                    self.current_fps = instant_fps
                else:
                    self.current_fps = 0.85 * self.current_fps + 0.15 * instant_fps
        self._last_frame_time = now
        self.frame_count += 1
        self.last_frame = frame

        return frame

    def get_stats(self) -> dict[str, Any]:
        """Return real-time capture diagnostics and telemetry."""
        resolution = self.last_frame.size if self.last_frame else None
        stats: dict[str, Any] = {
            "mode": self.mode,
            "fps": round(self.current_fps, 1),
            "latency_ms": round(self.last_capture_ms, 2),
            "frame_count": self.frame_count,
            "resolution": resolution,
            "hwnd": self.hwnd,
            "has_board_crop": self.board_crop_norm is not None,
            "simulate_live": self.simulate_live,
            "trim_browser_header": self.trim_browser_header,
        }
        if self.mode == "screen":
            stats["selected_monitor"] = self.selected_monitor_index
        return stats
