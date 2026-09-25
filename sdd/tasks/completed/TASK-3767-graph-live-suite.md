# TASK-3767: Opt-in live suite against a real tenant (SharePoint + OneDrive round trips)

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3754, TASK-3756, TASK-3757
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10**, §4 Integration Tests, AC18. Mocked tests cannot prove Graph path encoding, upload-session limits,
copy monitors or tenant sharing policy; this suite does, against a real tenant, **only** when the owner opts in. It is
skipped by default (CI and every other task see only skips). The owner runs it once before `/sdd-done` and saves the
output to `artifacts/logs/FEAT-603-live.log`; a skipped run is reported as skipped, never as a pass (AC18).

**Exclusive task** (`parallel: false`): a live run shares one real tenant; writing the file is harmless, but the task's
own manual verification must not overlap another run.

Open question spec §8 **Q1** (which site/library/user the suite may write to) is resolved at run time by the owner
through the knobs below — the suite never has defaults for targets.

---

## Scope

- Create `packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py` with the four `@pytest.mark.live` tests
  from spec §4, gated on the env knobs, writing only under `parrot-live/<uuid4>/` and deleting it at teardown.

**NOT in scope**: CI wiring (the suite never runs in CI); `parrot.conf` settings (the knobs are test-only env vars).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py` | CREATE | opt-in live suite |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.file.sharepoint import SharePointFileManager   # TASK-3756
from parrot.interfaces.file.onedrive import OneDriveFileManager       # TASK-3757
import pytest                                                         # marker `live` registered: pytest.ini:6
```

### Existing Signatures to Use
```python
# Credentials come from the existing settings (parrot/conf.py): SHAREPOINT_APP_ID / SHAREPOINT_APP_SECRET /
#   SHAREPOINT_TENANT_ID / SHAREPOINT_TENANT_NAME (:612-615) are the SharepointClient defaults (interfaces/sharepoint.py:44-47);
#   O365_CLIENT_ID / O365_CLIENT_SECRET / O365_TENANT_ID (:598-600) are the OneDriveClient defaults (o365.py:188-191).
#   Passing credentials=None lets the clients use those defaults.
# Manager API (TASK-3749..3754): async with manager; create_file, upload_file, exists, get_file_metadata, list_files,
#   find_files, get_file_url, download_file, copy_file, rename_file, delete_file, remove_folder, upload_files, download_files
```

### Does NOT Exist
- ~~`PARROT_LIVE_*` settings in `parrot/conf.py`~~ — read with `os.environ` only.
- ~~default live targets~~ — every target comes from a knob; no knob → skip.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Knobs: `PARROT_LIVE_GRAPH=1` (master switch), `PARROT_LIVE_SHAREPOINT_SITE`, `PARROT_LIVE_SHAREPOINT_LIBRARY`
  (default `Documents`), `PARROT_LIVE_ONEDRIVE_USER`. SharePoint tests skip unless the switch and the site are set;
  OneDrive tests skip unless the switch and the user are set. The skip reason names the missing knob.
- Every test works under `prefix=f"parrot-live/{uuid4().hex}/"` and its fixture teardown calls
  `remove_folder("")`-equivalent cleanup of that prefix folder (FILL IN: `remove_folder` on the prefixed root — bounded by
  "never delete outside the run folder"), then `close()`.
- Large-file test: 12 MiB of `os.urandom` bytes to force the upload session; assert round-trip equality by SHA-256.
- Batch test: 12 small files, `max_concurrency=3`; all `state == "succeeded"`, order preserved.
- Owner command (documented in TASK-3766's "Live tests" section):
  ```bash
  PARROT_LIVE_GRAPH=1 PARROT_LIVE_SHAREPOINT_SITE=<site> PARROT_LIVE_ONEDRIVE_USER=<upn> \
    pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py -m live -v \
    2>&1 | tee artifacts/logs/FEAT-603-live.log
  ```

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
1. Write the gating helpers and fixtures — *why*: default runs must skip cleanly.
2. Write the four tests.
3. Run the file with no knobs (must report 4 skipped) — the task's Validation Command.

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py` (CREATE)
```python
"""FEAT-603 TASK-3767 — opt-in live round trips against a real tenant (skipped unless PARROT_LIVE_GRAPH=1)."""
import hashlib
import io
import os
import uuid

import pytest

pytestmark = pytest.mark.live


def _need(*names: str) -> None:
    if os.environ.get("PARROT_LIVE_GRAPH") != "1":
        pytest.skip("set PARROT_LIVE_GRAPH=1 to run live Graph tests")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"missing live knob(s): {', '.join(missing)}")


@pytest.fixture
async def sp():
    _need("PARROT_LIVE_SHAREPOINT_SITE")
    from parrot.interfaces.file.sharepoint import SharePointFileManager

    m = SharePointFileManager(
        site=os.environ["PARROT_LIVE_SHAREPOINT_SITE"],
        library=os.environ.get("PARROT_LIVE_SHAREPOINT_LIBRARY", "Documents"),
        prefix=f"parrot-live/{uuid.uuid4().hex}/",
    )
    async with m:
        yield m
        # FILL IN: remove the run folder only (never outside the prefix)


@pytest.fixture
async def od():
    _need("PARROT_LIVE_ONEDRIVE_USER")
    # FILL IN: OneDriveFileManager(user=os.environ["PARROT_LIVE_ONEDRIVE_USER"], prefix=...) — same lifecycle as `sp`


async def test_live_sharepoint_roundtrip(sp):
    # FILL IN: create_file -> exists -> get_file_metadata -> list_files -> find_files -> get_file_url (https) ->
    #          download_file(BytesIO) equals -> copy_file -> rename_file -> delete_file


async def test_live_onedrive_user_roundtrip(od):
    # FILL IN: same sequence on OneDrive (app-only, user=UPN)


async def test_live_batch_upload_download(sp):
    # FILL IN: 12 files, max_concurrency=3 (set on the manager), all succeeded, order preserved, downloads equal


async def test_live_large_upload_session(sp):
    # FILL IN: 12 MiB random bytes -> upload -> download -> sha256 equal
```

### FILL IN checklist
- [ ] fixture teardown (run-folder cleanup) and the `od` fixture
- [ ] the four test bodies

---

## Acceptance Criteria

- [ ] With no knobs the file reports 4 skipped and no failures (safe in CI).
- [ ] With knobs set, the suite exercises every operation of spec §4 Integration Tests and cleans up its run folder.
- [ ] The Completion Note states whether the owner run happened; a skipped run is recorded as skipped (spec AC18).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_live_sharepoint_roundtrip` | full op sequence, SharePoint |
| `test_live_onedrive_user_roundtrip` | full op sequence, OneDrive app-only |
| `test_live_batch_upload_download` | batch semantics on a real tenant |
| `test_live_large_upload_session` | upload session path |

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


- Task: TASK-3767
- Feature: sharepoint-filemanager
- Implementation SHA: 7be7a2d8077a6fcf1a7f7767d833593fd68799cd
- Closed at (UTC): 2026-09-25T20:59:40+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: haiku (native) · Backend: native · Model: haiku · Attempts: 1 · Duration: n/a · Tokens: n/a |
| validation_note | Opt-in live suite, skipped by default (AC18): pytest test_graph_filemanager_live.py -q -> 4 skipped (no PARROT_LIVE_GRAPH set), never reported as a pass. Only file created matches Files to Create/Modify exactly. |
