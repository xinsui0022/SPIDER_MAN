#include "../src/coordinator.h"

#include <cmath>
#include <cstdint>
#include <functional>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using namespace coopsync;

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void expect_actions(const std::vector<Action>& actual,
                    std::initializer_list<ActionType> expected) {
    require(actual.size() == expected.size(), "Unexpected number of actions");
    std::size_t index = 0;
    for (const auto type : expected) {
        require(actual[index++].type == type, "Unexpected action order or type");
    }
}

void expect_block(const std::vector<Action>& actions,
                  const HostCoordinator& coordinator) {
    expect_actions(actions, {ActionType::BlockPeer, ActionType::BlockLocal});
    require(coordinator.phase() == Phase::Blocked, "Failure must retain Blocked phase");
    require(!actions[0].reason.empty(), "Blocked action needs a reason");
    require(actions[0].reason == actions[1].reason, "Both endpoints need the same reason");
}

Ticket make_ticket() {
    Ticket ticket;
    ticket.epoch = 999; // Must be replaced by the coordinator.
    ticket.world_revision = 12;
    ticket.scene_id = 43;
    ticket.cinematic_id = "intro/elevator";
    ticket.x = 10.25f;
    ticket.y = -2.5f;
    ticket.z = 120;
    return ticket;
}

std::uint64_t prepare(HostCoordinator& coordinator, std::uint64_t now_ms = 0) {
    const auto actions = coordinator.Prepare(make_ticket(), now_ms);
    expect_actions(actions, {ActionType::PreparePeer, ActionType::GatherLocal});
    require(coordinator.phase() == Phase::Preparing, "Prepare must enter Preparing");
    const auto epoch = coordinator.ticket().epoch;
    require(epoch != 0 && epoch != 999, "Host must allocate a nonzero epoch");
    for (const auto& action : actions) {
        require(action.ticket.epoch == epoch, "Both prepare actions need assigned epoch");
        require(action.ticket.scene_id == 43 && action.ticket.world_revision == 12,
                "Prepare actions must preserve scene and revision");
        require(action.ticket.cinematic_id == "intro/elevator" &&
                    action.ticket.x == 10.25f && action.ticket.y == -2.5f &&
                    action.ticket.z == 120,
                "Prepare must preserve cinematic ID and gather coordinates");
    }
    return epoch;
}

std::uint64_t start(HostCoordinator& coordinator, std::uint64_t now_ms = 0,
                    bool peer_first = false) {
    const auto epoch = prepare(coordinator, now_ms);
    if (peer_first) {
        expect_actions(coordinator.PeerReady(epoch, 43, 12, now_ms + 1), {});
        expect_actions(coordinator.LocalReady(epoch, 43, 12, now_ms + 2),
                       {ActionType::StartPeer, ActionType::StartLocal});
    } else {
        expect_actions(coordinator.LocalReady(epoch, 43, 12, now_ms + 1), {});
        expect_actions(coordinator.PeerReady(epoch, 43, 12, now_ms + 2),
                       {ActionType::StartPeer, ActionType::StartLocal});
    }
    require(coordinator.phase() == Phase::Playing, "Both matching Ready events must start");
    return epoch;
}

void test_natural_barrier() {
    for (const auto peer_first : {false, true}) {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator, 100, peer_first);
        const EndState state{13, 0xabc123};
        const auto first = peer_first ? coordinator.PeerEnded(epoch, state, 150)
                                      : coordinator.LocalEnded(epoch, state, 150);
        expect_actions(first, {});
        require(coordinator.phase() == Phase::Ending, "One end report must hold the barrier");
        const auto release = peer_first ? coordinator.LocalEnded(epoch, state, 160)
                                        : coordinator.PeerEnded(epoch, state, 160);
        expect_actions(release, {ActionType::ReleasePeer, ActionType::ReleaseLocal});
        require(coordinator.phase() == Phase::Idle, "Matching end states must release to Idle");
        for (const auto& action : release) {
            require(action.ticket.epoch == epoch && action.end_state.world_revision == 13 &&
                        action.end_state.state_digest == 0xabc123,
                    "Release must carry agreed state and epoch");
        }
        expect_actions(coordinator.LocalEnded(epoch, {14, 88}, 170), {});
        expect_actions(coordinator.PeerReady(epoch, 0, 0, 170), {});
    }
}

void test_prepare_skip_queue() {
    for (const auto peer_skip : {false, true}) {
        HostCoordinator coordinator;
        const auto epoch = prepare(coordinator, 0);
        expect_actions(peer_skip ? coordinator.PeerSkip(epoch, 1)
                                  : coordinator.LocalSkip(epoch, 1), {});
        expect_actions(coordinator.LocalSkip(epoch, 2), {});
        expect_actions(coordinator.PeerSkip(epoch, 3), {});
        require(coordinator.phase() == Phase::Preparing, "Queued Skip cannot bypass Ready");
        expect_actions(coordinator.LocalReady(epoch, 43, 12, 4), {});
        expect_actions(coordinator.PeerReady(epoch, 43, 12, 5),
                       {ActionType::StartPeer, ActionType::StartLocal,
                        ActionType::SkipPeer, ActionType::SkipLocal});
        require(coordinator.phase() == Phase::Ending, "Queued Skip must begin end barrier");
        expect_actions(coordinator.PeerSkip(epoch, 6), {});
        expect_actions(coordinator.LocalSkip(epoch, 7), {});
        expect_actions(coordinator.LocalEnded(epoch, {12, 1}, 8), {});
        expect_actions(coordinator.PeerEnded(epoch, {12, 1}, 9),
                       {ActionType::ReleasePeer, ActionType::ReleaseLocal});
    }
}

void test_either_player_skip_once() {
    for (const auto peer_skip : {false, true}) {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator);
        expect_actions(peer_skip ? coordinator.PeerSkip(epoch, 10)
                                  : coordinator.LocalSkip(epoch, 10),
                       {ActionType::SkipPeer, ActionType::SkipLocal});
        require(coordinator.phase() == Phase::Ending, "Skip must hold input until both finish");
        expect_actions(coordinator.PeerSkip(epoch, 11), {});
        expect_actions(coordinator.LocalSkip(epoch, 12), {});
        expect_actions(coordinator.PeerEnded(epoch, {13, 999}, 13), {});
        expect_actions(coordinator.LocalEnded(epoch, {13, 999}, 14),
                       {ActionType::ReleasePeer, ActionType::ReleaseLocal});
    }
}

void test_skip_does_not_extend_natural_end_deadline() {
    HostCoordinator coordinator(100, 50);
    const auto epoch = start(coordinator);
    expect_actions(coordinator.PeerEnded(epoch, {13, 99}, 10), {});
    expect_actions(coordinator.LocalSkip(epoch, 40), {ActionType::SkipLocal});
    expect_actions(coordinator.PeerSkip(epoch, 59), {});
    expect_block(coordinator.Tick(60), coordinator);
}

void test_skip_only_unfinished_endpoint() {
    for (const auto local_ended_first : {false, true}) {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator);
        const EndState state{13, 99};
        expect_actions(local_ended_first ? coordinator.LocalEnded(epoch, state, 10)
                                         : coordinator.PeerEnded(epoch, state, 10), {});
        if (local_ended_first) {
            expect_actions(coordinator.PeerSkip(epoch, 11), {ActionType::SkipPeer});
        } else {
            expect_actions(coordinator.LocalSkip(epoch, 11), {ActionType::SkipLocal});
        }
        require(coordinator.phase() == Phase::Ending,
                "One completed player plus skip must retain the end barrier");
        expect_actions(coordinator.LocalSkip(epoch, 12), {});
        expect_actions(coordinator.PeerSkip(epoch, 13), {});
        const auto release = local_ended_first ? coordinator.PeerEnded(epoch, state, 14)
                                               : coordinator.LocalEnded(epoch, state, 14);
        expect_actions(release, {ActionType::ReleasePeer, ActionType::ReleaseLocal});
        require(coordinator.phase() == Phase::Idle,
                "The originally ended endpoint must still count toward the barrier");
    }
}

void test_ready_contradictions() {
    for (const auto wrong_scene : {false, true}) {
        HostCoordinator coordinator;
        const auto epoch = prepare(coordinator);
        expect_block(coordinator.PeerReady(epoch, wrong_scene ? 44 : 43,
                                          wrong_scene ? 12 : 13, 1), coordinator);
    }
    {
        HostCoordinator coordinator;
        const auto epoch = prepare(coordinator);
        expect_actions(coordinator.LocalReady(epoch, 43, 12, 1), {});
        expect_actions(coordinator.LocalReady(epoch, 43, 12, 2), {});
        expect_block(coordinator.LocalReady(epoch, 44, 12, 3), coordinator);
    }
    {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator);
        expect_actions(coordinator.PeerReady(epoch, 43, 12, 3), {});
        expect_block(coordinator.PeerReady(epoch, 43, 11, 4), coordinator);
    }
}

void test_end_contradictions() {
    for (const auto wrong_revision : {false, true}) {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator);
        expect_actions(coordinator.LocalEnded(epoch, {13, 100}, 3), {});
        expect_block(coordinator.PeerEnded(epoch,
                                           {wrong_revision ? 14u : 13u,
                                            wrong_revision ? 100u : 101u}, 4), coordinator);
    }
    {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator);
        expect_actions(coordinator.PeerEnded(epoch, {13, 100}, 3), {});
        expect_actions(coordinator.PeerEnded(epoch, {13, 100}, 4), {});
        expect_block(coordinator.PeerEnded(epoch, {13, 101}, 5), coordinator);
    }
    {
        HostCoordinator coordinator;
        const auto epoch = start(coordinator);
        expect_block(coordinator.LocalEnded(epoch, {11, 100}, 3), coordinator);
    }
    {
        HostCoordinator coordinator;
        const auto epoch = prepare(coordinator);
        expect_block(coordinator.PeerEnded(epoch, {12, 100}, 1), coordinator);
    }
}

void test_old_epochs_and_new_session_progress() {
    HostCoordinator coordinator;
    const auto first_epoch = start(coordinator);
    expect_actions(coordinator.LocalEnded(first_epoch, {13, 100}, 3), {});
    expect_actions(coordinator.PeerEnded(first_epoch, {13, 100}, 4),
                   {ActionType::ReleasePeer, ActionType::ReleaseLocal});
    const auto epoch = prepare(coordinator, 5);
    require(epoch == first_epoch + 1, "A successful next cinematic needs a new epoch");
    // Stale messages must neither poison state nor tick the new epoch's deadline.
    expect_actions(coordinator.PeerReady(first_epoch, 0, 0, 1000000), {});
    expect_actions(coordinator.PeerSkip(first_epoch, 1000000), {});
    expect_actions(coordinator.LocalEnded(first_epoch, {0, 0}, 1000000), {});
    expect_actions(coordinator.PeerReady(epoch + 1, 0, 0, 6), {});
    expect_actions(coordinator.LocalReady(0, 0, 0, 6), {});
    require(coordinator.phase() == Phase::Preparing, "Other epochs must have no effect");
    expect_actions(coordinator.LocalReady(epoch, 43, 12, 6), {});
    expect_actions(coordinator.PeerReady(epoch, 43, 12, 7),
                   {ActionType::StartPeer, ActionType::StartLocal});
}

void test_prepare_timeout_boundary_and_late_ready() {
    {
        HostCoordinator coordinator(10, 20);
        const auto epoch = prepare(coordinator, 100);
        expect_actions(coordinator.LocalReady(epoch, 43, 12, 109), {});
        expect_block(coordinator.PeerReady(epoch, 43, 12, 110), coordinator);
    }
    {
        HostCoordinator coordinator(10, 20);
        prepare(coordinator, 100);
        expect_actions(coordinator.Tick(109), {});
        expect_block(coordinator.Tick(110), coordinator);
        expect_actions(coordinator.Tick(111), {});
    }
}

void test_ending_timeout_boundary_and_late_end() {
    {
        HostCoordinator coordinator(10, 20);
        const auto epoch = start(coordinator, 100);
        expect_actions(coordinator.Tick(100000), {});
        require(coordinator.phase() == Phase::Playing, "Playing has no guessed duration timeout");
        expect_actions(coordinator.LocalEnded(epoch, {13, 100}, 100001), {});
        expect_actions(coordinator.Tick(100020), {});
        expect_block(coordinator.PeerEnded(epoch, {13, 100}, 100021), coordinator);
    }
    {
        HostCoordinator coordinator(10, 20);
        const auto epoch = start(coordinator, 100);
        expect_actions(coordinator.LocalSkip(epoch, 110),
                       {ActionType::SkipPeer, ActionType::SkipLocal});
        expect_actions(coordinator.Tick(129), {});
        expect_block(coordinator.PeerSkip(epoch, 130), coordinator);
    }
}

void test_skip_queue_keeps_preparation_timeout() {
    HostCoordinator coordinator(10, 20);
    const auto epoch = prepare(coordinator, 100);
    expect_actions(coordinator.PeerSkip(epoch, 109), {});
    expect_block(coordinator.Tick(110), coordinator);
}

void test_near_clock_limit() {
    HostCoordinator coordinator(10, 20);
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    prepare(coordinator, maximum - 15);
    expect_actions(coordinator.Tick(maximum - 6), {});
    expect_block(coordinator.Tick(maximum - 5), coordinator);
}

void test_disconnect_and_blocked_latch() {
    {
        HostCoordinator idle;
        expect_actions(idle.PeerDisconnected(), {});
        require(idle.phase() == Phase::Idle, "Disconnect while idle is harmless");
    }
    for (const auto phase : {Phase::Preparing, Phase::Playing, Phase::Ending}) {
        HostCoordinator coordinator;
        const auto epoch = phase == Phase::Preparing ? prepare(coordinator)
                                                     : start(coordinator);
        if (phase == Phase::Ending) {
            expect_actions(coordinator.LocalEnded(epoch, {13, 100}, 3), {});
        }
        expect_block(coordinator.PeerDisconnected(), coordinator);
        expect_actions(coordinator.Prepare(make_ticket(), 4), {});
        expect_actions(coordinator.LocalReady(epoch, 43, 12, 4), {});
        expect_actions(coordinator.PeerSkip(epoch, 4), {});
        expect_actions(coordinator.PeerEnded(epoch, {13, 100}, 4), {});
        expect_actions(coordinator.Abort("again"), {});
        expect_actions(coordinator.PeerDisconnected(), {});
        require(coordinator.phase() == Phase::Blocked, "Blocked cannot auto-recover");
    }
}

void test_abort_reasons_and_active_prepare_rejected() {
    HostCoordinator coordinator;
    expect_actions(coordinator.Abort("idle"), {});
    const auto epoch = prepare(coordinator);
    auto conflicting = make_ticket();
    conflicting.cinematic_id = "another";
    expect_actions(coordinator.Prepare(conflicting, 1), {});
    require(coordinator.ticket().epoch == epoch &&
                coordinator.ticket().cinematic_id == "intro/elevator",
            "A new Prepare must not replace an active ticket");
    auto actions = coordinator.Abort(std::string(300, 'x'));
    expect_block(actions, coordinator);
    require(actions[0].reason.size() == 256, "Abort reason must fit the wire bound");
    HostCoordinator other;
    prepare(other);
    actions = other.Abort("");
    expect_block(actions, other);
}

void test_invalid_tickets_do_not_consume_epoch() {
    std::vector<Ticket> invalid;
    auto ticket = make_ticket();
    ticket.cinematic_id.clear();
    invalid.push_back(ticket);
    ticket = make_ticket();
    ticket.cinematic_id.assign(129, 'x');
    invalid.push_back(ticket);
    ticket = make_ticket();
    ticket.x = std::numeric_limits<float>::quiet_NaN();
    invalid.push_back(ticket);
    ticket = make_ticket();
    ticket.y = std::numeric_limits<float>::infinity();
    invalid.push_back(ticket);
    ticket = make_ticket();
    ticket.z = -std::numeric_limits<float>::infinity();
    invalid.push_back(ticket);
    HostCoordinator coordinator;
    for (const auto& value : invalid) {
        bool threw = false;
        try {
            coordinator.Prepare(value, 0);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        require(threw && coordinator.phase() == Phase::Idle &&
                    coordinator.ticket().epoch == 0,
                "Invalid input must be rejected without allocating an epoch");
    }
    ticket = make_ticket();
    ticket.cinematic_id.assign(128, 'x');
    ticket.scene_id = 0;
    ticket.world_revision = 0;
    expect_actions(coordinator.Prepare(ticket, 1),
                   {ActionType::PreparePeer, ActionType::GatherLocal});
    require(coordinator.ticket().epoch == 1, "Rejected tickets cannot leave gaps in epochs");
}

void test_timeout_configuration() {
    for (const auto prepare_zero : {false, true}) {
        bool threw = false;
        try {
            HostCoordinator coordinator(prepare_zero ? 0 : 10,
                                        prepare_zero ? 10 : 0);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        require(threw, "Zero timeout must be rejected");
    }
}

} // namespace

int main() {
    const std::vector<std::pair<const char*, std::function<void()>>> tests{
        {"natural completion barrier", test_natural_barrier},
        {"skip queued until both ready", test_prepare_skip_queue},
        {"either player skips exactly once", test_either_player_skip_once},
        {"skip preserves natural ending deadline", test_skip_does_not_extend_natural_end_deadline},
        {"skip targets only unfinished endpoint", test_skip_only_unfinished_endpoint},
        {"ready contradictions", test_ready_contradictions},
        {"end-state contradictions", test_end_contradictions},
        {"old epochs and next cinematic", test_old_epochs_and_new_session_progress},
        {"prepare timeout and late readiness", test_prepare_timeout_boundary_and_late_ready},
        {"ending timeout and late completion", test_ending_timeout_boundary_and_late_end},
        {"queued skip preserves prepare deadline", test_skip_queue_keeps_preparation_timeout},
        {"clock near uint64 limit", test_near_clock_limit},
        {"disconnect and blocked latch", test_disconnect_and_blocked_latch},
        {"abort reasons and active prepare rejection", test_abort_reasons_and_active_prepare_rejected},
        {"invalid tickets preserve epoch", test_invalid_tickets_do_not_consume_epoch},
        {"timeout configuration", test_timeout_configuration},
    };
    std::size_t passed = 0;
    for (const auto& test : tests) {
        try {
            test.second();
            std::cout << "PASS: " << test.first << '\n';
            ++passed;
        } catch (const std::exception& error) {
            std::cerr << "FAIL: " << test.first << ": " << error.what() << '\n';
            return 1;
        }
    }
    std::cout << passed << " coordinator tests passed\n";
    return 0;
}
