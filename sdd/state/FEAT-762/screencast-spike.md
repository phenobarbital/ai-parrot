# FEAT-762 active-page screencast spike (TASK-4842, M0)

## Result
**PASS for the in-connection recorder** (user decision (a), 2026-10-27). Real Obscura 0.2.2
captured the exact existing page via a Playwright `CDPSession` on the original automation
connection and produced a playable VP8 WebM whose decoded frames show white -> red after start.
The originally specified *separate detached recorder* is **infeasible** (see Observations);
spec §2/§Backend Contract Gate were revised accordingly.

## Reproduction and environment
- `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py::TestObscuraScreencastRecording::test_existing_page_produces_playable_webm -q -rs`
- Tested test commit: `87424df1485c77f3ca47beb8b7fc77d8c7c7a75d`. Obscura 0.2.2, PyAV 13.1.0 (libvpx), Pillow 13.0.0, Python 3.12.
- Result line: `1 passed, 1 warning in 4.81s` (raw log `artifacts/logs/FEAT-762-spike.log`, gitignored).
- Also passed via the engine merge-tier validation (`6 passed, 8 skipped`, then the node `1 passed`).

## Asserted by the test
- A second CDP connection sees `Target.getTargets == []`.
- Frames received (>=2), first frame 1280x720, span >= 500 ms.
- Decoded WebM: first sample white, last sample red, red run monotone to the end, no blue (decoy) sample.
- After stop: page URL unchanged, page and decoy still in `context.pages`, page state `red`, browser connected.

## Manual observations (probes, NOT asserted by the test)
- `Target.attachToTarget` from a second connection -> "Target not found"; `/devtools/page/page-1`
  of a second connection -> "No page" / its own fresh `about:blank`.
- Frames are `obscuraFrameSource: activity-driven` (only on change); JPEG; acked via `Page.screencastFrameAck`.
- Obscura only lets the most recently created page evaluate JS (an earlier page raised
  "Cannot read properties of undefined"), so the decoy is created first; a stronger
  "decoy created last" test is not possible on 0.2.2.

## Backend contract
See spec §6 "Backend Contract Gate" (frozen). `av` is not a declared dependency of the hosting
package: declaring it needs user approval (open question in spec §8).

## Handoff
M0 passed for the in-process design. Before `/sdd-task` decomposes M1–M3 the spec's M1–M3/CLI
text must be revised (`/sdd-spec`) for the in-process recorder. This report does not certify the whole feature.
