# Contribution and reuse record

The proposal starts from a new codebase. Git records the README-only
repository root `c29badee2f21e6542c67a176304460b14cea13b6` and the
initial engine checkpoint `34aa2414ff9bc3841e5441cb58ea806d96008313`.
The latter is the starting checkpoint identified in the finalization
brief. The comparable historical application is `b051973`, which
already has the browser and is earlier than keyed recovery.

| Contributor | Evidence |
| --- | --- |
| Srishruthik Alle | Engine, betting, hand evaluation integration, settlement, engine tests and documentation `34aa241`, `553ea0c`, `87a1fcf`. Legacy table/session API and authenticated lobby/connection tracking `e4a6651`, `0f48df7`. |
| Deepthi Morusupalli | Canonical private rooms, transport, historical integration `b119fc2`, gameplay coordination and snapshots through `92c9f29`, deadlines and reconnection through `125c7cd`, browser through `b051973`, admission and transport reliability through `3403933`, final correctness audit through `a6903fb`, and this verification and handoff. |
| Both | Engine/application boundary, individualized evidence, final rules, interrupted pot, demonstration, and presentation. Joint signoff remains pending. |

Codex assisted with implementation, tests, diagnosis, and documentation
under contributor direction. Git and the committed checks support the
attribution. Neither a commit author field nor agent output establishes
which individual typed particular lines.
[Detailed history and dependency inventory](../final-correctness-audit/contribution-inventory.md)

The fresh environment used Python 3.13.9. Locked direct versions are
Treys 0.1.8, FastAPI 0.165.0, Uvicorn 0.54.0, websockets 17.4,
AnyIO 4.16.0, and Pydantic 2.14.4. Starlette 1.10.0 is transitive.
HTTPX2 2.16.2 is a development dependency and Playwright 1.55.0 is
optional for browser tests. Treys provides card representation and
ranking. The engine owns dealing, transitions, and accounting.
FastAPI provides the HTTP and WebSocket framework. The project
implements session authority, synchronization and client views.
[Dependency lock](../../uv.lock) ·
[Treys](https://pypi.org/project/treys/0.1.8/) ·
[FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
