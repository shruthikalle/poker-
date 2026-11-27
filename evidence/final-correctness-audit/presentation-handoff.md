# Presentation handoff

**Project** Heads-Up Live Poker, a local two-player virtual-chip game.
Contributors are Deepthi Morusupalli and Srishruthik Alle. The repository
contains the browser, authoritative server, engine and reproducible fixtures.
The clean application and installed-wheel rehearsal used
`651a03cb7e23f688230d34603ac2f9663d6a93c3`. Use the verified final
default-branch revision for submission. [Repository](https://github.com/shruthikalle/poker-)
The official course instructions and source proposal were unavailable to
this audit. Confirm delivery format, duration, contributor identifiers,
and deadlines using the official materials. No slides or PDF were prepared.

## Evidence worth presenting

| Question and decision | Actual result | Relevant source and commits |
| --- | --- | --- |
| How can a tab recover a seat when the HTTP response is lost? Use keyed replay under the room lock. | The archived baseline returned 409 despite allocating the seat. The fixed probe recovered both original responses across refresh and posted one set of blinds. A restart workaround would erase the match. | `poker/rooms.py`, `poker/server.py`, browser session module. `135f9e9`, `e4eec2b`. [Before and after](engineering-comparisons.txt) |
| How do we prevent late requests from bypassing a delayed scheduler? Reconcile deadlines inside the room transaction. | The controlled callback-only model accepted a late call at t=35. Production folded first at revision 2 and left pot 0. Deadline 38 preserved 30 active seconds after a pause, while reset-on-reconnect modeled 42. | `server/coordinator.py`, `server/timers.py`. `50093d9`, `9247cd0`, `29f95bb`. [Generator](../deepthi-day-3/decision-deadlines.py) |
| How can lost acknowledgment recovery stay bounded during snapshot traffic? Set one deadline per transmission. | The historical browser was still pending after 5.8 seconds. Current recovery replayed the exact command near 4.5 seconds. Both observations ended at revision 2 and pot 20. | Browser connection and app modules. `135f9e9`, `3391a65`. [Generator](../browser-reliability/recovery_probe.py) |

For a debugging story, lead with the lost-acknowledgment watchdog.
A regular call committed and reached the other player, but the acting
browser kept waiting. Interception discarded just the acknowledgment
while repeated real snapshots continued. That separated delivery loss
from a server mutation problem and showed the resetting timer. The
stable watchdog, exact bytes, and final revision make the fix visible.
The original Chromium timer-receiver issue at `4d9af92` is a second short
story with a DOM diagnostic and a focused regression. The final audit's
admission error is also supported by the observed ARIA attributes.
[Original receiver diagnostic](../browser-interface/debug-results.txt) ·
[Final accessibility regression](accessibility-results.txt)

## Rehearsal and demo sequence

Run the ordinary randomized app for normal usage. For the demonstration
use the local fixture. The fixture supplies the first deck internally.
It exposes no public deck-setting endpoint.

```sh
uv sync --locked
uv run --locked uvicorn launch:showdown --factory --app-dir evidence/browser-interface --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

1. Open two independently created browser windows. Create a room, then
   join with its code. Point out 195/190 plus pot 15, the dealer,
   hidden opponent cards, and legal actions.
2. A calls 5. B checks the big blind option and starts the flop.
   For each remaining street B checks, then A checks. Reveal A's flush
   over B's straight and the independently expected 210/190 payout.
3. Both Ready. Note the rotated dealer and pause the hand by navigating
   one window away. Return within the fixture grace period to
   show the saved countdown and same seat.
4. For a fast terminal example, restart with `launch:expiry` using
   the same flags and let one player leave. The fixture intentionally
   shortens grace. Point out the match winner and the unawarded pot.
5. Show the admission and watchdog comparison with tracked output.
   Reserve exact timing claims for deterministic tests.

For a port conflict use another unused loopback port and the matching
browser URL. Verify `/health` if the process is absent. If a table is
occupied or a restart invalidates the seats, leave any stale session,
restart the local process if needed, and use independent browser
windows. If automation is unavailable, use the same manual sequence.
Only report the performed application-level rehearsal. A joint rehearsal
and timing rehearsal for the presentation remain pending.
[Rehearsal output](demo-rehearsal-results.txt) · [Known answers](correctness-oracles.md)

## Claims and limits

Supported claims include two independent seats, private-card filtering,
exact replay under its retention contract, authoritative deadline
reconciliation, loaded and cached history cases actually recorded,
and the finite browser and resource runs. The verification leaves
hardware, screen-reader speech, broad production security, long-run
resource leakage, the target poker variant, and joint approval open.
[Contributions](contribution-inventory.md) · [Open decisions](joint-decisions.md)
