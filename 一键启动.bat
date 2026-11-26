@echo off
title LLama Launcher - One Click Start
cd /d "%~dp0"

rem ==========================================================
rem 1) Standalone build: run the exe sitting next to this file.
rem    Wildcard patterns use ASCII, so Chinese build names such
rem    as LLama(name)-win-x64.exe still match on a cp936 console.
rem    x64 is tried first on purpose: v0.5.15 ships an arm64 build
rem    too, and if both sit in one folder an x64 machine must not
rem    pick the arm64 exe (alphabetically arm64 would come first).
rem    Arm64.bat is the counterpart that prefers arm64.
rem ==========================================================
setlocal enabledelayedexpansion
set "APP_EXE="
for %%F in ("%~dp0LLama*win-x64*.exe") do if not defined APP_EXE set "APP_EXE=%%~fF"
if not defined APP_EXE for %%F in ("%~dp0LLama*Launcher*.exe") do if not defined APP_EXE set "APP_EXE=%%~fF"
if not defined APP_EXE for %%F in ("%~dp0LLama*.exe") do (
    set "N=%%~nxF"
    if /i not "!N:~0,6!"=="llama-" if not defined APP_EXE set "APP_EXE=%%~fF"
)
endlocal & set "APP_EXE=%APP_EXE%"
if defined APP_EXE (
    start "LLamaLauncher" /D "%~dp0" "%APP_EXE%"
    exit /b
)

rem ==========================================================
rem 2) Source run: pick any Python that has PyQt6.
rem    Same-directory interpreters are preferred, then PATH.
rem ==========================================================
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PORTABLE_PYW=%~dp0python\pythonw.exe"

set "PY="
call :try_py "%VENV_PYW%"
if not defined PY call :try_py "%PORTABLE_PYW%"
if not defined PY call :try_py "%~dp0pythonw.exe"
if not defined PY for %%P in (pythonw.exe) do if not defined PY call :try_py "%%~$PATH:P"

rem Self-heal: a build step may recreate .venv with only build deps,
rem so install the runtime requirements before giving up.
if not defined PY if exist "%VENV_PY%" if exist "%~dp0requirements.txt" (
    echo [setup] PyQt6 missing - installing requirements into .venv ...
    "%VENV_PY%" -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -r "%~dp0requirements.txt"
    call :try_py "%VENV_PYW%"
)

if not defined PY (
    echo [ERROR] no standalone exe and no Python with PyQt6 was found.
    echo   exe      : LLama*-win-x64*.exe / LLama*Launcher*.exe
    echo   venv     : %VENV_PYW%
    echo   portable : %PORTABLE_PYW%
    echo Either drop a standalone exe next to this file, or install deps:
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "LLamaLauncher" /D "%~dp0" "%PY%" "%~dp0main.py"
exit /b

rem ----------------------------------------------------------
:try_py
if defined PY exit /b
if not exist "%~1" exit /b
"%~1" -c "import PyQt6" >nul 2>&1
if not errorlevel 1 set "PY=%~1"
exit /b
