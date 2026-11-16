---
id: F003
query_id: Q021, Q033, Q039
type: grep
intent: "Is everything the old M1 wanted to create (satellite skeleton, workspace source, release entry, CI, nightly, extras) already on dev; dependency declarations of pyarrow/duckdb/sqlglot."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_ids: [FC-006]
---

# F003 — Old M1 is fully delivered by FEAT-704: satellite, workspace source, release entry, CI step, nightly matrix and the `duckdb` extra all exist — and a packaging test pins them

## Summary

`packages/ai-parrot-semantic/pyproject.toml` declares `dependencies = ["ai-parrot", "sqlglot>=30.1,<31",
"jsonschema>=4.20", "pyyaml>=6"]` and extras `duckdb = ["duckdb>=1.0"]`, `bigquery`. The root workspace
source, the `scripts/release.py` `Package("ai-parrot-semantic", …)` entry, a CI step ("Semantic-layer
tests": `uv sync --all-packages --extra duckdb` + `pytest packages/ai-parrot-semantic/tests`) and the
nightly matrix entry (with `--extra duckdb`) are present. There is **no** job named `test-semantic`; the
semantic tests are a step of an existing job. `tests/test_packaging.py` asserts the exact dependency list,
the exact extras dict, the workspace source, the release entry and the CI lines, and that the removed
AGPL module is absent and banned in `ruff.toml`. `pyarrow>=25.0` is a core dependency (also declared by
`ai-parrot-server` and `ai-parrot-squawk`); core pins only `sqlglot>=20.0`; `duckdb` is declared nowhere
but the semantic extra.

## Citations

- path: `packages/ai-parrot-semantic/pyproject.toml`
  lines: 12-16
  symbol: `dependencies`
  excerpt: |
    dependencies = ["ai-parrot", "sqlglot>=30.1,<31", "jsonschema>=4.20", "pyyaml>=6"]
    [project.optional-dependencies]
    duckdb = ["duckdb>=1.0"]
    bigquery = ["google-cloud-bigquery>=3.30"]

- path: `pyproject.toml`
  lines: 248-248
  symbol: `tool.uv.sources`
  excerpt: |
    ai-parrot-semantic = { workspace = true }

- path: `scripts/release.py`
  lines: 234-236
  symbol: `PACKAGES`
  excerpt: |
    "ai-parrot-semantic",
    [("packages/ai-parrot-semantic/src/parrot/semantic/version.py", "python")],
    "packages/ai-parrot-semantic",

- path: `.github/workflows/ci.yml`
  lines: 668-671
  symbol: `Semantic-layer tests`
  excerpt: |
    - name: Semantic-layer tests
      run: |
        uv sync --all-packages --extra duckdb
        uv run pytest packages/ai-parrot-semantic/tests -q --tb=short

- path: `.github/workflows/nightly-tests.yml`
  lines: 45-45
  symbol: `matrix`
  excerpt: |
    - ai-parrot-semantic

- path: `.github/workflows/nightly-tests.yml`
  lines: 85-85
  symbol: `EXTRAS`
  excerpt: |
    ai-parrot-semantic) EXTRAS+=(--extra duckdb) ;;

- path: `.github/workflows/release.yml`
  lines: 412-412
  symbol: `publish step`
  excerpt: |
    cd packages/ai-parrot-semantic

- path: `packages/ai-parrot-semantic/tests/test_packaging.py`
  lines: 22-43
  symbol: `test_namespace_version_and_package_data`
  excerpt: |
    assert package_config["project"]["dependencies"] == [
        "ai-parrot", "sqlglot>=30.1,<31", "jsonschema>=4.20", "pyyaml>=6"]
    assert package_config["project"]["optional-dependencies"] == {
        "duckdb": ["duckdb>=1.0"], "bigquery": ["google-cloud-bigquery>=3.30"]}

- path: `packages/ai-parrot-semantic/tests/test_packaging.py`
  lines: 46-56
  symbol: `test_no_removed_dependency_or_import_exemption`
  excerpt: |
    removed_module = "side" + "mantic"
    assert removed_module not in str(package_config)
    assert f'"{removed_module}".msg' in ruff_config

- path: `packages/ai-parrot-semantic/tests/test_packaging.py`
  lines: 59-73
  symbol: `test_workspace_ci_duckdb_extra`
  excerpt: |
    assert root_config["tool"]["uv"]["sources"]["ai-parrot-semantic"] == {"workspace": True}
    assert 'Package(\n        "ai-parrot-semantic",' in release_script
    assert "uv sync --all-packages --extra duckdb\n" in ci_workflow
    assert "uv run pytest packages/ai-parrot-semantic/tests -q --tb=short" in ci_workflow

- path: `packages/ai-parrot/pyproject.toml`
  lines: 190-192
  symbol: `dependencies`
  excerpt: |
    "pyarrow>=25.0",
    "sqlglot>=20.0",

- path: `packages/ai-parrot-server/pyproject.toml`
  lines: 39-39
  symbol: `dependencies`
  excerpt: |
    "pyarrow>=25.0",

- path: `packages/ai-parrot-squawk/pyproject.toml`
  lines: 17-17
  symbol: `dependencies`
  excerpt: |
    "pyarrow>=25.0",

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 118-118
  symbol: `optional-dependencies.powerbi`
  excerpt: |
    powerbi = ["pyarrow>=25.0"]

## Notes

- Consequences for the old spec: M1 has nothing to create; AC1's "installs as a PEP 420 satellite" and
  AC16's "CI runs the satellite tests + nightly matrix" are already true; AC2 ("identical to
  `origin/feat-FEAT-704-semantic-layer`") is meaningless now; AC17 (pyarrow stays core, duckdb only an
  extra of the satellite) is the current state. Any new dependency or extra added by the revision
  **must update `test_packaging.py`**, which compares the dependency list and the extras dict by equality.
- `jsonschema` is a hard dependency of the satellite (Ossie loader); the old skeleton dropped it.
- A new `accounting` sub-package is picked up automatically by `[tool.setuptools.packages.find]`
  (`include = ["parrot*"]`, `namespaces = true`); golden `.sql` test files live under `tests/`, not package data.
- polars is not declared anywhere (not searched explicitly; no `polars` line appeared among the
  pyarrow/duckdb/sqlglot hits).
