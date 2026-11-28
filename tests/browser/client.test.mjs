import assert from "node:assert/strict";
import {test} from "node:test";
import {commandWatchdog, GameplayConnection, reconnectDelay, socketURL} from "../../server/static/js/network.mjs";
import {newAdmission, persist, restore, restoreAdmission} from "../../server/static/js/session.mjs";
import {
  acceptsSnapshot, acknowledge, actionLabel, decode, offeredMoves, readAck,
  readPending, readSnapshot, remainingMs, settleSnapshot, wireCommand,
} from "../../server/static/js/state.mjs";

function snapshot(changes = {}) {
  return {
    type: "snapshot", status: "ready", seat: "A", bet_unit: 10, revision: 1,
    lifecycle_revision: 2, lifecycle: "active", presence: {A: true, B: true},
    turn_clock: {status: "running", acting_player: "A", remaining_ms: 30000},
    disconnect_grace: {A: null, B: null}, last_automatic_action: null, match_result: null,
    hand_id: 1, phase: "preflop", button: "A", actor: "A", stacks: {A: 195, B: 190},
    contributions: {A: 5, B: 10}, pot: 15, raise_count: 0, board: [],
    own_hole_cards: ["9h", "5h"], legal_actions: ["call", "fold", "raise"],
    ready_seats: {A: false, B: false}, can_ready: false, result: null, match_winner: null,
    ...changes,
  };
}

test("revision pair rejects regression but accepts pause, resume, new hands and clock samples", () => {
  const current = snapshot();
  assert.ok(acceptsSnapshot(null, current));
  assert.ok(acceptsSnapshot(current, snapshot({revision: 2})));
  const paused = snapshot({lifecycle_revision: 3, lifecycle: "paused"});
  assert.ok(acceptsSnapshot(current, paused));
  assert.ok(acceptsSnapshot(paused, snapshot({lifecycle_revision: 4})));
  assert.ok(acceptsSnapshot(paused, {...paused}));
  assert.ok(acceptsSnapshot(paused, snapshot({revision: 3, hand_id: 2, lifecycle_revision: 3})));
  assert.ok(!acceptsSnapshot(paused, snapshot({revision: 99, lifecycle_revision: 2})));
  assert.ok(!acceptsSnapshot(snapshot({revision: 2}), snapshot({lifecycle_revision: 50})));
  const terminal = snapshot({lifecycle_revision: 4, lifecycle: "complete",
    match_result: {reason: "both_absent", winner: null}});
  assert.ok(!acceptsSnapshot(terminal, snapshot({revision: 99, lifecycle_revision: 99})));
});

test("decoder rejects malformed and unsafe frame shapes", () => {
  assert.equal(decode("{"), null);
  assert.equal(decode("[]"), null);
  assert.equal(decode("1"), null);
  assert.deepEqual(readSnapshot(snapshot(), "A"), snapshot());
  for (const frame of [snapshot({own_hole_cards: ["10x"]}), snapshot({bet_unit: 11}),
    snapshot({seat: "B"}), snapshot({lifecycle_revision: undefined}),
    snapshot({result: {kind: "fold_win", winner: "B", showdown_hole_cards: {A: ["9h", "5h"], B: ["Ts", "3c"]}}})]) {
    assert.equal(readSnapshot(frame, "A"), null);
  }
});

test("command uses random identity and authoritative hand and engine revision", () => {
  const state = snapshot({hand_id: 2, revision: 9, lifecycle_revision: 4});
  const command = wireCommand("call", state);
  assert.match(command.action_id, /^[A-Za-z0-9_-]{1,64}$/);
  assert.notEqual(command.action_id, wireCommand("call", state).action_id);
  assert.deepEqual(wireCommand("ready", state, "example"),
    {type: "ready", action_id: "example", hand_id: 2, expected_revision: 9});
  assert.equal(command.hand_id, 2);
  assert.equal(command.expected_revision, 9);
  assert.equal(readPending(JSON.stringify({...command, seat: "B"})), null);
});

test("ack and snapshot can arrive in either order without releasing stale actions", () => {
  const state = snapshot();
  const wire = JSON.stringify(wireCommand("call", state, "request-a"));
  const pending = readPending(wire);
  const ack = {type: "action_ack", hand_id: 1, action_id: "request-a", outcome_revision: 2,
    accepted: true, error_code: null};
  assert.ok(readAck(ack));
  assert.equal(acknowledge(pending, {...ack, action_id: "older"}, state).pending, pending);
  assert.deepEqual(offeredMoves(state, true, pending, false), []);
  const accepted = acknowledge(pending, ack, state).pending;
  assert.equal(accepted.wire, wire);
  assert.equal(settleSnapshot(accepted, state).pending, accepted);
  assert.equal(settleSnapshot(accepted, snapshot({revision: 2})).pending, null);
  assert.equal(acknowledge(pending, ack, snapshot({revision: 2})).pending, null);
  assert.equal(acknowledge(pending, {...ack, accepted: false, error_code: "STALE_REVISION"}, state).pending, null);
  assert.deepEqual(settleSnapshot(pending, snapshot({hand_id: 3, revision: 20})),
    {pending: null, expired: true});
});

test("signals authority only for server-offered moves, and labels exact fixed amounts", () => {
  const state = snapshot();
  assert.deepEqual(offeredMoves(state, false, null, false), []);
  assert.deepEqual(offeredMoves(state, true, null, true), []);
  assert.deepEqual(offeredMoves(state, true, null, false), ["call", "fold", "raise"]);
  assert.deepEqual(offeredMoves(snapshot({actor: "B"}), true, null, false), []);
  assert.deepEqual(offeredMoves(snapshot({lifecycle: "paused"}), true, null, false), []);
  assert.deepEqual(offeredMoves(snapshot({lifecycle: "between_hands", can_ready: true}), true, null, false), ["ready"]);
  assert.equal(actionLabel("call", state), "Call · 5");
  assert.equal(actionLabel("raise", state), "Raise · 15");
});

test("PDF rule snapshots label the turn and river increment", () => {
  const turn = snapshot({phase: "turn", bet_increment: 20,
    contributions: {A: 0, B: 20}, legal_actions: ["call", "raise"]});
  assert.deepEqual(readSnapshot(turn, "A"), turn);
  assert.equal(actionLabel("call", turn), "Call · 20");
  assert.equal(actionLabel("raise", turn), "Raise · 40");
  assert.equal(readSnapshot({...turn, bet_increment: 10}, "A"), null);
});

test("session storage retains only seat metadata and exact unresolved payload", () => {
  const map = new Map();
  const storage = {getItem: key => map.get(key), setItem: (key, value) => map.set(key, value),
    removeItem: key => map.delete(key)};
  const session = {seat: "A", room_code: "room", session_token: "fixture-token", bet_unit: 10};
  const pending = readPending(JSON.stringify(wireCommand("call", snapshot(), "id")));
  assert.ok(persist(storage, session, pending));
  assert.deepEqual(restore(storage), {session, pending});
  assert.ok(persist(storage, null, null));
  assert.deepEqual(restore(storage), {session: null, pending: null});
});

test("admission persistence recovers the exact operation and replaces it with seat identity", () => {
  let stored;
  const storage = {getItem: () => stored, setItem: (_, value) => { stored = value; }};
  const intent = newAdmission("join", "ROOM42");
  assert.match(intent.key, /^[0-9a-f]{64}$/);
  assert.notEqual(intent.key, newAdmission("join", "ROOM42").key);
  assert.equal(persist(storage, null, null, intent), true);
  assert.deepEqual(restoreAdmission(storage), intent);
  assert.deepEqual(restore(storage), {session: null, pending: null});
  const seat = {seat: "B", room_code: "ROOM42", bet_unit: 10, session_token: "fixture-token"};
  assert.equal(persist(storage, seat, null), true);
  assert.equal(restoreAdmission(storage), null);
  assert.equal(stored.includes(intent.key), false);
  assert.deepEqual(restore(storage), {session: seat, pending: null});
});

test("monotonic sampling handles delays, pause, resume, and zero clamp", () => {
  assert.equal(remainingMs(30000, 0, 0), 30000);
  assert.equal(remainingMs(30000, 0, 12341), 17659);
  assert.equal(remainingMs(17659, 12341, 26000, false), 17659);
  assert.equal(remainingMs(17659, 26000, 27000), 16659);
  assert.equal(remainingMs(2100, 28000, 29000), 1100);
  assert.equal(remainingMs(1000, 0, 1500), 0);
});

class FakeSocket {
  constructor(url) {
    this.url = url;
    this.handlers = new Map();
    this.sent = [];
    this.readyState = 0;
  }
  addEventListener(name, handler) { this.handlers.set(name, handler); }
  send(message) { this.sent.push(message); }
  open() {
    this.readyState = 1;
    this.emit("open");
  }
  close() {
    this.readyState = 3;
    this.emit("close", {code: 1006});
  }
  emit(name, event) { this.handlers.get(name)?.(event); }
}

test("socket authority, stale generation, bounded reconnect and replacement", () => {
  const timers = new Map();
  const received = [];
  const conn = new GameplayConnection({
    pageURL: "https://example.test/", token: "fixture-token", Socket: FakeSocket,
    onStatus: () => {}, onFrame: message => received.push(message),
    schedule(fn, delay) { const key = Symbol(); timers.set(key, {fn, delay}); return key; },
    cancel(key) { timers.delete(key); },
  });
  assert.equal(socketURL("http://example.test/").href, "ws://example.test/ws");
  assert.equal(socketURL("https://example.test/").href, "wss://example.test/ws");
  assert.deepEqual([0, 1, 2, 3, 11].map(reconnectDelay), [250, 500, 1000, 2000, 2000]);

  conn.connect();
  const old = conn.socket;
  conn.connect();
  assert.equal(conn.socket, old);
  old.open();
  assert.equal(conn.state, "authenticating");
  assert.deepEqual(JSON.parse(old.sent[0]), {type: "auth", token: "fixture-token", protocol: "gameplay.v1"});
  conn.synchronized(false);
  assert.equal(conn.state, "connected");
  old.close();
  assert.equal(conn.state, "reconnecting");
  assert.equal(timers.size, 1);
  const [key, retry] = [...timers.entries()][0];
  assert.equal(retry.delay, 250);
  timers.delete(key);
  retry.fn();
  const newer = conn.socket;
  assert.notEqual(newer, old);
  old.emit("message", {data: '{"type":"snapshot"}'});
  old.emit("close", {code: 4000});
  assert.equal(received.length, 0);
  assert.equal(conn.socket, newer);
  newer.emit("close", {code: 4000});
  assert.equal(conn.state, "replaced");
  assert.equal(timers.size, 0);

  conn.retryManually();
  conn.socket.emit("message", {data: '{"type":"error","code":"UNAUTHORIZED"}'});
  assert.equal(conn.state, "unauthorized");
  assert.equal(timers.size, 0);
  conn.halt();
  assert.equal(conn.socket, null);
});

test("command recovery has one fixed monotonic deadline per transmission", () => {
  let now = 0, timer, triggered = 0;
  const watchdog = commandWatchdog(() => triggered++, {
    now: () => now,
    schedule(fn, delay) { timer = {fn, delay}; return timer; },
    cancel() { timer = null; },
  });
  watchdog.arm();
  const original = timer;
  now = 2200;
  watchdog.arm();
  assert.equal(timer, original);
  timer.fn();
  assert.equal(timer.delay, 2300);
  now = 5000;
  timer.fn();
  assert.equal(triggered, 1);
  watchdog.arm();
  assert.equal(timer.delay, 4500);
  const obsolete = timer;
  watchdog.clear();
  obsolete.fn();
  assert.equal(timer, null);
  assert.equal(triggered, 1);
});

test("heartbeat and browser hints relinquish stale authority without reviving replaced seats", () => {
  const timers = new Map();
  const connection = new GameplayConnection({
    pageURL: "https://example.test/", token: "fixture-token", Socket: FakeSocket,
    onStatus() {}, onFrame() {},
    schedule(fn, delay) { const key = Symbol(); timers.set(key, {fn, delay}); return key; },
    cancel(key) { timers.delete(key); },
  });
  function runTimer(delay) {
    assert.equal(timers.size, 1);
    const [[key, timer]] = timers;
    assert.equal(timer.delay, delay);
    timers.delete(key);
    timer.fn();
  }
  connection.connect();
  connection.socket.open();
  connection.synchronized(false);
  runTimer(6000);
  assert.equal(connection.socket.sent.at(-1), '{"type":"ping"}');
  connection.socket.emit("message", {data: '{"type":"pong"}'});
  runTimer(6000);
  runTimer(4000);
  assert.equal(connection.state, "reconnecting");
  connection.setAvailable("network", false);
  connection.setAvailable("page", false);
  connection.setAvailable("network", true);
  assert.equal(connection.socket, null);
  assert.equal(timers.size, 0);
  connection.setAvailable("page", true);
  const successor = connection.socket;
  successor.emit("close", {code: 4000});
  connection.setAvailable("network", false);
  connection.setAvailable("network", true);
  assert.equal(connection.state, "replaced");
  assert.equal(connection.socket, null);
  assert.equal(timers.size, 0);
});

test("automatic reconnect stops after eleven schedules and explicit exit cancels retries", () => {
  const timers = new Map();
  const connection = new GameplayConnection({
    pageURL: "https://example.test/", token: "fixture-token", Socket: FakeSocket,
    onStatus() {}, onFrame() {},
    schedule(fn, delay) { const key = Symbol(); timers.set(key, {fn, delay}); return key; },
    cancel(key) { timers.delete(key); },
  });
  connection.connect();
  for (let count = 0; count < 11; count++) {
    connection.socket.close();
    assert.equal(timers.size, 1);
    const [[key, timer]] = timers;
    assert.ok(timer.delay <= 2000);
    timers.delete(key);
    timer.fn();
  }
  connection.socket.close();
  assert.equal(connection.state, "offline");
  assert.equal(timers.size, 0);
  connection.retryManually();
  connection.socket.close();
  const [obsolete] = timers.values();
  connection.halt();
  obsolete.fn();
  assert.equal(connection.socket, null);
  assert.equal(timers.size, 0);
});

test("default scheduling preserves the browser global receiver", {concurrency: false}, () => {
  const originalSet = globalThis.setTimeout;
  const originalClear = globalThis.clearTimeout;
  try {
    globalThis.setTimeout = function () {
      assert.equal(this, globalThis);
      return 42;
    };
    globalThis.clearTimeout = function (id) {
      assert.equal(this, globalThis);
      assert.equal(id, 42);
    };
    const conn = new GameplayConnection({
      pageURL: "http://example.test/", token: "fixture-token", Socket: FakeSocket,
      onStatus: () => {}, onFrame: () => {},
    });
    conn.connect();
    conn.halt();
  } finally {
    globalThis.setTimeout = originalSet;
    globalThis.clearTimeout = originalClear;
  }
});
