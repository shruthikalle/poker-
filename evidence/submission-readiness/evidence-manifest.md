# Final submission evidence manifest

| Claim | Tracked generator or source | Tracked evidence |
| --- | --- | --- |
| Proposal, course and joint-policy traceability | [Requirements](requirements-finalization.md) and [implemented wording](joint-approval-status.md) | [Prior matrix](../final-correctness-audit/requirements-matrix.md), [discrepancies](../final-correctness-audit/specification-discrepancies.md) |
| Both partners' work and exact reused libraries | [Engine](../../poker/engine.py), [coordinator](../../server/coordinator.py), [package metadata](../../pyproject.toml), [lock](../../uv.lock) | [Integration inventory](integration-inventory.md), [contributions](contribution-inventory.md) |
| Engine known answers and one-payout accounting | [Fixtures](../../server/fixtures.py), [engine tests](../../tests/test_engine.py), [gameplay tests](../../tests/test_gameplay.py), [wire tests](../../tests/test_websocket_gameplay.py) | [Independent arithmetic](../final-correctness-audit/correctness-oracles.md), [engine output](engine-verification-results.txt) |
| Live HTTP, WebSocket, and browser checks | [Original browser runner](../browser-interface/browser_smoke.py), [audit runner](../final-correctness-audit/browser_audit.py), [usability runner](../browser-reliability/browser_checks.py), [live commands](../browser-reliability/notes.md#reproduce) | [Combined results](final-regression-results.txt), [browser results](browser-verification-results.txt) |
| Lost admission historical comparison and lost-ack diagnosis | [Fault probe](../browser-reliability/recovery_probe.py), [room manager](../../poker/rooms.py), [client watchdog](../../server/static/js/network.mjs), [Node assertions](../../tests/browser/client.test.mjs) | [Historical and improved results](historical-comparison-results.txt), [previous fault evidence](../browser-reliability/recovery-before.txt) |
| Exact dispatch deadlines and decision backups | [Deadline model](../deepthi-day-3/decision-deadlines.py), [deadline tests](../../tests/test_deadlines.py), [privacy probe](../deepthi-day-2/decision-privacy.py), [coordination probe](../deepthi-day-2/decision-coordination.py) | [Measured alternatives](historical-comparison-results.txt) |
| Fresh checkout and installed wheel | [Package verifier](../final-correctness-audit/verify-package.sh) | [Finalization packaging record](clean-checkout-results.txt). The exact final revision is verified separately after the handoff is committed. |
| Live rehearsal, screenshot, wrong-turn and reconnect probes | [Demo runbook](demo-runbook.md), [protocol probe](demo_protocol.py), [fixture launch](../deepthi-day-2/launch.py) | [Observed rehearsal](demo-rehearsal-results.txt), [actual Chromium capture](../browser-interface/screenshots/active.png) |
| Presentation and logistics | [Six-slide content](presentation-content.md), [technical questions](technical-questions.md) | [Remaining actions](submission-checklist.md) |

## Historical reproduction and interpretation

The proposal starts from no previous codebase. Git's README-only
commit is distinct from the first engine `34aa241`. The first
engine has no `poker/server.py`, so the UI probe begins at the
comparable working browser `b051973`. Commit `e4eec2b` implements
keyed replay. The improved check was repeated on `a6903fb` before
this documentation and probe handoff. Production code, existing
regression tests, and dependencies stayed unchanged during finalization.

```sh
git cat-file -e 34aa241:poker/server.py
historical="$(mktemp -d)"
git archive b051973843c36a593ca40516f6f43a51a332b60d | tar -x -C "$historical"
mkdir -p "$historical/evidence/browser-reliability"
cp evidence/browser-reliability/recovery_probe.py "$historical/evidence/browser-reliability/"
(cd "$historical" && uv run --locked --group browser python evidence/browser-reliability/recovery_probe.py --baseline)
uv run --locked --group browser python evidence/browser-reliability/recovery_probe.py
uv run --locked python evidence/deepthi-day-3/decision-deadlines.py
```

The first command exits nonzero because the initial engine lacks
the entry point. The same browser probe delivers the successful
admission upstream, suppresses its response and observes the retry.
Its historical mode uses the former submission button and expects
409. Current mode uses the recovery button after refresh and verifies
the original response and one set of blinds. The watchdog comparison
uses the same acknowledgment drop and periodic snapshots. The deadline,
privacy and split-check alternatives are controlled models. Their
results do not describe historical releases.

Use the exact final SHA and tree from the publication verification
report. Confirm relative evidence paths on that tree before exporting
the deck. Course PDFs and private values remain outside Git.
