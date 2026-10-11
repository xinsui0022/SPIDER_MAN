#pragma once

#include "coordinator.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace coopsync {

enum class MessageType : uint16_t {
    Hello = 1, Welcome = 2, Prepare = 3, Ready = 4, Start = 5,
    SkipRequest = 6, Skip = 7, Ended = 8, Release = 9,
    Blocked = 10, Ping = 11, Pong = 12
};

struct Message {
    MessageType type = MessageType::Hello;
    uint64_t session = 0;
    uint64_t sequence = 0;
    Ticket ticket{};
    EndState end_state{};
    std::string reason;
};

constexpr std::size_t kMaxPayloadBytes = 1024;
constexpr std::size_t kMinPayloadBytes = 76;
constexpr std::size_t kMaxCinematicIdBytes = 128;
constexpr std::size_t kMaxReasonBytes = 256;

// Encode returns the entire frame, including the four-byte network-order length.
std::vector<uint8_t> Encode(const Message& message);
// Decode accepts exactly one payload, without its length prefix.
Message Decode(const std::vector<uint8_t>& payload);

} // namespace coopsync
