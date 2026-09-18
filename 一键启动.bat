@echo off
title LLama Launcher - One Click Start
cd /d "%~dp0"

rem ===== choose a working python =====
set "VENV_PY=%~dp0.venv\Scripts\pythonw.exe"
set "FALLBACK_PY=C:\ProgramData\miniconda3\pythonw.exe"

set "PY="
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import PyQt6" >nul 2>&1
    if not errorlevel 1 set "PY=%VENV_PY%"
)
if not defined PY if exist "%FALLBACK_PY%" set "PY=%FALLBACK_PY%"
if not defined PY (
    echo [ERROR] no usable python found.
    echo   venv : %VENV_PY%
    echo   conda: %FALLBACK_PY%
    echo install PyQt6 first or edit FALLBACK_PY in this script.
    pause
    exit /b 1
)

start "LLamaLauncher" /D "%~dp0" "%PY%" "%~dp0main.py"
exit /b
