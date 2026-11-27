# Questions for the demo

| Question | Answer and evidence |
| --- | --- |
| Why WebSockets? | The server pushes committed game views and presence changes over one authenticated connection. Polling would repeatedly request state. [Transport](../../poker/server.py) |
| Why is the server authoritative? | It owns the deck, revision checks, legal transitions and deadlines. The browser submits intent and draws a personalized view. [Coordinator](../../server/coordinator.py) |
| How are cards private? | A snapshot allowlists public fields and only the viewer's dealt cards. Paid showdown supplies the permitted reveal. CSS hiding alone would leave data in the payload. [Views](../../server/views.py) |
| How are duplicates handled? | Seat, hand and action ID identify retained outcomes. Reusing a retained ID with changed content is rejected. [Protocol](../../docs/protocol.md) |
| What if an acknowledgment is lost? | The tab keeps the exact bytes, reconnects on a bounded monotonic deadline, and replays after authenticating. [Probe](../browser-reliability/recovery_probe.py) |
| Why two revisions? | Pause, resume and presence can change without an engine transition. The pair rejects regressions while accepting lifecycle changes. [Comparison](historical-comparison-results.txt) |
| How are simultaneous commands ordered? | The room lock covers authority, reconciliation, replay, validation and commit. Network delivery is queued outside the commit path. [Coordinator](../../server/coordinator.py) |
| What happens exactly at expiry? | Turn deadlines are exclusive. The server reconciles a due timeout first. [Deterministic tests](../../tests/test_deadlines.py) |
| Why does reconnect preserve time? | Disconnect saves the remaining active turn. Reconnect adds only that saved duration to current server time. [Timers](../../server/timers.py) |
| What happens when both players leave? | At the first grace expiry with both absent, the match closes without a winner. [Live output](final-regression-results.txt) |
| How do hand and match results differ? | A hand ends via payout or tie. A match can also end by forfeit or both-absent while a hand remains unsettled. [Rules for review](joint-approval-status.md) |
| Why preserve the interrupted pot? | Current termination is a lifecycle event. It preserves the last committed chip state and avoids inventing a payout. Joint approval is pending. [Pot wording](joint-approval-status.md#interrupted-pot-wording) |
| How is the winner independently known? | The fixture gives A an ace-high flush and B an ace-high straight. A flush outranks a straight. [Oracle](../final-correctness-audit/correctness-oracles.md) |
| Why is conservation insufficient? | A wrong payout or duplicate accepted transition may still conserve chips. Verify winner, complete stacks, revision and accepted count. [Comparison](historical-comparison-results.txt) |
| What does refresh do? | The tab restores seat metadata and pending bytes from session storage. It needs a fresh authenticated snapshot before mutating. [Protocol](../../docs/protocol.md) |
| How does keyed admission work? | Successful operation and request input are bound to a random bearer key under the room lock. Retry returns the original response for the process lifetime. [Room manager](../../poker/rooms.py) |
| Why separate replay caches? | A flood of rejected commands should not displace a retained accepted outcome or consume accepted capacity. [Coordinator tests](../../tests/test_coordinator.py) |
| Can a slow client stall its peer? | Each socket has its own bounded writer queue. Overflow closes the slow socket and removes its authority. [Connections](../../server/connections.py) |
| Why monotonic time? | Deadlines and durations need elapsed time independent of wall-clock changes. The client shows an estimate. [Clock](../../server/clock.py) |
| What survives server restart? | The app can start again, but the previous room, tokens, deadlines and replay history were process-local. [Restart probe result](browser-verification-results.txt) |
| What if a token is stolen? | Bearer possession grants the corresponding seat. The threat model assumes a trusted browser and loopback deployment. [Protocol](../../docs/protocol.md) |
| Why is this scoped to local educational use? | Single worker and room, process-local records, bearer authority, and loopback HTTP. [Limitations](submission-checklist.md#verification-and-scope-limits) |
| What did Treys and FastAPI provide? | Treys supplies card representation and hand ranking. FastAPI provides routing, validation integration and WebSocket endpoints. Project code makes the game and protocol decisions. [Dependency inventory](contribution-inventory.md) |
| Who implemented what and how was the agent checked? | Attribute by the recorded engine, lobby, transport and browser work. Codex assisted under contributor direction. Independent expected results, wire checks, and historical comparisons verify the changes. [Contributions](contribution-inventory.md) |
| Which trade-off mattered most? | Reconcile deadlines in the transaction that accepts a command. It closes the gap when a scheduled callback is delayed. [Decision 2](presentation-content.md#4-reconcile-deadlines-where-commands-commit) |
| What genuine bug best shows your debugging process? | Snapshot traffic postponed the lost-ack watchdog. The peer's changed pot and stable revision isolated delivery recovery. [Debugging story](presentation-content.md#5-an-acknowledgment-went-missing-and-the-tab-kept-waiting) |
| What happens after the small blind calls? | The big blind retains a check or raise option before the first street closes. [Engine](../../poker/engine.py) |
| What does the next-hand threshold check? | Settlement marks a match winner when a stack is at or below the full unit, regardless of the next blind it would owe. [Rules for review](joint-approval-status.md) |
| What would you improve next? | Design durable transactional room and replay storage, then test a restart after a command commits with its acknowledgment missing. [Limitations slide](presentation-content.md#6-restarting-the-server-interrupts-an-active-match) |
