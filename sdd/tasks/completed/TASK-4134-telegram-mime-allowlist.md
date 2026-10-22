# TASK-4134: Telegram crew — accept office documents in the MIME allowlist

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 and §6 "Does NOT Exist". The Telegram crew's document-exchange
allowlist defaults to csv, json, txt, png, jpeg, pdf and parquet
(`telegram/crew/payload.py:36-44`) — **`.docx` is not in it**, so a Word document is
refused on that channel before any of FEAT-639's machinery is reached.

This task is independent of the store: it only widens a list of MIME strings, so it
has no dependencies and can run in the first wave.

---

## Scope

- Extend the default `allowed_mime_types` with the Office Open XML and OpenDocument
  word-processing / spreadsheet / presentation types, plus legacy `application/msword`.
- Write a test asserting `validate_mime` accepts docx and still rejects an
  unlisted type.

**NOT in scope**: MS Teams (TASK-4135) · routing Telegram documents into the session
store · changing `max_file_size_mb` · the admin UI gate (deferred, `issue:04dcfd611ebc`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py` | MODIFY | Widen the default allowlist |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_crew_mime_allowlist.py` | CREATE | docx accepted, unlisted rejected |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py
    def __init__(self, temp_dir: str = "/tmp/parrot_crew",            # line 28
                 max_file_size_mb: int = 50,
                 allowed_mime_types: Optional[List[str]] = None) -> None:
        self.allowed_mime_types = allowed_mime_types or [             # line 36
            "text/csv", "application/json", "text/plain", "image/png",
            "image/jpeg", "application/pdf",
            "application/vnd.apache.parquet",                          # lines 37-44
        ]
    def validate_mime(self, mime_type: str) -> bool:                   # line 61
        return mime_type in self.allowed_mime_types
```

### Does NOT Exist
- ~~`.docx` anywhere in the current allowlist~~ — verified absent (`payload.py:37-44`)
- ~~an extension-based check~~ — `validate_mime` compares MIME strings exactly
  (`payload.py:61`), so adding `".docx"` would do nothing
- ~~a shared MIME constant for office types in this repo~~ — none; declare the list here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_crew_mime_allowlist.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Only the **default** changes. A caller passing `allowed_mime_types` explicitly keeps
  full control — do not merge the new types into a caller-supplied list.

---

## Implementation Blueprint

### Steps (in order)
1. Append the office MIME types to the default list literal — *why*: the exact-match
   check means every type must be spelled out.
2. Test both directions — *why*: widening a security-ish allowlist needs proof it did
   not become "accept everything".

### `.../telegram/crew/payload.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self.allowed_mime_types = allowed_mime_types or \[' packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py)
# AFTER — extend the default list literal that starts at `self.allowed_mime_types = allowed_mime_types or [`
#         (verified: telegram/crew/payload.py:36); keep the existing seven entries
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
            "application/msword",                                                       # .doc
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",# .pptx
            "application/vnd.oasis.opendocument.text",                                  # .odt
```
**Why**: these are the exact IANA types Telegram sends for Office attachments; `.docx`
is the one named in the bug report, the rest are the obvious siblings a user will try
next. `application/pdf` is already present — do not duplicate it.

### FILL IN checklist
- [ ] test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `validate_mime("application/vnd.openxmlformats-officedocument.wordprocessingml.document")` is `True` (spec AC14)
- [ ] `validate_mime("application/x-msdownload")` is still `False`
- [ ] An explicitly supplied `allowed_mime_types` is unchanged by this task
- [ ] `ruff check packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_crew_mime_allowlist.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_crew_mime_allowlist.py
import pytest

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TestCrewMimeAllowlist:
    def test_accepts_docx_by_default(self):
        """Spec AC14."""
        # FILL IN: build the payload manager with defaults, assert validate_mime(DOCX)

    def test_still_rejects_unlisted_type(self):
        # FILL IN: assert not validate_mime("application/x-msdownload")

    def test_explicit_allowlist_is_not_widened(self):
        """A caller-supplied list keeps full control."""
        # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read the spec sections named in Context before writing code.
3. **Verify the Codebase Contract** — confirm every import and signature still exists;
   if anything moved, fix the contract in this file FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4134 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any

## Completion Note

Implemented by the sdd-coder engine and merged; merge-tier sweep red only from pre-existing unrelated failures (ibkr/pulumi/scraping). Orchestrator fixed stale telegram mime-count test.
