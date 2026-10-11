#include "coordinator.h"

#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace coopsync {
namespace {

bool same_state(const EndState& left, const EndState& right) noexcept {
    return left.world_revision == right.world_revision &&
           left.state_digest == right.state_digest;
}

bool valid_ticket(const Ticket& ticket) noexcept {
    return !ticket.cinematic_id.empty() && ticket.cinematic_id.size() <= 128 &&
           std::isfinite(ticket.x) && std::isfinite(ticket.y) &&
           std::isfinite(ticket.z);
}

bool expired(std::uint64_t now, std::uint64_t started,
             std::uint64_t timeout) noexcept {
    // Subtract instead of adding a deadline, avoiding overflow near UINT64_MAX.
    // A clock going backwards violates the caller's monotonic-clock contract.
    return now >= started && now - started >= timeout;
}

} // namespace

HostCoordinator::HostCoordinator(std::uint64_t prepare_timeout_ms,
                                 std::uint64_t ending_timeout_ms)
    : prepare_timeout_ms_(prepare_timeout_ms),
      ending_timeout_ms_(ending_timeout_ms) {
    if (prepare_timeout_ms == 0 || ending_timeout_ms == 0) {
        throw std::invalid_argument("Coordinator timeouts must be positive");
    }
}

bool HostCoordinator::active() const noexcept {
    return phase_ == Phase::Preparing || phase_ == Phase::Playing ||
           phase_ == Phase::Ending;
}

bool HostCoordinator::accepts(std::uint64_t epoch) const noexcept {
    return active() && epoch == ticket_.epoch;
}

Action HostCoordinator::action(ActionType type, EndState state,
                               std::string reason) const {
    return Action{type, ticket_, state, std::move(reason)};
}

std::vector<Action> HostCoordinator::block(std::string reason) {
    if (!active()) {
        return {};
    }
    if (reason.empty()) {
        reason = "Session aborted";
    }
    // The wire reason limit also bounds locally supplied abort messages.
    if (reason.size() > 256) {
        reason.resize(256);
    }
    phase_ = Phase::Blocked;
    return {action(ActionType::BlockPeer, {}, reason),
            action(ActionType::BlockLocal, {}, std::move(reason))};
}

std::vector<Action> HostCoordinator::Prepare(Ticket ticket,
                                            std::uint64_t now_ms) {
    if (phase_ != Phase::Idle) {
        return {};
    }
    if (!valid_ticket(ticket)) {
        throw std::invalid_argument("Ticket needs a 1-128 byte cinematic ID and finite coordinates");
    }
    if (next_epoch_ == std::numeric_limits<std::uint64_t>::max()) {
        throw std::overflow_error("Cinematic epoch exhausted; create a new verified session");
    }
    ticket.epoch = ++next_epoch_;
    ticket_ = std::move(ticket);
    local_ = {};
    peer_ = {};
    skip_requested_ = false;
    skip_sent_ = false;
    phase_started_ms_ = now_ms;
    phase_ = Phase::Preparing;
    return {action(ActionType::PreparePeer), action(ActionType::GatherLocal)};
}

std::vector<Action> HostCoordinator::Tick(std::uint64_t now_ms) {
    if (phase_ == Phase::Preparing &&
        expired(now_ms, phase_started_ms_, prepare_timeout_ms_)) {
        return block("Timed out waiting for both players to prepare");
    }
    if (phase_ == Phase::Ending &&
        expired(now_ms, phase_started_ms_, ending_timeout_ms_)) {
        return block("Timed out waiting for matching cinematic end states");
    }
    return {};
}

std::vector<Action> HostCoordinator::ready(
    Endpoint& endpoint, const char* endpoint_name, std::uint64_t epoch,
    std::uint32_t scene_id, std::uint64_t revision, std::uint64_t now_ms) {
    if (!accepts(epoch)) {
        return {};
    }
    auto actions = Tick(now_ms);
    if (!actions.empty()) {
        return actions;
    }
    if (scene_id != ticket_.scene_id || revision != ticket_.world_revision ||
        (endpoint.ready && (scene_id != endpoint.scene_id ||
                            revision != endpoint.ready_revision))) {
        return block(std::string(endpoint_name) + " reported a conflicting ready state");
    }
    if (endpoint.ready) {
        return {};
    }
    // No endpoint can legitimately become ready for the first time after start.
    if (phase_ != Phase::Preparing) {
        return block(std::string(endpoint_name) + " became ready after cinematic start");
    }
    endpoint.ready = true;
    endpoint.scene_id = scene_id;
    endpoint.ready_revision = revision;
    if (local_.ready && peer_.ready) {
        phase_ = Phase::Playing;
        actions.push_back(action(ActionType::StartPeer));
        actions.push_back(action(ActionType::StartLocal));
        if (skip_requested_) {
            append_skip(actions, now_ms);
        }
    }
    return actions;
}

std::vector<Action> HostCoordinator::LocalReady(
    std::uint64_t epoch, std::uint32_t scene_id, std::uint64_t revision,
    std::uint64_t now_ms) {
    return ready(local_, "Local player", epoch, scene_id, revision, now_ms);
}

std::vector<Action> HostCoordinator::PeerReady(
    std::uint64_t epoch, std::uint32_t scene_id, std::uint64_t revision,
    std::uint64_t now_ms) {
    return ready(peer_, "Peer", epoch, scene_id, revision, now_ms);
}

void HostCoordinator::append_skip(std::vector<Action>& actions,
                                  std::uint64_t now_ms) {
    if (skip_sent_) {
        return;
    }
    skip_sent_ = true;
    // A natural ending already has its own deadline, which skip cannot extend.
    if (phase_ == Phase::Playing) {
        phase_ = Phase::Ending;
        phase_started_ms_ = now_ms;
    }
    // An endpoint that has already ended must not receive another game command.
    // Its end report remains part of the barrier for the same epoch.
    if (!peer_.ended) {
        actions.push_back(action(ActionType::SkipPeer));
    }
    if (!local_.ended) {
        actions.push_back(action(ActionType::SkipLocal));
    }
}

std::vector<Action> HostCoordinator::skip(std::uint64_t epoch,
                                         std::uint64_t now_ms) {
    if (!accepts(epoch)) {
        return {};
    }
    auto actions = Tick(now_ms);
    if (!actions.empty()) {
        return actions;
    }
    skip_requested_ = true;
    if (phase_ != Phase::Preparing) {
        append_skip(actions, now_ms);
    }
    return actions;
}

std::vector<Action> HostCoordinator::LocalSkip(std::uint64_t epoch,
                                              std::uint64_t now_ms) {
    return skip(epoch, now_ms);
}

std::vector<Action> HostCoordinator::PeerSkip(std::uint64_t epoch,
                                             std::uint64_t now_ms) {
    return skip(epoch, now_ms);
}

std::vector<Action> HostCoordinator::ended(
    Endpoint& endpoint, const char* endpoint_name, std::uint64_t epoch,
    EndState state, std::uint64_t now_ms) {
    if (!accepts(epoch)) {
        return {};
    }
    auto actions = Tick(now_ms);
    if (!actions.empty()) {
        return actions;
    }
    if (phase_ == Phase::Preparing) {
        return block(std::string(endpoint_name) + " ended before both players were ready");
    }
    if (endpoint.ended) {
        if (!same_state(endpoint.end_state, state)) {
            return block(std::string(endpoint_name) + " changed its completed end state");
        }
        return {};
    }
    if (state.world_revision < ticket_.world_revision) {
        return block(std::string(endpoint_name) + " reported a regressed world revision");
    }
    endpoint.ended = true;
    endpoint.end_state = state;
    if (phase_ == Phase::Playing) {
        phase_ = Phase::Ending;
        phase_started_ms_ = now_ms;
    }
    if (local_.ended && peer_.ended) {
        if (!same_state(local_.end_state, peer_.end_state)) {
            return block("Players reported different world revisions or state digests");
        }
        actions.push_back(action(ActionType::ReleasePeer, state));
        actions.push_back(action(ActionType::ReleaseLocal, state));
        phase_ = Phase::Idle;
    }
    return actions;
}

std::vector<Action> HostCoordinator::LocalEnded(std::uint64_t epoch,
                                               EndState state,
                                               std::uint64_t now_ms) {
    return ended(local_, "Local player", epoch, state, now_ms);
}

std::vector<Action> HostCoordinator::PeerEnded(std::uint64_t epoch,
                                              EndState state,
                                              std::uint64_t now_ms) {
    return ended(peer_, "Peer", epoch, state, now_ms);
}

std::vector<Action> HostCoordinator::PeerDisconnected() {
    return block("Peer disconnected during an active cinematic");
}

std::vector<Action> HostCoordinator::Abort(std::string reason) {
    return block(std::move(reason));
}

} // namespace coopsync
