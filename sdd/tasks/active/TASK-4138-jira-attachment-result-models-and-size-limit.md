# TASK-4138: Jira attachments — typed result envelope, error codes and discovered size limit

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models and §3 Module 3, first slice. This task adds **only new code** —
no existing tool changes behaviour yet — so it can land safely while the rest of M3
is still being written.

Two spec decisions are realised here. The result envelope is shared by both
attachment-bearing tools, which today return different shapes (design research S7).
And the attachment size limit is **discovered from the live deployment** via
`jira.JIRA.attachment_meta()` rather than hard-coded, which is what made the
Cloud-vs-DC question moot (spec §8 Q2).

---

## Scope

- Add `AttachmentErrorCode`, `AttachmentResult`, `JiraAttachmentReport` and
  `JiraCommentReport` exactly as spec §2 Data Models fixes them.
- Add a `_bounded_detail()` helper: collapse newlines, cap at 500 characters.
- Add `JiraToolkit._max_attachment_bytes()`: `JIRA_MAX_ATTACHMENT_BYTES` when set,
  else `attachment_meta()["uploadLimit"]`, else a 10 MB fallback with a WARNING.
  Cache the discovered value per client.
- Write tests for the models, the detail bounding and all three limit branches.

**NOT in scope**: `_attach_session_files` (TASK-4139) · either tool's signature
(TASK-4140 / TASK-4141) · touching `AddAttachmentInput` or `AddCommentInput`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Result models, error codes, detail bounding, limit discovery |
| `packages/ai-parrot-tools/tests/unit/test_jira_attachment_models.py` | CREATE | Models + limit-resolution tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified against `1f74e23c7` on 2026-10-08, **after FEAT-637 merged**.
> Every one of them drifted from the spec's original §6 values — re-verify before editing.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # re-exported: jiratoolkit.py:55
from parrot.tools.decorators import tool_schema, requires_permission  # re-exported: jiratoolkit.py:56
from pydantic import BaseModel, Field                     # jiratoolkit.py:37
# already imported at jiratoolkit.py:29-57: asyncio, os, logging, typing
#   (Any, Dict, List, Optional, Sequence, Union, Literal, TypedDict)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (verified 1f74e23c7)
class AddAttachmentInput(BaseModel):                                   # line 389
class AddCommentInput(BaseModel):                                      # line 507
class JiraToolkit(AbstractToolkit):
    def _init_jira_client(self) -> JIRA                                # resolves self.jira
    def _cfg(self, key: str)                                           # existing config helper
    #  self.logger is provided by AbstractToolkit

# .venv/lib/python3.12/site-packages/jira/client.py  (jira==3.10.5)
def attachment_meta(self) -> dict[str, int]:                           # line 1110
    """GET attachment/meta -> {"enabled": bool, "uploadLimit": int}."""  # line 1116
self.deploymentType = None                                             # line 658
    self.deploymentType = si.get("deploymentType")                     # line 667
@property
def _is_cloud(self) -> bool: return self.deploymentType in ("Cloud",)  # lines 702-704
```

### Does NOT Exist
- ~~any Jira attachment-size constant or config key in this repo~~ — none today; this
  task introduces the resolution, and it is **discovery + override**, never a constant
- ~~`JIRA.max_attachment_size` / `JIRA.upload_limit`~~ — the only source is
  `attachment_meta()["uploadLimit"]` (`jira/client.py:1110`)
- ~~a `quota_exceeded` error code~~ — the session quota only reports (spec AC16); it is
  not part of `AttachmentErrorCode`
- ~~`self.jira` being always present~~ — it is `None` on the `oauth2_3lo` path and
  resolved per call in `_pre_execute`; `_max_attachment_bytes` must tolerate that and
  fall back rather than raise

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jira_attachment_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#AddAttachmentInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#AddCommentInput"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `attachment_meta()` is a blocking HTTP call — wrap it in `asyncio.to_thread`.
- Discovery must never raise: any failure logs a WARNING and returns the fallback.
- Cache per client instance, not per toolkit: `self.jira` can be rebound per call.

---

## Implementation Blueprint

### Steps (in order)
1. Add the models near the other input models — *why*: they are the contract TASK-4139
   through TASK-4141 all import; defining them first stops the shape drifting.
2. Add `_bounded_detail` as a module function — *why*: it is pure and must be testable
   without a toolkit instance.
3. Add `_max_attachment_bytes` with the three branches — *why*: AC9 tests each one.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class AddAttachmentInput(BaseModel):' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# BEFORE — insert above `class AddAttachmentInput(BaseModel):` (verified: jiratoolkit.py:389)
#: Default pre-flight limit used only when discovery fails.
DEFAULT_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
#: Maximum characters of Jira diagnostic text returned to the model.
MAX_ATTACHMENT_DETAIL_CHARS = 500

AttachmentErrorCode = Literal[
    "unknown_handle", "no_session", "outside_sandbox", "missing_file",
    "empty_file", "too_large", "forbidden", "rejected", "transport_error",
]


def _bounded_detail(text: Any) -> str:
    """Collapse *text* to one bounded line safe to hand back to the model.

    A Jira error body can be a multi-kilobyte HTML page; `error_code` is the stable
    signal, this is only for a human reading the transcript.
    """
    # FILL IN: str(text), collapse all whitespace runs to single spaces, strip, and
    # truncate to MAX_ATTACHMENT_DETAIL_CHARS with a trailing ellipsis when cut
    # — bounded by AC10 (<= 500 chars, never a raw body)
    raise NotImplementedError


class AttachmentResult(BaseModel):
    """Outcome for exactly ONE input handle. One entry per input, order preserved."""

    file_id: str
    ok: bool
    filename: Optional[str] = None
    attachment_id: Optional[str] = None
    size: Optional[int] = None
    error_code: Optional[AttachmentErrorCode] = None
    detail: Optional[str] = None


class JiraAttachmentReport(BaseModel):
    """Shared envelope returned by BOTH attachment-bearing tools."""

    issue: str
    attachments: List[AttachmentResult]
    attached: int
    failed: int


class JiraCommentReport(BaseModel):
    """jira_add_comment result — comment and attachment outcomes are INDEPENDENT."""

    issue: str
    comment: Dict[str, Any]
    comment_ok: bool
    attachments: List[AttachmentResult]
    attached: int
    failed: int
```
**Why this shape**: the `AttachmentErrorCode` literals are exactly the `code` strings
`SessionFileStore` raises (TASK-4128), so TASK-4139's mapping is a pass-through.
`JiraCommentReport` keeps `comment_ok` separate from the attachment counts because Jira
offers no rollback — spec §7. Do not merge the two report models into one.

```python
# occurrences: 1 (verified: grep -c '    def _set_jira_client(self):' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# BEFORE — insert above `def _set_jira_client(self):` on JiraToolkit
    async def _max_attachment_bytes(self) -> int:
        """Resolve this deployment's attachment size limit, cached per client.

        JIRA_MAX_ATTACHMENT_BYTES wins when set. Otherwise asks the live deployment
        via self.jira.attachment_meta()["uploadLimit"] (verified: jira/client.py:1110),
        which is correct for Cloud and Server/DC alike. A failed or malformed probe
        logs a WARNING and falls back to DEFAULT_MAX_ATTACHMENT_BYTES. Never raises.
        """
        # FILL IN: 1) self._cfg("JIRA_MAX_ATTACHMENT_BYTES") -> int when set and > 0;
        # 2) cache keyed on id(self.jira) so a rebound client re-probes; 3) probe via
        # asyncio.to_thread(self.jira.attachment_meta) and read "uploadLimit";
        # 4) any exception, missing key, or self.jira is None -> WARNING + default.
        # bounded by AC9 (discovery + override, never a constant) and "never raises"
        raise NotImplementedError
```
**Why**: the override is checked first so an operator can be stricter than the server.
Keying the cache on the client identity matters because `self.jira` is `None` on the
`oauth2_3lo` path and rebound per call — a toolkit-level cache would serve one tenant's
limit to another.

### FILL IN checklist
- [ ] `_bounded_detail` — collapsing and truncation; bounded by AC10
- [ ] `_max_attachment_bytes` — three branches + caching; bounded by AC9 and "never raises"
- [ ] test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `AttachmentResult`, `JiraAttachmentReport`, `JiraCommentReport` import and validate
- [ ] `_bounded_detail` output is <= 500 characters and single-line for a 50 KB HTML input (spec AC10)
- [ ] `JIRA_MAX_ATTACHMENT_BYTES` set -> used, and `attachment_meta` is NOT called
- [ ] Unset -> `attachment_meta()["uploadLimit"]` is used (spec AC9)
- [ ] A probe that raises -> WARNING logged and the 10 MB fallback returned, no exception
- [ ] `self.jira is None` -> fallback, no exception
- [ ] No existing tool's behaviour changes in this task
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_attachment_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/unit/test_jira_attachment_models.py
import pytest
from parrot_tools.jiratoolkit import (
    DEFAULT_MAX_ATTACHMENT_BYTES, AttachmentResult, JiraAttachmentReport,
    JiraCommentReport, _bounded_detail,
)


class TestBoundedDetail:
    def test_truncates_large_html(self):
        assert len(_bounded_detail("<html>" + "x" * 50000 + "</html>")) <= 500

    def test_collapses_newlines(self):
        assert "\n" not in _bounded_detail("a\nb\nc")


class TestMaxAttachmentBytes:
    async def test_config_override_wins(self):
        """JIRA_MAX_ATTACHMENT_BYTES set -> attachment_meta is never called."""
        # FILL IN

    async def test_discovers_upload_limit(self):
        """Spec AC9 — unset -> attachment_meta()["uploadLimit"]."""
        # FILL IN

    async def test_probe_failure_falls_back(self):
        """A raising probe logs a WARNING and returns the default."""
        # FILL IN: assert result == DEFAULT_MAX_ATTACHMENT_BYTES
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read spec §2 Data Models, §3 Module 3 and §6 before writing code.
3. **Verify the Codebase Contract** — `jiratoolkit.py` moves often (FEAT-637 shifted every
   anchor once already). Re-run each `grep -c` and correct the line numbers in this file
   FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4138 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
