# Player journey and application findings

[Browser probe](player_journey.py) uses separate browser contexts and
a fixed deck to inspect real views and WebSocket messages. Its before mode
records observations against the unchanged renderer. After mode asserts
the corrected behavior against all three Playwright browser engines.
This is browser automation with actual rendering and input.

The [observed comparison](browser-comparison.txt) records the working
baseline and the corrected outputs. Run the corrected probe with
`uv run --locked --group browser python evidence/application-quality/player_journey.py --browser chromium`.
For the baseline, export `c9f7a1b` into a temporary working directory
with `git archive`, copy the same probe into its relative path, and run
with `--observe-before` from that directory.

| Priority | Observation and reproduction | Resolution |
| --- | --- | --- |
| P1 | After offline transition in the waiting room, the connection badge said Offline while the lobby still said Waiting for opponent. An active cached view also still marked a seat Acting even though actions and the countdown were hidden. | Use the current connection to gate live waiting and actor indicators. Preserve the last known board and stacks for context. |
| P1 | Keyboard activation of Reconnect on a replaced session hid the focused control and dropped focus to the body. | Focus the table heading when the focused control starts reconnect. |
| P2 | After leaving a finished hand and starting a new process, the same tab reused the previous hand's title in the fresh waiting room. | Use the private table title whenever the current view has no hand. |
| P2 | An automatic reconnect could restore actions while the old unreachable-server notice remained visible. | Keep connectivity notices tied to the connection state so recovery clears them without clearing game feedback. |
| Limitation | A terminal room stays allocated until process restart. | [Match lifecycle assessment](rematch-feasibility.md). |
| Optional | A reconnecting player cannot retrieve an authoritative action transcript. Snapshots contain current state only. | [Action history assessment](action-history-feasibility.md). |

The walkthrough checks bet-unit preview, keyboard admission and copying,
independent joining, live actor visibility and focus, exact call and raise
costs, board progression, fold, showdown, Ready and dealer rotation,
pause, reconnect, and terminal forfeit. It checks 1440×900, 1280×720,
1024×768, 768×1024, 390×844, and 320×568 for overflow and visible
critical elements. The original suites cover timeout, tie, replay,
expiry, admission recovery and history behavior. Browser tests exercise
private views before payoff and clearing of prior cards after Ready.
Existing tests remain the authority for protocol shapes and race bounds.

[Renderer](../../server/static/js/render.mjs) formats public values and
authorized cards. [State helpers](../../server/static/js/state.mjs) handle
engine and lifecycle revision ordering, exact pending requests, and
terminal acceptance. [Transport](../../server/static/js/network.mjs) owns
socket generations, reconnect scheduling and heartbeat. The app controller
ties them together. The findings require no new timers, dependencies,
engine decisions, or wire fields.

The highest user-value next feature is fresh-room rollover after both
partners agree to its authority and recovery rules. Its implementation
effort and correctness risk are moderate, with lower privacy risk than
retaining history. Bounded public history is useful but should follow a
stable match identity and an explicit public data contract. Existing
restart remains the supported workflow. Physical devices, real
screen-reader output, and long-running resource profiling remain outside
these checks.

Actual Chromium captures use synthetic room codes and fixed decks.
[Landing](screenshots/landing.png) · [Waiting](screenshots/waiting.png) ·
[Preflop](screenshots/preflop.png) · [Flop](screenshots/flop.png) ·
[Showdown](screenshots/showdown.png) · [Fold](screenshots/fold.png) ·
[Paused](screenshots/paused.png) · [Terminal](screenshots/terminal.png) ·
[320 px mobile](screenshots/mobile.png)
