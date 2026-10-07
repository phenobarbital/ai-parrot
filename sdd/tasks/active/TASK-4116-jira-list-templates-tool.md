# TASK-4116: `jira_list_templates` read tool

**Feature**: FEAT-637 — JiraToolkit Template Support
**Spec**: `sdd/specs/jiratoolkit-template-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4115
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** (G6; AC13). Lets the agent discover template
names before passing `template=` to a write tool. Returns logical names only —
never filesystem paths or template source (spec S4).

---

## Scope

- Add `ListTemplatesInput` next to the other input models.
- Add `jira_list_templates(self, project=None)` decorated only with `@tool_schema(ListTemplatesInput)` (unrestricted read, like `jira_get_projects`).
- Write `test_jiratoolkit_list_templates.py`.

**NOT in scope**: any change to write paths or helpers; adding the tool to `test_write_methods_annotated` (it is a read tool); docs (TASK-4117).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `ListTemplatesInput` + `jira_list_templates` |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_list_templates.py` | CREATE | tool tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already in jiratoolkit.py: BaseModel, Field (:37); tool_schema (:56); _TEMPLATE_SUFFIX and
# self._get_template_engine (TASK-4113).
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class GetProjectsInput(BaseModel):          # line 498-499 — insert ListTemplatesInput after it
    """Input for listing projects."""
    @tool_schema(GetProjectsInput)          # line 2270 — unrestricted read-tool pattern (no @requires_permission)
    async def jira_get_projects(self) -> Dict[str, Any]:   # line 2271
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # line 999 — runs before every tool call

# packages/ai-parrot/src/parrot/tools/toolkit.py
def _generate_tools(self) -> None   # line 575 — auto-registers every public async method; no manual registration needed
```
Verified jinja2 3.1.6: `Environment.list_templates()` lists names across a `ChoiceLoader` of `DictLoader` + `FileSystemLoader`, using `/` separators.

### Does NOT Exist
- ~~`TemplateEngine.list_templates()`~~ — use `engine.env.list_templates()`.
- ~~a tool registry list to append to~~ — `_generate_tools` discovers the method by name.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_list_templates.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#GetProjectsInput",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_get_projects"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `ListTemplatesInput` after `GetProjectsInput` — *why*: keeps input models grouped.
2. Add the tool directly above `@tool_schema(GetProjectsInput)` — *why*: places it with the other unrestricted read tools.
3. Write the tests.

### `jiratoolkit.py` (MODIFY — input model)
```python
# occurrences: 1 (verified: grep -c -F -x 'class GetProjectsInput(BaseModel):' jiratoolkit.py)
# AFTER — insert below the 2-line class `class GetProjectsInput(BaseModel):` (verified: jiratoolkit.py:498-499)


class ListTemplatesInput(BaseModel):
    """Input for listing available Jira text templates."""

    project: Optional[str] = Field(default=None, description="Only templates under this project folder, e.g. 'NAV'")
```

### `jiratoolkit.py` (MODIFY — tool)
```python
# occurrences: 1 (verified: grep -c -F -x '    @tool_schema(GetProjectsInput)' jiratoolkit.py)
# BEFORE — insert above `    @tool_schema(GetProjectsInput)` (verified: jiratoolkit.py:2270)
    @tool_schema(ListTemplatesInput)
    async def jira_list_templates(self, project: Optional[str] = None) -> Dict[str, Any]:
        """List the Jira text templates usable with jira_create_issue, jira_update_issue and jira_add_comment.

        Pass a returned name as ``template=`` to a write tool. Without ``template=``
        the write tools apply a convention template automatically when one exists:
        ``<project>/<issuetype>.j2`` → ``<project>/_default.j2`` → ``_default.j2`` for
        issues, ``<project>/comment.j2`` → ``comment.j2`` for comments.

        Returns:
            ``{"ok": True, "templates": [names], "templates_dir": str | None}``.
        """
        engine = self._get_template_engine()
        names: List[str] = []
        if engine is not None:
            names = sorted(n for n in engine.env.list_templates() if n.endswith(_TEMPLATE_SUFFIX))
        # FILL IN: when `project` is given keep only names starting with f"{project.lower()}/" — bounded by AC13
        return {
            "ok": True,
            "templates": names,
            "templates_dir": str(self.templates_dir) if self.templates_dir else None,
        }
```
**Why**: the docstring is the LLM-facing description, so it states the convention order the agent can rely on.

### `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_list_templates.py` (CREATE)
```python
"""FEAT-637 TASK-4116 — jira_list_templates."""
from unittest.mock import patch

import pytest
from parrot_tools.jiratoolkit import JiraToolkit


class _FakeJIRA:
    def __init__(self, *args, **kwargs) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_TEMPLATES_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


def _make(**kwargs) -> JiraToolkit:
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        return JiraToolkit(auth_type="token_auth", server_url="https://x.atlassian.net",
                           token="t", verify_credentials=False, **kwargs)

# FILL IN: test_list_templates_names_only — tmp dir (nav/bug.j2, notes.txt) + inline {"_default.j2": "x"};
#          result templates == ["_default.j2", "nav/bug.j2"]; no absolute paths, no source text — AC13
# FILL IN: test_list_templates_project_filter — project="NAV" ⇒ ["nav/bug.j2"] — AC13
# FILL IN: test_list_templates_without_engine — templates == [], templates_dir is None
# FILL IN: test_list_templates_is_unrestricted_read — getattr(JiraToolkit.jira_list_templates, "_required_permissions", frozenset()) is empty
# FILL IN: test_list_templates_registered_as_tool — "jira_list_templates" in tk.list_tool_names() (or get_tools names)
```

### FILL IN checklist
- [ ] project filter
- [ ] five test bodies

---

## Acceptance Criteria

- [ ] Returns sorted `.j2` names from inline and filesystem loaders; never paths or source (spec AC13).
- [ ] `project` filters by lower-cased prefix.
- [ ] No `jira.write` permission on the tool; it is auto-registered.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_list_templates.py -q`
- `pytest packages/ai-parrot/tests/test_jiratoolkit_permissions.py -q`

Run inside the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the CREATE block. Spec §4 rows covered: `test_list_templates_names_only`, `test_list_templates_is_unrestricted_read`.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4115 is `done`.
2. Verify the Codebase Contract; mark `in-progress`.
3. Implement from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4116 jiratoolkit-template-support verified`, fill the Completion Note, commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
