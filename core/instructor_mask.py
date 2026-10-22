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
        else:
            self._k3 = None

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
        g_small = gray.resize((64, 36), Image.Resampling.NEAREST)
        if float(np.mean(np.asarray(g_small))) < 90.0:
            return Image.new("L", (pw, ph), 255)

        # 1. Skin tone detection (difference between red and blue channels)
        skin = ImageChops.subtract(r, b).point(self._skin_lut)

        # 2. 8x macro space for solid human silhouette (shirt, torso, limbs)
        w8 = max(1, pw // 8)
        h8 = max(1, ph // 8)
        g8 = gray.resize((w8, h8), Image.Resampling.BILINEAR)

        if _CV2_AVAILABLE:
            try:
                g8_arr = np.asarray(g8)
                dark8_arr = np.where(g8_arr < 130, 255, 0).astype(np.uint8)
                opened_arr = cv2.morphologyEx(dark8_arr, cv2.MORPH_OPEN, self._k3)
                dark_body_tight = (
                    Image.fromarray(opened_arr)
                    .resize((pw, ph), Image.Resampling.BILINEAR)
                    .point(self._binary_lut)
                )
            except Exception:
                dark8 = g8.point(self._body_lut)
                dark_body = (
                    dark8.filter(ImageFilter.MinFilter(3))
                    .filter(ImageFilter.MaxFilter(3))
                    .resize((pw, ph), Image.Resampling.BILINEAR)
                )
                dark_body_tight = dark_body.point(self._binary_lut)
        else:
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
