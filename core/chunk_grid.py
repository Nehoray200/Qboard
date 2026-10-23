"""
Tile-Based Chunk Grid Manager (core/chunk_grid.py)
==================================================
Partitions the whiteboard into discrete macroblock chunks (e.g. 128x128),
detects dirty regions outside the instructor's silhouette, tracks uncovering
events when the instructor moves, and provides seamless padded ROIs for
high-precision localized enhancement.
"""

from __future__ import annotations

from typing import Optional, Tuple, List
import numpy as np

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False


class ChunkGridManager:
    """
    Tracks whiteboard tiles across video frames to enable localized dirty-chunk updates.
    Ensures that static whiteboard text is reused from the persistent canvas while
    active writing/erasing is re-enhanced in real-time.
    """

    def __init__(self, chunk_size: int = 128, diff_threshold: float = 2.2) -> None:
        self.chunk_size: int = max(32, chunk_size)
        self.diff_threshold: float = diff_threshold

        self.grid_w: int = 0
        self.grid_h: int = 0
        self.total_chunks: int = 0

        self.prev_board_gray: Optional[np.ndarray] = None
        self.prev_inst_mask: Optional[np.ndarray] = None
        self.uncovered_ticks: Optional[np.ndarray] = None

    def reset(self) -> None:
        """Clear all historical state to force a clean full-board refresh."""
        self.prev_board_gray = None
        self.prev_inst_mask = None
        self.uncovered_ticks = None

    def _init_grid(self, width: int, height: int) -> None:
        gw = (width + self.chunk_size - 1) // self.chunk_size
        gh = (height + self.chunk_size - 1) // self.chunk_size
        if gw != self.grid_w or gh != self.grid_h or self.uncovered_ticks is None:
            self.grid_w = gw
            self.grid_h = gh
            self.total_chunks = gw * gh
            self.uncovered_ticks = np.zeros((gh, gw), dtype=np.uint8)
            self.prev_board_gray = None
            self.prev_inst_mask = None

    def find_dirty_roi(
        self,
        gray: np.ndarray,
        inst_mask: np.ndarray,
        force_full: bool = False,
        padding: int = 16,
    ) -> Tuple[Optional[Tuple[int, int, int, int]], int, int]:
        """
        Determines the dirty bounding box ROI (x1, y1, x2, y2) that needs re-enhancement.
        Returns:
            ((x1, y1, x2, y2), dirty_count, total_chunks)
            or (None, 0, total_chunks) if the whiteboard is completely static.
        """
        h, w = gray.shape[:2]
        self._init_grid(w, h)

        if force_full or self.prev_board_gray is None:
            self.prev_board_gray = gray.copy()
            self.prev_inst_mask = inst_mask.copy()
            if self.uncovered_ticks is not None:
                self.uncovered_ticks.fill(0)
            return ((0, 0, w, h), self.total_chunks, self.total_chunks)

        # 1. Mask out instructor from change detection
        # Neutral gray where lecturer is occluding so body motion does not trigger whiteboard dirtiness
        board_gray = gray.copy()
        if _CV2_AVAILABLE:
            board_gray[inst_mask > 0] = 180
            diff = cv2.absdiff(board_gray, self.prev_board_gray)
            # Area-downsample difference directly to the chunk grid
            grid_diff = cv2.resize(diff, (self.grid_w, self.grid_h), interpolation=cv2.INTER_AREA)
        else:
            board_gray[inst_mask > 0] = 180
            diff = np.abs(board_gray.astype(np.int16) - self.prev_board_gray.astype(np.int16)).astype(np.uint8)
            # Simple grid pooling
            grid_diff = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
            for gy in range(self.grid_h):
                for gx in range(self.grid_w):
                    y_start = gy * self.chunk_size
                    y_end = min(h, y_start + self.chunk_size)
                    x_start = gx * self.chunk_size
                    x_end = min(w, x_start + self.chunk_size)
                    grid_diff[gy, gx] = float(np.mean(diff[y_start:y_end, x_start:x_end]))

        # 2. Track newly uncovered chunks (instructor vacated a previously occluded tile)
        if _CV2_AVAILABLE and self.prev_inst_mask is not None:
            # Mask diff: was instructor before (prev=255) and is now whiteboard (curr=0)
            uncovered_mask = cv2.subtract(self.prev_inst_mask, inst_mask)
            grid_uncovered = cv2.resize(uncovered_mask, (self.grid_w, self.grid_h), interpolation=cv2.INTER_AREA)
            # Newly uncovered chunks get 2 refresh ticks to ensure fresh writing is fully captured
            new_uncovered = grid_uncovered > 25
            if self.uncovered_ticks is not None:
                self.uncovered_ticks[new_uncovered] = 2

        # 3. Detect dirty chunks (pixel diff > threshold OR uncovered tick active)
        dirty_mask = grid_diff > self.diff_threshold
        if self.uncovered_ticks is not None:
            dirty_mask = dirty_mask | (self.uncovered_ticks > 0)
            # Decrement active ticks
            self.uncovered_ticks[self.uncovered_ticks > 0] -= 1

        dirty_coords = np.argwhere(dirty_mask)
        dirty_count = len(dirty_coords)

        # Update historical references
        self.prev_board_gray = board_gray
        self.prev_inst_mask = inst_mask.copy()

        if dirty_count == 0:
            return (None, 0, self.total_chunks)

        # If more than 40% of the board changed, perform a full refresh
        if dirty_count >= int(self.total_chunks * 0.40):
            return ((0, 0, w, h), dirty_count, self.total_chunks)

        # Compute bounding rectangle around all dirty chunks
        gy_min = int(np.min(dirty_coords[:, 0]))
        gy_max = int(np.max(dirty_coords[:, 0]))
        gx_min = int(np.min(dirty_coords[:, 1]))
        gx_max = int(np.max(dirty_coords[:, 1]))

        x1 = max(0, gx_min * self.chunk_size - padding)
        y1 = max(0, gy_min * self.chunk_size - padding)
        x2 = min(w, (gx_max + 1) * self.chunk_size + padding)
        y2 = min(h, (gy_max + 1) * self.chunk_size + padding)

        return ((x1, y1, x2, y2), dirty_count, self.total_chunks)
