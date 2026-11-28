# Day 9: PDF rules

## Seeded engine simulation

Run from the repository root after `uv sync --locked`:

```sh
uv run --locked python evidence/pdf-rules/day9_simulation.py > evidence/pdf-rules/day9-simulation-results.json
```

The tracked [result](day9-simulation-results.json) uses seeds 11, 29, 47, and 83, with 250 hands per seed: 1,000 hands and 7,951 accepted actions. It reports 249 showdowns, 751 folds, and eight completed matches. The generator deals a seeded shuffled deck for every hand, rotates the dealer within each match, starts a fresh match after the blind threshold ends one, and bounds accepted actions. After every transition it checks all 52 cards across holes, burns, board, and deck; 1,000-chip conservation; nonnegative balances; phase/board/burn consistency; raise cap; and settled pot/actor state. An assertion failure includes the seed and recent action sequence.

This is a reproducible sample of legal action paths, not exhaustive proof of poker correctness. The separate hand-calculated showdown cases in `tests/test_pdf_rules.py` provide outcome oracles.

## Server command races

Run:

```sh
uv run --locked python -m unittest discover -s tests -p test_pdf_day9.py -v
```

`tests/test_pdf_day9.py` uses the PDF room and real coordinator. It checks that an exact retry returns the original acknowledgment even after the room advances; conflicting action-ID reuse and stale revisions preserve the authoritative room; and two threads submitting at one revision yield exactly one state mutation for distinct IDs or one mutation with identical replay outcomes for the same ID. Both seats retain a 1,000-chip total and the observer receives one committed revision. These checks exercise in-process command serialization, not cross-process or distributed deployment.
