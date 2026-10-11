@echo off
setlocal
cd /d "%~dp0"
call build.cmd
if errorlevel 1 exit /b 1
call tools\find_python.cmd
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tests\integration_tests.py
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tests\session_fault_tests.py
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tools\observe_game.py --self-check
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B research\cinematic_runtime_probe.py --self-check
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B research\ui_skip_runtime_probe.py --self-check
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tests\runtime_analysis_tests.py
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tests\test_ui_runtime_analysis.py
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tools\observe_game.py --check
exit /b %errorlevel%
