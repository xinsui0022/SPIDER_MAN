@echo off
setlocal
cd /d "%~dp0"
call "C:\D\VS_2022\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
if not exist build mkdir build
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /LD /Ivendor\minhook\include /Fobuild\DoorStep.obj /Febuild\DoorStep.dll DoorStep.cpp build\minhook.x64.lib bcrypt.lib user32.lib /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /O1 /MT /W4 /Ivendor\minhook\include /Fobuild\tests.obj /Febuild\DoorStepTests.exe tests.cpp build\minhook.x64.lib /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
build\DoorStepTests.exe build\DoorStep.dll
exit /b %errorlevel%
