---
id: F025
query_id: Q023
type: grep
intent: Verify gitignore rules affecting examples/a2ui/{server,client}.py and static HTML
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F025 — examples/a2ui/*.py and *.html are gitignored; examples/agents/a2ui/**/*.py is whitelisted
## Summary
`git check-ignore -v` confirms `examples/a2ui/server.py` and `client.py` match `.gitignore:20 examples/**/*.py` and `examples/a2ui/static/index.html` matches `.gitignore:37 examples/**/*.html`. The file whitelists `!examples/agents/a2ui/**/*.py` (FEAT-470 walkthrough "is documentation") but there is no `.html`/`.js` exception anywhere; `*.js` and `*.css` are not ignored. Tracked static HTML exists anyway (examples/dev_loop/static/*.html, examples/clients/voice/static/index.html) because it was force-added.
## Citations
- path: `.gitignore`
  lines: 20-37
  symbol: `-`
  excerpt: |
    examples/**/*.py
    !examples/autonomous_analyst/**/*.py
    # The A2UI dashboard walkthrough is documentation as well — it runs offline on
    # seeded data and doubles as a smoke test for the v1.0 wire (FEAT-470).
    !examples/agents/a2ui/**/*.py
    examples/**/*.csv
    ...
    examples/**/*.html
## Implications
- Either add `!examples/a2ui/**/*.py` and `!examples/a2ui/**/*.html` to .gitignore (preferred — matches the documented FEAT-470/FEAT-438 precedent so new files never need `git add -f`), or relocate to `examples/agents/a2ui/<subdir>/` (py already whitelisted; html still ignored), or `git add -f`.
- The spec's task list must include the .gitignore edit explicitly, otherwise the deliverable silently isn't committed.
