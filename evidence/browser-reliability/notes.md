# Browser reliability evidence

The clean local and remote starting point was
`b051973843c36a593ca40516f6f43a51a332b60d` (35 commits). Deepthi
directed the browser, transport, and verification work with Codex.
Srishruthik's poker engine and original lobby work remain in the
history. This change preserves the implemented rules. Approval of the
target rules and interrupted-pot settlement remains a joint decision.

[Baseline verification](baseline.txt) · [Case matrix](matrix.md) ·
[Protocol](../../docs/protocol.md)

## Lost admission responses

The probe forwarded the real browser request to the local server,
observed the successful upstream status, and aborted the response
before browser delivery. Against the baseline, create returned
201 then 409 and join returned 200 then 409, with the seats already
reserved. The in-memory diagnostic authenticated the original token
without printing it. Blind retry was the observed baseline behavior.
Restarting would free the blocked process at the cost of the entire
match. A keyed retry retrieves the original response without a reset.

The fix keeps only successful records, bound to the operation and
validated input. The already-reserved result replays under the same
room lock as allocation. The browser stores the request before sending
and can restore it following refresh. On the fixed run, both responses
matched in memory, the two browsers reached hand 1 with pot 15, and a
third join was refused. The script separately dropped a request before
it reached the server, then verified allocation on the exact retry.
Concurrent retries and the storage bound are also covered by backend
tests. One-process retention remains a property of the design.

[Reproduction source](recovery_probe.py) · [Baseline reproduction](recovery-before.txt) ·
[Fixed admission results](admission-results.txt)

## Pending-command watchdog

The first acknowledgment was dropped after the real server accepted a
5-chip call. A fixture requested current snapshots approximately every
600 ms, including unchanged engine revisions. The original client
reset its watchdog on every accepted snapshot and was still pending
after 5.81 s with ten snapshot requests and one send. With the fixed
deadline the browser reconnected and replayed the same bytes at about
4.5 s. The last state in both cases was pot 20 and A's stack 190, as
expected for one call. The Node test checks the deadline without
real-time sleeps. Separate browser checks cover a missing authoritative
snapshot after acknowledgment and refresh during a pending action.
These elapsed times describe the fixture. They are sensitive to browser
and operating system scheduling.

[Original observations](recovery-before.txt) · [Fixed watchdog observations](command-results.txt) ·
[Additional browser checks](browser-test-results.txt)

## Touch and accessibility

Rapidly tapping Check twice on the mobile viewport sent two legal
checks because B could check on consecutive streets. A command lock
covered the in-flight request but released at the next authoritative
snapshot, before the second tap. The touch-only 350 ms guard suppressed
the duplicate while allowing separate keyboard and mouse actions.
The same fixture confirmed one outbound Check after the fix.

The keyboard checks exercised actual Tab and Shift+Tab, Space and
Enter across room creation, code copy, showdown, and Ready.
Role/name snapshots covered rank/suit descriptions and hidden
opponent cards. Control focus and representative computed color
contrast were checked. Table announcements update on meaningful
state changes, and the timeout message uses a separate live region.
The application does not announce timer ticks. Testing used headless
browsers and a touch-enabled context. Actual screen-reader speech,
physical devices, native page zoom, and a full accessibility
conformance audit remain open.
[WCAG 2.2 techniques and criteria](https://www.w3.org/WAI/WCAG22/Understanding/)

[Touch reproduction](touch-reproduction.txt) · [Accessibility results](usability-results.txt) ·
[Desktop](screenshots/desktop-table.png) · [Mobile touch](screenshots/touch-table.png)

## Reproduce

```sh
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium firefox webkit
uv run --locked --group browser python evidence/browser-interface/browser_smoke.py --browser chromium
uv run --locked --group browser python evidence/browser-interface/browser_smoke.py --browser firefox
uv run --locked --group browser python evidence/browser-interface/browser_smoke.py --browser webkit
uv run --locked --group browser python evidence/browser-reliability/recovery_probe.py --only admission
uv run --locked --group browser python evidence/browser-reliability/recovery_probe.py --only watchdog
uv run --locked --group browser python evidence/browser-reliability/browser_checks.py --peer firefox
uv run --locked --group browser python evidence/browser-reliability/browser_checks.py --peer webkit --scenario extended
uv run --locked --group browser python evidence/browser-reliability/browser_checks.py --scenario usability
node --test tests/browser/client.test.mjs
node evidence/browser-interface/decisions.mjs
```

For the existing live smoke checks, start a fresh Uvicorn process for
each row or scenario on `127.0.0.1:8000` with
`--workers 1 --ws websockets-sansio --ws-max-size 4096`. In a second
terminal, prefix each listed Python command with `uv run --locked python`.

| Uvicorn app and options | Python smoke path and options |
| --- | --- |
| `poker.server:create_app --factory` | `evidence/deepthi-day-1/smoke.py` |
| `server.main:app` | `evidence/integration-day1-day3/smoke.py` |
| `launch:showdown --factory --app-dir evidence/deepthi-day-2` | `evidence/deepthi-day-2/smoke.py --scenario showdown` or `--scenario fold` |
| `launch:tie --factory --app-dir evidence/deepthi-day-2` | `evidence/deepthi-day-2/smoke.py --scenario tie` |
| `launch:timeout --factory --app-dir evidence/deepthi-day-3` | `evidence/deepthi-day-3/smoke.py --scenario timeout-fold` or `--scenario timeout-check` |
| `launch:recovery --factory --app-dir evidence/deepthi-day-3` | `evidence/deepthi-day-3/smoke.py --scenario reconnect`, `--scenario forfeit`, or `--scenario both-absent` |

To reproduce the historical admission and watchdog behavior, archive
the baseline into a temporary directory and copy the same probe into
it. Keep the browser cache environment variable exported if the
browsers are installed outside the default cache directory.

```sh
checkout="$(mktemp -d)"
git archive b051973843c36a593ca40516f6f43a51a332b60d | tar -x -C "$checkout"
mkdir -p "$checkout/evidence/browser-reliability"
cp evidence/browser-reliability/recovery_probe.py "$checkout/evidence/browser-reliability/"
(cd "$checkout" && uv run --locked --group browser python evidence/browser-reliability/recovery_probe.py --baseline)
```

Runners use deterministic cards and a synthetic room code. Credentials
are compared in memory. Committed outputs omit raw HTTP headers,
authentication frames, and tool call logs. The slow-writer and exact
grace boundary checks run under existing backend fixtures. Browser page
events supplement socket authentication and do not advance server time.

[Browser versions and results](browser-compatibility-results.txt) ·
[Final backend and client tests](test-results.txt) ·
[Existing live fixture results](regression-smoke-results.txt)
