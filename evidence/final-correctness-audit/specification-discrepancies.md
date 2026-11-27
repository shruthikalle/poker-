# Specification discrepancies

The [implemented rules](../../docs/rules-reconciliation.md) and [wire contract](../../docs/protocol.md)
govern the application checks. The [target draft](../../docs/rules.md)
records a different variant selected by one contributor from a PDF.
The [reconciliation](../../docs/rules-reconciliation.md)
is explicitly pending. Its language about timing as future work reflects
when it was written. The current timing contract is already live.

| Difference | Current behavior | Evidence and disposition |
| --- | --- | --- |
| Stacks and blinds | Host chooses even unit 2–20, 20 units per player, half-unit small blind, one-unit big blind. The target asks for 500 and 5/10. | Engine and admission tests, browser starting stacks. Both approve the rule and UI contract. |
| Bet increments and raise limit | One unit for all streets and two raises beyond the opener. The target asks for 10/20 increments and three raises. | Engine cap and reset tests. Srishruthik owns any migration after approval. |
| Deal and turns | Standard unique 52-card deck, alternating deal from button, no burns, 3/1/1 board, button first preflop and nondealer first postflop. Target adds burns. | Browser fixture and engine deck tests. Preserve ordering. Both decide burns. |
| Legal actions and affordability | Acting player must retain one chip. Fold remains legal if a call is unaffordable. There is no opponent-coverage check for a bet or raise. Target adds that restriction. | `engine.legal_actions`, G9. Srishruthik owns any change after approval. |
| Fold, showdown and odd chip | Pay once, reveal both hands only at paid showdown, and give an odd split chip to the dealer. Target sends it to the nondealer. | W known-answer fold, flush, and tie. The odd-chip branch is source-inspected. Reviewed matched-contribution fixtures have even pots. |
| Ready and match exhaustion | Both Ready actions rotate the dealer. A stack at or below one full unit ends the match regardless of the next blind owed. Target bases it on the actual upcoming blind. | G10/G11, engine terminal browser fixture. Joint rule decision. |
| Disconnect settlement | Terminal result is independent of the hand. Earlier fulfilled payout survives. Interrupted stacks and pot remain where they were, with no unauthorized reveal. | Exact grace tests and live forfeit/both-absent reports. Both decide retention or a new policy. |
| R7 token ownership | A valid token authenticates its seat. The server has no separate identity with which to reject a bearer who possesses the other seat's token. | Backend auth and replacement tests. Clarify README bearer interpretation; credential theft is outside the threat model. |
| C4 cards in the README | Actual browser fixture uses A `9h 5h`, B `Ts 3c`. The README privacy example lists different cards. | Packet and DOM checks use the real fixture and the same privacy invariant. |
| Ownership descriptions | Historical plans differ. Git history records Srishruthik's engine, table API and lobby work and Deepthi's browser, transport, and testing work. | Preserve old planning records and use the [software provenance](../submission-readiness/contribution-inventory.md) for current attribution. |
