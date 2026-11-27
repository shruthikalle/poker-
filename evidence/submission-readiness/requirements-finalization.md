# Proposal and course traceability

Deepthi supplied the four sections of the original proposal during
finalization. The original PDF file was unavailable. The official
18-page project guide and six-page writeup template were inspected
locally. The separately named comprehensive handbook describes a
reconstruction and planning targets. It does not record joint approval.
Official documents stay outside this public repository.

The existing [44-row application matrix](../final-correctness-audit/requirements-matrix.md)
contains the implementation and test selectors for the runtime, including
additional capabilities. Its missing-source row records the previous
audit. The new map resolves the proposal-text and course-guide portions
of that row. Canvas-only logistics remain open.

| Proposal section | Requirement and owner | Implementation and verification | Status |
| --- | --- | --- | --- |
| 1 | One private table for two browser players using virtual chips and fixed wagers. Deepthi owns admission and browser. Srishruthik owns engine rules. | `RoomManager.create/join`, `engine.legal_actions`, and `renderTable`. Browser `showdown` and engine G1/G7/G9. | Verified in trusted loopback. Internet deployment was outside the delivered scope. |
| 1 | Two hidden cards, turn-limited actions, shared board and winner. Both components. | `player_view`, `engine.apply_action` and `_showdown`. Wire test `test_flush_beats_straight_and_settlement_replay_does_not_pay_twice` and browser `showdown`. | Verified. Context-specific privacy and selected deterministic deals. |
| 2 | Two-browser complete hand and independent known-answer showdown. Both. | `fixed_deck("showdown")`, `browser_smoke.py --scenario showdown`, [independent card and chip answers](../final-correctness-audit/correctness-oracles.md). | Verified. A's flush wins and the final stacks are 210/190. |
| 2 | Reject an action from the wrong player without changing pot or turn. Deepthi. | `GameCoordinator.submit` and [demo protocol probe](demo_protocol.py), cross-checked by engine R1. | Verified in two authenticated sockets. Actor A, pot 15, revision 1 before and after. |
| 3 | Agent-directed changes in reviewable pieces, expected outcomes, and two-browser evidence. Both. | [Git contribution history](contribution-inventory.md), [historical and controlled comparisons](historical-comparison-results.txt), and [browser evidence](browser-verification-results.txt). | Evidenced for the documented work. Both partners' ability to present remains for joint rehearsal. |
| 4 | New codebase with FastAPI WebSockets, Treys 0.1.8, pinned reused versions, and tracked scope. Both. | `poker.server.room_socket`, `engine._showdown`, [lockfile](../../uv.lock), [contributions](contribution-inventory.md). | Verified. Betting was retained. Recovery, timers and multi-hand play are additions to the original minimum. |

| Official requirement | Source | Status |
| --- | --- | --- |
| Identify initial code, reused libraries, contributor/agent roles, and demonstrate a reproducible difference. | Guide pp. 2–4, template p. 2 | SHA, sources, and before/after tracked. Public starting-tag step remains open. |
| Working live demo, independent check, runnable setup, specific limitation. | Guide pp. 11 and 16–17 | Software and automated rehearsal verified. Joint live rehearsal pending. |
| Present two substantive decisions and one real debugging story with results. | Guide pp. 12–15, template pp. 3–5 | [Content and speaker notes](presentation-content.md) prepared, final choices for both partners. |
| Submit repository URL and six-slide PDF writeup, with no separate report. | Guide pp. 11 and 15–18, template pp. 1–6 | Content prepared. PDF and submission reserved for the team. |
| Staff can access the repository, evidence is tracked, and homework stays out. | Guide pp. 4 and 18 | Public repository and tracked citations verified. Partner collaborator status remains to be confirmed. |
| Use Canvas for the deadline, edit close, and demo scheduling. | Guide p. 18 | Exact dates, registration, slot, and submitting partner unverified. |

This finalization map has 6 proposal and 6 course rows. The first four
functional rows and dependency row passed. The documented process is
evidenced within its stated limit. The course rows retain separate
completion conditions. See [submission checklist](submission-checklist.md)
and [official project guide](https://www.cs.utexas.edu/~witchel/378AC/lectures/948_final_project_guide-slides.pdf).
