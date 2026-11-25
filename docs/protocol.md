# Multiplayer integration contract

The README defines the agreed poker rules. The application owns admission,
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

The current engine can advance to showdown and settle a fold. Showdown
evaluation, payout, and a next-hand operation that preserves stacks and
alternates the button require future engine work and joint agreement. The
application uses the existing API for the first hand.

## Day 1 transport

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
a hand ends. Room requests accept only their documented
fields. Errors use a fixed `detail` string with 422 for invalid input, 404
for an unknown code, or 409 for an existing room or full room.

The WebSocket endpoint is `/ws`. Within five seconds of opening the socket,
send `{"type":"authenticate","session_token":"…"}` as the first JSON text
message. Send the token only in that frame. Invalid authentication closes with code 1008 and
no application payload. A successful handshake sends exactly the fields
`type: "room_status"`, `seat`, `bet_unit`, and `status` for the
authenticated seat. The socket stays open after its one-time snapshot. Any
additional application message closes it with code 1008. Connection presence,
exclusive access per seat, and gameplay updates are future work.

## Planned WebSocket messages

All commands after authentication use the server-bound seat. The client never
supplies a seat or a chip amount for an action. Extend the outbound allowlist
only through explicit message schemas.

| Direction and type | Allowed fields in addition to `type` |
| --- | --- |
| Client `action` | `action_id`, `hand_id`, `state_revision`, `action` (fold, check, call, bet, raise) |
| Client `ready` | `hand_id` identifying the completed hand |
| Server `snapshot` (initial, changed state, or reconnect) | `hand_id`, `state_revision`, `seat`, `status`, `bet_unit`, `button`, `phase`, `actor`, `stacks`, `contributions`, `pot`, `board`, `own_hole_cards`, `legal_actions`, `ready_seats`, `connected_seats`, `turn_remaining_ms` |
| Server `action_ack` | `hand_id`, `action_id`, `outcome_revision`, `accepted`, `error_code` |
| Server `error` | `code` drawn from a fixed catalog |
| Server `timer` | `hand_id`, `state_revision`, `actor`, `turn_remaining_ms` |
| Server `connection` | `hand_id`, `state_revision`, `connected_seats`, `paused` |
| Server `ready_status` | `hand_id`, `state_revision`, `ready_seats` |
| Server `result` | `hand_id`, `state_revision`, `reason`, `winner`, `stacks`, `awards`, optional `showdown_hole_cards` |

Serialize each recipient's snapshot separately. The board contains only
revealed community cards. Showdown is the only result that may carry both
hands. Fold and forfeit omit `showdown_hole_cards`. Deck data, unrevealed
cards, credentials, internal diagnostics, and raw engine objects stay on
the server.

## Planned coordination

- Assign a new hand ID at each successful deal. Maintain a monotonically
  increasing room revision for accepted authoritative transitions. Timer
  display updates can reference the current revision without changing it.
- Serialize requests and callbacks in the same room synchronization boundary.
  Revalidate the bound connection and resolve due transitions at server
  receipt. For a new action, check its hand, revision, match status, and
  turn. Apply through the engine. Commit the returned state on acceptance.
  Preserve authoritative game state on rejection and return an allowlisted
  error code. Send personalized views after releasing the room lock.
- Scope action IDs to the authenticated seat for the room lifetime. Match a
  repeated ID against the original hand, submitted revision, and action
  before checking current-turn or stale-revision conditions. Return its
  recorded acknowledgment when identical and reject conflicting reuse.
  Keep acknowledgments separate from snapshots. Clients render snapshots
  in revision order and never use an old acknowledgment to replace state.
- Use server monotonic time for a 30-second turn and a 20-second reconnect
  grace period. At a deadline the due transition wins. On timeout, check if
  legal or fold. Stale callbacks verify the hand, revision or timer identity
  before mutating state. Disconnect pauses the current turn regardless of
  who disconnected. A timely return with the seat's token gets the current
  private snapshot and resumes the saved remaining time. One missing
  player's grace expiration forfeits the match to the connected player.
  When both are absent, close without a winner at grace expiration. Agree
  on which grace deadline governs overlapping disconnects before implementing
  the two-disconnect path.
- After a hand ends, keep one Ready flag per seat for that hand. Duplicate
  Ready requests are idempotent. Begin the next hand only with both Ready,
  an open match, and enough chips to post the full big blind while retaining
  at least one chip. The engine must carry stacks forward and alternate
  the button for that deal.
