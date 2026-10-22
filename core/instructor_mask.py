"""
Instructor presence and body silhouette mask computation.
Preserves lecturer's natural skin tone, clothing, and body contours
without gray halos around edges, while keeping whiteboard ink clear.
"""

from __future__ import annotations

from typing import List, Optional
import numpy as np
from PIL import Image, ImageChops, ImageFilter


class InstructorMaskComputer:
    """Computes accurate lecturer foreground masks for whiteboard compositing."""

    def __init__(self, skin_lut: Optional[List[int]] = None) -> None:
        if skin_lut is None:
            self._skin_lut: List[int] = [min(255, max(0, (i - 12) * 16)) for i in range(256)]
        else:
            self._skin_lut = skin_lut
        self._body_lut: List[int] = [255 if i < 130 else 0 for i in range(256)]

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
        if float(np.mean(np.array(g_small))) < 90.0:
            return Image.new("L", (pw, ph), 255)

        # 1. Skin tone detection (difference between red and blue channels)
        skin = ImageChops.subtract(r, b).point(self._skin_lut)

        # 2. 8x macro space for solid human silhouette (shirt, torso, limbs)
        # Threshold up to 130 captures the illuminated shirt completely without hollowing out
        w8 = max(1, pw // 8)
        h8 = max(1, ph // 8)
        g8 = gray.resize((w8, h8), Image.Resampling.BILINEAR)
        dark8 = g8.point(self._body_lut)

        # Morphological opening (Min 3, Max 3 -> net 0 expansion):
        # Requires > 24px thickness (ink lines vanish, shirt & body 100% kept)
        dark_body = (
            dark8.filter(ImageFilter.MinFilter(3))
            .filter(ImageFilter.MaxFilter(3))
            .resize((pw, ph), Image.Resampling.BILINEAR)
        )
        dark_body_tight = dark_body.point(lambda p: 255 if p >= 128 else 0)

        # 3. Combine skin & body
        combined = ImageChops.lighter(skin, dark_body_tight)
        return combined.point(lambda p: 255 if p >= 128 else 0)
