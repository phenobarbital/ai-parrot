# FEAT-762 active-page screencast spike (TASK-4842, M0)

## Result
**PARTIAL / BLOCKED on a spec decision.** Capture + WebM encode/decode of the
exact existing page works on real Obscura v0.2.2, but ONLY through a
CDPSession on the *original* automation connection. A *separate* recorder
connection (the spec's detached `parrot e2e screencast` daemon design)
**cannot attach** to the page. AC-3 is met for the in-connection path; AC-1/AC-4
are not met for the separate-recorder design, and the spec contract (AC-6) was
deliberately NOT frozen.

## Reproduction and environment
- Command: `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py::TestObscuraScreencastRecording::test_existing_page_produces_playable_webm -q -rs`
- Obscura 0.2.2 (`~/.local/bin/obscura`), Playwright (venv), PyAV 13.1.0 (libvpx
  VP8 encoder present), Pillow 13.0.0, Python 3.12. Raw log: `artifacts/logs/FEAT-762-spike.log` (1 passed).
- Implementation commit: see the TASK-4842 commit on this branch.

## Observations
- `Page.startScreencast` is supported; frames are `obscuraFrameSource: activity-driven`
  (a frame is emitted only when the page changes, not at a fixed rate) — the encoder
  must place frames by `metadata.timestamp` (test uses a 1/1000 time base).
- Frames: JPEG, 1280x720, ack with `Page.screencastFrameAck` required.
- **Isolation**: each CDP connection gets its own isolate. A second connection sees
  `Target.getTargets == []`, its own fresh `about:blank` `page-1` in `/json/list`,
  `Runtime.evaluate` on `/devtools/page/page-1` answers "No page", and
  `Target.attachToTarget` with the original page's ids answers "Target not found".
- `context.new_cdp_session(page)` works on the original Playwright connection;
  white→red change after start is visible in decoded WebM frames; a decoy blue page
  never appears; page URL, state, context pages and browser stayed intact after stop.

## Backend contract (verified, in-connection variant only)
- Transport: Playwright `BrowserContext.new_cdp_session(page)`; events `Page.screencastFrame`
  (`data` base64 JPEG, `metadata.timestamp`, `sessionId`), calls `Page.startScreencast`
  `{format, quality, everyNthFrame}`, `Page.screencastFrameAck`, `Page.stopScreencast`, then `CDPSession.detach()`.
- Encoder: `av` (libvpx VP8, webm) in a `ProcessPoolExecutor`; decode with `av` for verification.
  Dependency status: `av` is only a root constraint override (`av>=13,<14`), NOT a declared
  dependency of any package that would host M1 — needs user approval.

## Handoff / required decision
The spec's M1 (detached recorder process attaching by CDP endpoint + page target ID)
is infeasible on Obscura 0.2.2. Options: (a) record inside the process that owns the
Playwright connection (needs the exploration agent to run Playwright, not Bash-only
`parrot e2e` CLI commands); (b) get an Obscura capability for cross-connection target
sharing; (c) change the recording approach. M0 is NOT passed for the stated design; do not
decompose M1–M3 until the spec is revised. Task left incomplete; spec untouched.
