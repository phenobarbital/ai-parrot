# TASK-5735: Canonical experience events drop home-directory prefixes before identity

**Feature**: FEAT-905 — `parrot sdd experience export` writes into the checkout it runs in, without home paths
**Spec**: `sdd/specs/experience-sync-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:ebd9db5806f2`

---

## Context

Spec §2 item 2 / §3 Module 2. Exported lesson files are git-tracked, but experience events keep absolute
`/home/<user>/...` paths in `fix_example`, `scope_paths`, `command_example`, `solution` and `error_excerpt`.
The export in `/sdd-done FEAT-904` held 15 of them. `validate_event` is the one place every source (repo log,
global log, shared files) passes through before `event_id` is computed, so the normalization goes there.

---

## Scope

- Add `import re`, the compiled `_HOME_PATH_RE` and the private recursive `_strip_home` to `models.py`.
- In `validate_event`, apply `_strip_home` to the result of `_normalize_payload(...)` and to the redacted
  envelope, before `_event_id_for`.
- Tests: `test_strip_home_normalizes_home_prefixes`, `test_event_strips_home_paths_before_identity`
  (`test_models.py`) and `test_export_strips_home_paths_without_reexport` (`test_sync.py`).

**NOT in scope**: `fastpath.py` (`redact`, `normalize_error`, `append_event`), `service.py`
(`failure_signature`, `lesson_id_for`, `solution_rev_for` inputs), `sync.py`, `experience_cli.py`, rewriting raw
log lines on disk, paths outside a home directory, Windows backslash paths, the `actor` value.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | MODIFY | `re` import, `_HOME_PATH_RE`, `_strip_home`, two lines in `validate_event` |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` | MODIFY | two new tests |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` | MODIFY | one new test |

---

## Codebase Contract (Anti-Hallucination)

Verified against `70567be025`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py — already imported
import hashlib  # line 5
import json  # line 6
from collections.abc import Mapping  # line 7
from typing import Any, Literal  # line 8
from parrot.knowledge.wiki.experience.fastpath import MAX_EVENT_BYTES, leading_command, normalize_error, redact  # line 12
# to add: import re

# packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py — already imported
from pathlib import Path  # line 3
import pytest  # line 5
from parrot.knowledge.wiki.experience import models  # line 7
# to add
import json
from parrot.knowledge.wiki.experience.fastpath import normalize_error  # fastpath.py:370

# packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py — already imported
from parrot.knowledge.wiki.experience import sync  # line 12
from parrot.knowledge.wiki.experience.fastpath import append_event  # line 13
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py
def validate_event(line: Mapping[str, Any]) -> ExperienceEvent | None  # line 225
    # line 254: canonical_payload = _normalize_payload(envelope.kind, payload)
    # line 255: canonical_envelope = _redact_text(envelope.model_dump(mode="json"))
    # line 256: canonical_envelope["payload"] = canonical_payload
    # line 257: canonical_envelope["event_id"] = _event_id_for(canonical_envelope)
def _normalize_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]  # line 297
    # _redact_text first, then normalize_error(error_signature) and per-field truncation
def _redact_text(value: Any) -> Any  # line 317; recursive over str / list / dict

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py
def normalize_error(text: str) -> str  # line 370; redact, then absolute paths → " ", timestamps, hex, numbers
def append_event(plane_dir: Path, record: Mapping[str, Any]) -> bool  # line 584; writes the mapping as given

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py
def export_shared(repo_plane: Path, checkout: Path) -> Path | None  # line 121
def shared_event_ids(checkout: Path) -> set[str]  # line 106

# packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py
def _recorded_payload() -> dict[str, object]  # line 139
def _event(kind: str, payload: dict[str, object], **overrides: object) -> dict[str, object]  # line 159
def test_event_redaction_before_identity(tmp_path: Path) -> None  # line 213

# packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py
def _record(lesson_id: str, solution_rev: str, *, sequence: int, tier: str = "repo", solution: str = ...) -> dict[str, object]  # line 46
def _append(plane: Path, *events: dict[str, object]) -> None  # line 81
def _read_events(path: Path) -> list[dict[str, object]]  # line 98
def _checkout(tmp_path: Path, name: str) -> tuple[Path, Path]  # line 103
```

### Does NOT Exist
- ~~`models._HOME_PATH_RE`, `models._strip_home`~~ — created by this task.
- ~~home-path handling in `fastpath.redact` or `normalize_error`~~ — both stay unchanged.
- ~~an event field that records the producing feature~~ — none; export stays repo-wide.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py#validate_event",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py#_normalize_payload",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py#export_shared"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Apply `_strip_home` **after** `_normalize_payload`, never inside `redact()` or `_redact_text`. `normalize_error`
  turns `/home/u/x` into a space but `~/x` into `~`, so stripping earlier would change stored trigger
  signatures, and `service.record` derives `lesson_id` and `solution_rev` from `redact()` output.
- The function is idempotent, so validating a canonical event again yields an equal event.
- Dict keys are schema names; only values are rewritten.
- Truncation in `_normalize_payload` runs first. A home path cut short by truncation leaves at most a partial
  prefix, never a username followed by more path.

---

## Implementation Blueprint

### `models.py`

```python
import re  # after `import json`

_HOME_PATH_RE = re.compile(
    r"(?<![\w.~-])(?:/var)?/(?:home|Users)/[^/\s'\"`:;,)\]}>]+"
    r"|(?<![\w.~/:-])[A-Za-z]:/Users/[^/\s'\"`:;,)\]}>]+"
)

# validate_event
canonical_payload = _strip_home(_normalize_payload(envelope.kind, payload))
canonical_envelope = _strip_home(_redact_text(envelope.model_dump(mode="json")))


def _strip_home(value: Any) -> Any:
    """Recursively replace user home-directory prefixes with ``~``.

    Runs after redaction and error normalization, so failure signatures keep
    their inputs; the stored text and the event identity see ``~``.
    """
    if isinstance(value, str):
        return _HOME_PATH_RE.sub("~", value)
    if isinstance(value, list):
        return [_strip_home(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_home(item) for key, item in value.items()}
    return value
```

### `test_models.py`

- `test_strip_home_normalizes_home_prefixes`, parametrized over `(raw, expected)`:
  `/home/alice/repo/x.py` → `~/repo/x.py`; `PYTHONPATH=/home/alice/p:/home/alice/q` → `PYTHONPATH=~/p:~/q`;
  `/Users/bob` → `~`; `/var/home/carol/.cache` → `~/.cache`; `C:/Users/dave/src` → `~/src`;
  `(/home/alice)` → `(~)`; unchanged: `src/home/alice/x`, `/srv/home/alice`, `/tmp/project`, `~/x`. Assert
  `models._strip_home(raw) == expected`, `models._strip_home(expected) == expected`, and the nested form
  `models._strip_home({"k": [raw]}) == {"k": [expected]}`.
- `test_event_strips_home_paths_before_identity`: from `_recorded_payload()`, set `error_signature` and
  `error_excerpt` to `No such file: /home/alice/repo/missing.py`, `command_example` to
  `/home/alice/repo/.venv/bin/python -m pytest`, `solution` to a sentence holding
  `/home/alice/repo/.venv/bin/python`, `fix_example` to `PYTHONPATH=/home/alice/repo/src pytest` and
  `scope_paths` to `["/home/alice/repo/src/app.py"]`. The validated event's JSON has no `/home/alice` and
  holds `~/repo/.venv/bin/python`; its `error_signature` equals
  `normalize_error("No such file: /home/alice/repo/missing.py")`; `models.validate_event(event.model_dump(mode="json")) == event`.

### `test_sync.py`

- `test_export_strips_home_paths_without_reexport(tmp_path, monkeypatch)`: set `PARROT_HOME`;
  `root, plane = _checkout(tmp_path, "primary")`; `legacy = _record("pit-home", "rev-home", sequence=1)`; set
  its `draft["fix_example"]` to `PYTHONPATH=/home/alice/repo/src pytest` and `draft["scope_paths"]` to
  `["/home/alice/repo/src/app.py"]` (narrow with `isinstance` asserts), leaving the stale `event_id`;
  `_append(plane, legacy)`. `sync.export_shared(plane, root)` returns a file whose text has no `/home/alice`
  and holds `~/repo/src`; `sync.shared_event_ids(root)` equals the exported ids; a second
  `sync.export_shared(plane, root)` returns `None`.

---

## Acceptance Criteria

- [ ] Validated events contain no `/home/<user>`, `/var/home/<user>`, `/Users/<user>` or `<drive>:/Users/<user>`
      prefix; `error_signature` is unchanged by the normalization.
- [ ] Validating a canonical event again yields an equal event (same `event_id`).
- [ ] A legacy home-path line is exported once without the prefix; a second export returns `None`.
- [ ] `test_event_strips_home_paths_before_identity` and `test_export_strips_home_paths_without_reexport` fail
      on `origin/dev` without the fix and pass with it.
- [ ] Every pre-existing test in `test_models.py` and `test_sync.py` still passes; `ruff check` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py -q`

---

## Test Specification

Spec §4, M2 rows.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug experience-sync-fixes --feature-id FEAT-905`).
2. Verify the Codebase Contract, mark the task `in-progress` in `sdd/tasks/index/experience-sync-fixes.json`.
3. Implement from the blueprint, run the Validation Commands from the worktree root with
   `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the three files listed, close with `scripts/sdd/close_task.sh`, fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (`/sdd-fix` session, actor `agent:sdd-fix:d1ad40b1`)
**Date**: 2026-11-17
**Notes**: code commit `2cb5d8fd2a`. `models._HOME_PATH_RE` and the recursive `models._strip_home` replace
`/home/<user>`, `/var/home/<user>`, `/Users/<user>` and `<drive>:/Users/<user>` with `~`. `validate_event`
applies it to the result of `_normalize_payload` and to the redacted envelope, before `_event_id_for`.
`redact`, `normalize_error`, `failure_signature`, `lesson_id_for` and `solution_rev_for` are untouched.
Validation: `PYTHONPATH=packages/ai-parrot/src pytest .../test_models.py .../test_sync.py -q` → 29 passed;
wider experience suites (`tests/knowledge/wiki/experience`, `test_experience_cli.py`, `test_experience_hook.py`,
`test_launcher_experience_fast_path.py`) → 123 passed; `tests/flows/dev_loop/test_experience_interceptor.py`
→ 4 passed; `ruff check` and `black --check -l 120` clean. Mutation check: with `origin/dev`'s `models.py`,
`test_event_strips_home_paths_before_identity` and `test_export_strips_home_paths_without_reexport` fail;
restored → pass.
**Deviations from spec**: the pattern is written as one raw string instead of two adjacent literals, because
`black` would join the two literals on one line. The regex itself is the one in spec §2.
