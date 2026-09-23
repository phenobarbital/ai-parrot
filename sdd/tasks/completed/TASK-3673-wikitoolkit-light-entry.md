# TASK-3673: Dedicated light `wikitoolkit` console entry and startup benchmark

**Feature**: FEAT-595 — Lightweight wikitoolkit hook entry point
**Spec**: `sdd/specs/fixgroup-c3a787516a75.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3672
**Assigned-to**: unassigned
**discovered_from**: issue:f0a40d0853f2

---

## Context

Even with TASK-3672's light hook runtime, the `wikitoolkit` console script imports
`parrot.knowledge.wiki.cli` (~240 ms, the whole click CLI) before dispatching `claude-hook`.
This task implements spec Modules 4–5 and rewrites `test_hook_startup.py` so the benchmark
measures the real console entry. The installed hook command spelling (`<venv>/bin/wikitoolkit
claude-hook`) is unchanged, so none of its three writers are touched (spec G4).

## Scope

- Create `parrot/knowledge/wiki/entry.py` — stdlib-only `main()` dispatcher.
- Point `[project.scripts] wikitoolkit` at `parrot.knowledge.wiki.entry:main`.
- Update `test_hook_startup.py`: launch via `entry`; add import-trace checks for AC1–AC3; hard
  p50 < 300 ms on the prefilter path (AC4); config path p50/p95 recorded + warn-only.

**NOT in scope**: `hook.py`, `claude_code/__init__.py`, `file_suffixes.py` (TASK-3672);
the three installers; removing the `claude-hook` click subcommand (it stays for
`python -m parrot.knowledge.wiki.cli claude-hook`); reinstalling the shared venv (operator step).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/entry.py` | CREATE | Light console-script dispatcher |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Retarget the `wikitoolkit` script |
| `packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py` | MODIFY | Measure the real entry; AC1–AC4 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.cli import main            # verified: cli.py `def main() -> None:` (calls wiki())
from parrot.knowledge.wiki.cli import wiki            # verified: cli.py:1371 area (click group)
from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook  # verified: hook.py:222
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py (~L5157-5175)
@wiki.command(name="claude-hook", hidden=True)
def claude_hook() -> None: ...        # imports hook lazily, sys.exit(run_pre_tool_use_hook())
def main() -> None:
    """Console-script entry point for ``wikitoolkit``."""
    wiki()

# packages/ai-parrot/pyproject.toml:204
wikitoolkit = "parrot.knowledge.wiki.cli:main"

# packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py — helpers to reuse
_SRC_ROOTS, _subprocess_env(), _run_hook(payload, *, importtime=False),
_parse_importtime_modules(stderr), _percentile(sorted_values, pct), _build_project(root),
_BANNED_IMPORT_PREFIXES, _TARGET_P50_MS = 300.0, _REGRESSION_CEILING_MS, _WARM_RUNS = 20
# Existing tests: test_hook_process_protocol_and_imports, test_adr_help_options_and_completion,
# test_warm_process_startup (warns on miss; asserts only the 2500 ms ceiling)
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.entry`~~ — created by this task.
- ~~a `wikitoolkit-hook` console script~~ — deliberately NOT added (spec G4 keeps the spelling).
- ~~`python -m parrot.knowledge.wiki.claude_code.hook`~~ — `hook.py` has no `__main__` block; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/entry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#main",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#claude_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py#run_pre_tool_use_hook"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)

1. Create `entry.py` with stdlib-only module imports — because AC1 forbids `click`/`pydantic` at import.
2. Edit the one pyproject line — because the console shim is generated from it. Do NOT run
   `uv sync`/`uv pip install` (shared venv, see worktree rule) — tests call `entry` via `python -c`.
3. Switch `_run_hook` to launch the entry and extend the tests.
4. Run the Validation Commands; record the benchmark numbers in the Completion Note.

### `packages/ai-parrot/src/parrot/knowledge/wiki/entry.py` (CREATE)
```python
"""Light console-script entry point for ``wikitoolkit`` (FEAT-595).

``wikitoolkit claude-hook`` runs before every matching Claude Code tool
call, so it must not import the click CLI (~240 ms). This dispatcher
imports only :mod:`sys` at module level: the hook subcommand goes straight
to the hook runtime, and every other invocation is handed to the regular
click CLI unchanged.
"""

from __future__ import annotations

import sys

#: The hidden click subcommand the installed hook command invokes.
HOOK_ARGV = ["claude-hook"]


def main() -> None:
    """Dispatch ``claude-hook`` to the light hook runtime, anything else to the click CLI."""
    if sys.argv[1:] == HOOK_ARGV:
        from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook

        sys.exit(run_pre_tool_use_hook())
    from parrot.knowledge.wiki.cli import main as cli_main

    cli_main()


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    main()
```
**Why:** exact-argv match keeps `wikitoolkit claude-hook --help` and similar on the click path
(identical behaviour); `HOOK_ARGV` could import `assets.HOOK_SUBCOMMAND` but that would import the
`claude_code` package — keep the literal and FILL IN a test asserting it equals `assets.HOOK_SUBCOMMAND`.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# REPLACE (verified: pyproject.toml:204; occurrences: 1)
wikitoolkit = "parrot.knowledge.wiki.cli:main"
# WITH
wikitoolkit = "parrot.knowledge.wiki.entry:main"
```

### `packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py` (MODIFY)
```python
# REPLACE in _run_hook (occurrences: 1): args += ["-m", "parrot.knowledge.wiki.cli", "claude-hook"]
# WITH a launch of the real console entry, e.g.
    args += ["-c", "import sys; sys.argv = ['wikitoolkit', 'claude-hook']; "
                   "from parrot.knowledge.wiki.entry import main; main()"]
# FILL IN: keep a `via_cli: bool = False` kwarg that still uses `-m parrot.knowledge.wiki.cli claude-hook`
#          for the byte-equality comparison in AC3.

# ADD tests (FILL IN bodies):
def test_entry_module_imports_no_cli() -> None:
    """AC1: importing entry loads no click, pydantic or parrot.knowledge.wiki.cli."""

def test_prefilter_path_imports(tmp_path: Path) -> None:
    """AC2: non-search Bash payload → empty stdout, exit 0, no project/pydantic/cli/installer/repo_scan."""

def test_config_path_matches_cli(tmp_path: Path) -> None:
    """AC3: Grep payload in a built fixture → same stdout as via_cli (fresh throttle window each —
    use two separate fixture repos so the stamp of run 1 cannot throttle run 2); no cli/installer/repo_scan."""

def test_entry_falls_through_to_cli() -> None:
    """AC6: `entry.main` with ['--help'] prints the same help as `cli.main`."""

# MODIFY test_warm_process_startup:
# FILL IN: measure two payloads — prefilter path {"tool_name": "Bash", "tool_input": {"command": "git status"}, cwd=built fixture}
#          and config path {"tool_name": "Grep", ..., cwd=built fixture, cooldown irrelevant};
#          hard-assert prefilter p50 < _TARGET_P50_MS (AC4); config path: evidence + warnings.warn on miss;
#          keep the ceiling asserts; write both into artifacts/logs/hook_startup_benchmark.json.
# Update the module docstring to mention FEAT-595.
```
**Why:** the old benchmark launched `-m parrot.knowledge.wiki.cli`, i.e. it measured the path this
feature removes; the prefilter path is the common case and is expected ≪ 300 ms, so it can be a
hard assertion without flakiness.

### FILL IN checklist
- [ ] `entry.py` as above + `HOOK_ARGV == assets.HOOK_SUBCOMMAND` assertion in a test
- [ ] pyproject line
- [ ] `_run_hook` switch + `via_cli`
- [ ] four new tests + reworked warm benchmark
- [ ] record cold / p50 / p95 for both paths in the Completion Note, plus the rollout note
      (operator re-runs `uv pip install -e packages/ai-parrot` in the main checkout)

---

## Acceptance Criteria

- [ ] Spec AC1, AC2, AC3, AC4, AC6 covered by tests in `test_hook_startup.py`.
- [ ] Prefilter-path warm p50 < 300 ms asserted and passing; config-path numbers reported.
- [ ] Spec AC7: `test_cli.py`, `test_installer_mcp.py`, `test_installation.py` pass unchanged.
- [ ] `ruff check` clean on touched Python files.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_hook_prefilter.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_installation.py -q`

## Completion Note

Completed 2026-09-23 (Claude Opus 5.5, via `/sdd-fix issue:f0a40d0853f2`).

- `entry.py` created as blueprinted (stdlib-only; exact-argv `claude-hook` match, else `cli.main()`).
- `pyproject.toml`: `wikitoolkit = "parrot.knowledge.wiki.entry:main"`.
- `test_hook_startup.py`: `_run_hook` launches the entry (`-c` shim equivalent) with a `via_cli` switch for the
  legacy path; new tests `test_entry_module_imports_no_cli` (AC1), `test_entry_hook_argv_matches_installed_subcommand`,
  `test_prefilter_path_imports` (AC2), `test_config_path_matches_cli` (AC3, byte-equal, two fixture repos),
  `test_entry_falls_through_to_cli` (AC6); `test_warm_process_startup` reworked into a two-path benchmark (AC4).

Benchmark (this runner, linux / CPython 3.12, 1 cold + 20 warm fresh processes, `artifacts/logs/hook_startup_benchmark.json`):

| Path | cold | warm p50 | warm p95 |
|---|---|---|---|
| prefilter (Bash `git status`, built repo) | 42 ms | **42 ms** | 43 ms |
| config (Grep, built repo) | 194 ms | **193 ms** | 199 ms |
| legacy `python -m parrot.knowledge.wiki.cli claude-hook` (reference, `/usr/bin/time`) | — | ~285 ms | — |

Prefilter p50 < 300 ms is a hard assertion; config path is warn-only and also under target here.

**Rollout**: the console shim is generated at install time — the main-checkout operator must re-run
`uv pip install -e packages/ai-parrot` for `.venv/bin/wikitoolkit` to use `entry:main`. Until then the old shim keeps
working (it still imports `cli`, but benefits from TASK-3672's light hook runtime). Installed hook command spelling
is unchanged, so no installer/settings changes are needed.

Validation: `test_hook_startup.py` + `test_hook_prefilter.py` 52 passed; `test_installation.py` 24 passed;
`test_cli.py` 3 failed / 16 passed and `test_installer_mcp.py` 2 failed / 22 passed — all 5 failures pre-existing and
identical on unchanged base e46249734 (`TestIngestModelResolutionDetectionFallback::*` lightweight-model detection;
`TestMCPJsonInstall::*` `shutil.which` absolute path). `ruff check` clean.
