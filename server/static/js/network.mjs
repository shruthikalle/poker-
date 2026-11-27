import {decode, validUnit} from "./state.mjs";

export const reconnectDelay = attempt => Math.min(250 * 2 ** attempt, 2000);
const manualOnly = new Set(["replaced", "unauthorized", "protocol"]);

export function commandWatchdog(onTimeout, {
  now = () => performance.now(),
  schedule = (fn, delay) => setTimeout(fn, delay),
  cancel = id => clearTimeout(id),
  timeout = 4500,
} = {}) {
  let attempt = null;
  return {
    arm() {
      if (attempt) return;
      const current = {deadline: now() + timeout, timer: null};
      attempt = current;
      function check() {
        if (attempt !== current) return;
        const remaining = current.deadline - now();
        if (remaining > 0) {
          current.timer = schedule(check, remaining);
          return;
        }
        attempt = null;
        onTimeout();
      }
      current.timer = schedule(check, timeout);
    },
    clear() {
      if (attempt) cancel(attempt.timer);
      attempt = null;
    },
  };
}

export function socketURL(pageURL) {
  const url = new URL("./ws", pageURL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url;
}

export function validSession(value) {
  return value && ["A", "B"].includes(value.seat) && validUnit(value.bet_unit) &&
    typeof value.room_code === "string" && value.room_code.length > 0 && value.room_code.length <= 128 &&
    typeof value.session_token === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.session_token);
}

export class AdmissionRejected extends Error {}

export async function admit({kind, input, key}) {
  let response, data;
  const uncertain = "The server did not confirm admission. Retry the same request. A server restart can erase its recovery record.";
  try {
    response = await fetch(kind === "create" ? "./api/rooms" : "./api/rooms/join", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Admission-Key": key},
      body: JSON.stringify(kind === "create" ? {bet_unit: input} : {room_code: input}),
      signal: AbortSignal.timeout(8000),
      mode: "same-origin",
      redirect: "error",
    });
    data = await response.json();
  } catch {
    throw new Error(uncertain);
  }
  if (!response.ok) {
    const message = {
      "403:origin not allowed": "Open the poker table from its local server address.",
      "404:room not found": "Room code not found. Check the code and try again.",
      "409:an active room already exists": "An active room already exists. Join with its room code.",
      "409:room is full": "This room already has two players.",
      "409:admission key conflict": "The recovery request conflicts with an existing admission.",
      "422:invalid admission key": "The admission recovery key is invalid.",
      "422:invalid request body": kind === "create"
        ? "Choose an even bet unit from 2 to 20." : "Enter a valid room code.",
    }[`${response.status}:${data?.detail}`];
    if (message) throw new AdmissionRejected(message);
    throw new Error(uncertain);
  }
  if (!validSession(data) || data.seat !== (kind === "create" ? "A" : "B")) {
    throw new Error(uncertain);
  }
  const {seat, room_code, session_token, bet_unit} = data;
  return {seat, room_code, session_token, bet_unit};
}

export class GameplayConnection {
  constructor({pageURL, token, onStatus, onFrame, Socket = WebSocket,
    schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
    cancel = handle => globalThis.clearTimeout(handle)}) {
    Object.assign(this, {pageURL, token, onStatus, onFrame, Socket, schedule, cancel});
    this.state = "idle";
    this.generation = 0;
    this.attempt = 0;
    this.terminal = false;
    this.socket = null;
    this.retry = null;
    this.timeout = null;
    this.suspensions = new Set();
    this.awaitingPong = false;
  }

  status(state) {
    this.state = state;
    this.onStatus(state);
  }

  connect() {
    if (this.socket || this.retry !== null || this.suspensions.size) return;
    const generation = ++this.generation;
    this.status(this.attempt ? "reconnecting" : "connecting");
    let socket;
    try {
      socket = new this.Socket(socketURL(this.pageURL));
    } catch {
      this.disconnected(generation);
      return;
    }
    this.socket = socket;
    const current = callback => event => {
      if (this.socket === socket && this.generation === generation) callback(event);
    };
    this.timeout = this.schedule(current(() => this.abortSocket(socket)), 4600);
    socket.addEventListener("open", current(() => {
      this.status("authenticating");
      this.send({type: "auth", token: this.token, protocol: "gameplay.v1"});
    }));
    socket.addEventListener("message", current(event => {
      const frame = decode(event.data);
      if (frame?.type === "error" && frame.code === "UNAUTHORIZED") {
        this.halt("unauthorized");
      } else {
        if (frame?.type === "pong" && this.awaitingPong) this.monitor(socket);
        this.onFrame(frame);
      }
    }));
    socket.addEventListener("close", current(event => {
      this.disconnected(generation, event.code);
    }));
  }

  disconnected(generation, code) {
    this.clearTimers();
    this.socket = null;
    if (code === 4000) {
      this.status("replaced");
    } else if (this.terminal || this.attempt >= 11) {
      this.status("offline");
    } else {
      this.status("reconnecting");
      this.retry = this.schedule(() => {
        if (this.generation !== generation) return;
        this.retry = null;
        this.connect();
      }, reconnectDelay(this.attempt++));
    }
  }

  abortSocket(socket) {
    if (this.socket !== socket) return;
    this.disconnected(this.generation);
    socket.close();
  }

  synchronized(terminal) {
    const first = this.state !== "connected";
    this.terminal = terminal;
    this.attempt = 0;
    if (first) {
      this.monitor(this.socket);
      this.status("connected");
    }
    return first;
  }

  monitor(socket) {
    this.clearTimers();
    this.timeout = this.schedule(() => {
      if (this.socket !== socket || !this.send({type: "ping"})) return;
      this.awaitingPong = true;
      this.timeout = this.schedule(() => this.abortSocket(socket), 4000);
    }, 6000);
  }

  send(payload) {
    if (this.socket?.readyState !== 1) return false;
    try {
      this.socket.send(typeof payload === "string" ? payload : JSON.stringify(payload));
      return true;
    } catch {
      this.abortSocket(this.socket);
      return false;
    }
  }

  clearTimers() {
    if (this.retry !== null) this.cancel(this.retry);
    if (this.timeout !== null) this.cancel(this.timeout);
    this.retry = this.timeout = null;
    this.awaitingPong = false;
  }

  halt(reason = "idle") {
    this.generation++;
    this.clearTimers();
    const previous = this.socket;
    this.socket = null;
    previous?.close();
    this.status(reason);
  }

  retryManually() {
    if (this.suspensions.size) return;
    this.halt();
    this.attempt = 0;
    this.connect();
  }

  setAvailable(source, available) {
    const wasSuspended = this.suspensions.size > 0;
    if (available) this.suspensions.delete(source);
    else this.suspensions.add(source);
    if (manualOnly.has(this.state)) return;
    if (!available && !wasSuspended) this.halt("offline");
    if (available && wasSuspended && !this.suspensions.size) this.retryManually();
  }
}
