#pragma once

#include "wire.h"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace coopsync {

// Each connection is owned by one thread; different connections may run concurrently.
class TcpConnection {
public:
    TcpConnection() noexcept = default;
    ~TcpConnection();
    TcpConnection(const TcpConnection&) = delete;
    TcpConnection& operator=(const TcpConnection&) = delete;
    TcpConnection(TcpConnection&& other) noexcept;
    TcpConnection& operator=(TcpConnection&& other) noexcept;

    // Numeric IPv4/IPv6 only; synchronous DNS cannot bypass the connect deadline.
    static TcpConnection Connect(const std::string& host, uint16_t port, uint32_t timeout_ms);
    // A partially sent frame cannot be retried. Errors/timeouts close the connection.
    void Send(const Message& message);
    // Timeout retains a partial header/payload for the next call.
    bool Receive(Message& message, uint32_t timeout_ms);
    void Close() noexcept;

private:
    friend class TcpListener;
    explicit TcpConnection(std::uintptr_t socket) noexcept : socket_(socket) {}
    static constexpr std::uintptr_t kInvalidSocket = ~std::uintptr_t(0);
    std::uintptr_t socket_ = kInvalidSocket;
    std::array<uint8_t, 4> receive_header_{};
    std::size_t header_used_ = 0;
    std::vector<uint8_t> receive_payload_;
    std::size_t payload_used_ = 0;
};

class TcpListener {
public:
    // Port zero asks Windows to select an available port. External bind is explicit.
    explicit TcpListener(std::string bind_address = "127.0.0.1", uint16_t port = 0);
    ~TcpListener();
    TcpListener(const TcpListener&) = delete;
    TcpListener& operator=(const TcpListener&) = delete;
    TcpListener(TcpListener&& other) noexcept;
    TcpListener& operator=(TcpListener&& other) noexcept;

    uint16_t port() const noexcept { return port_; }
    TcpConnection Accept(uint32_t timeout_ms);

private:
    void Close() noexcept;
    static constexpr std::uintptr_t kInvalidSocket = ~std::uintptr_t(0);
    std::uintptr_t socket_ = kInvalidSocket;
    uint16_t port_ = 0;
};

} // namespace coopsync
