# Heads-Up Live Poker

A local two-player Texas Hold'em game using virtual chips. The server owns the deck, rules, clocks, and game state. Each authenticated browser receives only its own private view.

## PDF rules

The supplied comprehensive project PDF is the project's rules source. The normal application uses the [PDF rule contract](docs/rules.md): 500 chips per player, 5/10 blinds, fixed 10-chip opening bets and raises preflop and on the flop, 20-chip increments on the turn and river, and at most three raises after an opener. It burns one card before each board street. No all-ins or side pots are supported. At showdown an odd split chip goes to the nondealer. The engine rejects a wager if the opponent cannot cover it while retaining a chip.

The previous 200-chip configurable variant remains in the engine as `legacy` for historical fixtures and regression tests. It is documented in [legacy rule history](docs/rules-reconciliation.md); it is not the normal application rule set. Existing evidence files describing 195/190 opening stacks document that historical variant.

## Run the application

Use Python 3.13 and [uv](https://docs.astral.sh/uv/) from a clean checkout:

```sh
uv sync --locked --no-dev
uv run --locked --no-dev uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
```

Open http://127.0.0.1:8000/ in two independent browser contexts. The table settings are fixed. Create a room, share its code, and join from the second context. The browser displays server-provided legal actions, current board, pot, stacks, timers, and result. Both players choose **Ready** after a settled hand. Refreshing the same tab can restore its seat during the reconnect grace period.

## Architecture

- [Engine](poker/engine.py): immutable state, legal actions, betting, burns, showdown, and payout. `ruleset="pdf"` selects the project rules; `ruleset="legacy"` retains older fixtures.
- [Room manager](poker/rooms.py): admission, private bearer tokens, room revisions, and first-hand initialization. The normal app creates a PDF-rule room.
- [Transport](poker/server.py), [coordinator](server/coordinator.py), and [views](server/views.py): authenticated WebSocket commands, deadline reconciliation, personalized snapshots, and replay protection. The [protocol](docs/protocol.md) describes message formats.
- [Browser](server/static/): two-seat interface with fixed PDF settings in the normal app and server-authoritative action labels.

The first repository commit is `c29badee2f21e6542c67a176304460b14cea13b6`; the first engine commit is `34aa241`. Srishruthik originally directed the engine and initial lobby work. Deepthi implemented the gameplay coordinator, transport, timing, browser, and extensive verification. The repository history records actual contributions; the PDF's proposed ownership split does not retroactively reassign completed code. Both partners own final integration and explanation.

## Verify

```sh
uv sync --locked
uv run --locked python -W error -m unittest discover -s tests -q
node --test tests/browser/client.test.mjs
uvx --offline ruff==0.15.20 check .
uvx --offline ruff==0.15.20 format --check .
```

For the deterministic PDF-rule browser hand, install Playwright Chromium and run:

```sh
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium
uv run --locked --group browser python evidence/pdf-rules/browser_smoke.py
```

That fixture independently checks two browser seats, private cards, board progression, 1,000-chip conservation, a 540/460 paid showdown, and the rotated next hand. [PDF-rule tests](tests/test_pdf_rules.py) also check fixed stacks, three raises, 10/20 increments, burn cards, opponent coverage, and the next-blind boundary. Earlier [known-answer cases](docs/verification.md) and [evidence](evidence/submission-readiness/evidence-manifest.md) are retained as historical checks for the legacy variant.

## Limits

The app runs one in-memory room per process on trusted loopback. Restarting the process loses the room and sessions. A disconnected hand retains its unawarded pot if the match ends during the interruption; this transport policy is separate from poker-hand settlement. No real money, all-ins, side pots, spectators, or persistent account service are supported.
