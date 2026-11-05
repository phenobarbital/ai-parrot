---
id: F010
query_id: Q010
type: read
intent: "Which engine-side quality steps only understand Python files and pyproject.toml?"
executed_at: 2026-11-04T22:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — The sdd-coder lint pass and the green cache only handle `.py` files and `pyproject.toml`

## Summary

The engine-owned lint pass runs `ruff check --fix` plus a formatter detected from
`[tool.black]` / `[tool.ruff.format]` in `pyproject.toml` (or `ruff.toml`), over the
task's changed `.py` files only; anything else resolves to formatter `"none"` and an
empty file list. The green cache refuses any target that is not a `.py` file and
requires the `pyproject.toml` blob in its fingerprint, so it never caches elsewhere.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py`
  lines: 69-90
  symbol: `detect_formatter`
  excerpt: |
    tool = _load_toml(root / "pyproject.toml").get("tool", {})
    if "black" in tool:
        return "black"
    if "format" in tool.get("ruff", {}):
        return "ruff"
    ...
    return "none"

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py`
  lines: 119-121
  symbol: `_existing_python_files`
  excerpt: |
    """The changed paths that are ``.py`` files still present in ``cwd`` (deletions excluded)."""
    return [p for p in changed if p.endswith(".py") and Path(cwd, p).is_file()]

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py`
  lines: 76-103
  symbol: `_manifest`
  excerpt: |
    if not file_path.endswith(".py"):
        return None
    ...
    if not add("pyproject:root", "pyproject.toml"):
        return None

## Notes

`lint.py:1-12` states the design: mechanical formatting belongs to the engine, not to
coder turns. A language profile has to plug in here for a TypeScript repository to get
the same behaviour (prettier / eslint --fix over changed files).
The green cache being pytest-scoped is documented in the shipped prompts
("`n/a` for cache/baseline for non-pytest runners", `_assets/claude/commands/sdd-done.md`,
lane report) — a degradation, not a failure.
