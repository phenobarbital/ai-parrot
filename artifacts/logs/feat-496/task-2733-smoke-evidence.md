# TASK-2733 — index.html smoke verification (2026-09-02)

Same procedure as TASK-2732's `task-2732-smoke-evidence.md`, applied to
`examples/dev_loop/static/index.html`.

1. **Syntax check**: extracted the `<script type="module">` block (73488
   chars) and ran `node --check` — passes with no syntax errors.

2. **Runtime smoke test**: extracted `briefOf`, `foldSeat`, `node`,
   `ownEvents`, `nodeSeatsHtml`, `shortSeat`, `esc` and ran the identical 8
   assertions used for `dev.html` — all passed
   (`ALL SMOKE TESTS PASSED (index.html)`).

3. **No-divergence check**: extracted the three NEW shared functions
   (`foldSeat`, `ownEvents`, `nodeSeatsHtml`) from both files via the same
   brace-matching extractor and diffed them — all three are **byte-for-byte
   identical** between `dev.html` and `index.html`. `briefOf`'s new
   `if (p.summary) ...` branch is also textually identical in both files
   (verified by inspection — both files' `briefOf` differ only in the
   pre-existing, unrelated branch ordering already present before this
   feature).

**Not verified**: actual browser rendering in either the `bug` or `feature`
topology, or a side-by-side visual diff against `dev.html` on the same
replayed run — both require a running dev-loop server. Deferred to whoever
next drives an actual run against this build.
