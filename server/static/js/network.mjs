import {decode, validUnit} from "./state.mjs";

export const reconnectDelay = attempt => Math.min(250 * 2 ** attempt, 2000);

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

export async function admit(kind, input) {
  let response;
  try {
    response = await fetch(kind === "create" ? "./api/rooms" : "./api/rooms/join", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(kind === "create" ? {bet_unit: input} : {room_code: input}),
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    throw new Error("The server did not confirm admission. Check your connection. If the request reached the server, an already allocated seat may need a server restart.");
  }
  if (!response.ok) {
    const message = {
      404: "Room code not found. Check the code and try again.",
      409: kind === "create" ? "An active room already exists. Join with its room code." :
        "This room already has two players.",
      422: kind === "create" ? "Choose an even bet unit from 2 to 20." : "Enter a valid room code.",
    }[response.status];
    throw new Error(message ?? "The server could not confirm admission. The seat may already have been allocated.");
  }
  const data = await response.json().catch(() => null);
  if (!validSession(data)) throw new Error("The server returned an invalid admission response.");
  const {seat, room_code, session_token, bet_unit} = data;
  return {seat, room_code, session_token, bet_unit};
}

export class GameplayConnection {
  constructor({pageURL, token, onStatus, onFrame, Socket = WebSocket,
    schedule = setTimeout, cancel = clearTimeout}) {
    Object.assign(this, {pageURL, token, onStatus, onFrame, Socket, schedule, cancel});
    this.state = "idle";
    this.generation = 0;
    this.attempt = 0;
    this.terminal = false;
    this.socket = null;
    this.retry = null;
    this.timeout = null;
  }

  status(state) {
    this.state = state;
    this.onStatus(state);
  }

  connect() {
    if (this.socket || this.retry !== null) return;
    const generation = ++this.generation;
    this.status(this.attempt ? "reconnecting" : "connecting");
    const socket = new this.Socket(socketURL(this.pageURL));
    this.socket = socket;
    const current = callback => event => {
      if (this.socket === socket && this.generation === generation) callback(event);
    };
    this.timeout = this.schedule(current(() => socket.close()), 4600);
    socket.addEventListener("open", current(() => {
      this.status("authenticating");
      this.send({type: "auth", token: this.token, protocol: "gameplay.v1"});
    }));
    socket.addEventListener("message", current(event => {
      const frame = decode(event.data);
      if (frame?.type === "error" && frame.code === "UNAUTHORIZED") {
        this.halt("unauthorized");
      } else {
        this.onFrame(frame);
      }
    }));
    socket.addEventListener("close", current(event => {
      this.clearTimers();
      this.socket = null;
      if (event.code === 4000) {
        this.status("replaced");
        return;
      }
      if (this.terminal || this.attempt >= 11) {
        this.status("offline");
        return;
      }
      this.status("reconnecting");
      this.retry = this.schedule(() => {
        if (this.generation !== generation) return;
        this.retry = null;
        this.connect();
      }, reconnectDelay(this.attempt++));
    }));
  }

  synchronized(terminal) {
    const first = this.state !== "connected";
    this.terminal = terminal;
    this.attempt = 0;
    this.clearTimers();
    if (first) this.status("connected");
    return first;
  }

  send(payload) {
    if (this.socket?.readyState !== 1) return false;
    try {
      this.socket.send(typeof payload === "string" ? payload : JSON.stringify(payload));
      return true;
    } catch {
      this.socket.close();
      return false;
    }
  }

  clearTimers() {
    if (this.retry !== null) this.cancel(this.retry);
    if (this.timeout !== null) this.cancel(this.timeout);
    this.retry = this.timeout = null;
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
    this.halt();
    this.attempt = 0;
    this.connect();
  }
}
