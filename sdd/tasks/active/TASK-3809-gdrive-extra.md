# TASK-3809: `ai-parrot[gdrive]` packaging extra

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (packaging half; docs are TASK-3819), goal G8, AC17. Add a dedicated
`gdrive` extra mirroring the FEAT-603 `msgraph` extra and fold it into `all`. **Exclusive**
task: it edits a dependency manifest.

---

## Scope

- Add a `gdrive = [...]` block (with a one-line comment like the `msgraph` one) immediately
  before `agents = [` in `packages/ai-parrot/pyproject.toml`.
- Append `,gdrive` to the `ai-parrot[...]` self-reference inside `all = [`.
- Create `packages/ai-parrot/tests/test_gdrive_extra.py` (copy the `test_msgraph_extra.py` shape).
- Record `uv pip install -e "packages/ai-parrot[gdrive]" --dry-run` output (or the reason it
  could not run inside the worktree) in `artifacts/logs/FEAT-608-gdrive-extra.log` and mention
  it in the Completion Note — AC17 wants the resolution recorded; the real install is done by
  the main-checkout operator (worktree rule: never `uv sync` inside a worktree).

**NOT in scope**: `uv.lock`; the `aiogoogle==5.17.0` pins inside the `agents` bundles
(`pyproject.toml:432, 483, 518`) — must stay untouched; `all-fast`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `gdrive` extra + `all` self-ref |
| `packages/ai-parrot/tests/test_gdrive_extra.py` | CREATE | Parse-level tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml
msgraph = [ ... ]                     # :400-404 (pattern + comment at :399)
agents = [                            # :406  ← insert gdrive block before this
    "aiogoogle==5.17.0",              # :432 (also :483, :518 in other bundles) — DO NOT TOUCH
all = [                               # :886
    "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,reddit,mcp,charts,docling,visualizations,rust,msgraph]",   # :887
```
```python
# packages/ai-parrot/tests/test_msgraph_extra.py — shape to copy (PYPROJECT = parents[1] / "pyproject.toml"; tomllib)
```

### Does NOT Exist
- ~~`ai-parrot[gdrive]`~~ — created here. The existing `google` extra (`pyproject.toml:603`) is the GenAI client bundle, unrelated.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_gdrive_extra.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Insert the `gdrive` block before `agents = [` — *why*: mirrors `msgraph` placement.
2. Extend the `all` self-reference — *why*: G8 "included in `all`".
3. Write the test; record the dry-run log — *why*: AC17.

### `packages/ai-parrot/pyproject.toml` (MODIFY — new extra)
```toml
# occurrences: 1 (verified: grep -c '^agents = \[' packages/ai-parrot/pyproject.toml)
# BEFORE — insert above `agents = [` (verified: pyproject.toml:406), after the blank line closing msgraph
# Google Drive file manager + toolkit — FEAT-608. The agents bundles keep their own aiogoogle==5.17.0 pin.
gdrive = [
    "aiogoogle>=5.17,<6",
    "aiofiles>=23.0",
]

```

### `packages/ai-parrot/pyproject.toml` (MODIFY — all)
```toml
# occurrences: 1 (verified: grep -c 'rust,msgraph\]",' packages/ai-parrot/pyproject.toml)
# REPLACE pyproject.toml:887 with:
    "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,reddit,mcp,charts,docling,visualizations,rust,msgraph,gdrive]",
```

### `packages/ai-parrot/tests/test_gdrive_extra.py` (CREATE)
```python
"""FEAT-608 TASK-3809 — the gdrive extra exists and is part of `all`."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _extras() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["optional-dependencies"]


def test_gdrive_extra_present_and_in_all():
    extras = _extras()
    assert extras["gdrive"] == ["aiogoogle>=5.17,<6", "aiofiles>=23.0"]
    self_ref = next(e for e in extras["all"] if e.startswith("ai-parrot["))
    assert "gdrive" in self_ref[len("ai-parrot[") : -1].split(",")


def test_agents_extra_keeps_its_aiogoogle_pin():
    assert "aiogoogle==5.17.0" in _extras()["agents"]
```

### FILL IN checklist
- [ ] Dry-run resolution recorded in `artifacts/logs/FEAT-608-gdrive-extra.log` (git-ignored — `git add -f` only if the task owner wants it committed; otherwise quote it in the Completion Note).

---

## Acceptance Criteria

- [ ] AC17 (extra present, in `all`, agents pins untouched, resolution recorded).
- [ ] `test_msgraph_extra.py` still passes.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_gdrive_extra.py -q`
- `pytest packages/ai-parrot/tests/test_msgraph_extra.py -q`

---

## Agent Instructions
Standard. Do not run `uv sync` / `uv lock` in the worktree.

---

## Completion Note

*(Agent fills this in when done)*
