# Combined integration inventory

The baseline local and remote main was
`a6903fb3286fbf27ff96e6e32e4fcadf8eed0ed0`, with 45 commits and a
clean worktree. Fetch showed no newer partner changes. Both partners'
available work is incorporated through the historical integration
and original commits. This finalization changes no production modules,
existing tests, or shared protocol/engine contracts.

| Owned area | Actual implementation and checks | Integration status |
| --- | --- | --- |
| Srishruthik's immutable engine and dealing | Frozen `GameState`, `new_game`, injected fixed deck, rotating button, single authoritative actor. Engine G1/G2/G11/C3. | Implemented and verified. |
| Srishruthik's betting, evaluation and settlement | `legal_actions`, `apply_action`, `_showdown`, `_finish_hand`, `_match_winner`. Treys ranks hands. The engine pays and exposes result fields. G3–G10, G12 and wire fold/showdown/tie. | Implemented and verified for the current variant. Target migration requires joint approval. |
| Srishruthik's compatibility table and lobby | Legacy table and join, bearer identity lookup, authenticated lobby, current seat tracking. Commits `e4a6651` and `0f48df7`. | Existing integration smoke passed with shared room capacity. |
| Deepthi's application | Canonical routes, keyed admission, coordinator, bounded replay, private snapshots, deadline reconciliation, browser reliability and packaging. | End-to-end, browser, and wheel checks passed. |
| Seeded engine simulations and partner experiment outputs | No simulation program or its outputs found on the available refs. Engine implementation, unit tests and known-answer checks are tracked. | No simulation count is claimed. |

`RoomManager` calls `new_game` when B joins and records the immutable
returned state. `GameCoordinator` interprets `ActionResult.accepted`
and commits the returned state at the authorized revision. It preserves
the previous state on rejection. Engine `hand_number` becomes the
wire `hand_id`. Seats A/B, board, stacks and pot are shared in
personalized snapshots. Each seat receives its own hole cards and
legal moves. A paid tied showdown differs from match closure. Ready
starts a new hand only when both seats request it and the match is live.

[Engine verification](engine-verification-results.txt) ·
[Combined regression](final-regression-results.txt) ·
[Approval status](joint-approval-status.md)
