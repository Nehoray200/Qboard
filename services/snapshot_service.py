"""
Composite snapshot capture and clipboard export service.
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Optional, Any
from PIL import Image

from ui.theme import copy_image_to_clipboard, open_folder_in_explorer


class SnapshotService:
    """Manages full composite snapshot capturing, storage, and clipboard exports."""

    @staticmethod
    def save_composite_snapshot(app: Any, out_dir: Optional[str] = None) -> str:
        """
        Capture and compose a realistic screenshot matching exactly what the user sees:
        - The underlying desktop screen/Zoom meeting background is captured cleanly in full.
        - The enhanced whiteboard is composited directly into the whiteboard position.
        - The rest of the screen, classroom, lecturer and background remains natural.
        - Automatically saves high-res PNG to captures/ and copies to Windows Clipboard.
        """
        captures_dir = out_dir if out_dir else os.path.join(os.getcwd(), "captures")
        os.makedirs(captures_dir, exist_ok=True)
        filename = f"zoom_screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(captures_dir, filename)

        # 1. Full un-cropped background of the screen/window
        bg_full = app.capture_manager.capture_full_background()

        # 2. Get the whiteboard frame
        raw_board = (
            app.current_frame_orig
            if app.current_frame_orig is not None
            else app.capture_manager.capture_frame()
        )

        # 3. Enhance whiteboard
        if app.view_mode == "original":
            enhanced_board = raw_board
        else:
            enhanced_board = app.enhancer.enhance(
                raw_board,
                app.current_params.copy(fast_mode=False),
                max_process_width=2560,
            )
            if app.view_mode == "split":
                enhanced_board = app.enhancer.create_comparison_view(
                    raw_board, enhanced_board, app.split_ratio
                )

        # 4. Composite the enhanced board onto the full background
        composite_image = bg_full.copy()
        bw, bh = bg_full.size

        if app.capture_manager.board_crop_norm:
            x1, y1, x2, y2 = app.capture_manager.board_crop_norm
            px1, py1 = int(round(x1 * bw)), int(round(y1 * bh))
            px2, py2 = int(round(x2 * bw)), int(round(y2 * bh))
            target_w, target_h = max(10, px2 - px1), max(10, py2 - py1)
            board_resized = enhanced_board.resize((target_w, target_h), Image.Resampling.LANCZOS)
            composite_image.paste(board_resized, (px1, py1))
        elif app.capture_manager.region_bbox:
            rx1, ry1, rx2, ry2 = app.capture_manager.region_bbox
            target_w, target_h = max(10, rx2 - rx1), max(10, ry2 - ry1)
            board_resized = enhanced_board.resize((target_w, target_h), Image.Resampling.LANCZOS)
            px = max(0, min(bw - target_w, rx1))
            py = max(0, min(bh - target_h, ry1))
            composite_image.paste(board_resized, (px, py))
        elif (
            app.active_source_type in ("region", "window")
            and not getattr(app, "headless", False)
            and app.root.winfo_exists()
        ):
            try:
                wx = app.root.winfo_rootx()
                wy = app.root.winfo_rooty()
                ww = app.root.winfo_width()
                wh = app.root.winfo_height()
                if ww > 20 and wh > 20 and (ww < bw or wh < bh):
                    board_resized = enhanced_board.resize((ww, wh), Image.Resampling.LANCZOS)
                    px = max(0, min(bw - ww, wx))
                    py = max(0, min(bh - wh, wy))
                    composite_image.paste(board_resized, (px, py))
                else:
                    composite_image = enhanced_board.resize((bw, bh), Image.Resampling.LANCZOS)
            except Exception:
                composite_image = enhanced_board.resize((bw, bh), Image.Resampling.LANCZOS)
        else:
            composite_image = enhanced_board.resize((bw, bh), Image.Resampling.LANCZOS)

        composite_image.save(filepath, "PNG")

        owner_hwnd = None
        if not getattr(app, "headless", False) and app.root.winfo_exists():
            try:
                owner_hwnd = app.root.winfo_id()
            except Exception:
                pass

        clip_ok = copy_image_to_clipboard(composite_image, owner_hwnd)
        if clip_ok:
            msg = "📸 צילום משולב נשמר והועתק ללוח! הדבק בצ'אט (Ctrl+V)"
        else:
            msg = f"📸 צילום משולב נשמר: {os.path.basename(filepath)}"
        app.show_toast(msg)

        return os.path.abspath(filepath)

    @staticmethod
    def open_captures_folder() -> None:
        """Open the captures directory in Windows File Explorer."""
        captures_dir = os.path.join(os.getcwd(), "captures")
        os.makedirs(captures_dir, exist_ok=True)
        open_folder_in_explorer(captures_dir)
