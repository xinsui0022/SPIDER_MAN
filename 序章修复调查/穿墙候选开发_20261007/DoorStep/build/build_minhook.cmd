@echo off
setlocal
call "C:\D\VS_2022\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
pushd "%~dp0.."
if not exist "build\minhook-obj" mkdir "build\minhook-obj"
cl /nologo /TC /c /O2 /MT /W4 /DNDEBUG /DWIN32_LEAN_AND_MEAN /Ivendor\minhook\include /Ivendor\minhook\src /Ivendor\minhook\src\hde /Fobuild\minhook-obj\ vendor\minhook\src\buffer.c vendor\minhook\src\hook.c vendor\minhook\src\trampoline.c vendor\minhook\src\hde\hde64.c
if errorlevel 1 exit /b 1
lib /nologo /MACHINE:X64 /OUT:build\minhook.x64.lib build\minhook-obj\buffer.obj build\minhook-obj\hook.obj build\minhook-obj\trampoline.obj build\minhook-obj\hde64.obj
if errorlevel 1 exit /b 1
exit /b 0
