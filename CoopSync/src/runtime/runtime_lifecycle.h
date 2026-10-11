#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <cstdint>

namespace coopsync::runtime {

constexpr std::uint32_t kRuntimeAbiVersion = 1;

// This POD ABI is for the x64 build. The caller owns this memory until Start
// returns; Start copies the directory before launching the observer.
struct RuntimeConfigV1 {
    std::uint32_t size;
    std::uint32_t version;
    const wchar_t* output_directory;
    std::uint32_t sample_interval_ms;
    std::uint32_t reserved[4];
};

enum class RuntimePhase : std::uint32_t {
    Dormant = 0,
    Starting = 1,
    Observing = 2,
    Stopping = 3,
    Stopped = 4,
    Rejected = 5,
    Failed = 6,
};

struct RuntimeStatusV1 {
    std::uint32_t size;
    std::uint32_t version;
    std::uint32_t phase;
    std::uint32_t error_code;
    std::uint64_t sample_count;
    std::uint32_t game_operations; // Always zero in this diagnostic build.
    std::uint32_t world_sync_verified; // Always zero.
    std::uint32_t callable_interfaces_verified; // Always zero.
    std::uint32_t reserved;
};

} // namespace coopsync::runtime

// Call these exports outside DllMain/loader-lock callbacks. Start succeeds when
// the worker has been scheduled, not when a game hash or memory read is verified.
// Output directory must already exist and be an absolute local drive path.
// The caller must retain its DLL reference until Stop succeeds. Never force an
// unload after ERROR_TIMEOUT; the observer keeps its own temporary reference.
extern "C" DWORD WINAPI CoopSyncRuntimeStart(const coopsync::runtime::RuntimeConfigV1* config);
extern "C" DWORD WINAPI CoopSyncRuntimeStop(DWORD timeout_ms);
extern "C" DWORD WINAPI CoopSyncRuntimeGetStatus(coopsync::runtime::RuntimeStatusV1* status);

