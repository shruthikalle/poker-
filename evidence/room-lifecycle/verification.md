# Room lifecycle verification

## Live comparison

The [baseline output](baseline.txt) records the old behavior from `c8e9249`
and the fetched starting commit `868ab17`. To exercise the same probe on
the final app, start an empty default PDF room with the one-second grace
fixture. The fixture uses the production engine factory and retains the
real 60-second terminal retention.

```sh
uv run --locked uvicorn launch:room_lifecycle --factory --app-dir evidence/browser-interface --host 127.0.0.1 --port 8041 --ws websockets-sansio --ws-max-size 4096 --no-access-log
```

```sh
uv run --locked python evidence/room-lifecycle/rollover_probe.py --port 8041 --release
```

The final probe recorded the same private forfeit view and then the new
release boundary in the same process.

```text
POST /api/rooms -> 201; POST /api/rooms/join -> 200; two distinct seats
Both authenticated seats observed hand 1 in play
Terminal snapshot: {"hand_id": 1, "match_result": {"reason": "forfeit", "winner": "A"}, "pot": 15, "stacks": {"A": 495, "B": 490}}
POST /api/rooms after terminal -> 409 {"detail":"an active room already exists"}
Returning seat B observed the same terminal result and its own cards
Explicit release -> close 4001 for both seats; acknowledgment alone retained the room
Original create and join retry -> 409 ADMISSION_EXPIRED
Fresh admission in the same process -> 201/200; hand 1, revision 1, A/B 495/490 + pot 15
```

## Deterministic and repeated verification

```sh
uv run --locked python -W error -m unittest discover -s tests -p test_room_lifecycle.py -v
uv run --locked python -W error -m unittest discover -s tests -p test_generation_admission.py -v
```

The tests use the in-memory app and an injectable monotonic clock. They
exercise release at −1, 0 and +1 ns from eligibility, simultaneous
acknowledgment and release, create racing with release, retired admission
with and without a new room, a blocked writer, delayed connection cleanup
and scheduler wakeups, and restart isolation for scoped keys. The fixture
for an engine-terminal fold conserves chips and checks the existing paid
hand. A second legacy room uses unit 12 and starts 234/228 with an 18-chip
pot. This is separate from the normal PDF room, which starts 495/490 with a
15-chip pot after blinds.

```text
Rollover audit: 25 rooms; 50 distinct tokens; 1 scheduler start; peak active gameplay/lobby writers 2; sampled initial queue peak 1/32; 0 writers, replay entries, admission records or deadlines after each release
```

The runner counted one scheduler start and checked scheduler shutdown. It
sampled the initial queue at each connection and checked current registry,
replay, admission and deadline state at retirement. The existing separate
50-replacement regression peaked at three tracked writers and ended with
zero. These runs exercise bounded in-process cleanup over a finite sample.

## Browsers and regression

```sh
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium firefox webkit
uv run --locked --group browser python evidence/room-lifecycle/browser_matches.py --retention
uv run --locked --group browser python evidence/room-lifecycle/browser_matches.py --browser firefox
uv run --locked --group browser python evidence/room-lifecycle/browser_matches.py --browser webkit
uv run --locked --group browser python evidence/room-lifecycle/browser_matches.py --peer firefox
uv run --locked --group browser python evidence/room-lifecycle/browser_matches.py --peer webkit
```

| Pairing | Result |
| --- | --- |
| Chromium 140.0.7339.16 × Chromium | Three consecutive matches. One-seat acknowledgment with real 60-second retention. |
| Firefox 141.0 × Firefox | Three consecutive matches. |
| WebKit 26.0 × WebKit | Three consecutive matches. |
| Chromium × Firefox | Three consecutive matches. |
| Chromium × WebKit | Three consecutive matches. |

Each pairing used one server process and separate browser contexts. The
probe observed private cards, distinct codes and tokens, keyboard controls,
restored lobby focus, a 390px terminal layout, a replaced tab, a missed
retirement notification, and refresh with the old session still stored.
The existing suite also passed 12 scenarios per engine (36 total), the PDF
known-answer showdown, seven Chromium reliability scenarios, and both
mixed-browser five-hand checks. The earlier accessibility and layout runner
passed six widths, 200% root text sizing, keyboard and touch checks. Ten
earlier live HTTP/WebSocket smoke scenarios passed with their documented
default or legacy fixture. The unchanged seeded simulation matched the
recorded JSON byte-for-byte (1,000 hands, 7,951 accepted actions).

The existing complete player journey passed in Chromium, Firefox, and
WebKit. The Chromium audit also passed cached history restoration,
offline history, pending-command history, form feedback, repeat input,
page suspension, the combined rehearsal, and its recovery scenarios.
Native Chromium tab zoom passed at 100%, 150%, and 200% with keyboard
control and reflow.

```text
Python: Ran 146 tests — OK
Python warnings as errors: Ran 146 tests — OK
Node: 16 tests, 16 pass, 0 fail, 0 skipped
Ruff: All checks passed! 56 files already formatted
Lock: Resolved 24 packages
Dependency check: All installed packages are compatible
```

An offline, locked runtime-only installation built and loaded the wheel
from outside the checkout. The health/admission/socket path and the live
release probe passed. All seven assets returned HTTP 200. The target
runtime environment did not contain Playwright. Browser checks used a
separate dev environment. The historical installed-browser audit also
passed on a legacy ruleset launched from that wheel. The app serves the
bundled JS directly.

## Observed debugging results

- The first signed-token draft kept URL-safe characters but exceeded the
  existing 43-character token contract. The unchanged credential-format
  regression reported `AssertionError: Regex didn't match`. Checking the
  output length isolated the failure from the authentication flow. The
  32-byte packed representation restored the 43-character wire shape.
  The strict suite then passed all 136 existing tests.
- A browser fixture using Playwright 1.55 WebSocket routing raised
  `KeyError: 'code'` in `_channel_close_server`. Watching the browser's
  native close event directly avoids that routing hook. An initial refresh
  race also reported `Locator expected to be focused` on seat B because it
  could already have discarded its session before the reload. The fixture
  now waits for B's intentionally dropped 4001 event before refreshing.
  All five pairings passed with these controls. Dropping close events is a
  verification experiment, not a historical production outage.
