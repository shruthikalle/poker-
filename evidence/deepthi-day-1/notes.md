# Room and socket foundation

This checkpoint introduced the HTTP room boundary and one-time socket authentication.

## Decisions and checks

- **Separate admission and seat authority.** A shared room code admits B
  while the seat is vacant. Each admission returns only the caller's private
  token. The socket checks that token to identify the seat. Unit and live
  checks show both tokens map to their own seats and the shared code yields
  close code 1008 with an empty reason and no application message. Exact
  response assertions also cover private fields and forged seat claims. The
  shared-code-as-identity alternative would give anyone who received the code
  the information needed to impersonate the host.
- **Serialize seat allocation and hand initialization.** One short
  synchronous lock protects the in-memory room across HTTP worker threads
  and WebSocket authentication reads. Splitting the capacity check from
  assignment would let competing requests observe the same vacancy. Two
  barrier-based tests exercise concurrent creation and joining. Each
  observes one success and one conflict and checks the original session.
  The first-hand check independently expects stacks of 234 and 228, blinds
  of 6 and 12, and a pot of 18 at bet unit 12. A controlled token collision
  exercises the retry path and verifies that exhaustion leaves the waiting
  room intact.

The case coverage is R5 and R6. R9 has waiting-state coverage, with fake
clock and gameplay-action coverage still pending. R7 and C4 need the full
reconnect lifecycle and gameplay message stream, respectively.

## Observed development issues

- The initial baseline sync encountered a sandbox cache permission error
  and then a package-index DNS error with a writable cache. The baseline
  passed after using a temporary cache with authorized network access. The
  sandbox also blocked loopback bind with `[Errno 1] operation not permitted`.
  The authorized loopback run started and passed the smoke check.
- The first FastAPI trial ran six passing tests but emitted this warning:
  `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
  Inspecting the [Starlette TestClient documentation](https://starlette.dev/testclient/)
  confirmed the test backend. Replacing HTTPX 0.28.1 with HTTPX2 2.16.2 in
  the dev group removed the warning. The six-test rerun with
  `uv run --locked python -W error -m unittest discover -s tests -v`
  passed. The full 29-test suite also passed with warnings treated as errors.
- No application bug occurred during implementation. Duplicate tokens
  were controlled test inputs. The earlier snapshot's 404 below is the
  expected result of a feature comparison.

## Reproduce the live comparison

From the development branch, run `uv sync --locked`. In the first terminal,
start the source from before HTTP admission. This extracts a committed
snapshot into a temporary directory and uses the same locked dependencies.

```sh
DAY1_EARLIER_APP=$(mktemp -d)
git archive be518b957f9d2b076446f6725855c9ee11484608 | tar -x -C "$DAY1_EARLIER_APP"
uv run --locked uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096 --app-dir "$DAY1_EARLIER_APP"
```

In a second terminal run `uv run --locked python evidence/deepthi-day-1/smoke.py`.
The health request passes and the room request fails with 404. Stop
the first server with Ctrl-C. Start the current server from the repository
with the [README launch command](../../README.md#setup) and run the
same script again. The admission and socket assertions pass. The script
prints methods, paths, statuses, and seat status only. The captured output
is in [test-results.txt](test-results.txt).
