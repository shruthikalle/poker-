# Heads-Up Live Poker

A browser-based, two-player Texas Hold'em game using **virtual chips only**. One player creates a private room and shares its code; the other joins from a second browser. The server owns the deck, rules, timers, and game state. Each browser receives only the information that player is allowed to see.

This README is the **implementation plan**. The repository does not contain runnable game code yet. Setup, demo, and test commands will be added here as those parts are built.

Team: Srishruthik Alle and Deepthi Morusupalli. Contact: shruthik.alle@gmail.com; Deepthi's contact email will be added after she provides it.

## Planned demo

1. Create a room and choose the table's fixed bet unit.
2. Join it from a second browser using the room code.
3. Play a prepared hand through betting rounds and showdown.
4. Show that an action from the wrong player is rejected without changing the turn or pot.
5. Show that one player can disconnect and rejoin during a hand, while the other browser never receives that player's private cards before showdown.

## Rules and scope

These are deliberate rules for the first version, so the UI, server, and tests can agree on one behavior. We will use the standard 52-card deck and Texas Hold'em hand rankings, but a **fixed-limit** betting structure to keep the first build manageable.

| Area | First-version rule |
| --- | --- |
| Players | Exactly two per room. The first creates the room; the second joins with its code. |
| Chips | Each player starts with 20 times the chosen bet unit in virtual chips. There is no real-money play. |
| Bet unit | The host chooses an even whole-chip amount from 2 to 20 before the second player joins. It cannot change during a match. |
| Blinds | The dealer/button posts a small blind of half the bet unit; the other player posts a big blind of one bet unit. The button alternates after each hand. |
| Deal | Each player gets two private cards. Community cards are dealt as flop (3), turn (1), and river (1). |
| Turn order | The small blind acts first before the flop. The big blind acts first on each later betting round. |
| Actions | Fold, check, call, bet, and raise. The server decides which are legal from the current state; the browser only displays those choices. |
| Bet size | A bet or raise adds exactly one bet unit. At most two raises follow the opening bet in each betting round. No custom amounts, all-ins, or side pots. |
| Round end | A betting round ends when both players have acted and their contributions to that round are equal. A call after a bet or raise closes the round; a check closes it only after the other player has also checked or matched the blind. |
| Showdown | If neither player folds, compare the best five-card hands from seven cards. The winner takes the pot; a tie splits it. If the pot is odd, the extra chip goes to the button. |
| Hand end | A fold, including an automatic fold, gives the pot to the other player. After the result, players may start the next hand. If either player cannot post a full big blind, the match ends. |

An action that a player cannot afford is unavailable. In particular, if a player cannot afford a call, they must fold; this is a known simplification of poker without all-ins. We will test that it never makes the chip total change unexpectedly.

### Timers and reconnects

- A player's turn lasts **30 seconds**, measured by the server. When time runs out, the server checks if a check is legal; otherwise it folds that player. The UI countdown is informational, not authoritative.
- A disconnected player has **20 seconds** to reconnect. The hand pauses during that grace period, including the turn clock. If the player does not return, they forfeit the **match**; the connected player is declared the winner and no further hands are played. If both players disconnect, the room closes without a winner.
- The server gives each player a private reconnect token when they join. A room code admits the second player but cannot be used to take over an occupied seat. Reconnecting restores the same seat and a fresh view of the current state.
- All timer and disconnect transitions are server-side and should be tested with a controllable clock, rather than waiting 20 or 30 real seconds in tests.

### Privacy rule

Before showdown, **no WebSocket message sent to a player may contain the opponent's hole cards**, including join responses, action results, reconnect snapshots, errors, and timer updates. Spectators are not supported. At showdown the server may reveal both hands. The server creates a separate player-specific view for each message rather than sending one complete game state to both browsers.

## Planned components and ownership

This is a proposed split to confirm together. The repository's commit history and this section will be updated to reflect the work each person actually completes.

| Owner | Main responsibility | Evidence to produce |
| --- | --- | --- |
| Srishruthik | Game state and rules: dealing, blinds, legal actions, betting transitions, pot accounting, round changes, and showdown integration. | Unit tests for turn order, legal/illegal actions, betting totals, and known hands. |
| Deepthi | Real-time layer and browser: room creation/join, WebSocket messages, player-specific views, reconnect tokens, timer display, and two-browser UI. | Protocol tests that inspect every message for card leaks, reconnect tests, and a two-browser demo. |
| Both | Define the supported rules, review each other's changes, integrate the components, rehearse the demo, and explain the final system. | Saved demo fixture, documented decisions and debugging evidence, and final slides. |

The boundary between the parts is a server-side game API: the real-time layer submits a player identity and requested action; the game engine returns the new state or a rejection. Only the real-time layer converts state into player-specific messages. Neither browser is trusted to calculate the pot, choose the next turn, or decide the winner.

## Checks we intend to keep with the code

- **Turn order:** a prepared game state says exactly who acts next. An action from the other player is rejected, and the pot, chips, cards, phase, and turn remain unchanged.
- **Betting:** known action sequences produce independently calculated contributions, pot totals, legal actions, and next actors. The total chips across both stacks and the pot stay constant.
- **Round progression:** a call or two checks advance exactly one phase; the flop, turn, and river reveal the right number of cards.
- **Card privacy:** capture every outbound WebSocket message to both players, including a reconnect snapshot, and assert that the opponent's hole cards never appear before showdown.
- **Reconnect:** disconnect during a player's turn, reconnect before 20 seconds, and confirm the seat, hand, hidden cards, and remaining turn time are restored. Cross 20 seconds without reconnecting and confirm a single match-forfeit result.
- **Turn timeout:** cross 30 seconds and verify an automatic check when legal or fold otherwise, with no duplicate transition.
- **Showdown:** use prepared deals with hand rankings worked out independently. This checks our integration and pot award, but most tests target our own game logic rather than Treys itself.

Tests will use fixed decks and a controllable clock. We will save the fixtures and expected outcomes in the repository, so staff can run the core workflow locally without credentials or external services. A useful regression test should fail if the relevant rule is deliberately broken.

## Implementation and attribution

The project starts without an existing codebase. We plan to build the game logic, room protocol, privacy filtering, reconnect behavior, and browser interface ourselves. Planned external dependencies are:

- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) for server-to-browser communication.
- [Treys 0.1.8](https://pypi.org/project/treys/0.1.8/) for card representation and hand evaluation.
- [WSOP rules](https://www.wsop.com/poker-games/texas-holdem/rules/) as a reference for hand and action terminology; our supported betting rules are specified above.

We will pin actual dependency versions when implementation starts and document any additional reused code or assets with links. Course homework material will not be used. Agent-assisted code and each partner's contributions will be identified in the final slides and repository history.

## Setup and demo

Not available yet. Before submission, this section will include required versions, exact install and launch commands, a one-command check, and steps for a clean-start two-browser demo. The server, fixtures, and tests will run locally without private credentials.

## Known limits of the first version

The game supports heads-up play only, one active room per server process, fixed-size bets, and no all-ins or side pots. A player who cannot afford a call must fold. These are explicit scope choices; we will record any later change and why we made it.
# poker-
