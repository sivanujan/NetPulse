@echo off
setlocal enabledelayedexpansion
echo ========================================================
echo Building NetPulse for Windows (One-Folder Executable)
echo ========================================================

REM Ensure icon exists
if not exist "netpulse.ico" (
    echo Generating netpulse.ico...
    python generate_icon.py
)

echo Running PyInstaller...
pyinstaller --noconfirm --clean --noconsole --onedir ^
    --name NetPulse ^
    --icon netpulse.ico ^
    --add-data "netpulse.ico;." ^
    --hidden-import "matplotlib.backends.backend_pdf" ^
    --hidden-import "matplotlib.backends.backend_agg" ^
    app.py

if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] PyInstaller build failed with exit code !ERRORLEVEL!.
    exit /b !ERRORLEVEL!
)

echo.
echo ========================================================
echo Build complete!
echo Output directory: dist\NetPulse\
echo Executable:       dist\NetPulse\NetPulse.exe
echo ========================================================

