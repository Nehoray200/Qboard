"""
Computer vision based automatic whiteboard boundary detection.
"""

from __future__ import annotations

from typing import Tuple
import numpy as np
from PIL import Image


class BoardDetector:
    """Detects physical whiteboard bounds inside a classroom / Zoom video frame."""

    @staticmethod
    def detect_bbox(img: Image.Image) -> Tuple[float, float, float, float]:
        """
        Detect normalized coordinates (x1, y1, x2, y2) of the whiteboard in the image.
        Returns values between 0.0 and 1.0.
        """
        dw, dh = 256, 144
        arr = np.asarray(
            img.convert("RGB").resize((dw, dh), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )

        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        sat = np.max(arr, axis=2) - np.min(arr, axis=2)
        dy = np.abs(np.diff(lum, axis=0, prepend=lum[:1, :]))
        row_edge = np.mean(dy, axis=1)
        row_lum = np.mean(lum, axis=1)

        # 1. Top edge candidate selection
        r_top_min = int(0.15 * dh)
        r_top_max = int(0.42 * dh)
        top_thresh = max(
            float(np.percentile(row_edge, 75)),
            float(np.percentile(row_edge[r_top_min:r_top_max], 60)),
        )
        candidates = [
            r for r in range(r_top_min, r_top_max)
            if row_edge[r] > top_thresh and float(np.mean(row_lum[r + 2 : min(dh, r + 18)])) > 132.0
        ]
        if candidates:
            filtered = [r for r in candidates if abs(r - candidates[-1]) <= 2]
            y1 = max(filtered, key=lambda r: row_edge[r])
        else:
            y1 = int(0.20 * dh)

        # 2. Bottom edge candidate selection
        r_bot_min = int(0.58 * dh)
        r_bot_max = int(0.92 * dh)
        y2 = r_bot_min + int(np.argmax(row_edge[r_bot_min:r_bot_max]))

        # 3. Left and right edge detection
        col_lum = np.mean(lum[y1:y2, :], axis=0)
        col_sat = np.mean(sat[y1:y2, :], axis=0)
        col_edge = np.mean(np.abs(np.diff(lum[y1:y2, :], axis=1, prepend=lum[y1:y2, :1])), axis=0)

        bright_cols = np.where((col_lum > 128.0) & (col_sat < 42.0))[0]
        x1 = int(bright_cols[0]) if len(bright_cols) > 0 else int(0.03 * dw)
        lp = int(np.argmax(col_edge[: int(0.18 * dw)]))
        if col_edge[lp] > np.percentile(col_edge, 80) and lp > x1:
            x1 = lp

        rp = int(0.85 * dw) + int(np.argmax(col_edge[int(0.85 * dw) : int(0.99 * dw)]))
        x2 = int(bright_cols[-1]) if len(bright_cols) > 0 else int(0.97 * dw)
        if col_edge[rp] > np.percentile(col_edge, 80) and rp < x2:
            x2 = rp

        # 4. Guard inset: clear boundary aluminum rails and jagged frame edges
        y1 = min(int(0.48 * dh), y1 + 2)
        y2 = max(y1 + 10, y2 - 1)
        x1 = min(int(0.20 * dw), x1 + 1)
        x2 = max(x1 + 20, x2 - 1)

        x1_n = float(x1) / dw
        y1_n = float(y1) / dh
        x2_n = float(x2) / dw
        y2_n = float(y2) / dh

        if (
            len(bright_cols) == 0
            or (x2_n - x1_n < 0.25)
            or (y2_n - y1_n < 0.20)
            or (x1_n >= x2_n)
            or (y1_n >= y2_n)
        ):
            return (0.03, 0.18, 0.97, 0.82)

        return (
            round(max(0.0, min(1.0, x1_n)), 4),
            round(max(0.0, min(1.0, y1_n)), 4),
            round(max(0.0, min(1.0, x2_n)), 4),
            round(max(0.0, min(1.0, y2_n)), 4),
        )
