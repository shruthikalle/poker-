# Alternative poker rules draft

Status: unapproved alternative. See the [implemented variant](rules-reconciliation.md).

## Table, deal, and turn order

- Exactly two seats, A and B, start with 500 virtual chips each. A is the first dealer/button.
- Use a shuffled standard 52-card deck. Tests may inject a complete, unique fixed deck. Deal two private cards alternately, starting with the button.
- Burn one card before each board street. Reveal three flop cards, one turn card, and one river card. Future board cards and the remaining deck are never client-visible.
- The button posts 5 as small blind; the other seat posts 10 as big blind. The button acts first preflop; the nondealer acts first on later streets. Rotate the button after each hand.
- Start a hand only after both seats are filled. Start the next hand only after both players choose Ready.

## Betting and settlement

- Actions are fold, check, call, bet, raise, and between-hand Ready. The engine determines legal actions.
- Opening bet and raise increment: 10 preflop and flop, 20 turn and river. The big blind counts as the preflop opening wager. Permit at most three raises after the opening wager per street; reset the count on the next street.
- Check requires nothing owed. Call pays the owed amount. Raise pays the owed amount plus the street increment. No custom amounts.
- No all-ins or side pots. Call is legal only if it leaves at least one chip. Bet or raise is legal only if the actor can pay while retaining at least one chip **and** the opponent can cover the resulting amount owed while retaining at least one chip. Fold stays legal for an actor who cannot call. If neither can bet, they may check through the remaining streets.
- A street closes when required action opportunities are complete and street commitments match. A small-blind call preserves the big blind's check or raise option. Two checks close a street when no bet is outstanding.
- Fold settles the pot immediately without revealing the losing hand. At showdown, compare the best five cards of each seven-card set. Award the pot once; split ties and give any odd chip to the nondealer. A completed hand has no actor and pot zero.
- Do not start a new hand if a player cannot post the blind they would owe while keeping at least one chip. The terminal match outcome needs a shared engine/server convention.

## Independent expected values

These values are hand-calculated from the target rules; they are not output from Treys or the engine.

| Sequence | Stacks A/B | Pot | Next actor or result |
| --- | --- | --- | --- |
| A posts 5, B posts 10 | 495 / 490 | 15 | A preflop |
| A calls 5 | 490 / 490 | 20 | B preflop |
| B checks | 490 / 490 | 20 | B on flop; three board cards |
| B bets 10 | 490 / 480 | 30 | A on flop |
| A calls 10 | 480 / 480 | 40 | B on turn; four board cards |
| Both check turn and river; A wins | 520 / 480 | 0 | Showdown; five board cards |
| Alternatively, A folds to B's flop bet | 490 / 510 | 0 | B wins; no hole cards revealed |

At every accepted transition, A stack + B stack + pot = 1,000. No balance or pot is negative. A rejected action preserves the entire authoritative state, including private cards and deck position.

Known showdown oracle: board `Ah Kh Qh Jc 2d`, A `9h 5h`, B `Ts 3c`; A's flush beats B's straight. Add independent fixtures for a board-playing tie, kicker, wheel straight, full house versus flush, and quads versus full house. A fixed deck fixture must include the three burn cards in the correct positions.

## Migration and joint decisions

The current `poker/engine.py` uses 200 chips, a configurable bet unit on every street, two raises, no burn cards, and odd chip to the button. Its 22 tests pass for those older rules. Migration would require corresponding engine and fixture changes.

Both partners should settle: (1) the exact terminal match result when a future blind cannot be paid; (2) final engine API and whether hand ID/revision are server-owned; (3) whether any host-configurable settings remain. This target uses fixed 500 chips and 5/10 blinds, so the old adjustable bet-unit room flow should not be assumed.
