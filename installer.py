"""
Qboard - Automated Installation and Setup Script (installer.py)
==============================================================
Sets up dependencies, verifies system compatibility, runs self-tests,
and creates desktop shortcuts for one-click launching on Windows.
"""

from __future__ import annotations

import os
import sys
import subprocess
import shutil
import tempfile


def print_banner() -> None:
    print("=" * 68)
    print("      Qboard Whiteboard Enhancement Studio - Installation Setup")
    print("      משפר לוח חכם בזמן אמת לשידורי זום ולמידה מרחוק")
    print("=" * 68)
    print()


def check_python_version() -> bool:
    print(f"[1/4] Checking Python environment...")
    v = sys.version_info
    print(f"      Python version: {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    if v.major < 3 or (v.major == 3 and v.minor < 9):
        print(f"\n[ERROR] Qboard requires Python 3.9 or higher. Found: {v.major}.{v.minor}")
        return False
    print("      ✓ Python version meets requirements (>= 3.9).")
    return True


def install_dependencies() -> bool:
    print("\n[2/4] Installing / updating required dependencies (requirements.txt)...")
    req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if not os.path.isfile(req_path):
        print(f"[ERROR] Could not find requirements.txt at {req_path}")
        return False

    cmd = [sys.executable, "-m", "pip", "install", "-r", req_path]
    try:
        res = subprocess.run(cmd, check=True)
        print("      ✓ Packages installed successfully (numpy, Pillow).")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] pip installation failed with exit code {e.returncode}.")
        return False


def run_system_verification() -> bool:
    print("\n[3/4] Running automated system self-test verification...")
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    cmd = [sys.executable, main_py, "--self-test"]
    try:
        res = subprocess.run(cmd, check=True)
        print("\n      ✓ All core engine and GUI self-tests passed (Exit Code 0).")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[WARNING] Self-test returned exit code {e.returncode}.")
        return False


def resolve_desktop_path() -> str:
    """Accurately resolve the Windows Desktop directory across languages and OneDrive redirection."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        raw_val = winreg.QueryValueEx(k, "Desktop")[0]
        expanded = os.path.expandvars(raw_val)
        if os.path.isdir(expanded):
            return expanded
    except Exception:
        pass

    for cand in [
        os.path.join(os.path.expanduser("~"), "OneDrive - ac.sce.ac.il", "שולחן העבודה"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "שולחן העבודה"),
        os.path.join(os.path.expanduser("~"), "שולחן העבודה"),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
    ]:
        if os.path.isdir(cand):
            return cand

    return os.path.join(os.path.expanduser("~"), "Desktop")


def create_desktop_shortcut() -> bool:
    print("\n[4/4] Creating Windows shortcuts...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bat_target = os.path.join(base_dir, "run_qboard.bat")
    desktop_dir = resolve_desktop_path()
    lnk_desktop = os.path.join(desktop_dir, "Qboard.lnk")
    lnk_local = os.path.join(base_dir, "Qboard.lnk")

    ps1_content = (
        '$ws = New-Object -ComObject WScript.Shell\r\n'
        f'$s1 = $ws.CreateShortcut("{lnk_local}")\r\n'
        f'$s1.TargetPath = "{bat_target}"\r\n'
        f'$s1.WorkingDirectory = "{base_dir}"\r\n'
        '$s1.Description = "Qboard - Real-Time Whiteboard Enhancement Studio"\r\n'
        '$s1.Save()\r\n'
        f'try {{ $s2 = $ws.CreateShortcut("{lnk_desktop}"); $s2.TargetPath = "{bat_target}"; $s2.WorkingDirectory = "{base_dir}"; $s2.Save() }} catch {{ }}\r\n'
    )
    tmp_ps1 = os.path.join(tempfile.gettempdir(), "_mk_qboard_lnk.ps1")
    created_any = False
    try:
        with open(tmp_ps1, "w", encoding="utf-8-sig") as f:
            f.write(ps1_content)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_ps1],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if os.path.isfile(tmp_ps1):
            os.remove(tmp_ps1)
        if os.path.isfile(lnk_desktop):
            print(f"      ✓ קיצור דרך נוצר בשולחן העבודה: {lnk_desktop}")
            created_any = True
        if os.path.isfile(lnk_local):
            print(f"      ✓ קיצור דרך נוצר בתיקיית הפרויקט: Qboard.lnk")
            created_any = True
        return created_any
    except Exception:
        if os.path.isfile(tmp_ps1):
            try:
                os.remove(tmp_ps1)
            except Exception:
                pass

    print(f"      ℹ️ ניתן להפעיל את התוכנה ישירות דרך: run_qboard.bat")
    return False


def print_completion_guide() -> None:
    print("\n" + "=" * 68)
    print("      🎉 Qboard הותקנה בהצלחה ומוכנה לשימוש מיידי!")
    print("=" * 68)
    print("\nכיצד מפעילים את Qboard:")
    print("  1. לחיצה כפולה על קיצור הדרך 'Qboard' שנוצר בשולחן העבודה.")
    print("  2. או הפעלת הקובץ 'run_qboard.bat' בתיקיית הפרויקט.")
    print()
    print("קיצורי מקלדת שימושיים בזמן שיעור בזום:")
    print("  • F9  (או Alt+Z) : הפעלה / כיבוי של שכבת שיפור הלוח מעל הזום")
    print("  • F10 (או Alt+O) : פתיחת חלון הגדרות ומחווני כוונון עדינים")
    print("  • F8  (או Alt+S) : צילום ושמירת הלוח לקובץ נקי בתיקיית captures/")
    print("  • F6  (או Alt+T) : שקיפות עכבר מלאה (מאפשר לדבר במקש רווח בזום)")
    print("  • F7  (או Alt+M) : החלפת מסכים במערך מרובה-צגים")
    print("  • F5             : נעילת הפילטר על 2 או 4 פינות של הלוח בלבד")
    print("  • Shift+F5       : זיהוי לוח אוטומטי בראייה ממוחשבת")
    print("=" * 68)


def main() -> int:
    print_banner()
    if not check_python_version():
        return 1
    if not install_dependencies():
        return 1
    run_system_verification()
    create_desktop_shortcut()
    print_completion_guide()

    # Optional interactive launch prompt
    if sys.stdin and sys.stdin.isatty():
        try:
            choice = input("\nהאם להפעיל את Qboard כעת? (Enter להפעלה / N ליציאה): ").strip().lower()
            if choice != "n":
                base_dir = os.path.dirname(os.path.abspath(__file__))
                bat_target = os.path.join(base_dir, "run_qboard.bat")
                os.startfile(bat_target)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
