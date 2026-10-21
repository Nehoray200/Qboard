"""
Qboard Whiteboard Enhancement Engine V5 (processor.py)
Multi-Core Parallel + Sub-Macroblock Symmetric Bridge + Temporal Anti-Flicker & Cache Isolation.
"""

from __future__ import annotations
import os, time, threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
from PIL import Image, ImageFilter, ImageChops, ImageDraw


@dataclass
class EnhancementParams:
    """Tunable parameters for whiteboard stream enhancement."""
    preset: str = "clean_board"
    contrast: float = 1.65           # ink darkness / contrast stretch (0.5 to 4.0)
    thickening: float = 0.15         # morphological stroke dilation (0.0 to 2.0)
    glare_removal: float = 0.90      # illumination envelope strength (0.0 to 1.0)
    shadow_suppression: float = 0.85 # broad shadow & penumbra suppression (0.0 to 1.5)
    white_threshold: float = 0.012   # hysteresis noise floor for white board (0.002 to 0.08)
    ink_saturation: float = 0.145    # difference for 100% ink opacity (0.03 to 0.25)
    gamma: float = 1.12              # gamma curve on extracted ink mask (0.5 to 2.5)
    sharpen: float = 1.25            # UnsharpMask filter strength (0.0 to 4.0)
    preserve_instructor: bool = True # keeps teacher, hands, skin in natural color
    invert_dark_mode: bool = False   # modern blackboard view (#12161F slate)
    denoise: bool = False            # pre-smoothing for noisy webcams
    fast_mode: bool = True           # Turbo real-time 100+ FPS mode (True=SIMD direct, False=2x SSAA)
    dual_sharpen: bool = True        # dual-stage sharpening (stroke boundary + micro-contrast)
    temporal_stability: bool = True  # motion-gated temporal anti-flicker filter

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnhancementParams:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

    def copy(self, **kwargs) -> EnhancementParams:
        d = self.to_dict(); d.update(kwargs)
        return EnhancementParams.from_dict(d)


PRESETS: Dict[str, EnhancementParams] = {
    "clean_board": EnhancementParams(preset="clean_board", contrast=1.65, thickening=0.15, glare_removal=0.90, shadow_suppression=0.85, white_threshold=0.012, ink_saturation=0.145, gamma=1.12, sharpen=1.25, fast_mode=True, dual_sharpen=True),
    "ultra_bold": EnhancementParams(preset="ultra_bold", contrast=2.05, thickening=0.65, glare_removal=0.92, shadow_suppression=0.90, white_threshold=0.011, ink_saturation=0.115, gamma=1.18, sharpen=1.50, fast_mode=True, dual_sharpen=True),
    "color_markers": EnhancementParams(preset="color_markers", contrast=1.55, thickening=0.12, glare_removal=0.88, shadow_suppression=0.75, white_threshold=0.012, ink_saturation=0.155, gamma=1.08, sharpen=1.15, fast_mode=True, dual_sharpen=True),
    "dark_board": EnhancementParams(preset="dark_board", contrast=1.75, thickening=0.25, glare_removal=0.90, shadow_suppression=0.80, white_threshold=0.012, ink_saturation=0.140, gamma=1.14, sharpen=1.30, invert_dark_mode=True, fast_mode=True, dual_sharpen=True),
    "raw_contrast": EnhancementParams(preset="raw_contrast", contrast=1.30, thickening=0.0, glare_removal=0.60, shadow_suppression=0.50, white_threshold=0.016, ink_saturation=0.175, gamma=1.02, sharpen=0.95, fast_mode=True, dual_sharpen=False),
}

PRESET_INFO: Dict[str, Dict[str, str]] = {
    "clean_board": {"name_he": "לוח נקי (ברירת מחדל)", "icon": "✨", "desc_he": "שימור 100% מהפרטים והאותיות הדקות, הסרת בוהק והלבנת רקע טבעית"},
    "ultra_bold": {"name_he": "כתב מודגש (טושים דהויים)", "icon": "🖊️", "desc_he": "חיזוק ועיבוי מבוקר של קווים דקים וטושים חלשים ללא מחיקת פרטים"},
    "color_markers": {"name_he": "טושים צבעוניים", "icon": "🎨", "desc_he": "שמירה והגברה של צבעי טושים על רקע לבן נקי וחלק"},
    "dark_board": {"name_he": "לוח כהה (Dark Mode)", "icon": "🌙", "desc_he": "היפוך מודרני למניעת עייפות עיניים - רקע כהה וכיתוב בהיר"},
    "raw_contrast": {"name_he": "ניגודיות טבעית", "icon": "⚖️", "desc_he": "שיפור עדין וטבעי של ניגודיות ללא הלבנה אגרסיבית"},
}


class WhiteboardEnhancer:
    """Multi-Core Real-time Whiteboard Image Enhancer & Computer Vision Detector (Engine V5)."""

    def __init__(self):
        self.last_processing_time_ms: float = 0.0
        self.last_frame_was_cached: bool = False
        self.num_workers: int = min(6, os.cpu_count() or 4)
        self._pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=self.num_workers)
        self._lock = threading.Lock()
        self.backend_name: str = "Pillow C-SIMD (Vectorized AVX2)"

        self._ink_lut_cache: Dict[Tuple[int, int, float, float], List[int]] = {}
        self._x9_lut: List[int] = [min(255, i * 9) for i in range(256)]
        self._has_ink_lut: List[int] = [0 if d <= 1 else (180 if d == 2 else 255) for d in range(256)]
        self._cohesion_lut: List[int] = [0 if s <= 7 else min(10, (s - 6) // 3) for s in range(256)]
        self._co_gate_exact_lut: List[int] = [0 if s <= 4 else (140 if s == 5 else (210 if s == 6 else 255)) for s in range(256)]
        self._glare_zone_lut: List[int] = [min(255, max(0, (i - 172) * 6)) for i in range(256)]
        self._glare_diff_lut: List[int] = [0 if s <= 6 else min(255, (s - 6) // 2) for s in range(256)]
        self._skin_lut: List[int] = [min(255, max(0, (i - 12) * 16)) for i in range(256)]
        self._dark_gate_lut: List[int] = [min(255, max(0, (128 - i) * 10)) for i in range(256)]
        self._dark_lut: List[int] = [min(255, max(0, (132 - i) * 8)) for i in range(256)]
        self._dilate1_lut: List[int] = [min(255, int(i * 2.6)) for i in range(256)]
        self._shadow_135_lut: List[int] = [min(255, int(i * 1.35)) for i in range(256)]
        self._anti_flicker_lut: List[int] = [255 if d <= 12 else max(0, 255 - (d - 12) * 14) for d in range(256)]

        # Pre-cached reconstruction layers & LUTs
        self._bg_white_cache: Dict[Tuple[int, int], Image.Image] = {}
        self._bg_dark_cache: Dict[Tuple[int, int], Image.Image] = {}
        self._ink_lut_normal: List[int] = [int(i * 0.14) for i in range(256)] * 3
        self._ink_lut_color: List[int] = [int(i * 0.35) for i in range(256)] * 3
        self._ink_lut_dark_color: List[int] = [min(255, int(i * 1.3 + 40)) for i in range(256)] * 3

        # Stream delta-frame, temporal envelope & anti-flicker caches
        self._last_thumb: Optional[np.ndarray] = None
        self._last_params_key: Optional[Tuple] = None
        self._last_enhanced_out: Optional[Image.Image] = None
        self._cache_age: int = 0
        self._cached_bg_env: Optional[Image.Image] = None
        self._cached_glare_zone: Optional[Image.Image] = None
        self._cached_env_key: Optional[Tuple] = None
        self._env_tick: int = 0
        self._prev_ink: Optional[Image.Image] = None
        self._cached_inst_mask: Optional[Image.Image] = None
        self._inst_tick: int = 0

    def _get_bg_layer(self, pw: int, ph: int, dark: bool = False) -> Image.Image:
        cache = self._bg_dark_cache if dark else self._bg_white_cache
        color = (18, 22, 31) if dark else (255, 255, 255)
        layer = cache.get((pw, ph))
        if layer is None:
            layer = Image.new("RGB", (pw, ph), color)
            cache[(pw, ph)] = layer
        return layer

    def _get_ink_lut(self, white_threshold: float, ink_saturation: float, gamma: float, contrast: float) -> List[int]:
        thresh_u8 = max(1, min(6, int(round(white_threshold * 165.0))))
        sat_u8 = max(thresh_u8 + 8, int(round(ink_saturation * 250.0)))
        gamma_exp = round(1.0 / max(gamma, 0.25), 4)
        contrast_scale = round(max(contrast, 0.2) / 1.65, 4)
        key = (thresh_u8, sat_u8, gamma_exp, contrast_scale)
        lut = self._ink_lut_cache.get(key)
        if lut is None:
            denom = float(max(1, sat_u8 - thresh_u8))
            toe = 28.0 * contrast_scale
            span = 220.0 * contrast_scale
            lut = [
                0 if i <= thresh_u8 else (
                    min(255, int(round(toe))) if i == thresh_u8 + 1 else min(
                        255, int(round(toe + (min(1.0, (i - thresh_u8) / denom) ** gamma_exp) * span))
                    )
                )
                for i in range(256)
            ]
            self._ink_lut_cache[key] = lut
        return lut

    @staticmethod
    def _sub_macroblock_bridge(gray: Image.Image) -> Image.Image:
        w, h = gray.size; w4, h4 = max(1, w // 4), max(1, h // 4)
        g4 = gray.resize((w4, h4), Image.Resampling.BILINEAR)
        return g4.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.BoxBlur(1)).resize((w, h), Image.Resampling.BILINEAR)

    def _compute_instructor_mask(self, work_img: Image.Image, pw: int, ph: int) -> Image.Image:
        w2, h2 = max(1, pw // 2), max(1, ph // 2)
        work2 = work_img.resize((w2, h2), Image.Resampling.BILINEAR)
        r2, _, b2 = work2.split()
        gray2 = work2.convert("L")
        w4, h4 = max(1, pw // 4), max(1, ph // 4)
        g4 = gray2.resize((w4, h4), Image.Resampling.BILINEAR)
        skin = ImageChops.subtract(r2, b2).point(self._skin_lut)
        dark_gate = g4.point(self._dark_gate_lut).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)).resize((w2, h2), Image.Resampling.BILINEAR)
        dark = ImageChops.multiply(gray2.point(self._dark_lut), dark_gate)
        mask = ImageChops.lighter(skin, dark).filter(ImageFilter.BoxBlur(1)).point(self._dilate1_lut).filter(ImageFilter.BoxBlur(1))
        return mask.resize((pw, ph), Image.Resampling.BILINEAR)

    def _parallel_ssaa(self, diff_im: Image.Image, lut: List[int], pw: int, ph: int) -> Image.Image:
        n, pad = 4, 4
        def _worker(i: int):
            sy0, sy1 = i * ph // n, (i + 1) * ph // n
            cy0, cy1 = max(0, sy0 - pad), min(ph, sy1 + pad)
            crop = diff_im.crop((0, cy0, pw, cy1))
            ch = cy1 - cy0
            proc = crop.resize((pw * 2, ch * 2), Image.Resampling.BICUBIC).point(lut).resize((pw, ch), Image.Resampling.BILINEAR)
            top = sy0 - cy0
            return (sy0, proc.crop((0, top, pw, top + (sy1 - sy0))))
        strips = list(self._pool.map(_worker, range(n)))
        out = Image.new("L", (pw, ph))
        for sy0, s in strips: out.paste(s, (0, sy0))
        return out

    def detect_whiteboard_bbox(self, img: Image.Image) -> Tuple[float, float, float, float]:
        dw, dh = 256, 144
        arr = np.asarray(img.convert("RGB").resize((dw, dh), Image.Resampling.BILINEAR), dtype=np.float32)
        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        sat = np.max(arr, axis=2) - np.min(arr, axis=2)
        dy = np.abs(np.diff(lum, axis=0, prepend=lum[:1, :]))
        row_edge, row_lum = np.mean(dy, axis=1), np.mean(lum, axis=1)

        r_top_min, r_top_max = int(0.15 * dh), int(0.42 * dh)
        top_thresh = max(float(np.percentile(row_edge, 75)), float(np.percentile(row_edge[r_top_min:r_top_max], 60)))
        candidates = [r for r in range(r_top_min, r_top_max) if row_edge[r] > top_thresh and float(np.mean(row_lum[r + 2 : min(dh, r + 18)])) > 132.0]
        y1 = max([r for r in candidates if abs(r - candidates[-1]) <= 2], key=lambda r: row_edge[r]) if candidates else int(0.20 * dh)

        r_bot_min, r_bot_max = int(0.58 * dh), int(0.92 * dh)
        y2 = r_bot_min + int(np.argmax(row_edge[r_bot_min:r_bot_max]))

        col_lum, col_sat = np.mean(lum[y1:y2, :], axis=0), np.mean(sat[y1:y2, :], axis=0)
        col_edge = np.mean(np.abs(np.diff(lum[y1:y2, :], axis=1, prepend=lum[y1:y2, :1])), axis=0)
        bright_cols = np.where((col_lum > 128.0) & (col_sat < 42.0))[0]
        x1 = int(bright_cols[0]) if len(bright_cols) > 0 else int(0.03 * dw)
        lp = int(np.argmax(col_edge[: int(0.18 * dw)]))
        if col_edge[lp] > np.percentile(col_edge, 80) and lp > x1: x1 = lp

        rp = int(0.85 * dw) + int(np.argmax(col_edge[int(0.85 * dw):int(0.99 * dw)]))
        x2 = int(bright_cols[-1]) if len(bright_cols) > 0 else int(0.97 * dw)
        if col_edge[rp] > np.percentile(col_edge, 80) and rp < x2: x2 = rp

        x1_n, y1_n, x2_n, y2_n = float(x1) / dw, float(y1) / dh, float(x2) / dw, float(y2) / dh
        if len(bright_cols) == 0 or (x2_n - x1_n < 0.25) or (y2_n - y1_n < 0.20) or (x1_n >= x2_n) or (y1_n >= y2_n):
            return (0.03, 0.18, 0.97, 0.82)
        return (round(max(0.0, min(1.0, x1_n)), 4), round(max(0.0, min(1.0, y1_n)), 4), round(max(0.0, min(1.0, x2_n)), 4), round(max(0.0, min(1.0, y2_n)), 4))

    def enhance(self, img: Image.Image, params: Optional[EnhancementParams] = None, max_process_width: int = 1280) -> Image.Image:
        t_start = time.perf_counter()
        if params is None: params = PRESETS["clean_board"]
        w, h = img.size
        if w < 16 or h < 16:
            self.last_processing_time_ms, self.last_frame_was_cached = 0.0, False
            return img.convert("RGB") if img.mode != "RGB" else img.copy()

        src_img = img.convert("RGB") if img.mode != "RGB" else img

        # 1. Thread-safe fast thumbnail check (P1 & P9)
        params_key = None
        if params.fast_mode:
            with self._lock:
                thumb_arr = np.asarray(src_img.resize((128, 72), Image.Resampling.BILINEAR).convert("L"), dtype=np.int16)
                params_key = (w, h, max_process_width, params.preset, round(params.contrast, 3), round(params.thickening, 3), round(params.glare_removal, 3), round(getattr(params, "shadow_suppression", 0.85), 3), round(params.white_threshold, 4), round(params.ink_saturation, 4), round(params.gamma, 3), round(params.sharpen, 2), params.preserve_instructor, params.invert_dark_mode, params.denoise)
                if self._last_thumb is not None and self._last_params_key == params_key and self._last_enhanced_out is not None and self._cache_age < 12:
                    diff_t = np.abs(thumb_arr - self._last_thumb)
                    if float(np.max(diff_t.reshape(6, 12, 8, 16).mean(axis=(1, 3)))) <= 2.8 and float(np.mean(diff_t)) <= 0.45:
                        self.last_frame_was_cached, self._cache_age = True, self._cache_age + 1
                        self.last_processing_time_ms = (time.perf_counter() - t_start) * 1000.0
                        return self._last_enhanced_out
                self._last_thumb, self._cache_age, self.last_frame_was_cached = thumb_arr, 0, False
        else:
            self._cache_age, self.last_frame_was_cached = 0, False

        if params.denoise: src_img = src_img.filter(ImageFilter.BoxBlur(0.7))
        if params.fast_mode and w > 1440 and w > max_process_width:
            pw = max_process_width; ph = max(1, int(round(h * (pw / w))))
            work_img = src_img.resize((pw, ph), Image.Resampling.BILINEAR, reducing_gap=2.0)
        else:
            pw, ph = w, h; work_img = src_img

        gray = work_img.convert("L")
        w8, h8 = max(1, pw // 8), max(1, ph // 8)

        # 2. Concurrently submit Instructor Mask to Worker Core (P3 with 2-frame smoothing)
        fut_inst = None
        if params.preserve_instructor:
            need_inst = (self._cached_inst_mask is None) or (self._inst_tick % 2 == 0) or (not params.fast_mode)
            self._inst_tick += 1
            if need_inst:
                fut_inst = self._pool.submit(self._compute_instructor_mask, work_img, pw, ph)

        # 3. Smooth EMA Illumination Envelope (P7)
        env_key = (pw, ph, round(params.glare_removal, 2))
        need_env = self._cached_env_key != env_key or self._cached_bg_env is None or (self._env_tick % 3 == 0) or (not params.fast_mode)
        self._env_tick += 1
        if need_env:
            bg_bridge = self._sub_macroblock_bridge(gray)
            if params.glare_removal < 0.89:
                bg_ambient = gray.resize((w8, h8), Image.Resampling.BILINEAR).filter(ImageFilter.BoxBlur(3)).resize((pw, ph), Image.Resampling.BILINEAR)
                bg_bridge = Image.blend(bg_ambient, bg_bridge, float(np.clip(params.glare_removal / 0.90, 0.0, 1.0)))
            if params.fast_mode and self._cached_bg_env is not None and self._cached_bg_env.size == (pw, ph):
                bg_env = Image.blend(self._cached_bg_env, bg_bridge, 0.40)
            else:
                bg_env = bg_bridge
            glare_zone = bg_env.point(self._glare_zone_lut)
            if params.fast_mode:
                with self._lock: self._cached_bg_env, self._cached_glare_zone, self._cached_env_key = bg_env, glare_zone, env_key
        else:
            bg_env, glare_zone = self._cached_bg_env, self._cached_glare_zone

        # 4. Exact 3x3 Sum Neighborhood Gate, Glare Compensation & Broad Shadow Suppression
        diff = ImageChops.subtract(bg_env, gray)
        s_supp = float(getattr(params, "shadow_suppression", 0.85))
        if s_supp > 0.05:
            w16, h16 = max(1, pw // 16), max(1, ph // 16)
            broad_diff = diff.resize((w16, h16), Image.Resampling.BILINEAR).filter(ImageFilter.BoxBlur(2)).resize((pw, ph), Image.Resampling.BILINEAR)
            broad_scaled = broad_diff.point(self._shadow_135_lut) if abs(s_supp - 0.85) < 0.02 else broad_diff.point([min(255, int(i * s_supp * 1.58)) for i in range(256)])
            diff_clean = ImageChops.subtract(diff, broad_scaled)
        else:
            diff_clean = diff
        sum_3x3 = diff_clean.point(self._x9_lut).filter(ImageFilter.BoxBlur(1))
        co_gate = sum_3x3.point(self._co_gate_exact_lut)
        cohesion_boost = sum_3x3.point(self._cohesion_lut)
        cohesion_masked = ImageChops.multiply(cohesion_boost, diff_clean.point(self._has_ink_lut))
        glare_boost = ImageChops.multiply(sum_3x3.point(self._glare_diff_lut), glare_zone)
        diff_adaptive = ImageChops.multiply(ImageChops.add(diff_clean, ImageChops.add(cohesion_masked, glare_boost)), co_gate)

        # 5. Tone Mapping
        lut = self._get_ink_lut(params.white_threshold, params.ink_saturation, params.gamma, params.contrast)
        if not params.fast_mode and pw >= 768:
            ink_soft = self._parallel_ssaa(diff_adaptive, lut, pw, ph)
        elif not params.fast_mode:
            ink_soft = diff_adaptive.resize((pw * 2, ph * 2), Image.Resampling.BICUBIC).point(lut).resize((pw, ph), Image.Resampling.BILINEAR)
        else:
            ink_soft = diff_adaptive.point(lut)

        # 6. Controlled Proportional Stroke Thickening
        thickening = float(np.clip(params.thickening, 0.0, 2.0))
        if thickening > 0.25:
            s_r, s_l = ImageChops.offset(ink_soft, 1, 0), ImageChops.offset(ink_soft, -1, 0)
            s_d, s_u = ImageChops.offset(ink_soft, 0, 1), ImageChops.offset(ink_soft, 0, -1)
            d4 = ImageChops.lighter(ink_soft, ImageChops.lighter(ImageChops.lighter(s_r, s_l), ImageChops.lighter(s_d, s_u)))
            ink_final = Image.blend(ink_soft, d4, min(0.65, (thickening - 0.20) * 0.45)) if thickening <= 1.2 else Image.blend(d4, d4.filter(ImageFilter.MaxFilter(3)), (thickening - 1.2) * 0.35)
        else:
            ink_final = ink_soft

        # 7. Halo-Free Micro-Sharpening
        pct_sharp = int(round(params.sharpen * (42 if getattr(params, "dual_sharpen", True) else 32)))
        ink_sharp = ink_final.filter(ImageFilter.UnsharpMask(radius=0.65, percent=pct_sharp, threshold=1)) if params.sharpen > 0.05 else ink_final

        # 8. Motion-Gated Temporal Anti-Flicker (P8)
        if params.fast_mode and getattr(params, "temporal_stability", True) and self._prev_ink is not None and self._prev_ink.size == (pw, ph):
            diff_ink = ImageChops.difference(ink_sharp, self._prev_ink)
            calm = diff_ink.point(self._anti_flicker_lut)
            ink_stabilized = Image.composite(Image.blend(self._prev_ink, ink_sharp, 0.5), ink_sharp, calm)
        else:
            ink_stabilized = ink_sharp
        if params.fast_mode:
            with self._lock: self._prev_ink = ink_stabilized

        # 9. Board Color Reconstruction with Pre-cached Layers & LUTs (P6)
        if params.invert_dark_mode:
            bg_layer = self._get_bg_layer(pw, ph, dark=True)
            ink_layer = work_img.point(self._ink_lut_dark_color) if params.preset == "color_markers" else Image.new("RGB", (pw, ph), (242, 248, 255))
            board_clean = Image.composite(ink_layer, bg_layer, ink_stabilized)
        else:
            bg_layer = self._get_bg_layer(pw, ph, dark=False)
            ink_lut = self._ink_lut_color if params.preset == "color_markers" else self._ink_lut_normal
            ink_layer = work_img.point(ink_lut)
            board_clean = Image.composite(ink_layer, bg_layer, ink_stabilized)

        # 10. Instructor Composite
        if params.preserve_instructor:
            if fut_inst:
                inst_mask = fut_inst.result()
                if params.fast_mode:
                    with self._lock: self._cached_inst_mask = inst_mask
            else:
                inst_mask = self._cached_inst_mask
            out = Image.composite(work_img, board_clean, inst_mask) if inst_mask else board_clean
        else:
            out = board_clean

        if params.fast_mode:
            with self._lock: self._last_enhanced_out, self._last_params_key, self._cache_age = out, params_key, 0
        self.last_processing_time_ms = (time.perf_counter() - t_start) * 1000.0
        return out

    def create_comparison_view(self, orig: Image.Image, enhanced: Image.Image, split_ratio: float = 0.5) -> Image.Image:
        w, h = orig.size
        if enhanced.size != (w, h): enhanced = enhanced.resize((w, h), Image.Resampling.BILINEAR)
        orig_rgb = orig.convert("RGB") if orig.mode != "RGB" else orig
        enh_rgb = enhanced.convert("RGB") if enhanced.mode != "RGB" else enhanced
        split_x = int(round(w * float(np.clip(split_ratio, 0.02, 0.98))))
        comp = Image.new("RGB", (w, h))
        comp.paste(orig_rgb.crop((0, 0, split_x, h)), (0, 0))
        comp.paste(enh_rgb.crop((split_x, 0, w, h)), (split_x, 0))
        draw = ImageDraw.Draw(comp)
        draw.line([(split_x - 1, 0), (split_x - 1, h)], fill=(20, 24, 32), width=1)
        draw.line([(split_x, 0), (split_x, h)], fill=(255, 255, 255), width=2)
        draw.line([(split_x + 2, 0), (split_x + 2, h)], fill=(20, 24, 32), width=1)
        return comp

    def compute_metrics(self, orig: Image.Image, enhanced: Image.Image, processing_time_ms: Optional[float] = None) -> Dict[str, float]:
        orig_l = np.asarray(orig.resize((160, 90), Image.Resampling.NEAREST).convert("L"), dtype=np.float32)
        enh_l = np.asarray(enhanced.resize((160, 90), Image.Resampling.NEAREST).convert("L"), dtype=np.float32)
        is_dark = float(np.mean(enh_l)) < 80.0
        bg_clean_pct = float(np.mean(enh_l < 35.0) * 100.0) if is_dark else float(np.mean(enh_l > 240.0) * 100.0)
        cr_orig = float(np.percentile(orig_l, 95)) / max(float(np.percentile(orig_l, 5)), 1.0)
        cr_enh = float(np.percentile(enh_l, 95)) / max(float(np.percentile(enh_l, 5)), 1.0)
        sharp_orig = float(np.mean(np.abs(np.diff(orig_l, axis=0))) + np.mean(np.abs(np.diff(orig_l, axis=1))))
        sharp_enh = float(np.mean(np.abs(np.diff(enh_l, axis=0))) + np.mean(np.abs(np.diff(enh_l, axis=1))))
        time_ms = processing_time_ms if processing_time_ms is not None else self.last_processing_time_ms
        return {
            "background_whiteness_pct": round(bg_clean_pct, 2),
            "contrast_ratio_orig": round(cr_orig, 2),
            "contrast_ratio_enhanced": round(cr_enh, 2),
            "contrast_improvement": round(cr_enh / max(cr_orig, 0.001), 2),
            "sharpness_orig": round(sharp_orig, 2),
            "sharpness_enhanced": round(sharp_enh, 2),
            "sharpness_improvement": round(sharp_enh / max(sharp_orig, 0.001), 2),
            "processing_time_ms": round(time_ms, 2),
        }


_default_enhancer = WhiteboardEnhancer()
def detect_whiteboard_bbox(img: Image.Image) -> Tuple[float, float, float, float]: return _default_enhancer.detect_whiteboard_bbox(img)
def enhance_whiteboard(img: Image.Image, preset: str = "clean_board", **kwargs) -> Image.Image:
    b = PRESETS.get(preset, PRESETS["clean_board"]); return _default_enhancer.enhance(img, b.copy(**kwargs) if kwargs else b)
def get_preset_params(name: str) -> EnhancementParams:
    if name not in PRESETS: raise ValueError(f"Unknown preset '{name}'")
    return PRESETS[name].copy()
def list_presets() -> List[Dict[str, Any]]:
    return [{"key": k, "name_he": PRESET_INFO.get(k, {}).get("name_he", k), "desc_he": PRESET_INFO.get(k, {}).get("desc_he", ""), "icon": PRESET_INFO.get(k, {}).get("icon", ""), "params": p.to_dict()} for k, p in PRESETS.items()]
