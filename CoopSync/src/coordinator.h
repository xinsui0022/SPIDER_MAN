#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace coopsync {

enum class Phase { Idle, Preparing, Playing, Ending, Blocked };

enum class ActionType {
    PreparePeer,
    GatherLocal,
    StartPeer,
    StartLocal,
    SkipPeer,
    SkipLocal,
    ReleasePeer,
    ReleaseLocal,
    BlockPeer,
    BlockLocal
};

struct Ticket {
    std::uint64_t epoch = 0;
    std::uint64_t world_revision = 0;
    std::uint32_t scene_id = 0;
    std::string cinematic_id;
    float x = 0;
    float y = 0;
    float z = 0;
};

// These values only form a barrier. They do not carry or replicate world data.
struct EndState {
    std::uint64_t world_revision = 0;
    std::uint64_t state_digest = 0;
};

struct Action {
    ActionType type = ActionType::BlockLocal;
    Ticket ticket;
    EndState end_state;
    std::string reason;
};

class HostCoordinator {
public:
    explicit HostCoordinator(std::uint64_t prepare_timeout_ms = 10000,
                             std::uint64_t ending_timeout_ms = 10000);

    // now_ms must come from one monotonic clock for this session. A supplied
    // ticket epoch is ignored; only the coordinator allocates epochs.
    // Invalid tickets throw invalid_argument without consuming an epoch.
    std::vector<Action> Prepare(Ticket ticket, std::uint64_t now_ms);
    std::vector<Action> LocalReady(std::uint64_t epoch, std::uint32_t scene_id,
                                   std::uint64_t revision, std::uint64_t now_ms);
    std::vector<Action> PeerReady(std::uint64_t epoch, std::uint32_t scene_id,
                                  std::uint64_t revision, std::uint64_t now_ms);
    std::vector<Action> LocalSkip(std::uint64_t epoch, std::uint64_t now_ms);
    std::vector<Action> PeerSkip(std::uint64_t epoch, std::uint64_t now_ms);
    std::vector<Action> LocalEnded(std::uint64_t epoch, EndState state,
                                   std::uint64_t now_ms);
    std::vector<Action> PeerEnded(std::uint64_t epoch, EndState state,
                                  std::uint64_t now_ms);
    std::vector<Action> Tick(std::uint64_t now_ms);
    std::vector<Action> PeerDisconnected();
    std::vector<Action> Abort(std::string reason);

    Phase phase() const noexcept { return phase_; }
    const Ticket& ticket() const noexcept { return ticket_; }

private:
    struct Endpoint {
        bool ready = false;
        std::uint32_t scene_id = 0;
        std::uint64_t ready_revision = 0;
        bool ended = false;
        EndState end_state;
    };

    bool active() const noexcept;
    bool accepts(std::uint64_t epoch) const noexcept;
    Action action(ActionType type, EndState state = {},
                  std::string reason = {}) const;
    std::vector<Action> block(std::string reason);
    std::vector<Action> ready(Endpoint& endpoint, const char* endpoint_name,
                              std::uint64_t epoch, std::uint32_t scene_id,
                              std::uint64_t revision, std::uint64_t now_ms);
    std::vector<Action> skip(std::uint64_t epoch, std::uint64_t now_ms);
    std::vector<Action> ended(Endpoint& endpoint, const char* endpoint_name,
                              std::uint64_t epoch, EndState state,
                              std::uint64_t now_ms);
    void append_skip(std::vector<Action>& actions, std::uint64_t now_ms);

    Phase phase_ = Phase::Idle;
    Ticket ticket_;
    Endpoint local_;
    Endpoint peer_;
    std::uint64_t next_epoch_ = 0;
    std::uint64_t prepare_timeout_ms_;
    std::uint64_t ending_timeout_ms_;
    std::uint64_t phase_started_ms_ = 0;
    bool skip_requested_ = false;
    bool skip_sent_ = false;
};

} // namespace coopsync
