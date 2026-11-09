"""NetPulse Windows Installer.

Installs NetPulse into C:\\Users\\<User>\\AppData\\Local\\Programs\\NetPulse,
creates Start Menu and Desktop shortcuts, configures automatic launch on Windows boot,
and migrates existing CSV monitoring data safely.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import winreg
from typing import Optional

try:
    import win32com.client
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


def get_install_dir() -> str:
    """Return user-level program files installation directory on C: drive."""
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
    return os.path.join(local_app_data, "Programs", "NetPulse")


def get_data_dir() -> str:
    """Return persistent user data directory."""
    app_data = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
    return os.path.join(app_data, "NetPulse")


def is_process_running(exe_name: str = "NetPulse.exe") -> bool:
    """Check if NetPulse is currently running."""
    try:
        output = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {exe_name}"], text=True)
        return exe_name.lower() in output.lower()
    except Exception:
        return False


def kill_running_process(exe_name: str = "NetPulse.exe") -> None:
    """Terminate running instances before installation."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", exe_name], capture_output=True)
    except Exception:
        pass


def create_windows_shortcut(target_exe: str, lnk_path: str, icon_path: str, description: str = "NetPulse") -> bool:
    """Create a Windows .lnk shortcut."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(lnk_path)), exist_ok=True)
        if HAS_WIN32:
            shell = win32com.client.Dispatch("WScript.Shell")
            s = shell.CreateShortCut(lnk_path)
            s.TargetPath = os.path.abspath(target_exe)
            s.WorkingDirectory = os.path.dirname(os.path.abspath(target_exe))
            s.IconLocation = f"{os.path.abspath(icon_path)},0"
            s.Description = description
            s.save()
            return True
        else:
            ps_script = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut('{lnk_path}'); "
                f"$s.TargetPath = '{target_exe}'; "
                f"$s.WorkingDirectory = '{os.path.dirname(target_exe)}'; "
                f"$s.IconLocation = '{icon_path},0'; "
                f"$s.Description = '{description}'; "
                f"$s.Save();"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
            return True
    except Exception as exc:
        print(f"[!] Warning: Could not create shortcut at {lnk_path}: {exc}")
        return False


def enable_autostart(exe_path: str) -> bool:
    """Register NetPulse in Windows Registry (HKCU Run) for automatic startup on PC boot."""
    reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "NetPulse"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
        
        # Remove old legacy NetMonitor.vbs from Startup folder if present
        app_data = os.environ.get("APPDATA", "")
        old_vbs = os.path.join(app_data, r"Microsoft\Windows\Start Menu\Programs\Startup\NetMonitor.vbs")
        if os.path.exists(old_vbs):
            try:
                os.remove(old_vbs)
            except Exception:
                pass
        return True
    except Exception as exc:
        print(f"[!] Warning: Could not configure autostart in registry: {exc}")
        return False


def copy_existing_data(source_dir: str, target_data_dir: str) -> None:
    """Copy existing CSV monitoring logs and settings to %APPDATA%\\NetPulse."""
    os.makedirs(target_data_dir, exist_ok=True)
    files_to_copy = ["net_log.csv", "speed_log.csv", "netpulse_settings.json"]
    for filename in files_to_copy:
        src = os.path.join(source_dir, filename)
        dst = os.path.join(target_data_dir, filename)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
                print(f"  [+] Migrated data: {filename} -> {dst}")
            except Exception as exc:
                print(f"  [!] Could not copy {filename}: {exc}")

    # Copy old/ folder if exists
    src_old = os.path.join(source_dir, "old")
    dst_old = os.path.join(target_data_dir, "old")
    if os.path.exists(src_old) and not os.path.exists(dst_old):
        try:
            shutil.copytree(src_old, dst_old)
            print("  [+] Migrated historical logs from old/ folder.")
        except Exception:
            pass


def create_uninstaller_script(install_dir: str, data_dir: str) -> None:
    """Generate uninstall.bat in the install directory."""
    uninstaller_path = os.path.join(install_dir, "uninstall.bat")
    content = f"""@echo off
setlocal
echo ========================================================
echo Uninstalling NetPulse...
echo ========================================================

REM 1. Stop running NetPulse process
taskkill /F /IM NetPulse.exe 2>nul

REM 2. Remove Windows Autostart from Registry
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "NetPulse" /f 2>nul

REM 3. Remove Desktop & Start Menu Shortcuts
del "%USERPROFILE%\\Desktop\\NetPulse.lnk" 2>nul
del "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\NetPulse.lnk" 2>nul
del "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\NetMonitor.vbs" 2>nul

echo Shortcuts and autostart removed.
echo.
set /p DEL_DATA="Do you want to delete monitoring logs and settings (%APPDATA%\\NetPulse)? (Y/N): "
if /i "%DEL_DATA%"=="Y" (
    rmdir /S /Q "{data_dir}" 2>nul
    echo Data folder deleted.
) else (
    echo Monitoring data preserved at: {data_dir}
)

echo.
echo To complete uninstall, deleting application files...
cd /d "%TEMP%"
rmdir /S /Q "{install_dir}" 2>nul

echo ========================================================
echo NetPulse has been successfully uninstalled.
echo ========================================================
pause
"""
    with open(uninstaller_path, "w", encoding="utf-8") as f:
        f.write(content)


def run_install(source_dir: str) -> bool:
    """Execute full NetPulse installation."""
    print("=" * 60)
    print("           NetPulse Windows Installer")
    print("=" * 60)

    dist_dir = os.path.join(source_dir, "dist", "NetPulse")
    dist_exe = os.path.join(dist_dir, "NetPulse.exe")

    if not os.path.exists(dist_exe):
        print(f"[!] Built executable not found at: {dist_exe}")
        print("    Running build.bat first...")
        build_bat = os.path.join(source_dir, "build.bat")
        if os.path.exists(build_bat):
            subprocess.run([build_bat], cwd=source_dir, check=True)
        if not os.path.exists(dist_exe):
            print("[ERROR] Could not build NetPulse.exe. Aborting.")
            return False

    install_dir = get_install_dir()
    data_dir = get_data_dir()
    installed_exe = os.path.join(install_dir, "NetPulse.exe")
    installed_ico = os.path.join(install_dir, "netpulse.ico")

    # 1. Check if running
    if is_process_running("NetPulse.exe"):
        print("[*] NetPulse is currently running. Stopping it for installation...")
        kill_running_process("NetPulse.exe")

    # 2. Copy application files to C:\Users\<User>\AppData\Local\Programs\NetPulse
    print(f"[*] Installing NetPulse to:\n    {install_dir}")
    os.makedirs(install_dir, exist_ok=True)

    for item in os.listdir(dist_dir):
        s = os.path.join(dist_dir, item)
        d = os.path.join(install_dir, item)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)

    # Copy icon if not inside install_dir
    src_ico = os.path.join(source_dir, "netpulse.ico")
    if os.path.exists(src_ico):
        shutil.copy2(src_ico, installed_ico)

    # 3. Create Windows Shortcuts
    desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
    desktop_lnk = os.path.join(desktop, "NetPulse.lnk")
    start_menu = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs")
    start_lnk = os.path.join(start_menu, "NetPulse.lnk")

    print("[*] Creating shortcuts...")
    create_windows_shortcut(installed_exe, desktop_lnk, installed_ico, "NetPulse Network Monitor")
    create_windows_shortcut(installed_exe, start_lnk, installed_ico, "NetPulse Network Monitor")
    print(f"  [+] Desktop Shortcut:    {desktop_lnk}")
    print(f"  [+] Start Menu Shortcut: {start_lnk}")

    # 4. Enable Autostart on Windows boot
    print("[*] Configuring automatic start on PC boot...")
    enable_autostart(installed_exe)
    print("  [+] Windows Autostart registered (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run)")

    # 5. Migrate existing logs & config
    print("[*] Checking data logs...")
    copy_existing_data(source_dir, data_dir)
    print(f"  [+] User data folder ready at:\n      {data_dir}")

    # 6. Create uninstaller
    create_uninstaller_script(install_dir, data_dir)

    print("\n" + "=" * 60)
    print("  NetPulse installation complete!")
    print("  - App installed on C: drive at:")
    print(f"    {installed_exe}")
    print("  - NetPulse will now automatically start every time you turn on your PC.")
    print("  - You can control it anytime:")
    print("    * Right-click the NetPulse icon in the system tray (near the clock)")
    print("    * Toggle 'Start with Windows' on or off anytime")
    print("    * Double-click the desktop mini-widget to view the dashboard")
    print("=" * 60)
    return True


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    success = run_install(current_dir)
    if success:
        start_now = input("\nWould you like to launch NetPulse now? (Y/n): ").strip().lower()
        if start_now in ("", "y", "yes"):
            install_dir = get_install_dir()
            exe = os.path.join(install_dir, "NetPulse.exe")
            print(f"Starting {exe}...")
            subprocess.Popen([exe], cwd=install_dir)

