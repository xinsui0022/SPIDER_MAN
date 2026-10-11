@echo off
chcp 65001 >nul
echo 这是诊断记录器，不是修复补丁。不会修改游戏内存、存档或配置。
echo 记录持续 10 分钟；按 Ctrl+C 可提前停止。
echo 请先让主机停在序章目标正常显示的位置，再让客机加入。
"C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe" -B "%~dp0observe_missions.py" --seconds 600
echo 记录已结束。
pause
