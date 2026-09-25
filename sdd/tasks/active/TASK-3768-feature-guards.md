# TASK-3768: Feature guards — no httpx / no tools import in core, byte-identical files, signature snapshot, _srcfiles

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3754, TASK-3760, TASK-3762, TASK-3764, TASK-3756, TASK-3757
**Assigned-to**: unassigned

---

## Context

Spec AC4 (no change to `SharepointClient`), AC13 (Delta classes and `delta.py` byte-identical), AC15 (no httpx /
requests / langchain / print in new code), AC19 (no breaking signature change) and AC23 (`_srcfiles` stays empty after
every operation). These are cross-cutting invariants, so they are asserted once, at the end, in one guard module that
depends on every task that could break them.

**Deterministic baselines, computed at `/sdd-task` time against base commit `a6971f381`** (code identical to
`8da1f45c3`):

| Guarded block / file | SHA-256 |
|---|---|
| `parrot_tools/o365/sharepoint.py::DeltaSharePointFilesArgs` (class source segment) | `ad0ee3f2822201677f421527d9e9a56daaeb149e2911b79af8a1ce488e3f752c` |
| `parrot_tools/o365/sharepoint.py::DeltaSharePointFilesTool` | `41f6aa8e58cdcf5d3c6f5973c1940c93a106c6334b3e4982d9c862387f54b704` |
| `parrot_tools/o365/onedrive.py::DeltaOneDriveFilesArgs` | `d5d71031daa34a37622c0f1c81f66af9fb729fe949d680a5921c0b22e570baa0` |
| `parrot_tools/o365/onedrive.py::DeltaOneDriveFilesTool` | `433525bb7d5c177b22bb1af208d2073d21de3b938474aa6f3b22c4c2893ae005` |
| `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py` (file) | `cdb321b8196e4e097e284d94c9cfb2486dd9f1020af93affa25b6eba6c1022f6` |
| `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py` (file) | `c6c82feb0fee7401b7f6c99ce93e8c8807f7381b8ab3bf0d4092eb3d6354bb4f` |
| `packages/ai-parrot-tools/src/parrot_tools/o365/base.py` (file) | `fd8c5b95d90eaf5d014bbf985b40756899e7443ca936d6cb5b744d383c61f4bb` |
| `packages/ai-parrot/src/parrot/interfaces/sharepoint.py` (file) | `d65e397bac117f528942503870317c16a2a18dedf940ba7c6cb042c03c264e1d` |
| `packages/ai-parrot/src/parrot/interfaces/o365.py` (file) | `2a1c94ea77fb8f26bb655b90e173b95359f33cb49087dd1c43a42f8ead480aef` |

Class-segment hashes are `sha256(ast.get_source_segment(src, classdef).encode())`. If a hash differs at execution time,
STOP: either another feature legitimately changed that file on `dev` after `a6971f381` (then re-baseline from
`git show origin/dev:<path>` and record it in the Completion Note), or a FEAT-603 task broke the invariant (then fix
that task's change, not the hash).

---

## Scope

- Create `packages/ai-parrot/tests/interfaces/feat603_signature_snapshot.json` by running the generator below against
  `git show a6971f381:<path>` (NOT the working tree).
- Create `packages/ai-parrot/tests/interfaces/test_feat603_guards.py`.

**NOT in scope**: fixing violations in other tasks' code beyond what a failing guard points at.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/feat603_signature_snapshot.json` | CREATE | public-signature baseline (generated) |
| `packages/ai-parrot/tests/interfaces/test_feat603_guards.py` | CREATE | invariant tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `a6971f381`.

### Verified Imports
```python
import ast, hashlib, json, pathlib    # stdlib
from ._graph_fakes import FakeDrive, FakeGraphClient, FakeAiohttpSession, make_sharepoint_client   # TASK-3748
from parrot.interfaces.file.sharepoint import SharePointFileManager                               # TASK-3756
```

### Existing Signatures to Use
```text
Snapshot scope (public methods + __init__; 76 entries at a6971f381):
  packages/ai-parrot/src/parrot/interfaces/sharepoint.py      SharepointClient
  packages/ai-parrot/src/parrot/interfaces/onedrive.py        OneDriveClient
  packages/ai-parrot/src/parrot/interfaces/o365.py            O365Client
  packages/ai-parrot/src/parrot/tools/filemanager.py          FileManagerFactory, FileManagerTool, FileManagerToolkit
  packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py    SharePointToolkit, OneDriveToolkit, Office365FileManagementToolkit
Shape per method = [name, kind(pos|var|kwonly|varkw), default-source-or-null] for every parameter (annotations are NOT
compared: TASK-3758 legitimately changes `Literal[...]` to `ManagerType`).
New modules scanned for banned imports: packages/ai-parrot/src/parrot/interfaces/file/{graph,batch,sharepoint,onedrive}.py
```

### Does NOT Exist
- ~~a signature snapshot fixture in the repo~~ — created by this task from the base commit.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/interfaces/feat603_signature_snapshot.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_feat603_guards.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- **Snapshot generator** (run once from the repo/worktree root; writes the JSON fixture):
  ```python
  import ast, json, subprocess
  BASE = "a6971f381"
  TARGETS = {
      "packages/ai-parrot/src/parrot/interfaces/sharepoint.py": ["SharepointClient"],
      "packages/ai-parrot/src/parrot/interfaces/onedrive.py": ["OneDriveClient"],
      "packages/ai-parrot/src/parrot/interfaces/o365.py": ["O365Client"],
      "packages/ai-parrot/src/parrot/tools/filemanager.py": ["FileManagerFactory", "FileManagerTool", "FileManagerToolkit"],
      "packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py": ["SharePointToolkit", "OneDriveToolkit",
                                                                  "Office365FileManagementToolkit"],
  }
  def shape(fn):
      a = fn.args; pos = a.posonlyargs + a.args
      defs = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
      out = [[p.arg, "pos", ast.unparse(d) if d is not None else None] for p, d in zip(pos, defs)]
      if a.vararg: out.append([a.vararg.arg, "var", None])
      out += [[p.arg, "kwonly", ast.unparse(d) if d is not None else None] for p, d in zip(a.kwonlyargs, a.kw_defaults)]
      if a.kwarg: out.append([a.kwarg.arg, "varkw", None])
      return out
  snap = {}
  for path, classes in TARGETS.items():
      src = subprocess.check_output(["git", "show", f"{BASE}:{path}"]).decode()
      for node in ast.parse(src).body:
          if isinstance(node, ast.ClassDef) and node.name in classes:
              for item in node.body:
                  if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                      not item.name.startswith("_") or item.name == "__init__"):
                      snap[f"{path}::{node.name}.{item.name}"] = shape(item)
  json.dump({"base_commit": BASE, "signatures": snap}, open(
      "packages/ai-parrot/tests/interfaces/feat603_signature_snapshot.json", "w"), indent=1, sort_keys=True)
  ```
  Expect 76 entries. The test re-computes shapes from the WORKING TREE with the same `shape()` and asserts every
  snapshot key still exists with an identical shape (new methods are allowed; removed/changed ones fail).
- **Banned-import scan**: AST-walk the four new modules; fail on any `Import`/`ImportFrom` of `httpx`, `requests`,
  `langchain*`, or `parrot_tools*`, and on any call to the builtin `print`.
- **`_srcfiles` guard (AC23)**: a SharePoint manager adopting `make_sharepoint_client(fake)` runs list_files,
  list_entries, find_files, upload_file, download_file, copy_file, rename_file, delete_file (with a
  `FakeAiohttpSession` installed); after each call `client._srcfiles == []`.
- Paths in the test resolve from `pathlib.Path(__file__).resolve().parents[4]` (repo root:
  tests/interfaces → tests → ai-parrot → packages → root).

### Key Constraints (all FEAT-603 tasks)
- **aiohttp only** for raw HTTP. `httpx`, `requests`, `langchain*` are banned (ruff TID251). The two legacy
  clients carry an unused `import httpx` (`interfaces/sharepoint.py:11`, `interfaces/onedrive.py:10`) — never copy
  their import blocks into new code.
- **Core never imports the tools distribution**: nothing under `packages/ai-parrot/src/parrot/` may import
  `parrot_tools` (the retry helpers of `parrot_tools/o365/delta.py` are *re-implemented*, not imported).
- Pydantic v2 models; Google-style docstrings and strict type hints on every function/class; `self.logger`
  (or a module `logger = logging.getLogger(__name__)`), never `print`; `black` line length 120; `ruff check` clean.
- **Never log** upload-session `uploadUrl`s, copy monitor URLs, `@microsoft.graph.downloadUrl`s, tokens or secrets.
- **Byte-identical files** (no edit, ever, in this feature): `packages/ai-parrot/src/parrot/interfaces/sharepoint.py`,
  `packages/ai-parrot/src/parrot/interfaces/o365.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`,
  `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`,
  and the `Delta*Args` / `Delta*Tool` class blocks inside `parrot_tools/o365/{sharepoint,onedrive}.py` (FEAT-539).
- Tests never construct a real `O365Client` / `SharepointClient` / `OneDriveClient` (their `__init__` builds an
  aioredis client, `o365.py:198-200`) — use the fakes of TASK-3748 and `GraphDriveFileManager.adopt_client`.
- Tests are async with `asyncio_mode = auto` (`pytest.ini:3`); the `live` marker is registered (`pytest.ini:6`).
- **Worktree testing**: the shared `.venv` is editable-installed against the MAIN checkout, so run
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src timeout -s KILL 600 pytest <file> -q`.
  Never `uv sync` inside a worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Run the snapshot generator; commit the JSON — *why*: the baseline must come from the base commit, not the edited tree.
2. Write the guard tests.

### `packages/ai-parrot/tests/interfaces/test_feat603_guards.py` (CREATE)
```python
"""FEAT-603 TASK-3768 — cross-cutting invariants (AC4, AC13, AC15, AC19, AC23)."""
import ast
import hashlib
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
SNAPSHOT = pathlib.Path(__file__).with_name("feat603_signature_snapshot.json")
NEW_MODULES = [ROOT / "packages/ai-parrot/src/parrot/interfaces/file" / f"{n}.py"
               for n in ("graph", "batch", "sharepoint", "onedrive")]
FILE_HASHES = {
    "packages/ai-parrot-tools/src/parrot_tools/o365/delta.py": "cdb321b8196e4e097e284d94c9cfb2486dd9f1020af93affa25b6eba6c1022f6",
    "packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py": "c6c82feb0fee7401b7f6c99ce93e8c8807f7381b8ab3bf0d4092eb3d6354bb4f",
    "packages/ai-parrot-tools/src/parrot_tools/o365/base.py": "fd8c5b95d90eaf5d014bbf985b40756899e7443ca936d6cb5b744d383c61f4bb",
    "packages/ai-parrot/src/parrot/interfaces/sharepoint.py": "d65e397bac117f528942503870317c16a2a18dedf940ba7c6cb042c03c264e1d",
    "packages/ai-parrot/src/parrot/interfaces/o365.py": "2a1c94ea77fb8f26bb655b90e173b95359f33cb49087dd1c43a42f8ead480aef",
}
CLASS_HASHES = {
    ("packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py", "DeltaSharePointFilesArgs"): "ad0ee3f2822201677f421527d9e9a56daaeb149e2911b79af8a1ce488e3f752c",
    ("packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py", "DeltaSharePointFilesTool"): "41f6aa8e58cdcf5d3c6f5973c1940c93a106c6334b3e4982d9c862387f54b704",
    ("packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py", "DeltaOneDriveFilesArgs"): "d5d71031daa34a37622c0f1c81f66af9fb729fe949d680a5921c0b22e570baa0",
    ("packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py", "DeltaOneDriveFilesTool"): "433525bb7d5c177b22bb1af208d2073d21de3b938474aa6f3b22c4c2893ae005",
}


@pytest.mark.parametrize("rel,digest", sorted(FILE_HASHES.items()))
def test_protected_files_byte_identical(rel, digest):
    assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel


@pytest.mark.parametrize("key,digest", sorted(CLASS_HASHES.items()))
def test_delta_class_blocks_unchanged(key, digest):
    rel, cls = key
    src = (ROOT / rel).read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls)
    assert hashlib.sha256(ast.get_source_segment(src, node).encode()).hexdigest() == digest, cls


@pytest.mark.parametrize("module", NEW_MODULES, ids=lambda p: p.name)
def test_no_banned_imports_or_print_in_new_modules(module):
    # FILL IN: rule in Implementation Notes


def test_public_signatures_unchanged():
    # FILL IN: load SNAPSHOT; recompute shapes from the working tree with the generator's shape(); every key present & equal


async def test_sharepoint_manager_never_populates_srcfiles_across_operations():
    # FILL IN: rule in Implementation Notes (AC23)
```

### FILL IN checklist
- [ ] run the generator; fixture has 76 entries and `base_commit: a6971f381`
- [ ] the three FILL IN test bodies

---

## Acceptance Criteria

- [ ] `interfaces/sharepoint.py`, `interfaces/o365.py`, `o365/delta.py`, `o365/bundle.py`, `o365/base.py` are
      byte-identical to the base; the four Delta class blocks unchanged (spec AC4, AC13).
- [ ] No `httpx` / `requests` / `langchain*` / `parrot_tools` import and no `print(` in the four new core modules (AC15).
- [ ] Every public method in the snapshot keeps its parameter shape (AC19).
- [ ] `_srcfiles` stays empty across every SharePoint manager operation (AC23).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_feat603_guards.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_protected_files_byte_identical` | AC4, AC13 |
| `test_delta_class_blocks_unchanged` | AC13 |
| `test_no_banned_imports_or_print_in_new_modules` | AC15 |
| `test_public_signatures_unchanged` | AC19 |
| `test_sharepoint_manager_never_populates_srcfiles_across_operations` | AC23 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/sharepoint-filemanager.spec.md` (§2, the §3 module named in Context, §6, §7).
2. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/sharepoint-filemanager.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still resolves (`grep` or `read` the source).
   - Re-run the `grep -c` of every MODIFY anchor in the blueprint; a changed count means the anchor moved —
     re-locate it; a count of `0` means STOP and report drift.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/sharepoint-filemanager.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, and never
   change a signature, class name or file path the blueprint fixes.
6. **Verify** every acceptance criterion and run every Validation Command (plus `ruff check` on touched files).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
