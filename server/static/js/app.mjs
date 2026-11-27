import {admit, AdmissionRejected, commandWatchdog, GameplayConnection} from "./network.mjs";
import {newAdmission, persist, restore, restoreAdmission} from "./session.mjs";
import {
  acceptsSnapshot, acknowledge, offeredMoves, readAck, readPending, readSnapshot,
  settleSnapshot, validUnit, wireCommand,
} from "./state.mjs";
import {byId, renderTable, renderTimers} from "./render.mjs";

const storage = (() => {
  try { return window.sessionStorage; } catch { return null; }
})();
const state = {...restore(storage), snapshot: null, sampledAt: 0, status: "idle",
  recovering: false, notice: ""};
let admission = state.session ? null : restoreAdmission(storage);
let link;
let admissionPending = false;
let invalidAdmissionField = null;
let recoveryAttempts = 0;
let displayTimer = null;
let lastTouch = null;
const watchdog = commandWatchdog(() => {
  if (recoveryAttempts >= 2) {
    state.notice = "The server still has not confirmed the latest state. Reconnect to check it.";
    link.halt("protocol");
    return;
  }
  recoveryAttempts++;
  link.retryManually();
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
  if (document.activeElement === byId("action-status") && !byId("result").hidden &&
      result.textContent !== previousResult) {
    result.focus({preventScroll: true});
  }
  byId("admission-forms").hidden = Boolean(admission);
  byId("admission-recovery").hidden = !admission;
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
  const needsDisplay = state.session && state.status === "connected" && view && !view.match_result &&
    (view.turn_clock.status === "running" || view.disconnect_grace.A || view.disconnect_grace.B);
  if (displayTimer !== null && !needsDisplay) {
    clearInterval(displayTimer);
    displayTimer = null;
  } else if (displayTimer === null && needsDisplay) {
    displayTimer = setInterval(() => renderTimers(state, performance.now()), 200);
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
    // A protocol error does not identify a pending command. Keep its original payload.
    state.notice = errors[frame.code] ?? "The server rejected the message.";
    if (state.pending) link.halt("protocol");
    else draw();
  } else if (frame?.type !== "pong") {
    protocolError();
  }
}

function connect() {
  link = new GameplayConnection({
    pageURL: window.location.href,
    token: state.session.session_token,
    onStatus(status) {
      state.status = status;
      if (status !== "connected") watchdog.clear();
      draw();
    },
    onFrame: receive,
  });
  if (navigator.onLine === false) link.setAvailable("network", false);
  else link.connect();
}

function requestMove(move) {
  if (!offeredMoves(state.snapshot, state.status === "connected", state.pending, state.recovering).includes(move)) return;
  state.notice = "";
  state.pending = readPending(JSON.stringify(wireCommand(move, state.snapshot)));
  save();
  if (link.send(state.pending.wire)) watchdog.arm();
  draw();
}

function submitAdmission(event, kind) {
  event.preventDefault();
  if (admission || admissionPending || state.session) return;
  const field = kind === "create" ? "bet-unit" : "room-input";
  const input = kind === "create" ? Number(byId(field).value) : byId(field).value.trim();
  invalidAdmissionField = null;
  if (kind === "create" ? !validUnit(input) : !input || input.length > 128) {
    invalidAdmissionField = field;
    state.notice = kind === "create" ? "Choose an even bet unit from 2 to 20." : "Enter a valid room code.";
    draw();
    byId(field).focus();
    return;
  }
  try {
    admission = newAdmission(kind, input);
  } catch {
    state.notice = "Secure randomness is unavailable in this browser.";
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
    if (!state.session) byId(admission ? "retry-admission" : kind === "create" ? "bet-unit" : "room-input").focus();
  }
}

byId("retry-admission").addEventListener("click", confirmAdmission);
byId("create-form").addEventListener("submit", event => submitAdmission(event, "create"));
byId("join-form").addEventListener("submit", event => submitAdmission(event, "join"));
for (const id of ["bet-unit", "room-input"]) {
  byId(id).addEventListener("input", () => {
    if (invalidAdmissionField !== id) return;
    invalidAdmissionField = null;
    state.notice = "";
    draw();
  });
}
byId("bet-unit").addEventListener("change", event => {
  const unit = Number(event.currentTarget.value);
  if (!validUnit(unit)) return;
  byId("preview-stack").textContent = String(20 * unit);
  byId("preview-blinds").textContent = `${unit / 2} / ${unit}`;
  byId("preview-increment").textContent = String(unit);
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
  try {
    await navigator.clipboard.writeText(state.session.room_code);
    state.notice = "Room code copied.";
  } catch {
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
  if (dialog.returnValue !== "leave") return;
  lastTouch = null;
  finishRecovery();
  Object.assign(state, {session: null, pending: null, snapshot: null, recovering: false, notice: ""});
  save();
  link.halt();
  link = null;
  draw();
  byId("title").focus();
});
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
