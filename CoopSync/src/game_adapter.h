#pragma once

#include "coordinator.h"

#include <cstdint>
#include <string>
#include <vector>

namespace coopsync {

enum class BackendKind { Unverified, VerifiedGame, FakeForTests };
enum class AdapterMode { RequireVerifiedGame, OfflineFakeTest };
enum class NativeCinematicPhase { Preparing, Playing, Ended };
enum class GameOperation { GatherAndHold, Start, Skip, Release };
enum class AdapterEventType { Ready, Ended, Blocked };

enum WorldCoverage : std::uint32_t {
    TaskCoverage = 1u << 0,
    SceneCoverage = 1u << 1,
    DoorCoverage = 1u << 2,
    CollisionCoverage = 1u << 3,
    EnemyCoverage = 1u << 4
};

// Required coverage is the current scene scope, not the entire game world.
constexpr std::uint32_t kRequiredSceneCoverage =
    TaskCoverage | SceneCoverage | DoorCoverage | CollisionCoverage | EnemyCoverage;

// Instance tokens identify one live native scene/trigger invocation. They are
// opaque values, not addresses for this library to dereference. epoch belongs
// to the backend's verified binding, not a field assumed to exist in the game.
struct RuntimeIdentity {
    std::uint64_t epoch = 0;
    std::uint64_t scene_instance = 0;
    std::uint64_t cinematic_instance = 0;
    std::uint32_t scene_id = 0;
    std::string cinematic_id;
};

struct GameObservation {
    BackendKind source = BackendKind::Unverified;
    RuntimeIdentity identity;
    NativeCinematicPhase phase = NativeCinematicPhase::Preparing;
    std::uint64_t world_revision = 0;
    bool scene_loaded = false;
    bool collision_ready = false;
    // Must describe the actual local player, not just the target scene handle.
    std::uint64_t player_scene_instance = 0;
    bool player_at_gather_point = false;
    bool task_settled = false;
    bool world_scope_verified = false;
    std::uint32_t world_coverage = 0;
    std::uint64_t state_digest = 0;
};

struct AdapterEvent {
    AdapterEventType type = AdapterEventType::Blocked;
    std::uint64_t epoch = 0;
    std::uint32_t scene_id = 0;
    std::uint64_t revision = 0;
    EndState end_state;
    std::string reason;
};

// No real game backend is shipped. A future implementation must obtain native
// evidence, hold the preparation/end barriers, and recheck expected_identity
// atomically on the game thread before each operation. Observe may use ticket
// to select a verified binding; copying ticket into fabricated evidence is invalid.
class IGameBackend {
public:
    virtual ~IGameBackend() = default;
    virtual BackendKind kind() const noexcept = 0;
    virtual GameObservation Observe(const Ticket& ticket) = 0;
    virtual bool Execute(GameOperation operation, const Ticket& ticket,
                         const RuntimeIdentity& expected_identity) = 0;
};

// A checked local bridge between HostCoordinator actions/events and a backend.
// Remote actions remain the transport's responsibility. The caller must Abort
// the coordinator when the bridge emits Blocked; the bridge never auto-recovers.
class GameAdapterBridge {
public:
    explicit GameAdapterBridge(IGameBackend& backend,
                              AdapterMode mode = AdapterMode::RequireVerifiedGame);

    std::vector<AdapterEvent> Apply(const Action& action);
    std::vector<AdapterEvent> Poll();

    bool blocked() const noexcept { return blocked_; }
    bool active() const noexcept { return active_; }
    bool uses_fake_backend() const noexcept { return mode_ == AdapterMode::OfflineFakeTest; }

private:
    std::vector<AdapterEvent> block(std::string reason);
    GameObservation observe_checked();
    bool matches_identity(const RuntimeIdentity& identity) const noexcept;
    bool ready_evidence(const GameObservation& observation) const noexcept;
    bool end_evidence(const GameObservation& observation) const noexcept;
    std::vector<AdapterEvent> consume(const GameObservation& observation);
    std::vector<AdapterEvent> apply_local(const Action& action);

    IGameBackend& backend_;
    AdapterMode mode_;
    BackendKind expected_kind_;
    Ticket ticket_;
    RuntimeIdentity identity_;
    EndState final_state_;
    std::uint64_t last_epoch_ = 0;
    bool active_ = false;
    bool blocked_ = false;
    bool gathered_ = false;
    bool ready_reported_ = false;
    bool started_ = false;
    bool skip_sent_ = false;
    bool ended_reported_ = false;
};

} // namespace coopsync
