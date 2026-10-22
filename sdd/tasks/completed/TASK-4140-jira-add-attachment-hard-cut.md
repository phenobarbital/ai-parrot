# TASK-4140: `jira_add_attachment` — hard cut to session handles

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4139
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and AC5. `jira_add_attachment` today takes **one filesystem path**
(`attachment: str`, `jiratoolkit.py:2169`), which is precisely what the model cannot
produce for a chat upload — it hallucinates a path and gets `FileNotFoundError` from
`jira.JIRA.add_attachment` (`jira/client.py:1141`).

This task replaces that parameter with `file_ids` and routes the work through the
shared helper from TASK-4139, so the tool stops being a second, divergent code path.

The caller surface was measured on 2026-10-08: **no production code calls this tool**
— the only references are in `tests/test_jiratoolkit_permissions.py` (`:165-167` and
a name list at `:236`).

---

## Scope

- Replace `AddAttachmentInput.attachment: str` with `file_ids: List[str]`.
- Rewrite `jira_add_attachment(issue, file_ids)` to delegate to
  `_attach_session_files` and return a `JiraAttachmentReport` dict.
- Keep `@requires_permission("jira.write")` and `@tool_schema(AddAttachmentInput)`.
- Update `tests/test_jiratoolkit_permissions.py` for the new signature.
- Write tests for the tool's report shape.

**NOT in scope**: `jira_add_comment` (TASK-4141) · the helper (TASK-4139) · the models
(TASK-4138) · any compatibility shim for the old path parameter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Input schema + tool hard cut |
| `packages/ai-parrot/tests/test_jiratoolkit_permissions.py` | MODIFY | New signature in the write-permission test |
| `packages/ai-parrot-tools/tests/unit/test_jira_add_attachment_handles.py` | CREATE | Report-shape tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified against `1f74e23c7` on 2026-10-08, **after FEAT-637 merged**.
> Every one of them drifted from the spec's original §6 values — re-verify before editing.

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (verified 1f74e23c7)
class AddAttachmentInput(BaseModel):                                   # line 389
    issue: str = Field(description="Issue key or id")                  # line 392
    attachment: str = Field(description="Path to attachment file on disk")  # line 393

    @requires_permission("jira.write")                                 # line 2167
    @tool_schema(AddAttachmentInput)                                   # line 2168
    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]:  # line 2169
        def _run():
            return self.jira.add_attachment(issue=issue, attachment=attachment)   # line 2176
        await asyncio.to_thread(_run)                                  # line 2178
        return {"ok": True, "issue": issue, "attachment": attachment}  # line 2179

# from TASK-4138 / TASK-4139, in this same file:
    async def _attach_session_files(self, issue: str, file_ids: Sequence[str]) -> List[AttachmentResult]
class JiraAttachmentReport(BaseModel):
    issue: str; attachments: List[AttachmentResult]; attached: int; failed: int

# packages/ai-parrot/tests/test_jiratoolkit_permissions.py
    def test_jira_add_attachment_requires_write(self, toolkit):        # line 165
        method = getattr(toolkit, "jira_add_attachment", None)         # line 167
    #  "jira_add_attachment" also appears in a tool-name list          # line 236
```

### Does NOT Exist
- ~~any production caller of `jira_add_attachment`~~ — measured 2026-10-08: references
  exist only in `tests/test_jiratoolkit_permissions.py:165-167,236`
- ~~a path or URL parameter after this task~~ — spec AC5: the tool schema must expose
  `file_ids` only. Do NOT keep `attachment` as a deprecated alias
- ~~`JiraAttachmentReport` being returned as a model instance~~ — tools return plain
  dicts; use `.model_dump()`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_jiratoolkit_permissions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jira_add_attachment_handles.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#AddAttachmentInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_add_attachment"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Change the input model — *why*: `@tool_schema` derives the LLM-visible schema from
   it, so AC5 is satisfied here, not in the method signature.
2. Rewrite the method as a thin delegation — *why*: all logic belongs to the shared
   helper; a second implementation is what this feature is removing.
3. Update the permissions test — *why*: it is the only existing reference and would
   otherwise fail on the changed signature.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    attachment: str = Field(description="Path to attachment file on disk")' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# REPLACE — the field inside `class AddAttachmentInput` (verified: jiratoolkit.py:393)
    file_ids: List[str] = Field(
        description=(
            "Session file handles to attach, from sf_list_session_files. "
            "Filesystem paths and URLs are not accepted."
        )
    )
```
**Why**: the description is the model's only instruction about where handles come from;
naming `sf_list_session_files` is what makes the tool discoverable as a pair.

```python
# occurrences: 1 (verified: grep -c '    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict\[str, Any\]:' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# REPLACE — the whole method body (verified: jiratoolkit.py:2169-2179)
    async def jira_add_attachment(self, issue: str, file_ids: List[str]) -> Dict[str, Any]:
        """Attach one or more session files to an issue. Requires jira.write permission.

        file_ids come from sf_list_session_files. Returns a report with one entry per
        handle; a per-file failure is reported, never raised — read
        attachments[].error_code.

        Example: jira_add_attachment(issue='NAV-123', file_ids=['Ab3...'])
        """
        results = await self._attach_session_files(issue, file_ids)
        # FILL IN: build JiraAttachmentReport(issue=issue, attachments=results,
        # attached=<count ok>, failed=<count not ok>) and return .model_dump()
        # bounded by AC4 (one entry per input) and "never raises for a per-file failure"
        raise NotImplementedError
```
**Why**: the method is now pure delegation plus counting — if logic creeps back in here,
`jira_add_comment` and this tool diverge again, which is the defect spec §1 names.

```python
# occurrences: 1 (verified: grep -c '        method = getattr(toolkit, "jira_add_attachment", None)' packages/ai-parrot/tests/test_jiratoolkit_permissions.py)
# AFTER — in `test_jira_add_attachment_requires_write` (verified: tests/test_jiratoolkit_permissions.py:167)
# FILL IN: the assertion body only asserts the permission annotation, so it should keep
# passing unchanged. Verify that; if it inspects the call signature, update it to
# file_ids — bounded by: this test asserts PERMISSIONS, not the attachment contract
```
**Why**: this test is about `jira.write`, not about attachments. Read it before editing —
it may need no change at all, and an unnecessary edit here would hide a real regression.

### FILL IN checklist
- [ ] report construction + counts; bounded by AC4
- [ ] permissions-test check (edit only if the signature is actually inspected)
- [ ] test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `AddAttachmentInput` exposes `issue` and `file_ids` only — no path, no URL (spec AC5)
- [ ] `jira_add_attachment` returns `issue`, `attachments`, `attached`, `failed`
- [ ] A per-file failure does not raise; it appears with an `error_code` (spec AC4)
- [ ] `test_jira_add_attachment_requires_write` still passes
- [ ] No deprecated `attachment=` alias exists in the diff (spec AC17, hard cut)
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_add_attachment_handles.py -q`
- `pytest packages/ai-parrot/tests/test_jiratoolkit_permissions.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/unit/test_jira_add_attachment_handles.py
import pytest


class TestJiraAddAttachment:
    async def test_schema_exposes_file_ids_only(self):
        """Spec AC5 — no path or URL field reaches the model."""
        from parrot_tools.jiratoolkit import AddAttachmentInput
        assert set(AddAttachmentInput.model_fields) == {"issue", "file_ids"}

    async def test_returns_report_with_counts(self, toolkit, bound_session):
        # FILL IN: two good handles -> attached == 2, failed == 0

    async def test_per_file_failure_is_reported_not_raised(self, toolkit, bound_session):
        # FILL IN: one unknown handle -> failed == 1, no exception
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
8. `scripts/sdd/close_task.sh TASK-4140 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any

## Completion Note

Merged by engine (codex); jira unit tests run with --noconftest.
