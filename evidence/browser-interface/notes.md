# Browser interface evidence

The project began at `c29badee2f21e6542c67a176304460b14cea13b6`.
The browser work began at local and remote main
`125c7cd567aeb442732eb05a4453693d9213bbea`. Both baseline suites
passed 109 tests, and the ten existing live probes passed.
Deepthi directed Codex to implement and verify the browser interface,
including transport safety, independent browser tests, visual review,
and reproducible evidence. Srishruthik's engine and original lobby
contributions remain intact. The app entry point only gained static
routes, and the engine and gameplay messages stayed unchanged.

[Baseline](baseline.txt) · [Browser protocol](../../docs/protocol.md)

## Actual browser checks

The acceptance script uses independent Chromium contexts for A and B
and a new server for each scenario. It drives admission and mutations
through the UI. Fixture rooms use the public synthetic code FRIEND42
and known first decks. The short-stack case supplies a synthetic
but chip-conserving 10/375 state with a 15-chip pot. The engine
then settles the fold and determines the match winner normally.
The timeout and terminal fixtures shorten durations through internal
factory parameters. No public fixture route exists.

The observed hands included the 210/190 showdown, 200/200 tie, and
195/205 immediate fold. The browser bet/raise/call path observed a
60-chip pot and 170/170 stacks. Ready moved play into the next hand,
rotated the dealer, and replaced the prior showdown's exposed cards
with card backs. The reloaded browser retained its seat without an
admission POST. Reconnect, timeout, and terminal outcomes were also
observed through real WebSocket traffic.

The test script observes message types, revisions, and deterministic card
values in memory. It checks that opponent cards stay out of unauthorized
snapshots, token strings stay out of received state and logs, and
WebSocket URLs have no query string. It does not print raw authentication
frames. For lost-ack and stale-request cases, test-only WebSocket routing
drops a genuine acknowledgment or edits one request before forwarding.
The product client retries the original bytes after reconnect. The
server completes exactly one 5-chip call. Stale and illegal requests
produce a clear UI rejection and leave the pot at 15 until a deliberate
new valid call.

```sh
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium
uv run --locked --group browser python evidence/browser-interface/browser_smoke.py
node --test tests/browser/client.test.mjs
```

The standalone suite used Playwright 1.55.0 and Chromium 140.0.7339.16.
The in-app browser setup failed with a missing `sandboxPolicy` metadata
field, so the actual browser runs and screenshots came from the pinned
standalone Chromium. The suite verifies desktop gameplay and checks
horizontal overflow at a 390 px viewport. Other browser engines and
a screen-reader audit were outside this run.
[Captured scenarios](browser-test-results.txt) ·
[Existing live smoke results](regression-smoke-results.txt) ·
[Test suites, lint, dependency lock, and wheel results](test-results.txt)

## Regression investigated during implementation

On the first real Chromium launch after creating a room, the header
stayed at Connecting and the page displayed `Illegal invocation`.
The admission request returned a room, and server logs showed the
WebSocket connect. This ruled out room validation and the socket URL
as causes of that first failure. The default timer functions had been
stored as connection properties and invoked with the connection object
as their receiver. Chromium's browser-provided method expected the
browser global. Calling the global methods through wrappers resolved
the failure. The Node regression checks receiver binding and the
browser suite exercises actual authentication, retry, and cancellation.

Two initial browser-harness failures also sharpened the checks. The
paused control label becomes Call when the server withholds its amount.
The assertion now checks that disabled Call label. The lost-ack fixture
installs its WebSocket interceptor before navigation so it observes the
intended socket.
[Actual failure and post-fix output](debug-results.txt)

## Controlled client comparisons

The engine-only filter ignored pause and resume because both samples
had engine revision 1. The production pair accepted lifecycle
revisions 3 and 4. A counter decremented once after a simulated
12,341 ms callback delay showed 29,000 ms. The monotonic anchor showed
17,659 ms, matching the independent elapsed-time calculation.
These are controlled models, with network and scheduling differences
outside the experiment.

```sh
node evidence/browser-interface/decisions.mjs
```

[Measured client comparisons](decision-results.txt)

## Screenshots and limitations

The checked-in images are genuine deterministic Chromium captures. Their
room code is synthetic and their cards are fixed fixtures. Screenshot
generation is available with
`--screenshots evidence/browser-interface/screenshots` when running the
browser smoke script.

[Waiting room](screenshots/waiting.png) · [Active hand](screenshots/active.png) ·
[Showdown](screenshots/showdown.png) · [Paused hand](screenshots/paused.png) ·
[Terminal result](screenshots/terminal.png)

This is a one-room, one-worker local deployment. Browser storage survives
refresh in the same tab. Duplicated tabs can inherit the same session,
same-origin scripts and browser developer tools can inspect storage,
and a server restart invalidates sessions. A temporary network failure
does not erase the stored seat. A server that commits admission just
before the response is lost has no idempotent admission recovery.
Browser countdowns are sampled estimates. The server determines
deadlines and retry outcomes. Explicitly restart the process for a
new match. Joint poker rules and interrupted-pot approval remain pending.
