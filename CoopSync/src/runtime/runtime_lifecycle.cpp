#include "runtime_lifecycle.h"
#include "runtime_sampler.h"
#include <atomic>
#include <cstdio>
#include <cwchar>
#include <memory>
#include <new>
#include <string>

namespace {
using coopsync::runtime::RuntimeConfigV1;
using coopsync::runtime::RuntimePhase;
using coopsync::runtime::RuntimeStatusV1;
constexpr std::size_t kMaxRecordBytes = 65536;
constexpr std::size_t kMaxDirectoryChars = 32000;
SRWLOCK control_lock = SRWLOCK_INIT;
std::atomic<RuntimePhase> phase{RuntimePhase::Dormant};
std::atomic<DWORD> last_error{ERROR_SUCCESS};
std::atomic<std::uint64_t> sample_count{0};
std::atomic<std::uint64_t> file_sequence{0};

struct Control {
    HANDLE stop_event = nullptr;
    HANDLE worker = nullptr;
    HANDLE log = INVALID_HANDLE_VALUE;
    HMODULE worker_reference = nullptr;
    DWORD interval_ms = 100;
    DWORD worker_id = 0;
    ~Control() {
        if (worker) CloseHandle(worker);
        if (stop_event) CloseHandle(stop_event);
        if (log != INVALID_HANDLE_VALUE) CloseHandle(log);
    }
};
Control* control = nullptr; // Protected by control_lock; worker retains its context.

struct ExclusiveLock {
    ExclusiveLock() { AcquireSRWLockExclusive(&control_lock); }
    ~ExclusiveLock() { ReleaseSRWLockExclusive(&control_lock); }
};

bool CopyBytes(const void* source, void* target, std::size_t bytes) {
    SIZE_T copied = 0;
    return ReadProcessMemory(GetCurrentProcess(), source, target, bytes, &copied)
        && copied == bytes;
}

bool CopyDirectory(const wchar_t* source, std::wstring& value) {
    if (!source) return false;
    for (std::size_t i = 0; i < kMaxDirectoryChars; ++i) {
        wchar_t character = 0;
        // Copy caller storage before returning from Start, without retaining a
        // foreign pointer or risking an unchecked dereference in the worker.
        if (!CopyBytes(source + i, &character, sizeof(character))) return false;
        if (!character) return !value.empty();
        value.push_back(character);
    }
    return false;
}

bool LocalAbsoluteDirectory(const std::wstring& path, std::wstring& canonical) {
    if (path.size() < 3 || !((path[0] >= L'A' && path[0] <= L'Z')
        || (path[0] >= L'a' && path[0] <= L'z')) || path[1] != L':'
        || (path[2] != L'\\' && path[2] != L'/')) return false;
    if (path.find_first_of(L"*?\"<>|") != std::wstring::npos
        || path.find(L':', 2) != std::wstring::npos) return false;
    std::wstring buffer(kMaxDirectoryChars + 1, L'\0');
    const DWORD length = GetFullPathNameW(path.c_str(), static_cast<DWORD>(buffer.size()),
        &buffer[0], nullptr);
    if (!length || length >= buffer.size()) return false;
    buffer.resize(length);
    const DWORD attributes = GetFileAttributesW(buffer.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY)) return false;
    canonical = std::move(buffer);
    return true;
}

bool WriteRecord(Control& current, const std::string& record) {
    if (record.empty() || record.size() > kMaxRecordBytes
        || record.front() != '{' || record.back() != '}'
        || record.find_first_of("\r\n") != std::string::npos) {
        SetLastError(ERROR_INVALID_DATA);
        return false;
    }
    DWORD written = 0;
    const DWORD length = static_cast<DWORD>(record.size());
    if (!WriteFile(current.log, record.data(), length, &written, nullptr)) return false;
    if (written != length) {
        SetLastError(ERROR_WRITE_FAULT);
        return false;
    }
    if (!WriteFile(current.log, "\n", 1, &written, nullptr)) return false;
    if (written != 1) {
        SetLastError(ERROR_WRITE_FAULT);
        return false;
    }
    return true;
}

std::string LifecycleRecord(const char* event, DWORD error) {
    char record[600]{};
    sprintf_s(record,
        "{\"record_type\":\"runtime_lifecycle\",\"event\":\"%s\",\"pid\":%lu,"
        "\"monotonic_ms\":%llu,\"error_code\":%lu,\"sample_count\":%llu,"
        "\"mode\":\"read_only_diagnostic\",\"game_operations\":false,"
        "\"scene_ready_verified\":false,\"world_sync_verified\":false,"
        "\"verified_callable_interfaces\":[]}",
        event, GetCurrentProcessId(), GetTickCount64(), error, sample_count.load());
    return record;
}

void Failure(RuntimePhase new_phase, DWORD error) {
    last_error.store(error, std::memory_order_release);
    phase.store(new_phase, std::memory_order_release);
}

void WorkerBody(Control& current) noexcept {
    bool initialized = false;
    try {
        if (!WriteRecord(current, LifecycleRecord("starting", ERROR_SUCCESS))) {
            Failure(RuntimePhase::Failed, GetLastError());
        } else {
            std::string record;
            initialized = coopsync::runtime::SamplerInitialize(record);
            if (!WriteRecord(current, record)) {
                Failure(RuntimePhase::Failed, GetLastError());
            } else if (!initialized) {
                Failure(RuntimePhase::Rejected, ERROR_BAD_EXE_FORMAT);
            } else {
                phase.store(RuntimePhase::Observing, std::memory_order_release);
                for (;;) {
                    const DWORD wait_result = WaitForSingleObject(current.stop_event, 0);
                    if (wait_result == WAIT_OBJECT_0) break;
                    if (wait_result != WAIT_TIMEOUT) {
                        Failure(RuntimePhase::Failed, GetLastError());
                        break;
                    }
                    record.clear();
                    const auto next_sequence = sample_count.load() + 1;
                    const bool keep_observing = coopsync::runtime::SamplerCapture(next_sequence, record);
                    if (!WriteRecord(current, record)) {
                        Failure(RuntimePhase::Failed, GetLastError());
                        break;
                    }
                    sample_count.store(next_sequence, std::memory_order_release);
                    if (!keep_observing) {
                        Failure(RuntimePhase::Rejected, ERROR_INVALID_DATA);
                        break;
                    }
                    const DWORD timed_result = WaitForSingleObject(current.stop_event, current.interval_ms);
                    if (timed_result == WAIT_OBJECT_0) break;
                    if (timed_result != WAIT_TIMEOUT) {
                        Failure(RuntimePhase::Failed, GetLastError());
                        break;
                    }
                }
            }
        }
        coopsync::runtime::SamplerShutdown();
        const auto final_phase = phase.load(std::memory_order_acquire);
        if (final_phase != RuntimePhase::Rejected && final_phase != RuntimePhase::Failed) {
            phase.store(RuntimePhase::Stopped, std::memory_order_release);
        }
        if (!WriteRecord(current, LifecycleRecord("ended", last_error.load()))) {
            Failure(RuntimePhase::Failed, GetLastError());
        }
        if (!FlushFileBuffers(current.log)) Failure(RuntimePhase::Failed, GetLastError());
    } catch (...) {
        coopsync::runtime::SamplerShutdown();
        Failure(RuntimePhase::Failed, ERROR_UNHANDLED_EXCEPTION);
        // An exception is a terminal observation failure, never a permission to
        // bypass the sampler's identity gate or attempt a game operation.
    }
}

DWORD WINAPI Worker(void* context) {
    auto* current = static_cast<Control*>(context);
    const HMODULE held_reference = current->worker_reference;
    WorkerBody(*current);
    // The reference protects all worker code, including shutdown and exception
    // cleanup. This last API exits the thread while releasing it atomically.
    if (held_reference) FreeLibraryAndExitThread(held_reference, 0);
    return 0; // Unit-test build may compile this worker directly into an EXE.
}

} // namespace

extern "C" DWORD WINAPI CoopSyncRuntimeStart(const RuntimeConfigV1* supplied) {
    try {
        RuntimeConfigV1 config{};
        if (!supplied || !CopyBytes(supplied, &config, sizeof(config))
            || config.size != sizeof(config)
            || config.version != coopsync::runtime::kRuntimeAbiVersion
            || config.sample_interval_ms < 50 || config.sample_interval_ms > 2000) return ERROR_INVALID_PARAMETER;
        for (const auto reserved : config.reserved) if (reserved) return ERROR_INVALID_PARAMETER;
        std::wstring copied_directory, output_directory;
        if (!CopyDirectory(config.output_directory, copied_directory)
            || !LocalAbsoluteDirectory(copied_directory, output_directory)) return ERROR_INVALID_PARAMETER;

        ExclusiveLock locked;
        if (control) {
            const DWORD finished = WaitForSingleObject(control->worker, 0);
            if (finished == WAIT_TIMEOUT) return ERROR_ALREADY_EXISTS;
            if (finished != WAIT_OBJECT_0) return GetLastError();
            delete control;
            control = nullptr;
        }
        auto next = std::make_unique<Control>();
        next->interval_ms = config.sample_interval_ms;
        next->stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!next->stop_event) return GetLastError();
        wchar_t filename[150]{};
        swprintf_s(filename, L"CoopSyncRuntime_%lu_%llu_%llu.jsonl", GetCurrentProcessId(),
            GetTickCount64(), file_sequence.fetch_add(1));
        if (output_directory.back() != L'\\') output_directory.push_back(L'\\');
        output_directory += filename;
        next->log = CreateFileW(output_directory.c_str(), GENERIC_WRITE, FILE_SHARE_READ,
            nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (next->log == INVALID_HANDLE_VALUE) return GetLastError();
        HMODULE own_module = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
            reinterpret_cast<LPCWSTR>(&CoopSyncRuntimeStart), &own_module)) return GetLastError();
        // The fake lifecycle test is an EXE and cannot use FreeLibrary on its
        // main module. The production DLL always takes a releasable reference.
        if (own_module != GetModuleHandleW(nullptr)) next->worker_reference = own_module;
        last_error.store(ERROR_SUCCESS, std::memory_order_release);
        sample_count.store(0, std::memory_order_release);
        phase.store(RuntimePhase::Starting, std::memory_order_release);
        next->worker = CreateThread(nullptr, 0, Worker, next.get(), 0, &next->worker_id);
        if (!next->worker) {
            const DWORD error = GetLastError();
            if (next->worker_reference) FreeLibrary(next->worker_reference);
            Failure(RuntimePhase::Failed, error);
            return error;
        }
        control = next.release();
        return ERROR_SUCCESS;
    } catch (const std::bad_alloc&) {
        return ERROR_NOT_ENOUGH_MEMORY;
    } catch (...) {
        return ERROR_UNHANDLED_EXCEPTION;
    }
}

extern "C" DWORD WINAPI CoopSyncRuntimeStop(DWORD timeout_ms) {
    if (timeout_ms > 10000) return ERROR_INVALID_PARAMETER;
    ExclusiveLock locked;
    if (!control) return ERROR_SUCCESS;
    if (GetCurrentThreadId() == control->worker_id) return ERROR_POSSIBLE_DEADLOCK;
    if (!SetEvent(control->stop_event)) return GetLastError();
    const auto current_phase = phase.load(std::memory_order_acquire);
    if (current_phase == RuntimePhase::Starting || current_phase == RuntimePhase::Observing)
        phase.store(RuntimePhase::Stopping, std::memory_order_release);
    const DWORD wait_result = WaitForSingleObject(control->worker, timeout_ms);
    if (wait_result == WAIT_TIMEOUT) return ERROR_TIMEOUT;
    if (wait_result != WAIT_OBJECT_0) return GetLastError();
    delete control;
    control = nullptr;
    return ERROR_SUCCESS;
}

extern "C" DWORD WINAPI CoopSyncRuntimeGetStatus(RuntimeStatusV1* supplied) {
    RuntimeStatusV1 previous{};
    if (!supplied || !CopyBytes(supplied, &previous, sizeof(previous))
        || previous.size != sizeof(previous)
        || previous.version != coopsync::runtime::kRuntimeAbiVersion) return ERROR_INVALID_PARAMETER;
    RuntimeStatusV1 status{};
    status.size = sizeof(status);
    status.version = coopsync::runtime::kRuntimeAbiVersion;
    status.phase = static_cast<std::uint32_t>(phase.load(std::memory_order_acquire));
    status.error_code = last_error.load(std::memory_order_acquire);
    status.sample_count = sample_count.load(std::memory_order_acquire);
    SIZE_T copied = 0;
    // This writes only the caller-provided ABI response, never a game object.
    return WriteProcessMemory(GetCurrentProcess(), supplied, &status, sizeof(status), &copied)
        && copied == sizeof(status) ? ERROR_SUCCESS : ERROR_INVALID_PARAMETER;
}

#ifndef COOPSYNC_RUNTIME_NO_DLLMAIN
BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) {
    // No automatic observer, hook, game call, file IO, or wait under loader lock.
    return TRUE;
}
#endif
