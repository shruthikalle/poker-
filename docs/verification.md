# Known-answer cases

These fixtures describe the implemented variant. Exact deadline boundaries use a controllable clock. The live browser fixtures include additional fixed showdown and tie deals.

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
| R7 | Present an invalid or expired reconnect token. | Reject without replacing the connected player or leaking their cards. A valid bearer token authenticates its own seat. |
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
