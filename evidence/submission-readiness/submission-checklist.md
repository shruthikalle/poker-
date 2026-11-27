# Submission checklist

| Owner | Item | Status and remaining action |
| --- | --- | --- |
| Deepthi | Application and packaging | Verified. No submission-blocking runtime defect found in the completed checks. See the [evidence manifest](evidence-manifest.md). |
| Srishruthik | Partner engine work | Available engine and lobby work is integrated. 22 direct engine tests passed. No tracked seeded simulation was found. This stretch check is outside the proposal text and official guide. [Inventory](integration-inventory.md) |
| Both | Final poker rules and interrupted pot | Pending explicit joint approval. Review the exact proposed wording. Existing behavior stays in place. [Rules for review](joint-approval-status.md) |
| Both | Source documents and attribution | Proposal text and both official course PDFs reviewed. Original proposal PDF file was unavailable. Verify personal identifiers from team records before adding them to the final deck. |
| Repository owner | Access and starting tag | The repository is public and defaults to main. Confirm partner collaborator access separately. The guide asks for a starting tag. Confirm its name and publish it with explicit authorization, using the recorded starting checkpoint. |
| Both | Presentation | Six topics and speaker notes prepared. Review the official template and both partners' attribution. Insert confirmed EIDs, the [repository URL](https://github.com/shruthikalle/poker-), and the verified submission commit. Export and review the PDF separately. |
| Both | Live demo | Automated rehearsal passed. Book or confirm the Canvas-linked demo slot, rehearse the 20-minute runbook together, and confirm both names on the booking. |
| Submitting partner | Canvas | Deadline, edit close, registration status, slot, submitting partner and actual form remain unverified. Confirm in Canvas. Submit the URL and reviewed slide PDF as required, then verify the uploaded PDF and the default branch commit once more. |

The official guide calls for a live demonstration and a short slide
PDF as the writeup. It states there is no late window and points to
Canvas for the demo sign-up and available-until date. Course logistics
still need confirmation. [Course guide](https://www.cs.utexas.edu/~witchel/378AC/lectures/948_final_project_guide-slides.pdf) ·
[Proposal and course traceability](requirements-finalization.md)

## Verification and scope limits

- One in-memory room per process and one worker. Restart invalidates
  sessions and prior actions. New matches use the supported local
  restart workflow.
- Replay retention is bounded. Local HTTP and bearer credentials
  assume a trusted host, browser and loopback deployment. Internet
  multiplayer deployment was outside the delivered scope.
- The verified variant excludes all-ins, side pots, burns and custom
  wagers. The target draft remains pending.
- Automated headless checks cover Chromium, Firefox and WebKit.
  Actual screen-reader speech, physical phones, native Firefox/Safari
  zoom and OS sleep/wake remain unverified. The current environment
  lacks interactive audio and an authorized physical device. The
  Chromium renderer freeze and touch emulation are recorded separately.
  [Manual checks](../final-correctness-audit/manual-verification.md)
