"""
Quantitative quality telemetry and enhancement metrics calculation.
"""

from __future__ import annotations

from typing import Dict, Optional
import numpy as np
from PIL import Image


class MetricsCalculator:
    """Calculates contrast, sharpness, and whiteness improvements."""

    @staticmethod
    def compute(
        orig: Image.Image,
        enhanced: Image.Image,
        processing_time_ms: float = 0.0,
    ) -> Dict[str, float]:
        """Compute comparative quality metrics between original and enhanced images."""
        orig_l = np.asarray(
            orig.resize((160, 90), Image.Resampling.NEAREST).convert("L"),
            dtype=np.float32,
        )
        enh_l = np.asarray(
            enhanced.resize((160, 90), Image.Resampling.NEAREST).convert("L"),
            dtype=np.float32,
        )

        is_dark = float(np.mean(enh_l)) < 80.0
        if is_dark:
            bg_clean_pct = float(np.mean(enh_l < 35.0) * 100.0)
        else:
            bg_clean_pct = float(np.mean(enh_l > 240.0) * 100.0)

        cr_orig = float(np.percentile(orig_l, 95)) / max(float(np.percentile(orig_l, 5)), 1.0)
        cr_enh = float(np.percentile(enh_l, 95)) / max(float(np.percentile(enh_l, 5)), 1.0)

        sharp_orig = float(
            np.mean(np.abs(np.diff(orig_l, axis=0)))
            + np.mean(np.abs(np.diff(orig_l, axis=1)))
        )
        sharp_enh = float(
            np.mean(np.abs(np.diff(enh_l, axis=0)))
            + np.mean(np.abs(np.diff(enh_l, axis=1)))
        )

        return {
            "background_whiteness_pct": round(bg_clean_pct, 2),
            "contrast_ratio_orig": round(cr_orig, 2),
            "contrast_ratio_enhanced": round(cr_enh, 2),
            "contrast_improvement": round(cr_enh / max(cr_orig, 0.001), 2),
            "sharpness_orig": round(sharp_orig, 2),
            "sharpness_enhanced": round(sharp_enh, 2),
            "sharpness_improvement": round(sharp_enh / max(sharp_orig, 0.001), 2),
            "processing_time_ms": round(processing_time_ms, 2),
        }
