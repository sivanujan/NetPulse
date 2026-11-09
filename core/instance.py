"""Single instance management, legacy monitor collision protection, and Windows autostart."""

from __future__ import annotations

import os
import sys
import winreg
from typing import Optional, Tuple

IS_WIN = sys.platform.startswith("win")

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    ERROR_ALREADY_EXISTS = 183


def get_legacy_startup_file() -> str:
    """Path to the legacy NetMonitor.vbs in Windows Startup folder."""
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(
        appdata,
        r"Microsoft\Windows\Start Menu\Programs\Startup",
        "NetMonitor.vbs",
    )


def is_pid_alive(pid: int) -> bool:
    """Check if process with given PID is actively running on Windows."""
    if not IS_WIN:
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    STILL_ACTIVE = 259
    return exit_code.value == STILL_ACTIVE


def check_legacy_monitor_running(base_dir: str = ".") -> Tuple[bool, Optional[int]]:
    """Check if legacy net_monitor.py is actively running via monitor.pid."""
    pid_file = os.path.join(base_dir, "monitor.pid")
    if not os.path.exists(pid_file):
        return False, None

    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        if is_pid_alive(pid):
            return True, pid
        return False, None
    except Exception:
        return False, None


class SingleInstanceLock:
    """Enforces a single running instance of NetPulse using a Win32 Mutex."""

    def __init__(self, mutex_name: str = "NetPulse_SingleInstance_App_Mutex") -> None:
        self.mutex_name = mutex_name
        self.mutex_handle: Optional[int] = None
        self.acquired = False

    def acquire(self) -> bool:
        """Attempt to acquire named mutex. Return True if this is the only instance."""
        if not IS_WIN:
            return True

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        last_error = kernel32.GetLastError()

        if last_error == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            self.acquired = False
            return False

        self.mutex_handle = handle
        self.acquired = True
        return True

    def release(self) -> None:
        """Release and close the Win32 mutex."""
        if IS_WIN and self.mutex_handle:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.ReleaseMutex(self.mutex_handle)
            kernel32.CloseHandle(self.mutex_handle)
            self.mutex_handle = None
            self.acquired = False


class AutostartManager:
    """Manages Windows Registry autostart (HKCU Run) and legacy VBS cleanup."""

    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "NetPulse"

    @classmethod
    def get_run_command(cls) -> str:
        """Determine command line string to launch NetPulse on Windows startup."""
        if getattr(sys, "frozen", False):
            # PyInstaller binary
            return f'"{sys.executable}"'

        # Running from source: use pythonw if available so no console window flashes
        python_exe = sys.executable
        pythonw_cand = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        exe_to_use = pythonw_cand if os.path.exists(pythonw_cand) else python_exe

        app_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        return f'"{exe_to_use}" "{app_py}"'

    @classmethod
    def is_autostart_enabled(cls) -> bool:
        """Check if HKCU Run entry exists for NetPulse."""
        if not IS_WIN:
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, cls.APP_NAME)
                return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @classmethod
    def remove_legacy_vbs(cls) -> bool:
        """Remove legacy NetMonitor.vbs from Windows Startup folder."""
        path = get_legacy_startup_file()
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception:
                return False
        return False

    @classmethod
    def set_autostart(cls, enabled: bool) -> bool:
        """Enable or disable Windows autostart. When enabling, removes legacy NetMonitor.vbs."""
        if not IS_WIN:
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    cmd = cls.get_run_command()
                    winreg.SetValueEx(
                        key, cls.APP_NAME, 0, winreg.REG_SZ, cmd
                    )
                    # Safe explicit migration: Remove old NetMonitor.vbs now
                    cls.remove_legacy_vbs()
                else:
                    try:
                        winreg.DeleteValue(key, cls.APP_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except Exception:
            return False

