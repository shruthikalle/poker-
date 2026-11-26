import {validSession} from "./network.mjs";
import {readPending} from "./state.mjs";

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

export function persist(storage, session, pending) {
  try {
    if (session) storage.setItem(KEY, JSON.stringify({session, wire: pending?.wire ?? null}));
    else storage.removeItem(KEY);
    return true;
  } catch {
    return false;
  }
}
