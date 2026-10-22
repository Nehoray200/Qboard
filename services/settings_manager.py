"""
Settings persistence service for Qboard.
Handles saving and loading of user presets, custom parameters,
toggles, and locked geometry to local app data JSON.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Any, Optional

from core.params import EnhancementParams, PRESETS, PRESET_INFO

logger = logging.getLogger("qboard")


class SettingsManager:
    """Manages persistent configuration and custom user presets."""

    def __init__(self, app_dir: Optional[str] = None) -> None:
        self.app_dir = app_dir or self._discover_app_dir()
        self.settings_file = os.path.join(self.app_dir, "settings.json")
        self._init_logging()

    def _discover_app_dir(self) -> str:
        """Find a reliable writable directory for settings and logs."""
        candidates = [
            os.path.join(os.environ.get("APPDATA") or "", "Qboard"),
            os.path.join(os.path.expanduser("~"), ".qboard"),
            os.path.join(os.getcwd(), ".qboard"),
            os.path.join(os.environ.get("APPDATA") or "", "ZoomPlus"),
        ]
        for c in candidates:
            if not c:
                continue
            try:
                os.makedirs(c, exist_ok=True)
                test_file = os.path.join(c, ".write_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                return c
            except Exception:
                continue
        return os.getcwd()

    def _init_logging(self) -> None:
        try:
            log_path = os.path.join(self.app_dir, "qboard.log")
            logging.basicConfig(
                filename=log_path,
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
            )
        except Exception:
            pass

    def load_settings(self, app: Any) -> None:
        """Load saved presets, sliders, toggles, and geometry into app."""
        if not os.path.exists(self.settings_file):
            return

        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                d: Dict[str, Any] = json.load(f)

            if d.get("version") != 4:
                return

            if "custom_preset" in d:
                try:
                    PRESETS["custom"] = EnhancementParams.from_dict(d["custom_preset"])
                except Exception:
                    pass

            if d.get("preset") in PRESETS:
                app.apply_preset(d["preset"], update_sliders=False)

            sliders = d.get("sliders", {})
            for k, v in sliders.items():
                if k in app._slider_map:
                    var, lbl, fmt = app._slider_map[k]
                    var.set(v)
                    lbl.set(fmt.format(v))
                    setattr(app.current_params, k, v)

            toggles = d.get("toggles", {})
            for k, v in toggles.items():
                if k != "exclude_capture" and hasattr(app, f"var_{k}"):
                    getattr(app, f"var_{k}").set(v)
                    app._on_toggle_change(k)

            if d.get("last_locked_geometry"):
                app._last_locked_geometry = d["last_locked_geometry"]

            last_source = d.get("last_source_type")
            if last_source and last_source not in ("demo",):
                app.active_source_type = last_source
                if app.active_source_type == "region" and app._last_locked_geometry:
                    try:
                        parts = (
                            app._last_locked_geometry.replace("+", " ")
                            .replace("x", " ")
                            .split()
                        )
                        if len(parts) == 4:
                            gw, gh, gx, gy = map(int, parts)
                            if gw > 50 and gh > 50:
                                app.capture_manager.set_region((gx, gy, gx + gw, gy + gh))
                                app.root.geometry(app._last_locked_geometry)
                    except Exception:
                        app.active_source_type = "screen"

        except Exception as e:
            logger.warning(f"Settings load error: {e}")

    def save_settings(self, app: Any) -> None:
        """Persist current configuration to settings.json."""
        if getattr(app, "headless", False):
            return

        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            t_keys = (
                "fast_mode",
                "preserve_instructor",
                "invert_dark_mode",
                "denoise",
                "click_through",
                "trim_browser_header",
            )
            sliders = {k: app._slider_map[k][0].get() for k in app._slider_map}
            toggles = {
                k: getattr(app, f"var_{k}").get()
                for k in t_keys
                if hasattr(app, f"var_{k}")
            }

            d = {
                "version": 4,
                "preset": app.current_preset,
                "sliders": sliders,
                "toggles": toggles,
                "custom_preset": PRESETS.get("custom", PRESETS["clean_board"]).to_dict(),
                "last_source_type": app.active_source_type,
                "last_locked_geometry": getattr(app, "_last_locked_geometry", None),
            }

            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)

        except Exception as e:
            logger.warning(f"Settings save error: {e}")

    def save_custom_preset(self, app: Any) -> None:
        """Save current slider values & toggles as the custom preset."""
        t_keys = (
            "fast_mode",
            "preserve_instructor",
            "invert_dark_mode",
            "denoise",
            "click_through",
            "trim_browser_header",
        )
        sliders = {k: app._slider_map[k][0].get() for k in app._slider_map}
        toggles = {
            k: getattr(app, f"var_{k}").get()
            for k in t_keys
            if hasattr(app, f"var_{k}")
        }

        p = app.current_params.copy(preset="custom", **sliders, **toggles)
        PRESETS["custom"] = p
        app.current_preset = "custom"
        app.preset_desc_var.set(PRESET_INFO["custom"]["desc_he"])
        self.save_settings(app)
