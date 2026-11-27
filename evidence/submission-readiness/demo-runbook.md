# Live demo runbook

Use the final submission SHA confirmed in the verification report.
Start from a clean checkout with Python 3.13 and uv. Preview the slide
evidence locally, start one Uvicorn process, and open two independently
created tabs or browser profiles. Duplicate tabs can share a seat.
Clear expired seats through **Leave table** before the rehearsal.

## Launch and known answer

```sh
uv sync --locked
uv run --locked uvicorn launch:showdown --factory --app-dir evidence/deepthi-day-2 --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

Open `http://127.0.0.1:8000/` in both windows. The fixture provides
the first deck at construction. It uses the normal 30-second turn and
20-second grace. The production launch in the README shuffles cards.

- Create at unit 10, join by room code, and point out A 195/B 190,
  pot 15, dealer A, hidden opponent cards and the legal actions.
- A calls 5, taking the pot to 20. B checks once to reach the flop.
  On flop, turn and river, B checks then A checks. Board is Ah Kh Qh
  Jc 2d. A has 9h 5h, giving an ace-high flush. B has Ts 3c, giving an
  ace-high straight. A wins 210/190, pot 0. Both players Ready and
  the dealer rotates. [Independent oracle](../final-correctness-audit/correctness-oracles.md)
- Let several seconds of a new turn elapse. Navigate away in one
  browser. Show the peer's paused time and reconnect before grace
  expires in the same browser tab. Display estimates can round.
  [Measured protocol rehearsal](demo-rehearsal-results.txt)

The wrong-turn check uses a **fresh process** started with the same
fixture and the normal browser table vacated. In a second terminal run
`uv run --locked python evidence/submission-readiness/demo_protocol.py`.
It acts as both authenticated seats, tries B's fold on A's turn, then
samples both views. Pot 15, actor A and revision 1 remain unchanged.
It also demonstrates a paused turn after time has elapsed and a
reconnect with the same seat. Restart the fixture afterward for manual
play. The probe leaves the room allocated in that process.

## Suggested 20-minute sequence

| Time | Lead | Demonstration |
| --- | --- | --- |
| 0–2 min | Both | Explain private virtual-chip poker, project scope and original starting point. |
| 2–5 min | Deepthi | Draw the engine/transport boundary and create/join from two independent windows. |
| 5–9 min | Srishruthik | Work out the flush-versus-straight result, play the hand, show the payout, and advance with Ready. |
| 9–12 min | Deepthi | Show wrong-turn rejection and live pause/resume. Use a fresh process for each independent path. |
| 12–15 min | Deepthi | Explain lost admission and the exact recovery evidence. |
| 15–17 min | Both | Explain the controlled deadline comparison and how the engine executes the resulting check or fold. |
| 17–19 min | Deepthi | Present the lost-ack watchdog story and why one mutation matters. |
| 19–20 min | Both | Explain the in-memory restart limit and take questions if time permits. |

## Fallbacks

| Issue | Recovery |
| --- | --- |
| Port 8000 in use | Use another free loopback port. Change both browser URLs and the probe's `--url`. |
| Server absent or dependencies unavailable | Check `/health`, verify Python 3.13 and rerun `uv sync --locked`. Use the prevalidated installed wheel environment if prepared. |
| Existing room or expired session | Leave stale seats and restart the local fixture. Keep independent tabs. |
| Temporary disconnection | Recover in the same tab before the displayed grace expires. If the server declares terminal, show the outcome and start a fresh process for further play. |
| Randomized deal | Relaunch the deterministic fixture. Use its independently calculated first hand. |
| Browser automation unavailable | Perform the browser workflow manually. The protocol and engine tests run without browser tooling. |

Stop the local server after the demo and close both demo tabs. The
measured rehearsal was automated. Both partners still need to rehearse
the timing and speaker handoffs together.
