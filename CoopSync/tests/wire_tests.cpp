#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>

#include "tcp_transport.h"
#include "wire.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <future>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

using namespace coopsync;

namespace {

unsigned checks = 0;

void Check(bool condition, const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}

template<class F> void Rejects(F&& operation, const char* message) {
    bool rejected = false;
    try { operation(); } catch (const std::exception&) { rejected = true; }
    Check(rejected, message);
}

Message Sample() {
    Message result;
    result.type = MessageType::Prepare;
    result.session = 0x0123456789abcdefULL;
    result.sequence = 0xfedcba9876543210ULL;
    result.ticket.epoch = 0x1020304050607080ULL;
    result.ticket.world_revision = 0x8070605040302010ULL;
    result.ticket.scene_id = 0x98badcfe;
    result.ticket.x = 1.25f;
    result.ticket.y = -2.5f;
    result.ticket.z = -0.0f;
    result.ticket.cinematic_id = "intro_scene";
    result.end_state.world_revision = 0xaabbccddeeff0011ULL;
    result.end_state.state_digest = 0x8877665544332211ULL;
    result.reason = std::string("ready\0detail", 12);
    return result;
}

bool Same(const Message& lhs, const Message& rhs) {
    return lhs.type == rhs.type && lhs.session == rhs.session && lhs.sequence == rhs.sequence
        && lhs.ticket.epoch == rhs.ticket.epoch
        && lhs.ticket.world_revision == rhs.ticket.world_revision
        && lhs.ticket.scene_id == rhs.ticket.scene_id
        && std::memcmp(&lhs.ticket.x, &rhs.ticket.x, sizeof(float)) == 0
        && std::memcmp(&lhs.ticket.y, &rhs.ticket.y, sizeof(float)) == 0
        && std::memcmp(&lhs.ticket.z, &rhs.ticket.z, sizeof(float)) == 0
        && lhs.ticket.cinematic_id == rhs.ticket.cinematic_id
        && lhs.end_state.world_revision == rhs.end_state.world_revision
        && lhs.end_state.state_digest == rhs.end_state.state_digest
        && lhs.reason == rhs.reason;
}

std::vector<uint8_t> Payload(const Message& message) {
    auto frame = Encode(message);
    return {frame.begin() + 4, frame.end()};
}

void TestWire() {
    const auto sample = Sample();
    const auto encoded = Encode(sample);
    Check(encoded.size() == 4 + kMinPayloadBytes + sample.ticket.cinematic_id.size() + sample.reason.size(),
          "frame length includes every field");
    const uint32_t declared = (uint32_t(encoded[0]) << 24) | (uint32_t(encoded[1]) << 16)
        | (uint32_t(encoded[2]) << 8) | encoded[3];
    Check(declared == encoded.size() - 4, "big-endian frame prefix");
    const auto payload = Payload(sample);
    const std::vector<uint8_t> prefix = {
        'C', 'S', 'Y', '1', 0, 1, 0, 3,
        0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
        0xfe, 0xdc, 0xba, 0x98, 0x76, 0x54, 0x32, 0x10,
        0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80,
        0x80, 0x70, 0x60, 0x50, 0x40, 0x30, 0x20, 0x10,
        0x98, 0xba, 0xdc, 0xfe,
        0x3f, 0xa0, 0, 0, 0xc0, 0x20, 0, 0, 0x80, 0, 0, 0,
        0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0, 0x11,
        0x88, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x11,
        0, 11
    };
    Check(std::equal(prefix.begin(), prefix.end(), payload.begin()), "independent wire byte layout");
    Check(Same(Decode(payload), sample), "all message fields round trip");
    for (uint16_t value = 1; value <= 12; ++value) {
        auto message = sample;
        message.type = static_cast<MessageType>(value);
        Check(Same(message, Decode(Payload(message))), "all defined message types round trip");
    }
    for (std::size_t length = 0; length < payload.size(); ++length) {
        const std::vector<uint8_t> truncated(payload.begin(), payload.begin() + length);
        Rejects([&] { Decode(truncated); }, "every truncated field is rejected");
    }
    auto mutated = payload;
    mutated.push_back(0);
    Rejects([&] { Decode(mutated); }, "trailing payload byte rejected");
    Rejects([&] { Decode(std::vector<uint8_t>(1025)); }, "oversized payload rejected");
    for (std::size_t offset : {std::size_t(0), std::size_t(5), std::size_t(6)}) {
        mutated = payload;
        mutated[offset] = 0xff;
        Rejects([&] { Decode(mutated); }, "invalid magic version or message type rejected");
    }
    for (std::size_t offset : {std::size_t(8), std::size_t(16)}) {
        mutated = payload;
        std::fill(mutated.begin() + offset, mutated.begin() + offset + 8, uint8_t{0});
        Rejects([&] { Decode(mutated); }, "zero session or sequence rejected");
    }
    for (std::size_t offset : {std::size_t(44), std::size_t(48), std::size_t(52)}) {
        for (uint8_t mantissa : {uint8_t(0x80), uint8_t(0xc0)}) {
            mutated = payload;
            mutated[offset] = 0x7f;
            mutated[offset + 1] = mantissa;
            mutated[offset + 2] = mutated[offset + 3] = 0;
            Rejects([&] { Decode(mutated); }, "wire infinity or NaN rejected");
        }
    }
    auto maximum = sample;
    maximum.ticket.cinematic_id.assign(128, 'x');
    maximum.reason.assign(256, 'y');
    Check(Same(maximum, Decode(Payload(maximum))), "maximum text lengths accepted");
    maximum.ticket.cinematic_id.push_back('x');
    Rejects([&] { Encode(maximum); }, "oversized cinematic ID rejected");
    maximum = sample;
    maximum.reason.assign(257, 'y');
    Rejects([&] { Encode(maximum); }, "oversized reason rejected");
    mutated = payload;
    mutated[72] = 0; mutated[73] = 129;
    Rejects([&] { Decode(mutated); }, "oversized declared cinematic ID rejected");
    mutated = payload;
    const auto reason_offset = 74 + sample.ticket.cinematic_id.size();
    mutated[reason_offset] = 1; mutated[reason_offset + 1] = 1;
    Rejects([&] { Decode(mutated); }, "oversized declared reason rejected");
    for (float value : {std::numeric_limits<float>::infinity(),
                        -std::numeric_limits<float>::infinity(),
                        std::numeric_limits<float>::quiet_NaN()}) {
        auto bad = sample;
        bad.ticket.x = value;
        Rejects([&] { Encode(bad); }, "nonfinite encode coordinate rejected");
    }
    for (uint16_t value : {uint16_t(0), uint16_t(13), uint16_t(65535)}) {
        auto bad = sample;
        bad.type = static_cast<MessageType>(value);
        Rejects([&] { Encode(bad); }, "undefined encode type rejected");
    }
    auto bad = sample;
    bad.session = 0;
    Rejects([&] { Encode(bad); }, "zero encode session rejected");
    bad = sample; bad.sequence = 0;
    Rejects([&] { Encode(bad); }, "zero encode sequence rejected");
}

class RawPeer {
public:
    explicit RawPeer(uint16_t port, bool small_receive_buffer = false) {
        socket_ = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (socket_ == INVALID_SOCKET) throw std::runtime_error("raw socket creation failed");
        if (small_receive_buffer) {
            const int size = 1024;
            if (setsockopt(socket_, SOL_SOCKET, SO_RCVBUF, reinterpret_cast<const char*>(&size), sizeof(size)) != 0)
                throw std::runtime_error("raw receive buffer configuration failed");
        }
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(port);
        inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);
        if (connect(socket_, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0) {
            closesocket(socket_); socket_ = INVALID_SOCKET;
            throw std::runtime_error("raw socket connect failed");
        }
        const DWORD timeout = 3000;
        setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
        setsockopt(socket_, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
    }
    ~RawPeer() { if (socket_ != INVALID_SOCKET) closesocket(socket_); }
    RawPeer(const RawPeer&) = delete;
    RawPeer& operator=(const RawPeer&) = delete;
    void SendBytes(const uint8_t* bytes, std::size_t count) {
        while (count != 0) {
            const int sent = send(socket_, reinterpret_cast<const char*>(bytes), static_cast<int>(count), 0);
            if (sent <= 0) throw std::runtime_error("raw send failed");
            bytes += sent; count -= static_cast<std::size_t>(sent);
        }
    }
    void SendBytes(const std::vector<uint8_t>& bytes) { SendBytes(bytes.data(), bytes.size()); }
    std::vector<uint8_t> ReceiveBytes(std::size_t count) {
        std::vector<uint8_t> bytes(count);
        std::size_t used = 0;
        while (used != count) {
            const int received = recv(socket_, reinterpret_cast<char*>(bytes.data() + used), static_cast<int>(count - used), 0);
            if (received <= 0) throw std::runtime_error("raw receive failed");
            used += static_cast<std::size_t>(received);
        }
        return bytes;
    }
    void EndSending() { shutdown(socket_, SD_SEND); }
private:
    SOCKET socket_ = INVALID_SOCKET;
};

void TestConcurrentStartup() {
    std::vector<std::future<bool>> results;
    for (unsigned i = 0; i < 8; ++i) {
        results.push_back(std::async(std::launch::async, [i] {
            TcpListener listener;
            auto client = TcpConnection::Connect("127.0.0.1", listener.port(), 1000);
            auto host = listener.Accept(1000);
            auto sent = Sample();
            sent.sequence = i + 1;
            client.Send(sent);
            Message received;
            return host.Receive(received, 1000) && Same(sent, received);
        }));
    }
    for (auto& result : results) Check(result.get(), "concurrent Winsock initialization and connections");
}

void TestFragmentedTransport() {
    TcpListener listener;
    Check(listener.port() != 0, "listener selects ephemeral loopback port");
    RawPeer peer(listener.port());
    auto connection = listener.Accept(1000);
    const auto sample = Sample();
    const auto frame = Encode(sample);
    Message received;
    received.sequence = 17;
    peer.SendBytes(frame.data(), 2);
    Check(!connection.Receive(received, 10), "partial header times out");
    Check(received.sequence == 17, "timeout does not mutate output message");
    TcpConnection moved(std::move(connection));
    Rejects([&] { connection.Receive(received, 0); }, "moved-from connection is closed");
    peer.SendBytes(frame.data() + 2, 15);
    Check(!moved.Receive(received, 10), "partial payload times out");
    connection = std::move(moved);
    peer.SendBytes(frame.data() + 17, frame.size() - 17);
    Check(connection.Receive(received, 1000), "split frame completes after timeout and moves");
    Check(Same(received, sample), "partial receive state is retained without corruption");
    peer.SendBytes(frame);
    auto second = sample; ++second.sequence;
    peer.SendBytes(Encode(second));
    Check(connection.Receive(received, 1000) && Same(received, sample), "first coalesced frame exact");
    Check(connection.Receive(received, 1000) && Same(received, second), "next coalesced frame retained");
    Check(!connection.Receive(received, 1), "idle receive times out");
    connection.Send(second);
    Check(peer.ReceiveBytes(Encode(second).size()) == Encode(second), "TCP send emits exact encoded frame");
    // Invalid local input leaves the valid connection usable; no frame was sent.
    auto invalid = second; invalid.sequence = 0;
    Rejects([&] { connection.Send(invalid); }, "invalid outgoing message rejected");
    connection.Send(sample);
    Check(peer.ReceiveBytes(frame.size()) == frame, "local encode error does not damage connection");
    peer.EndSending();
    Rejects([&] { connection.Receive(received, 1000); }, "peer EOF throws");
    Rejects([&] { connection.Receive(received, 0); }, "EOF terminates connection");
}

void TestBadFrame(const std::vector<uint8_t>& bytes, bool end_sending) {
    TcpListener listener;
    RawPeer peer(listener.port());
    auto connection = listener.Accept(1000);
    peer.SendBytes(bytes);
    if (end_sending) peer.EndSending();
    Message received;
    Rejects([&] { connection.Receive(received, 1000); }, "malformed or truncated TCP frame rejected");
    Rejects([&] { connection.Receive(received, 0); }, "protocol error terminates connection");
}

void TestTransportErrors() {
    TestBadFrame({0, 0, 0, 0}, false);
    TestBadFrame({0, 0, 4, 1}, false);
    TestBadFrame({0, 0, 0, 75}, false);
    auto bytes = Encode(Sample());
    bytes[4] = 0;
    TestBadFrame(bytes, false);
    bytes = Encode(Sample());
    bytes.resize(9);
    TestBadFrame(bytes, true);
    TestBadFrame({0, 0}, true);
    TcpListener listener;
    Rejects([&] { listener.Accept(1); }, "accept timeout throws");
    Rejects([&] { TcpConnection::Connect("127.0.0.1", 0, 1); }, "zero destination port rejected");
    Rejects([&] { TcpConnection::Connect("localhost", listener.port(), 1000); }, "hostname is rejected without DNS lookup");
    Rejects([&] { TcpListener empty("", 0); }, "empty bind address rejected");
    auto moved = std::move(listener);
    Check(listener.port() == 0 && moved.port() != 0, "listener move transfers ownership");
    Rejects([&] { listener.Accept(0); }, "moved-from listener is closed");
    uint16_t unused_port = 0;
    { TcpListener temporary; unused_port = temporary.port(); }
    Rejects([&] { TcpConnection::Connect("127.0.0.1", unused_port, 1000); }, "refused connect throws");
}

void TestSlowReaderDeadline() {
    TcpListener listener;
    RawPeer peer(listener.port(), true);
    auto connection = listener.Accept(1000);
    auto message = Sample();
    message.ticket.cinematic_id.assign(128, 'x');
    message.reason.assign(256, 'y');
    const auto started = std::chrono::steady_clock::now();
    bool rejected = false;
    // An idle receiver must eventually stop Send. At most 46.4 MB is attempted,
    // with no files or remote destinations involved.
    for (unsigned i = 0; i < 100000 && !rejected; ++i) {
        try { connection.Send(message); }
        catch (const std::exception&) { rejected = true; }
    }
    const auto elapsed = std::chrono::steady_clock::now() - started;
    Check(rejected, "idle receiver produces bounded send failure");
    Check(elapsed < std::chrono::seconds(20), "slow-reader send deadline is finite");
    Rejects([&] { connection.Send(message); }, "send timeout terminates partial-frame connection");
}

} // namespace

int main() {
    try {
        TestConcurrentStartup();
        TestWire();
        TestFragmentedTransport();
        TestTransportErrors();
        TestSlowReaderDeadline();
        std::cout << "PASS wire/TCP: " << checks << " checks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL wire/TCP after " << checks << " checks: " << error.what() << '\n';
        return 1;
    }
}
