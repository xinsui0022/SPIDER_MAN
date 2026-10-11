#include "../src/game_adapter.h"

#include <algorithm>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace coopsync;

namespace {

void require(bool value, const std::string& message) {
    if (!value) {
        throw std::runtime_error(message);
    }
}

void expect_event(const std::vector<AdapterEvent>& events, AdapterEventType type) {
    require(events.size() == 1 && events[0].type == type, "Expected exactly one adapter event");
    if (type == AdapterEventType::Blocked) {
        require(!events[0].reason.empty(), "Blocked requires a reason");
    }
}

Ticket ticket(std::uint64_t epoch = 1) {
    return Ticket{epoch, 12, 43, "fake_test_intro", 10, 20, 30};
}

Action action(ActionType type, const Ticket& current = ticket(), EndState state = {}) {
    return Action{type, current, state, {}};
}

bool equal_identity(const RuntimeIdentity& left, const RuntimeIdentity& right) {
    return left.epoch == right.epoch && left.scene_instance == right.scene_instance &&
           left.cinematic_instance == right.cinematic_instance &&
           left.scene_id == right.scene_id && left.cinematic_id == right.cinematic_id;
}

// OFFLINE FAKE ONLY: these flags and tokens are test fixtures. No game process,
// native address, real world snapshot, or multiplayer world is accessed.
class FakeGameBackend final : public IGameBackend {
public:
    BackendKind reported_kind = BackendKind::FakeForTests;
    GameObservation observation;
    std::vector<GameOperation> operations;
    std::function<void()> before_execute;
    bool held = false;
    bool skip_completes = false;
    bool throw_observe = false;
    bool reject_execute = false;

    BackendKind kind() const noexcept override { return reported_kind; }

    void BindFixture(const Ticket& current, std::uint64_t instance_offset = 0) {
        observation = {};
        observation.source = BackendKind::FakeForTests;
        observation.identity = {current.epoch, 1000 + instance_offset,
                                2000 + instance_offset, current.scene_id,
                                current.cinematic_id};
        observation.world_revision = current.world_revision;
        observation.scene_loaded = true;
        observation.collision_ready = true;
        observation.player_scene_instance = observation.identity.scene_instance;
        observation.player_at_gather_point = true;
        held = false;
    }

    void CompleteFixture(bool settled = true) {
        observation.phase = NativeCinematicPhase::Ended;
        observation.world_revision = 13;
        observation.task_settled = settled;
        observation.world_scope_verified = true;
        observation.world_coverage = kRequiredSceneCoverage;
        observation.state_digest = 0xf00d;
    }

    GameObservation Observe(const Ticket&) override {
        if (throw_observe) {
            throw std::runtime_error("OFFLINE_FAKE observe failure");
        }
        return observation;
    }

    bool Execute(GameOperation operation, const Ticket& current,
                 const RuntimeIdentity& expected) override {
        if (before_execute) {
            before_execute();
        }
        // Test the mandatory second check at execution time, including a race
        // after the bridge's preflight observation.
        if (reject_execute || !equal_identity(expected, observation.identity) ||
            current.epoch != observation.identity.epoch) {
            return false;
        }
        operations.push_back(operation);
        switch (operation) {
        case GameOperation::GatherAndHold: held = true; break;
        case GameOperation::Start: observation.phase = NativeCinematicPhase::Playing; break;
        case GameOperation::Skip: if (skip_completes) CompleteFixture(); break;
        case GameOperation::Release: held = false; break;
        }
        return true;
    }

    std::size_t count(GameOperation operation) const {
        return static_cast<std::size_t>(std::count(operations.begin(), operations.end(), operation));
    }
};

void prepare(FakeGameBackend& backend, GameAdapterBridge& bridge) {
    backend.BindFixture(ticket());
    const auto events = bridge.Apply(action(ActionType::GatherLocal));
    expect_event(events, AdapterEventType::Ready);
    require(events[0].epoch == 1 && events[0].scene_id == 43 && events[0].revision == 12,
            "Ready must report the bound scene and revision");
    require(backend.held && bridge.active() && bridge.uses_fake_backend(),
            "Fake preparation must hold the test barrier and remain labelled fake");
}

void start(FakeGameBackend& backend, GameAdapterBridge& bridge) {
    prepare(backend, bridge);
    require(bridge.Apply(action(ActionType::StartLocal)).empty(), "Playing is not an end report");
    require(backend.count(GameOperation::Start) == 1, "Native Start must execute once");
}

void test_backend_modes() {
    FakeGameBackend fake;
    bool rejected = false;
    try { GameAdapterBridge bridge(fake); }
    catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "Default mode must reject a fake backend");
    fake.reported_kind = BackendKind::Unverified;
    rejected = false;
    try { GameAdapterBridge bridge(fake, AdapterMode::OfflineFakeTest); }
    catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "Offline mode must also reject an unverified backend");
}

void test_prepare_requires_loading_collision_and_actual_player() {
    for (int missing = 0; missing < 4; ++missing) {
        FakeGameBackend backend;
        backend.BindFixture(ticket());
        if (missing == 0) backend.observation.scene_loaded = false;
        if (missing == 1) backend.observation.collision_ready = false;
        if (missing == 2) backend.observation.player_scene_instance = 123;
        if (missing == 3) backend.observation.player_at_gather_point = false;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        require(bridge.Apply(action(ActionType::GatherLocal)).empty(),
                "Missing preparation evidence must not emit Ready");
        require(backend.count(GameOperation::GatherAndHold) == 1, "Gather must be issued once");
        backend.observation.scene_loaded = backend.observation.collision_ready = true;
        backend.observation.player_scene_instance = backend.observation.identity.scene_instance;
        backend.observation.player_at_gather_point = true;
        expect_event(bridge.Poll(), AdapterEventType::Ready);
        require(bridge.Poll().empty(), "Ready must be emitted once");
        require(bridge.Apply(action(ActionType::GatherLocal)).empty(), "Duplicate gather is idempotent");
        require(backend.count(GameOperation::GatherAndHold) == 1, "Duplicate gather must not move the player again");
    }
}

void test_wrong_identity_never_executes_gather() {
    for (int invalid = 0; invalid < 7; ++invalid) {
        FakeGameBackend backend;
        backend.BindFixture(ticket());
        if (invalid == 0) ++backend.observation.identity.epoch;
        if (invalid == 1) ++backend.observation.identity.scene_id;
        if (invalid == 2) backend.observation.identity.cinematic_id = "another";
        if (invalid == 3) backend.observation.identity.scene_instance = 0;
        if (invalid == 4) backend.observation.identity.cinematic_instance = 0;
        if (invalid == 5) backend.observation.source = BackendKind::Unverified;
        if (invalid == 6) ++backend.observation.world_revision;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        expect_event(bridge.Apply(action(ActionType::GatherLocal)), AdapterEventType::Blocked);
        require(backend.operations.empty() && bridge.blocked(),
                "Invalid binding cannot execute a native operation");
    }
}

void test_start_requires_current_ready_and_instance() {
    for (int invalid = 0; invalid < 4; ++invalid) {
        FakeGameBackend backend;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        if (invalid == 0) {
            backend.BindFixture(ticket());
            backend.observation.scene_loaded = false;
            require(bridge.Apply(action(ActionType::GatherLocal)).empty(), "No loaded scene means no Ready");
        } else {
            prepare(backend, bridge);
            if (invalid == 1) backend.observation.collision_ready = false;
            if (invalid == 2) ++backend.observation.identity.cinematic_instance;
            if (invalid == 3) backend.observation.phase = NativeCinematicPhase::Playing;
        }
        expect_event(bridge.Apply(action(ActionType::StartLocal)), AdapterEventType::Blocked);
        require(backend.count(GameOperation::Start) == 0, "Invalid readiness cannot start native playback");
    }
}

void test_atomic_execution_recheck() {
    FakeGameBackend backend;
    GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
    prepare(backend, bridge);
    backend.before_execute = [&backend] { ++backend.observation.identity.cinematic_instance; };
    expect_event(bridge.Apply(action(ActionType::StartLocal)), AdapterEventType::Blocked);
    require(backend.count(GameOperation::Start) == 0,
            "A native instance change between observation and execution must reject the command");
}

void test_skip_once_and_never_after_end() {
    FakeGameBackend backend;
    GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
    start(backend, bridge);
    require(bridge.Apply(action(ActionType::SkipLocal)).empty(), "A pending native skip is not a completed task");
    require(bridge.Apply(action(ActionType::SkipLocal)).empty(), "Duplicate skip must be idempotent");
    require(backend.count(GameOperation::Skip) == 1, "Native Skip executes once");
    backend.CompleteFixture();
    expect_event(bridge.Poll(), AdapterEventType::Ended);
    require(bridge.Apply(action(ActionType::SkipLocal)).empty(), "Ended endpoints ignore Skip");
    require(backend.count(GameOperation::Skip) == 1, "Already completed endpoint must not receive another native Skip");
}

void test_native_end_before_poll_does_not_receive_skip() {
    FakeGameBackend backend;
    GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
    start(backend, bridge);
    backend.CompleteFixture(false);
    require(bridge.Apply(action(ActionType::SkipLocal)).empty(), "Unsettled native end must wait for task settlement");
    require(backend.count(GameOperation::Skip) == 0, "Even an unpolled native end must not receive Skip");
    backend.observation.task_settled = true;
    expect_event(bridge.Apply(action(ActionType::SkipLocal)), AdapterEventType::Ended);
    require(backend.count(GameOperation::Skip) == 0, "Completed native endpoint only emits its end report");
}

void test_task_digest_is_not_full_scene_evidence() {
    for (int missing = 0; missing < 7; ++missing) {
        FakeGameBackend backend;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        start(backend, bridge);
        backend.CompleteFixture();
        if (missing < 5) backend.observation.world_coverage &= ~(1u << missing);
        if (missing == 5) backend.observation.world_scope_verified = false;
        if (missing == 6) backend.observation.collision_ready = false;
        expect_event(bridge.Poll(), AdapterEventType::Blocked);
        require(backend.held && backend.count(GameOperation::Release) == 0,
                "Incomplete world evidence must retain the barrier");
    }
}

void test_end_report_and_release_consistency() {
    FakeGameBackend backend;
    GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
    start(backend, bridge);
    backend.CompleteFixture(false);
    require(bridge.Poll().empty(), "Native End alone cannot settle a task");
    backend.observation.task_settled = true;
    const auto ended = bridge.Poll();
    expect_event(ended, AdapterEventType::Ended);
    require(ended[0].end_state.world_revision == 13 && ended[0].end_state.state_digest == 0xf00d,
            "End report must contain the verified-scope test snapshot");
    require(bridge.Poll().empty(), "End must be reported once");
    require(bridge.Apply(action(ActionType::ReleaseLocal, ticket(), ended[0].end_state)).empty(),
            "Matching release should succeed");
    require(!bridge.active() && !backend.held && backend.count(GameOperation::Release) == 1,
            "Only matching release may drop the native barrier");
    require(bridge.Apply(action(ActionType::ReleaseLocal, ticket(), ended[0].end_state)).empty(),
            "Repeated completed release is stale");
    require(backend.count(GameOperation::Release) == 1, "Repeated release must not repeat the native operation");
}

void test_early_wrong_or_changed_release_is_blocked() {
    for (int invalid = 0; invalid < 3; ++invalid) {
        FakeGameBackend backend;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        start(backend, bridge);
        EndState state{13, 0xf00d};
        if (invalid != 0) {
            backend.CompleteFixture();
            expect_event(bridge.Poll(), AdapterEventType::Ended);
            if (invalid == 1) ++state.state_digest;
            if (invalid == 2) ++backend.observation.state_digest;
        }
        expect_event(bridge.Apply(action(ActionType::ReleaseLocal, ticket(), state)), AdapterEventType::Blocked);
        require(backend.held && backend.count(GameOperation::Release) == 0,
                "Early, mismatched, or changed-state release cannot resume gameplay");
    }
}

void test_old_epochs_and_conflicting_ticket() {
    FakeGameBackend backend;
    GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
    start(backend, bridge);
    require(bridge.Apply(action(ActionType::SkipLocal, ticket(0))).empty(), "Old epoch has no effect");
    require(backend.count(GameOperation::Skip) == 0, "Old epoch cannot invoke a native operation");
    auto wrong = ticket();
    ++wrong.x;
    expect_event(bridge.Apply(action(ActionType::StartLocal, wrong)), AdapterEventType::Blocked);
    require(backend.count(GameOperation::Start) == 1, "Conflicting ticket cannot start another operation");
    require(bridge.Apply(action(ActionType::GatherLocal, ticket(2))).empty(), "Blocked cannot recover through a new epoch");
    require(backend.count(GameOperation::GatherAndHold) == 1, "Blocked adapter must be rebuilt only after verification");
}

void test_backend_errors_and_wrong_action_direction() {
    {
        FakeGameBackend backend;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        prepare(backend, bridge);
        backend.throw_observe = true;
        expect_event(bridge.Poll(), AdapterEventType::Blocked);
        require(bridge.Poll().empty(), "Blocked event emits once");
    }
    {
        FakeGameBackend backend;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        prepare(backend, bridge);
        backend.reject_execute = true;
        expect_event(bridge.Apply(action(ActionType::StartLocal)), AdapterEventType::Blocked);
        require(backend.count(GameOperation::Start) == 0, "Backend rejection cannot count as native success");
    }
    {
        FakeGameBackend backend;
        GameAdapterBridge bridge(backend, AdapterMode::OfflineFakeTest);
        expect_event(bridge.Apply(action(ActionType::StartPeer)), AdapterEventType::Blocked);
        require(backend.operations.empty(), "A remote action must not be locally executed");
    }
}

// In-process integration only. Distinct native instance tokens on each fake
// endpoint deliberately prove that network ticket identity is not a pointer.
struct FakeTwoEndpointSession {
    HostCoordinator coordinator;
    FakeGameBackend local, peer;
    GameAdapterBridge local_bridge{local, AdapterMode::OfflineFakeTest};
    GameAdapterBridge peer_bridge{peer, AdapterMode::OfflineFakeTest};
    std::uint64_t now = 0;

    void Events(bool is_peer, const std::vector<AdapterEvent>& events) {
        for (const auto& event : events) {
            if (event.type == AdapterEventType::Ready) {
                Dispatch(is_peer ? coordinator.PeerReady(event.epoch, event.scene_id, event.revision, ++now)
                                 : coordinator.LocalReady(event.epoch, event.scene_id, event.revision, ++now));
            } else if (event.type == AdapterEventType::Ended) {
                Dispatch(is_peer ? coordinator.PeerEnded(event.epoch, event.end_state, ++now)
                                 : coordinator.LocalEnded(event.epoch, event.end_state, ++now));
            } else {
                Dispatch(coordinator.Abort(event.reason));
            }
        }
    }

    void Dispatch(const std::vector<Action>& actions) {
        for (auto current : actions) {
            bool is_peer = false;
            switch (current.type) {
            case ActionType::PreparePeer: current.type = ActionType::GatherLocal; is_peer = true; break;
            case ActionType::StartPeer: current.type = ActionType::StartLocal; is_peer = true; break;
            case ActionType::SkipPeer: current.type = ActionType::SkipLocal; is_peer = true; break;
            case ActionType::ReleasePeer: current.type = ActionType::ReleaseLocal; is_peer = true; break;
            case ActionType::BlockPeer: current.type = ActionType::BlockLocal; is_peer = true; break;
            default: break;
            }
            Events(is_peer, is_peer ? peer_bridge.Apply(current) : local_bridge.Apply(current));
        }
    }

    void Begin() {
        const auto actions = coordinator.Prepare(ticket(), ++now);
        local.BindFixture(coordinator.ticket());
        peer.BindFixture(coordinator.ticket(), 7);
        Dispatch(actions);
        require(coordinator.phase() == Phase::Playing, "Two real bridge APIs must satisfy the fake readiness barrier");
    }
};

void test_fake_two_endpoint_coordinator_integration() {
    for (int finish = 0; finish < 5; ++finish) {
        FakeTwoEndpointSession session;
        session.Begin();
        const auto epoch = session.coordinator.ticket().epoch;
        if (finish == 0) {
            session.local.CompleteFixture();
            session.Events(false, session.local_bridge.Poll());
            require(session.coordinator.phase() == Phase::Ending && session.local.held && session.peer.held,
                    "One end report cannot release either fake player");
            session.peer.CompleteFixture();
            session.Events(true, session.peer_bridge.Poll());
        } else if (finish < 3) {
            session.local.skip_completes = session.peer.skip_completes = true;
            session.Dispatch(finish == 1 ? session.coordinator.LocalSkip(epoch, ++session.now)
                                        : session.coordinator.PeerSkip(epoch, ++session.now));
            require(session.local.count(GameOperation::Skip) == 1 && session.peer.count(GameOperation::Skip) == 1,
                    "Either initiating player must skip both unfinished fake endpoints exactly once");
        } else if (finish == 3) {
            session.local.CompleteFixture();
            session.Events(false, session.local_bridge.Poll());
            session.peer.skip_completes = true;
            session.Dispatch(session.coordinator.PeerSkip(epoch, ++session.now));
            require(session.local.count(GameOperation::Skip) == 0 && session.peer.count(GameOperation::Skip) == 1,
                    "Peer skip must not invoke native Skip on the already completed local player");
        } else {
            session.peer.CompleteFixture();
            session.Events(true, session.peer_bridge.Poll());
            session.local.skip_completes = true;
            session.Dispatch(session.coordinator.LocalSkip(epoch, ++session.now));
            require(session.local.count(GameOperation::Skip) == 1 && session.peer.count(GameOperation::Skip) == 0,
                    "Local skip must not invoke native Skip on the already completed peer");
        }
        require(session.coordinator.phase() == Phase::Idle &&
                    !session.local_bridge.active() && !session.peer_bridge.active() &&
                    !session.local.held && !session.peer.held,
                "Matching fake end snapshots must release both checked bridges");
    }
}

void test_fake_adapter_failure_blocks_coordinator_and_both_barriers() {
    FakeTwoEndpointSession session;
    session.Begin();
    session.local.CompleteFixture();
    session.local.observation.world_coverage = TaskCoverage;
    session.Events(false, session.local_bridge.Poll());
    require(session.coordinator.phase() == Phase::Blocked &&
                session.local_bridge.blocked() && session.peer_bridge.blocked(),
            "A task-only end report must block the coordinator and both checked endpoints");
    require(session.local.held && session.peer.held &&
                session.local.count(GameOperation::Release) == 0 &&
                session.peer.count(GameOperation::Release) == 0,
            "Unverified world scope cannot release either endpoint");
}

} // namespace

int main() {
    const std::vector<std::pair<const char*, std::function<void()>>> tests{
        {"backend mode isolation", test_backend_modes},
        {"preparation evidence", test_prepare_requires_loading_collision_and_actual_player},
        {"binding identity rejection", test_wrong_identity_never_executes_gather},
        {"start preflight checks", test_start_requires_current_ready_and_instance},
        {"atomic backend execution recheck", test_atomic_execution_recheck},
        {"skip idempotence", test_skip_once_and_never_after_end},
        {"unpolled native end skip race", test_native_end_before_poll_does_not_receive_skip},
        {"task digest is not world coverage", test_task_digest_is_not_full_scene_evidence},
        {"settled end and matching release", test_end_report_and_release_consistency},
        {"release safety", test_early_wrong_or_changed_release_is_blocked},
        {"old epochs and ticket conflict", test_old_epochs_and_conflicting_ticket},
        {"errors and action direction", test_backend_errors_and_wrong_action_direction},
        {"two fake bridges with host coordinator", test_fake_two_endpoint_coordinator_integration},
        {"fake adapter failure blocks both barriers", test_fake_adapter_failure_blocks_coordinator_and_both_barriers},
    };
    for (const auto& test : tests) {
        try {
            test.second();
            std::cout << "PASS OFFLINE_FAKE_ONLY: " << test.first << '\n';
        } catch (const std::exception& error) {
            std::cerr << "FAIL OFFLINE_FAKE_ONLY: " << test.first << ": " << error.what() << '\n';
            return 1;
        }
    }
    std::cout << tests.size() << " offline fake adapter tests passed; no real game integration verified\n";
    return 0;
}
