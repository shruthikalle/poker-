# Day 2 engineering notes

The repository began at `c29badee2f21e6542c67a176304460b14cea13b6`. Day 2
started at local and remote main `eee3489c8675d770f9bc9ff0018584f4464d7dc1`.
That tip contains the seven Deepthi Day 1 commits and Srishruthik's engine,
lobby admission, and replacement-safe registry. Both baseline suites ran
58 tests and passed. [Baseline capture](baseline.txt)

Deepthi's Day 2 brief directed Codex to implement and validate the transport
milestone, preserve the engine and earlier test assertions, and record
the actual repository, test, and GitHub results. This branch uses the
current configurable engine. The exact proposed rules reconciliation
is ready for joint approval. [Rules reconciliation](../../docs/rules-reconciliation.md)

## Known-answer hands

The fixture lists the cards in engine deal order, with no burns.
A's `9h 5h` makes an ace-high flush on `Ah Kh Qh Jc 2d`. B's
`Ts 3c` makes an ace-high straight. The tie fixture's five spades
form a royal flush on the board for both players. Each starts with 200
chips. Initial stacks are 195/190 after the 5/10 blinds. Calling
5 makes the stacks 190/190 and pot 20. Checks through the remaining
streets settle the pot at 210/190 for the flush and 200/200 for the
board tie. An immediate A fold pays B the 15-chip pot for 195/205.
All settlements leave pot zero and 400 chips in public stacks.

The independent flop accounting checks an opening bet, two raises,
and a call. After both preflop contributions reach 10, B bets 10 for
190/180 and pot 30. A pays 20 to raise for 170/180 and pot 50.
B pays 20 to raise for 170/160 and pot 70. A third raise is rejected.
A calls 10 for 160/160 and pot 80 on the turn. The socket tests
assert these values and both public views at each step. [Wire tests](../../tests/test_websocket_gameplay.py)

## Controlled comparisons

- **Private views.** The same checker evaluated a raw engine dataclass
  and the production A snapshot for the known initial state. The raw
  engine alternative exposed both B cards, 48 undealt cards, and four
  forbidden internal fields. The production view exposed none of those.
  The raw engine object itself has no room credentials, so both
  representations scored zero on that check. The result covers this
  fixture and the explicit field checks. The wire tests extend coverage
  across both seats, all streets, and settlement. The alternative ran
  offline and never existed as a production route.
- **Atomic command coordination.** A barrier let two copies of one call
  pass checks before either could publish in a controlled split-check
  model. Both invoked the real engine on the same starting state and
  published outcomes, producing two revisions for one logical command.
  The last write left pot 20 and a single visible 5-chip deduction, so
  chip conservation alone missed the failure. The production coordinator
  invoked the engine once, published one revision, and returned two
  copies of the original acknowledgment. The comparison exercises one
  interleaving and models a split implementation that lacks a recheck.
  Other competing actions, replacement, queue overflow, and blocked
  writer behavior are covered by the coordinator tests.

```sh
uv run --locked python evidence/deepthi-day-2/decision-privacy.py
uv run --locked python evidence/deepthi-day-2/decision-coordination.py
```

[Privacy measurements](decision-privacy-results.txt) ·
[Coordination measurements](decision-coordination-results.txt)

## Actual debugging

The first queued socket implementation caused five existing tests to
fail on context exit with `concurrent.futures._base.CancelledError`.
They had received their expected messages before teardown. The failures
included lobby updates, replacement, and two mixed-route tests. Running
the five lobby tests in isolation ruled out ordering with other test
modules. Replacing manual task cancellation with an asyncio TaskGroup
still left three teardown errors in that targeted run. Inspection of
Starlette's installed TestClient showed that socket exit cancels an
AnyIO scope and waits for the app future. Moving the reader, writer, and
close watcher into an AnyIO task group scoped cancellation coherently
with that lifecycle. The same five lobby tests all passed, with their
assertions intact. The full suite and live probes also passed. AnyIO was
already locked transitively at 4.16.0 and is now a direct dependency.

The intermediate variants were genuine working-tree failures.
The captured outputs are excerpts. The old drafts were superseded before
commit. The committed regression reruns the same lobby tests and adds
blocked-writer replacement and failed-send checks.

```sh
uv run --locked python -W error -m unittest discover -s tests -p test_connections.py -v
uv run --locked python -W error -m unittest discover -s tests -p test_coordinator.py -v
```

The earlier integration's non-ASCII room-code 500, dependency warning,
and event-loop stall artifacts remain available. The non-ASCII reproducer
remains the simplest historical presentation story. [Day 1 integration debugging](../integration-day1-day3/notes.md)

## Historical feature comparison and live runs

Keep the current checkout as the working directory. Export the earlier
source and start its server on loopback in a first terminal.

```sh
DAY2_EARLIER=$(mktemp -d)
git archive eee3489c8675d770f9bc9ff0018584f4464d7dc1 | tar -x -C "$DAY2_EARLIER"
uv run --locked uvicorn poker.server:create_app --factory --app-dir "$DAY2_EARLIER" --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

In another terminal, run the current `smoke.py --scenario showdown`
with uv as shown below. The old app returns `INVALID_MESSAGE` to the
gameplay handshake and the script exits 1. Stop it, then start a fresh
Day 2 fixture server for each check. The exact same command passes
against Day 2.

```sh
uv run --locked python evidence/deepthi-day-2/smoke.py --scenario showdown
```

[Launch and scenario commands](../../README.md#setup-and-demo) ·
[Captured live results](smoke-results.txt) · [Combined suite output](test-results.txt)

## Limits and handoff

One process and one in-memory room. Gameplay has no clock, forfeits,
timed recovery, or browser yet. Replacing a socket is supported.
Queues and replay storage are bounded. Overflow closes the connection
and requires a new snapshot or a retry within retention. A seat that
exhausts 256 distinct command IDs in a hand loses the ability to submit
new IDs for that hand. Sessions, decks, and replay outcomes are lost
on process restart. The app uses local origin validation, private token
authentication, and loopback for the documented local demo. Production
deployment and rate limiting are outside this milestone.

Before changing poker rules, obtain joint approval. For the next
transport milestone, use a monotonic clock and apply timeout/reconnect
callbacks within the same room boundary. Preserve the paid showdown
and fold privacy behavior in every new message type.
