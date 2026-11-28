import {admissionContext, admit, AdmissionRejected, commandWatchdog, GameplayConnection} from "./network.mjs";
import {newAdmission, persist, restore, restoreAdmission} from "./session.mjs";
import {
  acceptsSnapshot, acknowledge, offeredMoves, readAck, readPending, readSnapshot,
  remainingMs, settleSnapshot, terminalCommands, validUnit, wireCommand,
} from "./state.mjs";
import {byId, renderTable, renderTimers} from "./render.mjs";

const storage = (() => {
  try { return window.sessionStorage; } catch { return null; }
})();
const state = {...restore(storage), snapshot: null, sampledAt: 0, status: "idle",
  recovering: false, notice: "", terminalPending: null};
let admission = state.session ? null : restoreAdmission(storage);
let link;
let admissionPending = false;
let invalidAdmissionField = null;
let recoveryAttempts = 0;
let displayTimer = null;
let lastReleasePoll = -Infinity;
let lastTouch = null;
let tableRules = "legacy";
const watchdog = commandWatchdog(() => {
  if (recoveryAttempts >= 2) {
    state.notice = "The server still has not confirmed the latest state. Reconnect to check it.";
    link.halt("protocol");
    return;
  }
  recoveryAttempts++;
  link.retryManually();
});
const terminalWatchdog = commandWatchdog(() => {
  if (!state.terminalPending) return;
  state.terminalPending = null;
  state.notice = "The server did not confirm the request. Checking the current session.";
  link.retryManually();
  draw();
});
const errors = {
  INVALID_MESSAGE: "The server could not read the command.",
  ILLEGAL_ACTION: "The server rejected that action. Choose an available action.",
  WRONG_TURN: "It is no longer your turn.",
  STALE_REVISION: "The table changed. Review the latest state before acting.",
  WRONG_HAND: "That command targeted a different hand.",
  MATCH_PAUSED: "The hand is paused while a player reconnects.",
  MATCH_COMPLETE: "The match has ended.",
  HAND_COMPLETE: "The hand is already settled.",
  REPLAY_CONFLICT: "That action identifier was already used for a different command.",
  NOT_READY: "Wait until both players are connected.",
  ROOM_NOT_TERMINAL: "Only a completed match can be released.",
  RELEASE_NOT_ELIGIBLE: "Room release is not available yet.",
};

function save() {
  if (!persist(storage, state.session, state.pending, admission) && state.session && !state.notice) {
    state.notice = "Refresh recovery is unavailable in this tab.";
  }
}

function draw() {
  const focused = document.activeElement;
  const result = byId("result-title");
  const previousResult = byId("result").hidden ? "" : result.textContent;
  renderTable(state);
  if (focused?.matches("#actions button") && (focused.disabled || focused.hidden)) {
    byId("action-status").focus({preventScroll: true});
  }
  if (focused?.matches("#room-release button") && focused.disabled) {
    result.focus({preventScroll: true});
  }
  if (document.activeElement === byId("action-status") && !byId("result").hidden &&
      result.textContent !== previousResult) {
    result.focus({preventScroll: true});
  }
  byId("admission-forms").hidden = Boolean(admission);
  byId("admission-recovery").hidden = !admission;
  for (const button of byId("admission-forms").querySelectorAll("button[type=submit]")) {
    button.disabled = admissionPending;
  }
  for (const id of ["bet-unit", "room-input"]) {
    const field = byId(id);
    if (id === invalidAdmissionField) {
      field.setAttribute("aria-invalid", "true");
      field.setAttribute("aria-errormessage", "notice");
    } else {
      field.removeAttribute("aria-invalid");
      field.removeAttribute("aria-errormessage");
    }
  }
  if (admission) {
    byId("recovery-detail").textContent = admission.kind === "create"
      ? "Retry the original room creation to recover the host seat."
      : "Retry the original room join to recover the guest seat.";
    const retry = byId("retry-admission");
    retry.disabled = admissionPending;
    retry.textContent = admissionPending ? "Confirming admission…" : "Retry admission";
  }
  const view = state.snapshot;
  const release = view?.room_release;
  const needsDisplay = state.session && state.status === "connected" && view && (
    (!view.match_result && (view.turn_clock.status === "running" || view.disconnect_grace.A || view.disconnect_grace.B)) ||
    (release && !release.eligible && release.remaining_ms > 0)
  );
  if (displayTimer !== null && !needsDisplay) {
    clearInterval(displayTimer);
    displayTimer = null;
  } else if (displayTimer === null && needsDisplay) {
    displayTimer = setInterval(updateTimers, 200);
  }
}

function updateTimers() {
  const now = performance.now();
  renderTimers(state, now);
  const release = state.snapshot?.room_release;
  if (release && !release.eligible && remainingMs(release.remaining_ms, state.sampledAt, now) === 0) {
    if (!release.acknowledged.A && !release.acknowledged.B) {
      byId("release-countdown").hidden = true;
      clearInterval(displayTimer);
      displayTimer = null;
    } else if (now - lastReleasePoll >= 1000) {
      lastReleasePoll = now;
      link.send({type: "snapshot_request"});
    }
  }
}

function finishRecovery() {
  watchdog.clear();
  recoveryAttempts = 0;
}

function protocolError() {
  state.notice = "The server sent an unexpected message. Reconnect to synchronize or leave the table.";
  link.halt("protocol");
}

function receive(frame) {
  if (frame?.type === "snapshot") {
    const incoming = readSnapshot(frame, state.session.seat);
    if (!incoming) return protocolError();
    if (!acceptsSnapshot(state.snapshot, incoming)) return;
    state.snapshot = incoming;
    state.sampledAt = performance.now();
    state.recovering = false;
    if (state.terminalPending === "acknowledge_result" && incoming.room_release?.acknowledged[incoming.seat]) {
      state.terminalPending = null;
      terminalWatchdog.clear();
    }
    const {pending, expired} = settleSnapshot(state.pending, incoming);
    if (pending !== state.pending) {
      state.pending = pending;
      save();
    }
    if (expired) state.notice = "An unconfirmed action expired. The current hand is up to date.";
    const first = link.synchronized(Boolean(incoming.match_result));
    if (first && state.pending && link.send(state.pending.wire)) watchdog.arm();
    if (!state.pending) finishRecovery();
    draw();
  } else if (frame?.type === "action_ack") {
    if (!state.snapshot || !readAck(frame)) return protocolError();
    const result = acknowledge(state.pending, frame, state.snapshot);
    if (!result.matched) return;
    state.pending = result.pending;
    if (result.error) {
      state.notice = errors[result.error] ?? "The server rejected the action.";
      state.recovering = true;
      if (link.send({type: "snapshot_request"})) watchdog.arm();
    }
    save();
    if (!state.pending && !state.recovering) finishRecovery();
    draw();
  } else if (frame?.type === "error" && typeof frame.code === "string") {
    if (["ROOM_NOT_TERMINAL", "RELEASE_NOT_ELIGIBLE"].includes(frame.code)) {
      terminalWatchdog.clear();
      state.terminalPending = null;
    }
    // A protocol error does not identify a pending command. Keep its original payload.
    state.notice = errors[frame.code] ?? "The server rejected the message.";
    if (state.pending) link.halt("protocol");
    else draw();
  } else if (frame?.type !== "pong") {
    protocolError();
  }
}

function connect() {
  const connection = new GameplayConnection({
    pageURL: window.location.href,
    token: state.session.session_token,
    onStatus(status) {
      if (link !== connection) return;
      if (status === "retired") {
        returnToLobby("The completed room was released. You can create or join a new room.");
        return;
      }
      state.status = status;
      if (status !== "connected") watchdog.clear();
      if (["replaced", "unauthorized"].includes(status)) {
        terminalWatchdog.clear();
        state.terminalPending = null;
      }
      draw();
    },
    onFrame(frame) { if (link === connection) receive(frame); },
  });
  link = connection;
  if (navigator.onLine === false) link.setAvailable("network", false);
  else link.connect();
}

function requestTerminal(type) {
  if (!terminalCommands(state.snapshot, state.status === "connected", state.terminalPending).includes(type)) return;
  state.notice = "";
  state.terminalPending = type;
  if (link.send({type})) terminalWatchdog.arm();
  else state.terminalPending = null;
  draw();
}

function requestMove(move) {
  if (!offeredMoves(state.snapshot, state.status === "connected", state.pending, state.recovering).includes(move)) return;
  state.notice = "";
  state.pending = readPending(JSON.stringify(wireCommand(move, state.snapshot)));
  save();
  if (link.send(state.pending.wire)) watchdog.arm();
  draw();
}

async function submitAdmission(event, kind) {
  event.preventDefault();
  if (admission || admissionPending || state.session) return;
  const field = kind === "create" ? "bet-unit" : "room-input";
  const input = kind === "create"
    ? tableRules === "pdf" ? 10 : Number(byId(field).value)
    : byId(field).value.trim();
  invalidAdmissionField = null;
  if (kind === "create" ? !validUnit(input) : !input || input.length > 128) {
    invalidAdmissionField = field;
    state.notice = kind === "create" ? "Choose an even bet unit from 2 to 20." : "Enter a valid room code.";
    draw();
    byId(field).focus();
    return;
  }
  admissionPending = true;
  state.notice = "";
  draw();
  try {
    const context = await admissionContext();
    admission = newAdmission(kind, input, globalThis.crypto, context);
  } catch {
    state.notice = "Could not prepare a room request. Check your connection and try again.";
  } finally {
    admissionPending = false;
  }
  if (!admission) {
    draw();
    return;
  }
  if (!persist(storage, null, null, admission)) {
    admission = null;
    state.notice = "Enable tab storage to reserve a room seat safely.";
    draw();
    return;
  }
  confirmAdmission();
}

async function confirmAdmission() {
  if (!admission || admissionPending || state.session) return;
  const {kind} = admission;
  admissionPending = true;
  state.notice = "";
  draw();
  try {
    state.session = await admit(admission);
    admission = null;
    save();
    connect();
    byId("game-title").focus();
  } catch (error) {
    if (error instanceof AdmissionRejected) {
      admission = null;
      if (error.invalidInput) invalidAdmissionField = kind === "create" ? "bet-unit" : "room-input";
      save();
    }
    state.notice = error.message;
  } finally {
    admissionPending = false;
    draw();
    if (!state.session) {
      const unit = byId("bet-unit");
      (admission ? byId("retry-admission") : kind === "join" ? byId("room-input") :
        unit.disabled ? byId("create-form").querySelector("button") : unit).focus();
    }
  }
}

byId("retry-admission").addEventListener("click", confirmAdmission);
byId("create-form").addEventListener("submit", event => submitAdmission(event, "create"));
byId("join-form").addEventListener("submit", event => submitAdmission(event, "join"));
byId("acknowledge-result").addEventListener("click", () => requestTerminal("acknowledge_result"));
byId("release-room").addEventListener("click", () => requestTerminal("release_room"));
for (const id of ["bet-unit", "room-input"]) {
  byId(id).addEventListener("input", () => {
    if (invalidAdmissionField !== id) return;
    invalidAdmissionField = null;
    state.notice = "";
    draw();
  });
}
byId("bet-unit").addEventListener("change", event => {
  if (tableRules === "pdf") return;
  const unit = Number(event.currentTarget.value);
  if (!validUnit(unit)) return;
  byId("preview-stack").textContent = String(20 * unit);
  byId("preview-blinds").textContent = `${unit / 2} / ${unit}`;
  byId("preview-increment").textContent = String(unit);
});
fetch("./api/config", {mode: "same-origin"}).then(response => response.json()).then(config => {
  if (config.ruleset !== "pdf") return;
  tableRules = "pdf";
  const select = byId("bet-unit");
  select.replaceChildren(new Option("10 (fixed)", "10"));
  select.disabled = true;
  byId("bet-unit-label").textContent = "Big blind";
  byId("preview-stack").textContent = "500";
  byId("preview-blinds").textContent = "5 / 10";
  byId("preview-increment").textContent = "10 preflop/flop · 20 turn/river";
  byId("rules-summary").textContent = "Two players start with 500 virtual chips. Blinds are 5/10. Bets and raises use 10 chips preflop and flop, then 20 on turn and river. Up to three raises follow the opening wager. Burn one card before each board street. No all-ins or side pots.";
}).catch(() => {
  state.notice = "Could not load table rules. Reload before creating a room.";
  draw();
});
byId("actions").addEventListener("click", event => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  const move = button.dataset.action;
  if (event.pointerType === "touch") {
    const now = performance.now();
    if (lastTouch?.move === move && now - lastTouch.at < 350) return;
    lastTouch = {move, at: now};
  }
  requestMove(move);
});
byId("copy-code").addEventListener("click", async () => {
  const session = state.session;
  try {
    await navigator.clipboard.writeText(session.room_code);
    if (state.session !== session) return;
    state.notice = "Room code copied.";
  } catch {
    if (state.session !== session) return;
    const range = document.createRange();
    range.selectNodeContents(byId("room-code"));
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    state.notice = "Room code selected. Use your browser’s copy command.";
  }
  draw();
});
byId("reconnect").addEventListener("click", event => {
  if (navigator.onLine === false) {
    draw();
    return;
  }
  const returnFocus = document.activeElement === event.currentTarget;
  state.notice = "";
  finishRecovery();
  link.retryManually();
  if (returnFocus) byId("game-title").focus();
});
const dialog = byId("leave-dialog");
byId("leave").addEventListener("click", () => {
  dialog.returnValue = "stay";
  dialog.showModal();
});
dialog.addEventListener("close", () => {
  if (dialog.returnValue === "leave" && state.session) returnToLobby();
});
function returnToLobby(notice = "") {
  lastTouch = null;
  lastReleasePoll = -Infinity;
  finishRecovery();
  terminalWatchdog.clear();
  admission = null;
  invalidAdmissionField = null;
  Object.assign(state, {session: null, pending: null, snapshot: null, sampledAt: 0, status: "idle",
    recovering: false, terminalPending: null, notice});
  save();
  const previous = link;
  link = null;
  previous?.halt();
  if (dialog.open) dialog.close();
  byId("room-input").value = "";
  const unit = byId("bet-unit");
  if (unit.value !== "10") {
    unit.value = "10";
    unit.dispatchEvent(new Event("change"));
  }
  draw();
  byId("title").focus();
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.status === "connected") link.send({type: "snapshot_request"});
});
window.addEventListener("offline", () => link?.setAvailable("network", false));
window.addEventListener("online", () => link?.setAvailable("network", true));
window.addEventListener("pagehide", () => link?.setAvailable("page", false));
window.addEventListener("pageshow", event => {
  if (event.persisted) link?.setAvailable("page", true);
});
if (state.session) connect();
else draw();
