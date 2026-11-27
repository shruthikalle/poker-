# Test quality, privacy, and resource limits

The application gates gameplay by the current socket and authenticated
seat. Relevant tests assert both response and resulting state.
`test_distinct_keys_and_legacy_join_share_capacity` checks one hand,
one revision, one set of blinds, the original tokens, and two digest
records. The admission/socket race also checks the actual A card
fixture and the unchanged room object after opposing requests. It uses
a barrier; the assertions hold whichever thread enters the lock first.

Existing coordinator checks count engine calls or verify the immutable
room and revision. Retained accepted replay, evicted rejected records,
wrong actor, stale hand, command conflicts, blocked writers, and
terminal mutation were tested without weakening existing assertions.
Tests use fresh rooms, isolated browser contexts, bounded endpoint
startup, and deterministic cards where outcomes depend on them.
Interrupted hands include the unawarded pot in the conservation check.
Scheduler boundary tests use a controlled clock. Browser tests use
observed DOM and packet events in place of estimating exact grace
boundaries with wall-clock sleeps.

Three separate five-test runs each ran competing admissions and 50
writer replacements. Admission stores up to two successful digest
records. The registry owns a current connection per seat and shares it
between lobby and gameplay. Each queue is bounded at 32. The audit
saw a sampled attach queue of 1, at most 3 simultaneously tracked
writers during an attach/replacement, and zero at teardown. Five
legitimate hands exercised removal of accepted commands older than the
previous hand. The sampled retained accepted count peaked at 3 for
that fold/Ready sequence. The rejected cache has a separate per-seat,
per-hand FIFO and is exercised by the older flood tests.

There is one lifespan scheduler per app. Per authenticated persistent
socket, a reader, writer, and close waiter share a cancellable task
group. The ASGI lifecycle test visits waiting, active, paused, and
terminal states, then closes clients and confirms scheduler cancellation
on lifespan exit. The blocked-writer test cancels with queued work and
confirms its reader exits without a send. The other peer remains
independent in the existing blocked-writer and exact timeout tests.
These measurements cover instrumented task ownership and sampled
quantities. They do not establish memory-leak-free operation or all
shutdown orderings in a production deployment.

The browser owns one socket generation, retry/heartbeat schedule,
pending-command deadline, countdown interval and persisted unresolved
command per tab. Visibility and history events reuse the same
connection object. Tests inspect focus during repeat actions, verify
real browser history return, and use the existing controlled
heartbeat/cancellation tests. Browser interval/task memory was outside
the bounded resource measurement.

## Privacy evidence review

The canonical backend distinguishes successful credential responses
using `Cache-Control: no-store`, including keyed replay. Session lookup
success carries the same header. Validation/authentication errors
return fixed public envelopes. Legacy and current routes share capacity.
CSP and static-path checks cover intended files and encoded parent paths.
Origin checks support equal loopback scheme, host and port and allow
originless non-browser clients. Valid bearer possession remains the
seat authentication boundary. The audit did not extend the deployment
model to untrusted hosts.

Targeted source inspection and text scans excluded raw packet dumps.
The scan found zero candidates for literal recovery headers, long
Bearer values, private-key delimiters, or known API-token prefixes
in the tracked documentation and evidence plus the new audit files.
Actual browser probes compare credential values in memory and retained
only sanitized status lines. The role and DOM checks used known cards;
the wire checks captured live personalized frames before and after
settlement. This is bounded coverage of representative engine outcomes,
browser transitions and error paths, with additional exact shape tests.

[Repeated transport measurements](transport-and-resource-results.txt) ·
[Backend tests](../../tests/test_coordinator.py) ·
[Deadline tests](../../tests/test_deadlines.py) ·
[Original browser fixture results](../browser-reliability/browser-compatibility-results.txt)
