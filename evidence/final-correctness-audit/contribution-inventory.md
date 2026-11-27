# Contributions and dependency inventory

The repository began at `c29badee2f21e6542c67a176304460b14cea13b6`
(README-only). The initial immutable engine is
`34aa2414ff9bc3841e5441cb58ea806d96008313`, authored by the
`shruthikalle` Git identity. The current audit started from
`340393392bb84ba0adf74a233fa114c4a541a92f`.

| Ownership | Work and commit evidence |
| --- | --- |
| Srishruthik Alle | Engine, legal betting progression and settlement, engine API and tests. `34aa241`, `553ea0c`, `87a1fcf`. Proposed target rules `e65f0c2`, compatibility HTTP admission and identity `e4a6651`, authenticated lobby and replacement `0f48df7`. |
| Deepthi Morusupalli | FastAPI and configurable private room admission `bf4e680`–`5dc015c`. Integrated room and lobby histories in `b119fc2`. Personalized snapshots, authenticated gameplay coordination, replay protection and transport verification `6aca6fb`–`92c9f29`. Deadline reconciliation, disconnect recovery and terminal states `13e08e9`–`125c7cd`. Browser UI, synchronization and browser verification `e62657f`–`b051973`. Keyed admission, monotonic watchdog, heartbeat, origin checks, and accessible browser reliability `135f9e9`–`3403933`. Final audit extends the tests and evidence and fixes the admission error association. |
| Joint | Shared engine/transport boundary, integration decisions, final rules, interrupted-pot policy, demonstration and presentation. Final approval status is recorded separately. |

The current audit uses Codex under Deepthi's direction to inspect Git
and source, write tests and the small browser fix, run local verification,
and prepare the handoff. The earlier engine work used Codex under
Srishruthik's direction according to the existing project attribution.
This describes assistance and ownership, without treating the tool
or Git account alone as evidence of an individual manual action.

| Package or tool | Actual version and role |
| --- | --- |
| Python | CPython 3.13.9 verified, `.python-version` selects 3.13. Package metadata declares `>=3.11`; other versions were outside this clean-checkout run. |
| Treys | 0.1.8, direct hand evaluation library. |
| FastAPI / Starlette | 0.165.0 direct / 1.10.0 transitive. |
| Pydantic / pydantic-core | 2.14.4 direct / 2.50.5 transitive. |
| Uvicorn / websockets / h11 | 0.54.0 and 17.4 direct, h11 0.16.0 transitive; launch uses websockets-sansio. |
| AnyIO | 4.16.0 direct, task groups and deadlines. |
| HTTPX2 / HTTPCore2 | 2.16.2 each. HTTPX2 is in the development group, HTTPCore2 is transitive. |
| Playwright / greenlet / pyee | 1.55.0 optional browser group, transitive 3.5.6 / 13.0.1. |
| Node / Ruff / uv | 26.7.0 / 0.15.20 / 0.12.3 in the audit environment. Development tools. |

[Project metadata](../../pyproject.toml) · [Resolved lock](../../uv.lock) ·
[Joint decisions](joint-decisions.md)
