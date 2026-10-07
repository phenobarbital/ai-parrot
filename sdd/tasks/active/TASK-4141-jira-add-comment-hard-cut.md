# TASK-4141: `jira_add_comment` — handles, pre-flight before posting, independent statuses

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4140
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, AC11, and design-research finding S8. Two things are wrong with the
current `jira_add_comment` (`jiratoolkit.py:2530`, post-FEAT-637):

1. Its `attachments` parameter takes **filesystem paths** (`:2534`), the contract this
   feature replaces with handles.
2. It **creates the comment first** (`self.jira.add_comment(...)`) and only then uploads
   (`:2578-2600`). An attachment failure therefore leaves a published comment promising
   a file nobody can see — and pre-flighting does not make it atomic, so the fix is to
   pre-flight *before* posting and report the two outcomes independently.

FEAT-637's `template` / `template_params` / `body: Optional[str]` are kept verbatim —
this task must not alter templating behaviour.

---

## Scope

- Replace `AddCommentInput.attachments: Optional[List[str]]` with
  `file_ids: Optional[List[str]]`; leave `body`, `is_internal`, `template` and
  `template_params` untouched.
- Change the method signature the same way.
- **Pre-flight handles before anything is posted**: resolve/validate first; if any
  handle is unresolvable, return without creating the comment.
- Delete the inline upload loop (`:2578-2600`) and delegate to `_attach_session_files`.
- Return a `JiraCommentReport` dict: `comment`, `comment_ok`, `attachments`,
  `attached`, `failed`.
- Rewrite `tests/test_jira_comment_attachments.py` (6 tests, 4 of them pass paths).
- Update the docstring example at `:2550` which still shows `attachments=['/path/...']`.

**NOT in scope**: templating (FEAT-637's, unchanged) · `jira_add_attachment`
(TASK-4140) · the helper (TASK-4139).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Input schema, signature, pre-flight, delegation |
| `packages/ai-parrot/tests/test_jira_comment_attachments.py` | MODIFY | Rewrite the 6 tests onto handles |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified against `1f74e23c7` on 2026-10-08, **after FEAT-637 merged**.
> Every one of them drifted from the spec's original §6 values — re-verify before editing.

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (verified 1f74e23c7)
class AddCommentInput(BaseModel):                                      # line 507
    issue: str                                                         # line 510
    body: Optional[str] = Field(default=None, ...)                     # line 511  (FEAT-637)
    is_internal: bool = Field(default=False, ...)                      # line 512
    attachments: Optional[List[str]] = Field(default=None, ...)        # lines 513-519  <- REPLACE
    template: Optional[str] = Field(default=None, ...)                 # line 520  (FEAT-637)
    #  template_params follows                                          (FEAT-637)

    @requires_permission("jira.write")                                 # line 2528
    @tool_schema(AddCommentInput)                                      # line 2529
    async def jira_add_comment(                                        # line 2530
        self, issue: str, body: Optional[str] = None, is_internal: bool = False,
        attachments: Optional[List[str]] = None,                       # line 2535  <- REPLACE
        template: Optional[str] = None,
        template_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        project = self._project_of(issue)                              # FEAT-637
        body = await self._render_jira_text("comment", text=body, template=template,
                   template_params=template_params, call_fields={...}, project=project)
        if body is None:
            raise ValueError("jira_add_comment: body is required when no template applies")
        def _run(): return self.jira.add_comment(issue, body, is_internal=is_internal)
        comment = await asyncio.to_thread(_run)                        # comment CREATED here
        result = self._issue_to_dict(comment)
        if attachments:                                                # lines 2578-2600  <- DELETE
            ...  # os.path.isfile check + per-file to_thread upload + except -> {"error"}

# from TASK-4138 / TASK-4139, in this same file:
    async def _attach_session_files(self, issue: str, file_ids: Sequence[str]) -> List[AttachmentResult]
class JiraCommentReport(BaseModel):
    issue: str; comment: Dict[str, Any]; comment_ok: bool
    attachments: List[AttachmentResult]; attached: int; failed: int

# packages/ai-parrot/tests/test_jira_comment_attachments.py  (142 lines, 6 tests)
async def test_add_comment_without_attachments(toolkit)                # line 23
async def test_add_comment_internal_is_forwarded(toolkit)              # line 38
async def test_add_comment_with_valid_attachments(toolkit, tmp_path)   # line 51   <- paths
async def test_add_comment_with_missing_file(toolkit)                  # line 83   <- paths
async def test_add_comment_with_mixed_files(toolkit, tmp_path)         # line 99   <- paths
async def test_add_comment_attachment_upload_error(toolkit, tmp_path)  # line 127  <- paths
```

### Does NOT Exist
- ~~atomicity between the comment and its attachments~~ — Jira has no attachment
  rollback. Pre-flight removes the common case; `comment_ok` and the per-file results
  stay separate precisely because the rest cannot be made atomic (spec §7, AC11)
- ~~`os.path.isfile` validation after this task~~ — handles are validated by
  `SessionFileStore.resolve`, not by touching the filesystem here. Delete the check
- ~~any change to `_render_jira_text` or template behaviour~~ — FEAT-637 owns it; this
  task must not alter it
- ~~a production caller passing `attachments=`~~ — measured 2026-10-08: only the
  docstring example (`:2550`) and this test module

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_jira_comment_attachments.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#AddCommentInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_add_comment"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Order inside the method: **pre-flight handles → render the template → create the
  comment → upload**. A bad handle must cost no template render and no POST.
- `comment_ok` is `True` whenever the comment was created, regardless of attachments.
- Keep `self._issue_to_dict(comment)` as the `comment` field's value.

---

## Implementation Blueprint

### Steps (in order)
1. Swap the input model field — *why*: `@tool_schema` drives what the model sees (AC5).
2. Swap the signature parameter — *why*: it must match the model exactly or the schema
   and the callable disagree.
3. Insert the pre-flight gate before `_render_jira_text` — *why*: AC11 requires that a
   bad handle prevents comment creation.
4. Replace the trailing upload loop with the helper and build the report — *why*: one
   attachment implementation is the whole point of M3.
5. Rewrite the six tests — *why*: four of them assert the path contract and would
   otherwise pass against a contract that no longer exists.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    attachments: Optional\[List\[str\]\] = Field(' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# REPLACE — the `attachments` field of `AddCommentInput` (verified: jiratoolkit.py:513-519)
    file_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional session file handles to attach to the issue alongside this "
            "comment, from sf_list_session_files. Files are attached at the issue "
            "level. Filesystem paths and URLs are not accepted."
        ),
    )
```
**Why**: "attached at the issue level" is kept from the original description because it
is still true and is the one thing the model gets wrong otherwise.

```python
# occurrences: 1 (verified: grep -c '        attachments: Optional\[List\[str\]\] = None,' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# REPLACE — the parameter in the method signature (verified: jiratoolkit.py:2535)
        file_ids: Optional[List[str]] = None,
```
**Why**: position is kept so the surrounding FEAT-637 parameters are untouched.

```python
# occurrences: 1 (verified: grep -c '        project = self._project_of(issue)' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# BEFORE — insert above `project = self._project_of(issue)` (first line of the body)
        # Pre-flight the handles BEFORE anything is rendered or posted: a bad handle
        # must never leave a published comment promising a file (AC11).
        preflight: List[AttachmentResult] = []
        if file_ids:
            # FILL IN: resolve each handle via the store WITHOUT uploading; when any
            # result is not ok, return JiraCommentReport(issue=issue, comment={},
            # comment_ok=False, attachments=<those results>, attached=0,
            # failed=<count>).model_dump() immediately — no render, no POST.
            # bounded by AC11 (a bad handle prevents comment creation)
            raise NotImplementedError
```
**Why**: this gate is the behavioural change AC11 names. It runs before
`_render_jira_text` so a handle error is reported as a handle error, not as the
`ValueError("body is required …")` the render path raises.

```python
# occurrences: 1 (verified: grep -c '        # Upload attachments if provided' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# REPLACE — the whole `if attachments:` block from `# Upload attachments if provided`
#           to the end of the method (verified: jiratoolkit.py:2577-2600+)
        attachments_out: List[AttachmentResult] = []
        if file_ids:
            attachments_out = await self._attach_session_files(issue, file_ids)
        # FILL IN: return JiraCommentReport(issue=issue, comment=result,
        # comment_ok=True, attachments=attachments_out, attached=<ok count>,
        # failed=<not-ok count>).model_dump()
        # bounded by AC11 (comment_ok stays True when an upload fails afterwards)
        raise NotImplementedError
```
**Why**: `comment_ok=True` with `failed > 0` is a legitimate, expected outcome — Jira
cannot roll the comment back, and collapsing both into one boolean is what made the old
behaviour unreadable. Delete the `os.path.isfile` check with the loop: handle validation
belongs to the store.

```python
# occurrences: 1 (verified: grep -c "                attachments=\['/path/to/screenshot.png'\]" packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# REPLACE — the docstring example (verified: jiratoolkit.py:2550)
                file_ids=['Ab3xYz...']
```
**Why**: the docstring is the LLM-facing description; leaving a path example there would
teach the model the contract this task removes.

### FILL IN checklist
- [ ] pre-flight gate — resolve-without-upload + early return; bounded by AC11
- [ ] final report construction; bounded by AC11 (`comment_ok` independent of uploads)
- [ ] rewrite of the six tests; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `AddCommentInput` exposes `file_ids`, never `attachments`; `body`, `is_internal`,
      `template`, `template_params` are unchanged (spec AC5)
- [ ] A bad handle returns `comment_ok=False` and **no comment is created** (spec AC11)
- [ ] An upload failure *after* creation returns `comment_ok=True` with `failed >= 1` (spec AC11)
- [ ] A comment with no `file_ids` behaves exactly as before (templates included)
- [ ] `test_add_comment_without_attachments` and `test_add_comment_internal_is_forwarded` still pass
- [ ] The inline upload loop and its `os.path.isfile` check are gone from the diff
- [ ] The docstring no longer shows a filesystem path example
- [ ] FEAT-637's template tests still pass
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_jira_comment_attachments.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_writes.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jira_comment_attachments.py  (rewritten onto handles)
import pytest


async def test_add_comment_without_attachments(toolkit):
    """Unchanged behaviour when no file_ids are given."""
    # FILL IN: keep the existing assertions

async def test_add_comment_internal_is_forwarded(toolkit):
    """Unchanged."""
    # FILL IN: keep the existing assertions

async def test_add_comment_with_valid_handles(toolkit, bound_session):
    """Replaces test_add_comment_with_valid_attachments (was: tmp_path + paths)."""
    # FILL IN: attached == 1, comment_ok is True

async def test_bad_handle_prevents_comment_creation(toolkit, bound_session):
    """Spec AC11 — replaces test_add_comment_with_missing_file."""
    # FILL IN: assert comment_ok is False and the Jira client never created a comment

async def test_mixed_handles_are_best_effort(toolkit, bound_session):
    """Replaces test_add_comment_with_mixed_files.

    NOTE: with the AC11 pre-flight gate, a mix containing an UNRESOLVABLE handle now
    creates no comment. Use a mix where every handle resolves but one upload fails.
    """
    # FILL IN

async def test_comment_ok_with_failed_upload(toolkit, bound_session):
    """Spec AC11 — replaces test_add_comment_attachment_upload_error."""
    # FILL IN: comment_ok is True, failed == 1
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
8. `scripts/sdd/close_task.sh TASK-4141 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
