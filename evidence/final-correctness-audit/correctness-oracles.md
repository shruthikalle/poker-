# Independent application oracles

These values follow from the chosen chips and visible cards. Engine
outputs were compared against the independently determined amounts.
The browser received snapshots from the actual server.

| Scenario at unit 10 | Independent calculation | Observed result |
| --- | --- | --- |
| Initial deal | Start 200 each. A posts 5 as button, B posts 10. | A 195, B 190, pot 15, A acts. |
| A calls | Pay the remaining 5, producing equal contributions of 10. | A 190, B 190, pot 20. B acts. An exact retry leaves amounts and revision unchanged. |
| A folds preflop instead | B receives the pot of 15 on top of 190. | A 195, B 205, pot 0. Opponent cards hidden. |
| Flush beats straight | Board Ah Kh Qh Jc 2d. A's hearts 9h and 5h make the five-card A-high flush Ah Kh Qh 9h 5h. B's Ts completes A-K-Q-J-T. Award A the entire checked-down pot of 20. | A 210, B 190, pot 0. A wins at showdown. |
| Tied showdown | Board As Ks Qs Js Ts is a royal flush that neither hand can beat. Both started this showdown with 190 and split 20 into 10 each. | 200/200/pot 0. Tied showdown is distinct from a both-absent match closure. |
| Ready after fold | Rotate dealer to B. A posts 10 from 195, B posts 5 from 205. | Hand 2 with A 185, B 200, pot 15, B acts first. |
| Interrupted initial hand | A 195 + B 190 + outstanding 15 = 400. No completed hand payout. | Forfeit identifies the present player and preserves stacks and pot. Late observer cannot reopen it. |

The original browser suite asserts room setup, legal actions and
private-card visibility. Its extended mixed fixture checks conservation
across five hands and four dealer rotations. The exact reconnect
tests use the independent timing equation 30 s − 12 s = 18 s, with time
paused excluded. These are finite fixtures for the retained variant.

[Backend wire checks](../../tests/test_websocket_gameplay.py) ·
[Exact deadline tests](../../tests/test_deadlines.py) ·
[Browser and wire output](browser-compatibility-results.txt) ·
[Rehearsal result](demo-rehearsal-results.txt)
