@echo off
setlocal
cd /d "%~dp0"
call tools\find_python.cmd
if errorlevel 1 exit /b 1
echo Python: "%COOPSYNC_PYTHON%"
"%COOPSYNC_PYTHON%" -c "import pefile; print('pefile: ' + pefile.__version__)"
if errorlevel 1 (
  echo Install the requirements into this Python: "%COOPSYNC_PYTHON%" -m pip install -r requirements.txt
  exit /b 1
)
"%COOPSYNC_PYTHON%" -X utf8 -B tools\show_configuration.py
if errorlevel 1 exit /b 1
call tools\find_msvc.cmd
if errorlevel 1 exit /b 1
echo MSVC x64: ready
exit /b 0

