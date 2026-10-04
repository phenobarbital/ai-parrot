# TASK-3819: Docs — `gdrive-filemanager.md` + `google-oauth2.md`

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3816
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (docs half; AC19). Written last so it documents the names that actually
landed (manager, toolkit, extra).

---

## Scope

- Create `docs/interfaces/gdrive-filemanager.md` in the `docs/interfaces/graph-filemanager.md`
  shape with sections: **Install · Quick start · Authentication · Paths · Uploads and downloads ·
  Sharing links · Batch operations · Search · Serving over HTTP · Agents**. Must mention the
  `serving_max_bytes` limit (64 MiB default, 413) and "no Workspace export in v1".
- Create `docs/integrations/google-oauth2.md`: service account vs OAuth user vs cached modes,
  scopes (`DEFAULT_SCOPES["drive"]`), shared-drive membership for service accounts (and the
  SA My Drive quota caveat), `GOOGLE_CREDENTIALS_FILE`, cached-session files / Redis
  (`REDIS_HISTORY_URL` soft requirement).
- Create `packages/ai-parrot/tests/test_gdrive_docs.py` asserting both files exist with the
  required section headings and phrases (makes AC19 checkable).

**NOT in scope**: README/index edits beyond what already links docs automatically.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/interfaces/gdrive-filemanager.md` | CREATE | Manager + toolkit guide |
| `docs/integrations/google-oauth2.md` | CREATE | Auth setup guide |
| `packages/ai-parrot/tests/test_gdrive_docs.py` | CREATE | Doc structure test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```text
docs/interfaces/graph-filemanager.md        — shape to follow
docs/integrations/office365-oauth2.md       — shape to follow for the auth page
parrot.conf.GOOGLE_CREDENTIALS_FILE         — conf.py:434-436
parrot.interfaces.google.DEFAULT_SCOPES     — google.py:40-47
```
Names to document come from the landed code: `GoogleDriveFileManager` constructor
(TASK-3810), `create_sharing_link` (TASK-3813), `upload_files`/`download_files`/`setup`
(TASK-3814), `FileManagerToolkit(manager_type="gdrive")` (TASK-3815), `GoogleDriveToolkit`
(TASK-3816), `ai-parrot[gdrive]` (TASK-3809). Read them; do not invent kwargs.

### Does NOT Exist
- ~~`export_file` / Workspace export~~ — document as not supported in v1.
- ~~domain-wide delegation (`subject=`)~~ — document as out of scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/interfaces/gdrive-filemanager.md", "action": "CREATE"},
    {"path": "docs/integrations/google-oauth2.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/test_gdrive_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read `graph-filemanager.md` / `office365-oauth2.md` — *why*: consistent doc shape.
2. Write both docs with runnable snippets from the spec §2 New Public Interfaces block — *why*: AC19.
3. Write the structure test.

### `packages/ai-parrot/tests/test_gdrive_docs.py` (CREATE)
```python
"""FEAT-608 TASK-3819 — the Drive docs exist with the required sections (AC19)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FM_DOC = ROOT / "docs/interfaces/gdrive-filemanager.md"
AUTH_DOC = ROOT / "docs/integrations/google-oauth2.md"
SECTIONS = ("Install", "Quick start", "Authentication", "Paths", "Uploads and downloads", "Sharing links",
            "Batch operations", "Search", "Serving over HTTP", "Agents")


def test_filemanager_doc_sections():
    text = FM_DOC.read_text(encoding="utf-8")
    for section in SECTIONS:
        assert f"## {section}" in text, section
    assert "serving_max_bytes" in text
    # FILL IN: assert the "no Workspace export" note is present (choose the exact phrase you write)


def test_oauth_doc_mentions_credentials_and_shared_drives():
    text = AUTH_DOC.read_text(encoding="utf-8")
    for needle in ("GOOGLE_CREDENTIALS_FILE", "service_account", "cached", "shared drive"):
        assert needle in text, needle
```

### FILL IN checklist
- [ ] Both docs' content.
- [ ] Workspace-export assertion.

---

## Acceptance Criteria

- [ ] AC19.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_gdrive_docs.py -q`

---

## Agent Instructions
Standard.

---

## Completion Note

*(Agent fills this in when done)*
