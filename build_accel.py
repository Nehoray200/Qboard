"""
Qboard C++ Accelerator Build Script (build_accel.py)
===================================================
Automates compilation of qboard_accel.cpp into a native Win64 DLL.
Detects MSVC (cl.exe), GCC/G++ (MinGW), or Clang.
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_FILE = os.path.join(BASE_DIR, "src", "qboard_accel.cpp")
OUT_DLL = os.path.join(BASE_DIR, "qboard_accel.dll")


def try_compile_gcc() -> bool:
    gcc = shutil.which("g++") or shutil.which("gcc")
    if not gcc:
        return False
    cmd = [
        gcc, "-O3", "-mavx2", "-shared", "-std=c++17",
        "-fPIC", "-Wall", "-s",
        SRC_FILE, "-o", OUT_DLL
    ]
    print(f"Compiling with GCC/G++: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        return os.path.isfile(OUT_DLL)
    except Exception as e:
        print(f"GCC compilation failed: {e}")
        return False


def try_compile_clang() -> bool:
    clang = shutil.which("clang++") or shutil.which("clang")
    if not clang:
        return False
    cmd = [
        clang, "-O3", "-mavx2", "-shared", "-std=c++17",
        SRC_FILE, "-o", OUT_DLL
    ]
    print(f"Compiling with Clang: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        return os.path.isfile(OUT_DLL)
    except Exception as e:
        print(f"Clang compilation failed: {e}")
        return False


def try_compile_msvc() -> bool:
    cl = shutil.which("cl")
    if not cl:
        return False
    cmd = [
        cl, "/O2", "/arch:AVX2", "/LD", "/EHsc",
        SRC_FILE, f"/Fe:{OUT_DLL}"
    ]
    print(f"Compiling with MSVC cl.exe: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        return os.path.isfile(OUT_DLL)
    except Exception as e:
        print(f"MSVC compilation failed: {e}")
        return False


def main() -> int:
    print("=" * 60)
    print(" Qboard Native C++ AVX2 Accelerator Builder")
    print("=" * 60)

    if not os.path.isfile(SRC_FILE):
        print(f"[ERROR] Source file not found: {SRC_FILE}")
        return 1

    success = try_compile_gcc() or try_compile_clang() or try_compile_msvc()
    if success:
        sz = os.path.getsize(OUT_DLL)
        print(f"\n[SUCCESS] Native accelerator DLL built successfully!")
        print(f"Output: {OUT_DLL} ({sz} bytes)")
        return 0

    print("\n[INFO] No supported C++ compiler (G++, Clang, or MSVC) was found in PATH.")
    print("Qboard will continue running using its highly optimized Pillow C-SIMD engine.")
    print("To enable native hardware acceleration, install MinGW-w64 or Visual Studio C++ Build Tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
