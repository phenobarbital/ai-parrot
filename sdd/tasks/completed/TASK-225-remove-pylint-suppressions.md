# TASK-225: Remove # pylint: disable=E0611 from Dependent Files

**Feature**: Exception Migration — Cython to Pure Python (FEAT-031)
**Spec**: `sdd/specs/exception-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-222
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Every file that imports from `parrot.exceptions` carries a `# pylint: disable=E0611` comment
> because pylint cannot introspect compiled `.so` extensions (E0611 = "no-name-in-module"). Now
> that `parrot/exceptions.py` is pure Python, pylint can introspect it normally and the
> suppressions are no longer needed.

---

## Scope

For each file in the table below, remove the `# pylint: disable=E0611` inline comment from the
exception import line. If `# noqa` is present **solely** for E0611, remove it too. Do not remove
`# noqa` comments that cover other warnings.

| File | Import line (before) | Import line (after) |
|---|---|---|
| `parrot/bots/abstract.py` | `from ..exceptions import ConfigError  # pylint: disable=E0611` | `from ..exceptions import ConfigError` |
| `parrot/interfaces/google.py` | `from ..exceptions import ConfigError  # pylint: disable=E0611 # noqa` | `from ..exceptions import ConfigError` |
| `parrot/stores/abstract.py` | `from ..exceptions import ConfigError  # pylint: disable=E0611` | `from ..exceptions import ConfigError` |
| `parrot/stores/bigquery.py` | `from ..exceptions import DriverError` | (verify no suppression; no change if clean) |
| `parrot/clients/google/generation.py` | `from ...exceptions import SpeechGenerationError  # pylint: disable=E0611` | `from ...exceptions import SpeechGenerationError` |
| `parrot/tools/qsource.py` | `from ..exceptions import ToolError  # pylint: disable=E0611` | `from ..exceptions import ToolError` |
| `parrot/tools/querytoolkit.py` | `from ..exceptions import ToolError  # pylint: disable=E0611 # noqa` | `from ..exceptions import ToolError` |
| `parrot/tools/nextstop/employee.py` | `from ...exceptions import ToolError  # pylint: disable=E0611` | `from ...exceptions import ToolError` |
| `parrot/tools/epson/__init__.py` | `from ...exceptions import ToolError  # pylint: disable=E0611 # noqa` | `from ...exceptions import ToolError` |
| `parrot/tools/sassie/__init__.py` | `from ...exceptions import ToolError  # pylint: disable=E0611` | `from ...exceptions import ToolError` |

**Read each file before editing** to confirm the exact comment text — the table above shows
expected content but verify against actual file state.

**NOT in scope**: Any other code changes in these files beyond removing the import-line comments.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/bots/abstract.py` | MODIFY — strip inline comment |
| `parrot/interfaces/google.py` | MODIFY — strip inline comment |
| `parrot/stores/abstract.py` | MODIFY — strip inline comment |
| `parrot/stores/bigquery.py` | VERIFY — likely already clean |
| `parrot/clients/google/generation.py` | MODIFY — strip inline comment |
| `parrot/tools/qsource.py` | MODIFY — strip inline comment |
| `parrot/tools/querytoolkit.py` | MODIFY — strip inline comment |
| `parrot/tools/nextstop/employee.py` | MODIFY — strip inline comment |
| `parrot/tools/epson/__init__.py` | MODIFY — strip inline comment |
| `parrot/tools/sassie/__init__.py` | MODIFY — strip inline comment |

---

## Acceptance Criteria

- [ ] No file in `parrot/` contains `# pylint: disable=E0611` on an `exceptions` import line
- [ ] Import paths (`from ..exceptions import X`, `from ...exceptions import X`) are unchanged
- [ ] `pytest` full suite passes (no import errors introduced)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/exception-migration.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Read each target file** before editing (do not guess line numbers)
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-225-remove-pylint-suppressions.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**: Removed `# pylint: disable=E0611` (and `# noqa` where it was solely for E0611) from all 9 target files. `parrot/stores/bigquery.py` was already clean. Remaining suppressions in other files (`datamodel`, `asyncdb`, `navconfig`, `querysource`) are for external compiled packages and are out of scope. All 20 exception tests pass.

**Deviations from spec**: None.
