---
id: F007
query_id: Q011
type: read
intent: "check the Obscura compatibility matrix for a video/screencast row"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — The Obscura/Playwright compatibility matrix has no row for video/screencast; real-binary behavior is unverified

## Summary

`docs/obscura-headless-browser.md` §3 "Compatibility matrix" lists every
other Playwright-exclusive feature Obscura mode supports —
`intercept_requests`, `record_har` (explicitly flagged "config-time only"),
`save_pdf`, `start_tracing`/`stop_tracing`, `save_storage_state` — each with
a status (✅ pass / ⚠️ known-existing-gap) and citing the test that verifies
it. There is **no row at all** for video recording. The doc's own status
legend states ✅ rows are "expected to hold" by code-path analogy but that
"the opt-in real-Obscura fixture... is what actually re-verifies each one
against a real binary — run it before enabling Obscura broadly." Separately,
a currently-open ledger issue records real, already-observed Obscura
v0.2.2 CDP incompatibilities (`get_page_source`/`wait_for_load_state`)
that are not Obscura-specific CDP-naming assumptions but genuine renderer
gaps — evidence that "speaks CDP" does not imply every CDP-adjacent
Playwright feature behaves identically on Obscura vs. launched Chromium.

## Citations

- path: `docs/obscura-headless-browser.md`
  lines: 161-170
  symbol: "Compatibility matrix" status legend
  excerpt: |
    ✅ pass — verified against a real, headless-launched Chromium via
    PlaywrightDriver ... the opt-in real-Obscura fixture (below) is what
    actually re-verifies each one against a real binary — run it before
    enabling Obscura broadly.

- path: `docs/obscura-headless-browser.md`
  lines: 191-201
  symbol: "Playwright-exclusive extended surface" table
  excerpt: |
    | `record_har` | ✅ pass (config-time only) | `PlaywrightConfig.record_har_path` |
    | `save_pdf` | ✅ pass (chromium only) | Obscura mode forces `browser_type="chromium"` |
    (no row for video/screencast anywhere in this table)

- path: `docs/obscura-headless-browser.md`
  lines: 229-250
  symbol: "Opt-in real-binary verification"
  excerpt: |
    **Run these before enabling Obscura for any real workload** — every ✅
    above is measured against launched Chromium and a mocked CDP
    transport; these are what actually exercises a real Obscura process
    end to end.

## Notes

This is the strongest basis for treating Obscura-side video capture as a
genuine unknown (U1 in the synthesis), not an implementation detail: no
one has run `record_video_dir` against a real Obscura v0.2.2 binary, the
feature isn't even tracked in the matrix, and a sibling CDP feature
(`get_page_source`) is already known to misbehave on real Obscura in ways
the "speaks CDP" assumption did not predict.
