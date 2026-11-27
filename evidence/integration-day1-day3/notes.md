# Engine and admission integration

| Input | Commit |
| --- | --- |
| Canonical admission branch | `5dc015ceaee057b77c3b98a9313f7778a5da1c7c` |
| Srishruthik's Days 1–3 on `origin/main` | `0f48df7af44e24e8dfb472bd16e0ef8c82bf923d` |
| Common ancestor | `34aa2414ff9bc3841e5441cb58ea806d96008313` |
| Integration merge | `b119fc20c0f823af76148bbbd33097d650a2d4f6` |

Before the admission branch was published, `git ls-remote --heads origin` listed only `main`.
The partner's five commits after the common ancestor were already reachable
from that branch. The admission suite passed 29 tests before its branch was
pushed and verified against the local SHA. The integration merge has both
input commits as parents.

## Merge conflicts and resolutions

| File | Changes combined |
| --- | --- |
| `README.md` | Deepthi added room and status behavior, launch instructions, and evidence. Srishruthik described the settled engine, lobby, and forward-looking rules and responsibilities. The merged README describes the implemented behavior, preserves the original fixtures with the updated showdown expectations, and identifies the draft rules and ownership decisions. |
| `docs/protocol.md` | Both partners added a protocol with different HTTP routes, WebSocket authentication forms, snapshots, and action replay proposals. The merged contract documents both implemented lobby formats over the shared room and records the unresolved gameplay schema decisions. |
| `pyproject.toml` | Deepthi added the newer FastAPI and Uvicorn stack, Pydantic, websockets, and HTTPX2. Srishruthik added Treys, pinned the older FastAPI and Uvicorn stack with HTTPX for tests, and packaged `server`. The combined project packages both modules, includes Treys, and retains the canonical transport and supported test backend. |
| `uv.lock` | Both branches had generated different dependency sets. uv regenerated the lock from the merged declarations. `uv sync --locked` and the lock check passed. |

`poker/engine.py`, `poker/__init__.py`, `server/connections.py`, and the
existing engine, gameplay, and session test files match the partner input.
The lobby test fixture changed only to use one TestClient context. All
original tests and assertions remain.

## Compatibility and checks

- **Hand creation.** `new_game(bet_unit=…, deck=None)` still accepts the
  host's selected unit. At 12 the combined regression checks hand 1, actor A,
  stacks 234 and 228, contributions 6 and 12, and pot 18. At the lobby
  default of 10 it checks stacks 195 and 190. Both join paths publish the
  same immutable hand after B is admitted. A rejected competing join
  preserves that hand object.
- **Two implementations of admission.** The branches had independent
  session state and different HTTP paths, success statuses, errors, and
  payloads. Both sets of endpoints now share one `RoomManager` and one
  lobby registry per running app. The lobby adapter preserves Bearer
  identity lookup, coded errors, and default-unit creation. Either join path
  updates lobby subscribers. Combined regression tests run each creation
  path against the other join path and test shared room capacity.
- **Two WebSocket contracts.** One-time status clients still receive a one-time
  `room_status` after an `authenticate` frame. Lobby clients receive
  personalized `lobby` broadcasts after an `auth` frame and retain
  replacement, connection flags, and ping/pong. Only lobby sockets
  participate in presence. Both formats use the same seat credentials.
  The app entry point determines how to reply to a malformed first frame
  with no recognizable type. Existing exact-payload tests and the real
  loopback scripts check that credentials, hole cards, and deck data stay
  out of lobby replies.
- **Non-ASCII joins.** On `0f48df7`, an unknown room code of `café`
  returned HTTP 500. Running TestClient with exception propagation
  exposed the `compare_digest` ASCII-only string comparison. The shared
  room lookup checks ASCII before comparing. Regression and live tests
  verify controlled 404s, and the unit check verifies no seat or hand change.
- **Test dependencies and event loops.** The partner snapshot passed
  31 tests with default warnings. With `-W error`, Starlette 0.50.0
  imported the deprecated AnyIO `BlockingPortal` alias and prevented two
  test modules from loading. The combined lock uses Starlette 1.10.0
  through FastAPI and the HTTPX2 dev backend. On the updated TestClient,
  the partner's two-socket test stalled while A waited for B's broadcast.
  A traced run showed A's socket, the join request, and B's socket running
  on different event loops. Entering the client context made callbacks share
  one loop and delivered the expected update. All assertions stayed intact.
  The live check also verified replacement and disconnect presence over
  the actual Uvicorn socket.

[Captured commands and results](test-results.txt)

## Reproduction

Run the combined verification from the integration checkout.

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -W error -m unittest discover -s tests -v
uv lock --check
uvx ruff==0.15.20 check .
uvx ruff==0.15.20 format --check .
git diff --check
```

For live verification, start a clean server for each script using the
launch commands in the captured results. The scripts print status codes
and permission-safe summaries. They keep generated credentials in memory.

To reproduce the partner dependency result, export the parent into a
temporary checkout and use its own lockfile.

```sh
PARTNER_CHECKOUT=$(mktemp -d)
git archive 0f48df7 | tar -x -C "$PARTNER_CHECKOUT"
cd "$PARTNER_CHECKOUT"
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -W error -m unittest discover -s tests -v
```

The Unicode failure uses the same exported snapshot. Create an empty
lobby app with `server.main.create_app`, then send `POST /api/table`
and `POST /api/join` with `{"room_code":"café"}`. With exception
propagation enabled, the second request raises the captured TypeError.
