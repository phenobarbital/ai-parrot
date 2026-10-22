# TASK-4564: InboxConfig stability-window settings

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1**. The watcher (TASK-4565/4566) must hold every inbox candidate
behind a uniform size+mtime stability window (spec C11, §8 "Stability window value":
two polls ~1.5 s apart, ≈3 s, **configurable**). This task adds only the two
configuration fields and their validation. It is the root of the watcher chain.

---

## Scope

- Add `stability_window: float` (default `3.0`, `ge=0.0`, `le=300.0`) to `InboxConfig`.
- Add `stability_poll_interval: float` (default `1.5`, `gt=0.0`, `le=60.0`) to `InboxConfig`.
- Extend the existing `_validate_layout` validator: reject `stability_poll_interval >
  stability_window` whenever `stability_window > 0`. `stability_window == 0` means
  "no stability gate" and is valid with any interval.
- Write tests for all of the above.

**NOT in scope**: the watcher itself (TASK-4565/4566), the CLI flag (TASK-4567),
touching `stage_git` (spec C15 — the watcher must never override it), docs (TASK-4576).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Add `stability_window` / `stability_poll_interval` to `InboxConfig`; extend `_validate_layout` |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` | MODIFY | Defaults, bounds and cross-field validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import InboxConfig  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:286
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:286
class InboxConfig(BaseModel):
    dir: str = Field(default="inbox", ...)                          # :289
    archive_dir: str = Field(default=f"{PARROT_DIR}/archive", ...)  # :290
    rejected_subdir: str = Field(default="rejected", ...)           # :293
    markdown_dir: str | None = Field(default=None, ...)             # :294
    date_format: str = Field(default="%Y-%m-%d", ...)               # :297
    stage_git: bool = Field(default=True, ...)                      # :298  — DO NOT TOUCH (C15)
    max_candidates: int = Field(default=20, ge=1, le=100, ...)      # :299
    lock_timeout: float = Field(default=30.0, ge=0.0, ...)          # :300

    @model_validator(mode="after")
    def _validate_layout(self) -> "InboxConfig":                    # :303 — EXTEND, do not replace
        # :305-311 reject empty dir/archive_dir and an unsafe rejected_subdir
        return self
```

### Does NOT Exist
- ~~`InboxConfig.stability_window`~~ / ~~`InboxConfig.stability_poll_interval`~~ — this task creates them.
- ~~`InboxConfig.watch`~~ / ~~`InboxConfig.debounce`~~ — not fields; the watcher's debounce is a constructor argument (TASK-4566).
- ~~a separate `WatcherConfig` model~~ — the settings live on `InboxConfig` by spec decision.

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
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#InboxConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#InboxConfig._validate_layout"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 `Field(...)` with `description=` on both fields, matching the style of
  the neighbouring fields — because `wikitoolkit config` surfaces descriptions to users.
- Keep `_validate_layout` a single validator: add the new check just before its
  `return self`, because a second `model_validator` would split one concern into two.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the two fields immediately below `lock_timeout` — *why*: groups all inbox
   run-control knobs together, and the anchor line is unique.
2. Add the cross-field check at the end of `_validate_layout` — *why*: the poll
   interval must fit inside the window it samples (spec §3 M1 docstring).
3. Extend `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` — *why*: AC5's correctness rests on these bounds.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY) — fields
```python
# occurrences: 1 (verified: grep -cF '    lock_timeout: float = Field(default=30.0, ge=0.0, description="Seconds to wait for the inbox lock.")' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:300)
    stability_window: float = Field(
        default=3.0,
        ge=0.0,
        le=300.0,
        description="Seconds a candidate's size and mtime must stay unchanged before ingestion (0 disables the gate).",
    )
    stability_poll_interval: float = Field(
        default=1.5,
        gt=0.0,
        le=60.0,
        description="Seconds between the size/mtime samples that prove a candidate is stable.",
    )
```
**Why this shape**: defaults are the spec's decided ≈3 s (two samples 1.5 s apart);
the upper bounds stop a typo from parking ingestion for hours.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY) — validator
```python
# occurrences: 1 (verified: grep -cF '            raise ValueError("inbox.rejected_subdir must be a single path segment without separators or '"'"'..'"'"'")' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — insert below that raise (verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:311), i.e. directly before `return self`
        if self.stability_window > 0 and self.stability_poll_interval > self.stability_window:
            raise ValueError("inbox.stability_poll_interval must not exceed inbox.stability_window")
```
**Why**: a poll interval longer than the window can never take two samples inside it.
Keep the message prefixed `inbox.` like the existing errors.

### FILL IN checklist
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` — tests: defaults (3.0 / 1.5); `stability_window=-1` rejected;
  `stability_poll_interval=0` rejected; `window=1.0, interval=2.0` rejected;
  `window=0, interval=5.0` accepted; `stage_git` default unchanged (`True`).

---

## Acceptance Criteria

- [ ] `InboxConfig()` has `stability_window == 3.0` and `stability_poll_interval == 1.5`.
- [ ] Out-of-bounds values and `poll > window` (window > 0) raise `ValidationError`.
- [ ] `stage_git` default is still `True` (C15).
- [ ] Existing `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` tests still pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/project.py packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py  (append)
import pytest
from pydantic import ValidationError
from parrot.knowledge.wiki.project import InboxConfig


def test_stability_defaults() -> None:
    cfg = InboxConfig()
    assert cfg.stability_window == 3.0
    assert cfg.stability_poll_interval == 1.5
    assert cfg.stage_git is True


@pytest.mark.parametrize("kwargs", [
    {"stability_window": -1.0},
    {"stability_poll_interval": 0.0},
    {"stability_window": 1.0, "stability_poll_interval": 2.0},
])
def test_stability_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        InboxConfig(**kwargs)


def test_zero_window_disables_gate() -> None:
    assert InboxConfig(stability_window=0.0, stability_poll_interval=5.0).stability_window == 0.0
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4564 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4564 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note


- Task: TASK-4564
- Feature: fireflies-insights-agent
- Implementation SHA: f2b9c15a3b3622a4831920b2c6eec5a27fb1be9d
- Closed at (UTC): 2026-10-21T23:53:25+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 105.4s · Tokens: n/a |
