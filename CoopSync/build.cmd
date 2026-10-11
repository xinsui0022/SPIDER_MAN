@echo off
setlocal
cd /d "%~dp0"
call tools\find_msvc.cmd
if errorlevel 1 exit /b 1
if not exist build mkdir build
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /Isrc /Fobuild\ /Febuild\CoopSync.exe src\main.cpp src\coordinator.cpp src\wire.cpp src\tcp_transport.cpp ws2_32.lib bcrypt.lib /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /Isrc /Fobuild\ /Febuild\CoordinatorTests.exe tests\coordinator_tests.cpp src\coordinator.cpp /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /Isrc /Fobuild\ /Febuild\WireTests.exe tests\wire_tests.cpp src\wire.cpp src\tcp_transport.cpp ws2_32.lib /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /WX /Isrc /Fobuild\ /Febuild\GameAdapterTests.exe tests\game_adapter_tests.cpp src\game_adapter.cpp src\coordinator.cpp /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
build\CoordinatorTests.exe
if errorlevel 1 exit /b 1
build\WireTests.exe
if errorlevel 1 exit /b 1
build\GameAdapterTests.exe
exit /b %errorlevel%
