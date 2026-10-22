"""
Instructor presence and body silhouette mask computation.
Preserves lecturer's natural skin tone, clothing, and body contours
without gray halos around edges, while keeping whiteboard ink clear.
Hardware-accelerated SIMD / GPU morphology with clean Pillow fallback.
"""

from __future__ import annotations

from typing import List, Optional
import numpy as np
from PIL import Image, ImageChops, ImageFilter

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False


class InstructorMaskComputer:
    """Computes accurate lecturer foreground masks for whiteboard compositing."""

    def __init__(self, skin_lut: Optional[List[int]] = None) -> None:
        if skin_lut is None:
            self._skin_lut: List[int] = [min(255, max(0, (i - 12) * 16)) for i in range(256)]
        else:
            self._skin_lut = skin_lut
        self._body_lut: List[int] = [255 if i < 130 else 0 for i in range(256)]
        self._binary_lut: List[int] = [255 if i >= 128 else 0 for i in range(256)]

        if _CV2_AVAILABLE:
            self._k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            self._skin_lut_arr = np.array(self._skin_lut, dtype=np.uint8)
        else:
            self._k3 = None
            self._skin_lut_arr = None

    def compute_mask(
        self,
        r: Image.Image,
        b: Image.Image,
        gray: Image.Image,
        pw: int,
        ph: int,
    ) -> Image.Image:
        """
        Compute binary mask where 255 represents lecturer/person
        and 0 represents the whiteboard.
        """
        # If the frame has a dark background (e.g. File Explorer, IDE, dark theme desktop),
        # it is not a whiteboard; preserve 100% original sharpness with zero alteration.
        if _CV2_AVAILABLE:
            try:
                g_arr = np.asarray(gray)
                # Fast sampled mean check for dark theme
                if float(np.mean(g_arr[::16, ::16])) < 90.0:
                    return Image.new("L", (pw, ph), 255)

                r_arr = np.asarray(r)
                b_arr = np.asarray(b)

                # 2x downsample for ultra-fast SIMD processing (4x fewer pixels, 0 perceptible silhouette loss)
                w2, h2 = max(1, pw // 2), max(1, ph // 2)
                r2 = cv2.resize(r_arr, (w2, h2), interpolation=cv2.INTER_AREA)
                b2 = cv2.resize(b_arr, (w2, h2), interpolation=cv2.INTER_AREA)
                g2 = cv2.resize(g_arr, (w2, h2), interpolation=cv2.INTER_AREA)

                # 1. Skin tone detection (SIMD vector difference + hardware LUT)
                diff2 = cv2.subtract(r2, b2)
                skin2 = cv2.LUT(diff2, self._skin_lut_arr)

                # 2. 8x macro space for solid human silhouette (shirt, torso, limbs)
                w8, h8 = max(1, pw // 8), max(1, ph // 8)
                g8_arr2 = cv2.resize(g2, (w8, h8), interpolation=cv2.INTER_AREA)
                dark8_arr2 = (g8_arr2 < 130).astype(np.uint8) * 255
                opened8_2 = cv2.morphologyEx(dark8_arr2, cv2.MORPH_OPEN, self._k3)
                dark_body_half = cv2.resize(opened8_2, (w2, h2), interpolation=cv2.INTER_LINEAR)
                dark_body_half_tight = (dark_body_half >= 128).astype(np.uint8) * 255

                # 3. Combine skin & body silhouette
                comb2 = cv2.max(skin2, dark_body_half_tight)
                mask2_bin = (comb2 >= 128).astype(np.uint8) * 255
                mask_cv_full = cv2.resize(mask2_bin, (pw, ph), interpolation=cv2.INTER_NEAREST)
                return Image.fromarray(mask_cv_full)
            except Exception:
                pass

        # Fallback to pure Pillow
        g_small = gray.resize((64, 36), Image.Resampling.NEAREST)
        if float(np.mean(np.asarray(g_small))) < 90.0:
            return Image.new("L", (pw, ph), 255)

        # 1. Skin tone detection (difference between red and blue channels)
        skin = ImageChops.subtract(r, b).point(self._skin_lut)

        # 2. 8x macro space for solid human silhouette (shirt, torso, limbs)
        w8 = max(1, pw // 8)
        h8 = max(1, ph // 8)
        g8 = gray.resize((w8, h8), Image.Resampling.BILINEAR)

        dark8 = g8.point(self._body_lut)
        dark_body = (
            dark8.filter(ImageFilter.MinFilter(3))
            .filter(ImageFilter.MaxFilter(3))
            .resize((pw, ph), Image.Resampling.BILINEAR)
        )
        dark_body_tight = dark_body.point(self._binary_lut)

        # 3. Combine skin & body
        combined = ImageChops.lighter(skin, dark_body_tight)
        return combined.point(self._binary_lut)
