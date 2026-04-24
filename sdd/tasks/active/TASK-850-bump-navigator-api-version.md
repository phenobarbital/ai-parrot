# TASK-850: Bump navigator-api dependency floor to 2.14.1

**Feature**: FEAT-123 — fileinterface-migration
**Spec**: `sdd/specs/fileinterface-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The migration plan turns `parrot.interfaces.file` into a thin shim
over `navigator.utils.file`. That upstream module first appears in
`navigator-api` tag `2.14.1`. The current
`packages/ai-parrot/pyproject.toml` pins
`navigator-api[uvloop,locale]>=2.13.5`, which would let CI / fresh
installs pull a version that does not have `navigator/utils/file/`,
breaking the shim at import time.

This task only bumps the dependency pin and verifies the
environment still resolves cleanly. Implements **Module 1** of the
spec.

---

## Scope

- Edit `packages/ai-parrot/pyproject.toml` to change the
  `navigator-api` requirement from `>=2.13.5` to `>=2.14.1`. Keep
  the `[uvloop,locale]` extras and the existing line ordering.
- Run `uv pip install -e packages/ai-parrot` (with the venv
  activated per CLAUDE.md) and confirm the resolver finds a
  compatible version with no conflict against `navigator-auth`,
  `navigator-session`, `flowtask`, `azure-teambots`,
  `querysource`, or any other already-installed consumer of
  `navigator-api`.
- Confirm
  `python -c "from navigator.utils.file import FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager, FileManagerFactory; print('ok')"`
  prints `ok` from inside the venv after the bump.

**NOT in scope**:
- Editing `parrot/interfaces/file/*` (TASK-851).
- Editing `parrot/tools/filemanager.py` (TASK-852).
- Writing or updating tests (TASK-853 / TASK-854).
- Touching any other dependency in `pyproject.toml`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | One-line change: `navigator-api[uvloop,locale]>=2.13.5` → `navigator-api[uvloop,locale]>=2.14.1`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Verified to exist in the installed navigator-api ≥ 2.14.1:
from navigator.utils.file import (
    FileManagerInterface,        # navigator/utils/file/abstract.py:36
    FileMetadata,                # navigator/utils/file/abstract.py:16
    LocalFileManager,            # navigator/utils/file/local.py:22
    TempFileManager,             # navigator/utils/file/tmp.py
    FileManagerFactory,          # navigator/utils/file/factory.py:14
    FileServingExtension,        # navigator/utils/file/web.py:28
)
```

### Existing Signatures to Use

```toml
# packages/ai-parrot/pyproject.toml — current line (verified 2026-04-25):
"navigator-api[uvloop,locale]>=2.13.5",
```

The bump must produce exactly:

```toml
"navigator-api[uvloop,locale]>=2.14.1",
```

No other dependency lines are touched.

### Does NOT Exist

- ~~`navigator-api>=3.0.0` is **not** the right pin~~. The locally
  installed 3.0.0 is an editable / pre-release install of master.
  The first **published** PyPI release that ships
  `navigator/utils/file/` is `2.14.1` (verified via local git
  tags in `~/proyectos/navigator/navigator`). Using `>=3.0.0`
  would block the install on a release that may not be on PyPI.
- ~~`navigator-api[uvloop,locale,file]`~~ — there is no `file`
  extra. The file module is part of the base package.
- ~~A `[project.optional-dependencies] file = [...]` entry~~ —
  none required; `aioboto3` and `google-cloud-storage` are
  already optional/lazy.

---

## Implementation Notes

### Pattern to Follow

A previous version bump for context:
```bash
git log --oneline -- packages/ai-parrot/pyproject.toml | head -3
```
Just edit the one line.

### Key Constraints

- Use the **`uv`** package manager only, with the venv activated:
  ```bash
  source .venv/bin/activate
  uv pip install -e packages/ai-parrot
  ```
- Do **not** run `pip install` directly.
- Do **not** regenerate or commit `uv.lock` unless the project
  already has one tracked. Check with
  `git ls-files | grep -E '(uv|requirements)\.lock'` first; if
  present, regenerate, otherwise leave alone.
- Do not touch any other dependency line.

### References in Codebase

- `packages/ai-parrot/pyproject.toml` — the file to edit.
- `~/proyectos/navigator/navigator/navigator/version.py` —
  evidence for the version floor (`__version__ = "2.14.1"`).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/pyproject.toml` shows
      `navigator-api[uvloop,locale]>=2.14.1`.
- [ ] No other dependency line in `pyproject.toml` is changed.
- [ ] `uv pip install -e packages/ai-parrot` completes without
      resolver errors.
- [ ] `python -c "from navigator.utils.file import FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager, FileManagerFactory; print('ok')"`
      prints `ok`.
- [ ] `git diff packages/ai-parrot/pyproject.toml` shows exactly
      one changed line.

---

## Test Specification

No code tests — this is a dependency declaration. The verification
is the import smoke test in the acceptance criteria.

```bash
source .venv/bin/activate
uv pip install -e packages/ai-parrot
python - <<'PY'
from navigator.utils.file import (
    FileManagerInterface, FileMetadata,
    LocalFileManager, TempFileManager,
    FileManagerFactory,
)
print("ok")
PY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — none (this is the first task).
3. **Verify the Codebase Contract** — confirm the current
   `pyproject.toml` line still reads `>=2.13.5` before editing.
4. **Update status** in `sdd/tasks/.index.json` →
   `"in-progress"` with your session ID.
5. **Implement** the one-line change. Run the smoke test.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-850-bump-navigator-api-version.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
