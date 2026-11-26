import assert from "node:assert/strict";
import {acceptsSnapshot, remainingMs} from "../../server/static/js/state.mjs";

const active = {revision: 1, lifecycle_revision: 2, hand_id: 1, lifecycle: "active",
  match_result: null};
const paused = {...active, lifecycle_revision: 3, lifecycle: "paused"};
const resumed = {...active, lifecycle_revision: 4};
function show(accepts) {
  let rendered = active;
  for (const frame of [paused, resumed]) {
    if (accepts(rendered, frame)) rendered = frame;
    console.log(`  ${frame.lifecycle}: rendered ${rendered.lifecycle} at lifecycle revision ${rendered.lifecycle_revision}`);
  }
}
console.log("Controlled engine-only filter:");
show((old, frame) => frame.revision > old.revision);
console.log("Production revision pair:");
show(acceptsSnapshot);
assert(acceptsSnapshot(active, paused) && acceptsSnapshot(paused, resumed));
const elapsed = 12341;
const integerCounter = 30000 - 1000;
const anchored = remainingMs(30000, 0, elapsed);
console.log(`One callback at ${elapsed} ms: callback counter ${integerCounter} ms; monotonic anchor ${anchored} ms`);
assert.equal(anchored, 17659);
