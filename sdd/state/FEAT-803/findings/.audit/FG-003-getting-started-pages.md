# FG-003: Getting started pages history

## Query
`git log --oneline --since="2026-01-01" -- docs/INSTALL.md docs/config.md docs/tools_quick.md`
`git log --oneline --all -- docs/getting-started.md`

## Result
4 commits to the Getting Started trio since Jan 2026:
- `d9c4a858c3` — FEAT-798 Google migration docs (TASK-5150)
- `3850087e56` — FEAT-633 installer + CLI noun-grouped docs
- `a850754fd5` — TASK-3458 CREW_AI_KEY docs
- `7e393385bc` — 74 orphaned pages nav bulk add

`docs/getting-started.md` EXISTS on disk and has git history across branches (10+ commits, dating back to the installer rewrite). INSTALL.md references it: `[getting-started.md](getting-started.md)`.

## Citations
- docs/INSTALL.md — installation guide, references getting-started.md
- docs/getting-started.md — exists on disk, referenced by INSTALL.md but NOT in mkdocs.yml nav
- docs/config.md — configuration reference
- docs/tools_quick.md — quick start for tools

## Notes
`getting-started.md` exists but is NOT listed in the mkdocs.yml nav — it's only reachable via a link inside INSTALL.md. This is a content gap the redesign should fix: a proper Getting Started flow is critical for the informative landing site.
