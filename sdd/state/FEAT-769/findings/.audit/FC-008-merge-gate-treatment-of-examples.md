# FC-008 — Examples get a ruff per-file-ignore but no CI job; the real gate is "new/changed files add no ruff findings" plus the semantic-layer pytest job

**Query**: Q015 · **Type**: grep+read · **Depth**: 0

## Summary
Ruff is configured in `ruff.toml` (a `[tool.ruff]` table in `pyproject.toml` would be ignored —
stated at `pyproject.toml:285`). `examples/**/*.py` has a per-file-ignore of `F401, F841, E402`
only — **`E4/E7/E9`, the rest of `F`, and all of `TID251`, `B`, `ASYNC`, `PIE`, `C4`, `LOG` still
apply**, at `line-length = 120`, `target-version = py311`. So a new example may not import
`requests`/`httpx`/`fastapi`/`langchain*`/`sidemantic` (TID251), may not make blocking calls inside
`async def` (ASYNC), and `logger.exception` outside an `except` is a LOG finding. `black` is
configured separately in `pyproject.toml` at line-length 120.

No GitHub workflow mentions `examples` at all. The only CI step that can fail because of these files
is `ci.yml` "Semantic-layer tests": `uv sync --all-packages --extra duckdb` then
`uv run pytest packages/ai-parrot-semantic/tests -q --tb=short` — run from the repo root with **no**
`--continue-on-collection-errors`, so a broken `_EXAMPLE_PATH` or an import error in the example is a
hard CI failure.

Collection hazard: root `pytest.ini` sets `--import-mode=importlib` + `consider_namespace_packages = true`
with no `testpaths`/`norecursedirs`, and the root `conftest.py` has no `collect_ignore`. `examples/agents/`
already contains five files named `test_*.py` with pytest-compiled `__pycache__`, proving the tree
gets collected when someone runs a bare `pytest`. **Do not name any new example file `test_*.py`.**

## Citations
- `ruff.toml:152` — `"examples/**/*.py" = ["F401", "F841", "E402"]` — "Examples are illustrative snippets, not shipped code"
- `ruff.toml:113` — `select = ["E4", "E7", "E9", "F", "TID251", "B", "ASYNC", "PIE", "C4", "LOG"]`; `ruff.toml:114-121` — `ignore = ["ASYNC109", "C408"]`
- `ruff.toml:68, 71` — `line-length = 120`, `target-version = "py311"`
- `ruff.toml:125-136` — `[lint.flake8-tidy-imports.banned-api]` incl. `"sidemantic"` ("do not import sidemantic anywhere")
- `ruff.toml:23-30` — the stated gate: "new and modified files must be clean; the backlog must not grow"
- `ruff.toml:94-105` — `extend-exclude = ["artifacts", "*.ipynb", ".claude/worktrees"]` — `examples/` is NOT excluded
- `pyproject.toml:258, 285` — `[tool.black] line-length = 120`; "Ruff is configured in ruff.toml — a `[tool.ruff]` table here would be ignored"
- `pyproject.toml:254` — note that a `[tool.pytest.ini_options]` table in the root `pyproject.toml` is silently ignored (FEAT-720)
- `.github/workflows/ci.yml:534-537` — `- name: Semantic-layer tests` / `uv sync --all-packages --extra duckdb` / `uv run pytest packages/ai-parrot-semantic/tests -q --tb=short`
- `pytest.ini:1-19` — `asyncio_mode = auto`, `addopts = --import-mode=importlib`, `consider_namespace_packages = true`; no `testpaths`, no `norecursedirs`
- `packages/ai-parrot-semantic/pyproject.toml:14-16` — `[project.optional-dependencies] duckdb = ["duckdb>=1.0"]`, `bigquery = ["google-cloud-bigquery>=3.30"]`; `packages/ai-parrot-semantic/pyproject.toml:21-27` — `packages.find where=["src"] include=["parrot*"]` + `package-data` for `schemas/*.json` and `sql/*.sql` — **the examples tree is not packaged**
- `examples/agents/test_map.py`, `examples/agents/test_mcp.py`, `examples/agents/test_mcp_client.py`, `examples/agents/test_mcp_server.py`, `examples/agents/test_stdio.py` + `examples/agents/__pycache__/*.cpython-312-pytest-9.1.1.pyc` — evidence the tree is pytest-collected

## Notes
- `asyncio_mode = auto` means a new pinning test needs no `@pytest.mark.asyncio`, though the existing
  `test_example_agent.py` uses it explicitly.
- A second example depending on anything beyond `duckdb` would need a matching `uv sync --extra` in
  `ci.yml:536`, or must `pytest.importorskip` it. Prefer DuckDB — it is already in the CI step.
