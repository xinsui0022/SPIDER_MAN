#include "runtime/runtime_lifecycle.h"
#include <atomic>
#include <cstdio>
#include <stdexcept>
#include <string>

namespace {
enum class FakeMode { Accept, RejectInitialization, RejectCapture, MalformedInitialization,
    ThrowCapture, HoldCapture };
std::atomic<FakeMode> fake_mode{FakeMode::Accept};
std::atomic<bool> capture_entered{false};
std::atomic<bool> release_capture{false};
std::atomic<unsigned> shutdown_calls{0};
unsigned checks = 0;
unsigned failures = 0;

void Check(bool accepted, const char* message) {
    ++checks;
    if (!accepted) {
        ++failures;
        std::printf("FAIL: %s\n", message);
    }
}

coopsync::runtime::RuntimeStatusV1 Status() {
    coopsync::runtime::RuntimeStatusV1 status{};
    status.size = sizeof(status);
    status.version = coopsync::runtime::kRuntimeAbiVersion;
    if (CoopSyncRuntimeGetStatus(&status) != ERROR_SUCCESS) ++failures;
    return status;
}

bool WaitPhase(coopsync::runtime::RuntimePhase wanted) {
    const auto deadline = GetTickCount64() + 2000;
    do {
        if (Status().phase == static_cast<std::uint32_t>(wanted)) return true;
        Sleep(5);
    } while (GetTickCount64() < deadline);
    return false;
}

bool WaitSamples(std::uint64_t count) {
    const auto deadline = GetTickCount64() + 2000;
    do {
        if (Status().sample_count >= count) return true;
        Sleep(5);
    } while (GetTickCount64() < deadline);
    return false;
}
} // namespace

namespace coopsync::runtime {
bool SamplerInitialize(std::string& record) {
    record = fake_mode.load() == FakeMode::MalformedInitialization ? "invalid record"
        : "{\"record_type\":\"offline_fake_session\",\"game_operations\":false}";
    return fake_mode.load() != FakeMode::RejectInitialization;
}
bool SamplerCapture(std::uint64_t, std::string& record) {
    capture_entered.store(true);
    if (fake_mode.load() == FakeMode::ThrowCapture) throw std::runtime_error("offline fake exception");
    while (fake_mode.load() == FakeMode::HoldCapture && !release_capture.load()) Sleep(1);
    record = "{\"record_type\":\"offline_fake_snapshot\",\"game_operations\":false}";
    return fake_mode.load() != FakeMode::RejectCapture;
}
void SamplerShutdown() noexcept { shutdown_calls.fetch_add(1); }
} // namespace coopsync::runtime

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) {
        std::printf("Usage: RuntimeLifecycleTests.exe absolute-existing-output-directory\n");
        return 2;
    }
    static_assert(sizeof(coopsync::runtime::RuntimeConfigV1) == 40, "x64 config ABI");
    static_assert(sizeof(coopsync::runtime::RuntimeStatusV1) == 40, "x64 status ABI");
    using coopsync::runtime::RuntimePhase;
    auto status = Status();
    Check(status.phase == static_cast<std::uint32_t>(RuntimePhase::Dormant), "no implicit DLL lifecycle startup");
    Check(!status.game_operations && !status.world_sync_verified && !status.callable_interfaces_verified,
        "capabilities initially disabled");
    Check(CoopSyncRuntimeStart(nullptr) == ERROR_INVALID_PARAMETER, "null config rejected");
    Check(CoopSyncRuntimeGetStatus(nullptr) == ERROR_INVALID_PARAMETER, "null status rejected");
    status.version = 2;
    Check(CoopSyncRuntimeGetStatus(&status) == ERROR_INVALID_PARAMETER, "unknown status version rejected");
    coopsync::runtime::RuntimeConfigV1 config{};
    config.size = sizeof(config);
    config.version = coopsync::runtime::kRuntimeAbiVersion;
    config.output_directory = argv[1];
    config.sample_interval_ms = 50;
    config.version = 2;
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "unknown config version rejected");
    config.version = coopsync::runtime::kRuntimeAbiVersion;
    config.reserved[0] = 1;
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "reserved flags cannot enable controls");
    config.reserved[0] = 0;
    config.sample_interval_ms = 49;
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "too-fast observer rejected");
    config.sample_interval_ms = 2001;
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "excessive period rejected");
    config.sample_interval_ms = 50;
    config.output_directory = L"relative";
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "relative directory rejected");
    config.output_directory = L"\\\\server\\share";
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "network directory rejected");
    config.output_directory = reinterpret_cast<const wchar_t*>(1);
    Check(CoopSyncRuntimeStart(&config) == ERROR_INVALID_PARAMETER, "invalid caller path pointer rejected safely");
    std::wstring copied_path(argv[1]);
    config.output_directory = copied_path.c_str();
    Check(CoopSyncRuntimeStart(&config) == ERROR_SUCCESS, "explicit start schedules observer");
    copied_path.assign(L"caller buffer changed after return");
    config.output_directory = argv[1];
    Check(CoopSyncRuntimeStart(&config) == ERROR_ALREADY_EXISTS, "duplicate observer rejected");
    Check(WaitSamples(2), "scheduled fake observer captures more than one sample");
    status = Status();
    Check(!status.game_operations && !status.world_sync_verified && !status.callable_interfaces_verified,
        "fake activity cannot enable capabilities");
    Check(CoopSyncRuntimeStop(10001) == ERROR_INVALID_PARAMETER, "bounded stop deadline required");
    Check(CoopSyncRuntimeStop(2000) == ERROR_SUCCESS, "stop waits and reclaims observer");
    Check(Status().phase == static_cast<std::uint32_t>(RuntimePhase::Stopped), "clean stop status preserved");
    Check(CoopSyncRuntimeStop(0) == ERROR_SUCCESS, "stop is idempotent");

    fake_mode = FakeMode::RejectInitialization;
    Check(CoopSyncRuntimeStart(&config) == ERROR_SUCCESS, "restart after clean stop is allowed");
    Check(WaitPhase(RuntimePhase::Rejected), "failed identity gate stops worker");
    Check(Status().sample_count == 0, "no capture before identity acceptance");
    Check(CoopSyncRuntimeStop(2000) == ERROR_SUCCESS, "rejected worker can be reclaimed");

    fake_mode = FakeMode::RejectCapture;
    Check(CoopSyncRuntimeStart(&config) == ERROR_SUCCESS, "capture rejection scenario starts");
    Check(WaitPhase(RuntimePhase::Rejected), "capture rejection stops further reads");
    Check(Status().sample_count == 1, "final rejecting record is retained");
    Check(CoopSyncRuntimeStop(2000) == ERROR_SUCCESS, "capture rejection cleanup succeeds");

    fake_mode = FakeMode::MalformedInitialization;
    Check(CoopSyncRuntimeStart(&config) == ERROR_SUCCESS, "malformed record scenario starts");
    Check(WaitPhase(RuntimePhase::Failed), "malformed sampler record rejects log write");
    Check(Status().sample_count == 0, "malformed initialization never starts captures");
    Check(CoopSyncRuntimeStop(2000) == ERROR_SUCCESS, "malformed record cleanup succeeds");

    fake_mode = FakeMode::ThrowCapture;
    Check(CoopSyncRuntimeStart(&config) == ERROR_SUCCESS, "exception scenario starts");
    Check(WaitPhase(RuntimePhase::Failed), "sampler exception becomes terminal failure");
    Check(CoopSyncRuntimeStop(2000) == ERROR_SUCCESS, "exception cleanup succeeds");

    fake_mode = FakeMode::HoldCapture;
    capture_entered = false;
    release_capture = false;
    Check(CoopSyncRuntimeStart(&config) == ERROR_SUCCESS, "held capture scenario starts");
    const auto deadline = GetTickCount64() + 2000;
    while (!capture_entered.load() && GetTickCount64() < deadline) Sleep(5);
    Check(capture_entered.load(), "fake capture entered before timeout test");
    Check(CoopSyncRuntimeStop(0) == ERROR_TIMEOUT, "timeout retains active observer");
    Check(CoopSyncRuntimeStart(&config) == ERROR_ALREADY_EXISTS, "timeout cannot admit overlapping worker");
    release_capture = true;
    Check(CoopSyncRuntimeStop(2000) == ERROR_SUCCESS, "later stop reclaims timed-out observer");
    Check(shutdown_calls.load() == 6, "each completed worker shuts down exactly once");
    std::printf("%u runtime lifecycle checks, %u failures; OFFLINE_FAKE_ONLY\n", checks, failures);
    return failures ? 1 : 0;
}
