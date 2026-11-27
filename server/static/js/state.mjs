const seats = ["A", "B"];
export const moves = ["fold", "check", "call", "bet", "raise"];
const phases = ["preflop", "flop", "turn", "river", "showdown", "finished"];
const lifecycles = ["waiting", "awaiting_players", "active", "paused", "between_hands", "complete"];
const cardPattern = /^[2-9TJQKA][cdhs]$/;
const idPattern = /^[A-Za-z0-9_-]{1,64}$/;
const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
const count = value => Number.isSafeInteger(value) && value >= 0;
const positive = value => count(value) && value > 0;
const seatOrNull = value => value === null || seats.includes(value);
const pair = (value, check) => record(value) && seats.every(seat => check(value[seat]));
const cards = (value, min, max = min) =>
  Array.isArray(value) && value.length >= min && value.length <= max &&
  value.every(card => typeof card === "string" && cardPattern.test(card));
export const validUnit = unit => count(unit) && unit >= 2 && unit <= 20 && unit % 2 === 0;

function validResult(result) {
  if (result === null) return true;
  if (!record(result)) return false;
  if (result.kind === "showdown_tie") return result.winner === null;
  return ["showdown_win", "fold_win"].includes(result.kind) && seats.includes(result.winner);
}

export function readSnapshot(frame, seat) {
  if (!record(frame) || frame.type !== "snapshot" || frame.seat !== seat ||
      !validUnit(frame.bet_unit) || !count(frame.revision) || !count(frame.lifecycle_revision) ||
      !lifecycles.includes(frame.lifecycle) || !pair(frame.presence, value => typeof value === "boolean") ||
      !record(frame.turn_clock) || !["inactive", "paused", "running"].includes(frame.turn_clock.status) ||
      !seatOrNull(frame.turn_clock.acting_player) ||
      (frame.turn_clock.status === "inactive"
        ? frame.turn_clock.remaining_ms !== null || frame.turn_clock.acting_player !== null
        : !count(frame.turn_clock.remaining_ms) || !seats.includes(frame.turn_clock.acting_player)) ||
      !pair(frame.disconnect_grace, value => value === null || (record(value) && count(value.remaining_ms)))) {
    return null;
  }
  const terminal = frame.match_result;
  if (frame.lifecycle === "complete") {
    if (!record(terminal) || !["engine", "forfeit", "both_absent", "engine_error"].includes(terminal.reason) ||
        (["engine", "forfeit"].includes(terminal.reason)
          ? !seats.includes(terminal.winner) : terminal.winner !== null)) return null;
  } else if (terminal !== null) return null;
  const automatic = frame.last_automatic_action;
  if (automatic !== null && (!record(automatic) || !positive(automatic.hand_id) ||
      !seats.includes(automatic.seat) || !["fold", "check"].includes(automatic.action) ||
      automatic.source !== "server" || automatic.reason !== "turn_timeout")) return null;
  if (frame.status === "waiting") {
    return frame.lifecycle === "waiting" && frame.revision === 0 && frame.hand_id === undefined ? frame : null;
  }
  if (frame.status !== "ready" || frame.lifecycle === "waiting" || !positive(frame.hand_id) ||
      !phases.includes(frame.phase) || !seats.includes(frame.button) || !seatOrNull(frame.actor) ||
      !pair(frame.stacks, count) || !pair(frame.contributions, count) || !count(frame.pot) ||
      !count(frame.raise_count) || !cards(frame.board, 0, 5) || !cards(frame.own_hole_cards, 2) ||
      !Array.isArray(frame.legal_actions) || !frame.legal_actions.every(move => moves.includes(move)) ||
      typeof frame.can_ready !== "boolean" || !pair(frame.ready_seats, value => typeof value === "boolean") ||
      !validResult(frame.result) || !seatOrNull(frame.match_winner)) return null;
  if (frame.result && Object.hasOwn(frame.result, "showdown_hole_cards") &&
      (frame.phase !== "showdown" || frame.pot !== 0 || frame.result.kind === "fold_win" ||
       (terminal && terminal.reason !== "engine") ||
       !pair(frame.result.showdown_hole_cards, value => cards(value, 2)))) return null;
  return frame;
}

export function acceptsSnapshot(current, incoming) {
  if (!current) return true;
  return incoming.revision >= current.revision &&
    incoming.lifecycle_revision >= current.lifecycle_revision &&
    (incoming.hand_id ?? 0) >= (current.hand_id ?? 0) &&
    (!current.match_result || incoming.match_result?.reason === current.match_result.reason &&
      incoming.match_result.winner === current.match_result.winner);
}

export function decode(text) {
  if (typeof text !== "string") return null;
  try {
    const frame = JSON.parse(text);
    return record(frame) && typeof frame.type === "string" ? frame : null;
  } catch {
    return null;
  }
}

export function wireCommand(move, snapshot, id = globalThis.crypto.randomUUID()) {
  const command = {
    type: move === "ready" ? "ready" : "action",
    action_id: id,
    hand_id: snapshot.hand_id,
    expected_revision: snapshot.revision,
  };
  if (move !== "ready") command.action = move;
  return command;
}

export function readPending(wire) {
  const command = decode(wire);
  if (!command || !positive(command.hand_id) || !count(command.expected_revision) ||
      typeof command.action_id !== "string" || !idPattern.test(command.action_id)) return null;
  if (command.type === "ready" && Object.keys(command).length === 4 ||
      command.type === "action" && Object.keys(command).length === 5 && moves.includes(command.action)) {
    return {command, wire, acceptedRevision: null};
  }
  return null;
}

export function readAck(frame) {
  return positive(frame.hand_id) && typeof frame.action_id === "string" && idPattern.test(frame.action_id) &&
    count(frame.outcome_revision) && typeof frame.accepted === "boolean" &&
    (frame.accepted ? frame.error_code === null : typeof frame.error_code === "string");
}

export function acknowledge(pending, frame, snapshot) {
  if (!pending || frame.hand_id !== pending.command.hand_id ||
      frame.action_id !== pending.command.action_id) return {pending, matched: false};
  const settled = !frame.accepted || snapshot?.revision >= frame.outcome_revision;
  return {
    matched: true,
    pending: settled ? null : {...pending, acceptedRevision: frame.outcome_revision},
    error: frame.accepted ? null : frame.error_code,
  };
}

export function settleSnapshot(pending, snapshot) {
  if (!pending || snapshot.match_result) return {pending: null, expired: false};
  const expired = pending.command.hand_id < snapshot.hand_id - 1;
  const confirmed = pending.acceptedRevision !== null && snapshot.revision >= pending.acceptedRevision;
  return {pending: expired || confirmed ? null : pending, expired};
}

export function offeredMoves(snapshot, connected, pending, recovering) {
  if (!snapshot || !connected || pending || recovering || snapshot.match_result) return [];
  if (snapshot.lifecycle === "active" && snapshot.actor === snapshot.seat) return snapshot.legal_actions;
  if (snapshot.lifecycle === "between_hands" && snapshot.can_ready) return ["ready"];
  return [];
}

export function remainingMs(sample, sampledAt, now, running = true) {
  return Math.max(0, sample - (running ? Math.max(0, now - sampledAt) : 0));
}

export function actionLabel(move, snapshot) {
  const label = move[0].toUpperCase() + move.slice(1);
  if (!snapshot?.contributions || !snapshot.legal_actions.includes(move)) return label;
  const owed = Math.max(snapshot.contributions.A, snapshot.contributions.B) -
    snapshot.contributions[snapshot.seat];
  if (move === "call") return `Call · ${owed}`;
  if (move === "bet") return `Bet · ${snapshot.bet_unit}`;
  if (move === "raise") return `Raise · ${owed + snapshot.bet_unit}`;
  return label;
}
