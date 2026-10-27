# TASK-4867: Hooks config models and loader (`.parrot/sdd_hooks.toml`)

**Feature**: FEAT-764 — `/sdd-done` closeout hooks
**Spec**: `sdd/specs/sdd-done-closeout-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1 and §2 Data Models: the declarative registry every other
module reads. Spec G1, AC1, AC2. Config lives ONLY in `.parrot/sdd_hooks.toml` (no CLAUDE.md section).

---

## Scope

- Create `scripts/sdd/closeout_hooks_config.py` with `HookKind`, `HookSpec`, `HooksConfig`,
  `HookContext`, `HookResult`, `HooksConfigError`, `CONFIG_PATH`, `EVENTS`, `KNOWN_BUILTINS`,
  `PUSH_PROVIDERS` and `load_hooks(root)`.
- Validation (all raise `HooksConfigError`, never silently default):
  per-kind required fields (`command`→`run`, `agent`→`agent`+`prompt`, `builtin`→`builtin`);
  `builtin` must be in `KNOWN_BUILTINS`; `push.send` `with.provider` (default `ntfy`) must be in
  `PUSH_PROVIDERS`; `blocking=True` rejected on `post_pr`/`on_failure`; duplicate `name` per event;
  `name` matches `^[a-z0-9][a-z0-9-]*$`; unknown top-level event keys under `[hooks]`.
- Absent file → empty `HooksConfig()`.
- Write unit tests.

**NOT in scope**: running hooks (TASK-4869), builtin behaviour (TASK-4868), twins/docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/closeout_hooks_config.py` | CREATE | Pydantic models, KNOWN_BUILTINS, PUSH_PROVIDERS, load_hooks() |
| `tests/sdd_scripts/test_closeout_hooks_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib                           # stdlib; same usage: packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py:6
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator   # pydantic v2 (project-wide)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py
CONFIG_PATH: str = ".parrot/test_runners.toml"            # line 14 — naming precedent only
def load_registry(worktree: Path) -> RunnerRegistry:       # line 125 — loader precedent (tomllib.loads, line 131)
```
Do NOT import from `parrot.*`: `scripts/sdd/` modules stay stdlib + pydantic only so they relocate
unchanged when FEAT-633 moves `scripts/` into the package (spec §7).

### Does NOT Exist
- ~~`.parrot/sdd_hooks.toml`~~ — not in the repo; tests create it under `tmp_path`.
- ~~`parrot.sdd.hooks`~~ / ~~`parrot_sdd`~~ — no such module on `dev`.
- ~~`scripts/sdd/closeout_hooks_config.py`~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/closeout_hooks_config.py",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_closeout_hooks_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py#load_registry"
  ]
}
```

---

## Implementation Notes

- Pydantic v2; `HookSpec.with_` uses `alias="with"` and `model_config = ConfigDict(populate_by_name=True, extra="forbid")` — *because* a typo'd key in a committed config must fail, not be ignored.
- `blocking` validation needs the event name, so do it in `load_hooks`, not in `HookSpec`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the models exactly as below — *why*: TASK-4868/4869 import these names verbatim.
2. Implement `load_hooks` — *why*: single fail-closed entry point (AC2).
3. Write the tests from the Test Specification, then fill each.

### `scripts/sdd/closeout_hooks_config.py` (CREATE)
```python
"""Closeout-hook registry for /sdd-done (FEAT-764): models + `.parrot/sdd_hooks.toml` loader."""
from __future__ import annotations

import re
import tomllib
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_PATH: str = ".parrot/sdd_hooks.toml"
EVENTS: tuple[str, ...] = ("pre_pr", "post_pr", "on_failure")
NON_BLOCKING_EVENTS: frozenset[str] = frozenset({"post_pr", "on_failure"})
KNOWN_BUILTINS: frozenset[str] = frozenset({"jira.transition", "telegram.send", "push.send", "webhook.post"})
PUSH_PROVIDERS: frozenset[str] = frozenset({"ntfy", "gotify"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class HooksConfigError(ValueError):
    """Raised when .parrot/sdd_hooks.toml is malformed."""


class HookKind(str, Enum):
    """How a hook is executed."""

    COMMAND = "command"
    AGENT = "agent"
    BUILTIN = "builtin"


class HookSpec(BaseModel):
    """One subscribed hook."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    kind: HookKind
    run: str | None = None
    agent: str | None = None
    prompt: str | None = None
    builtin: str | None = None
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")
    blocking: bool = False
    timeout_s: int = Field(default=600, gt=0)
    artifacts: str | None = None
    enabled: bool = True


class HooksConfig(BaseModel):
    """Hooks grouped by closeout event."""

    pre_pr: list[HookSpec] = Field(default_factory=list)
    post_pr: list[HookSpec] = Field(default_factory=list)
    on_failure: list[HookSpec] = Field(default_factory=list)

    def for_event(self, event: str) -> list[HookSpec]:
        """Return the enabled hooks for ``event`` in declaration order."""
        return [h for h in getattr(self, event) if h.enabled]


class HookContext(BaseModel):
    """Context handed to every hook (JSON file + env vars)."""

    feat_id: str
    spec_path: str
    branch: str
    base_branch: str
    worktree: str
    pr_url: str | None = None
    merge_sha: str | None = None
    test_report_md: str | None = None
    e2e_gate: dict[str, Any] | None = None
    abort_reason: str | None = None
    dry_run: bool = False


class HookResult(BaseModel):
    """Outcome of one hook."""

    name: str
    kind: HookKind
    status: Literal["pass", "fail", "skipped", "pending", "timeout"]
    blocking: bool
    duration_s: float = 0.0
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)


def _validate_hook(event: str, hook: HookSpec) -> None:
    """Raise HooksConfigError for any per-hook rule violation (spec §3 M1)."""
    # FILL IN: name regex; per-kind required fields; builtin in KNOWN_BUILTINS;
    #          push.send provider (with_.get("provider", "ntfy")) in PUSH_PROVIDERS;
    #          blocking on NON_BLOCKING_EVENTS — bounded by spec §3 M1 + AC2
    raise NotImplementedError


def load_hooks(root: Path) -> HooksConfig:
    """Load and validate hooks; return an empty HooksConfig when the file is absent.

    Raises:
        HooksConfigError: invalid TOML or schema violation (never a silent default).
    """
    path = Path(root) / CONFIG_PATH
    if not path.is_file():
        return HooksConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise HooksConfigError(f"{path}: {exc}") from exc
    hooks = data.get("hooks", {})
    # FILL IN: reject unknown keys in `hooks` (not in EVENTS) and any top-level key other than "hooks";
    #          build HooksConfig (wrap ValidationError in HooksConfigError); duplicate names per event;
    #          call _validate_hook for each — bounded by AC2 (fail closed)
    raise NotImplementedError
```
**Why this shape**: names and fields are fixed by spec §2 Data Models; `for_event` keeps the
`enabled` filter in one place for the dispatcher.

### FILL IN checklist
- [ ] `_validate_hook` — all per-hook rules; bounded by spec §3 M1
- [ ] `load_hooks` — unknown keys, duplicates, ValidationError wrapping; bounded by AC2

---

## Acceptance Criteria

- [ ] Absent file → `HooksConfig()` with three empty lists (AC1).
- [ ] Every invalid case in the Test Specification raises `HooksConfigError` (AC2).
- [ ] `push.send` with provider `ntfy`/`gotify` loads; any other provider raises.
- [ ] No `parrot.*` import; `ruff check scripts/sdd/closeout_hooks_config.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_closeout_hooks_config.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_closeout_hooks_config.py
from pathlib import Path
import pytest
from scripts.sdd.closeout_hooks_config import HooksConfigError, load_hooks


def _cfg(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "sdd_hooks.toml").write_text(body)
    return tmp_path


def test_absent_file_is_empty(tmp_path): ...
def test_valid_all_kinds_load(tmp_path): ...            # command, agent, builtin; `with` alias
def test_malformed_toml_raises(tmp_path): ...
def test_blocking_on_post_pr_raises(tmp_path): ...
def test_unknown_builtin_raises(tmp_path): ...
def test_push_send_unknown_provider_raises(tmp_path): ...
def test_push_send_ntfy_and_gotify_ok(tmp_path): ...
def test_duplicate_name_raises(tmp_path): ...
def test_missing_kind_field_raises(tmp_path): ...       # command without run, agent without prompt
def test_unknown_event_key_raises(tmp_path): ...
def test_extra_hook_key_raises(tmp_path): ...
def test_disabled_hook_filtered_by_for_event(tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-done-closeout-hooks --feature-id FEAT-764`), never on `dev`.
2. Read the spec `sdd/specs/sdd-done-closeout-hooks.spec.md` (§2 Overview, Data Models, exit-code table).
3. Every `Depends-on` task must be `done` in `sdd/tasks/index/sdd-done-closeout-hooks.json`.
4. Verify the Codebase Contract before writing code; fix stale entries first.
5. Mark `in-progress` in the index, implement from the Blueprint, complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH=.` from the worktree root; `ruff check` the new files.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh <TASK-ID> sdd-done-closeout-hooks verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
