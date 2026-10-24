@echo off
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  1) bundled runtime first: the "download and run" package ships
rem     its own Python, so nothing has to be installed on the machine
rem ---------------------------------------------------------------
set "PY="
if exist "runtime\python.exe" (
    "runtime\python.exe" -c "import fastapi, uvicorn, requests" >nul 2>nul
    if not errorlevel 1 set "PY=runtime\python.exe"
)

rem ---------------------------------------------------------------
rem  2) fall back to a system Python (for people who run from source)
rem ---------------------------------------------------------------
if not defined PY call :try_py "py -3"
if not defined PY call :try_py "python"
if not defined PY call :try_py "python3"

if not defined PY (
    echo.
    echo [ERROR] No usable Python found.
    echo.
    echo         This package is supposed to carry its own runtime in
    echo         the "runtime" folder. If it is missing, either
    echo         re-download the full zip from:
    echo             https://github.com/xmissing/SZU_fuckOJ/releases
    echo         or install Python 3.9+ and run:
    echo             pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if /i "%PY%"=="runtime\python.exe" (set "PYSRC=bundled, nothing to install") else (set "PYSRC=system Python")

echo ==========================================
echo   OJ Auto Console
echo   Python : %PY%
echo   Source : %PYSRC%
echo   Close this window to stop the server.
echo ==========================================
echo.

%PY% webapp.py

if errorlevel 1 (
    echo.
    echo [ERROR] Startup failed - see the message above.
    pause
)
endlocal
exit /b 0

:try_py
rem %~1 = candidate interpreter, may carry arguments (e.g. py -3)
%~1 -c "import fastapi, uvicorn, requests" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
exit /b 0
