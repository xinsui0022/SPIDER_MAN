#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>

#include "runtime_sampler.h"
#include "runtime_world.h"

#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace coopsync::runtime {
namespace {
constexpr wchar_t kGameFilename[] = L"Spider-Man.exe";
constexpr char kGameHash[] = "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1";
constexpr std::uintptr_t kManager = 0x6044830, kManagerVt = 0x3CF47B0;
constexpr std::uintptr_t kSystem = 0x6044A60, kSystemVt = 0x3CF4C68;
constexpr std::uintptr_t kComponentSlot = 0x6045C30, kComponentVt = 0x3CF4100;
constexpr std::uintptr_t kOverlay = 0x7B84580, kOverlayVt = 0x4F44980, kOverlaySecondVt = 0x4F449E0;
constexpr std::uintptr_t kTasks = 0x6EFC1A0, kTaskPointer = 0x7C3EF70;
std::uintptr_t base = 0;
std::uint32_t image_size = 0;
bool initialized = false;

std::string quote(const std::string& input) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : input) {
        if (c == '"' || c == '\\') out << '\\' << static_cast<char>(c);
        else if (c < 0x20 || c >= 0x80) {
            // Task symbols in this audited layout are ASCII. Preserve unknown
            // bytes as JSON escapes rather than emitting invalid UTF-8.
            out << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(c);
        } else out << static_cast<char>(c);
    }
    out << '"';
    return out.str();
}

std::string hex(std::uint64_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << value;
    return quote(out.str());
}

class Reader {
public:
    void bytes(std::uintptr_t address, void* output, std::size_t count) {
        constexpr std::uintptr_t max_address = 0x0000800000000000ull;
        if (address < 0x10000 || !count || count > 256 || address >= max_address ||
            count > max_address - address || reads_ >= 16384 || total_ + count > 2 * 1024 * 1024) {
            throw std::runtime_error("bounded_read_refused");
        }
        ++reads_;
        total_ += count;
        SIZE_T copied = 0;
        if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(address), output, count, &copied) || copied != count) {
            throw std::runtime_error("read_failed_or_instance_invalidated");
        }
    }
    template<class T> T value(std::uintptr_t address) {
        T result{};
        bytes(address, &result, sizeof(result));
        return result;
    }
    std::string symbol(std::uintptr_t address) {
        const auto pointer = value<std::uintptr_t>(address);
        const auto count = value<std::uint32_t>(address + 8);
        if (!count) return {};
        if (!pointer || count > 256) throw std::runtime_error("symbol_bounds_refused");
        std::string result(count, '\0');
        bytes(pointer, result.data(), result.size());
        if (pointer != value<std::uintptr_t>(address) || count != value<std::uint32_t>(address + 8)) {
            throw std::runtime_error("symbol_changed_during_reads");
        }
        return result;
    }
    std::uint32_t reads() const noexcept { return reads_; }
    std::size_t total() const noexcept { return total_; }
private:
    std::uint32_t reads_ = 0;
    std::size_t total_ = 0;
};

std::uintptr_t address(std::uintptr_t rva, std::size_t count = 8) {
    if (!base || rva >= image_size || count > image_size - rva) throw std::runtime_error("rva_outside_pinned_image");
    return base + rva;
}

std::string file_hash(const wchar_t* path) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw std::runtime_error("game_file_hash_open_failed");
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD object_size = 0, received = 0;
    std::vector<unsigned char> object;
    std::array<unsigned char, 32> digest{};
    std::array<unsigned char, 65536> buffer{};
    bool okay = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (okay) okay = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size), &received, 0) >= 0;
    if (okay) {
        object.resize(object_size);
        okay = BCryptCreateHash(algorithm, &hash, object.data(), object_size, nullptr, 0, 0) >= 0;
    }
    while (okay) {
        DWORD amount = 0;
        if (!ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size()), &amount, nullptr)) { okay = false; break; }
        if (!amount) break;
        okay = BCryptHashData(hash, buffer.data(), amount, 0) >= 0;
    }
    if (okay) okay = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    if (!okay) throw std::runtime_error("game_file_hash_failed");
    std::ostringstream out;
    for (auto byte : digest) out << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(byte);
    return out.str();
}

bool cinematic_identity(Reader& reader) {
    return reader.value<std::uintptr_t>(address(kManager)) == base + kManagerVt &&
           reader.value<std::uintptr_t>(address(kSystem)) == base + kSystemVt;
}

std::string cinematic() {
    Reader reader;
    if (!cinematic_identity(reader)) return "{\"status\":\"static_identity_not_ready_or_mismatch\"}";
    const auto component = reader.value<std::uintptr_t>(address(kComponentSlot));
    if (!component) {
        const auto after = reader.value<std::uintptr_t>(address(kComponentSlot));
        const bool identities = cinematic_identity(reader);
        return std::string("{\"status\":\"") + (after == 0 && identities ? "no_selected_component_raw_only" : "selection_changed_during_reads") + "\",\"component\":\"0x0\"}";
    }
    const auto vt = reader.value<std::uintptr_t>(component);
    if (vt != base + kComponentVt) return "{\"status\":\"component_identity_mismatch\"}";
    const auto owner = reader.value<std::uintptr_t>(component + 8);
    const auto handle = reader.value<std::uint32_t>(component + 0x14);
    if (reader.value<std::uintptr_t>(address(kComponentSlot)) != component) return "{\"status\":\"selection_changed_during_reads\"}";
    const auto state58 = reader.value<std::uint32_t>(component + 0x58);
    const auto state5c = reader.value<std::uint32_t>(component + 0x5C);
    const auto statec0 = reader.value<std::uint32_t>(component + 0xC0);
    const auto flagc7 = reader.value<std::uint8_t>(component + 0xC7);
    const auto flagc9 = reader.value<std::uint8_t>(component + 0xC9);
    const auto flagca = reader.value<std::uint8_t>(component + 0xCA);
    // These widths and sources are established by the bounded static report
    // cinematic_native_next.md; no resource/context pointer is followed.
    const auto asset_a0 = reader.value<std::uint64_t>(component + 0xA0);
    const auto reference_a8 = reader.value<std::uint64_t>(component + 0xA8);
    const auto elapsed_ec = reader.value<std::uint32_t>(component + 0xEC);
    const auto elapsed_f0 = reader.value<std::uint32_t>(component + 0xF0);
    const auto flags408 = reader.value<std::uint32_t>(component + 0x408);
    const auto flags438 = reader.value<std::uint32_t>(component + 0x438);
    const auto vt_after = reader.value<std::uintptr_t>(component);
    const auto owner_after = reader.value<std::uintptr_t>(component + 8);
    const auto handle_after = reader.value<std::uint32_t>(component + 0x14);
    const auto after = reader.value<std::uintptr_t>(address(kComponentSlot));
    if (!cinematic_identity(reader) || vt_after != vt || after != component || owner != owner_after || handle != handle_after ||
        asset_a0 != reader.value<std::uint64_t>(component + 0xA0)) return "{\"status\":\"selection_or_identity_changed_during_reads\"}";
    std::ostringstream out;
    out << "{\"status\":\"component_identity_match_raw_only\",\"component\":" << hex(component)
        << ",\"raw_58\":" << state58 << ",\"raw_5c\":" << state5c << ",\"raw_c0\":" << statec0
        << ",\"raw_c7\":" << static_cast<unsigned>(flagc7) << ",\"raw_c9\":" << static_cast<unsigned>(flagc9)
        << ",\"raw_ca\":" << static_cast<unsigned>(flagca)
        << ",\"owner_raw\":" << hex(owner) << ",\"component_handle_local\":" << handle
        << ",\"asset_id_a0_raw_candidate\":" << hex(asset_a0) << ",\"reference_a8_raw\":" << hex(reference_a8)
        << ",\"ec_float_bits_raw\":" << hex(elapsed_ec) << ",\"f0_float_bits_raw\":" << hex(elapsed_f0)
        << ",\"flags408_raw\":" << flags408 << ",\"flags438_raw\":" << flags438
        << ",\"cross_peer_asset_id_verified\":false,\"fields_sampled_atomically\":false}";
    return out.str();
}

std::string overlay() {
    Reader reader;
    const auto object = address(kOverlay, 0x230);
    const auto main_vt = reader.value<std::uintptr_t>(object);
    const auto second_vt = reader.value<std::uintptr_t>(object + 0x158);
    if (main_vt != base + kOverlayVt || second_vt != base + kOverlaySecondVt) return "{\"status\":\"dual_identity_not_ready_or_mismatch\"}";
    std::array<std::uintptr_t, 2> pair{}, after{};
    reader.bytes(object + 0x220, pair.data(), sizeof(pair));
    const auto flag = reader.value<std::uint8_t>(object + 0x210);
    const auto elapsed = reader.value<float>(object + 0x214);
    reader.bytes(object + 0x220, after.data(), sizeof(after));
    if (reader.value<std::uintptr_t>(object) != main_vt || reader.value<std::uintptr_t>(object + 0x158) != second_vt || pair != after) return "{\"status\":\"dual_identity_or_slots_changed_during_reads\"}";
    std::ostringstream out;
    out << "{\"status\":\"dual_identity_match_slots_stable_raw_only\",\"flag_raw\":" << static_cast<unsigned>(flag)
        << ",\"elapsed_raw\":";
    if (std::isfinite(elapsed)) out << std::setprecision(9) << elapsed;
    else out << "null";
    out << ",\"callback_raw\":" << hex(pair[0]) << ",\"context_raw\":" << hex(pair[1]) << ",\"callback_main_rva\":";
    if (pair[0] >= base && pair[0] - base < image_size) out << hex(pair[0] - base);
    else out << "null";
    out << '}';
    return out.str();
}

std::string tasks() {
    Reader reader;
    const auto manager = address(kTasks, 0x688B8);
    const auto manager_pointer = reader.value<std::uintptr_t>(address(kTaskPointer));
    if (manager_pointer && manager_pointer != manager) return "{\"status\":\"manager_pointer_mismatch\"}";
    const auto storage = reader.value<std::uintptr_t>(manager + 0x688B0);
    const auto entries = reader.value<std::uintptr_t>(manager + 0x28);
    const auto entry_count = reader.value<std::int32_t>(manager + 0x30);
    if (!storage || !entries) return "{\"status\":\"manager_not_initialized\"}";
    const auto count = reader.value<std::int32_t>(storage + 0x30320);
    const auto states = reader.value<std::uintptr_t>(storage);
    if (entry_count < 0 || entry_count > 200000 || count < 0 || count > 64) throw std::runtime_error("task_counts_outside_audited_bounds");
    if (!states) return "{\"status\":\"state_array_not_initialized\"}";
    std::vector<std::int32_t> indices(static_cast<std::size_t>(count));
    if (count) reader.bytes(storage + 0x120, indices.data(), indices.size() * sizeof(indices[0]));
    std::vector<std::int32_t> all_values;
    std::ostringstream out;
    out << "{\"status\":\"task_subset_raw_only\",\"missions\":[";
    for (std::size_t position = 0; position < indices.size(); ++position) {
        const auto index = indices[position];
        if (index < 0 || index >= entry_count) throw std::runtime_error("task_index_outside_audited_bounds");
        const auto mission = reader.value<std::uintptr_t>(entries + static_cast<std::size_t>(index) * 0x30);
        if (!mission) throw std::runtime_error("listed_task_pointer_missing");
        const auto state = reader.value<std::int32_t>(states + static_cast<std::size_t>(index) * 4);
        all_values.push_back(state);
        const auto id = reader.value<std::uint32_t>(mission + 0x14);
        const auto name = reader.symbol(mission + 8);
        const auto goals = reader.value<std::uint32_t>(mission + 0x80);
        const auto definitions = reader.value<std::uintptr_t>(mission + 0x78);
        if (goals > 64 || (goals && !definitions)) throw std::runtime_error("objective_definitions_outside_audited_bounds");
        if (position) out << ',';
        out << "{\"id_raw\":" << hex(id) << ",\"name_raw\":" << quote(name) << ",\"state_raw\":" << state << ",\"objectives\":[";
        for (std::uint32_t goal = 0; goal < goals; ++goal) {
            const auto definition = reader.value<std::uintptr_t>(definitions + static_cast<std::size_t>(goal) * 0x18 + 8);
            const auto goal_state = reader.value<std::int32_t>(storage + 0x220 + position * 0x100 + static_cast<std::size_t>(goal) * 4);
            all_values.push_back(goal_state);
            const auto goal_name = reader.symbol(definition + 8);
            if (goal) out << ',';
            out << "{\"name_raw\":" << quote(goal_name) << ",\"state_raw\":" << goal_state << '}';
        }
        if (goals != reader.value<std::uint32_t>(mission + 0x80) || definitions != reader.value<std::uintptr_t>(mission + 0x78) ||
            mission != reader.value<std::uintptr_t>(entries + static_cast<std::size_t>(index) * 0x30)) throw std::runtime_error("objective_identity_changed_during_reads");
        out << "]}";
    }
    if (storage != reader.value<std::uintptr_t>(manager + 0x688B0) || entries != reader.value<std::uintptr_t>(manager + 0x28) ||
        entry_count != reader.value<std::int32_t>(manager + 0x30) || count != reader.value<std::int32_t>(storage + 0x30320) ||
        states != reader.value<std::uintptr_t>(storage)) throw std::runtime_error("task_storage_changed_during_reads");
    std::vector<std::int32_t> after(indices.size());
    if (count) reader.bytes(storage + 0x120, after.data(), after.size() * sizeof(after[0]));
    if (after != indices) throw std::runtime_error("listed_task_indices_changed_during_reads");
    // Recheck raw states before accepting the subset. This is still sampled
    // evidence, not an atomic engine snapshot or a scene/collision-ready signal.
    std::size_t cursor = 0;
    for (std::size_t position = 0; position < indices.size(); ++position) {
        const auto index = indices[position];
        if (all_values[cursor++] != reader.value<std::int32_t>(states + static_cast<std::size_t>(index) * 4)) throw std::runtime_error("task_state_changed_during_reads");
        const auto mission = reader.value<std::uintptr_t>(entries + static_cast<std::size_t>(index) * 0x30);
        const auto goals = reader.value<std::uint32_t>(mission + 0x80);
        if (goals > 64 || cursor + goals > all_values.size()) throw std::runtime_error("objective_count_changed_during_reads");
        for (std::uint32_t goal = 0; goal < goals; ++goal) {
            if (all_values[cursor++] != reader.value<std::int32_t>(storage + 0x220 + position * 0x100 + static_cast<std::size_t>(goal) * 4)) throw std::runtime_error("objective_state_changed_during_reads");
        }
    }
    if (cursor != all_values.size()) throw std::runtime_error("objective_count_changed_during_reads");
    out << "],\"read_count\":" << reader.reads() << ",\"read_bytes\":" << reader.total() << '}';
    return out.str();
}

template<class Function> std::string capture_part(Function function) {
    try { return function(); }
    catch (const std::exception& error) { return "{\"status\":\"observation_gap\",\"reason\":" + quote(error.what()) + '}'; }
}
} // namespace

bool SamplerInitialize(std::string& session_json) {
    initialized = false;
    try {
        std::array<wchar_t, 32768> path{};
        const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
        if (!length || length >= path.size()) throw std::runtime_error("host_path_unavailable");
        if (_wcsicmp(std::filesystem::path(path.data()).filename().c_str(), kGameFilename) != 0) throw std::runtime_error("host_filename_not_pinned_game_no_fixed_address_reads");
        if (file_hash(path.data()) != kGameHash) throw std::runtime_error("game_build_hash_mismatch_no_fixed_address_reads");
        base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        Reader reader;
        const auto dos = reader.value<IMAGE_DOS_HEADER>(base);
        if (dos.e_magic != IMAGE_DOS_SIGNATURE || dos.e_lfanew <= 0 || dos.e_lfanew > 0x100000) throw std::runtime_error("invalid_host_pe_header");
        // The entire IMAGE_NT_HEADERS64 exceeds the bounded single-read size.
        const auto nt = base + static_cast<std::uintptr_t>(dos.e_lfanew);
        if (reader.value<DWORD>(nt) != IMAGE_NT_SIGNATURE || reader.value<WORD>(nt + 4) != IMAGE_FILE_MACHINE_AMD64 ||
            reader.value<WORD>(nt + 24) != IMAGE_NT_OPTIONAL_HDR64_MAGIC) throw std::runtime_error("host_is_not_verified_amd64_pe");
        image_size = reader.value<std::uint32_t>(nt + 24 + offsetof(IMAGE_OPTIONAL_HEADER64, SizeOfImage));
        address(kOverlay, 0x230);
        address(kTasks, 0x688B8);
        address(kTaskPointer);
        initialized = true;
        std::ostringstream out;
        out << "{\"schema\":1,\"record_type\":\"runtime_session\",\"status\":\"pinned_game_verified\",\"pid\":" << GetCurrentProcessId()
            << ",\"module_base\":" << hex(base) << ",\"module_size\":" << image_size << ",\"game_sha256\":\"" << kGameHash
            << "\",\"mode\":\"in_process_read_only_diagnostic\",\"game_operations\":false,\"hooks_installed\":false,\"world_replication_enabled\":false,\"verified_callable_interfaces\":[]}";
        session_json = out.str();
        return true;
    } catch (const std::exception& error) {
        session_json = "{\"schema\":1,\"record_type\":\"runtime_session\",\"status\":\"disabled\",\"reason\":" + quote(error.what()) +
            ",\"game_operations\":false,\"hooks_installed\":false,\"world_replication_enabled\":false,\"verified_callable_interfaces\":[]}";
        base = image_size = 0;
        return false;
    }
}

bool SamplerCapture(std::uint64_t sequence, std::string& sample_json) {
    if (!initialized) {
        sample_json = "{\"record_type\":\"runtime_snapshot\",\"status\":\"sampler_not_initialized\"}";
        return false;
    }
    std::ostringstream out;
    out << "{\"schema\":1,\"record_type\":\"runtime_snapshot\",\"sequence\":" << sequence
        << ",\"pid\":" << GetCurrentProcessId() << ",\"monotonic_ms\":" << GetTickCount64()
        << ",\"cinematic_raw\":" << capture_part(cinematic) << ",\"ui_skip_raw\":" << capture_part(overlay)
        << ",\"task_subset_raw\":" << capture_part(tasks)
        << ",\"world_components_raw\":" << capture_part([sequence] { return CaptureWorldRaw(base, image_size, sequence); })
        << ",\"game_operations\":false,\"scene_ready_verified\":false,\"cinematic_phase_verified\":false,\"skip_verified\":false,\"door_sync_verified\":false,\"enemy_sync_verified\":false,\"verified_callable_interfaces\":[]}";
    sample_json = out.str();
    return true;
}

void SamplerShutdown() noexcept {
    initialized = false;
    base = image_size = 0;
}
} // namespace coopsync::runtime
