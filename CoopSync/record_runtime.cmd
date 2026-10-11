@echo off
setlocal
cd /d "%~dp0"
call tools\find_python.cmd
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tools\record_runtime.py %*
exit /b %errorlevel%
