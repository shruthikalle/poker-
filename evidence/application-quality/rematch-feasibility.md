# Match lifecycle options

[RoomManager](../../poker/rooms.py) owns one room, two seat identities
and at most two successful admission recoveries. The second admission
deals hand 1. [GameCoordinator](../../server/coordinator.py) owns active
connections, engine and lifecycle snapshots, per-hand replay records,
and scheduler state. A terminal room remains observable. There is no
room release endpoint. Restarting clears the room and its credentials.

| Option | Application consequences | Complexity and risk |
| --- | --- | --- |
| Restart process | Existing tokens, admission keys, connections, clocks and replay records all cease to apply. A new room receives a new code and new seats. | Low implementation cost. Player interruption and a manual operator step. |
| Close a terminal room and create a fresh one | Release only a completed room under the same transaction that retires connections and session tokens. Invalidate old admission keys without letting an old create retry silently create a new table. Allocate fresh credentials and code. Tag or fence queued callbacks with room identity. | Medium effort, with risky races at room release, delayed close and recovery. Reuse the existing engine initialization. |
| Mutual rematch in the same room | Require separate consent from both current authenticated seats. Keep seat tokens and public room code. Introduce a match identity in actions, snapshots, and replay keys. Reset admission's meaning to seat recovery only. Fence queued callbacks and browser state by match identity. | Higher effort. Wire clients and browser storage must understand the new match identity. Joint policy needed for initial stack, dealer and bet unit. |

Fresh-room rollover is the narrower first change. Keep the old terminal
view until an explicit release. Rotating the room identity permits hand
IDs and revisions to begin at their ordinary initial values. Stale socket
events and timer callbacks must match the room generation before changing
anything. The same lock should retire authority, cancel deadlines and clear
replay data. Restart and create both currently use the normal engine
factory with fresh stacks and seat A as first dealer. Reusing those rules
requires no engine change. Reusing seats with a different dealer, changed
units or interrupted-pot handling needs partner review.

1. Agree on who can release a completed room, whether consent is needed,
   how long the final result is visible, and the old-key expiry response.
2. Add transaction tests for delayed callbacks, retries, concurrent
   release, and authentication against old and new rooms.
3. Add a versioned browser flow once the authority contract is agreed.
   Verify that old snapshots never reopen controls.
4. Reassess same-room rematch after fresh-room isolation is proven.
