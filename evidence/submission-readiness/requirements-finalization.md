# Functional coverage

The [case matrix](../final-correctness-audit/requirements-matrix.md) maps runtime verification.

| Scope area | Requirement and owner | Implementation and verification | Status |
| --- | --- | --- | --- |
| 1 | One private table for two browser players using virtual chips and fixed wagers. Deepthi owns admission and browser. Srishruthik owns engine rules. | `RoomManager.create/join`, `engine.legal_actions`, and `renderTable`. Browser `showdown` and engine G1/G7/G9. | Verified in trusted loopback. Internet deployment was outside the delivered scope. |
| 1 | Two hidden cards, turn-limited actions, shared board and winner. Both components. | `player_view`, `engine.apply_action` and `_showdown`. Wire test `test_flush_beats_straight_and_settlement_replay_does_not_pay_twice` and browser `showdown`. | Verified. Context-specific privacy and selected deterministic deals. |
| 2 | Two-browser complete hand and independent known-answer showdown. Both. | `fixed_deck("showdown")`, `browser_smoke.py --scenario showdown`, [independent card and chip answers](../final-correctness-audit/correctness-oracles.md). | Verified. A's flush wins and the final stacks are 210/190. |
| 2 | Reject an action from the wrong player without changing pot or turn. Deepthi. | `GameCoordinator.submit` and [demo protocol probe](demo_protocol.py), cross-checked by engine R1. | Verified in two authenticated sockets. Actor A, pot 15, revision 1 before and after. |
| 4 | New codebase with FastAPI WebSockets, Treys 0.1.8, pinned reused versions, and tracked scope. Both. | `poker.server.room_socket`, `engine._showdown`, [lockfile](../../uv.lock), [contributions](contribution-inventory.md). | Verified. Betting was retained. Recovery, timers and multi-hand play are additions to the original minimum. |
