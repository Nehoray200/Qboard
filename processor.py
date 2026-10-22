"""
Qboard Whiteboard Enhancement Engine V4 (processor.py)
======================================================
Facade for core whiteboard processing components.
Maintains full backward-compatibility with all existing imports.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, List
from PIL import Image

from core import (
    EnhancementParams,
    PRESETS,
    PRESET_INFO,
    get_preset_params,
    list_presets,
    WhiteboardEnhancer,
    BoardDetector,
    InstructorMaskComputer,
    MetricsCalculator,
)

_default_enhancer = WhiteboardEnhancer()


def detect_whiteboard_bbox(img: Image.Image) -> Tuple[float, float, float, float]:
    """Detect bounding box of whiteboard in frame (normalized coordinates)."""
    return _default_enhancer.detect_whiteboard_bbox(img)


def enhance_whiteboard(
    img: Image.Image,
    preset: str = "clean_board",
    **kwargs: Any,
) -> Image.Image:
    """Enhance a whiteboard image using named preset and optional overrides."""
    base_params = PRESETS.get(preset, PRESETS["clean_board"])
    params = base_params.copy(**kwargs) if kwargs else base_params
    return _default_enhancer.enhance(img, params)


__all__ = [
    "EnhancementParams",
    "PRESETS",
    "PRESET_INFO",
    "get_preset_params",
    "list_presets",
    "WhiteboardEnhancer",
    "BoardDetector",
    "InstructorMaskComputer",
    "MetricsCalculator",
    "detect_whiteboard_bbox",
    "enhance_whiteboard",
]
