@echo off
rem Called by build scripts; only the x64 MSVC toolchain is accepted.
if defined COOPSYNC_VCVARS goto configure
if /i "%VSCMD_ARG_TGT_ARCH%"=="x64" (
  where cl.exe >nul 2>nul
  if not errorlevel 1 exit /b 0
)
if not defined COOPSYNC_VSWHERE set "COOPSYNC_VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%COOPSYNC_VSWHERE%" (
  echo Visual Studio discovery was unavailable. Set COOPSYNC_VCVARS to vcvars64.bat.
  exit /b 1
)
set "COOPSYNC_DISCOVERY_FILE=%TEMP%\coopsync_vs_%RANDOM%_%RANDOM%.txt"
"%COOPSYNC_VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find VC\Auxiliary\Build\vcvars64.bat > "%COOPSYNC_DISCOVERY_FILE%"
for /f "usebackq delims=" %%V in ("%COOPSYNC_DISCOVERY_FILE%") do if not defined COOPSYNC_VCVARS set "COOPSYNC_VCVARS=%%V"
del "%COOPSYNC_DISCOVERY_FILE%" >nul 2>nul
set "COOPSYNC_DISCOVERY_FILE="
if not defined COOPSYNC_VCVARS (
  echo Install MSVC C++ x64 build tools or set COOPSYNC_VCVARS to vcvars64.bat.
  exit /b 1
)
:configure
if not exist "%COOPSYNC_VCVARS%" (
  echo COOPSYNC_VCVARS does not point to an existing vcvars64.bat.
  exit /b 1
)
call "%COOPSYNC_VCVARS%" >nul
if errorlevel 1 exit /b 1
if /i not "%VSCMD_ARG_TGT_ARCH%"=="x64" (
  echo The configured Visual Studio toolchain did not select x64.
  exit /b 1
)
where cl.exe >nul 2>nul
exit /b %errorlevel%

