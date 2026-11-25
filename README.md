# Heads-Up Live Poker

A browser-based, two-player Texas Hold'em game using **virtual chips only**. One player creates a private room and shares its code; the other joins from a second browser. The server owns the deck, rules, timers, and game state. Each browser receives only the information that player is allowed to see.

The integrated development app runs the existing configurable-bet-unit engine through showdown and subsequent hands. Both HTTP admission contracts and both WebSocket lobby formats use one room per running app. Player B's admission initializes the first hand. Gameplay messages, timers, reconnect deadlines, player-specific game views, and the browser remain planned.

Team: Srishruthik Alle and Deepthi Morusupalli, CS 378 Agentic Software Engineering.

## Implemented rules and target draft

The numerical fixtures below describe the current engine. [The target rule draft](docs/rules.md) proposes fixed 500-chip stacks, 5/10 blinds, street-dependent increments, three raises, burns, and the odd chip going to the nondealer. Adopting it would require engine, admission, and fixture changes. The current app uses the configurable unit and defaults to 10 when creating through the lobby API.

The Day 1 commits reflect the earlier plan with Srishruthik on the engine and Deepthi on the real-time layer. Srishruthik's later draft proposes Deepthi owning engine migration, rules, accounting, showdown, and independent fixtures, with Srishruthik owning server, browser, and integration work. Both plans assign the shared interface, evidence, demo, and slides to both partners. Confirm the forward split together before assigning more work.

The repository's first commit is `c29badee2f21e6542c67a176304460b14cea13b6` (README only, November 23, 2026). The first engine commit is `34aa241`. The branch histories record each partner's actual contributions.

## Planned demo

1. Create a room using the table rules agreed for the demo.
2. Join it from a second browser using the room code.
3. Play a prepared hand through betting rounds and showdown.
4. Show that an action from the wrong player is rejected without changing the turn or pot.
5. Show that one player can disconnect and rejoin during a hand, while the other browser never receives that player's private cards before showdown.

## Existing engine rules and scope

The table describes the behavior exercised by the current engine tests. [Target rule draft](docs/rules.md)

| Area | First-version rule |
| --- | --- |
| Players | Exactly two per room. The first creates the room; the second joins with its code. |
| Chips | Each player starts with 20 times the chosen bet unit in virtual chips. There is no real-money play. |
| Bet unit | The host chooses an even whole-chip amount from 2 to 20 before the second player joins. It cannot change during a match. |
| Blinds | The dealer/button posts a small blind of half the bet unit; the other player posts a big blind of one bet unit. The button alternates after each hand. |
| Deal | Each player gets two private cards. The button receives the first card, then cards alternate. The next five cards become the flop (3), turn (1), and river (1). This simplified version does not burn cards. |
| Turn order | The small blind acts first before the flop. The big blind acts first on each later betting round. |
| Actions | Fold, check, call, bet, and raise. The server decides which are legal from the current state; the browser only displays those choices. |
| Bet size | An opening bet is one bet unit. A raise increases the current wager by exactly one bet unit, so the player pays the amount needed to call **plus** one bet unit. The big blind counts as the opening wager before the flop. At most two raises follow an opening wager in each round. No custom amounts, all-ins, or side pots. |
| Round end | A betting round ends when both players have acted and their contributions to that round are equal. A call after a bet or raise closes the round; a check closes it only after the other player has also checked or matched the blind. |
| Showdown | If neither player folds, compare the best five-card hands from seven cards. The winner takes the pot; a tie splits it. If the pot is odd, the extra chip goes to the button. |
| Hand end | A fold, including an automatic fold, gives the pot to the other player. After the result, players may start the next hand. If either player cannot post a full big blind while retaining at least one chip, the match ends. |

An action is unavailable if paying for it would leave the player with zero or fewer chips. In particular, if a player cannot call while keeping at least one chip, they must fold; this is a known simplification of poker without all-ins. We will test that it never makes the chip total change unexpectedly.

Player actions must include a unique action ID. Replaying the same ID must return the original outcome without applying the action twice. An invalid action must leave all authoritative game fields unchanged. A new hand starts only after both players choose **Ready** after the previous result.

### Timers and reconnects

- A player's turn lasts **30 seconds**, measured by the server. When time runs out, the server checks if a check is legal; otherwise it folds that player. The UI countdown is informational, not authoritative.
- A disconnected player has **20 seconds** to reconnect. The hand pauses during that grace period, including the turn clock. If the player does not return, they forfeit the **match**; the connected player is declared the winner and no further hands are played. If both players disconnect, the room closes without a winner.
- The server gives each player a private reconnect token when they join. A room code admits the second player but cannot be used to take over an occupied seat. Reconnecting restores the same seat and a fresh view of the current state.
- All timer and disconnect transitions are server-side and should be tested with a controllable clock, rather than waiting 20 or 30 real seconds in tests.
- Deadlines are exclusive: an action or reconnection received **before** its deadline counts; at the deadline, the timeout or forfeit takes effect first. A reconnect resumes the remaining turn time rather than granting a new 30 seconds.

### Privacy rule

Before showdown, **no WebSocket message sent to a player may contain the opponent's hole cards**, including join responses, action results, reconnect snapshots, errors, and timer updates. Spectators are not supported. At showdown the server may reveal both hands. A hand ending by fold or forfeit does not reveal the cards. The server creates a separate player-specific view for each message rather than sending one complete game state to both browsers.

## Shared boundary and previous ownership record

The table records the plan represented by the original commits. Final attribution follows each person's actual contributions.

| Owner | Main responsibility | Evidence to produce |
| --- | --- | --- |
| Srishruthik | Game state and rules: dealing, blinds, legal actions, betting transitions, pot accounting, round changes, and showdown integration. | Unit tests for turn order, legal/illegal actions, betting totals, and known hands. |
| Deepthi | Real-time layer and browser: room creation/join, WebSocket messages, player-specific views, reconnect tokens, timer display, and two-browser UI. | Protocol tests that inspect every message for card leaks, reconnect tests, and a two-browser demo. |
| Both | Define the supported rules, review each other's changes, integrate the components, rehearse the demo, and explain the final system. | Saved demo fixture, documented decisions and debugging evidence, and final slides. |

The boundary between the parts is a server-side game API: the real-time layer submits a player identity and requested action; the game engine returns the new state or a rejection. Only the real-time layer converts state into player-specific messages. Neither browser is trusted to calculate the pot, choose the next turn, or decide the winner.

The engine API is `new_game(bet_unit=10, deck=None)`, `legal_actions(state, player)`, and `apply_action(state, player, action, *, deck=None)`. `apply_action` returns an `ActionResult` with `accepted`, `state`, and `error`. On rejection, `state` is the original unchanged object. On success, it is a new immutable state. The optional `deck` argument is only for the **second** Ready action and allows a prepared next hand in tests; normal play omits it.

At showdown, the engine evaluates and awards the pot immediately, then sets `phase="showdown"`. This is the only completed-hand phase in which a client may see both hole-card pairs. A fold sets `phase="finished"` and must not reveal the opponent's cards. `winner=None` in a showdown means a tie; `match_winner` is set when a player cannot fund the next big blind. The WebSocket layer authenticates players and sends filtered lobby views. Gameplay actions, deduplication, clocks, and gameplay views remain planned. **Never serialize `GameState` directly to a client:** it includes both private hands and the remaining deck.

## Test cases and expected results

These are **older-rule** expected values, not tests for the target PDF rules. Engine tests cover the numeric and rule portions of **G1-G12, R1-R3, R5, R10, and C1-C3** under the existing implementation. Update these fixtures and tests as the engine changes. Admission tests cover R5 and R6 and the waiting-room and no-deal portions of R9. Lobby tests cover token privacy and socket replacement. Action IDs, timer behavior, reconnect deadlines, and gameplay message privacy remain planned. Use a fixed deck, deterministic room-code generator, fake WebSocket clients, and a controllable clock. Store actual fixture files and runnable tests with the code.

### Common fixture

Unless a case says otherwise, set bet unit **10**, player **A** as the first button/small blind, and player **B** as big blind. Both start with **200** chips. After blinds: A has **195**, B has **190**, the pot is **15**, round contributions are A **5** and B **10**, and A acts next. Chips in both stacks plus the pot must always total **400**. Card notation is rank plus suit, such as `As` for ace of spades.

### Game rules and chip accounting

| ID | Input or action sequence | Expected result |
| --- | --- | --- |
| G1 | Start a hand from the common fixture. | Only A may act. A may fold, call **5**, or raise to a total round contribution of **20** (paying **15**). A cannot check or make a new opening bet while facing the blind. |
| G2 | A calls **5**; B checks. | After the call: pot **20**, A **190**, B **190**, B's turn. After B checks: flop begins, contributions reset to **0/0**, three community cards appear, pot stays **20**, and B acts first. |
| G3 | From G2, B bets **10**; A calls **10**. | After B bets: pot **30**, A **190**, B **180**, A's turn. After A calls: pot **40**, A **180**, B **180**; turn begins, contributions reset, one more community card appears, and B acts first. |
| G4 | From G3, B checks; A checks; B checks; A checks. | The first pair of checks advances from turn to river, revealing one card. The second pair reaches showdown. Pot stays **40** until showdown, then is awarded and becomes **0**; no extra cards are dealt. |
| G5 | From the initial state, A folds. | Hand ends immediately. B receives the **15**-chip pot; final stacks are A **195**, B **205**, pot **0**. No hole cards are revealed. |
| G6 | From G2, B bets **10** and A folds. | B receives the **30**-chip pot; final stacks are A **190**, B **210**, pot **0**. This checks that B receives back chips already contributed to the pot. |
| G7 | From the initial state, A raises to **20** (pays **15**); B raises to **30** (pays **20**). | Pot **50**; A **180**, B **170**; contributions **20/30**; A acts next. A may call **10** or fold, but a third raise is rejected. If A calls, pot **60**, stacks **170/170**, and the flop begins. |
| G8 | From G2, B checks; A checks. | Turn begins with pot **20**, contributions **0/0**, four community cards total, and B acts first. A second or stale check from A does not advance another phase. |
| G9 | Set a player to **10** chips while facing a **10**-chip call in a valid late-match state. | Call is unavailable because it would leave zero chips; fold remains legal. Trying to call is rejected without a negative stack, changed pot, or changed turn. |
| G10 | Finish a hand with one player's stack at **10** when the unit is **10**. | The match ends instead of starting another hand, because the next full big blind would leave that player at zero. No blind is posted and no new cards are dealt. |
| G11 | Start a second hand when both stacks are above **10** and both players choose Ready. | Button alternates: B posts the small blind and acts first before the flop; A posts the big blind and acts first after the flop. The two stack changes and pot equal the posted blinds. |
| G12 | In one round use both allowed raises; then reach the next round. | A third raise is unavailable in the first round. The raise count resets to **0** in the next round, where a new opening bet and up to two raises are possible if both players can afford them. |

### Rejections, room access, and repeated requests

For every rejected request, compare a complete authoritative state snapshot before and after: stacks, pot, round contributions, deck position, hole cards, board, phase, actor, raise count, winner, and turn deadline. None may change. An error message may be returned, but it must be player-specific and reveal no private cards.

| ID | Input or action sequence | Expected result |
| --- | --- | --- |
| R1 | B sends any action while A is first to act. | Reject as out of turn; initial pot remains **15**, stacks **195/190**, actor A. |
| R2 | A tries to check in the initial state, bet while facing the blind, raise by a custom amount, or send an unknown action. | Reject each; no state change. |
| R3 | From G7, A attempts a third raise. | Reject at the cap; pot remains **50**, contributions **20/30**, actor A. |
| R4 | A's call in G2 has action ID `a1`; send `a1` again after B becomes the actor. | Return the recorded outcome for `a1`; the second request does not add another **5** to the pot or change the actor. The same ID attached to a *different* action is rejected. |
| R5 | Create a room with bet unit **0**, **3**, or **22**; try to change the unit after B joins. | Reject each. The existing room and bet unit remain unchanged. Accept even whole-chip values from **2** through **20**. |
| R6 | Join with an invalid code, join a room already holding A and B, or try to claim A's seat with only the room code. | Reject; neither seat nor game state changes. |
| R7 | Present an invalid, expired, or other player's reconnect token. | Reject without replacing the connected player or leaking their cards. A valid token reclaims only its original seat. |
| R8 | A submits a call and a raise with different IDs at nearly the same time from two connections. | The server serializes them. Exactly one applies; the other is rejected as out of turn after the actor changes. The pot and stacks match whichever single action won, and chip total remains **400**. |
| R9 | Create a room but do not admit B yet; send A an action or advance the fake clock by 30 seconds. | No hand is dealt, no turn timer runs, and no action can change the room. |
| R10 | After a hand, A presses Ready twice while B has not pressed Ready. | Only one readiness flag is set. No new hand or blind posting occurs until B presses Ready. |

### Timers, disconnects, and race boundaries

Start a controllable clock at `t=0` when a turn begins. Do not use real sleeps in unit tests.

| ID | Input or action sequence | Expected result |
| --- | --- | --- |
| T1 | From the initial state, A makes no move through `t=30s`. | A faces a blind and cannot check, so the server folds A once. B wins the pot; final stacks **195/205** and pot **0**. |
| T2 | From G2, B has the first flop turn and makes no move through `t=30s`. | Check is legal, so the server checks B once. Pot stays **20**, board stays at three cards, and A becomes actor with a new 30-second turn. |
| T3 | A disconnects **12 seconds** into A's turn and reconnects **19 seconds** later. | No move or timeout occurs during the pause. A reclaims the seat with **18 seconds** remaining, the same cards, pot, and actor. The other player did not receive A's hole cards. |
| T4 | A disconnects and is still absent exactly **20 seconds** later. | A forfeits the match once; B is declared match winner; no further hand or turn action runs. Reconnecting after the deadline cannot resume the match. |
| T5 | A reconnects just before the 20-second deadline. | The reconnect succeeds, the hand resumes, and no forfeit result is emitted. |
| T6 | A sends a legal action just before the turn deadline, then an old timeout callback runs. | Only the action applies; the old timeout is ignored. An action arriving exactly at or after the deadline loses to the timeout. |
| T7 | Both players disconnect during the grace period. | The room closes without a winner after the grace period; neither player is falsely awarded a match win. |
| T8 | B is the active player but A disconnects. | The hand and B's turn timer pause. On A's timely return, B resumes with the time that remained, not a fresh 30 seconds. |

### Cards, showdown, and privacy

Use two fixed seven-card results whose rankings are obvious without a library. For a winner case, A has `As Ah`, B has `Kc Kd`, and the board is `2c 7d 9h Js 3c`: A's pair of aces beats B's pair of kings. For a tie case, A has `As Kh`, B has `Ac Kd`, and the board is `2c 4d 6h 8s Td`: both have the same ace-high five-card hand. Use the action path in G2 followed by checks on every later round, so the showdown pot is **20**.

| ID | Input or action sequence | Expected result |
| --- | --- | --- |
| C1 | Winner fixture reaches showdown. | A wins **20**; final stacks A **210**, B **190**, pot **0**. Both hands may be revealed only in the showdown result. |
| C2 | Tie fixture reaches showdown. | Each receives **10**; final stacks return to **200/200**, pot **0**. |
| C3 | Supply a fixed deck with a duplicate card or fewer than enough unique cards for a hand. | Reject the fixture/deal before state changes. No player sees an incomplete hand. |
| C4 | Capture **every** outbound message to A and B from join through G3, plus timer updates, errors, and both reconnect snapshots. | Before showdown, A's messages never contain B's `Kc` or `Kd`, and B's messages never contain A's `As` or `Ah`. Each sees only their own two hole cards plus currently revealed community cards. Error text sent to clients follows the same rule. |
| C5 | End the winner fixture by fold or disconnect before showdown. | The result identifies the winner but does **not** reveal the losing player's hole cards in any outbound message. |
| C6 | Inspect the flop, turn, and river messages for either player. | Board length is exactly **3**, then **4**, then **5**. Neither client receives a future board card early, and a reconnect snapshot contains only the current board. |

Under the older rule set, the highest-value automated checks are G1-G8, R1-R4, T1-T6, and C4-C6. C1-C2 check Treys integration and payout. These numeric expectations must be recalculated for the target rules in [docs/rules.md](docs/rules.md) before they are used as new acceptance tests. Planting a wrong turn, payout, or privacy filter should make the corresponding test fail.

## Implementation and attribution

The project began as a new codebase. The combined lockfile includes the following direct dependencies.

- HTTP and WebSocket routing uses [FastAPI 0.165.0](https://pypi.org/project/fastapi/0.165.0/).
- Transport validation uses [Pydantic 2.14.4](https://pypi.org/project/pydantic/2.14.4/).
- The ASGI server and WebSocket protocol use [Uvicorn 0.54.0](https://pypi.org/project/uvicorn/0.54.0/) and [websockets 17.4](https://pypi.org/project/websockets/17.4/).
- Hand evaluation uses [Treys 0.1.8](https://pypi.org/project/treys/0.1.8/).
- Development tests use [HTTPX2 2.16.2](https://pypi.org/project/httpx2/2.16.2/).
- The rules reference uses standard poker terminology. [WSOP rules](https://www.wsop.com/poker-games/texas-holdem/rules/)

The original engine and tests were built with Codex under Srishruthik's direction. Deepthi's Day 1 work added the configurable room API, private session tokens, and first-hand initialization. Srishruthik's later server work added the lobby API, connection tracking, and socket replacement. Actual partner and agent contributions will be identified in the final slides and repository history.

## Setup and demo

Use Python 3.13 and uv. No external accounts or credentials are required to run the local app and tests.

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

`server.main:app` also serves both admission contracts. Run one app entry point per server. Start with an empty process for each smoke run. In a second terminal, run the Day 1 smoke script or the integration smoke script.

```sh
uv run --locked python evidence/deepthi-day-1/smoke.py
uv run --locked python evidence/integration-day1-day3/smoke.py
```

For manual room admission, start with an empty server and replace `ROOM_CODE` with the code from A's response. Share only the room code with B.

```sh
curl -sS http://127.0.0.1:8000/health
curl -sS -H 'Content-Type: application/json' -d '{"bet_unit":10}' http://127.0.0.1:8000/api/rooms
curl -sS -H 'Content-Type: application/json' -d '{"room_code":"ROOM_CODE"}' http://127.0.0.1:8000/api/rooms/join
```

### Main files and evidence

- [poker/rooms.py](poker/rooms.py) owns room state, admission, credentials, and initial hand creation.
- [poker/server.py](poker/server.py) serves both HTTP and WebSocket contracts. [server/connections.py](server/connections.py) tracks lobby sockets by seat. [server/sessions.py](server/sessions.py) maps the older lobby API to the same room.
- [docs/protocol.md](docs/protocol.md) describes both current contracts and the gameplay decisions still open.
- [Day 1 baseline](evidence/deepthi-day-1/baseline.txt) and [Day 1 results](evidence/deepthi-day-1/test-results.txt) preserve the original checks and reproduction steps.

## Known limits of the first version

The game supports heads-up play only, one active room per server process, fixed-size bets, and no all-ins or side pots. A player who cannot afford a call must fold. These are explicit scope choices; we will record any later change and why we made it.
