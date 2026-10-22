"""
Enhancement parameters and preset definitions for Qboard.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, List


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
    fast_mode: bool = False          # False = full 2x SSAA native quality
    dual_sharpen: bool = True        # dual-stage sharpening (stroke boundary + micro-contrast)

    def to_dict(self) -> Dict[str, Any]:
        """Convert parameters to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnhancementParams:
        """Create parameters from dictionary, ignoring invalid keys."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def copy(self, **kwargs: Any) -> EnhancementParams:
        """Return a copy with optionally updated fields."""
        data = self.to_dict()
        data.update(kwargs)
        return EnhancementParams.from_dict(data)


PRESETS: Dict[str, EnhancementParams] = {
    "clean_board": EnhancementParams(
        preset="clean_board",
        contrast=1.80,
        thickening=0.18,
        glare_removal=0.90,
        shadow_suppression=0.85,
        white_threshold=0.010,
        ink_saturation=0.135,
        gamma=1.12,
        sharpen=1.25,
        fast_mode=False,
        dual_sharpen=True,
    ),
    "ultra_bold": EnhancementParams(
        preset="ultra_bold",
        contrast=2.15,
        thickening=0.55,
        glare_removal=0.92,
        shadow_suppression=0.90,
        white_threshold=0.009,
        ink_saturation=0.110,
        gamma=1.18,
        sharpen=1.50,
        fast_mode=False,
        dual_sharpen=True,
    ),
    "color_markers": EnhancementParams(
        preset="color_markers",
        contrast=1.55,
        thickening=0.12,
        glare_removal=0.88,
        shadow_suppression=0.75,
        white_threshold=0.012,
        ink_saturation=0.155,
        gamma=1.08,
        sharpen=1.15,
        fast_mode=False,
        dual_sharpen=True,
    ),
    "dark_board": EnhancementParams(
        preset="dark_board",
        contrast=1.75,
        thickening=0.25,
        glare_removal=0.90,
        shadow_suppression=0.80,
        white_threshold=0.012,
        ink_saturation=0.140,
        gamma=1.14,
        sharpen=1.30,
        invert_dark_mode=True,
        fast_mode=False,
        dual_sharpen=True,
    ),
    "custom": EnhancementParams(
        preset="custom",
        contrast=1.80,
        thickening=0.18,
        glare_removal=0.90,
        shadow_suppression=0.85,
        white_threshold=0.010,
        ink_saturation=0.135,
        gamma=1.12,
        sharpen=1.25,
        fast_mode=False,
        dual_sharpen=True,
    ),
    "raw_contrast": EnhancementParams(
        preset="raw_contrast",
        contrast=1.30,
        thickening=0.0,
        glare_removal=0.60,
        shadow_suppression=0.50,
        white_threshold=0.016,
        ink_saturation=0.175,
        gamma=1.02,
        sharpen=0.95,
        fast_mode=False,
        dual_sharpen=False,
    ),
}

PRESET_INFO: Dict[str, Dict[str, str]] = {
    "clean_board": {
        "name_he": "לוח נקי (ברירת מחדל)",
        "icon": "✨",
        "desc_he": "שימור 100% מהפרטים והאותיות הדקות, הסרת בוהק והלבנת רקע טבעית",
    },
    "ultra_bold": {
        "name_he": "כתב מודגש (טושים דהויים)",
        "icon": "🖊️",
        "desc_he": "חיזוק ועיבוי מבוקר של קווים דקים וטושים חלשים ללא מחיקת פרטים",
    },
    "color_markers": {
        "name_he": "טושים צבעוניים",
        "icon": "🎨",
        "desc_he": "שמירה והגברה של צבעי טושים על רקע לבן נקי וחלק",
    },
    "dark_board": {
        "name_he": "לוח כהה (Dark Mode)",
        "icon": "🌙",
        "desc_he": "היפוך מודרני למניעת עייפות עיניים - רקע כהה וכיתוב בהיר",
    },
    "custom": {
        "name_he": "מותאם אישית",
        "icon": "⭐",
        "desc_he": "ההגדרות המותאמות אישית שלך שנשמרו לפעם הבאה",
    },
    "raw_contrast": {
        "name_he": "ניגודיות טבעית",
        "icon": "⚖️",
        "desc_he": "שיפור עדין וטבעי של ניגודיות ללא הלבנה אגרסיבית",
    },
}


def get_preset_params(name: str) -> EnhancementParams:
    """Retrieve a copy of parameters for a given preset name."""
    if name not in PRESETS:
        raise ValueError(f"Unknown preset '{name}'")
    return PRESETS[name].copy()


def list_presets() -> List[Dict[str, Any]]:
    """List all available presets with Hebrew metadata."""
    return [
        {
            "key": k,
            "name_he": PRESET_INFO.get(k, {}).get("name_he", k),
            "desc_he": PRESET_INFO.get(k, {}).get("desc_he", ""),
            "icon": PRESET_INFO.get(k, {}).get("icon", ""),
            "params": p.to_dict(),
        }
        for k, p in PRESETS.items()
    ]
