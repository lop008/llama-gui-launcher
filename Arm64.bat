@echo off
title LLama Launcher ARM64 - One Click Start
cd /d "%~dp0"

rem ==========================================================
rem ARM64 one-click start (v0.5.15+).
rem
rem Same idea as "one-click start.bat", but it prefers the arm64
rem build, so a Snapdragon / Windows-on-ARM machine never picks
rem up an x64 exe that happens to sit in the same folder.
rem
rem Lookup order:
rem   1) arm64 single-file exe next to this file
rem   2) arm64 portable build folder (the extracted ...-portable.zip)
rem   3) any launcher exe next to this file
rem   4) source run with any Python that has PyQt6
rem
rem Wildcard patterns stay ASCII, so Chinese build names such as
rem LLama(name)-win-arm64.exe still match on a cp936 console.
rem
rem Note: the launcher also needs an arm64 llama-server. On the
rem "Update llama.cpp" page both architectures are listed, with
rem your own architecture first.
rem ==========================================================
setlocal enabledelayedexpansion
set "APP_EXE="

rem 1) arm64 single-file exe
for %%F in ("%~dp0LLama*arm64*.exe") do if not defined APP_EXE set "APP_EXE=%%~fF"

rem 2) arm64 portable folder, one level down
for /D %%D in ("%~dp0*arm64-portable*") do if not defined APP_EXE (
    for %%F in ("%%~fD\LLama*arm64*.exe") do if not defined APP_EXE set "APP_EXE=%%~fF"
)

rem 3) anything else that looks like the launcher
if not defined APP_EXE for %%F in ("%~dp0LLama*Launcher*.exe") do if not defined APP_EXE set "APP_EXE=%%~fF"
if not defined APP_EXE for %%F in ("%~dp0LLama*.exe") do (
    set "N=%%~nxF"
    if /i not "!N:~0,6!"=="llama-" if not defined APP_EXE set "APP_EXE=%%~fF"
)
endlocal & set "APP_EXE=%APP_EXE%"

if defined APP_EXE goto :run

rem ==========================================================
rem 4) Source run: pick any Python that has PyQt6.
rem ==========================================================
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PORTABLE_PYW=%~dp0python\pythonw.exe"

set "PY="
call :try_py "%VENV_PYW%"
if not defined PY call :try_py "%PORTABLE_PYW%"
if not defined PY call :try_py "%~dp0pythonw.exe"
if not defined PY for %%P in (pythonw.exe) do if not defined PY call :try_py "%%~$PATH:P"

rem Self-heal: install runtime deps into .venv before giving up.
if not defined PY if exist "%VENV_PY%" if exist "%~dp0requirements.txt" (
    echo [setup] PyQt6 missing - installing requirements into .venv ...
    "%VENV_PY%" -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -r "%~dp0requirements.txt"
    call :try_py "%VENV_PYW%"
)

if not defined PY (
    echo [ERROR] no arm64 exe and no Python with PyQt6 was found.
    echo   exe      : LLama*arm64*.exe  ^(or an extracted *arm64-portable* folder^)
    echo   venv     : %VENV_PYW%
    echo   portable : %PORTABLE_PYW%
    echo Either unpack LLama-Launcher-vX.Y.Z-win-arm64.exe next to this file,
    echo or install deps:  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "LLamaLauncherArm64" /D "%~dp0" "%PY%" "%~dp0main.py"
exit /b

:run
echo [arm64] launching: "%APP_EXE%"
start "LLamaLauncherArm64" /D "%~dp0" "%APP_EXE%"
exit /b

rem ----------------------------------------------------------
:try_py
if defined PY exit /b
if not exist "%~1" exit /b
"%~1" -c "import PyQt6" >nul 2>&1
if not errorlevel 1 set "PY=%~1"
exit /b
