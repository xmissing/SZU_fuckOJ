@echo off
setlocal
cd /d "%~dp0"

rem Find a Python that already has fastapi + uvicorn + requests.
set "PY="
call :try_py "py -3"
if not defined PY call :try_py "python"
if not defined PY call :try_py "python3"

if not defined PY (
    echo.
    echo [ERROR] No Python with fastapi + uvicorn + requests was found.
    echo.
    echo         Install the dependencies first:
    echo             pip install -r requirements.txt
    echo.
    echo         If you have several Pythons, point to one explicitly:
    echo             "C:\Python313\python.exe" webapp.py
    echo.
    pause
    exit /b 1
)

echo ==========================================
echo   OJ Auto Console
echo   Python: %PY%
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
