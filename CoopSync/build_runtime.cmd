@echo off
setlocal
cd /d "%~dp0"
call tools\find_msvc.cmd
if errorlevel 1 exit /b 1
if not exist build mkdir build
if not exist build\runtime mkdir build\runtime
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /LD /Isrc /Fobuild\runtime\ src\runtime\runtime_lifecycle.cpp src\runtime\runtime_sampler.cpp src\runtime\runtime_world.cpp bcrypt.lib /link /OUT:build\CoopSyncRuntime.dll /IMPLIB:build\runtime\CoopSyncRuntime.lib /DEF:src\runtime\runtime_exports.def /INCREMENTAL:NO
if errorlevel 1 exit /b 1
call tests\build_runtime_lifecycle_tests.cmd
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /Isrc /Fobuild\runtime\ /Febuild\RuntimeDllGateTests.exe tests\runtime_dll_gate_tests.cpp /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
build\RuntimeDllGateTests.exe
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /Fobuild\runtime\ /Febuild\RuntimeWorldMockTests.exe research\runtime_world_mock_tests.cpp /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
build\RuntimeWorldMockTests.exe
if errorlevel 1 exit /b 1
call tools\find_python.cmd
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tests\runtime_control_tests.py
if errorlevel 1 exit /b 1
"%COOPSYNC_PYTHON%" -X utf8 -B tests\native_runtime_analysis_tests.py
exit /b %errorlevel%
