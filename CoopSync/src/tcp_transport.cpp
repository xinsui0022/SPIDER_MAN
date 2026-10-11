#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>

#include "tcp_transport.h"

#include <chrono>
#include <memory>
#include <stdexcept>
#include <utility>

#pragma comment(lib, "ws2_32.lib")

namespace coopsync {
namespace {

using Clock = std::chrono::steady_clock;
constexpr uint32_t kSendTimeoutMs = 5000;

std::runtime_error SocketError(const char* operation, int error = WSAGetLastError()) {
    return std::runtime_error(std::string(operation) + " failed (Winsock " + std::to_string(error) + ")");
}

class WinsockRuntime {
public:
    WinsockRuntime() {
        WSADATA data{};
        const int result = WSAStartup(MAKEWORD(2, 2), &data);
        if (result != 0) throw SocketError("WSAStartup", result);
        if (data.wVersion != MAKEWORD(2, 2)) {
            WSACleanup();
            throw std::runtime_error("Winsock 2.2 is unavailable");
        }
    }
    ~WinsockRuntime() { WSACleanup(); }
};

void InitializeWinsock() {
    // Function-local static initialization is synchronized by the C++ runtime.
    static WinsockRuntime runtime;
    (void)runtime;
}

void MakeNonblocking(SOCKET socket) {
    u_long enabled = 1;
    if (ioctlsocket(socket, FIONBIO, &enabled) == SOCKET_ERROR)
        throw SocketError("ioctlsocket");
}

bool WaitForSocket(SOCKET socket, bool write, Clock::time_point deadline) {
    const auto now = Clock::now();
    const auto remaining = deadline > now
        ? std::chrono::duration_cast<std::chrono::microseconds>(deadline - now).count() : 0;
    timeval timeout{};
    timeout.tv_sec = static_cast<long>(remaining / 1000000);
    timeout.tv_usec = static_cast<long>(remaining % 1000000);
    fd_set ready;
    FD_ZERO(&ready);
    FD_SET(socket, &ready);
    fd_set errors;
    FD_ZERO(&errors);
    FD_SET(socket, &errors);
    const int result = select(0, write ? nullptr : &ready, write ? &ready : nullptr, &errors, &timeout);
    if (result == SOCKET_ERROR) throw SocketError("select");
    if (FD_ISSET(socket, &errors)) {
        int error = 0;
        int length = sizeof(error);
        if (getsockopt(socket, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&error), &length) == SOCKET_ERROR)
            throw SocketError("getsockopt");
        throw SocketError("socket", error);
    }
    return result != 0 && FD_ISSET(socket, &ready);
}

class OwnedSocket {
public:
    explicit OwnedSocket(SOCKET value) : value_(value) {}
    ~OwnedSocket() { if (value_ != INVALID_SOCKET) closesocket(value_); }
    SOCKET get() const { return value_; }
    SOCKET release() { return std::exchange(value_, INVALID_SOCKET); }
private:
    SOCKET value_;
};

using AddressList = std::unique_ptr<addrinfo, decltype(&freeaddrinfo)>;

AddressList Resolve(const std::string& host, uint16_t port) {
    if (host.empty()) throw std::invalid_argument("A host or explicit bind address is required");
    addrinfo hints{};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;
    // Prototype endpoints are numeric IPv4/IPv6 addresses. DNS is deliberately
    // rejected so synchronous resolver work cannot bypass the connect deadline.
    hints.ai_flags = AI_NUMERICHOST;
    addrinfo* list = nullptr;
    const std::string service = std::to_string(port);
    const int result = getaddrinfo(host.c_str(), service.c_str(), &hints, &list);
    if (result != 0) throw SocketError("getaddrinfo", result);
    return AddressList(list, &freeaddrinfo);
}

} // namespace

TcpConnection::~TcpConnection() { Close(); }

TcpConnection::TcpConnection(TcpConnection&& other) noexcept
    : socket_(std::exchange(other.socket_, kInvalidSocket)),
      receive_header_(other.receive_header_), header_used_(std::exchange(other.header_used_, 0)),
      receive_payload_(std::move(other.receive_payload_)),
      payload_used_(std::exchange(other.payload_used_, 0)) {}

TcpConnection& TcpConnection::operator=(TcpConnection&& other) noexcept {
    if (this != &other) {
        Close();
        socket_ = std::exchange(other.socket_, kInvalidSocket);
        receive_header_ = other.receive_header_;
        header_used_ = std::exchange(other.header_used_, 0);
        receive_payload_ = std::move(other.receive_payload_);
        payload_used_ = std::exchange(other.payload_used_, 0);
    }
    return *this;
}

void TcpConnection::Close() noexcept {
    if (socket_ != kInvalidSocket) {
        closesocket(static_cast<SOCKET>(socket_));
        socket_ = kInvalidSocket;
    }
    header_used_ = 0;
    receive_payload_.clear();
    payload_used_ = 0;
}

TcpConnection TcpConnection::Connect(const std::string& host, uint16_t port, uint32_t timeout_ms) {
    InitializeWinsock();
    if (port == 0) throw std::invalid_argument("Connect requires a nonzero port");
    const auto deadline = Clock::now() + std::chrono::milliseconds(timeout_ms);
    auto addresses = Resolve(host, port);
    int last_error = WSAECONNREFUSED;
    for (auto* address = addresses.get(); address != nullptr; address = address->ai_next) {
        OwnedSocket socket(::socket(address->ai_family, address->ai_socktype, address->ai_protocol));
        if (socket.get() == INVALID_SOCKET) { last_error = WSAGetLastError(); continue; }
        MakeNonblocking(socket.get());
        int result = connect(socket.get(), address->ai_addr, static_cast<int>(address->ai_addrlen));
        if (result == SOCKET_ERROR) {
            last_error = WSAGetLastError();
            if (last_error != WSAEWOULDBLOCK && last_error != WSAEINPROGRESS) continue;
            try {
                if (!WaitForSocket(socket.get(), true, deadline))
                    throw std::runtime_error("TCP connect timed out");
                int error = 0;
                int length = sizeof(error);
                if (getsockopt(socket.get(), SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&error), &length) == SOCKET_ERROR)
                    throw SocketError("getsockopt");
                if (error != 0) { last_error = error; continue; }
            } catch (const std::runtime_error&) {
                if (Clock::now() >= deadline) throw;
                last_error = WSAGetLastError();
                continue;
            }
        }
        return TcpConnection(static_cast<std::uintptr_t>(socket.release()));
    }
    throw SocketError("connect", last_error);
}

void TcpConnection::Send(const Message& message) {
    const auto frame = Encode(message);
    if (socket_ == kInvalidSocket) throw std::runtime_error("TCP connection is closed");
    const auto deadline = Clock::now() + std::chrono::milliseconds(kSendTimeoutMs);
    const SOCKET socket = static_cast<SOCKET>(socket_);
    std::size_t used = 0;
    try {
        while (used < frame.size()) {
            if (!WaitForSocket(socket, true, deadline)) throw std::runtime_error("TCP send timed out");
            const int sent = send(socket, reinterpret_cast<const char*>(frame.data() + used),
                                  static_cast<int>(frame.size() - used), 0);
            if (sent == SOCKET_ERROR) {
                if (WSAGetLastError() == WSAEWOULDBLOCK && Clock::now() < deadline) continue;
                throw SocketError("send");
            }
            if (sent == 0) throw std::runtime_error("Peer closed during send");
            used += static_cast<std::size_t>(sent);
            if (used < frame.size() && Clock::now() >= deadline)
                throw std::runtime_error("TCP send timed out");
        }
    } catch (...) {
        Close();
        throw;
    }
}

bool TcpConnection::Receive(Message& message, uint32_t timeout_ms) {
    if (socket_ == kInvalidSocket) throw std::runtime_error("TCP connection is closed");
    const auto deadline = Clock::now() + std::chrono::milliseconds(timeout_ms);
    const SOCKET socket = static_cast<SOCKET>(socket_);
    try {
        for (;;) {
            if (header_used_ == receive_header_.size() && receive_payload_.empty()) {
                uint32_t length = 0;
                for (uint8_t byte : receive_header_) length = (length << 8) | byte;
                if (length < kMinPayloadBytes || length > kMaxPayloadBytes)
                    throw std::runtime_error("Invalid TCP frame length");
                receive_payload_.resize(length);
            }
            if (!receive_payload_.empty() && payload_used_ == receive_payload_.size()) {
                Message decoded = Decode(receive_payload_);
                header_used_ = 0;
                receive_payload_.clear();
                payload_used_ = 0;
                message = std::move(decoded);
                return true;
            }
            if (!WaitForSocket(socket, false, deadline)) return false;
            uint8_t* destination = nullptr;
            std::size_t count = 0;
            if (header_used_ < receive_header_.size()) {
                destination = receive_header_.data() + header_used_;
                count = receive_header_.size() - header_used_;
            } else {
                destination = receive_payload_.data() + payload_used_;
                count = receive_payload_.size() - payload_used_;
            }
            const int received = recv(socket, reinterpret_cast<char*>(destination), static_cast<int>(count), 0);
            if (received == 0) throw std::runtime_error("Peer closed the TCP connection");
            if (received == SOCKET_ERROR) {
                if (WSAGetLastError() == WSAEWOULDBLOCK) {
                    if (Clock::now() >= deadline) return false;
                    continue;
                }
                throw SocketError("recv");
            }
            if (header_used_ < receive_header_.size()) header_used_ += static_cast<std::size_t>(received);
            else payload_used_ += static_cast<std::size_t>(received);
            // At most one bounded frame is drained per Receive. A ready, complete
            // frame can still be returned for a zero timeout without a blocking wait.
        }
    } catch (...) {
        Close();
        throw;
    }
}

TcpListener::TcpListener(std::string bind_address, uint16_t port) {
    InitializeWinsock();
    auto addresses = Resolve(bind_address, port);
    int last_error = WSAEADDRNOTAVAIL;
    for (auto* address = addresses.get(); address != nullptr; address = address->ai_next) {
        OwnedSocket socket(::socket(address->ai_family, address->ai_socktype, address->ai_protocol));
        if (socket.get() == INVALID_SOCKET) { last_error = WSAGetLastError(); continue; }
        BOOL exclusive = TRUE;
        if (setsockopt(socket.get(), SOL_SOCKET, SO_EXCLUSIVEADDRUSE,
                       reinterpret_cast<const char*>(&exclusive), sizeof(exclusive)) == SOCKET_ERROR)
            throw SocketError("setsockopt");
        if (bind(socket.get(), address->ai_addr, static_cast<int>(address->ai_addrlen)) == SOCKET_ERROR) {
            last_error = WSAGetLastError();
            continue;
        }
        MakeNonblocking(socket.get());
        if (listen(socket.get(), 1) == SOCKET_ERROR) throw SocketError("listen");
        sockaddr_storage bound{};
        int length = sizeof(bound);
        if (getsockname(socket.get(), reinterpret_cast<sockaddr*>(&bound), &length) == SOCKET_ERROR)
            throw SocketError("getsockname");
        port_ = bound.ss_family == AF_INET
            ? ntohs(reinterpret_cast<const sockaddr_in*>(&bound)->sin_port)
            : ntohs(reinterpret_cast<const sockaddr_in6*>(&bound)->sin6_port);
        socket_ = static_cast<std::uintptr_t>(socket.release());
        return;
    }
    throw SocketError("bind", last_error);
}

TcpListener::~TcpListener() { Close(); }

TcpListener::TcpListener(TcpListener&& other) noexcept
    : socket_(std::exchange(other.socket_, kInvalidSocket)), port_(std::exchange(other.port_, uint16_t{0})) {}

TcpListener& TcpListener::operator=(TcpListener&& other) noexcept {
    if (this != &other) {
        Close();
        socket_ = std::exchange(other.socket_, kInvalidSocket);
        port_ = std::exchange(other.port_, uint16_t{0});
    }
    return *this;
}

void TcpListener::Close() noexcept {
    if (socket_ != kInvalidSocket) {
        closesocket(static_cast<SOCKET>(socket_));
        socket_ = kInvalidSocket;
    }
    port_ = 0;
}

TcpConnection TcpListener::Accept(uint32_t timeout_ms) {
    if (socket_ == kInvalidSocket) throw std::runtime_error("TCP listener is closed");
    const auto deadline = Clock::now() + std::chrono::milliseconds(timeout_ms);
    const SOCKET listener = static_cast<SOCKET>(socket_);
    for (;;) {
        if (!WaitForSocket(listener, false, deadline)) throw std::runtime_error("TCP accept timed out");
        OwnedSocket peer(accept(listener, nullptr, nullptr));
        if (peer.get() == INVALID_SOCKET) {
            if (WSAGetLastError() == WSAEWOULDBLOCK && Clock::now() < deadline) continue;
            throw SocketError("accept");
        }
        MakeNonblocking(peer.get());
        return TcpConnection(static_cast<std::uintptr_t>(peer.release()));
    }
}

} // namespace coopsync
