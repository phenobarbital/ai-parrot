# F001 — /sdd-done PR body has no test data
- .claude/commands/sdd-done.md:145-147 — "Test validation is intentionally skipped here — each task already ran its acceptance-criteria tests".
- .claude/commands/sdd-done.md:516-530 — PR body = Summary + "<N>/<total> tasks verified" only.
- .claude/commands/sdd-done.md:173 — select_tests --tier feature --run is used only conditionally (non-neutral lint fix).
- Codex twin .agents/skills/sdd-done/SKILL.md:182-183 — same gh pr create, also no tests.
