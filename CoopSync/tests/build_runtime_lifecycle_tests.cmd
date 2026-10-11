@echo off
setlocal
cd /d "%~dp0.."
call tools\find_msvc.cmd
if errorlevel 1 exit /b 1
if not exist build mkdir build
if not exist build\runtime-lifecycle-test-logs mkdir build\runtime-lifecycle-test-logs
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /DCOOPSYNC_RUNTIME_NO_DLLMAIN /Isrc /Fobuild\ /Febuild\RuntimeLifecycleTests.exe tests\runtime_lifecycle_tests.cpp src\runtime\runtime_lifecycle.cpp /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
build\RuntimeLifecycleTests.exe "%CD%\build\runtime-lifecycle-test-logs"
exit /b %errorlevel%
