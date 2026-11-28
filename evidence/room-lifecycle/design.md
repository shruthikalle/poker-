# Room retirement and generation boundaries

The [historical feasibility note](../application-quality/rematch-feasibility.md)
identified one allocated room per process. The [live baseline](baseline.txt)
showed that both the legacy and PDF defaults kept that room occupied after
forfeit. The PDF checkpoint introduced 500-chip stacks and fixed 5/10
blinds. Retirement works at the application boundary and reuses the engine
factory for either ruleset.

| Design | Isolation and cleanup | Effect on the existing application |
| --- | --- | --- |
| Reset coordinator fields in place | A field reset can leave an old socket callback or timer wakeup with authority over the next room. | Few edits initially. Every deferred path would need an independent ownership check. |
| New coordinator per room | Per-room state is naturally scoped. An application-level router and scheduler would still need to fence delayed callbacks and retire the old scheduler. | Replaces the current coordinator references and introduces a scheduler handoff. Tests must exercise both old and new scheduler lifetimes. |
| One coordinator with a generation check | Connection ownership and scheduler wakeups bind to their originating generation. Retirement clears bounded state in one transaction. | Retains the current app factory, queue delivery model and lifespan scheduler. Deterministic clocks and delayed callbacks can exercise the boundary directly. |

The third design uses the room manager's existing reentrant lock as the
single synchronization boundary. The coordinator takes it before checking
connection ownership, reconciling time, or changing engine state. Admission
validates its supplied context and allocates under the same lock. Release
checks the current socket, terminal state and server clock, then removes the
room, rotates the generation, clears replay and timing, signals the old
status observers and revokes the registered sockets. Queue writers and
socket closes run outside the lock. Even if an old writer has an in-flight
frame, that frame belongs to the old socket and carries no authority into
the next room. The only scheduler rejects a wakeup captured for an earlier
generation before it can apply any action.

The application derives progression from existing timing and engine state.
An empty manager can allocate a waiting room. Joining creates hand 1, and
two authenticated gameplay sockets start its clock. Established matches can
pause, resume, finish a hand and advance, or reach a terminal match. A
terminal match tracks distinct seat acknowledgments. Both acknowledgments
enable release immediately. One enables release at the exact 60-second
mark from the monotonic terminal transition. Eligibility enables a separate
release command. A terminal room with no acknowledgment stays reserved
even after the retention period. Release returns the process to its empty
state. The existing terminal state remains observable until that command.

Admission stores at most two successful recovery records. A fixed-size
tombstone list would let an arbitrarily old key through after eviction.
Instead, the current context is derived from the in-memory process secret
and generation. All scoped requests prove which generation they belong to
before recovery or allocation. Retirement retains no tombstones or old
bearer tokens. The token's authenticated generation lets a valid old token
receive a retirement close during same-process browser recovery, with no
private data. This is a single-process design. Restart resets all room
state and intentionally reopens startup compatibility for unscoped legacy
clients. The [protocol](../../docs/protocol.md) specifies what happens to
both old and scoped requests after release or restart.
