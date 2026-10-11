@echo off
rem Called by project scripts; exports COOPSYNC_PYTHON into the caller's setlocal.
if defined COOPSYNC_PYTHON goto validate
where py.exe >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.11 3.12 3.13 3) do call :launcher %%V with_pefile
  for %%V in (3.11 3.12 3.13 3) do call :launcher %%V
)
if defined COOPSYNC_PYTHON goto validate
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :candidate "%%~fD\python.exe" with_pefile
for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /v /i "WindowsApps"') do call :candidate "%%P" with_pefile
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :candidate "%%~fD\python.exe"
for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /v /i "WindowsApps"') do call :candidate "%%P"
if not defined COOPSYNC_PYTHON (
  echo A 64-bit Python 3.11 or newer was not found. Set COOPSYNC_PYTHON to its executable.
  exit /b 1
)
:validate
"%COOPSYNC_PYTHON%" -c "import struct,sys; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8" >nul 2>nul
if errorlevel 1 (
  echo COOPSYNC_PYTHON must be an executable for 64-bit Python 3.11 or newer.
  exit /b 1
)
exit /b 0
:launcher
if defined COOPSYNC_PYTHON exit /b 0
if "%~2"=="with_pefile" (
  for /f "delims=" %%P in ('py -%~1 -c "import struct,sys,pefile; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8; print(sys.executable)" 2^>nul') do set "COOPSYNC_PYTHON=%%P"
) else (
  for /f "delims=" %%P in ('py -%~1 -c "import struct,sys; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8; print(sys.executable)" 2^>nul') do set "COOPSYNC_PYTHON=%%P"
)
exit /b 0
:candidate
if defined COOPSYNC_PYTHON exit /b 0
if not exist "%~1" exit /b 0
if "%~2"=="with_pefile" (
  "%~1" -c "import struct,sys,pefile; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8" >nul 2>nul
) else (
  "%~1" -c "import struct,sys; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8" >nul 2>nul
)
if not errorlevel 1 set "COOPSYNC_PYTHON=%~1"
exit /b 0

