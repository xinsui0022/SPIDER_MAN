#include "game_adapter.h"

#include <cmath>
#include <stdexcept>
#include <utility>

namespace coopsync {
namespace {

bool same_ticket(const Ticket& left, const Ticket& right) noexcept {
    return left.epoch == right.epoch &&
           left.world_revision == right.world_revision &&
           left.scene_id == right.scene_id &&
           left.cinematic_id == right.cinematic_id &&
           left.x == right.x && left.y == right.y && left.z == right.z;
}

bool valid_ticket(const Ticket& ticket) noexcept {
    return ticket.epoch != 0 && !ticket.cinematic_id.empty() &&
           ticket.cinematic_id.size() <= 128 && std::isfinite(ticket.x) &&
           std::isfinite(ticket.y) && std::isfinite(ticket.z);
}

bool same_state(const EndState& left, const EndState& right) noexcept {
    return left.world_revision == right.world_revision &&
           left.state_digest == right.state_digest;
}

bool local_action(ActionType type) noexcept {
    return type == ActionType::GatherLocal || type == ActionType::StartLocal ||
           type == ActionType::SkipLocal || type == ActionType::ReleaseLocal ||
           type == ActionType::BlockLocal;
}

} // namespace

GameAdapterBridge::GameAdapterBridge(IGameBackend& backend, AdapterMode mode)
    : backend_(backend), mode_(mode),
      expected_kind_(mode == AdapterMode::OfflineFakeTest ? BackendKind::FakeForTests
                                                         : BackendKind::VerifiedGame) {
    if (backend.kind() != expected_kind_) {
        throw std::invalid_argument("A verified game backend is required; fake tests need explicit OfflineFakeTest mode");
    }
}

std::vector<AdapterEvent> GameAdapterBridge::block(std::string reason) {
    if (blocked_) {
        return {};
    }
    blocked_ = true;
    if (reason.empty()) {
        reason = "Game adapter blocked";
    }
    if (reason.size() > 256) {
        reason.resize(256);
    }
    AdapterEvent event;
    event.type = AdapterEventType::Blocked;
    event.epoch = ticket_.epoch;
    event.scene_id = ticket_.scene_id;
    event.revision = ticket_.world_revision;
    event.reason = std::move(reason);
    return {std::move(event)};
}

bool GameAdapterBridge::matches_identity(const RuntimeIdentity& identity) const noexcept {
    return identity.epoch == ticket_.epoch && identity.scene_id == ticket_.scene_id &&
           identity.cinematic_id == ticket_.cinematic_id && identity.scene_instance != 0 &&
           identity.cinematic_instance != 0 &&
           (!gathered_ || (identity.scene_instance == identity_.scene_instance &&
                          identity.cinematic_instance == identity_.cinematic_instance));
}

GameObservation GameAdapterBridge::observe_checked() {
    if (backend_.kind() != expected_kind_) {
        throw std::runtime_error("Backend kind changed during an active session");
    }
    auto observation = backend_.Observe(ticket_);
    if (observation.source != expected_kind_) {
        throw std::runtime_error("Unverified or incorrectly labelled game observation");
    }
    if (!matches_identity(observation.identity)) {
        throw std::runtime_error("Game observation belongs to another scene, cinematic instance, or epoch");
    }
    if (observation.phase != NativeCinematicPhase::Preparing &&
        observation.phase != NativeCinematicPhase::Playing &&
        observation.phase != NativeCinematicPhase::Ended) {
        throw std::runtime_error("Game observation has an unknown cinematic phase");
    }
    if (observation.world_revision < ticket_.world_revision) {
        throw std::runtime_error("Game observation regressed the authoritative world revision");
    }
    return observation;
}

bool GameAdapterBridge::ready_evidence(const GameObservation& observation) const noexcept {
    return observation.phase == NativeCinematicPhase::Preparing &&
           observation.world_revision == ticket_.world_revision &&
           observation.scene_loaded && observation.collision_ready &&
           observation.player_scene_instance == observation.identity.scene_instance &&
           observation.player_at_gather_point;
}

bool GameAdapterBridge::end_evidence(const GameObservation& observation) const noexcept {
    return observation.phase == NativeCinematicPhase::Ended && observation.task_settled &&
           observation.scene_loaded && observation.collision_ready &&
           observation.player_scene_instance == observation.identity.scene_instance &&
           observation.world_scope_verified &&
           (observation.world_coverage & kRequiredSceneCoverage) == kRequiredSceneCoverage;
}

std::vector<AdapterEvent> GameAdapterBridge::consume(const GameObservation& observation) {
    if (!started_) {
        if (observation.phase != NativeCinematicPhase::Preparing) {
            return block("Native cinematic advanced before the coordinated Start action");
        }
        if (observation.world_revision != ticket_.world_revision) {
            return block("World revision changed during the preparation barrier");
        }
        if (ready_reported_ && !ready_evidence(observation)) {
            return block("Prepared scene lost its loading, collision, or gather evidence");
        }
        if (!ready_reported_ && ready_evidence(observation)) {
            ready_reported_ = true;
            AdapterEvent event;
            event.type = AdapterEventType::Ready;
            event.epoch = ticket_.epoch;
            event.scene_id = ticket_.scene_id;
            event.revision = observation.world_revision;
            return {event};
        }
        return {};
    }
    if (ended_reported_) {
        if (!end_evidence(observation) ||
            !same_state(final_state_, {observation.world_revision, observation.state_digest})) {
            return block("Reported cinematic end state changed before release");
        }
        return {};
    }
    if (observation.phase == NativeCinematicPhase::Preparing) {
        return block("Native Start did not enter the bound cinematic instance");
    }
    if (observation.phase != NativeCinematicPhase::Ended || !observation.task_settled) {
        return {};
    }
    if (!end_evidence(observation)) {
        return block("Task completion alone is insufficient: verified scene, doors, collision, and enemies are required");
    }
    ended_reported_ = true;
    final_state_ = {observation.world_revision, observation.state_digest};
    AdapterEvent event;
    event.type = AdapterEventType::Ended;
    event.epoch = ticket_.epoch;
    event.scene_id = ticket_.scene_id;
    event.revision = observation.world_revision;
    event.end_state = final_state_;
    return {event};
}

std::vector<AdapterEvent> GameAdapterBridge::Poll() {
    if (!active_ || blocked_) {
        return {};
    }
    try {
        return consume(observe_checked());
    } catch (const std::exception& error) {
        return block(error.what());
    }
}

std::vector<AdapterEvent> GameAdapterBridge::apply_local(const Action& action) {
    if (!local_action(action.type)) {
        return block("A remote action was incorrectly forwarded to the local game adapter");
    }
    if (action.type == ActionType::GatherLocal) {
        if (action.ticket.epoch < last_epoch_ ||
            (!active_ && action.ticket.epoch == last_epoch_ && last_epoch_ != 0)) {
            return {};
        }
        if (active_) {
            if (action.ticket.epoch != ticket_.epoch || !same_ticket(action.ticket, ticket_)) {
                return block("A new or conflicting gather arrived during an active cinematic");
            }
            return Poll(); // A duplicate gather never repeats a native operation.
        }
        ticket_ = action.ticket;
        if (!valid_ticket(ticket_)) {
            return block("Gather action has an invalid ticket");
        }
        active_ = true;
        gathered_ = ready_reported_ = started_ = skip_sent_ = ended_reported_ = false;
        final_state_ = {};
        const auto observation = observe_checked();
        if (observation.phase != NativeCinematicPhase::Preparing ||
            observation.world_revision != ticket_.world_revision) {
            return block("Gather requires the pending bound cinematic and matching preparation revision");
        }
        identity_ = observation.identity;
        // Lock to this exact runtime identity before native code executes.
        gathered_ = true;
        if (!backend_.Execute(GameOperation::GatherAndHold, ticket_, identity_)) {
            return block("Native gather rejected its runtime identity or preparation barrier");
        }
        last_epoch_ = ticket_.epoch;
        return Poll();
    }
    if (action.ticket.epoch < last_epoch_ ||
        (!active_ && action.ticket.epoch == last_epoch_)) {
        return {};
    }
    if (!active_ || !same_ticket(action.ticket, ticket_)) {
        return block("Local action does not match an active prepared ticket");
    }
    if (action.type == ActionType::BlockLocal) {
        // GatherAndHold owns the native barrier. Do not attempt arbitrary game
        // writes if the current instance is no longer safe to inspect.
        return block(action.reason);
    }
    const auto observation = observe_checked();
    if (action.type == ActionType::StartLocal) {
        if (started_) {
            return consume(observation);
        }
        if (!ready_reported_ || !ready_evidence(observation)) {
            return block("Start arrived without current verified loading and gather evidence");
        }
        if (!backend_.Execute(GameOperation::Start, ticket_, identity_)) {
            return block("Native Start rejected the prepared cinematic instance");
        }
        started_ = true;
        return Poll();
    }
    if (action.type == ActionType::SkipLocal) {
        if (!started_) {
            return block("Skip arrived before coordinated Start");
        }
        // A native end may occur before the caller has polled it. Detect that
        // first, so even this race cannot send Skip to a completed endpoint.
        if (ended_reported_ || observation.phase == NativeCinematicPhase::Ended) {
            return consume(observation);
        }
        if (skip_sent_) {
            return consume(observation);
        }
        if (observation.phase != NativeCinematicPhase::Playing) {
            return block("Skip requires the currently playing cinematic instance");
        }
        if (!backend_.Execute(GameOperation::Skip, ticket_, identity_)) {
            return block("Native Skip rejected the playing cinematic instance");
        }
        skip_sent_ = true;
        return Poll();
    }
    if (action.type == ActionType::ReleaseLocal) {
        if (!ended_reported_ || !same_state(action.end_state, final_state_)) {
            return block("Release arrived before a matching verified end report");
        }
        const auto errors = consume(observation);
        if (blocked_) {
            return errors;
        }
        if (!backend_.Execute(GameOperation::Release, ticket_, identity_)) {
            return block("Native Release rejected the completed cinematic instance");
        }
        active_ = false;
        return {};
    }
    return block("Unsupported local game operation");
}

std::vector<AdapterEvent> GameAdapterBridge::Apply(const Action& action) {
    if (blocked_) {
        return {};
    }
    try {
        return apply_local(action);
    } catch (const std::exception& error) {
        return block(error.what());
    }
}

} // namespace coopsync
