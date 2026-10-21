"""
Zoom+ Studio UI Modals (ui/modals.py)
=====================================
Interactive modal dialogs for window capture, monitor switching, and ROI:
- ScreenRegionSelector: Fullscreen semi-transparent canvas overlay for click-drag ROI.
- BoardPointSelector: Interactive corner-point picker (2 or 4 points) for static whiteboard.
- WindowPickerModal: Searchable list of capturable desktop windows with auto-Zoom.
- ScreenPickerModal: Monitor and capture source selection dialog.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Tuple, List, Any

from capture import list_capturable_windows, WindowInfo, enum_display_monitors, MonitorInfo
from ui.theme import (
    CLR_BG_ROOT,
    CLR_BG_TOOLBAR,
    CLR_BG_PANEL,
    CLR_BG_CARD,
    CLR_BG_INPUT,
    CLR_BORDER,
    CLR_ACCENT,
    CLR_ACCENT_HOVER,
    CLR_ACCENT_BG,
    CLR_TEXT_PRIMARY,
    CLR_TEXT_SECONDARY,
    CLR_TEXT_MUTED,
    FONT_FAMILY,
    FONT_SUBTITLE,
    FONT_HEADING,
    FONT_BODY,
    FONT_BODY_BOLD,
    apply_dark_title_bar,
    set_window_capture_passthrough,
    make_flat_button,
    configure_studio_styles,
)


# ---------------------------------------------------------------------------
# Fullscreen Screen Region (ROI) Selector Overlay
# ---------------------------------------------------------------------------

class ScreenRegionSelector(tk.Toplevel):
    """Semi-transparent fullscreen overlay allowing click-and-drag ROI bounding box."""

    def __init__(self, parent: tk.Widget, callback: Any) -> None:
        super().__init__(parent)
        self.callback = callback
        self.start_x: Optional[int] = None
        self.start_y: Optional[int] = None
        self.current_rect_id: Optional[int] = None
        self.current_text_id: Optional[int] = None

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.overrideredirect(True)
        self.attributes("-alpha", 0.35)
        self.attributes("-topmost", True)
        self.configure(bg="#000000", cursor="cross")
        set_window_capture_passthrough(self, True)

        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        hud_text = "📐 לחץ וגרור עם העכבר לבחירת אזור לכידה במסך | לחץ ESC לביטול"
        self.canvas.create_rectangle(sw // 2 - 280, 20, sw // 2 + 280, 60, fill=CLR_BG_TOOLBAR, outline=CLR_ACCENT, width=2)
        self.canvas.create_text(sw // 2, 40, text=hud_text, fill=CLR_TEXT_PRIMARY, font=(FONT_FAMILY, 11, "bold"))

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_press(self, event: tk.Event) -> None:
        self.start_x, self.start_y = event.x_root, event.y_root
        if self.current_rect_id:
            self.canvas.delete(self.current_rect_id)
        if self.current_text_id:
            self.canvas.delete(self.current_text_id)

    def _on_motion(self, event: tk.Event) -> None:
        if self.start_x is None or self.start_y is None:
            return
        cur_x, cur_y = event.x_root, event.y_root
        if self.current_rect_id:
            self.canvas.delete(self.current_rect_id)
        if self.current_text_id:
            self.canvas.delete(self.current_text_id)
        self.current_rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, cur_x, cur_y, outline=CLR_ACCENT, width=2, dash=(6, 4)
        )
        w, h = abs(cur_x - self.start_x), abs(cur_y - self.start_y)
        self.current_text_id = self.canvas.create_text(
            (self.start_x + cur_x) // 2, (self.start_y + cur_y) // 2,
            text=f"{w} × {h}", fill=CLR_ACCENT, font=(FONT_FAMILY, 12, "bold")
        )

    def _on_release(self, event: tk.Event) -> None:
        if self.start_x is None or self.start_y is None:
            self.destroy()
            return
        left, right = min(self.start_x, event.x_root), max(self.start_x, event.x_root)
        top, bottom = min(self.start_y, event.y_root), max(self.start_y, event.y_root)
        self.destroy()
        if (right - left) > 30 and (bottom - top) > 30 and callable(self.callback):
            self.callback((left, top, right, bottom))


# ---------------------------------------------------------------------------
# Interactive Whiteboard Corner Point Selector (BoardPointSelector)
# ---------------------------------------------------------------------------

class BoardPointSelector(tk.Toplevel):
    """
    Interactive corner-point selector for static whiteboards.
    Allows students to click 2 or 4 corners (or drag a box) so enhancement filters
    target only the whiteboard region.
    """

    def __init__(self, parent: tk.Widget, callback: Any) -> None:
        super().__init__(parent)
        self.callback = callback
        self.points: List[Tuple[int, int]] = []
        self._press_pos: Optional[Tuple[int, int]] = None
        self._is_dragging: bool = False
        self._preview_ids: List[int] = []

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.overrideredirect(True)
        self.attributes("-alpha", 0.38)
        self.attributes("-topmost", True)
        self.configure(bg="#000000", cursor="cross")
        set_window_capture_passthrough(self, True)

        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        hud_text = "📍 סמן את פינות הלוח (2 או 4 נקודות) | Enter/קליק-ימני לאישור מ-2 נקודות | Esc לביטול"
        self.canvas.create_rectangle(sw // 2 - 340, 18, sw // 2 + 340, 58, fill=CLR_BG_TOOLBAR, outline=CLR_ACCENT, width=2)
        self.canvas.create_text(sw // 2, 38, text=hud_text, fill=CLR_TEXT_PRIMARY, font=(FONT_FAMILY, 11, "bold"))

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", lambda e: self._draw_feedback(live_mouse=(e.x_root, e.y_root)))
        self.canvas.bind("<Button-3>", lambda e: self._finish() if len(self.points) >= 2 else None)

        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda e: self._finish() if len(self.points) >= 2 else None)
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_press(self, event: tk.Event) -> None:
        self._press_pos = (event.x_root, event.y_root)
        self._is_dragging = False

    def _on_drag(self, event: tk.Event) -> None:
        if self._press_pos and not self.points:
            dx, dy = event.x_root - self._press_pos[0], event.y_root - self._press_pos[1]
            if (dx * dx + dy * dy) > 625:  # > 25px
                self._is_dragging = True
        self._draw_feedback(live_mouse=(event.x_root, event.y_root))

    def _on_release(self, event: tk.Event) -> None:
        cur = (event.x_root, event.y_root)
        if self._is_dragging and self._press_pos:
            self.points = [self._press_pos, cur]
            self._finish()
            return
        self._press_pos = None
        self.points.append(cur)
        self._draw_feedback()
        if len(self.points) >= 4:
            self._finish()

    def _draw_feedback(self, live_mouse: Optional[Tuple[int, int]] = None) -> None:
        for item in self._preview_ids:
            self.canvas.delete(item)
        self._preview_ids.clear()

        if self._is_dragging and self._press_pos and live_mouse:
            pts = [self._press_pos, live_mouse]
        elif len(self.points) >= 1 and live_mouse and len(self.points) < 4:
            pts = self.points + [live_mouse]
        else:
            pts = list(self.points)

        if len(pts) >= 2:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
            self._preview_ids.append(self.canvas.create_rectangle(
                left, top, right, bottom, outline=CLR_ACCENT, width=2, dash=(6, 4)
            ))
            for i in range(len(pts)):
                if i + 1 < len(pts):
                    p2 = pts[i + 1]
                elif len(pts) >= 3 and not live_mouse:
                    p2 = pts[0]
                else:
                    break
                self._preview_ids.append(self.canvas.create_line(
                    pts[i][0], pts[i][1], p2[0], p2[1], fill=CLR_ACCENT, width=2, dash=(3, 3)
                ))
            lbl = f"{right - left} × {bottom - top} px (לוח נעול)"
            self._preview_ids.append(self.canvas.create_text(
                (left + right) // 2, (top + bottom) // 2, text=lbl, fill=CLR_ACCENT, font=(FONT_FAMILY, 12, "bold")
            ))

        for idx, (px, py) in enumerate(self.points):
            r = 10
            self._preview_ids.append(self.canvas.create_oval(
                px - r, py - r, px + r, py + r, fill=CLR_ACCENT_BG, outline=CLR_ACCENT, width=2
            ))
            self._preview_ids.append(self.canvas.create_text(
                px, py, text=str(idx + 1), fill="#FFFFFF", font=(FONT_FAMILY, 9, "bold")
            ))

    def _finish(self) -> None:
        if not self.points:
            self.destroy()
            return
        xs, ys = [p[0] for p in self.points], [p[1] for p in self.points]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        self.destroy()
        if (right - left) > 40 and (bottom - top) > 40 and callable(self.callback):
            self.callback((left, top, right, bottom))


# ---------------------------------------------------------------------------
# Window Picker Modal Dialog
# ---------------------------------------------------------------------------

class WindowPickerModal(tk.Toplevel):
    """
    Modal window listing capturable desktop windows with auto-detection of Zoom.
    Allows searching and filtering by window title, shows resolution, and
    provides instant selection callback.
    """

    def __init__(self, parent: tk.Widget, callback: Any) -> None:
        super().__init__(parent)
        self.callback = callback
        self.title("בחירת חלון לכידה - Qboard")
        self.geometry("680x480")
        self.minsize(580, 400)
        self.configure(bg=CLR_BG_ROOT)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.grab_set()
        apply_dark_title_bar(self)
        set_window_capture_passthrough(self, True)

        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - 680) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - 480) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        self._windows_list: List[WindowInfo] = []
        self._build_ui()
        self._refresh_windows()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=CLR_BG_TOOLBAR, pady=12, padx=16)
        header.pack(fill=tk.X)
        tk.Label(header, text="🪟 בחירת חלון לכידה לשידור חי", font=FONT_HEADING, bg=CLR_BG_TOOLBAR, fg=CLR_TEXT_PRIMARY).pack(side=tk.RIGHT)
        tk.Label(header, text="בחר חלון של Zoom, דפדפן, מצגת או נגן וידאו לשיפור לוח חי", font=FONT_SUBTITLE, bg=CLR_BG_TOOLBAR, fg=CLR_TEXT_MUTED).pack(side=tk.LEFT)

        filter_bar = tk.Frame(self, bg=CLR_BG_PANEL, padx=14, pady=8)
        filter_bar.pack(fill=tk.X)
        make_flat_button(filter_bar, text="🔄 רענן רשימה", command=self._refresh_windows, bg=CLR_BORDER, fg=CLR_TEXT_PRIMARY, padx=10, pady=4).pack(side=tk.LEFT, padx=4)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._apply_filter())
        search_entry = tk.Entry(
            filter_bar, textvariable=self.search_var, bg=CLR_BG_INPUT, fg=CLR_TEXT_PRIMARY,
            insertbackground=CLR_ACCENT, font=FONT_BODY, bd=1, relief="solid", highlightthickness=0, width=32,
        )
        search_entry.pack(side=tk.RIGHT, padx=6)
        tk.Label(filter_bar, text="🔍 סינון לפי כותרת:", bg=CLR_BG_PANEL, fg=CLR_TEXT_SECONDARY, font=FONT_BODY).pack(side=tk.RIGHT)

        list_container = tk.Frame(self, bg=CLR_BG_ROOT, padx=14, pady=10)
        list_container.pack(fill=tk.BOTH, expand=True)

        configure_studio_styles(self)
        columns = ("type", "title", "size", "hwnd")
        self.tree = ttk.Treeview(list_container, columns=columns, show="headings", style="DarkPicker.Treeview", selectmode="browse")
        for c, h, w, a in (("type", "סוג", 80, tk.CENTER), ("title", "כותרת החלון", 360, tk.W), ("size", "רזולוציה", 110, tk.CENTER), ("hwnd", "HWND", 80, tk.CENTER)):
            self.tree.heading(c, text=h, anchor=a)
            self.tree.column(c, width=w, anchor=a)

        scroll_y = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda e: self._on_select())
        self.tree.bind("<Return>", lambda e: self._on_select())

        footer = tk.Frame(self, bg=CLR_BG_TOOLBAR, pady=10, padx=16)
        footer.pack(fill=tk.X)
        make_flat_button(footer, text="ביטול", command=self.destroy, bg=CLR_BORDER, fg=CLR_TEXT_MUTED, padx=14, pady=6).pack(side=tk.LEFT, padx=6)
        make_flat_button(footer, text="🎯 בחר חלון זה", command=self._on_select, bg=CLR_ACCENT_BG, fg="#FFFFFF", hover_bg=CLR_ACCENT_HOVER, font=FONT_HEADING, padx=18, pady=6).pack(side=tk.RIGHT, padx=6)

    def _refresh_windows(self) -> None:
        self._windows_list = list_capturable_windows()
        self._apply_filter()

    def _apply_filter(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        q = self.search_var.get().strip().lower()
        first_zoom = None
        for win in self._windows_list:
            if q and (q not in win.title.lower()):
                continue
            tag = "🎯 Zoom" if win.is_zoom else "🪟 חלון"
            item_id = self.tree.insert(
                "", tk.END, values=(tag, win.title, f"{win.width} × {win.height}", str(win.hwnd))
            )
            if win.is_zoom and first_zoom is None:
                first_zoom = item_id

        sel = first_zoom or (self.tree.get_children()[0] if self.tree.get_children() else None)
        if sel:
            self.tree.selection_set(sel)
            self.tree.focus(sel)

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("בחירת חלון", "אנא בחר חלון מהרשימה.")
            return

        vals = self.tree.item(sel[0], "values")
        if vals and len(vals) >= 4:
            try:
                hwnd, title = int(vals[3]), vals[1]
                self.destroy()
                if callable(self.callback):
                    self.callback(hwnd, title)
            except Exception as e:
                messagebox.showerror("שגיאה", f"לא ניתן לבחור חלון: {e}")


# ---------------------------------------------------------------------------
# Screen & Capture Source Picker Modal
# ---------------------------------------------------------------------------

class ScreenPickerModal(tk.Toplevel):
    """Floating dark-slate dialog for switching display monitors and capture sources."""

    def __init__(
        self, parent: tk.Widget, callback: Any, current_source: str = "screen", current_index: int = 0
    ) -> None:
        super().__init__(parent)
        self.callback = callback
        self.current_source = current_source
        self.current_index = current_index

        self.title("Qboard | בחירת מסך או מקור לכידה")
        self.geometry("520x440")
        self.minsize(460, 380)
        self.configure(bg=CLR_BG_ROOT)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.grab_set()
        apply_dark_title_bar(self)
        set_window_capture_passthrough(self, True)

        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - 520) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - 440) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        self.bind("<Escape>", lambda e: self.destroy())
        self._build_ui()

    def _select(self, source_type: str, arg: Any = None) -> None:
        self.destroy()
        if callable(self.callback):
            self.callback(source_type, arg)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=CLR_BG_TOOLBAR, pady=10, padx=16)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="🖥️ בחירת מסך או מקור לכידה", font=FONT_HEADING, bg=CLR_BG_TOOLBAR, fg=CLR_TEXT_PRIMARY
        ).pack(side=tk.RIGHT)
        tk.Label(
            header, text="בחר מסך לתצוגה חיה או עבור למקור אחר", font=FONT_SUBTITLE, bg=CLR_BG_TOOLBAR, fg=CLR_TEXT_MUTED
        ).pack(side=tk.LEFT)

        body = tk.Frame(self, bg=CLR_BG_ROOT, padx=16, pady=10)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body, text="מסכים מחוברים:", font=FONT_BODY_BOLD, bg=CLR_BG_ROOT, fg=CLR_TEXT_SECONDARY, anchor=tk.E
        ).pack(fill=tk.X, pady=(0, 4))

        screens_box = tk.Frame(body, bg=CLR_BG_ROOT)
        screens_box.pack(fill=tk.X, pady=(0, 8))

        for m in enum_display_monitors():
            is_active = (self.current_source == "screen" and self.current_index == m.index)
            btn_text = f"🖥️ מסך {m.index + 1}: {m.width}×{m.height}{' (ראשי)' if m.is_primary else ''}"
            make_flat_button(
                screens_box, text=btn_text,
                command=lambda idx=m.index: self._select("screen", idx),
                bg=CLR_ACCENT_BG if is_active else CLR_BG_CARD,
                fg="#FFFFFF" if is_active else CLR_TEXT_PRIMARY,
                hover_bg=CLR_ACCENT_HOVER if is_active else CLR_BORDER,
                font=FONT_BODY_BOLD if is_active else FONT_BODY,
                pady=6, padx=12,
            ).pack(fill=tk.X, pady=2)

        tk.Label(
            body, text="מקורות נוספים:", font=FONT_BODY_BOLD, bg=CLR_BG_ROOT, fg=CLR_TEXT_SECONDARY, anchor=tk.E
        ).pack(fill=tk.X, pady=(4, 4))

        grid = tk.Frame(body, bg=CLR_BG_ROOT)
        grid.pack(fill=tk.BOTH, expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        actions = [
            ("🎯 זיהוי חלון זום אוטומטי", "zoom", None),
            ("🪟 בחירת חלון מתוך רשימה...", "window_picker", None),
            ("📐 גרירת אזור במסך (ROI)", "roi", None),
            ("🖼️ מצב הדגמה (Sample Image)", "demo", None),
        ]
        for i, (label, src_type, arg) in enumerate(actions):
            make_flat_button(
                grid, text=label, command=lambda st=src_type, a=arg: self._select(st, a),
                bg=CLR_BG_CARD, fg=CLR_TEXT_PRIMARY, hover_bg=CLR_BORDER, pady=7, padx=8,
            ).grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky="nsew")

        footer = tk.Frame(self, bg=CLR_BG_TOOLBAR, pady=8, padx=16)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        make_flat_button(
            footer, text="סגור (Esc)", command=self.destroy,
            bg=CLR_BORDER, fg=CLR_TEXT_MUTED, padx=16, pady=4,
        ).pack(side=tk.LEFT)


__all__ = [
    "ScreenRegionSelector",
    "BoardPointSelector",
    "WindowPickerModal",
    "ScreenPickerModal",
]
