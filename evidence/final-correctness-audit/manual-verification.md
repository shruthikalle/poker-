# Manual checks that remain

VoiceOver is installed on the audit host. The tool environment did not
provide an interactive desktop or audible assistive output. No system
accessibility settings were changed. Browser accessibility snapshots
and keyboard checks were executed. The official course instructions
were unavailable for checking any course-specific accessibility claim.

## Screen reader with keyboard

1. Open the landing page and find the title, main landmark, Bet unit,
   and Room code using headings or form navigation.
2. Submit an invalid code. Check that focus returns to the field and its
   error can be read. Correct the field and verify the stale error clears.
3. Launch the two-player fixture. Check the room code, both accessible
   card names, and face-down opponent cards before showdown.
4. Follow the turn, actions, pause and resume announcements. Let the clock
   tick and confirm speech is limited to meaningful changes.
5. Settle a hand, find Ready, advance to a new hand, and verify a terminal
   fixture announces the match result. Check the leave dialog and focus return.

## Physical mobile and native browser zoom

No authorized physical phone was connected. Leave the app on loopback
unless both partners approve a different deployment. On an authorized
device, check create/join, card readability, action targets, rapid
double taps, later deliberate actions, pause, and recovery. Repeat with
portrait and landscape orientation. Hardware emulation is already
recorded in [the prior usability results](../browser-reliability/usability-results.txt).

Native tab zoom was executed on Chromium at 100%, 150%, and 200%.
For Firefox and Safari, repeat at 200% using browser menu controls.
Verify that forms, legal actions, focus, cards, timers, and error
messages stay reachable without horizontal scrolling. Test with your
screen reader and platform settings if they are part of the demo.

## Longer runtime and additional cache configurations

Chromium cache restore and Firefox/WebKit history reload were exercised.
A physical OS sleep/wake cycle and longer observation of task, socket,
and memory usage remain optional quality checks. Use a fresh room,
record the browser versions and whether `pageshow.persisted` was true,
and include observed counts and elapsed workload.
