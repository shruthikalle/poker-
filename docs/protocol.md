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
or 409 for an existing room or full room. A supplied foreign browser
origin is rejected with 403.

### Recovering canonical admission

The two canonical room routes accept an optional `Admission-Key`
header with exactly 64 lower-case hexadecimal characters. The browser
generates this bearer recovery credential from 32 cryptographically
random bytes and keeps it out of URLs. The request identity is the
operation and its validated value (numeric bet unit for create, exact
case-sensitive room code for join).

Under the room lock, the server either allocates the seat and records
the original response, replays the same response and HTTP status, or
returns 409 for a key bound to a different request. Malformed or
duplicate headers receive 422. An unknown well-formed key follows
ordinary allocation rules. It cannot recover seats that another
credential reserved. Existing originless clients and calls without this
header retain their admission behavior. The legacy lobby routes do
not use keyed admission.

The room retains a digest and the original successful response for each
keyed seat, up to two records. Rejections do not consume storage.
Replay does not initialize a new hand, post blinds, publish another
lobby event, or update the historical admission body. Recovering A's
admission can still report `waiting` after B joins. Authenticate on the
socket to obtain current state. Records expire with process exit. After
a restart an explicitly retried create may create a new room if the
process is empty. A retried join still needs its original room code.
Neither replay nor session recovery persists across restart.

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
Both modes and gameplay accept same-origin local browsers and clients
that omit Origin. WebSockets cap inbound messages at 4,096 UTF-8 bytes. Valid auth
messages select their reply format. The legacy `server.main:app` launch
also keeps the lobby error response for ambiguous malformed first
messages. The `poker.server:create_app` launch closes those without a payload.

## Gameplay protocol

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
Old-socket teardown can remove only its own registration. A new gameplay connection
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
| `NOT_READY` | Gameplay has not activated, or an existing lobby-only client sent a gameplay command. |
| `MATCH_PAUSED` | A current gameplay participant is absent. |
| `WRONG_HAND` | The command targets a different hand and has no eligible recorded outcome. |
| `STALE_REVISION` | The supplied revision is older or newer than the room revision. |
| `WRONG_TURN` | The authenticated seat cannot act on this betting turn. |
| `ILLEGAL_ACTION` | The engine rejected the requested action or Ready transition. |
| `HAND_COMPLETE` | The betting hand has settled. |
| `MATCH_COMPLETE` | The engine ended the match. |
| `REPLAY_CONFLICT` | The same replay key was used with different validated content. |

`WRONG_HAND` and `STALE_REVISION` on a new command send a current
snapshot to the caller after the acknowledgment. A rejected command does
not broadcast a transition. Ping yields `{"type":"pong"}`; a snapshot
request sends the current personalized snapshot. These reads do not
change the revision. Engine error text and raw exception details stay
on the server.

### Personalized snapshots

A waiting snapshot has `type: "snapshot"`, `status: "waiting"`,
`seat`, `bet_unit`, `revision: 0`, and the lifecycle fields below. Admission of B atomically creates
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
Gameplay snapshots include the following public lifecycle fields. The
existing `status` still describes admission. `lifecycle` describes the
current match or hand context.

| Fields | Meaning |
| --- | --- |
| `lifecycle` | `waiting`, `awaiting_players`, `active`, `paused`, `between_hands`, or `complete`. |
| `lifecycle_revision`, `presence` | Monotonic lifecycle version and gameplay presence booleans for A and B. Terminal presence is frozen at the outcome. |
| `turn_clock` | `status` is `running`, `paused`, or `inactive`. `acting_player` and `remaining_ms` are null when inactive. |
| `disconnect_grace` | A and B each map to null or an object with `remaining_ms`. |
| `match_result` | Null or `{"reason":"forfeit","winner":"B"}`, for example. The other reasons are `both_absent`, `engine`, and `engine_error` for a controlled invariant failure. |
| `last_automatic_action` | Null or `source: "server"`, `reason: "turn_timeout"`, `hand_id`, `seat`, and `action`. Cleared at the next hand. |

The existing `revision` advances only for committed engine transitions,
including automatic actions. `lifecycle_revision` advances for gameplay
presence changes, including pause and resume, and for match termination.
One logical lifecycle transition advances it once. Countdown samples
can differ at the same revision pair. A client displays running time
using elapsed local time since receiving the latest snapshot. A paused
time is constant. Only the server decides expiration. Legal actions
and Ready eligibility are suppressed while inactive for lack of
presence, paused, or terminal.

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
retry returns the exact stored acknowledgment after deadline reconciliation
and before command revision checks. Accepted records survive through the
previous hand. Rejected records use a separate per-seat FIFO of 256 per hand
through the same two-hand window. A rejected ID outside that FIFO can be
submitted as new and is validated against the current hand and revision.
Conflicting reuse of any retained identifier is rejected. Wrong-hand
requests with no retained record never reach the engine. Malformed frames,
pre-deal requests, and replay conflicts do not enter either ledger.

Accepted memory is bounded by the engine. At most four actions resolve
preflop after the blinds. At most five resolve each other street, including
an optional opening check, a bet, two raises, and a call. A fold ends
the hand early. Two Ready transitions give at most 21 accepted mutations
per hand across both seats. Automatic actions take an engine turn without
entering a client ledger.

Each persistent connection has its own FIFO queue of 32 frames and one
writer. A stalled client cannot block a room commit or another writer.
Overflow removes its command authority and requests close 1013. A
client whose acknowledgment was interrupted can reconnect, read the
current snapshot, and retry the same ID while its hand is retained.
Queue contents stay with the old connection during replacement.
Structured cancellation ends the reader and writer together. This is
one in-memory app on one worker.

### Timing and recovery

The default turn is 30 seconds and each absent seat has an independent
20-second grace period. Durations and clock are injectable only at
app construction. A hand can be dealt before both gameplay sockets
authenticate. The first countdown starts when both are present.
A never-connected seat has no grace deadline before activation.
After activation, absence also matters between hands awaiting Ready.

Only current gameplay sockets count. Gameplay-to-gameplay replacement
transfers ownership without creating an absence. A lobby-only replacement
removes gameplay presence. A further lobby replacement preserves any
existing grace deadline. Status-only sockets never enter the registry.
A failed authentication leaves presence untouched. Writer failure and
overflow revoke gameplay presence. Old cleanup has no authority over
a replacement connection.

The coordinator samples monotonic nanoseconds after acquiring the room
lock. At or after a deadline it reconciles expiry before processing input
or a connection change. At turn expiry it queries engine legality, then
checks if legal or folds otherwise. A newly active turn gets its full
duration from the transition time. Delayed scheduler wakeups cannot
admit a late command. An expiry broadcast can precede an acknowledgment
when input itself triggers reconciliation.

Disconnect saves the exact remaining turn duration. The other seat's grace
deadline is independent. Both timely returns are necessary to resume.
The earliest remaining grace deadline governs. If both seats are still
absent at expiry the match closes without a winner. With one absent seat,
that seat forfeits and the present seat wins. Authenticated late observers
can read a terminal snapshot with their own cards. Gameplay cannot resume.

A transport terminal outcome preserves the last engine state and any
outstanding pot. It creates neither a new hand result nor a payout.
Hand result, match result, and phase stay distinct. Transport terminal
messages withhold the opponent's cards. There is no room reset endpoint,
so a new match after terminal completion requires restarting the server.

One lifespan-owned scheduler waits for the earliest deadline or a
state-change event and is canceled on shutdown. Wakeups carry no
cached acting seat or executable callback. Each one rechecks the current
deadline under the room lock, so stale wakeups cannot act on earlier hands
or paused turns. Nanoseconds are internal. Wire time is ceiling-rounded
remaining milliseconds, without process-local timestamps. Timing tests
use a manual clock and the live smoke fixture uses shorter durations.

The configurable poker rules are preserved and the final joint rules and
forfeit-specification approval remains pending.


## Browser client

FastAPI serves the browser at `/` and only the frontend directory under
`/assets`. HTTP and WebSocket URLs are derived from the page origin.
The gameplay authentication, actions, Ready, and recovery schemas above
also serve the browser. Browser admission and WebSocket upgrade require a
matching scheme, host, and port when the Origin header is present.
Launch on `127.0.0.1` or `localhost` and use the same address throughout.
The origin check supplements authentication and is independent of the
gameplay message schemas and engine.

The browser requires an authenticated snapshot before enabling gameplay.
It discards a snapshot if either engine `revision` or
`lifecycle_revision` regresses. Each server field is monotonic within
the room. If both stay equal the arrival can refresh the clock sample.
The current WebSocket generation alone may publish state. A terminal
snapshot remains terminal for that browser session.

Before admission, the browser saves the pending operation, input, and
recovery key in per-tab `sessionStorage`. Ambiguous failures retain that
record and offer a deliberate retry, including after refresh. A definitive
rejection clears it. On success the browser replaces the recovery record
with seat, room code, bet unit, token, and any unresolved wire command.
Snapshots and cards stay out of storage. Browser developer tools and
same-origin scripts can read the credentials, and a duplicated tab may
inherit them.
When replaced, the tab stops automatic reconnect attempts. A manual
reconnect is an explicit choice to reclaim that seat. Leaving clears the
saved session and can trigger ordinary disconnect expiry.

Each seat's tab sends at most one unresolved mutation at a time. A success
acknowledgment waits for a snapshot at or beyond its outcome revision.
A rejection requests a snapshot and requires a deliberate new action.
If delivery is ambiguous, the client resends the exact stored payload on
a newly authenticated connection after synchronizing. Each transmission
gets one 4.5-second monotonic watchdog. Snapshots and acknowledgments
cannot move that deadline. After two automatic watchdog recoveries the
tab asks for a deliberate reconnect while retaining an ambiguous
command. It drops unresolved gameplay at terminal results and retires
commands outside server replay retention.
It never changes a pending action ID or claims a successful send committed
the engine mutation. Server replay and revision enforcement remain
authoritative.

With an authenticated connection the client sends a heartbeat after
six seconds and allows four seconds for a reply. Connection retries
back off from 250 ms to 2 seconds and stop after eleven automatic
attempts per failure sequence. Browser network and page events are
hints. They never confer authority or reclaim an explicitly replaced
seat. Invalid sessions stop retrying and require leaving the old session.

Turn and grace presentation use elapsed `performance.now()` time from
the latest sampled snapshot. A paused turn retains its sampled amount.
The browser requests a fresh snapshot on visibility return and never
sends an automatic fold or forfeit. A sampled countdown may lag the
server by network transit time and browser scheduling. Without a current
authenticated snapshot, the latest view is marked last known and
actions, turn estimates, and grace clocks are suspended. Terminal views
hide the historical presence record and render the server's match result
separately from a settled hand result.

This local educational app gates cards and credentials by seat and uses
only local browser assets. It assumes a trusted machine, browser, and
same-origin code. Anyone who acquires either bearer credential can act
as the corresponding player. Loopback HTTP provides no protection
against network interception if deployed beyond its intended local
environment.
