@echo off
chcp 65001 >nul
"C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe" -B "%~dp0baseline_control.py" prepare
if errorlevel 1 (
    echo 准备未完成。请查看上方原因，不要启动对照游戏。
    pause
    exit /b 1
)
pause
