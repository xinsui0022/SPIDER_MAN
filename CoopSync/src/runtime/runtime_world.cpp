#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include "runtime_world.h"

#include <array>
#include <cstring>
#include <iomanip>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace coopsync::runtime {
namespace {
constexpr std::uintptr_t kEntityTable = 0x7A44380, kEntityCount = 0x7A4439C;
constexpr std::uint32_t kEntityStride = 0xC0, kWindow = 128, kMapSlots = 128;
constexpr std::uint32_t kMaxEntities = 0x100000, kMaxReads = 16384;
constexpr std::size_t kMaxBytes = 1024 * 1024, kMaxRecords = 32, kGapDetails = 16;
constexpr std::uintptr_t kHighestAddress = 0x0000800000000000ull;

struct Type {
    const char* name;
    std::uintptr_t vtable;
    std::uintptr_t descriptor;
    bool door;
};
// Each class has an RTTI TypeDescriptor -> COL -> vtable proof and a
// constructor write. Virtual +0x48 returns the separate engine descriptor
// used as the ECS map key; the two descriptor types must not be conflated.
constexpr std::array<Type, 5> kTypes{{
    {"Door", 0x4F67720, 0x7C32140, true},
    {"DoorAnimated", 0x4F677C8, 0x7C32250, true},
    {"DoorSlide", 0x4F67BB8, 0x7C32650, true},
    {"Health", 0x3839E08, 0x7C2C290, false},
    {"BotHealth", 0x3839E98, 0x6C87910, false},
}};

struct Cursor {
    std::uintptr_t base = 0, table = 0;
    std::uint32_t next = 0;
    std::uint64_t last_sequence = 0;
};
Cursor cursor;
std::mutex cursor_mutex;

std::string hex(std::uint64_t value) {
    std::ostringstream out;
    out << '"' << "0x" << std::hex << value << '"';
    return out.str();
}

std::string raw_hex(const unsigned char* data, std::size_t size) {
    std::ostringstream out;
    out << '"' << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < size; ++i) out << std::setw(2) << static_cast<unsigned>(data[i]);
    out << '"';
    return out.str();
}

class Reader {
public:
    void bytes(std::uintptr_t address, void* output, std::size_t count,
               bool final_global_check = false) {
        if (address < 0x10000 || address >= kHighestAddress || !count ||
            count > 4096 || count > kHighestAddress - address) {
            throw std::runtime_error("read_address_bounds_refused");
        }
        // Reserve two reads/twelve bytes so the global table can still be
        // rechecked after an ordinary read budget is exhausted.
        const auto read_limit = final_global_check ? kMaxReads : kMaxReads - 2;
        const auto byte_limit = final_global_check ? kMaxBytes : kMaxBytes - 12;
        if (reads >= read_limit || count > byte_limit - total) {
            exhausted = true;
            throw std::runtime_error("diagnostic_read_budget_exhausted");
        }
        ++reads;
        total += count;
        SIZE_T copied = 0;
        if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(address),
                               output, count, &copied) || copied != count) {
            throw std::runtime_error("read_failed_or_short");
        }
    }
    template<class T> T value(std::uintptr_t address, bool final_check = false) {
        T output{};
        bytes(address, &output, sizeof(output), final_check);
        return output;
    }
    std::uint32_t reads = 0;
    std::size_t total = 0;
    bool exhausted = false;
};

std::uintptr_t add(std::uintptr_t value, std::size_t offset) {
    if (value < 0x10000 || value >= kHighestAddress || offset >= kHighestAddress - value) {
        throw std::runtime_error("pointer_arithmetic_bounds_refused");
    }
    return value + offset;
}

std::uintptr_t rva(std::uintptr_t base, std::uint32_t image_size,
                   std::uintptr_t offset, std::size_t count) {
    if (!base || offset >= image_size || count > image_size - offset) {
        throw std::runtime_error("pinned_rva_outside_image");
    }
    return add(base, static_cast<std::size_t>(offset));
}

struct EntityHeader {
    std::uint32_t index = 0;
    std::uint16_t generation = 0, compact_count = 0, hash_capacity = 0;
    std::uintptr_t compact = 0, hashed = 0;
    bool operator==(const EntityHeader& other) const noexcept {
        return index == other.index && generation == other.generation &&
            compact_count == other.compact_count && hash_capacity == other.hash_capacity &&
            compact == other.compact && hashed == other.hashed;
    }
};

EntityHeader entity_header(Reader& reader, std::uintptr_t entry) {
    EntityHeader out;
    out.index = reader.value<std::uint32_t>(add(entry, 0xC));
    out.generation = reader.value<std::uint16_t>(add(entry, 0x10));
    out.compact = reader.value<std::uintptr_t>(add(entry, 0x68));
    out.compact_count = reader.value<std::uint16_t>(add(entry, 0x70));
    out.hashed = reader.value<std::uintptr_t>(add(entry, 0x80));
    out.hash_capacity = reader.value<std::uint16_t>(add(entry, 0x88));
    return out;
}

struct Identity {
    std::uintptr_t vt = 0, owner = 0;
    std::uint32_t handle = 0;
    bool operator==(const Identity& other) const noexcept {
        return vt == other.vt && owner == other.owner && handle == other.handle;
    }
};

Identity component_identity(Reader& reader, std::uintptr_t component) {
    Identity out;
    out.vt = reader.value<std::uintptr_t>(component);
    out.owner = reader.value<std::uintptr_t>(add(component, 8));
    out.handle = reader.value<std::uint32_t>(add(component, 0x14));
    return out;
}

struct Field {
    std::uint32_t offset = 0;
    std::uint32_t size = 0;
    std::array<unsigned char, 16> raw{};
};

std::vector<Field> fields(Reader& reader, std::uintptr_t component, const Type& type) {
    // Only registered/native-code-supported fields. No unknown pointer is
    // followed and no serialized engine data object is copied wholesale.
    const std::array<std::pair<std::uint32_t, std::uint32_t>, 7> doors{{
        {0x48, 12}, {0xBC, 1}, {0xBF, 1}, {0xC1, 1},
        {0xC2, 1}, {0xC3, 1}, {0xC4, 4},
    }};
    const std::array<std::pair<std::uint32_t, std::uint32_t>, 2> health{{
        {0x80, 16}, {0xAC, 2},
    }};
    std::vector<Field> result;
    auto read_one = [&](const auto& definition) {
        Field field;
        field.offset = definition.first;
        field.size = definition.second;
        reader.bytes(add(component, field.offset), field.raw.data(), field.size);
        result.push_back(field);
    };
    if (type.door) for (const auto& definition : doors) read_one(definition);
    else for (const auto& definition : health) read_one(definition);
    return result;
}

bool fields_equal(const std::vector<Field>& before, const std::vector<Field>& after) noexcept {
    if (before.size() != after.size()) return false;
    for (std::size_t i = 0; i < before.size(); ++i) {
        if (before[i].offset != after[i].offset || before[i].size != after[i].size ||
            std::memcmp(before[i].raw.data(), after[i].raw.data(), before[i].size) != 0) return false;
    }
    return true;
}

struct Gaps {
    std::size_t count = 0;
    std::vector<std::string> details;
    void add(const char* reason, std::uint32_t index,
             std::uintptr_t component = 0) {
        ++count;
        if (details.size() >= kGapDetails) return;
        std::ostringstream out;
        out << "{\"reason\":\"" << reason << "\",\"entity_index\":" << index
            << ",\"component_raw\":" << hex(component) << '}';
        details.push_back(out.str());
    }
};

const Type* type_for(std::uintptr_t base, std::uint32_t image_size,
                     std::uintptr_t vt) {
    for (const auto& type : kTypes) {
        if (vt == rva(base, image_size, type.vtable, 8)) return &type;
    }
    return nullptr;
}

std::string record(std::uint32_t index, const EntityHeader& entity,
                   std::uintptr_t component, const Identity& identity,
                   const Type& type, const std::vector<Field>& raw) {
    const auto handle = (static_cast<std::uint32_t>(entity.generation) << 20) | index;
    std::ostringstream out;
    out << "{\"type\":\"" << type.name << "\",\"entity_index\":" << index
        << ",\"entity_generation_raw\":" << entity.generation
        << ",\"entity_handle_local\":" << handle
        << ",\"component_raw\":" << hex(component)
        << ",\"owner_raw\":" << hex(identity.owner)
        << ",\"vtable_raw\":" << hex(identity.vt)
        << ",\"component_handle_local\":" << identity.handle
        << ",\"network_entity_id\":null,\"fields\":[";
    for (std::size_t i = 0; i < raw.size(); ++i) {
        if (i) out << ',';
        out << "{\"offset\":" << hex(raw[i].offset)
            << ",\"size\":" << raw[i].size << ",\"raw_hex\":"
            << raw_hex(raw[i].raw.data(), raw[i].size) << '}';
    }
    out << "]}";
    return out.str();
}

std::string capture(std::uintptr_t base, std::uint32_t image_size,
                    std::uint64_t sequence) {
    Reader reader;
    Gaps gaps;
    std::vector<std::string> records;
    std::uintptr_t table = 0;
    std::uint32_t count = 0, start = 0, next = 0, attempted = 0, completed = 0;
    std::uint32_t live_headers = 0, slots_checked = 0, non_whitelisted = 0;
    bool reset = false, wrapped = false, global_stable = false;
    bool record_limit = false;
    const char* status = "stable_raw_window_only";
    try {
        table = reader.value<std::uintptr_t>(rva(base, image_size, kEntityTable, 8));
        count = reader.value<std::uint32_t>(rva(base, image_size, kEntityCount, 4));
        if (count > kMaxEntities) throw std::runtime_error("entity_table_count_bounds_refused");
        reset = cursor.base != base || cursor.table != table || sequence <= cursor.last_sequence;
        if (reset) cursor.next = 0;
        cursor.base = base;
        cursor.table = table;
        cursor.last_sequence = sequence;
        if (!table || !count) {
            status = "entity_table_not_ready_or_empty_raw_only";
            cursor.next = 0;
        } else {
            start = cursor.next % count;
            next = start;
            const auto amount = count < kWindow ? count : kWindow;
            for (std::uint32_t n = 0; n < amount; ++n) {
                const auto index = next;
                next = index + 1;
                if (next >= count) { next = 0; wrapped = true; }
                cursor.next = next;
                ++attempted;
                try {
                    const auto entry = add(table, static_cast<std::size_t>(index) * kEntityStride);
                    const auto header = entity_header(reader, entry);
                    if (!header.generation) { ++completed; continue; }
                    ++live_headers;
                    if (header.generation > 0x7FF || (header.index & 0xFFFFF) != index) {
                        gaps.add("entity_index_or_generation_mismatch", index);
                        continue;
                    }
                    if (header.compact_count > kMapSlots || header.hash_capacity > kMapSlots) {
                        gaps.add("component_map_exceeds_diagnostic_cap", index);
                        continue;
                    }
                    if (header.compact_count && !header.compact) {
                        gaps.add("component_map_unavailable", index);
                        continue;
                    }
                    // The compact map is the source used to construct the
                    // hashed lookup and to enumerate/remove components. Avoid
                    // probing its inherited aliases from the hashed table.
                    std::vector<std::string> entity_records;
                    std::vector<std::uintptr_t> seen;
                    for (std::uint32_t slot = 0; slot < header.compact_count; ++slot) {
                        const auto slot_address = add(header.compact, static_cast<std::size_t>(slot) * 16);
                        std::array<std::uintptr_t, 2> pair{};
                        reader.bytes(slot_address, pair.data(), sizeof(pair));
                        ++slots_checked;
                        if (!pair[0] || !pair[1]) continue;
                        const auto vt = reader.value<std::uintptr_t>(pair[1]);
                        const auto* type = type_for(base, image_size, vt);
                        if (!type) { ++non_whitelisted; continue; }
                        if (pair[0] != rva(base, image_size, type->descriptor, 1)) {
                            gaps.add("type_descriptor_key_mismatch", index, pair[1]);
                            continue;
                        }
                        bool duplicate = false;
                        for (auto pointer : seen) if (pointer == pair[1]) duplicate = true;
                        if (duplicate) continue;
                        seen.push_back(pair[1]);
                        if (records.size() + entity_records.size() >= kMaxRecords) {
                            record_limit = true;
                            gaps.add("raw_record_limit_reached", index, pair[1]);
                            break;
                        }
                        const auto before = component_identity(reader, pair[1]);
                        if (before.vt != vt || before.owner != entry || !before.handle) {
                            gaps.add("component_owner_or_handle_mismatch", index, pair[1]);
                            continue;
                        }
                        const auto raw = fields(reader, pair[1], *type);
                        const auto raw_after = fields(reader, pair[1], *type);
                        const auto after = component_identity(reader, pair[1]);
                        std::array<std::uintptr_t, 2> pair_after{};
                        reader.bytes(slot_address, pair_after.data(), sizeof(pair_after));
                        if (!(before == after) || pair != pair_after) {
                            gaps.add("component_identity_or_map_value_changed", index, pair[1]);
                            continue;
                        }
                        if (!fields_equal(raw, raw_after)) {
                            gaps.add("raw_fields_changed_during_reads", index, pair[1]);
                            continue;
                        }
                        entity_records.push_back(record(index, header, pair[1], before, *type, raw));
                    }
                    if (!(header == entity_header(reader, entry))) {
                        gaps.add("entity_identity_or_map_header_changed", index);
                        continue;
                    }
                    records.insert(records.end(), entity_records.begin(), entity_records.end());
                    ++completed;
                    if (record_limit) break;
                } catch (const std::runtime_error& error) {
                    gaps.add(error.what(), index);
                    if (reader.exhausted) break;
                }
            }
        }
        const auto table_after = reader.value<std::uintptr_t>(rva(base, image_size, kEntityTable, 8), true);
        const auto count_after = reader.value<std::uint32_t>(rva(base, image_size, kEntityCount, 4), true);
        global_stable = table == table_after && count == count_after;
        if (!global_stable) {
            status = "global_entity_table_changed_during_reads";
            gaps.add("global_entity_table_changed_during_reads", start);
            records.clear();
            cursor.next = 0;
        } else if (reader.exhausted) status = "partial_raw_window_read_budget_exhausted";
        else if (record_limit) status = "partial_raw_window_record_limit";
        else if (gaps.count) status = "partial_raw_window_with_gaps";
    } catch (const std::runtime_error& error) {
        status = "world_observation_unavailable";
        gaps.add(error.what(), start);
        records.clear();
    }
    std::ostringstream out;
    out << "{\"status\":\"" << status << "\",\"sequence\":" << sequence
        << ",\"game_operations\":false,\"full_world_coverage\":false"
        << ",\"door_open_verified\":false,\"collision_ready_verified\":false"
        << ",\"enemy_health_or_death_verified\":false,\"world_replication_verified\":false"
        << ",\"coverage\":\"incomplete_rolling_diagnostic_window\""
        << ",\"identity_scope\":\"local_process_handle_only\""
        << ",\"table_raw\":" << hex(table) << ",\"table_count_raw\":" << count
        << ",\"global_table_stable\":" << (global_stable ? "true" : "false")
        << ",\"window_start_index\":" << start << ",\"window_next_index\":" << next
        << ",\"window_wrapped\":" << (wrapped ? "true" : "false")
        << ",\"rolling_cursor_reset\":" << (reset ? "true" : "false")
        << ",\"entities_attempted\":" << attempted << ",\"entities_completed\":" << completed
        << ",\"live_headers_raw\":" << live_headers << ",\"component_slots_checked\":" << slots_checked
        << ",\"non_whitelisted_slots\":" << non_whitelisted << ",\"records_accepted\":" << records.size()
        << ",\"budget\":{\"read_calls\":" << reader.reads << ",\"read_bytes\":" << reader.total
        << ",\"max_read_calls\":" << kMaxReads << ",\"max_read_bytes\":" << kMaxBytes
        << ",\"max_entities_per_tick\":" << kWindow << ",\"max_map_slots_per_entity\":" << kMapSlots
        << ",\"max_records_per_tick\":" << kMaxRecords << ",\"exhausted\":"
        << (reader.exhausted ? "true" : "false") << "},\"gap_count\":" << gaps.count << ",\"gaps\":[";
    for (std::size_t i = 0; i < gaps.details.size(); ++i) {
        if (i) out << ',';
        out << gaps.details[i];
    }
    out << "],\"records\":[";
    for (std::size_t i = 0; i < records.size(); ++i) {
        if (i) out << ',';
        out << records[i];
    }
    out << "]}";
    return out.str();
}
} // namespace

std::string CaptureWorldRaw(std::uintptr_t base, std::uint32_t image_size,
                            std::uint64_t sequence) {
    try {
        std::lock_guard<std::mutex> lock(cursor_mutex);
        return capture(base, image_size, sequence);
    } catch (...) {
        // Including allocation failures: do not allow diagnostics to unwind
        // through the host's sampling thread. Empty JSON carries no success.
        return "{}";
    }
}

} // namespace coopsync::runtime
