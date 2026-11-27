# Heads-Up Live Poker

A local two-player Texas Hold’em game with private rooms, fixed-size wagers,
and virtual chips. The server owns the game state and deadlines. Each browser
receives a view for its authenticated seat.

## Setup

Python 3.13 and [uv](https://docs.astral.sh/uv/) are used for the locked setup.

```sh
uv sync --locked --no-dev
uv run --locked --no-dev uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

Open http://127.0.0.1:8000/. Select a bet unit and create a room.
Copy the room code to an independently opened tab or browser profile
and join there. A duplicated tab can inherit the original seat.
Use the enabled controls. A call or raise label shows the chips paid
for that action. Both players select **Ready** after a settled hand.
Refresh the same tab to recover its seat. If room admission is uncertain,
select **Retry admission** to recover the original reservation.

## Rules and architecture

The [implemented rules](docs/rules-reconciliation.md) cover betting, payout,
Ready, and match termination. The [alternative rules draft](docs/rules.md)
is retained for technical review. The implemented variant and interrupted-pot
policy remain pending joint approval.

- [Engine](poker/engine.py) owns cards, legal moves, immutable transitions,
  settlement, and dealer rotation. Treys provides hand evaluation.
- [Room manager](poker/rooms.py) owns admission, seat credentials, and
  atomic recovery of a successful reservation.
- [FastAPI transport](poker/server.py) and [coordinator](server/coordinator.py)
  authenticate sockets, serialize commands, reconcile deadlines, and
  deliver [personalized views](server/views.py). See the [wire contract](docs/protocol.md).
- [Browser assets](server/static/) use native modules and require no
  frontend build. They render authoritative snapshots and retain exact
  pending requests across recoverable interruptions.

## Verification

```sh
uv sync --locked
uv run --locked python -W error -m unittest discover -s tests -v
node --test tests/browser/client.test.mjs
uv lock --check --offline
uvx --offline ruff==0.15.20 check .
uvx --offline ruff==0.15.20 format --check .
```

Install optional browser tooling and run the scenarios against real browser engines.

```sh
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium firefox webkit
for engine in chromium firefox webkit; do
  uv run --locked --group browser python evidence/browser-interface/browser_smoke.py --browser "$engine"
done
uv run --locked --group browser python evidence/browser-reliability/browser_checks.py --peer firefox
bash evidence/final-correctness-audit/verify-package.sh HEAD
```

To run a fixed-deck server on an unused port, start the following in place
of the normal launch. Each probe needs a fresh process.

```sh
uv run --locked uvicorn launch:showdown --factory --app-dir evidence/deepthi-day-2 --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

Play the fixed hand in two browser sessions or run one of these probes
from a second terminal.

```sh
uv run --locked python evidence/submission-readiness/demo_protocol.py
uv run --locked python evidence/deepthi-day-2/smoke.py --scenario showdown
```

See the [known-answer cases](docs/verification.md),
[other live smoke commands](evidence/browser-reliability/notes.md#reproduce),
[technical evidence index](evidence/submission-readiness/evidence-manifest.md),
and [software provenance](evidence/submission-readiness/contribution-inventory.md).

## Security and limits

Use one worker on loopback. Browser admission and sockets use the same
scheme, host, and port. Session tokens and admission keys are bearer
credentials. Keep them private. This deployment assumes a trusted local
host and browser. It has no public hosting or persistent data store.

Restarting the process starts a new match and clears sessions, admission
records, and replay history. Replay inside a running process is bounded.
Turn and grace countdowns are estimates. The server enforces deadlines.
An interrupted hand retains its stacks and outstanding unawarded pot.
