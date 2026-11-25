# Multiplayer integration contract

The README describes the implemented poker rules. The target draft proposes a different contract. [Target rules](rules.md) The application owns admission,
seat credentials, transport, and future match coordination. The engine owns
the authoritative immutable state and transitions for a poker hand. The browser
renders the server's views and submits requests.

## Engine boundary

The existing engine exposes `new_game(bet_unit=10, deck=None)`,
`legal_actions(state, player)`, and `apply_action(state, player, action)`.
`new_game` deals immediately, posts blinds, and selects A as the first actor.
It accepts a fixed full deck for fixtures. `legal_actions` returns the
affordable legal action names for that seat. `apply_action` returns
`ActionResult(accepted, state, error)`. Rejection returns the same state object.
Acceptance returns a new immutable state.

The room stores admission data and, once B joins, the initial engine state.
The room code grants admission to the vacant B seat. The server assigns A to
the creator and B to the joiner, then authenticates future commands against
the separate private token issued to that seat. Creation leaves the hand
absent. A per-app lock serializes creation, guest allocation, first-hand
initialization, and authentication reads. B's session and the engine state
are published together after initialization succeeds. The bet unit is fixed
at creation, a conservative choice within the README's requirement to choose
it before B joins.

The engine settles showdown and folds. A paid showdown has
`phase="showdown"` and a zero pot. At showdown, `winner=None` means a tie.
A fold sets `phase="finished"`. `match_winner` records a terminal outcome
when the current rule prevents the next deal. Keep that distinct from the
hand winner.

`apply_action(state, player, action, *, deck=None)` accepts the optional
deck only when the second Ready action starts a hand. The engine owns
`ready_players`, the stack-preserving deal, button rotation, and
`hand_number`. Outside the active betting phases, `legal_actions` may
return `ready` even when there is no actor. Engine errors remain plain
strings. The coordinator uses `apply_action` for betting and Ready.

## Implemented transport

Run one Uvicorn worker and one app instance. The in-memory room lives until
process exit. Separate factory calls provide isolated state for tests.

| Request | Success |
| --- | --- |
| `GET /health` | 200 with `{"status":"ok"}` |
| `POST /api/rooms` with `{"bet_unit":10}` | 201 with A's admission |
| `POST /api/rooms/join` with `{"room_code":"…"}` | 200 with B's admission |

Admission fields are `room_code`, `seat`, `session_token`, `bet_unit`,
and `status`. Successful admission responses carry `Cache-Control: no-store`.
Status is `waiting` or `ready`, where `ready` means both seats are allocated
and the first hand has been initialized. The future Ready flags apply after
a hand ends. Room requests accept only their documented fields. Errors use
a fixed `detail` string with 422 for invalid input, 404 for an unknown code,
or 409 for an existing room or full room.

The lobby routes share the same two seats and credentials.

| Request | Success |
| --- | --- |
| `POST /api/table` | 201 with `room_code`, `seat`, and `session_token`. Uses bet unit 10. |
| `POST /api/join` with `{"room_code":"…"}` | 201 with `seat` and `session_token`. |
| `GET /api/session` with `Authorization: Bearer <token>` | 200 with `seat` and `table_ready`. |

Lobby failures preserve the coded `detail` object for `TABLE_EXISTS`,
`TABLE_FULL`, `INVALID_CODE`, and `UNAUTHORIZED`. Both join routes
initialize the same engine hand and notify subscribed lobby sockets.

The WebSocket endpoint is `/ws`. Within five seconds of opening the socket,
send `{"type":"authenticate","session_token":"…"}` as the first JSON text
message. Send the token only in that frame. Invalid authentication closes
with code 1008 and no application payload. A successful handshake sends
exactly `type: "room_status"`, `seat`, `bet_unit`, and `status` for the
authenticated seat. The socket stays open after its one-time snapshot.
An additional application message closes it with code 1008.

The lobby handshake uses `{"type":"auth","token":"…"}`. Its personalized
`lobby` message contains `your_seat`, `table_ready`, and `connected` flags
for A and B. Lobby sockets get presence and admission updates, replace an
old lobby socket on the same seat, and accept `ping` with a `pong` reply.
Other well-formed requests receive `NOT_READY`. The `room_status` mode
provides a one-time status snapshot without participating in lobby presence.
Both modes accept local browser origins and non-browser clients that omit
Origin, and both cap inbound messages at 4,096 UTF-8 bytes. Valid auth
messages select their reply format. The legacy `server.main:app` launch
also keeps the lobby error response for ambiguous malformed first
messages. The `poker.server:create_app` launch closes those without a payload.

## Day 2 gameplay protocol

Use the same persistent `/ws` endpoint. Send this first as a JSON text frame
within five seconds of connecting.

```json
{"type":"auth","token":"…","protocol":"gameplay.v1"}
```

The token binds the connection to one seat. A new authenticated connection
replaces the old persistent connection for that seat. The old connection
closes with 4000. Replacement participates in the same room transaction as
commands. A command that commits first remains valid. A replacement that
commits first revokes the old connection before its next command can apply.
Old-socket teardown can remove only its own registration. A new connection
always gets a current personalized snapshot. Existing two-field `auth`
clients continue receiving lobby broadcasts. The one-time `authenticate`
status path remains available.

### Commands and acknowledgments

```json
{"type":"action","action_id":"c1","hand_id":1,"expected_revision":1,"action":"call"}
{"type":"ready","action_id":"r1","hand_id":1,"expected_revision":9}
{"type":"snapshot_request"}
{"type":"ping"}
```

These are four separate frames. An action is `fold`, `check`, `call`,
`bet`, or `raise`. The engine determines the amount and legality. Ready
uses the same command identity, and its first accepted transition updates
only one Ready flag. The other seat's accepted Ready deals the next hand.
`action_id` is 1–64 ASCII letters, digits, underscores, or hyphens.
`hand_id` is a positive integer and `expected_revision` a nonnegative
integer, both at most 2^53−1. Booleans, additional fields, including a
seat or an amount, missing fields, unsupported commands, non-object
JSON, invalid JSON, and binary frames are invalid. The application-level
message limit is 4,096 UTF-8 bytes. Uvicorn can close oversized frames at
the transport layer before application validation.

A well-formed command returns exactly these acknowledgment fields, with
`error_code` set to null for acceptance.

```json
{"type":"action_ack","hand_id":1,"action_id":"c1","outcome_revision":2,"accepted":true,"error_code":null}
```

| Error code | Meaning |
| --- | --- |
| `INVALID_MESSAGE` | A malformed or unsupported frame. Gameplay replies with `{"type":"error","code":"INVALID_MESSAGE"}`. |
| `UNAUTHORIZED` | Invalid token on persistent auth. An error precedes close 1008. |
| `NOT_READY` | No hand exists, or an existing lobby-only client sent a gameplay command. |
| `WRONG_HAND` | The command targets a different hand and has no eligible recorded outcome. |
| `STALE_REVISION` | The supplied revision is older or newer than the room revision. |
| `WRONG_TURN` | The authenticated seat cannot act on this betting turn. |
| `ILLEGAL_ACTION` | The engine rejected the requested action or Ready transition. |
| `HAND_COMPLETE` | The betting hand has settled. |
| `MATCH_COMPLETE` | The engine ended the match. |
| `REPLAY_CONFLICT` | The same replay key was used with different validated content. |
| `REPLAY_CAPACITY` | The seat reached the per-hand command budget. |

`WRONG_HAND` and `STALE_REVISION` on a new command send a current
snapshot to the caller after the acknowledgment. A rejected command does
not broadcast a transition. Ping yields `{"type":"pong"}`; a snapshot
request sends the current personalized snapshot. These reads do not
change the revision. Engine error text and raw exception details stay
on the server.

### Personalized snapshots

The waiting snapshot has exactly `type: "snapshot"`, `status: "waiting"`,
`seat`, `bet_unit`, and `revision: 0`. Admission of B atomically creates
hand 1 at revision 1 and sends each gameplay socket its own view. A dealt
snapshot sets `status: "ready"` and adds:

| Fields | Meaning |
| --- | --- |
| `hand_id`, `phase`, `button`, `actor` | Engine hand number, current phase, dealer, and acting seat or null. |
| `stacks`, `contributions`, `pot`, `raise_count`, `board` | Public betting values, per-seat chip maps, and revealed board only. |
| `ready_seats` | Public per-seat Ready flags for the settled hand. |
| `own_hole_cards`, `legal_actions`, `can_ready` | The recipient's cards, betting actions, and separate Ready eligibility. |
| `result`, `match_winner` | Hand result or null, and terminal match winner or null. |

Paid showdown has result kind `showdown_win` or `showdown_tie`, a winner
seat or null for tie, and `showdown_hole_cards` for both players. A fold
result is `{"kind":"fold_win","winner":"B"}` when B wins. Active hands
have null result. A null engine winner means tie only at paid showdown.
Opponent hole cards are withheld at every other phase, including folds.
The deck, undealt board, tokens, and internal objects stay on the server.
Presence remains in lobby messages and is independent of gameplay revision.

### Commit, replay, and delivery

The room's synchronous lock protects admission, current-socket ownership,
replay, the engine transition, revision, and enqueue order. WebSocket attach,
detach, and queue operations run on the application's event loop. No
network send or await occurs while the room lock is held. In the same
transaction the coordinator enqueues the caller's acknowledgment, then
both views built from the same committed room. A changed engine state
increments revision once. Revisions do not reset between hands.

The replay key is `(seat, hand_id, action_id)`. Compare the full validated
command, including its type, action and expected revision. An identical
retry returns the exact stored acknowledgment, including its older
`outcome_revision`, before checking the current revision. It sends no
new snapshot and never calls the engine. Store structurally valid
current-hand results, including rejected commands. Malformed frames,
pre-deal requests, unseen commands for the wrong hand, replay conflicts,
and over-capacity requests are outside that cache. Retain the current
and previous hands with a cap of 256 distinct IDs per seat per hand
(1,024 records maximum across both seats and both hands). Reject a new
ID at the cap without evicting previous IDs. A seat that exhausts its
budget cannot submit a new command in that hand.

Each persistent connection has its own FIFO queue of 32 frames and one
writer. A stalled client cannot block a room commit or another writer.
Overflow removes its command authority and requests close 1013. A
client whose acknowledgment was interrupted can reconnect, read the
current snapshot, and retry the same ID while its hand is retained.
Queue contents stay with the old connection during replacement.
Structured cancellation ends the reader and writer together. This is
one in-memory app on one worker.

### Future clocks and recovery

Pending joint approval, use server monotonic time and an exclusive
30-second turn deadline. On expiry, check when legal and otherwise fold.
Each absent seat has an independent exclusive 20-second deadline.
Pause the turn and preserve its remaining time while either seat is
absent. On timely return of both seats, resume that remaining time. At
the earliest applicable expiry, close without a winner if both remain
absent. If only one is absent, that seat forfeits. Route authoritative
callbacks through the same room boundary and invalidate callbacks tied
to an old hand or connection. Day 2 implements socket replacement
without game clocks, disconnect deadlines, or forfeits.
