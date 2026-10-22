# TASK-4115: Wire templates into create / update / comment write paths

**Feature**: FEAT-637 — JiraToolkit Template Support
**Spec**: `sdd/specs/jiratoolkit-template-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4114
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3** (G1, G6, G7; AC1, AC7, AC10, AC12, AC15). Adds
`template` / `template_params` to the three input models and the three write
tools, calls `_render_jira_text` at each tool's text-shaping point, makes the
comment `body` optional (spec S2) and fails closed when a template would be
overwritten by `fields["description"]` (spec S6).

---

## Scope

- Add `template: Optional[str]` and `template_params: Optional[Dict[str, Any]]` (with `x-exclude-form`) to `CreateIssueInput`, `UpdateIssueInput`, `AddCommentInput`.
- Make `AddCommentInput.body` and the `jira_add_comment` `body` parameter `Optional[str] = None`.
- Add the two kwargs (last, after `fields` / `attachments`) to `jira_create_issue`, `jira_update_issue`, `jira_add_comment`; update each docstring with one template example.
- Render: create after `canonical_issuetype`; update before the standard-fields block; comment before `_run`.
- Raise `JiraTemplateError` when a template was applied and `fields` contains `"description"` (create and update).
- Raise `ValueError` in `jira_add_comment` when, after rendering, the body is `None` or blank.
- Write `test_jiratoolkit_templates_writes.py`.

**NOT in scope**: helper internals (TASK-4114); `jira_list_templates` (TASK-4116); `jira_update_ticket` needs NO edit (it forwards `**kwargs`, :3384-3386); `ResearchNode`, `jira_specialist.py` and dev_loop nodes are not touched.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | input-model fields + three write-path integrations |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_writes.py` | CREATE | write-path tests with a mocked `self.jira` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All already in jiratoolkit.py after TASK-4113/4114:
# JiraTemplateError, JiraTemplateNotFound, self._render_jira_text, self._project_of
from pydantic import BaseModel, Field     # jiratoolkit.py:37
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (dev d79fdf0b5)
class CreateIssueInput(BaseModel):   # 375-405; last field `fields` (:401-405, has json_schema_extra={"x-exclude-form": True})
    original_estimate: Optional[str] = Field(default=None, description="Original time estimate, e.g. '8h', '2d', '30m'")  # :399
class UpdateIssueInput(BaseModel):   # 408-437
    fields: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary field updates dict")   # :437 (last line)
class AddCommentInput(BaseModel):    # 455-467
    body: str = Field(description="Comment body text")                                                  # :459
    is_internal: bool = Field(default=False, description="If true, mark as internal (Service Desk)")    # :460

    async def jira_create_issue(self, project=None, summary="", issuetype=None, description=None,
        assignee=None, priority=None, labels=None, components=None, due_date=None, parent=None,
        original_estimate=None, fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:   # 1781-1795
        canonical_issuetype = await self._validate_issue_type(project, issuetype)            # :1856
        # Build fields dict                                                                   # :1858
        if description: issue_fields["description"] = description                           # :1865-1866
        if fields: issue_fields.update(fields)                                              # :1891-1892
    async def jira_update_issue(self, issue: str, summary=None, description=None, ...,
        fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:                          # 1916-1931
        update_kwargs: Dict[str, Any] = {}                                                    # :1950
        if description is not None: update_fields["description"] = description               # :1956-1957
        if fields: update_fields.update(fields)                                             # :1984-1985
    async def jira_add_comment(self, issue: str, body: str, is_internal: bool = False,
        attachments: Optional[List[str]] = None) -> Dict[str, Any]:                          # 2027-2032
        def _run():                                                                           # :2049
            return self.jira.add_comment(issue, body, is_internal=is_internal)               # :2050
    async def jira_update_ticket(self, **kwargs) -> Dict[str, Any]   # 3384 — forwards to jira_update_issue
```
`test_write_methods_still_use_self_jira` (test_jiratoolkit_delegation.py:190-195) requires the literal `self.jira` to stay inside `jira_create_issue` and `jira_add_comment` — keep each `_run` where it is.

### Does NOT Exist
- ~~`jira_add_comment(..., body=..., fields=...)`~~ — comment has no `fields` parameter; the conflict rule applies to create and update only.
- ~~an `issuetype` for update/comment convention lookup~~ — not available without a fetch; pass `issuetype=None` (spec S3).
- ~~resolved `accountId` / component ids in the template context~~ — context uses values as passed (spec AC7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_writes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#CreateIssueInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#UpdateIssueInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#AddCommentInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_create_issue",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_update_issue",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_add_comment",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_update_ticket"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- AC1 (G7): no template config and no `template` ⇒ the helper returns `description` / `body` unchanged, so the payloads stay byte-for-byte identical. Do not reorder or rewrite any existing payload line.
- "A template was applied" = the rendered value differs from the input object (`rendered is not description`) — this works because the helper returns the very same object on pass-through.
- Create's context uses the post-default `project` and the canonical issuetype (spec §2 context table).

---

## Implementation Blueprint

### Steps (in order)
1. Add the input-model fields — *why*: `@tool_schema` exposes them to the LLM (spec G6).
2. Extend the three method signatures — *why*: tool kwargs map 1:1 onto method parameters.
3. Insert the three render calls — *why*: one seam per path, before any payload is built (spec S1).
4. Write the tests.

### `jiratoolkit.py` (MODIFY — shared field block, used 3 times)
```python
# Field block appended to each model (identical text):
    template: Optional[str] = Field(
        default=None,
        description=(
            "Template name used to compose the text (e.g. 'nav/bug' or 'nav/bug.j2'); see "
            "jira_list_templates. Omit to apply the configured convention template, if any."
        ),
    )
    template_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Extra variables available to the template; they override same-named call fields.",
        json_schema_extra={"x-exclude-form": True},
    )
```
- **CreateIssueInput** — occurrences: 1 (`grep -c -F -x "    original_estimate: Optional[str] = Field(default=None, description=\"Original time estimate, e.g. '8h', '2d', '30m'\")"`), anchor :399. Insert the block AFTER the `fields` field that ends the class (:401-405), i.e. directly before the blank lines preceding `class UpdateIssueInput`.
- **UpdateIssueInput** — occurrences: 1, anchor `    fields: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary field updates dict")` (:437). Insert AFTER it.
- **AddCommentInput** — occurrences: 1, anchor `    is_internal: bool = Field(default=False, description="If true, mark as internal (Service Desk)")` (:460). Insert the block AFTER the `attachments` field (:461-467). Replace :459 with:
  `    body: Optional[str] = Field(default=None, description="Comment body text (required unless a template applies)")`

### `jiratoolkit.py` (MODIFY — `jira_create_issue`)
```python
# signature: add after `fields: Optional[Dict[str, Any]] = None,` inside jira_create_issue (:1794)
# FILL IN: disambiguate — that line occurs 4 times (verified: grep -c -F -x); attach to the one inside
#          the `async def jira_create_issue(` signature (:1781-1795), directly above `    ) -> Dict[str, Any]:`.
        template: Optional[str] = None,
        template_params: Optional[Dict[str, Any]] = None,

# occurrences: 1 (verified: grep -c -F -x '        canonical_issuetype = await self._validate_issue_type(project, issuetype)' jiratoolkit.py)
# AFTER — insert below that line (verified: jiratoolkit.py:1856)
        # FEAT-637 — compose the description from a template, if one applies.
        rendered_description = await self._render_jira_text(
            "create",
            text=description,
            template=template,
            template_params=template_params,
            call_fields={
                "project": project, "summary": summary, "issuetype": canonical_issuetype,
                "description": description, "assignee": assignee, "priority": priority,
                "labels": labels, "components": components, "due_date": due_date,
                "parent": parent, "original_estimate": original_estimate,
            },
            project=project,
            issuetype=canonical_issuetype,
        )
        if rendered_description is not description and fields and "description" in fields:
            raise JiraTemplateError("fields['description'] conflicts with the rendered template description")
        description = rendered_description
```

### `jiratoolkit.py` (MODIFY — `jira_update_issue`)
```python
# signature: add the two kwargs after `fields: Optional[Dict[str, Any]] = None,` inside jira_update_issue
# FILL IN: disambiguate — `fields: Optional[Dict[str, Any]] = None,` occurs in several method signatures;
#          attach to the one in the `async def jira_update_issue(` signature (:1916-1931).

# occurrences: 1 (verified: grep -c -F -x '        update_kwargs: Dict[str, Any] = {}' jiratoolkit.py)
# BEFORE — insert above `        update_kwargs: Dict[str, Any] = {}` (verified: jiratoolkit.py:1950)
        # FEAT-637 — compose the description from a template, if one applies.
        project = self._project_of(issue)
        rendered_description = await self._render_jira_text(
            "update",
            text=description,
            template=template,
            template_params=template_params,
            call_fields={
                "issue": issue, "project": project, "summary": summary, "description": description,
                "labels": labels, "due_date": due_date, "priority": priority, "issuetype": issuetype,
            },
            project=project,
        )
        if rendered_description is not description and fields and "description" in fields:
            raise JiraTemplateError("fields['description'] conflicts with the rendered template description")
        description = rendered_description
```

### `jiratoolkit.py` (MODIFY — `jira_add_comment`)
```python
# signature (:2027-2032): `body: Optional[str] = None`, then add after `attachments: Optional[List[str]] = None,`
        template: Optional[str] = None,
        template_params: Optional[Dict[str, Any]] = None,

# FILL IN: disambiguate — `        def _run():` occurs many times. Attach ABOVE this exact 2-line context
#          (occurrences of the second line: 1, verified jiratoolkit.py:2049-2050):
#              def _run():
#                  return self.jira.add_comment(issue, body, is_internal=is_internal)
        project = self._project_of(issue)
        body = await self._render_jira_text(
            "comment",
            text=body,
            template=template,
            template_params=template_params,
            call_fields={"issue": issue, "project": project, "body": body, "is_internal": is_internal},
            project=project,
        )
        if body is None or not body.strip():
            raise ValueError("jira_add_comment: body is required when no template applies")
```
**Why**: rendering sits in the async part of each method, before the blocking `_run`, so `self.jira` stays inside the method (delegation test) and a failure never reaches the transport.

### `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_writes.py` (CREATE)
```python
"""FEAT-637 TASK-4115 — templates on create / update / comment."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot_tools.jiratoolkit import JiraTemplateError, JiraToolkit


class _FakeJIRA:
    def __init__(self, *args, **kwargs) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_TEMPLATES_DIR", "JIRA_DEFAULT_LABELS",
                "JIRA_DEFAULT_COMPONENTS", "JIRA_DEFAULT_DUE_DATE_OFFSET", "JIRA_DEFAULT_ESTIMATE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


def _make(**kwargs) -> JiraToolkit:
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        tk = JiraToolkit(auth_type="token_auth", server_url="https://x.atlassian.net",
                         token="t", verify_credentials=False, **kwargs)
    tk.jira = MagicMock()
    tk._validate_issue_type = AsyncMock(side_effect=lambda project, it: it)
    tk._issue_to_dict = MagicMock(return_value={"id": "1", "key": "NAV-1"})
    return tk

# FILL IN: test_no_templates_payload_unchanged — create_issue fields == {"project":{"key":"NAV"},"summary":"S","issuetype":{"name":"Task"},"description":"D"} — AC1
# FILL IN: test_create_renders_convention_template (templates={"nav/bug.j2": "h2. Bug\n{{ description }}"}) — AC6/AC7
# FILL IN: test_fields_description_conflict_raises (create and update) — AC10
# FILL IN: test_fields_description_without_template_passthrough — AC1
# FILL IN: test_update_renders_before_update_fields — tk.jira.issue.return_value.update called with fields["description"] == rendered
# FILL IN: test_update_ticket_alias_forwards_template_kwargs — AC15
# FILL IN: test_comment_template_only_body_optional (body=None, templates={"comment.j2": "(bot) {{ issue }}"}) — AC12
# FILL IN: test_comment_without_body_or_template_raises — ValueError, add_comment not called — AC12
# FILL IN: test_comment_body_wrapped_by_template ("(bot) {{ body }}") — AC7
# FILL IN: test_missing_variables_no_transport — create_issue not called — AC8
```

### FILL IN checklist
- [ ] Disambiguate the `jira_update_issue` signature edit and the comment `_run` anchor.
- [ ] Docstring examples for the three tools (`template="nav/bug"`, `template_params={...}`).
- [ ] Ten test bodies.

---

## Acceptance Criteria

- [ ] No template config and no `template` ⇒ create/update/comment payloads unchanged (spec AC1).
- [ ] Template applied + `fields["description"]` ⇒ `JiraTemplateError` on create and update (spec AC10).
- [ ] `jira_add_comment(body=None)` works when a template resolves; raises `ValueError` with no transport otherwise (spec AC12).
- [ ] `jira_update_ticket(issue=..., template=...)` reaches the renderer (spec AC15).
- [ ] `test_jiratoolkit_delegation.py` and `packages/ai-parrot/tests/test_jiratoolkit_permissions.py` still pass (spec AC16).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_writes.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py -q`
- `pytest packages/ai-parrot/tests/test_jiratoolkit_permissions.py -q`

Run inside the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the CREATE block. Spec §4 rows covered: no-templates payload, fields conflict (both), passthrough, update render, alias forwarding, comment template-only / no-body / wrapped, missing variables with no transport.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4114 is `done`.
2. Verify the Codebase Contract (re-run each `grep -c`); mark `in-progress`.
3. Implement from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4115 jiratoolkit-template-support verified`, fill the Completion Note, commit.

---

## Completion Note

**Completed by**: sdd-worker (coder seat gpt-5.6-terra, codex, 1 attempt, 263s; reviewed by orchestrator)
**Date**: 2026-10-08
**Notes**: Delivery matches the task's Files table and acceptance criteria (spec AC1, AC10, AC12, AC15, AC16). Task validation: templates_writes/render/config + delegation = 57 passed; `packages/ai-parrot/tests/test_jiratoolkit_permissions.py` = 27 passed (needs the compiled `parrot/utils/**/*.so` copied into the worktree); ruff clean. Review recorded (0 corrections). The create/update docstrings mention `jira_list_templates`, delivered by TASK-4116.
**Merge-tier gate not re-run: known RED, pre-existing** (see TASK-4113 note, PR #1600, issue:265b7797ae9b, issue:1e9c207bd223). Closed as `partial`.

**Deviations from spec**:
