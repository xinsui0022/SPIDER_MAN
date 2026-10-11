#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <map>
#include <stdexcept>
#include <vector>

namespace mock {
std::map<std::uintptr_t, std::vector<unsigned char>> regions;
std::function<void(std::uintptr_t, std::size_t)> before_read;
std::uintptr_t short_address = 0;
std::size_t calls = 0, bytes = 0;

void allocate(std::uintptr_t address, std::size_t size) { regions[address] = std::vector<unsigned char>(size); }
unsigned char* locate(std::uintptr_t address, std::size_t size) {
    auto next = regions.upper_bound(address);
    if (next == regions.begin()) return nullptr;
    --next;
    const auto offset = address - next->first;
    if (offset > next->second.size() || size > next->second.size() - offset) return nullptr;
    return next->second.data() + offset;
}
template<class T> void write(std::uintptr_t address, T value) {
    auto* target = locate(address, sizeof(value));
    if (!target) throw std::runtime_error("mock_write_out_of_region");
    std::memcpy(target, &value, sizeof(value));
}
BOOL WINAPI rpm(HANDLE, LPCVOID address, LPVOID output, SIZE_T count, SIZE_T* copied) {
    const auto pointer = reinterpret_cast<std::uintptr_t>(address);
    ++calls;
    bytes += count;
    if (before_read) before_read(pointer, count);
    const auto* source = locate(pointer, count);
    if (!source) { *copied = 0; return FALSE; }
    if (pointer == short_address) {
        *copied = count / 2;
        std::memcpy(output, source, *copied);
        return TRUE;
    }
    *copied = count;
    std::memcpy(output, source, count);
    return TRUE;
}
} // namespace mock

// Compile the exact production implementation against deterministic memory.
// This is a separate test executable; its fake API is never linked into DLLs.
#define ReadProcessMemory mock::rpm
#include "../src/runtime/runtime_world.cpp"
#undef ReadProcessMemory

namespace {
constexpr std::uintptr_t base = 0x140000000, table = 0x200000000;
constexpr std::uintptr_t map_base = 0x210000000, component = 0x220000000;
constexpr std::uint32_t image_size = 0x8600000;
unsigned checks = 0;

void require(bool condition, const char* description) {
    ++checks;
    if (!condition) throw std::runtime_error(description);
}
bool has(const std::string& text, const char* fragment) { return text.find(fragment) != std::string::npos; }

void setup(std::uint32_t count = 1, bool door = false) {
    mock::regions.clear();
    mock::before_read = {};
    mock::short_address = 0;
    mock::calls = mock::bytes = 0;
    mock::allocate(base + 0x7A44380, 0x20);
    mock::write(base + 0x7A44380, table);
    mock::write(base + 0x7A4439C, count);
    mock::allocate(table, static_cast<std::size_t>(count) * 0xC0);
    for (std::uint32_t i = 0; i < count; ++i) {
        mock::write(table + static_cast<std::size_t>(i) * 0xC0 + 0xC, i);
        mock::write<std::uint16_t>(table + static_cast<std::size_t>(i) * 0xC0 + 0x10, 3);
    }
    mock::allocate(map_base, 16);
    mock::write(map_base, base + (door ? 0x7C32140 : 0x7C2C290));
    mock::write(map_base + 8, component);
    mock::write(table + 0x68, map_base);
    mock::write<std::uint16_t>(table + 0x70, 1);
    mock::allocate(component, 0xD0);
    mock::write(component, base + (door ? 0x4F67720 : 0x3839E08));
    mock::write(component + 8, table);
    mock::write<std::uint32_t>(component + 0x14, 0x500001);
    if (door) mock::write<std::uint8_t>(component + 0x48, 2);
    else {
        mock::write<float>(component + 0x80, 100.0f);
        mock::write<float>(component + 0x88, 81.0f);
    }
}

std::string capture(std::uint64_t sequence = 1) {
    return coopsync::runtime::CaptureWorldRaw(base, image_size, sequence);
}

void stable_samples() {
    setup();
    auto result = capture();
    require(has(result, "\"records_accepted\":1"), "stable Health rejected");
    require(has(result, "\"type\":\"Health\""), "Health vtable not classified");
    require(has(result, "\"offset\":\"0x80\",\"size\":16"), "audited health range missing");
    require(has(result, "\"full_world_coverage\":false"), "world falsely complete");
    require(has(result, "\"network_entity_id\":null"), "local handle promoted to peer ID");
    require(has(result, "\"game_operations\":false"), "diagnostic operations misreported");
    setup(1, true);
    result = capture();
    require(has(result, "\"records_accepted\":1"), "stable Door rejected");
    require(has(result, "\"offset\":\"0x48\",\"size\":12"), "audited Door tuple missing");
    require(has(result, "\"door_open_verified\":false"), "raw door value interpreted");
}

void races() {
    setup();
    unsigned field_reads = 0;
    mock::before_read = [&](std::uintptr_t pointer, std::size_t size) {
        if (pointer == component + 0x80 && size == 16 && ++field_reads == 2)
            mock::write<float>(component + 0x88, 80.0f);
    };
    auto result = capture();
    require(has(result, "raw_fields_changed_during_reads"), "field race missed");
    require(has(result, "\"records_accepted\":0"), "field race accepted");

    setup();
    unsigned owner_reads = 0;
    mock::before_read = [&](std::uintptr_t pointer, std::size_t) {
        if (pointer == component + 8 && ++owner_reads == 2)
            mock::write(component + 8, table + 0xC0);
    };
    result = capture();
    require(has(result, "component_identity_or_map_value_changed"), "owner race missed");
    require(has(result, "\"records_accepted\":0"), "owner race accepted");

    setup();
    unsigned slot_reads = 0;
    mock::before_read = [&](std::uintptr_t pointer, std::size_t size) {
        if (pointer == map_base && size == 16 && ++slot_reads == 2)
            mock::write(map_base + 8, component + 0x1000);
    };
    result = capture();
    require(has(result, "component_identity_or_map_value_changed"), "map race missed");
    require(has(result, "\"records_accepted\":0"), "map race accepted");

    setup();
    unsigned generation_reads = 0;
    mock::before_read = [&](std::uintptr_t pointer, std::size_t) {
        if (pointer == table + 0x10 && ++generation_reads == 2)
            mock::write<std::uint16_t>(table + 0x10, 4);
    };
    result = capture();
    require(has(result, "entity_identity_or_map_header_changed"), "generation race missed");
    require(has(result, "\"records_accepted\":0"), "generation race accepted");

    setup();
    unsigned count_reads = 0;
    mock::before_read = [&](std::uintptr_t pointer, std::size_t) {
        if (pointer == base + 0x7A4439C && ++count_reads == 2)
            mock::write<std::uint32_t>(base + 0x7A4439C, 2);
    };
    result = capture();
    require(has(result, "global_entity_table_changed_during_reads"), "global race missed");
    require(has(result, "\"records_accepted\":0"), "global race accepted");
}

void fail_closed_and_windows() {
    setup();
    mock::short_address = component + 0x80;
    auto result = capture();
    require(has(result, "read_failed_or_short"), "short RPM missed");
    require(has(result, "\"records_accepted\":0"), "short RPM accepted");
    setup();
    mock::write(map_base, base + 0x7C32250);
    result = capture();
    require(has(result, "type_descriptor_key_mismatch"), "wrong descriptor accepted");
    require(has(result, "\"records_accepted\":0"), "wrong descriptor raw field read");
    setup();
    mock::write<std::uint16_t>(table + 0x70, 129);
    result = capture();
    require(has(result, "component_map_exceeds_diagnostic_cap"), "map cap ignored");
    setup(256);
    result = capture();
    require(has(result, "\"window_start_index\":0,\"window_next_index\":128"), "first window wrong");
    result = capture(2);
    require(has(result, "\"window_start_index\":128,\"window_next_index\":0"), "rolling cursor wrong");
    require(has(result, "\"entities_attempted\":128"), "entity window cap ignored");
    setup();
    result = coopsync::runtime::CaptureWorldRaw(base, 0x1000, 1);
    require(has(result, "pinned_rva_outside_image"), "bad image bounds accepted");
    require(mock::calls == 0, "bad image touched memory");
}

void budget() {
    setup(128);
    mock::allocate(map_base, 128 * 16);
    mock::write<std::uintptr_t>(component, base + 0x111111);
    for (unsigned slot = 0; slot < 128; ++slot) {
        mock::write(map_base + static_cast<std::uintptr_t>(slot) * 16, base + 0x111111);
        mock::write(map_base + static_cast<std::uintptr_t>(slot) * 16 + 8, component);
    }
    for (unsigned i = 0; i < 128; ++i) {
        mock::write(table + static_cast<std::uintptr_t>(i) * 0xC0 + 0x68, map_base);
        mock::write<std::uint16_t>(table + static_cast<std::uintptr_t>(i) * 0xC0 + 0x70, 128);
    }
    const auto result = capture();
    require(has(result, "partial_raw_window_read_budget_exhausted"), "budget exhaustion not identified");
    require(has(result, "\"global_table_stable\":true"), "reserved final reads not performed");
    require(mock::calls <= 16384, "RPM call budget exceeded");
    require(mock::bytes <= 1024 * 1024, "RPM byte budget exceeded");
}

void record_and_output_caps() {
    setup(33, true);
    for (unsigned i = 1; i < 33; ++i) {
        const auto entry = table + static_cast<std::uintptr_t>(i) * 0xC0;
        const auto pair = map_base + static_cast<std::uintptr_t>(i) * 0x1000;
        const auto instance = component + static_cast<std::uintptr_t>(i) * 0x1000;
        mock::allocate(pair, 16);
        mock::write(pair, base + 0x7C32140);
        mock::write(pair + 8, instance);
        mock::write(entry + 0x68, pair);
        mock::write<std::uint16_t>(entry + 0x70, 1);
        mock::allocate(instance, 0xD0);
        mock::write(instance, base + 0x4F67720);
        mock::write(instance + 8, entry);
        mock::write<std::uint32_t>(instance + 0x14, 0x500001 + i);
    }
    const auto result = capture();
    require(has(result, "\"records_accepted\":32"), "record cap wrong");
    require(has(result, "partial_raw_window_record_limit"), "record cap status missing");
    require(has(result, "raw_record_limit_reached"), "record cap gap missing");
    require(result.size() < 48 * 1024, "world output exceeds lifecycle allocation");
}
} // namespace

int main() {
    try {
        stable_samples();
        races();
        fail_closed_and_windows();
        budget();
        record_and_output_caps();
        std::cout << "World raw diagnostic: " << checks << " deterministic checks passed; no game process used.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
