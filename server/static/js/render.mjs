import {actionLabel, offeredMoves, remainingMs} from "./state.mjs";

const ranks = {A: "Ace", K: "King", Q: "Queen", J: "Jack", T: "Ten"};
const suits = {c: ["♣", "clubs"], d: ["♦", "diamonds"], h: ["♥", "hearts"], s: ["♠", "spades"]};
const streets = {preflop: "Preflop", flop: "Flop", turn: "Turn", river: "River",
  showdown: "Showdown", finished: "Hand settled"};
const connectionLabels = {
  idle: "Disconnected", connecting: "Connecting", authenticating: "Authenticating",
  connected: "Connected", reconnecting: "Reconnecting", replaced: "Session replaced",
  unauthorized: "Session expired", offline: "Offline", protocol: "Synchronization unavailable",
};
const lifecycleLabels = {
  waiting: "Waiting room", awaiting_players: "Table forming", active: "Hand in play",
  paused: "Hand paused", between_hands: "Between hands", complete: "Match complete",
};
const cardGroups = new WeakMap();

export const byId = id => document.getElementById(id);
function text(id, value) {
  const node = byId(id);
  if (node.textContent !== value) node.textContent = value;
}

function card(value, kind) {
  const node = document.createElement("span");
  node.className = `card ${kind}`;
  if (kind === "empty") {
    node.setAttribute("aria-hidden", "true");
    return node;
  }
  node.setAttribute("role", "img");
  if (kind === "back") {
    node.setAttribute("aria-label", "Face-down card");
    return node;
  }
  const [rank, suit] = value;
  node.setAttribute("aria-label", `${ranks[rank] ?? rank} of ${suits[suit][1]}`);
  if ("dh".includes(suit)) node.classList.add("red");
  const corner = document.createElement("span");
  corner.textContent = rank === "T" ? "10" : rank;
  const symbol = document.createElement("span");
  symbol.className = "suit";
  symbol.textContent = suits[suit][0];
  node.append(corner, symbol);
  return node;
}

function updateCards(id, values, slots, hiddenStyle) {
  const group = byId(id);
  const signature = values.join(",");
  if (group.childElementCount === slots && cardGroups.get(group) === signature) return;
  group.replaceChildren(...Array.from({length: slots}, (_, i) =>
    card(values[i], values[i] ? "face" : hiddenStyle)));
  cardGroups.set(group, signature);
}

function markers(view, seat) {
  const indicators = [];
  if (view.button === seat) indicators.push("Dealer");
  if (view.phase === "preflop" && !view.match_result) {
    indicators.push(view.button === seat ? "Small blind seat" : "Big blind seat");
  }
  if (view.actor === seat && view.lifecycle === "active") indicators.push("Acting");
  if (view.ready_seats[seat]) indicators.push("Ready");
  return indicators.join(" · ");
}

function handResult(view) {
  if (view.match_result) {
    const {reason, winner} = view.match_result;
    if (reason === "forfeit") return [
      `Player ${winner} wins the match by forfeit`,
      view.result ? "The last hand had already settled." : "Hand interrupted. The outstanding pot remains unawarded.",
    ];
    if (reason === "both_absent") return [
      "Match closed without a winner",
      view.result ? "Both players were absent after the last hand settled." :
        "Both players were absent. The interrupted hand’s pot remains unawarded.",
    ];
    if (reason === "engine") return [`Player ${winner} wins the match`, "The match has ended."];
    return ["Match closed", "The server ended the match before it could continue."];
  }
  if (view.result?.kind === "fold_win") return [`Player ${view.result.winner} wins by fold`, "The hand is settled."];
  if (view.result?.kind === "showdown_tie") return ["Showdown tie", "The pot was split."];
  if (view.result?.kind === "showdown_win") return [`Player ${view.result.winner} wins at showdown`, "The hand is settled."];
  return null;
}

export function renderTable(state) {
  const {session, snapshot: view, status, pending, recovering} = state;
  byId("landing").hidden = Boolean(session);
  byId("game").hidden = !session;
  byId("connection-label").hidden = !session;
  text("notice", state.notice);
  if (!session) {
    text("announcements", "");
    text("automatic", "");
    for (const id of ["board", "your-cards", "opponent-cards"]) byId(id).replaceChildren();
    return;
  }

  text("connection-label", connectionLabels[status]);
  text("room-code", session.room_code);
  text("game-meta", `PLAYER ${session.seat} · BET UNIT ${session.bet_unit}`);
  const retry = ["offline", "replaced", "protocol"].includes(status);
  byId("reconnect").hidden = !retry;
  const hasHand = Boolean(view?.hand_id);
  byId("waiting").hidden = hasHand;
  byId("table-layout").hidden = !hasHand;
  if (!hasHand) {
    const waiting = byId("waiting");
    waiting.querySelector("h2").textContent = view ? "Waiting for opponent" : connectionLabels[status];
    waiting.querySelector("p").textContent = view ? "Share the room code with a friend. The first turn starts when both players are connected." :
      status === "unauthorized" ? "Leave this table to clear the expired session." : "Your table will appear after the server confirms your seat.";
    text("announcements", status === "connected" && view ? "Waiting for opponent." : "");
    return;
  }

  const opponent = view.seat === "A" ? "B" : "A";
  text("game-title", `Hand ${view.hand_id} · ${streets[view.phase]}`);
  text("your-name", `You · Player ${view.seat}`);
  text("opponent-name", `Opponent · Player ${opponent}`);
  text("your-markers", markers(view, view.seat));
  text("opponent-markers", markers(view, opponent));
  text("your-stack", `${view.stacks[view.seat]} chips`);
  text("opponent-stack", `${view.stacks[opponent]} chips`);
  text("pot", `${view.pot} chips`);
  byId("you").classList.toggle("acting", view.lifecycle === "active" && view.actor === view.seat);
  byId("opponent").classList.toggle("acting", view.lifecycle === "active" && view.actor === opponent);
  updateCards("your-cards", view.own_hole_cards, 2, "empty");
  const revealed = view.result?.showdown_hole_cards?.[opponent] ?? [];
  updateCards("opponent-cards", revealed, 2, "back");
  updateCards("board", view.board, 5, "empty");

  const terminal = Boolean(view.match_result);
  const authoritative = status === "connected" || terminal;
  text("lifecycle", authoritative ? lifecycleLabels[view.lifecycle] : "Last known table");
  const turn = {
    awaiting_players: "Waiting for both players",
    active: view.actor === view.seat ? "Your turn" : `Player ${view.actor}’s turn`,
    paused: "Waiting for reconnection",
    between_hands: "Ready for the next hand",
    complete: "Play has ended",
  }[view.lifecycle];
  text("turn-status", status === "connected" || terminal ? turn : connectionLabels[status]);
  byId("presence").hidden = terminal;
  text("presence", !authoritative ? "Current opponent status is unknown." :
    view.presence[opponent] ? "Opponent connected" : "Opponent disconnected");
  if (authoritative) {
    const automatic = view.last_automatic_action;
    text("automatic", automatic
      ? `Player ${automatic.seat} timed out. The server applied ${automatic.action}.` : "");
  }

  const result = handResult(view);
  byId("result").hidden = !result;
  if (result) {
    text("result-title", result[0]);
    const lastHand = terminal && view.result
      ? view.result.winner ? ` Player ${view.result.winner} won the last hand.` : " The last hand was a tie."
      : "";
    text("result-detail", result[1] + lastHand);
  }
  const presence = view.presence[opponent] ? "Opponent connected." : "Opponent disconnected.";
  text("announcements", terminal ? result[0] : status !== "connected" ? "" :
    `${presence} ${result?.[0] ?? turn}`);
  const moves = offeredMoves(view, status === "connected", pending, recovering);
  text("action-status", pending ? "Waiting for server confirmation…" : recovering ? "Synchronizing…" :
    terminal ? "This match is complete." : view.ready_seats[view.seat] ? "Waiting for the other player to Ready." :
      moves.length ? "Choose an available action." : "Actions are unavailable.");
  for (const button of byId("actions").querySelectorAll("[data-action]")) {
    const move = button.dataset.action;
    button.disabled = !moves.includes(move);
    button.hidden = move === "ready" ? !view.result || terminal : view.lifecycle === "between_hands" || terminal;
    button.textContent = actionLabel(move, view);
  }
  renderTimers(state, performance.now());
}

export function renderTimers({snapshot: view, sampledAt, status}, now) {
  const clock = view?.turn_clock;
  const show = status === "connected" && clock && !view.match_result && clock.status !== "inactive";
  byId("turn-clock").hidden = !show;
  byId("turn-progress").hidden = !show;
  if (show) {
    const remaining = remainingMs(clock.remaining_ms, sampledAt, now, clock.status === "running");
    const seconds = Math.ceil(remaining / 1000);
    byId("turn-progress").value = remaining;
    text("turn-clock", `${seconds}s${clock.status === "paused" ? " · paused" : ""}`);
  }
  const grace = status !== "connected" || view?.match_result ? null : view?.disconnect_grace;
  byId("grace").hidden = !grace || !(grace.A || grace.B);
  for (const seat of ["A", "B"]) {
    const entry = grace?.[seat], id = `grace-${seat.toLowerCase()}`;
    byId(id).hidden = !entry;
    if (entry) text(id, `Player ${seat} can return for ${Math.ceil(remainingMs(entry.remaining_ms, sampledAt, now) / 1000)}s`);
  }
}
