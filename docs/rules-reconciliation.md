# Proposed rules documentation replacement

Joint approval is pending. The engine and its existing tests govern this
branch. If both partners approve, replace the body of `docs/rules.md` with the
text under **Retained rules** below, remove this proposal file, and point the
README's rules summary at `docs/rules.md`. In README, replace the paragraph
under **Implemented rules and target draft** with:

> This is a deliberately simplified heads-up fixed-limit poker variant.
> The configurable rules below describe the engine and its tests.
> [Agreed rules](docs/rules.md)

Rename that heading to **Implemented rules**. The earlier proposal remains
available in Git at `e65f0c2`.

## Retained rules

Two players share one active room per process. The host chooses an even
integer bet unit between 2 and 20 inclusive. Each starts with 20 times that
unit. A buttons first. The button posts half the unit and acts first
preflop. The nondealer posts one unit and acts first after the flop.

Deal two private cards per player from a standard shuffled deck. The board
is a three-card flop, one-card turn, and one-card river. There are no burns.
Use one unit for every opening bet or raise increment, with at most two
raises after the opening wager per street. The big blind counts as the
preflop opener. Acting players must retain at least one chip after paying.
Fold remains available when a call cannot be paid. All-ins and side pots
are unsupported.

A fold pays the opponent immediately without revealing either player's
cards to their opponent. At showdown Treys compares the best five of seven
and settles immediately. A tie splits the pot with an odd chip going to
the button. The match ends if a seat cannot post the full big blind while
retaining one chip. Otherwise both players choose Ready before starting
the next hand with the settled stacks and the rotated button.

The 30-second turn and 20-second reconnect grace periods are future
server milestones. Their deadline and recovery details require joint
approval.
