@echo off
chcp 65001 >nul
"C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe" -B "%~dp0baseline_control.py" restore
if errorlevel 1 (
    echo 恢复未完成。所有原件和结果仍保留，请查看上方原因。
    pause
    exit /b 1
)
pause
