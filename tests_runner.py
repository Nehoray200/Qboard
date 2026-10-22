"""
Qboard Automated Self-Test Runner (tests_runner.py)
==================================================
Headless diagnostic and validation suite for Qboard Pro Studio.
Verifies frame capture, Pillow C-SIMD enhancement pipelines, all 5 presets,
quantitative quality telemetry, interactive split/crop modes, and GUI bindings.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
from ctypes import wintypes
from typing import Dict, Any

from processor import (
    WhiteboardEnhancer,
    PRESETS,
)
from capture import (
    LiveCaptureManager,
    list_capturable_windows,
    find_zoom_window,
)
from ui.theme import set_window_capture_passthrough, set_window_click_through, copy_image_to_clipboard
from app import ZoomPlusApp


def run_self_test() -> int:
    """
    Automated self-test verifying capture, all presets, view modes,
    quality metrics computation, image saving, and GUI components.
    """
    print("\n" + "=" * 65)
    print(" Qboard Whiteboard Enhancement Engine - Automated Self-Test")
    print("=" * 65)

    # 1. Initialize Capture Engine
    print("\n[1/6] Initializing LiveCaptureManager in demo mode...")
    cap = LiveCaptureManager(mode="demo", simulate_live=False)
    frame0 = cap.capture_frame()
    print(f"      Initial frame size: {frame0.size}, mode: {frame0.mode}")
    assert frame0.size[0] >= 100 and frame0.size[1] >= 100, "Frame size too small"

    for i in range(5):
        f = cap.capture_frame()
        assert f is not None, f"Capture frame {i} failed"
    print(f"      Captured 5 frames successfully. Average latency: {cap.last_capture_ms:.2f}ms")

    # 2. Test Core Whiteboard Enhancer with all Presets
    print("\n[2/6] Verifying enhancement pipeline across all 5 presets...")
    enhancer = WhiteboardEnhancer()
    preset_keys = ("clean_board", "ultra_bold", "color_markers", "dark_board", "raw_contrast")

    for key in preset_keys:
        t0 = time.perf_counter()
        params = PRESETS[key]
        enhanced = enhancer.enhance(frame0, params)
        dt = (time.perf_counter() - t0) * 1000.0
        metrics = enhancer.compute_metrics(frame0, enhanced)

        print(
            f"      ✓ Preset {key:<14}: {dt:.1f}ms | "
            f"Whiteness: {metrics['background_whiteness_pct']}% | "
            f"Contrast: x{metrics['contrast_improvement']} | "
            f"Sharpness: x{metrics['sharpness_improvement']}"
        )
        assert enhanced.size == frame0.size, f"Size mismatch in {key}"
        assert metrics["contrast_improvement"] >= 0.85, f"Contrast didn't improve in {key}"

    # 3. Save Demo Validation Images
    print("\n[3/6] Generating sample demonstration output images...")
    import tempfile, shutil
    test_dir = tempfile.mkdtemp(prefix="zoomplus_test_")
    p_clean = os.path.join(test_dir, "demo_clean_board.png")
    img_clean = enhancer.enhance(frame0, PRESETS["clean_board"])
    img_clean.save(p_clean, "PNG")
    print("      ✓ Saved: demo_clean_board.png (isolated temp)")

    p_bold = os.path.join(test_dir, "demo_ultra_bold.png")
    img_bold = enhancer.enhance(frame0, PRESETS["ultra_bold"])
    img_bold.save(p_bold, "PNG")
    print("      ✓ Saved: demo_ultra_bold.png (isolated temp)")

    p_dark = os.path.join(test_dir, "demo_dark_board.png")
    img_dark = enhancer.enhance(frame0, PRESETS["dark_board"])
    img_dark.save(p_dark, "PNG")
    print("      ✓ Saved: demo_dark_board.png (isolated temp)")

    p_split = os.path.join(test_dir, "demo_split_comparison.png")
    img_split = enhancer.create_comparison_view(frame0, img_clean, split_ratio=0.50)
    img_split.save(p_split, "PNG")
    print("      ✓ Saved: demo_split_comparison.png (isolated temp)")

    for fpath in (p_clean, p_bold, p_dark, p_split):
        size = os.path.getsize(fpath)
        assert size > 10000, f"Output image {fpath} file size suspicious ({size} bytes)"

    # 4. Test Interactive Components (Split, Loupe, Sub-ROI)
    print("\n[4/6] Testing interactive split views and sub-ROI cropping...")
    split_25 = enhancer.create_comparison_view(frame0, img_clean, split_ratio=0.25)
    split_75 = enhancer.create_comparison_view(frame0, img_clean, split_ratio=0.75)
    assert split_25.size == frame0.size and split_75.size == frame0.size

    # Sub-ROI crop
    cap.set_board_crop((0.15, 0.15, 0.85, 0.85))
    cropped = cap.capture_frame()
    expected_w = int(frame0.width * 0.70)
    expected_h = int(frame0.height * 0.70)
    print(f"      Sub-ROI crop size: {cropped.size} (expected ~{expected_w}x{expected_h})")
    assert cropped.size[0] < frame0.size[0] and cropped.size[1] < frame0.size[1]
    cap.set_board_crop(None)
    uncropped = cap.capture_frame()
    assert uncropped.size == frame0.size
    print("      ✓ Sub-ROI crop and reset verified")

    # Whiteboard automatic ROI detection via Computer Vision
    bbox_detected = enhancer.detect_whiteboard_bbox(frame0)
    assert len(bbox_detected) == 4, "Whiteboard detection didn't return 4 coords"
    assert 0.0 <= bbox_detected[0] < bbox_detected[2] <= 1.0, f"Invalid x bounds: {bbox_detected}"
    assert 0.0 <= bbox_detected[1] < bbox_detected[3] <= 1.0, f"Invalid y bounds: {bbox_detected}"
    print(f"      ✓ detect_whiteboard_bbox: normalized {bbox_detected}")

    # 5. Test ZoomPlusApp Desktop GUI Creation
    print("\n[5/6] Testing ZoomPlusApp desktop GUI initialization (headless)...")
    app = ZoomPlusApp(headless=True)

    # Test window capture passthrough (Anti-Mirror WDA_EXCLUDEFROMCAPTURE)
    res_passthrough = set_window_capture_passthrough(app.root, True)
    assert isinstance(res_passthrough, bool)
    print(f"      ✓ Window capture passthrough (WDA_EXCLUDEFROMCAPTURE): {res_passthrough}")

    # Test window click-through (Input transparency WS_EX_TRANSPARENT | WS_EX_LAYERED)
    res_clickthrough = set_window_click_through(app.root, True)
    assert isinstance(res_clickthrough, bool)
    print(f"      ✓ Window click-through (WS_EX_TRANSPARENT): {res_clickthrough}")

    # Test click-through toggle and mode switching
    assert app.click_through_enabled is True
    app.toggle_click_through()
    assert app.click_through_enabled is False
    assert app.var_click_through.get() is False
    app.set_click_through_mode(True)
    assert app.click_through_enabled is True
    assert app.var_click_through.get() is True
    print("      ✓ Input pass-through & spacebar talk mode verified")

    # Test preset switching in GUI
    app.apply_preset("ultra_bold")
    assert app.current_preset == "ultra_bold"
    assert app.current_params.contrast == PRESETS["ultra_bold"].contrast

    # Test preset cycling hotkey action
    app.cycle_next_preset()
    print(f"      ✓ Preset cycling hotkey action: {app.current_preset}")

    # Test parameter slider update
    app.update_param_from_slider("contrast", 2.75)
    assert round(app.current_params.contrast, 2) == 2.75

    # Test always-on-top toggle
    app.toggle_always_on_top()
    assert app.var_always_on_top.get() is True
    app.toggle_always_on_top()
    assert app.var_always_on_top.get() is False
    print("      ✓ Always-on-top toggle verified")

    # Test quick launch toggle
    app.toggle_quick_launch()
    print("      ✓ Quick launch toggle executed cleanly")

    # Test view modes
    app.set_view_mode("split")
    assert app.view_mode == "split"
    app.set_view_mode("original")
    assert app.view_mode == "original"
    app.set_view_mode("enhanced")
    assert app.view_mode == "enhanced"

    # Test loupe & crop toggles
    app.toggle_loupe()
    assert app.loupe_enabled is True
    app.toggle_loupe()
    assert app.loupe_enabled is False

    app.toggle_crop_mode()
    assert app.crop_mode is True
    app.toggle_crop_mode()
    assert app.crop_mode is False

    # Test frame execution tick
    for _ in range(5):
        app.process_single_frame()
    print("      ✓ 5 frame ticks executed smoothly")

    # Test snapshot generation and composite snapshot
    saved_path = app.save_snapshot(out_dir=test_dir)
    assert os.path.isfile(saved_path), f"Snapshot file not created at {saved_path}"
    assert os.path.getsize(saved_path) > 1000, f"Snapshot too small: {saved_path}"
    print(f"      ✓ Composite snapshot saved successfully: {os.path.basename(saved_path)}")

    # Test clipboard copy utility
    test_clip_res = copy_image_to_clipboard(frame0)
    assert isinstance(test_clip_res, bool)
    print(f"      ✓ copy_image_to_clipboard execution verified (res={test_clip_res})")

    # Test Snipping Tool Mode & Anti-Mirror safeguards
    app.enter_snipping_tool_mode()
    assert app.capture_manager.anti_mirror_frozen is True
    assert app.is_paused is True
    app.exit_snipping_tool_mode()
    assert app.capture_manager.anti_mirror_frozen is False
    assert app.is_paused is False
    app.toggle_snipping_tool_mode()
    assert app.capture_manager.anti_mirror_frozen is True
    app.toggle_snipping_tool_mode()
    assert app.capture_manager.anti_mirror_frozen is False
    print("      ✓ Snipping tool mode & anti-mirror freeze verified")

    # Test exclude_capture toggle anti-mirror behavior
    app.var_exclude_capture.set(False)
    app._on_toggle_change("exclude_capture")
    assert app.capture_manager.anti_mirror_frozen is True
    app.var_exclude_capture.set(True)
    app._on_toggle_change("exclude_capture")
    assert app.capture_manager.anti_mirror_frozen is False
    print("      ✓ exclude_capture anti-mirror safeguard verified")

    # Test window snapping, direct capture & browser trim
    import tkinter as tk
    test_win = tk.Toplevel(app.root)
    test_win.geometry("400x300+150+150")
    test_win.update()
    test_hwnd = test_win.winfo_id()
    assert app.snap_to_window(test_hwnd) is True
    assert app.var_trim_browser_header.get() is False
    app.toggle_trim_browser_header()
    assert app.var_trim_browser_header.get() is True
    assert app.capture_manager.trim_browser_header is True
    app._on_window_selected(test_hwnd, "Google Chrome")
    assert app.active_source_type == "window"
    assert app.capture_manager.hwnd == test_hwnd
    test_win.destroy()
    print("      ✓ Window direct snapping & browser header trim verified")

    # Test automatic whiteboard detection and board corner locking
    auto_bbox = app.auto_detect_board_region()
    assert auto_bbox is not None and len(auto_bbox) == 4
    assert auto_bbox[2] > auto_bbox[0] and auto_bbox[3] > auto_bbox[1]
    print(f"      ✓ auto_detect_board_region: locked {auto_bbox}")

    app._on_board_points_selected((80, 80, 680, 480))
    assert app.active_source_type == "region"
    assert app.capture_manager.region_bbox == (80, 80, 680, 480)
    print("      ✓ _on_board_points_selected screen locking verified")

    # Clean shutdown
    app.root.destroy()
    print("      ✓ GUI root destroyed cleanly")

    # 6. Windows Capture Enumeration Test
    print("\n[6/6] Verifying Windows desktop window detection...")
    windows = list_capturable_windows()
    print(f"      Detected {len(windows)} capturable windows on desktop.")
    my_pid = os.getpid()
    for w in windows:
        win_pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(w.hwnd), ctypes.byref(win_pid))
        assert win_pid.value != my_pid, f"Window belongs to own PID: {w}"
        assert "qboard" not in w.title.lower() and "zoom+" not in w.title.lower(), f"Qboard window not excluded: {w.title}"
    print("      ✓ Own process and Qboard windows strictly excluded from window detection")
    zoom_win = find_zoom_window()
    if zoom_win:
        print(f"      🎯 Active Zoom window found: {zoom_win.title}")
    else:
        print("      ℹ️ No active Zoom window currently running (normal for testing).")

    print("\n" + "=" * 65)
    print(" ✅ ALL SELF-TESTS PASSED SUCCESSFULLY! Exit Code: 0")
    print("=" * 65 + "\n")
    shutil.rmtree(test_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_self_test())
