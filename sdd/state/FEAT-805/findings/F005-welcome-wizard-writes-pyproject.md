---
id: F005
query_id: Q005
type: grep
intent: "Which code WRITES the [tool.parrot.sdd] table?"
executed_at: 2026-11-04T22:50:00Z
duration_ms: 0
parent_id: F001
depth: 1
---

# F005 — The Claude install welcome wizard writes `[tool.parrot.sdd] sandbox` into `pyproject.toml`

## Summary

`[tool.parrot.sdd]` has a writer as well as readers: the welcome wizard reads the table
only when `pyproject.toml` exists and persists the choice with `_set_pyproject_sandbox`.
Across `packages/*/src`, `tool.parrot.*` is referenced by exactly three modules:
`native_claude_sandbox.py`, `native_artifacts.py` and `welcome.py`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py`
  lines: 148-180
  symbol: `_set_pyproject_sandbox`
  excerpt: |
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
    ...
    def _set_pyproject_sandbox(root: Path, value: str) -> None:
        """Set [tool.parrot.sdd] sandbox = value with minimal text edits; validate with tomllib."""
        path = root / "pyproject.toml"

## Notes

Open ledger issue `issue:1ec3dc062b34` (minor): "welcome._set_pyproject_sandbox duplicates
table when [tool.parrot.sdd] header has a trailing comment". Moving the write target to
JSON removes the text-editing problem for repositories that use `sdd/config.json`.
The branch taken at line 149 when the file is absent was not read.
