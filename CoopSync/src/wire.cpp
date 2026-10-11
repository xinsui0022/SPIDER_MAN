#include "wire.h"

#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace coopsync {
namespace {

static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
              "CoopSync wire protocol requires IEEE-754 binary32");

bool ValidType(MessageType type) {
    const auto value = static_cast<uint16_t>(type);
    return value >= static_cast<uint16_t>(MessageType::Hello)
        && value <= static_cast<uint16_t>(MessageType::Pong);
}

void Validate(const Message& message) {
    if (!ValidType(message.type)) throw std::invalid_argument("Unknown message type");
    if (message.session == 0 || message.sequence == 0)
        throw std::invalid_argument("Session and sequence must be nonzero");
    if (message.ticket.cinematic_id.size() > kMaxCinematicIdBytes)
        throw std::invalid_argument("Cinematic ID exceeds 128 bytes");
    if (message.reason.size() > kMaxReasonBytes)
        throw std::invalid_argument("Reason exceeds 256 bytes");
    if (!std::isfinite(message.ticket.x) || !std::isfinite(message.ticket.y)
        || !std::isfinite(message.ticket.z))
        throw std::invalid_argument("Coordinates must be finite");
}

void Put(std::vector<uint8_t>& bytes, uint64_t value, std::size_t count) {
    for (std::size_t i = count; i != 0; --i)
        bytes.push_back(static_cast<uint8_t>(value >> ((i - 1) * 8)));
}

void PutFloat(std::vector<uint8_t>& bytes, float value) {
    uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    Put(bytes, bits, 4);
}

void PutText(std::vector<uint8_t>& bytes, const std::string& value) {
    Put(bytes, value.size(), 2);
    bytes.insert(bytes.end(), value.begin(), value.end());
}

class Reader {
public:
    explicit Reader(const std::vector<uint8_t>& bytes) : bytes_(bytes) {}

    uint64_t Get(std::size_t count) {
        Require(count);
        uint64_t value = 0;
        for (std::size_t i = 0; i < count; ++i)
            value = (value << 8) | bytes_[position_++];
        return value;
    }

    float GetFloat() {
        const uint32_t bits = static_cast<uint32_t>(Get(4));
        float value = 0;
        std::memcpy(&value, &bits, sizeof(value));
        return value;
    }

    std::string GetText(std::size_t maximum) {
        const auto count = static_cast<std::size_t>(Get(2));
        if (count > maximum) throw std::invalid_argument("Text length exceeds protocol limit");
        Require(count);
        std::string value(bytes_.begin() + position_, bytes_.begin() + position_ + count);
        position_ += count;
        return value;
    }

    bool Finished() const { return position_ == bytes_.size(); }

private:
    void Require(std::size_t count) const {
        if (count > bytes_.size() - position_)
            throw std::invalid_argument("Truncated payload");
    }

    const std::vector<uint8_t>& bytes_;
    std::size_t position_ = 0;
};

} // namespace

std::vector<uint8_t> Encode(const Message& message) {
    Validate(message);
    const auto payload_size = kMinPayloadBytes + message.ticket.cinematic_id.size()
        + message.reason.size();
    if (payload_size > kMaxPayloadBytes) throw std::invalid_argument("Payload exceeds 1024 bytes");
    std::vector<uint8_t> bytes;
    bytes.reserve(payload_size + 4);
    Put(bytes, payload_size, 4);
    bytes.insert(bytes.end(), {'C', 'S', 'Y', '1'});
    Put(bytes, 1, 2);
    Put(bytes, static_cast<uint16_t>(message.type), 2);
    Put(bytes, message.session, 8);
    Put(bytes, message.sequence, 8);
    Put(bytes, message.ticket.epoch, 8);
    Put(bytes, message.ticket.world_revision, 8);
    Put(bytes, message.ticket.scene_id, 4);
    PutFloat(bytes, message.ticket.x);
    PutFloat(bytes, message.ticket.y);
    PutFloat(bytes, message.ticket.z);
    Put(bytes, message.end_state.world_revision, 8);
    Put(bytes, message.end_state.state_digest, 8);
    PutText(bytes, message.ticket.cinematic_id);
    PutText(bytes, message.reason);
    return bytes;
}

Message Decode(const std::vector<uint8_t>& payload) {
    if (payload.size() < kMinPayloadBytes || payload.size() > kMaxPayloadBytes)
        throw std::invalid_argument("Invalid payload length");
    Reader reader(payload);
    if (reader.Get(4) != 0x43535931) throw std::invalid_argument("Invalid protocol magic");
    if (reader.Get(2) != 1) throw std::invalid_argument("Unsupported protocol version");
    Message message;
    message.type = static_cast<MessageType>(reader.Get(2));
    message.session = reader.Get(8);
    message.sequence = reader.Get(8);
    message.ticket.epoch = reader.Get(8);
    message.ticket.world_revision = reader.Get(8);
    message.ticket.scene_id = static_cast<uint32_t>(reader.Get(4));
    message.ticket.x = reader.GetFloat();
    message.ticket.y = reader.GetFloat();
    message.ticket.z = reader.GetFloat();
    message.end_state.world_revision = reader.Get(8);
    message.end_state.state_digest = reader.Get(8);
    message.ticket.cinematic_id = reader.GetText(kMaxCinematicIdBytes);
    message.reason = reader.GetText(kMaxReasonBytes);
    if (!reader.Finished()) throw std::invalid_argument("Trailing payload data");
    Validate(message);
    return message;
}

} // namespace coopsync
