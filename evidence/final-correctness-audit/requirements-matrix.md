# Requirements and verification

The G, R, T, and C identifiers come from the implemented contract in
[README](../../README.md). The [protocol](../../docs/protocol.md) defines
transport behavior. The incompatible [target draft](../../docs/rules.md)
and [reconciliation](../../docs/rules-reconciliation.md) remain open.
The original proposal, source PDF, and official submission instructions
were absent from the tracked tree and available branch history.

Owners are Deepthi for application and transport, Srishruthik for engine
behavior, and both for rule changes and final approval. A joint audit
row uses the implemented behavior for testing and keeps approval separate.

Test selectors below are names or unique fragments of names. E denotes
engine unit tests in [test_engine.py](../../tests/test_engine.py) or
[test_gameplay.py](../../tests/test_gameplay.py). C denotes backend tests in
[test_coordinator.py](../../tests/test_coordinator.py), W denotes ASGI
WebSocket integration in [test_websocket_gameplay.py](../../tests/test_websocket_gameplay.py),
and T denotes deterministic clock or scheduler tests in
[test_deadlines.py](../../tests/test_deadlines.py). B denotes actual browser
scenarios in [browser_smoke.py](../browser-interface/browser_smoke.py),
with [recorded browser output](browser-compatibility-results.txt). H
denotes the ten live HTTP/WebSocket probes, with
[recorded live output](regression-smoke-results.txt). These levels provide
different evidence. The [oracles](correctness-oracles.md) calculate
expected outcomes independently of the engine.

| ID | Implemented requirement | Owner and implementation | Executed verification | Status and limit |
| --- | --- | --- | --- | --- |
| G1 | A acts after 5/10 blinds. Only fold, call 5, raise paying 15. | Srishruthik, `engine.new_game`, `legal_actions`. Deepthi, `views.player_view`. | E `g1_initial`; B `showdown` and H showdown with 195/190/pot 15. | Verified. Unit 10 fixture. |
| G2 | Call 5 reaches 190/190/pot 20. B's check starts the flop and B acts first. | Srishruthik, `engine.apply_action`, `_advance_round`. | E `g2_call_then_check`; B `showdown`; H showdown. | Verified. |
| G3 | Flop bet 10 then call reaches 180/180/pot 40 and starts turn. | Srishruthik, `engine._pay`, `_advance_round`. | E `g3_bet_call`; W `flop_bet_raises` covers a separate larger wager. | Verified at engine level for the precise sequence. |
| G4 | Check down turn and river to a paid showdown with no extra cards. | Srishruthik, `engine._advance_round`, `_showdown`. | E `g4_turn_and_river`; B `showdown` uses the 20-chip pot variant. | Verified. |
| G5 | Immediate fold pays B for 195/205 and hides the folded cards. | Srishruthik, `engine._finish_hand`. Deepthi, `views.player_view`. | E `g5_fold`; W `fold_pays_opponent`; H fold. | Verified. |
| G6 | Flop fold awards the full 30-chip pot for 190/210. | Srishruthik, `engine._finish_hand`. | E `g6_flop_fold`. | Verified at engine level. |
| G7 | Two preflop raises are permitted. The third is unavailable. Calling yields 170/170/pot 60. | Srishruthik, `engine.legal_actions`, `apply_action`. | E `g7_r3_two_raises`; W `flop_bet_raises` independently covers the cap. | Verified. |
| G8 | Two checks advance one street. Duplicate or stale check cannot advance again. | Srishruthik, `engine._advance_round`. Deepthi, `coordinator.submit`. | E `g8_two_checks`; B `stale`; C `competing_commands`. | Verified. |
| G9 | Calling when the payment empties the stack is illegal. | Srishruthik, `engine.legal_actions`. | E `g9_call_that_would_empty_stack`. | Partner-owned. Known-answer regression passed. |
| G10 | A stack unable to retain one chip after a big blind ends the match. | Srishruthik, `engine._match_winner`. Deepthi, `timers.Timing.with_hand`. | E `g10_match_ends`; B `engine-terminal`. | Verified under retained rules. |
| G11 | Both Ready actions start the next hand with rotated button and matching blinds. | Srishruthik, `engine._start_next_hand`. Deepthi, `coordinator.submit`. | E `g11_second_hand`; W `ready_advances_over_transport`; B `showdown`. | Verified. |
| G12 | The raise cap resets for the next street. | Srishruthik, `engine._advance_round`. | E `g12_raise_cap_resets`. | Partner-owned. Engine regression passed. |
| R1 | Wrong-turn action leaves stacks, pot, and actor unchanged. | Srishruthik, `engine.apply_action`. Deepthi, `coordinator.submit`. | E `r1_out_of_turn`; W `malformed_unauthorized_and_stale`. | Verified. |
| R2 | Invalid action and custom amount are rejected without mutation. | Deepthi, `commands.COMMAND_SCHEMA`; Srishruthik, `engine.legal_actions`. | [Schema tests](../../tests/test_commands.py) `exact_fields_types_and_bounds`; W `malformed_unauthorized_and_stale`. | Verified. |
| R3 | Third raise leaves pot 50, contributions 20/30, and actor A. | Srishruthik, `engine.legal_actions`; Deepthi, `coordinator.submit`. | E `g7_r3_two_raises`; W `flop_bet_raises` for a separate street. | Verified. |
| R4 | Identical retained command replays once; conflicts do not mutate. | Deepthi, `coordinator.submit`, `_prune`, browser `receive`. | C `replay_after_later_transition`, `ready_across_hands`; B `replay`; [watchdog probe](../browser-reliability/recovery_probe.py). | Verified within stated retention. |
| R5 | Only even units 2–20. Unit remains fixed after admission. | Deepthi, `rooms.RoomManager.create`, `server.CreateRoomRequest`. | [Room tests](../../tests/test_rooms.py) `accepts_every_even`, `room_code_cannot_reclaim`; H room smoke. | Verified. |
| R6 | Invalid or full room and attempts to use code as a token leave seats unchanged. | Deepthi, `rooms.RoomManager.join`, `admit_once`; shared legacy routes. | [Admission tests](../../tests/test_admission_recovery.py) and [audit tests](../../tests/test_final_transport.py) `test_distinct_keys_and_legacy_join_share_capacity`; H admission and B `errors`. | Verified. |
| R7 | Valid token always authenticates its original seat; invalid tokens cannot displace it. | Deepthi, `rooms.authenticate`, `server.room_socket`; shared seat ownership. | [Server tests](../../tests/test_server.py) `invalid_credentials`; T `replacement_lobby_downgrade`; B `replacement`, `errors`. | Partial. README's “other player's” phrase requires bearer interpretation. |
| R8 | Competing commands from a seat apply at most one matching revision. | Deepthi, `coordinator.submit`; shared `connections.ConnectionRegistry`. | C `competing_commands_against_one_revision`, `one_legal_seat`; B `replacement`. | Verified. |
| R9 | Before B joins, no hand or turn action. | Deepthi, `rooms.create`, `timers.Timing.with_presence`. | T `waiting_and_initial_activation`; H waiting. | Verified. |
| R10 | Repeated Ready leaves one flag until the other seat is Ready. | Deepthi, `coordinator.submit`; Srishruthik, `engine.apply_action`. | E `r10_repeated_ready`; W `ready_advances_over_transport`. | Verified. |
| T1 | At 30 seconds facing the blind, server folds once. | Deepthi, `coordinator._reconcile`. | T `exact_and_late_commands`; H timeout-fold; B `timeout`. | Verified. Browser uses shorter fixture. |
| T2 | Where check is legal, timeout checks once and starts the next turn. | Deepthi, `coordinator._reconcile`, `Timing.with_hand`. | T `t2_flop_timeout`; H timeout-check. | Verified. |
| T3 | Pause after 12 active seconds, recover 18 seconds and same cards before grace expiry. | Deepthi, `Timing.with_presence`, `coordinator.attach`. | T `t3_and_t8_nonacting_absence`, `pause_at_12`; H and B `recovery`. | Verified. |
| T4 | Reconnect at or after grace expiry cannot reopen a forfeited match. | Deepthi, `Timing.disconnect_result`, `coordinator.attach`. | T `reconnect_at_exact_deadline`; H and B `forfeit`. | Verified. |
| T5 | Returning before expiry resumes the live match. | Deepthi, `Timing.with_presence`. | T `either_player_returns_before_earliest`; H reconnect. | Verified. |
| T6 | Command just before the turn deadline wins. At or after expiry the timeout wins. | Deepthi, `coordinator._reconcile`, `submit`, `run_scheduler`. | T `command_before_deadline`, `exact_and_late_commands`, `scheduler_wakes_for_earlier`. | Verified under a controlled clock. |
| T7 | Both absent at first grace expiry closes with no winner. | Deepthi, `Timing.disconnect_result`. | T `overlapping_and_simultaneous_absence`; H and B `both-absent`. | Verified under retained policy. |
| T8 | A nonacting absence pauses B's clock without replenishing time. | Deepthi, `Timing.with_presence`. | T `t3_and_t8_nonacting_absence`, `repeated_resume_and_stale_callbacks`; H reconnect. | Verified. |
| C1 | Deterministic winning showdown pays 20 once, leaving 210/190. | Srishruthik, `engine._showdown`. Deepthi, `views.player_view`. | W `flush_beats_straight`; H and B `showdown`. | Verified with fixed flush-vs-straight fixture. |
| C2 | Royal flush on the board ties and leaves 200/200/pot 0. | Srishruthik, `engine._showdown`. Deepthi, `views.player_view`. | W `royal_flush_on_board`; H and B `tie`. | Verified. |
| C3 | Reject short and duplicate injected decks without committing a new hand. | Srishruthik, `engine._deck_or_shuffle`. | E `c3_reject_duplicate`, `c3_bad_next_deck`. | Partner-owned. Negative fixtures passed. |
| C4 | Before showdown, no opponent cards, future board, or undealt deck in messages. | Deepthi, `views.player_view`, `render.renderTable`. | W gameplay and validation; B wire capture; [view tests](../../tests/test_views.py) `first_hand_exact_fields`; [usability audit](../browser-reliability/browser_checks.py). | Partial. Actual fixture uses other cards. Every error and browser transition combination was outside the bounded capture. |
| C5 | Fold or disconnect before showdown reveals no losing hole cards. | Deepthi, `views.player_view`. | W `fold_pays_opponent`; H forfeit and both-absent; B `forfeit` and `replacement`. | Verified for tested outcomes. |
| C6 | Flop, turn, and river expose exactly 3, 4, and 5 board cards. | Srishruthik, `engine._advance_round`. Deepthi, `views.player_view`. | W `flush_beats_straight`; H and B `showdown`. | Verified. |

## Additional audit acceptance

These identifiers refer to the supplied final audit brief. They leave
the README requirement IDs intact.

| ID | Source and requirement | Owner and implementation | Verification | Status |
| --- | --- | --- | --- | --- |
| Audit D/E | Replay admission and recover exact gameplay commands safely. | Deepthi, `rooms.admit_once`, `coordinator.submit`, `network.commandWatchdog`. | [Transport results](transport-and-resource-results.txt); [historical comparison](engineering-comparisons.txt). | Verified. |
| Audit H | History return must synchronize before actions. | Deepthi, browser `GameplayConnection` and `app` lifecycle handlers. | [Browser audit](browser_audit.py) `history`, `history-offline`, and `suspension`. | Partial. Real Chromium cache and Firefox/WebKit reload covered. |
| Audit J | Keyboard, error association, zoom and physical accessibility. | Deepthi, browser `app`, `render`, forms. | [Browser audit](browser_audit.py) `forms`, `input`, `zoom`; [manual verification](manual-verification.md). | Partial. No interactive screen reader or physical device test. |
| Audit N | Fresh locked install and isolated wheel launch. | Deepthi, [pyproject](../../pyproject.toml), static mount. | [Clean checkout results](clean-checkout-results.txt); `browser_audit.py --case installed`. | Verified. |
| Audit C1 | Agree final target or retained poker rules. | Both. | [Open decisions](joint-decisions.md). | Pending joint approval. |
| Audit C2 | Agree how disconnect interruption treats the pot. | Both. | T and H prove present behavior; [approval checklist](joint-decisions.md). | Pending joint approval. |
| Audit R/S | Agree presentation selections and rehearse together. | Both. | [Handoff](presentation-handoff.md). | Pending joint approval. |
| Audit B/R | Review the actual source PDF, proposal, and official delivery instructions. | Both. | Tracked files and all accessible Git refs inspected. | Blocked by missing source. |

Across 44 mapped rows there are 33 verified, 4 partial, 3 partner-owned,
3 pending joint approval, and 1 blocked by missing source.
