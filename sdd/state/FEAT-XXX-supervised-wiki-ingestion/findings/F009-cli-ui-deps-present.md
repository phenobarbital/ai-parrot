# F009 — HITL TUI needs no new dependencies

- `packages/ai-parrot/pyproject.toml` — `click>=8.1.7` (:81), `rich>=13.0`
  (:77), `questionary>=2.1.1` (:98) already declared.
- `cli.py:211` `_render_results_table` shows the existing table-rendering
  style in this CLI.
- Implication: interactive review (per-doc prompt) and rich manifest tables
  are feasible with the current dependency set.

Method: grep of pyproject + cli.py.
