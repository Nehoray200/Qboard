"""
Canvas rendering component for Qboard overlay window.
Draws enhanced video frames, interactive split sliders, 2.5x loupe, HUD badges, and toasts.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Tuple
from PIL import Image, ImageTk, ImageDraw

from ui.theme import (
    CLR_BG_ROOT,
    CLR_BG_TOOLBAR,
    CLR_BORDER,
    CLR_ACCENT,
    CLR_TEXT_MUTED,
    FONT_FAMILY,
    FONT_BODY_BOLD,
    FONT_BADGE,
)


class CanvasRenderer:
    """Renders processed video, overlays, HUD, and toasts to Tkinter Canvas."""

    def __init__(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.current_tk_photo: Optional[ImageTk.PhotoImage] = None
        self.loupe_tk_photo: Optional[ImageTk.PhotoImage] = None
        self.canvas_layout: Tuple[int, int, int, int, float] = (0, 0, 800, 450, 1.0)
        self._last_canvas_size: Optional[Tuple[int, int]] = None
        self._rendered_frame_seq: int = -1

    def render_frame(
        self,
        processed_frame: Optional[Image.Image],
        frame_seq: int,
        view_mode: str,
        split_ratio: float,
        toast_message: Optional[str] = None,
        last_frame_was_cached: bool = False,
    ) -> None:
        """Render the processed video frame with proper scaling and overlays."""
        if processed_frame is None or not self.canvas.winfo_exists():
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        iw, ih = processed_frame.size

        if cw < 30 or ch < 30 or iw < 10 or ih < 10:
            return

        # Avoid redundant redraws when frame is cached and size is unchanged
        if (
            last_frame_was_cached
            and self._rendered_frame_seq == frame_seq
            and (cw, ch) == self._last_canvas_size
            and view_mode == "enhanced"
        ):
            if toast_message:
                self.render_toast(toast_message)
            return

        # Calculate aspect-ratio preserving display dimensions
        if abs(cw - iw) <= 2 and abs(ch - ih) <= 2:
            dw, dh, ox, oy, scale = iw, ih, 0, 0, 1.0
        else:
            scale = max(0.01, min(cw / float(iw), ch / float(ih)))
            dw = int(round(iw * scale))
            dh = int(round(ih * scale))
            ox = (cw - dw) // 2
            oy = (ch - dh) // 2

        self.canvas_layout = (ox, oy, dw, dh, scale)

        if (dw, dh) == (iw, ih):
            img_to_show = processed_frame
        else:
            img_to_show = processed_frame.resize((dw, dh), Image.Resampling.LANCZOS)

        self.current_tk_photo = ImageTk.PhotoImage(img_to_show)
        self._rendered_frame_seq = frame_seq
        self._last_canvas_size = (cw, ch)

        self.canvas.delete("video_frame")
        self.canvas.delete("split_hud")
        self.canvas.create_image(ox, oy, anchor="nw", image=self.current_tk_photo, tags="video_frame")

        if view_mode == "split":
            self._render_split_decorations(ox, oy, dw, dh, split_ratio)

        self.render_hud()
        if toast_message:
            self.render_toast(toast_message)

        self.canvas.tag_raise("hud")
        self.canvas.tag_raise("toast")

    def _render_split_decorations(
        self,
        ox: int,
        oy: int,
        dw: int,
        dh: int,
        split_ratio: float,
    ) -> None:
        """Render split comparison divider and badges."""
        sx = ox + int(dw * split_ratio)
        my = oy + dh // 2

        self.canvas.create_line(sx, oy, sx, oy + dh, fill=CLR_ACCENT, width=2, tags="split_hud")
        self.canvas.create_oval(
            sx - 12, my - 12, sx + 12, my + 12,
            fill=CLR_BG_TOOLBAR, outline=CLR_ACCENT, width=2, tags="split_hud"
        )
        self.canvas.create_text(
            sx, my, text="↔", fill=CLR_ACCENT,
            font=(FONT_FAMILY, 9, "bold"), tags="split_hud"
        )

        badges = [
            (ox + 10, "📷 מקור לפני", CLR_TEXT_MUTED, CLR_BORDER),
            (ox + dw - 120, "✨ לוח משופר", CLR_ACCENT, CLR_ACCENT),
        ]
        for bx, text, col, border in badges:
            self.canvas.create_rectangle(
                bx, oy + 10, bx + 110, oy + 36,
                fill=CLR_BG_TOOLBAR, outline=border, tags="split_hud"
            )
            self.canvas.create_text(
                bx + 55, oy + 23, text=text, fill=col,
                font=FONT_BODY_BOLD, tags="split_hud"
            )

    def render_loupe(self, processed_frame: Optional[Image.Image], cx: int, cy: int) -> None:
        """Render circular 2.5x magnifier glass centered at (cx, cy)."""
        if processed_frame is None:
            return

        ox, oy, dw, dh, scale = self.canvas_layout
        if not (ox <= cx <= ox + dw and oy <= cy <= oy + dh):
            self.canvas.delete("loupe")
            return

        fw, fh = processed_frame.size
        fx = max(0, min(fw - 1, int((cx - ox) / scale)))
        fy = max(0, min(fh - 1, int((cy - oy) / scale)))

        dst_rad = 110
        patch = processed_frame.crop(
            (max(0, fx - 44), max(0, fy - 44), min(fw, fx + 44), min(fh, fy + 44))
        ).resize((dst_rad * 2, dst_rad * 2), Image.Resampling.BILINEAR)

        mask = Image.new("L", (dst_rad * 2, dst_rad * 2), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, dst_rad * 2 - 1, dst_rad * 2 - 1), fill=255)

        circle_img = Image.new("RGBA", (dst_rad * 2, dst_rad * 2), (0, 0, 0, 0))
        circle_img.paste(patch.convert("RGBA"), (0, 0), mask=mask)

        self.loupe_tk_photo = ImageTk.PhotoImage(circle_img)
        self.canvas.delete("loupe")
        self.canvas.create_image(cx, cy, image=self.loupe_tk_photo, tags="loupe")

        for r, col, w in [(dst_rad, CLR_ACCENT, 3), (dst_rad + 2, CLR_BG_ROOT, 1)]:
            self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r, outline=col, width=w, tags="loupe"
            )

        self.canvas.create_line(cx - 16, cy, cx + 16, cy, fill=CLR_ACCENT, width=1, tags="loupe")
        self.canvas.create_line(cx, cy - 16, cx, cy + 16, fill=CLR_ACCENT, width=1, tags="loupe")

        by = cy + dst_rad - 18
        self.canvas.create_rectangle(
            cx - 24, by - 8, cx + 24, by + 8,
            fill=CLR_BG_TOOLBAR, outline=CLR_ACCENT, tags="loupe"
        )
        self.canvas.create_text(
            cx, by, text="2.5x", fill=CLR_ACCENT, font=FONT_BADGE, tags="loupe"
        )

    def render_hud(self) -> None:
        """Render top status badge and bottom-right resize grip indicator."""
        self.canvas.delete("hud")
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 320:
            return

        text = "Qboard | F9: כיבוי | F4: זיהוי לוח | F5: נקודות | F6: עכבר | F7: מסך | F10: הגדרות"
        bw = 600
        bh = 26
        x2 = cw - 10
        y1 = 8
        x1 = max(10, x2 - bw)
        y2 = y1 + bh

        self.canvas.create_rectangle(x1, y1, x2, y2, fill="#0B0F19", outline="#1E293B", width=1, tags="hud")
        self.canvas.create_oval(x1 + 8, y1 + 9, x1 + 16, y1 + 17, fill="#10B981", outline="#10B981", tags="hud")
        self.canvas.create_text(
            (x1 + x2) // 2 + 6,
            (y1 + y2) // 2,
            text=text,
            fill="#94A3B8",
            font=(FONT_FAMILY, 8, "bold"),
            tags="hud",
        )

        for off in (4, 8, 12):
            self.canvas.create_line(cw - off, ch - 2, cw - 2, ch - off, fill="#334155", width=1, tags="hud")

    def render_toast(self, message: str) -> None:
        """Render notification toast on the canvas."""
        self.canvas.delete("toast")
        if not message or not self.canvas.winfo_exists():
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 60 or ch < 60:
            return

        pw = max(260, min(cw - 40, len(message) * 10 + 44))
        ph = 36
        x1 = (cw - pw) // 2
        y1 = ch - 54

        self.canvas.create_rectangle(
            x1, y1, x1 + pw, y1 + ph,
            fill="#0F172A", outline=CLR_ACCENT, width=1, tags="toast"
        )
        self.canvas.create_text(
            x1 + pw // 2, y1 + ph // 2,
            text=message, fill="#F8FAFC", font=FONT_BODY_BOLD, tags="toast"
        )
        self.canvas.tag_raise("toast")
