#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "coordinator.h"
#include "tcp_transport.h"
#include <windows.h>
#include <bcrypt.h>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>

namespace {
using namespace coopsync;
constexpr uint64_t kDigest = 0x53494d554c415445ull; // SIMULATE: never a game snapshot.
struct Options {
    std::string role, address = "127.0.0.1", scenario = "natural", log;
    uint16_t port = 0;
    bool simulate = false;
};
std::string Escape(const std::string& s) {
    std::string out;
    const char hex[] = "0123456789abcdef";
    for (const unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
        else if (c < 32) { out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
        else out += static_cast<char>(c);
    }
    return out;
}
class Logger {
    std::string role_;
    std::ofstream file_;
public:
    Logger(std::string role, const std::string& path) : role_(std::move(role)) {
        if (!path.empty()) {
            file_.open(path, std::ios::out | std::ios::trunc);
            if (!file_) throw std::runtime_error("Cannot create requested log file");
        }
    }
    void Write(const std::string& event, uint64_t epoch = 0,
               const std::string& detail = "", uint16_t port = 0) {
        const std::string row = "{\"build_version\":\"0.1\",\"monotonic_ms\":" + std::to_string(GetTickCount64()) +
            ",\"mode\":\"simulation\",\"game_operations\":false,\"role\":\"" +
            Escape(role_) + "\",\"event\":\"" + Escape(event) + "\",\"epoch\":" +
            std::to_string(epoch) + ",\"detail\":\"" + Escape(detail) + "\",\"port\":" +
            std::to_string(port) + "}";
        std::cout << row << std::endl;
        if (file_) { file_ << row << '\n'; file_.flush(); }
    }
};
Options Parse(int argc, char** argv) {
    if (argc < 2) throw std::invalid_argument("Usage: CoopSync.exe host|guest --simulate [--port N] [--host ADDRESS|--bind ADDRESS] [--scenario natural|host-skip|guest-skip|mismatch-end|disconnect] [--log FILE]");
    Options o; o.role = argv[1];
    if (o.role != "host" && o.role != "guest") throw std::invalid_argument("Role must be host or guest");
    std::map<std::string, bool> seen;
    for (int i = 2; i < argc; ++i) {
        const std::string key = argv[i];
        if (seen[key]) throw std::invalid_argument("Duplicate option: " + key);
        seen[key] = true;
        if (key == "--simulate") { o.simulate = true; continue; }
        if (key != "--port" && key != "--host" && key != "--bind" && key != "--scenario" && key != "--log")
            throw std::invalid_argument("Unknown option: " + key);
        if (++i == argc) throw std::invalid_argument("Missing value: " + key);
        const std::string value = argv[i];
        if (key == "--port") {
            if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
                throw std::invalid_argument("Port must be numeric");
            size_t end = 0; const auto n = std::stoul(value, &end);
            if (end != value.size() || n > 65535) throw std::invalid_argument("Port outside 0..65535");
            o.port = static_cast<uint16_t>(n);
        } else if (key == "--host" || key == "--bind") {
            if ((key == "--host") != (o.role == "guest")) throw std::invalid_argument("Address option does not match role");
            if (value.empty()) throw std::invalid_argument("Empty address");
            o.address = value;
        } else if (key == "--scenario") {
            if (o.role != "host") throw std::invalid_argument("Scenario is selected by host");
            o.scenario = value;
        } else o.log = value;
    }
    if (!o.simulate) throw std::invalid_argument("Game adapter is not implemented. Explicit --simulate is required; this build does not control Spider-Man.");
    if (o.role == "guest" && !o.port) throw std::invalid_argument("Guest requires a nonzero --port");
    if (o.scenario != "natural" && o.scenario != "host-skip" && o.scenario != "guest-skip" &&
        o.scenario != "mismatch-end" && o.scenario != "disconnect") throw std::invalid_argument("Unknown scenario");
    return o;
}
uint64_t RandomId() {
    uint64_t id = 0;
    if (BCryptGenRandom(nullptr, reinterpret_cast<PUCHAR>(&id), sizeof(id), BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0)
        throw std::runtime_error("Session identifier generation failed");
    return id ? id : 1;
}
Message Make(MessageType type, uint64_t session, uint64_t sequence, const Ticket& ticket = {},
             const EndState& state = {}, const std::string& reason = "") {
    Message m{}; m.type = type; m.session = session; m.sequence = sequence;
    m.ticket = ticket; m.end_state = state; m.reason = reason; return m;
}
bool SameTicket(const Ticket& a, const Ticket& b) {
    return a.epoch == b.epoch && a.scene_id == b.scene_id && a.world_revision == b.world_revision &&
        a.cinematic_id == b.cinematic_id && a.x == b.x && a.y == b.y && a.z == b.z;
}
bool AcceptSequence(const Message& m, uint64_t session, uint64_t& previous) {
    if (m.session != session) throw std::runtime_error("Message belongs to another session");
    if (m.sequence <= previous) return false;
    if (m.sequence != previous + 1) throw std::runtime_error("Message sequence gap on reliable stream");
    previous = m.sequence; return true;
}
int Host(const Options& o, Logger& log) {
    TcpListener listener(o.address, o.port);
    log.Write("listening", 0, o.address, listener.port());
    auto peer = listener.Accept(5000);
    Message hello;
    if (!peer.Receive(hello, 5000) || hello.type != MessageType::Hello || hello.sequence != 1 || hello.ticket.epoch != 0)
        throw std::runtime_error("Invalid simulation handshake");
    const uint64_t session = RandomId();
    uint64_t send_sequence = 1, receive_sequence = hello.sequence;
    peer.Send(Make(MessageType::Welcome, session, send_sequence++, {}, {}, o.scenario));
    HostCoordinator coordinator(2000, 2000);
    bool local_ready_due = false, local_ended = false, skip_due = false;
    uint64_t end_at = 0;
    const auto dispatch = [&](const std::vector<Action>& actions) {
        for (const auto& action : actions) {
            const auto epoch = action.ticket.epoch;
            switch (action.type) {
            case ActionType::PreparePeer:
                peer.Send(Make(MessageType::Prepare, session, send_sequence++, action.ticket));
                log.Write("prepare_sent", epoch); break;
            case ActionType::GatherLocal:
                log.Write("gather_local_simulated", epoch); local_ready_due = true; break;
            case ActionType::StartPeer:
                peer.Send(Make(MessageType::Start, session, send_sequence++, action.ticket)); break;
            case ActionType::StartLocal:
                log.Write("start_local_simulated", epoch); end_at = GetTickCount64() + 100;
                skip_due = o.scenario == "host-skip"; break;
            case ActionType::SkipPeer:
                peer.Send(Make(MessageType::Skip, session, send_sequence++, action.ticket)); break;
            case ActionType::SkipLocal:
                log.Write("skip_local_simulated", epoch); if (!local_ended) end_at = GetTickCount64() + 10; break;
            case ActionType::ReleasePeer:
                try { peer.Send(Make(MessageType::Release, session, send_sequence++, action.ticket, action.end_state)); }
                catch (const std::exception& e) { log.Write("release_delivery_failed", epoch, e.what()); throw; }
                break;
            case ActionType::ReleaseLocal:
                log.Write("released", epoch, "Matching simulated terminal state; no game world was copied"); break;
            case ActionType::BlockPeer:
                try { peer.Send(Make(MessageType::Blocked, session, send_sequence++, action.ticket, {}, action.reason)); }
                catch (const std::exception&) { /* Peer may already be disconnected. */ }
                break;
            case ActionType::BlockLocal:
                log.Write("blocked", epoch, action.reason); break;
            }
        }
    };
    Ticket ticket{}; ticket.scene_id = 101; ticket.world_revision = 1;
    ticket.cinematic_id = "simulated_fisk_intro"; ticket.y = 1;
    try {
        dispatch(coordinator.Prepare(ticket, GetTickCount64()));
        for (;;) {
            const auto now = GetTickCount64();
            if (local_ready_due) {
                local_ready_due = false; const auto& t = coordinator.ticket();
                dispatch(coordinator.LocalReady(t.epoch, t.scene_id, t.world_revision, now));
            }
            if (skip_due) {
                skip_due = false;
                dispatch(coordinator.LocalSkip(coordinator.ticket().epoch, now));
            }
            if (end_at && !local_ended && now >= end_at) {
                local_ended = true; log.Write("ended_local_simulated", coordinator.ticket().epoch);
                dispatch(coordinator.LocalEnded(coordinator.ticket().epoch, {2, kDigest}, now));
            }
            dispatch(coordinator.Tick(now));
            if (coordinator.phase() == Phase::Idle) return 0;
            if (coordinator.phase() == Phase::Blocked) return 2;
            Message m;
            if (!peer.Receive(m, 20)) continue;
            if (!AcceptSequence(m, session, receive_sequence)) { log.Write("duplicate_ignored", m.ticket.epoch); continue; }
            if ((m.type == MessageType::Ready || m.type == MessageType::SkipRequest || m.type == MessageType::Ended) &&
                m.ticket.epoch == coordinator.ticket().epoch && !SameTicket(m.ticket, coordinator.ticket()))
                throw std::runtime_error("Guest message does not match the current cinematic ticket");
            if (m.type == MessageType::Ready) {
                log.Write("peer_ready", m.ticket.epoch);
                dispatch(coordinator.PeerReady(m.ticket.epoch, m.ticket.scene_id, m.ticket.world_revision, GetTickCount64()));
            } else if (m.type == MessageType::SkipRequest) {
                log.Write("peer_skip_request", m.ticket.epoch);
                dispatch(coordinator.PeerSkip(m.ticket.epoch, GetTickCount64()));
            } else if (m.type == MessageType::Ended) {
                log.Write("peer_ended", m.ticket.epoch);
                dispatch(coordinator.PeerEnded(m.ticket.epoch, m.end_state, GetTickCount64()));
            } else if (m.type == MessageType::Ping) {
                peer.Send(Make(MessageType::Pong, session, send_sequence++, m.ticket));
            } else throw std::runtime_error("Guest sent a host-only or unexpected message");
        }
    } catch (const std::exception& e) {
        log.Write("transport_error", coordinator.ticket().epoch, e.what());
        dispatch(coordinator.Abort("Peer communication failed"));
        return 2;
    }
}
int Guest(const Options& o, Logger& log) {
    auto peer = TcpConnection::Connect(o.address, o.port, 5000);
    uint64_t send_sequence = 1;
    peer.Send(Make(MessageType::Hello, RandomId(), send_sequence++));
    Message welcome;
    if (!peer.Receive(welcome, 5000) || welcome.type != MessageType::Welcome || welcome.sequence != 1)
        throw std::runtime_error("Invalid host handshake");
    const auto session = welcome.session;
    uint64_t receive_sequence = welcome.sequence, end_at = 0;
    Ticket current{}; bool started = false, ended = false, skipped = false;
    EndState final_state{2, kDigest};
    const auto deadline = GetTickCount64() + 6000;
    for (;;) {
        const auto now = GetTickCount64();
        if (now >= deadline) throw std::runtime_error("Simulation session timed out");
        if (started && !ended && now >= end_at) {
            ended = true;
            if (welcome.reason == "mismatch-end") final_state.state_digest ^= 1;
            peer.Send(Make(MessageType::Ended, session, send_sequence++, current, final_state));
            log.Write("ended_local_simulated", current.epoch);
        }
        Message m;
        if (!peer.Receive(m, 20)) continue;
        if (!AcceptSequence(m, session, receive_sequence)) { log.Write("duplicate_ignored", m.ticket.epoch); continue; }
        if (m.type == MessageType::Prepare) {
            if (current.epoch || !m.ticket.epoch || m.ticket.cinematic_id.empty()) throw std::runtime_error("Unexpected prepare");
            current = m.ticket;
            log.Write("gather_local_simulated", current.epoch);
            if (welcome.reason == "disconnect") { log.Write("disconnect_simulated", current.epoch); peer.Close(); return 2; }
            peer.Send(Make(MessageType::Ready, session, send_sequence++, current));
            log.Write("ready_sent", current.epoch);
        } else if (m.type == MessageType::Start) {
            if (!current.epoch || !SameTicket(m.ticket, current)) throw std::runtime_error("Start does not match prepared scene");
            if (started) continue;
            started = true; end_at = GetTickCount64() + 120;
            log.Write("start_local_simulated", current.epoch);
            if (welcome.reason == "guest-skip") {
                peer.Send(Make(MessageType::SkipRequest, session, send_sequence++, current));
                log.Write("skip_requested", current.epoch);
            }
        } else if (m.type == MessageType::Skip) {
            if (!SameTicket(m.ticket, current) || !started) throw std::runtime_error("Skip outside current cinematic");
            if (!skipped) {
                skipped = true;
                if (!ended) end_at = GetTickCount64() + 10;
                log.Write("skip_local_simulated", current.epoch);
            }
        } else if (m.type == MessageType::Release) {
            if (!SameTicket(m.ticket, current) || !ended || m.end_state.world_revision != final_state.world_revision ||
                m.end_state.state_digest != final_state.state_digest) throw std::runtime_error("Release before matching terminal state");
            log.Write("released", current.epoch, "Matching simulated terminal state; no game world was copied"); return 0;
        } else if (m.type == MessageType::Blocked) {
            if (!current.epoch || !SameTicket(m.ticket, current)) throw std::runtime_error("Blocked message does not match current cinematic");
            log.Write("blocked", m.ticket.epoch, m.reason); return 2;
        } else if (m.type == MessageType::Ping) {
            peer.Send(Make(MessageType::Pong, session, send_sequence++, current));
        } else throw std::runtime_error("Host sent a guest-only or unexpected message");
    }
}
}
int main(int argc, char** argv) {
    try {
        const auto options = Parse(argc, argv);
        Logger log(options.role, options.log);
        log.Write("simulation_only", 0, "TCP and coordinator test; Spider-Man is not controlled");
        return options.role == "host" ? Host(options, log) : Guest(options, log);
    } catch (const std::exception& e) {
        std::cerr << "CoopSync: " << e.what() << std::endl; return 1;
    }
}
