@echo off
setlocal
cd /d "%~dp0"

set "PY="
for %%P in ("py -3" "python" "python3") do (
    if not defined PY (
        %%P -c "import fastapi, uvicorn, requests" >nul 2>nul && set "PY=%%P"
    )
)

if not defined PY (
    echo.
    echo [ERROR] 没找到装了 fastapi + uvicorn + requests 的 Python。
    echo 先装依赖：
    echo     pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo ==========================================
echo   OJ Auto Console  -  http://127.0.0.1:8765
echo   Python: %PY%
echo   关掉这个窗口即停止服务。
echo ==========================================
echo.

%PY% webapp.py

if errorlevel 1 (
    echo.
    echo [ERROR] 启动失败，看上面的报错。
    pause
)
endlocal
