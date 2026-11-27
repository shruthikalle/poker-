# Public action history options

[Snapshots](../../server/views.py) expose the current phase, actor,
contributions, board, stacks, pot, Ready flags, write revisions, sanitized
results and the latest automatic action. An ordinary accepted command
provides its action name and actor to the
[coordinator](../../server/coordinator.py), but snapshots can skip
intermediate values and do not encode the entire action sequence.
Contribution increases can describe payment before a street resets.
On round completion or settlement the after-state may reset contributions
and pot. Blindly subtracting snapshots cannot always recover payment.
Ready, automatic action and terminal changes have explicit server paths.

| Option | Usefulness | Limits and risk |
| --- | --- | --- |
| Browser-local | Low-cost record of successful own actions and observed visible changes. | Missed snapshots, refresh, timeout transitions and lost acknowledgments can make two views disagree. Cannot serve as authoritative history. |
| Bounded server history | Append a public event with the same lock and commit point as the accepted transition. Include room or match ID, hand ID, event order, action kind, actor, authorized public amount if known, and outcome type. | Medium application effort. Requires a cap and clear truncation, reconnect recovery, delivery limits and an explicit safe serializer. |
| Engine-owned events | Can represent exact payment and settlement details at the source. | Requires partner-owned engine API and tests. Keep lifecycle terminal and disconnect events in the application. |

Prefer bounded authoritative server events for basic action names,
actor, transition and result. Record events only on a new commit.
Replayed acknowledgments, rejected commands, and duplicate deliveries
produce no new event. Label automatic moves separately. Use an event
sequence to order engine and lifecycle events even when the engine
revision is unchanged. A reconnect may receive only the retained range,
with a visible truncation boundary. Never include credentials, deck,
unrevealed cards, or other raw state.

A completed-hand summary could carry hand number, dealer, public board,
result, and final stacks or net changes. Exact pot awarded and amounts
for transitions that reset contributions require an explicit recorded
pre-settlement value or partner-approved engine transition metadata.
Do not deduce them with browser poker logic. Strip opponent cards from
historical entries by default. Any historical showdown retention requires
an explicit audience and retention policy. Fold and interrupted outcomes
must stay distinct from a paid showdown and must preserve existing privacy.

Test accepted-once versus replay, ordering across automatic actions and
Ready, bounded reconnect delivery, and the absence of private fields in
both network payloads and rendered history. Agree on these contracts
before implementing a new message shape.
