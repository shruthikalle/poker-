import {validSession} from "./network.mjs";
import {readPending, validUnit} from "./state.mjs";

const KEY = "heads-up-session-v1";

export function restore(storage) {
  try {
    const data = JSON.parse(storage.getItem(KEY));
    if (validSession(data?.session)) {
      const {seat, room_code, session_token, bet_unit} = data.session;
      return {
        session: {seat, room_code, session_token, bet_unit},
        pending: readPending(data.wire),
      };
    }
  } catch {
    // Storage can be unavailable or hold an obsolete entry.
  }
  return {session: null, pending: null};
}

export function newAdmission(kind, input, crypto = globalThis.crypto) {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const key = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return {kind, input, key};
}

export function restoreAdmission(storage) {
  try {
    const {kind, input, key} = JSON.parse(storage.getItem(KEY)).admission;
    const valid = kind === "create" ? validUnit(input)
      : kind === "join" && typeof input === "string" && input.length > 0 && input.length <= 128;
    if (valid && typeof key === "string" && /^[0-9a-f]{64}$/.test(key)) {
      return {kind, input, key};
    }
  } catch {
    // Missing, obsolete, or unavailable tab state.
  }
  return null;
}

export function persist(storage, session, pending, admission = null) {
  try {
    if (session) storage.setItem(KEY, JSON.stringify({session, wire: pending?.wire ?? null}));
    else if (admission) storage.setItem(KEY, JSON.stringify({admission}));
    else storage.removeItem(KEY);
    return true;
  } catch {
    return false;
  }
}
