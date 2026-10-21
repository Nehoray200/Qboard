"""
Qboard Async Multi-Thread Frame Pipeline (pipeline.py)
======================================================
Decouples Screen Capture, SIMD Image Processing, and GUI Rendering
into independent concurrent worker threads with non-blocking,
zero-latency latest-frame queues.
"""

from __future__ import annotations

import time
import threading
import queue
from typing import Optional, Callable, Any, Tuple
from PIL import Image


class FramePipeline:
    """
    3-Stage concurrent pipeline:
    Stage 1: Capture Thread -> _raw_queue (maxsize=1)
    Stage 2: Processing Thread -> _processed_queue (maxsize=1)
    Stage 3: GUI Main Thread (Tkinter after loop) -> render to Canvas
    """

    def __init__(
        self,
        capture_fn: Callable[[], Optional[Image.Image]],
        process_fn: Callable[[Image.Image], Optional[Image.Image]],
    ) -> None:
        self.capture_fn = capture_fn
        self.process_fn = process_fn
        self.running: bool = False
        self.paused: bool = False

        self._raw_queue: queue.Queue[Image.Image] = queue.Queue(maxsize=1)
        self._processed_queue: queue.Queue[Tuple[Image.Image, Image.Image]] = queue.Queue(maxsize=1)

        self._cap_thread: Optional[threading.Thread] = None
        self._proc_thread: Optional[threading.Thread] = None

        self.last_capture_ms: float = 0.0
        self.last_process_ms: float = 0.0
        self.capture_fps: float = 0.0
        self.process_fps: float = 0.0

        self._cap_count: int = 0
        self._proc_count: int = 0
        self._last_fps_calc: float = time.perf_counter()

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.paused = False

        self._cap_thread = threading.Thread(target=self._capture_worker, name="Qboard-CaptureThread", daemon=True)
        self._proc_thread = threading.Thread(target=self._process_worker, name="Qboard-ProcessThread", daemon=True)

        self._cap_thread.start()
        self._proc_thread.start()

    def stop(self) -> None:
        self.running = False
        self.paused = False
        # Empty queues to unblock workers if waiting
        try:
            self._raw_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._processed_queue.get_nowait()
        except queue.Empty:
            pass

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def _capture_worker(self) -> None:
        while self.running:
            if self.paused:
                time.sleep(0.04)
                continue

            t0 = time.perf_counter()
            try:
                frame = self.capture_fn()
            except Exception:
                frame = None

            dt = (time.perf_counter() - t0) * 1000.0
            self.last_capture_ms = dt
            self._cap_count += 1

            if frame is not None:
                # Latest-frame wins: if queue full, replace item
                try:
                    self._raw_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self._raw_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._raw_queue.put_nowait(frame)
                    except queue.Full:
                        pass

            # Yield to prevent 100% spin if capture is extremely fast (<2ms)
            if dt < 4.0:
                time.sleep(0.003)

    def _process_worker(self) -> None:
        while self.running:
            if self.paused:
                time.sleep(0.04)
                continue

            try:
                raw_frame = self._raw_queue.get(timeout=0.08)
            except queue.Empty:
                continue

            t0 = time.perf_counter()
            try:
                processed_frame = self.process_fn(raw_frame)
            except Exception:
                processed_frame = raw_frame

            dt = (time.perf_counter() - t0) * 1000.0
            self.last_process_ms = dt
            self._proc_count += 1

            if processed_frame is not None:
                item = (raw_frame, processed_frame)
                try:
                    self._processed_queue.put_nowait(item)
                except queue.Full:
                    try:
                        self._processed_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._processed_queue.put_nowait(item)
                    except queue.Full:
                        pass

            # Update FPS telemetry every 0.8s
            now = time.perf_counter()
            elapsed = now - self._last_fps_calc
            if elapsed >= 0.8:
                self.capture_fps = self._cap_count / elapsed
                self.process_fps = self._proc_count / elapsed
                self._cap_count = 0
                self._proc_count = 0
                self._last_fps_calc = now

    def get_latest_frame(self) -> Optional[Tuple[Image.Image, Image.Image]]:
        """Non-blocking fetch for the GUI thread. Returns (raw_frame, processed_frame) or None."""
        try:
            return self._processed_queue.get_nowait()
        except queue.Empty:
            return None
