# Day 3 engineering evidence

The project started at `c29badee2f21e6542c67a176304460b14cea13b6`.
Day 3 started at local and remote `92c9f2991242a9245e929c10b3a0f33ca0372413`.
Both baseline suites passed 83 tests, as did the existing set of five live
scenarios. Srishruthik's earlier engine and lobby work remains in the
history. Deepthi directed Codex to implement the replay fix, authoritative
clocks, recoverable presence, transport terminal results, and their tests.
The engine and its chip rules were preserved. There was no dependency
change. The existing proposed rules and exact reconciliation draft still
await joint approval. [Baseline](baseline.txt) · [Rules reconciliation](../../docs/rules-reconciliation.md)

## Replay debugging and regression

After 256 validly formed but stale commands from one seat, the Day 2
coordinator returned `REPLAY_CAPACITY` for the next legal call. The
unchanged revision and 15-chip pot showed the engine transition had not
run. The shared pre-dispatch capacity check counted both accepted and
rejected outcomes, so filling it could strand a hand and prevent Ready.

The fix keeps accepted transitions through the next hand and caps
rejected outcomes separately with a 256-entry FIFO per seat per hand.
The same probe now accepts the call at revision 2 with pot 20.
Tests also verify that an illegal-command flood cannot block Ready,
accepted retries retain the original outcome, retained conflicts are
rejected, and an evicted rejection can be evaluated as fresh. The
poker raise cap and at most two Ready transitions bound accepted
history to 21 state-changing commands per hand across both seats.
Automatic actions consume no client identifiers.

Use the current checkout to run the same code against the old source
and then against the current code. The earlier run exits 1.

```sh
DAY3_OLD=$(mktemp -d)
git archive 92c9f2991242a9245e929c10b3a0f33ca0372413 | tar -x -C "$DAY3_OLD"
PYTHONPATH="$DAY3_OLD" uv run --locked python evidence/deepthi-day-3/replay_probe.py
uv run --locked python evidence/deepthi-day-3/replay_probe.py
```

This reproduced an existing implementation bug. It did not require
introducing a failing production variant. The old reduced-capacity
assertion was intentionally changed because it specified lockout.
Existing gameplay and delivery tests were also updated for separate
deal and activation frames and the lifecycle fields. Their action,
payout, authorization, privacy, and delivery assertions remain.
[Observed before and after](replay-results.txt)

## Controlled timing decisions

- The turn starts at 0, pauses at 12, and resumes at 20. Resetting
  on reconnect gives a deadline of 50 and 42 seconds of active decision
  time. The coordinator preserves 18 seconds, ending at 38 after
  30 total active seconds.
- At t=35, model a turn whose t=30 callback has not executed. The
  callback-only alternative delegates the late call to the engine and
  reaches pot 20. Production reconciles expiry on ingress, folds A,
  and rejects the late call. The settled pot is zero at revision 2.

The reset calculation and callback-only model are controlled
alternatives. Neither was deployed. The comparison demonstrates two
specific timelines. The separate fake-clock and live tests exercise
further cases, and finite tests cannot prove all interleavings.

```sh
uv run --locked python evidence/deepthi-day-3/decision-deadlines.py
uv run --locked python -W error -m unittest discover -s tests -p test_deadlines.py -v
```

[Measured decision results](decision-results.txt) · [Fake-clock tests](../../tests/test_deadlines.py)

## Independent timing oracles

- Unit 10 gives stacks 195/190 and pot 15. At t=30 on the initial
  turn, check is illegal. A folds and B takes 15 for 195/205, pot 0.
- After A calls and both contribute 10, B can check. Autocheck moves
  the hand to the flop with B still acting first, stacks 190/190 and
  pot 20. B's flop autocheck moves the turn to A without paying chips.
- Pausing at 12 saves 18 seconds. Returning at 20 sets expiry at 38.
  Separate cycles at 10/15 and 22/30 preserve an expiry at 43.
- Absences at 10 and 17 create deadlines 30 and 37. With both absent
  at 30 the match closes without a winner. If B returns at 25, B wins
  at 30. If A returns at 25, A wins at 37 if B is still absent.
- An exact-deadline return leaves the preceding expiry in effect.
  Transport terminal outcomes preserve stacks 195/190 and pot 15
  for an interrupted initial hand, conserving all 400 chips.

## Live verification and limits

The combined suite passed in a fresh locked environment. All five
previous live scenarios and five new timeout and recovery scenarios
passed. The new fixtures shorten turns or grace internally. Exact
boundaries are established by the manual clock rather than by
wall-clock smoke observations.

[Actual combined test output](test-results.txt) · [Live outputs and commands](smoke-results.txt)

The process owns one in-memory room. Terminal observation uses the
existing private token and preserves the terminal result. Starting a
new match after termination requires a restart. A queued writer
can be disconnected on overflow. Timer delivery is subject to the
event loop, and late authoritative input still reconciles expiry.
A deployment, browser, persistence, distributed coordination, and
reset workflow are future work. The rules, deadline, and interrupted
pot policies still require final joint sign-off. Fully approved
chip settlement for forfeits would require an explicit engine rule.
