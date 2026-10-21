"""
Qboard Performance & Quality Benchmark (bench.py)
================================================
Comprehensive, realistic measurement tool for Qboard pipeline.
Tests real uncached processing, capture, latency, FPS, and quality metrics:
- Contrast improvement (in shadow and outside shadow)
- Background whiteness %
- Sharpness improvement
- Temporal stability (anti-flicker std dev across frames)
"""

from __future__ import annotations

import time
import os
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import numpy as np

from processor import WhiteboardEnhancer, PRESETS
from capture import LiveCaptureManager


def create_realistic_test_frame(w: int = 1920, h: int = 1080, seed: int = 42) -> Image.Image:
    """Creates a realistic 1080p classroom whiteboard frame with lighting gradient, projector shadow, and text."""
    base = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(base)

    # 1. Lighting gradient across classroom
    for x in range(w):
        d.line([(x, 0), (x, h)], fill=int(235 - (x / w) * 55))

    # 2. Large soft projector shadow of lecturer
    sh = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(sh)
    sd.ellipse([int(0.22 * w), int(0.15 * h), int(0.48 * w), int(0.85 * h)], fill=85)
    sd.polygon([(int(0.18 * w), int(0.40 * h)), (int(0.42 * w), int(0.55 * h)),
                (int(0.38 * w), int(0.62 * h)), (int(0.15 * w), int(0.48 * h))], fill=75)
    sh_b = sh.filter(ImageFilter.GaussianBlur(16))
    board = ImageChops.subtract(base, sh_b)

    # 3. Add classroom formulas (both outside shadow and inside shadow)
    rgb = Image.merge("RGB", (board, board, board))
    d2 = ImageDraw.Draw(rgb)
    d2.text((int(0.55 * w), int(0.20 * h)), "Algorithm Analysis: T(n) = 2T(n/2) + O(n)", fill=(60, 65, 75))
    d2.text((int(0.55 * w), int(0.28 * h)), "Master Theorem: T(n) = O(n log n)", fill=(60, 65, 75))
    d2.text((int(0.55 * w), int(0.36 * h)), "FindMax(A, n) loop invariant verified", fill=(60, 65, 75))

    # Inside the shadow:
    d2.text((int(0.26 * w), int(0.32 * h)), "Inside Shadow: x = y + 1", fill=(35, 40, 45))
    d2.text((int(0.26 * w), int(0.40 * h)), "Important Equation: E = mc^2", fill=(35, 40, 45))

    # 4. Add Zoom H.264 video compression noise
    np.random.seed(seed)
    noise = np.random.normal(0, 3.5, (h, w))
    arr = np.clip(np.asarray(rgb, dtype=np.float32) + noise[:, :, None], 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def run_benchmark(iterations: int = 10) -> dict:
    print("=" * 68)
    print("      Qboard Performance & Quality Diagnostic Benchmark")
    print("=" * 68)

    enhancer = WhiteboardEnhancer()
    print(f"Engine Backend: {getattr(enhancer, 'backend_name', 'Pillow C-SIMD')}")
    print(f"Workers Pool:   {enhancer.num_workers} threads\n")

    # A. Measure Real Uncached Processing Latency
    frame_1024 = create_realistic_test_frame(1024, 576)
    frame_1080p = create_realistic_test_frame(1920, 1080)

    results = {}

    for res_name, test_frame in [("1024x576", frame_1024), ("1080p (1920x1080)", frame_1080p)]:
        print(f"--- Benchmark Resolution: {res_name} ---")
        for preset_name in ["clean_board", "ultra_bold"]:
            p = PRESETS[preset_name]
            times = []
            metrics_list = []

            for i in range(iterations):
                # Turn off delta cache to measure TRUE per-frame throughput
                enhancer._last_thumb = None
                enhancer._cached_bg_env = None

                t0 = time.perf_counter()
                out = enhancer.enhance(test_frame, p)
                dt = (time.perf_counter() - t0) * 1000.0
                times.append(dt)

                if i == 0:
                    m = enhancer.compute_metrics(test_frame, out)
                    metrics_list.append(m)

            median_ms = sorted(times)[len(times) // 2]
            fps = 1000.0 / max(median_ms, 0.001)
            m0 = metrics_list[0]

            # Measure shadow retention: text inside shadow vs text outside shadow
            arr_out = np.asarray(out.convert("L"))
            w, h = test_frame.size
            # Inside shadow text box
            box_in = arr_out[int(0.30*h):int(0.44*h), int(0.25*w):int(0.45*w)]
            # Outside shadow text box
            box_out = arr_out[int(0.18*h):int(0.38*h), int(0.54*w):int(0.85*w)]

            ink_in = float(np.min(box_in))
            bg_in = float(np.percentile(box_in, 85))
            cr_in = bg_in / max(ink_in, 1.0)

            ink_out = float(np.min(box_out))
            bg_out = float(np.percentile(box_out, 85))
            cr_out = bg_out / max(ink_out, 1.0)

            shadow_cr_ratio = cr_in / max(cr_out, 0.001)

            results[f"{res_name}_{preset_name}"] = {
                "ms": round(median_ms, 1),
                "fps": round(fps, 1),
                "contrast": m0["contrast_improvement"],
                "whiteness": m0["background_whiteness_pct"],
                "sharpness": m0["sharpness_improvement"],
                "shadow_cr_ratio": round(shadow_cr_ratio, 2),
            }

            print(f"  [{preset_name:<12}] Latency: {median_ms:>5.1f} ms | FPS: {fps:>5.1f} | "
                  f"Contrast: x{m0['contrast_improvement']} | White: {m0['background_whiteness_pct']}% | "
                  f"Shadow/Light Contrast Ratio: {shadow_cr_ratio:.2f}")
        print()

    # B. Measure Real Capture Latency
    print("--- Live Capture Benchmarks ---")
    cap_demo = LiveCaptureManager(mode="demo")
    t0 = time.perf_counter()
    for _ in range(iterations):
        cap_demo.capture_frame()
    t_demo = (time.perf_counter() - t0) / iterations * 1000.0
    print(f"  Demo mode capture avg:       {t_demo:.2f} ms")

    cap_full = LiveCaptureManager(mode="fullscreen")
    t0 = time.perf_counter()
    for _ in range(min(5, iterations)):
        cap_full.capture_frame()
    t_full = (time.perf_counter() - t0) / min(5, iterations) * 1000.0
    print(f"  Fullscreen capture avg:     {t_full:.2f} ms")

    # C. Temporal Stability Benchmark (Anti-Flicker)
    print("\n--- Temporal Anti-Flicker Stability ---")
    noisy_frames = [create_realistic_test_frame(1024, 576, seed=s) for s in range(5)]
    p_stab = PRESETS["clean_board"].copy(temporal_stability=True)
    p_raw = PRESETS["clean_board"].copy(temporal_stability=False)

    e_stab = WhiteboardEnhancer()
    outs_stab = [np.asarray(e_stab.enhance(f, p_stab).convert("L"), dtype=np.float32) for f in noisy_frames]
    std_stab = float(np.mean(np.std(np.stack(outs_stab, axis=0), axis=0)))

    e_raw = WhiteboardEnhancer()
    outs_raw = [np.asarray(e_raw.enhance(f, p_raw).convert("L"), dtype=np.float32) for f in noisy_frames]
    std_raw = float(np.mean(np.std(np.stack(outs_raw, axis=0), axis=0)))

    stability_gain = (1.0 - std_stab / max(std_raw, 0.001)) * 100.0
    print(f"  Pixel Noise StdDev (Without Anti-Flicker): {std_raw:.2f}")
    print(f"  Pixel Noise StdDev (With Anti-Flicker)   : {std_stab:.2f} (Shimmer reduction: {stability_gain:.1f}%)")

    print("\n" + "=" * 68)
    return results


if __name__ == "__main__":
    run_benchmark(iterations=8)
