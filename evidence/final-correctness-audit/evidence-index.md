# Final correctness audit

The inspected baseline is `340393392bb84ba0adf74a233fa114c4a541a92f`.
The audit preserves the engine, all earlier evidence, the tested variant,
and the current interrupted-pot behavior.

| Topic | Evidence |
| --- | --- |
| Requirements, discrepancies, and owners | [Matrix](requirements-matrix.md), [discrepancies](specification-discrepancies.md), [joint approval](joint-decisions.md), [contributions and dependencies](contribution-inventory.md) |
| Independent answers and regression output | [Arithmetic/card oracles](correctness-oracles.md), [baseline](baseline.txt), [test results](test-results.txt), [live smoke](regression-smoke-results.txt) |
| Transport, privacy and resource bounds | [Three repeated transport runs](transport-and-resource-results.txt), [quality notes](test-quality-notes.md) |
| Browser evidence | [Cross-engine output](browser-compatibility-results.txt), [history and suspension](browser-lifecycle-results.txt), [accessibility and zoom](accessibility-results.txt), [unexecuted manual checks](manual-verification.md) |
| Installation and demo | [Clean checkout and wheel](clean-checkout-results.txt), [rehearsal](demo-rehearsal-results.txt), [presentation handoff](presentation-handoff.md) |
| Engineering evidence | [Reproduced comparisons](engineering-comparisons.txt), [earlier debugging evidence](../browser-interface/debug-results.txt), [reliability notes](../browser-reliability/notes.md) |

## Reproduction

Run the [README](../../README.md) setup and optional browser install.
The existing ten live fixture launch and test pairs are documented in
[the previous evidence notes](../browser-reliability/notes.md#reproduce).

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -W error -m unittest discover -s tests -v
node --test tests/browser/client.test.mjs
uv lock --check --offline
uvx --offline ruff==0.15.20 check .
uvx --offline ruff==0.15.20 format --check .
git diff --check
uv sync --locked --group browser
uv run --locked --group browser playwright install chromium firefox webkit

for engine in chromium firefox webkit; do
  uv run --locked --group browser python evidence/browser-interface/browser_smoke.py --browser "$engine"
  uv run --locked --group browser python evidence/final-correctness-audit/browser_audit.py --case reliability --engine "$engine"
  uv run --locked --group browser python evidence/final-correctness-audit/browser_audit.py --case history --engine "$engine"
done
for scenario in history-offline pending-history suspension forms input zoom rehearsal; do
  uv run --locked --group browser python evidence/final-correctness-audit/browser_audit.py --case "$scenario"
done
for peer in firefox webkit; do
  uv run --locked --group browser python evidence/final-correctness-audit/browser_audit.py --case mixed --peer "$peer"
done
uv run --locked --group browser python evidence/browser-reliability/recovery_probe.py
uv run --locked python evidence/deepthi-day-3/decision-deadlines.py
node evidence/browser-interface/decisions.mjs
bash evidence/final-correctness-audit/verify-package.sh
```

To run the historical browser comparison, use the isolated archive
commands in the [recovery notes](../browser-reliability/notes.md#reproduce).
The historical comparison and controlled scheduler model measure
different things. The first injects real delivery faults. The second
compares a modeled stale callback with the current room transaction.

The native zoom fixture uses a temporary profile and Chromium's
native extension tab-zoom API. Its host permission is restricted to
loopback and the app has no extension dependency. The Chromium
suspension fixture freezes the renderer through DevTools.
[Native tab zoom API](https://developer.chrome.com/docs/extensions/reference/api/tabs/#method-setZoom) ·
[DevTools lifecycle API](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-setWebLifecycleState)
