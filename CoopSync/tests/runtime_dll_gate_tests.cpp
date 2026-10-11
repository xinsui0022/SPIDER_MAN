#include "runtime/runtime_lifecycle.h"
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>

int main() {
    using namespace coopsync::runtime;
    const HMODULE dll = LoadLibraryW(L"build\\CoopSyncRuntime.dll");
    if (!dll) { std::printf("FAIL: loading diagnostic DLL: %lu\n", GetLastError()); return 1; }
    const auto start = reinterpret_cast<decltype(&CoopSyncRuntimeStart)>(GetProcAddress(dll, "CoopSyncRuntimeStart"));
    const auto stop = reinterpret_cast<decltype(&CoopSyncRuntimeStop)>(GetProcAddress(dll, "CoopSyncRuntimeStop"));
    const auto status = reinterpret_cast<decltype(&CoopSyncRuntimeGetStatus)>(GetProcAddress(dll, "CoopSyncRuntimeGetStatus"));
    if (!start || !stop || !status) return 2;
    RuntimeStatusV1 observed{};
    observed.size = sizeof(observed);
    observed.version = kRuntimeAbiVersion;
    if (status(&observed) || observed.phase != static_cast<unsigned>(RuntimePhase::Dormant) || observed.sample_count) return 3;
    wchar_t relative[180]{};
    swprintf_s(relative, L"logs\\runtime_dll_gate_%lu_%llu", GetCurrentProcessId(), GetTickCount64());
    if (!CreateDirectoryW(relative, nullptr)) return 4;
    wchar_t directory[32768]{};
    if (!GetFullPathNameW(relative, 32768, directory, nullptr)) return 5;
    RuntimeConfigV1 config{};
    config.size = sizeof(config);
    config.version = kRuntimeAbiVersion;
    config.output_directory = directory;
    config.sample_interval_ms = 100;
    if (start(&config)) return 6;
    for (unsigned i = 0; i < 200; ++i) {
        if (status(&observed)) return 7;
        if (observed.phase == static_cast<unsigned>(RuntimePhase::Rejected)) break;
        Sleep(10);
    }
    const bool rejected = observed.phase == static_cast<unsigned>(RuntimePhase::Rejected);
    const bool no_reads = observed.sample_count == 0;
    const bool disabled = !observed.game_operations && !observed.world_sync_verified && !observed.callable_interfaces_verified;
    if (stop(5000)) return 8;
    wchar_t pattern[32768]{};
    swprintf_s(pattern, L"%s\\*.jsonl", directory);
    WIN32_FIND_DATAW found{};
    HANDLE search = FindFirstFileW(pattern, &found);
    if (search == INVALID_HANDLE_VALUE) return 9;
    FindClose(search);
    std::wstring log = directory;
    log += L"\\";
    log += found.cFileName;
    std::ifstream input(log);
    const std::string content((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    const bool path_gate = content.find("host_filename_not_pinned_game_no_fixed_address_reads") != std::string::npos;
    const bool no_snapshots = content.find("runtime_snapshot") == std::string::npos;
    const bool ended = content.find("\"event\":\"ended\"") != std::string::npos;
    FreeLibrary(dll);
    if (!rejected || !no_reads || !disabled || !path_gate || !no_snapshots || !ended) return 10;
    std::printf("PASS: production DLL rejected test host before fixed-address sampling; no automatic start, zero game operations, clean Stop\n");
    return 0;
}
