"""
Core real-time Whiteboard Image Enhancement Engine (Engine V4).
Hardware-accelerated C-SIMD / OpenCL + Sub-Macroblock Symmetric Bridge + Glare Roll-Off Recovery & Natural Grayscale.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Tuple, List, Optional
import numpy as np
from PIL import Image, ImageFilter, ImageChops, ImageDraw

try:
    import cv2
    if cv2.ocl.haveOpenCL():
        cv2.ocl.setUseOpenCL(True)
    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False

from core.params import EnhancementParams, PRESETS
from core.instructor_mask import InstructorMaskComputer
from core.board_detector import BoardDetector
from core.metrics import MetricsCalculator


class WhiteboardEnhancer:
    """Multi-Core Real-time Whiteboard Image Enhancer & Computer Vision Detector."""

    def __init__(self) -> None:
        self.last_processing_time_ms: float = 0.0
        self.last_frame_was_cached: bool = False
        self.num_workers: int = min(6, os.cpu_count() or 4)
        self._pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=self.num_workers)

        # Lookup tables for fast SIMD point transforms
        self._ink_lut_cache: Dict[Tuple[int, int, float, float], List[int]] = {}
        self._x9_lut: List[int] = [min(255, i * 9) for i in range(256)]
        self._has_ink_lut: List[int] = [0 if d <= 3 else (140 if d == 4 else 255) for d in range(256)]
        self._cohesion_lut: List[int] = [0 if s <= 8 else min(10, (s - 7) // 3) for s in range(256)]
        self._co_gate_exact_lut: List[int] = [0 if s <= 6 else (140 if s == 7 else 255) for s in range(256)]
        self._glare_zone_lut: List[int] = [min(255, max(0, (i - 162) * 6)) for i in range(256)]
        self._glare_diff_lut: List[int] = [0 if s <= 6 else min(255, (s - 6) // 2) for s in range(256)]
        self._skin_lut: List[int] = [min(255, max(0, (i - 12) * 16)) for i in range(256)]
        self._dark_gate_lut: List[int] = [min(255, max(0, (128 - i) * 10)) for i in range(256)]
        self._dark_lut: List[int] = [min(255, max(0, (132 - i) * 8)) for i in range(256)]
        self._dilate1_lut: List[int] = [min(255, int(i * 2.6)) for i in range(256)]
        self._shadow_135_lut: List[int] = [min(255, int(i * 1.35)) for i in range(256)]

        # Pre-computed morphological structuring elements and LUTs for OpenCV SIMD/GPU
        if _CV2_AVAILABLE:
            self._k5_ellipse = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            self._k_cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
            self._k3_rect = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            self._lut_x9_arr = np.array(self._x9_lut, dtype=np.uint8)
            self._lut_co_gate_arr = np.array(self._co_gate_exact_lut, dtype=np.uint8)
            self._lut_cohesion_arr = np.array(self._cohesion_lut, dtype=np.uint8)
            self._lut_has_ink_arr = np.array(self._has_ink_lut, dtype=np.uint8)
            self._lut_glare_diff_arr = np.array(self._glare_diff_lut, dtype=np.uint8)
            self._lut_shadow_arr = np.array(self._shadow_135_lut, dtype=np.uint8)
        else:
            self._k5_ellipse = None
            self._k_cross = None
            self._k3_rect = None

        # Dedicated sub-components
        self._mask_computer = InstructorMaskComputer(self._skin_lut)
        self._board_detector = BoardDetector()
        self._metrics_calc = MetricsCalculator()

        # Delta-frame & temporal envelope caches
        self._last_thumb: Optional[np.ndarray] = None
        self._last_params_key: Optional[Tuple] = None
        self._last_enhanced_out: Optional[Image.Image] = None
        self._cache_age: int = 0
        self._cached_bg_env: Optional[Image.Image] = None
        self._cached_glare_zone: Optional[Image.Image] = None
        self._cached_env_key: Optional[Tuple] = None
        self._env_tick: int = 0

    def _get_ink_lut(
        self,
        white_threshold: float,
        ink_saturation: float,
        gamma: float,
        contrast: float,
    ) -> List[int]:
        """Compute or retrieve cached look-up table for tone mapping ink curves."""
        thresh_u8 = max(2, min(7, int(round(white_threshold * 180.0))))
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
                    min(255, int(round(toe)))
                    if i == thresh_u8 + 1
                    else min(
                        255,
                        int(round(toe + (min(1.0, (i - thresh_u8) / denom) ** gamma_exp) * span)),
                    )
                )
                for i in range(256)
            ]
            self._ink_lut_cache[key] = lut
        return lut

    def _sub_macroblock_bridge(self, gray: Image.Image) -> Image.Image:
        """
        Construct illumination background bridge using hardware-accelerated morphology.
        Bridges over dark ink lines to recover smooth paper/board background illumination.
        """
        if _CV2_AVAILABLE:
            try:
                arr = np.asarray(gray)
                closed = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, self._k5_ellipse)
                smoothed = cv2.blur(closed, (2, 2))
                return Image.fromarray(smoothed)
            except Exception:
                pass

        # Fallback to pure Pillow directional bridge
        bv2 = ImageChops.darker(ImageChops.offset(gray, 0, -2), ImageChops.offset(gray, 0, 2))
        bv4 = ImageChops.darker(ImageChops.offset(gray, 0, -4), ImageChops.offset(gray, 0, 4))
        bh2 = ImageChops.darker(ImageChops.offset(gray, -2, 0), ImageChops.offset(gray, 2, 0))
        bh3 = ImageChops.darker(ImageChops.offset(gray, -3, 0), ImageChops.offset(gray, 3, 0))
        bd2 = ImageChops.lighter(
            ImageChops.darker(ImageChops.offset(gray, -2, -2), ImageChops.offset(gray, 2, 2)),
            ImageChops.darker(ImageChops.offset(gray, -2, 2), ImageChops.offset(gray, 2, -2)),
        )
        return ImageChops.lighter(
            gray,
            ImageChops.lighter(
                ImageChops.lighter(bv2, bv4),
                ImageChops.lighter(ImageChops.lighter(bh2, bh3), bd2),
            ),
        ).filter(ImageFilter.BoxBlur(0.8))

    def _compute_adaptive_gating(
        self,
        diff: Image.Image,
        bg_env: Image.Image,
        glare_zone: Image.Image,
        pw: int,
        ph: int,
        shadow_suppression: float,
    ) -> Image.Image:
        """Hardware-accelerated 3x3 sum neighborhood gate, glare compensation, and shadow suppression."""
        if _CV2_AVAILABLE:
            try:
                arr_diff = np.asarray(diff)
                arr_glare = np.asarray(glare_zone)
                if shadow_suppression > 0.05:
                    w16, h16 = max(1, pw // 16), max(1, ph // 16)
                    small_diff = cv2.resize(arr_diff, (w16, h16), interpolation=cv2.INTER_LINEAR)
                    blurred_small = cv2.blur(small_diff, (5, 5))
                    broad_cv = cv2.resize(blurred_small, (pw, ph), interpolation=cv2.INTER_LINEAR)
                    if abs(shadow_suppression - 0.85) < 0.02:
                        broad_scaled = cv2.LUT(broad_cv, self._lut_shadow_arr)
                    else:
                        lut_custom = np.array(
                            [min(255, int(i * shadow_suppression * 1.58)) for i in range(256)],
                            dtype=np.uint8,
                        )
                        broad_scaled = cv2.LUT(broad_cv, lut_custom)
                    diff_clean = cv2.subtract(arr_diff, broad_scaled)
                else:
                    diff_clean = arr_diff

                sum_3x3 = cv2.blur(cv2.LUT(diff_clean, self._lut_x9_arr), (3, 3))
                co_gate = cv2.LUT(sum_3x3, self._lut_co_gate_arr)
                cohesion_boost = cv2.LUT(sum_3x3, self._lut_cohesion_arr)
                has_ink = cv2.LUT(diff_clean, self._lut_has_ink_arr)
                cohesion_masked = cv2.multiply(cohesion_boost, has_ink, scale=1.0 / 255.0)
                glare_boost = cv2.multiply(
                    cv2.LUT(sum_3x3, self._lut_glare_diff_arr),
                    arr_glare,
                    scale=1.0 / 255.0,
                )

                boosted = cv2.add(diff_clean, cv2.add(cohesion_masked, glare_boost))
                diff_adaptive = cv2.multiply(boosted, co_gate, scale=1.0 / 255.0)
                return Image.fromarray(diff_adaptive)
            except Exception:
                pass

        # Fallback to pure Pillow
        if shadow_suppression > 0.05:
            w16, h16 = max(1, pw // 16), max(1, ph // 16)
            broad_diff = (
                diff.resize((w16, h16), Image.Resampling.BILINEAR)
                .filter(ImageFilter.BoxBlur(2))
                .resize((pw, ph), Image.Resampling.BILINEAR)
            )
            if abs(shadow_suppression - 0.85) < 0.02:
                broad_scaled = broad_diff.point(self._shadow_135_lut)
            else:
                broad_scaled = broad_diff.point(
                    [min(255, int(i * shadow_suppression * 1.58)) for i in range(256)]
                )
            diff_clean = ImageChops.subtract(diff, broad_scaled)
        else:
            diff_clean = diff

        sum_3x3 = diff_clean.point(self._x9_lut).filter(ImageFilter.BoxBlur(1))
        co_gate = sum_3x3.point(self._co_gate_exact_lut)
        cohesion_boost = sum_3x3.point(self._cohesion_lut)
        cohesion_masked = ImageChops.multiply(cohesion_boost, diff_clean.point(self._has_ink_lut))
        glare_boost = ImageChops.multiply(sum_3x3.point(self._glare_diff_lut), glare_zone)
        return ImageChops.multiply(
            ImageChops.add(diff_clean, ImageChops.add(cohesion_masked, glare_boost)),
            co_gate,
        )

    def _compute_instructor_mask(
        self,
        r: Image.Image,
        b: Image.Image,
        gray: Image.Image,
        w4: int,
        h4: int,
        pw: int,
        ph: int,
    ) -> Image.Image:
        """Worker thread entry point for instructor mask calculation."""
        return self._mask_computer.compute_mask(r, b, gray, pw, ph)

    def detect_whiteboard_bbox(self, img: Image.Image) -> Tuple[float, float, float, float]:
        """Detect whiteboard normalized coordinates in frame."""
        return self._board_detector.detect_bbox(img)

    def enhance(
        self,
        img: Image.Image,
        params: Optional[EnhancementParams] = None,
        max_process_width: Optional[int] = None,
    ) -> Image.Image:
        """
        Main whiteboard enhancement pipeline:
        1. Fast resolution check & delta-frame temporal caching
        2. Concurrent Instructor Mask detection
        3. Background illumination envelope & glare compensation (SIMD / GPU accelerated)
        4. Directional sum-neighborhood gating & shadow suppression
        5. Tone mapping & edge sharpening
        6. Clean paper-white compositing
        """
        t_start = time.perf_counter()
        if params is None:
            params = PRESETS["clean_board"]

        w, h = img.size
        if w < 16 or h < 16:
            self.last_processing_time_ms = 0.0
            self.last_frame_was_cached = False
            return img.convert("RGB") if img.mode != "RGB" else img.copy()

        src_img = img.convert("RGB") if img.mode != "RGB" else img

        params_key = None
        if params.fast_mode:
            thumb_arr = np.asarray(
                src_img.convert("L").resize((128, 72), Image.Resampling.BILINEAR),
                dtype=np.int16,
            )
            params_key = (
                w,
                h,
                max_process_width,
                params.preset,
                round(params.contrast, 3),
                round(params.thickening, 3),
                round(params.glare_removal, 3),
                round(getattr(params, "shadow_suppression", 0.85), 3),
                round(params.white_threshold, 4),
                round(params.ink_saturation, 4),
                round(params.gamma, 3),
                round(params.sharpen, 2),
                params.preserve_instructor,
                params.invert_dark_mode,
                params.denoise,
            )
            if (
                self._last_thumb is not None
                and self._last_params_key == params_key
                and self._last_enhanced_out is not None
                and self._cache_age < 12
            ):
                diff_t = np.abs(thumb_arr - self._last_thumb)
                if (
                    float(np.max(diff_t.reshape(6, 12, 8, 16).mean(axis=(1, 3)))) <= 2.8
                    and float(np.mean(diff_t)) <= 0.45
                ):
                    self.last_frame_was_cached = True
                    self._cache_age += 1
                    self.last_processing_time_ms = (time.perf_counter() - t_start) * 1000.0
                    return self._last_enhanced_out
            self._last_thumb = thumb_arr
            self._cache_age = 0
            self.last_frame_was_cached = False
        else:
            self._cache_age = 0
            self.last_frame_was_cached = False

        # Native resolution handling: never downsample below 1920 to keep crystal clarity
        if max_process_width is not None and w > max_process_width and max_process_width >= 1920:
            pw = max_process_width
            ph = max(1, int(round(h * (pw / w))))
            work_img = src_img.resize((pw, ph), Image.Resampling.BILINEAR)
        else:
            pw, ph = w, h
            work_img = src_img

        r, g, b = work_img.split()
        gray = work_img.convert("L")
        w4, h4 = max(1, pw // 4), max(1, ph // 4)
        w8, h8 = max(1, pw // 8), max(1, ph // 8)

        # 2. Concurrently submit Instructor Mask to Worker Core
        fut_inst = (
            self._pool.submit(self._compute_instructor_mask, r, b, gray, w4, h4, pw, ph)
            if params.preserve_instructor
            else None
        )

        # 3. Sub-Macroblock Symmetric Bridge Envelope (Cached for 8 frames if static)
        env_key = (pw, ph, round(params.glare_removal, 2))
        need_env = (
            self._cached_env_key != env_key
            or self._cached_bg_env is None
            or (self._env_tick % 8 == 0)
        )
        self._env_tick += 1

        if need_env:
            bg_env = self._sub_macroblock_bridge(gray)
            if params.glare_removal < 0.89:
                bg_ambient = (
                    gray.resize((w8, h8), Image.Resampling.BILINEAR)
                    .filter(ImageFilter.BoxBlur(3))
                    .resize((pw, ph), Image.Resampling.BILINEAR)
                )
                bg_env = Image.blend(
                    bg_ambient,
                    bg_env,
                    float(np.clip(params.glare_removal / 0.90, 0.0, 1.0)),
                )
            glare_zone = bg_env.point(self._glare_zone_lut)
            self._cached_bg_env = bg_env
            self._cached_glare_zone = glare_zone
            self._cached_env_key = env_key
        else:
            bg_env = self._cached_bg_env
            glare_zone = self._cached_glare_zone

        # 4. Hardware-Accelerated Exact 3x3 Sum Neighborhood Gate, Glare & Shadow Suppression
        diff = ImageChops.subtract(bg_env, gray)
        diff_adaptive = self._compute_adaptive_gating(
            diff=diff,
            bg_env=bg_env,
            glare_zone=glare_zone,
            pw=pw,
            ph=ph,
            shadow_suppression=float(getattr(params, "shadow_suppression", 0.85)),
        )

        # 5. Pixel-Perfect 1:1 Direct Tone Mapping
        lut = self._get_ink_lut(
            params.white_threshold,
            params.ink_saturation,
            params.gamma,
            params.contrast,
        )
        ink_soft = diff_adaptive.point(lut)

        # 6. Controlled Proportional Stroke Thickening (Hardware-accelerated)
        thickening = float(np.clip(params.thickening, 0.0, 2.0))
        if thickening > 0.25:
            if _CV2_AVAILABLE:
                try:
                    arr_ink = np.asarray(ink_soft)
                    d4_arr = cv2.dilate(arr_ink, self._k_cross)
                    if thickening <= 1.2:
                        alpha = min(0.65, (thickening - 0.20) * 0.45)
                        ink_final_arr = cv2.addWeighted(arr_ink, 1.0 - alpha, d4_arr, alpha, 0)
                    else:
                        d4_max = cv2.dilate(d4_arr, self._k3_rect)
                        alpha = (thickening - 1.2) * 0.35
                        ink_final_arr = cv2.addWeighted(d4_arr, 1.0 - alpha, d4_max, alpha, 0)
                    ink_final = Image.fromarray(ink_final_arr)
                except Exception:
                    # Pillow fallback
                    s_r = ImageChops.offset(ink_soft, 1, 0)
                    s_l = ImageChops.offset(ink_soft, -1, 0)
                    s_d = ImageChops.offset(ink_soft, 0, 1)
                    s_u = ImageChops.offset(ink_soft, 0, -1)
                    d4 = ImageChops.lighter(
                        ink_soft,
                        ImageChops.lighter(ImageChops.lighter(s_r, s_l), ImageChops.lighter(s_d, s_u)),
                    )
                    ink_final = Image.blend(ink_soft, d4, min(0.65, (thickening - 0.20) * 0.45))
            else:
                s_r = ImageChops.offset(ink_soft, 1, 0)
                s_l = ImageChops.offset(ink_soft, -1, 0)
                s_d = ImageChops.offset(ink_soft, 0, 1)
                s_u = ImageChops.offset(ink_soft, 0, -1)
                d4 = ImageChops.lighter(
                    ink_soft,
                    ImageChops.lighter(ImageChops.lighter(s_r, s_l), ImageChops.lighter(s_d, s_u)),
                )
                if thickening <= 1.2:
                    ink_final = Image.blend(ink_soft, d4, min(0.65, (thickening - 0.20) * 0.45))
                else:
                    ink_final = Image.blend(d4, d4.filter(ImageFilter.MaxFilter(3)), (thickening - 1.2) * 0.35)
        else:
            ink_final = ink_soft

        # 7. Halo-Free Micro-Sharpening (Hardware-accelerated)
        pct_sharp = params.sharpen * (0.42 if getattr(params, "dual_sharpen", True) else 0.32)
        if params.sharpen > 0.05:
            if _CV2_AVAILABLE:
                try:
                    arr_ink = np.asarray(ink_final)
                    blurred = cv2.GaussianBlur(arr_ink, (3, 3), 0.65)
                    sharp_arr = cv2.addWeighted(arr_ink, 1.0 + pct_sharp, blurred, -pct_sharp, 0)
                    ink_sharp = Image.fromarray(sharp_arr)
                except Exception:
                    pct_int = int(round(pct_sharp * 100))
                    ink_sharp = ink_final.filter(ImageFilter.UnsharpMask(radius=0.65, percent=pct_int, threshold=1))
            else:
                pct_int = int(round(pct_sharp * 100))
                ink_sharp = ink_final.filter(ImageFilter.UnsharpMask(radius=0.65, percent=pct_int, threshold=1))
        else:
            ink_sharp = ink_final

        # 8. Board Color Reconstruction
        if params.invert_dark_mode:
            bg_layer = Image.new("RGB", (pw, ph), (18, 22, 31))
            if params.preset == "color_markers":
                ink_layer = work_img.point([min(255, int(i * 1.3 + 40)) for i in range(256)] * 3)
            else:
                ink_layer = Image.new("RGB", (pw, ph), (242, 248, 255))
            board_clean = Image.composite(ink_layer, bg_layer, ink_sharp)
        else:
            bg_layer = Image.new("RGB", (pw, ph), (255, 255, 255))
            if params.preset == "color_markers":
                # High-contrast non-linear color curve: boosts colored marker depth and saturation
                marker_lut = [min(255, int(pow(i / 255.0, 1.35) * 125)) for i in range(256)] * 3
                ink_layer = work_img.point(marker_lut)
            else:
                ink_scale = 0.14
                ink_layer = work_img.point([int(i * ink_scale) for i in range(256)] * 3)
            board_clean = Image.composite(ink_layer, bg_layer, ink_sharp)

        # 9. Instructor Composite (retrieve result from worker core)
        if fut_inst:
            out = Image.composite(work_img, board_clean, fut_inst.result())
        else:
            out = board_clean

        if params.fast_mode:
            self._last_enhanced_out = out
            self._last_params_key = params_key
            self._cache_age = 0

        self.last_processing_time_ms = (time.perf_counter() - t_start) * 1000.0
        return out

    def create_comparison_view(
        self,
        orig: Image.Image,
        enhanced: Image.Image,
        split_ratio: float = 0.5,
    ) -> Image.Image:
        """Create a side-by-side split comparison view between original and enhanced."""
        w, h = orig.size
        if enhanced.size != (w, h):
            enhanced = enhanced.resize((w, h), Image.Resampling.BILINEAR)

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

    def compute_metrics(
        self,
        orig: Image.Image,
        enhanced: Image.Image,
        processing_time_ms: Optional[float] = None,
    ) -> Dict[str, float]:
        """Compute quantitative metrics on board whiteness, contrast, and sharpness."""
        time_ms = processing_time_ms if processing_time_ms is not None else self.last_processing_time_ms
        return self._metrics_calc.compute(orig, enhanced, time_ms)
