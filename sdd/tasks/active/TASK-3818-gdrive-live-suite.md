# TASK-3818: Opt-in live Drive suite (`@pytest.mark.live`)

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3814
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (AC21). Round trips against a real Drive, skipped unless
`PARROT_LIVE_GDRIVE=1`. **Exclusive**: it writes to one shared real Drive. The test code is
written and committed here; the **live run** is done once by the owner (spec §8 Q1 — the
target folder / shared drive is still to be confirmed). A skipped run must be recorded as
skipped, never as a pass.

---

## Scope

- Create `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py` with the five
  tests in spec §3 M9, pattern `test_graph_filemanager_live.py:10-26`.
- All writes go under `parrot-live/<uuid4>/` and are deleted in a `finally` (permanent delete).
- Record the run (or the skip) in `artifacts/logs/FEAT-608-live.log` and the Completion Note.

**NOT in scope**: CI wiring; any source change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py` | CREATE | Live suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.file.gdrive import GoogleDriveFileManager     # TASK-3810..3814
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py:10-26 — env-gated skip pattern (pytestmark + skipif)
# GoogleDriveFileManager(root_id=, root_path=, shared_drive_id=, permanent_delete=, max_concurrency=,
#   small_file_threshold=, chunk_size=) ; connect/close; upload_file_from_bytes, exists, get_file_metadata,
#   list_files, find_files, get_file_url, download_file, copy_file, rename_file, delete_file,
#   upload_files, download_files, upload_file, create_sharing_link
# parrot.conf.GOOGLE_CREDENTIALS_FILE (conf.py:434-436) — used implicitly by GoogleClient when credentials=None
```

### Does NOT Exist
- ~~A `live` marker registration you must add~~ — check `pyproject.toml`/`pytest.ini` markers; FEAT-603's live suite already uses `pytest.mark.live`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the env gate and a `live_manager` async fixture — *why*: skip cleanly without knobs.
2. Write the five tests — *why*: AC21 evidence.
3. Run once without knobs (expect all skipped) and record it.

### `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py` (CREATE)
```python
"""FEAT-608 TASK-3818 — opt-in live Google Drive round trips (PARROT_LIVE_GDRIVE=1)."""
import io
import os
import sys
import uuid

import pytest

sys.modules.pop("parrot.interfaces.file", None)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("PARROT_LIVE_GDRIVE") != "1", reason="set PARROT_LIVE_GDRIVE=1 to run"),
]
ROOT_ID = os.getenv("PARROT_LIVE_GDRIVE_ROOT_ID")
ROOT_PATH = os.getenv("PARROT_LIVE_GDRIVE_ROOT_PATH")
SHARED_DRIVE = os.getenv("PARROT_LIVE_GDRIVE_SHARED_DRIVE")
SHARE_EMAIL = os.getenv("PARROT_LIVE_GDRIVE_SHARE_EMAIL")


def _manager(**kwargs):
    from parrot.interfaces.file.gdrive import GoogleDriveFileManager

    if not (ROOT_ID or ROOT_PATH):
        pytest.skip("PARROT_LIVE_GDRIVE_ROOT_ID or PARROT_LIVE_GDRIVE_ROOT_PATH is required")
    base = dict(root_id=ROOT_ID) if ROOT_ID else dict(root_path=ROOT_PATH)
    return GoogleDriveFileManager(**base, prefix=f"parrot-live/{uuid.uuid4().hex}/", permanent_delete=True, **kwargs)


async def test_live_roundtrip(): ...                 # FILL IN: upload bytes → exists → metadata → list → find → get_file_url
                                                     #   → download to BytesIO → copy → rename → delete; cleanup in finally
async def test_live_shared_drive_roundtrip(): ...    # FILL IN: skip without SHARED_DRIVE
async def test_live_batch_upload_download(): ...     # FILL IN: 12 files, max_concurrency=3, all ok, order preserved
async def test_live_large_resumable_upload(): ...    # FILL IN: 12 MiB → resumable (≥ 2 chunks at 8 MiB)
async def test_live_sharing_link_user_scope(): ...   # FILL IN: skip without SHARE_EMAIL; scope="user", expiry=3600
```

### FILL IN checklist
- [ ] Five tests with cleanup.
- [ ] Log file / Completion Note records "skipped (no knobs)" or the real run output.

---

## Acceptance Criteria

- [ ] Suite skips cleanly without `PARROT_LIVE_GDRIVE=1`.
- [ ] AC21: the owner's live run is recorded, or the skip is recorded as a skip.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py -q`

---

## Agent Instructions
Standard. Never mark AC21 as passed from a skipped run.

---

## Completion Note

*(Agent fills this in when done)*
