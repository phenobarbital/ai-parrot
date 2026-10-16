# TASK-4311: resolve_setting() — one configuration reader; ProviderNotAvailable → exit 2

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4302
**Assigned-to**: unassigned

---

## Context

Spec §3 M4. Settings are read by `_navconfig`/`_env_credential` (project.py:792,822), `_env_setting` (cli.py:576, llm_resolve.py:11) and an inline navconfig block (graphindex/loader.py:337, handled in TASK-4318).

---

## Scope

- Add `resolve_setting(key, *, default=None, explicit=None, project_defaults=None)` to `wiki/project.py` (spec §2 semantics).
- Re-implement `_env_credential` on top of it (keep signature); `resolve_arango_params`/`resolve_wiki_env` unchanged in behaviour, except no implicit Arango loopback when the host is unset (actionable error naming keys).
- Replace `cli._env_setting` and `llm_resolve._env_setting` bodies with `resolve_setting` calls.
- Map `ProviderNotAvailable` to `click` exit code 2 with its message in the CLI entry point.
- Tests: precedence, falsey values preserved, broken navconfig (monkeypatched import raising) logs at debug and falls through, secrets never in messages, no loopback default.

**NOT in scope**: pg_schema (TASK-4312); loader navconfig block (TASK-4318); SQL dialect map (TASK-4313).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | resolve_setting + _env_credential |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | _env_setting + exit 2 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` | MODIFY | _env_setting |
| `packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py` | CREATE | resolver tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import ProviderNotAvailable  # TASK-4302
```

### Existing Signatures to Use
```python
# project.py: _navconfig() -> Any | None :792; _env_credential(key, default) :822; resolve_arango_params(config) :851; resolve_wiki_env :1112
# cli.py: def _env_setting(name: str) -> str | None :576 (callers :641, :658, :1612, :3958, :3966)
# llm_resolve.py: def _env_setting(name: str) -> str | None :11; resolve_optional_llm :31
```

### Does NOT Exist
- ~~`resolve_setting` (created here)~~
- ~~reading `wiki.json` inside the resolver — callers pass `project_defaults`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#_env_credential",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#resolve_arango_params",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_env_setting"
  ]
}
```

---

## Implementation Notes

Check `os.environ` membership before importing navconfig (hook path). `None` means absent; `False`/`0`/`""` are values. Never log values.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Write `resolve_setting` — *why*: one precedence for the whole graph tree.
2. Rebase `_env_credential` and the two `_env_setting` — *why*: no duplicate readers.
3. Remove loopback default in `resolve_arango_params` (actionable error) — *why*: spec §3 M4 intentional behaviour change.
4. Wire exit 2 — *why*: spec §2 ProviderNotAvailable contract.
5. Tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _env_credential(key: str, default: Any) -> Any:' parrot/knowledge/wiki/project.py)
# AFTER/AT — anchor `def _env_credential(key: str, default: Any) -> Any:` (verified: project.py:822)
# INSERT ABOVE `_env_credential`:
def resolve_setting(key: str, *, default: Any = None, explicit: Any = None, project_defaults: Mapping[str, Any] | None = None) -> Any:
    """explicit → os.environ → optional navconfig → project_defaults → default. ``None`` means absent."""
    if explicit is not None:
        return explicit
    if key in os.environ:
        return os.environ[key]
    nav = _navconfig()
    if nav is not None:
        value = nav.get(key)
        if value is not None:
            return value
    if project_defaults is not None and project_defaults.get(key) is not None:
        return project_defaults[key]
    return default


# THEN make _env_credential's body: return resolve_setting(key, default=default)
# FILL IN: add `from collections.abc import Mapping` if absent
```
**Why**: Exact precedence from spec §2; `_navconfig` already tolerates a broken navconfig.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _env_setting(name: str) -> str | None:' parrot/knowledge/wiki/cli.py)
# AFTER/AT — anchor `def _env_setting(name: str) -> str | None:` (verified: cli.py:576)
# REPLACE the body with:
#     from parrot.knowledge.wiki.project import resolve_setting
#     value = resolve_setting(name)
#     return value or None
# FILL IN: in the top-level click group/main, catch ProviderNotAvailable -> click.echo(str(exc), err=True); sys.exit(2)
```
**Why**: Same semantics as today (empty → None).

### `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _env_setting(name: str) -> str | None:' parrot/knowledge/wiki/llm_resolve.py)
# AFTER/AT — anchor `def _env_setting(name: str) -> str | None:` (verified: llm_resolve.py:11)
# REPLACE the body with resolve_setting(name) or None (import lazily inside the function)
```
**Why**: Keeps llm_resolve import-light.

### `packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py` (CREATE)
```python
"""resolve_setting precedence (FEAT-540 M4)."""
import pytest

from parrot.knowledge.wiki.project import resolve_setting


def test_explicit_wins(monkeypatch) -> None:
    monkeypatch.setenv("X_KEY", "env")
    assert resolve_setting("X_KEY", explicit="arg") == "arg"


def test_falsey_explicit_preserved() -> None:
    assert resolve_setting("X_KEY", explicit=0) == 0


def test_project_defaults_then_default(monkeypatch) -> None:
    monkeypatch.delenv("X_KEY", raising=False)
    assert resolve_setting("X_KEY", project_defaults={"X_KEY": "p"}, default="d") in ("p",)  # FILL IN: neutralise navconfig

# FILL IN: broken navconfig -> falls through + debug log; resolve_arango_params without host -> actionable error, no '127.0.0.1';
#          ProviderNotAvailable raised in a CLI command -> exit code 2 (click CliRunner)
```
**Why**: Covers every precedence level and the behaviour change.

### FILL IN checklist
- [ ] Mapping import
- [ ] exit-2 handler placement
- [ ] loopback removal in resolve_arango_params
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] `resolve_setting` precedence and falsey semantics covered
- [ ] no implicit Arango loopback
- [ ] `ProviderNotAvailable` → exit 2
- [ ] existing project/cli tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_remote_config.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4311 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: Setting-resolution seam + test_resolve_setting.py; no review corrections. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings show no failure absent from the clean origin/dev baseline.

**Deviations from spec**: none
