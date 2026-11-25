# Day 1 multiplayer protocol

Status: Srishruthik's draft for partner review, November 25, 2026. HTTP admission, token-authenticated WebSocket lobby messages, and a replacement-safe connection registry now exist. Gameplay actions, game snapshots, and the browser do not. It uses the target rules in [rules.md](rules.md).

## Ownership and session lifecycle

The engine owns cards, legal actions, betting, and settlement. The FastAPI server owns table membership, sessions, connections, clock, action IDs, hand ID, revision, and message delivery. Browsers only request actions and render server-provided snapshots.

- `POST /api/table` creates the one in-memory table and reserves seat A. Return a random room code, a private session token, and `seat: "A"`. Do not deal or start a turn timer yet.
- `POST /api/join` accepts a room code, fills seat B, and returns B's distinct private token and seat. Reject unknown codes and a third seat without changing table state. A code alone cannot reclaim an occupied seat.
- `GET /api/session` with `Authorization: Bearer <token>` returns only that token's seat and whether both seats are filled. It is a small admission milestone endpoint, not a game snapshot.
- `WS /ws` begins with `{ "type": "auth", "token": "..." }`. The server binds the socket to the token's seat and ignores client-selected seat identity. A valid reconnect replaces the old socket safely and receives a fresh personal snapshot. Invalid tokens receive no game state.
- Until engine integration, an authenticated socket receives a typed `lobby` message with `your_seat`, `table_ready`, and public A/B connection flags. Gameplay requests receive `NOT_READY` and never call the old-rule engine. This is the implemented Day 3 boundary, not the final game snapshot.
- Keep tokens out of URLs, later state messages, logs committed as evidence, and opponent messages. In-memory sessions do not survive a server restart.
- Validate origin, message size, JSON shape, allowed fields, and action names. Never expose raw exceptions.

## Action request and ordering

```json
{"type":"action","action_id":"a1","hand_id":1,"expected_revision":1,"action":"call"}
```

The server assigns increasing hand IDs and revisions. The first dealt hand starts at hand ID 1, revision 1. Each accepted transition, including the first Ready flag, increments revision. New hands increment both. Before B joins, there is no hand ID, actor, or turn timer.

Under a per-table lock: authenticate, process any expired deadline first, check replay cache, validate hand ID and expected revision, call the engine, commit an accepted new state, increment revision, and prepare a personal snapshot for each seat. Release the lock before sending to sockets. Recheck all state under the lock so competing actions cannot both apply to one turn.

Replay cache key: `(seat, hand_id, action_id)`. Store the original payload and result. An identical retry returns its recorded result without another transition, even after revision changes. Reusing an ID for another payload returns `DUPLICATE_CONFLICT`. Bound the cache but retain entries for the hand's retry window.

Rejected requests leave game state, room state, deadline, and revision unchanged, except when an authoritative deadline had already expired and is processed first. Return a safe error and current personal snapshot. Map internal engine errors to stable public codes.

## Personal snapshots and errors

Build separate allowlisted `state` messages for A and B. Public fields: `hand_id`, `revision`, `phase`, `dealer`, `actor`, revealed `board`, `pot`, `stacks`, street commitments, result, connection status, and remaining turn seconds. Private fields: `your_seat`, `your_cards`, and `legal_actions`. Before showdown, never include opponent hole cards. At showdown, `revealed_opponent_cards` may contain them. A fold or forfeit never reveals them. Never include deck, burn cards, other token, or raw engine objects.

```json
{"type":"state","hand_id":1,"revision":1,"phase":"preflop","dealer":"A","actor":"A","board":[],"pot":15,"stacks":{"A":495,"B":490},"street_commitments":{"A":5,"B":10},"your_seat":"A","your_cards":["As","Ah"],"legal_actions":["fold","call","raise"],"opponent_card_count":2,"remaining_turn_seconds":30}
```

The example shows message shape and hand-calculated chip values; its cards are illustrative, not a committed fixture. Both seats must receive identical public fields at the same revision. Clients ignore older revisions. `error` messages include a stable code, safe text, supplied action ID, and current revision, but no hidden state. Proposed codes: `INVALID_MESSAGE`, `UNAUTHORIZED`, `TABLE_FULL`, `WRONG_TURN`, `ILLEGAL_ACTION`, `STALE_REVISION`, `WRONG_HAND`, `DUPLICATE_CONFLICT`, `NOT_READY`, and `HAND_COMPLETE`.

## Timers and reconnects

The server starts a 30-second clock for each turn. At the exclusive deadline, check if legal; otherwise fold. An action at or after the deadline loses to the timeout. Browser countdowns are informational.

If either seat disconnects, pause the hand and preserve the remaining turn time. Allow 20 seconds to reconnect. A valid reconnect before that exclusive deadline restores the seat and resumes the saved turn time. At the deadline, a missing player forfeits if the other is connected. If both disconnect during grace, close the room without a winner. Ignore stale timeout callbacks after an action, reconnect, or hand change. Tests use a controllable clock rather than real sleeps.

## Day 1 acceptance

Both partners must approve the message fields and engine boundary before parallel implementation. Decide whether hand ID and revision stay server-owned as proposed, and whether the engine returns structured illegal-action reasons; the current `apply_action` API has neither version handling nor stable error codes.

First integration checks: distinct seats/tokens, third join rejection, invalid token cannot subscribe or act, wrong-turn action changes nothing, each initial snapshot contains only its owner's cards, and no outbound message contains deck or opponent cards before showdown. Later checks cover retries, stale and concurrent actions, timers, reconnect, fold privacy, and consecutive hands.
