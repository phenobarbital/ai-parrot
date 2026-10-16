# TASK-4420: Parity Tools and KB Integration in JiraToolkit

**Feature**: FEAT-696 — JiraToolkit upgrades
**Spec**: `sdd/specs/jiratoolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4417
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 1 (parity tools) and the Module 6 KB-lookup integration
> into `jiratoolkit.py`. Both touch `jiratoolkit.py`, so they are serialized in
> one task. Depends on TASK-4417 for the `JiraKnowledgeBase` model. TASK-4421
> (toolkit wiring) depends on this task because it also modifies `jiratoolkit.py`.

---

## Scope

- Add five new tool methods to `JiraToolkit`: `jira_create_issue_link`,
  `jira_get_link_types`, `jira_get_create_fields`, `jira_edit_comment`,
  `jira_get_accessible_resources`.
- Add input models: `CreateIssueLinkInput`, `GetCreateFieldsInput`, `EditCommentInput`.
- Add `knowledge_base` kwarg to `__init__`; load KB from path/env.
- Integrate KB lookups into existing methods: `jira_get_issue_types`,
  `jira_get_projects`, `jira_get_components`, and new `jira_get_create_fields`.
- Add KB field-alias resolution in create/update calls.
- Add KB limits enforcement (`validate_limits`) before create/update API calls.
- Write unit tests for the new tools and KB integration.

**NOT in scope**: `oauth2_local` wiring (TASK-4421), local token store (TASK-4419),
CLI (TASK-4422), or the `_pre_execute` changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | New tools + KB init + KB lookups |
| `packages/ai-parrot-tools/tests/unit/test_jira_parity_tools.py` | CREATE | Unit tests for new tools |
| `packages/ai-parrot-tools/tests/unit/test_jira_kb_integration.py` | CREATE | KB integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.jira_kb import JiraKnowledgeBase                  # created by TASK-4417
from parrot.auth.jira_oauth import (                                # verified: jira_oauth.py:34
    ACCESSIBLE_RESOURCES_URL,
    fetch_accessible_resources,                                     # created by TASK-4418 (only for 3LO mode)
)
# Already imported in jiratoolkit.py:
from .decorators import tool_schema, requires_permission            # verified: jiratoolkit.py:63
```

### Existing Signatures to Use
```python
# jiratoolkit.py
class JiraToolkit(AbstractToolkit):                                  # L742
    def __init__(self, ..., templates: Optional[Mapping[str, str]] = None, **kwargs):  # L844-862
    async def jira_add_comment(self, issue, body=None, ..., template=None, template_params=None):  # L2856
    async def jira_get_issue_types(self, project=None):              # L2956
    async def jira_get_projects(self) -> Dict[str, Any]:             # L3142
    async def jira_get_components(self, project=None):               # L3215
    async def jira_list_transitions(self, issue):                    # L4242

# jira 3.10.5
JIRA.create_issue_link(type, inwardIssue, outwardIssue, comment=None)
JIRA.issue_link_types(force=False) -> list[IssueLinkType]
JIRA.comment(issue, comment, expand=None) -> Comment   # Comment.update(body=...)
JIRA.project_issue_fields(project, issue_type, startAt=0, maxResults=50)
```

### Does NOT Exist
- ~~`JiraToolkit.jira_create_issue_link`~~ — does not exist yet; this task creates it
- ~~`JiraToolkit.jira_edit_comment`~~ — does not exist yet
- ~~`JiraToolkit.jira_get_create_fields`~~ — does not exist yet
- ~~`JiraToolkit.jira_get_accessible_resources`~~ — does not exist yet
- ~~`JiraToolkit.jira_get_link_types`~~ — does not exist yet
- ~~`JiraToolkit._kb`~~ — does not exist yet; this task adds it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_parity_tools.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_kb_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_add_comment",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_get_issue_types",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_get_projects",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_get_components"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
New tools follow the `jira_get_issue_types` pattern (L2956):
```python
@tool_schema(SomeInput)
async def jira_some_method(self, ...) -> ...:
    """Docstring."""
    def _run():
        return self.jira.some_jira_method(...)
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_run), timeout=self.request_timeout + 5)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(...) from exc
    return ...
```

Writes are decorated `@requires_permission("jira.write")` BEFORE `@tool_schema(...)`.

### Key Constraints
- `jira_get_accessible_resources` works in ALL auth modes (spec §2 M1):
  3LO/local → `fetch_accessible_resources(access_token)`;
  static + KB → KB's `cloud_id`/`site`;
  static, no KB → `GET <server_url>/_edge/tenant_info` (best-effort).
- `jira_edit_comment` reuses the FEAT-637 template machinery from `jira_add_comment`.
- KB `resolve_issue_type` used in `jira_get_create_fields`; falls back to live lookup on miss.
- KB `resolve_field` applied to `fields` keys in create/update calls.
- KB limits enforced before create/update API calls via `validate_limits`.

---

## Implementation Blueprint

### Steps (in order)
1. Add input models before `ConfigureClientInput` — *why*: convention places inputs above the toolkit class.
2. Add `knowledge_base` kwarg and `_kb` attribute to `__init__` — *why*: KB must be loaded once at init time.
3. Add five new tool methods near `jira_list_transitions` — *why*: "New Methods" section at end of class.
4. Integrate KB lookups into `jira_get_issue_types`, `jira_get_projects`, `jira_get_components` — *why*: serve from KB first (AC7).
5. Add KB field-alias resolution and limits enforcement in create/update paths — *why*: AC7, AC8.
6. Write tests — *why*: validates tools and integration.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)

**New input models — insert before `ConfigureClientInput`:**
```python
# occurrences: 1 (verified: grep -c 'class ConfigureClientInput' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# BEFORE — insert above `class ConfigureClientInput(BaseModel):` (verified: jiratoolkit.py:732)

class CreateIssueLinkInput(BaseModel):
    inward_issue: str = Field(..., description="Issue key of the inward issue (e.g. 'PROJ-1')")
    outward_issue: str = Field(..., description="Issue key of the outward issue (e.g. 'PROJ-2')")
    link_type: str = Field("Relates", description="Link type name (e.g. 'Blocks', 'Relates')")
    comment: Optional[str] = Field(None, description="Optional comment on the link")


class GetCreateFieldsInput(BaseModel):
    issue_type: str = Field(..., description="Issue type name or id")
    project: Optional[str] = Field(None, description="Project key (uses default_project if omitted)")


class EditCommentInput(BaseModel):
    issue: str = Field(..., description="Issue key (e.g. 'PROJ-123')")
    comment_id: str = Field(..., description="Comment id to edit")
    body: Optional[str] = Field(None, description="New comment body (plain text or ADF)")
    template: Optional[str] = Field(None, description="Template name (FEAT-637)")
    template_params: Optional[Dict[str, Any]] = Field(None, description="Template parameters")
```

**KB init — insert in `__init__` after `templates` kwarg:**
```python
# occurrences: 1 (verified: grep -c 'templates: Optional\[Mapping\[str, str\]\] = None,' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# AFTER — insert below `        templates: Optional[Mapping[str, str]] = None,` (verified: jiratoolkit.py:860)
        knowledge_base: Optional[Union[str, Path, "JiraKnowledgeBase"]] = None,
```

```python
# In __init__ body, after template loading, load the KB:
# FILL IN: load KB from kwarg or JIRA_KB_PATH env, store as self._kb,
#          validate site identity (S4), log warning on failure (AC10)
#          — bounded by spec §2 M4/M6
```

**New tools — insert after `jira_list_transitions`:**
```python
# occurrences: 1 (verified: grep -c 'async def jira_list_transitions' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# AFTER — insert below `    async def jira_list_transitions(self, issue: str) -> List[Dict[str, Any]]:` block (verified: jiratoolkit.py:4242)

    @requires_permission("jira.write")
    @tool_schema(CreateIssueLinkInput)
    async def jira_create_issue_link(
        self,
        inward_issue: str,
        outward_issue: str,
        link_type: str = "Relates",
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Link two issues (e.g. 'Blocks', 'Relates'). Use jira_get_link_types for valid names."""
        # FILL IN: asyncio.to_thread(self.jira.create_issue_link(...)) + wait_for — bounded by spec §2 M1
        raise NotImplementedError

    @tool_schema(TicketIdInput)
    async def jira_get_link_types(self) -> List[Dict[str, Any]]:
        """List issue link types: name, inward and outward descriptions."""
        # FILL IN: asyncio.to_thread(self.jira.issue_link_types()) — bounded by spec §2 M1
        raise NotImplementedError

    @tool_schema(GetCreateFieldsInput)
    async def jira_get_create_fields(
        self, issue_type: str, project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fields (id, name, required, schema, allowedValues) to create an issue of this type."""
        # FILL IN: resolve issue_type via KB first, fall back to live;
        #          JIRA.project_issue_fields(project, issue_type_id) — bounded by spec §2 M1
        raise NotImplementedError

    @requires_permission("jira.write")
    @tool_schema(EditCommentInput)
    async def jira_edit_comment(
        self,
        issue: str,
        comment_id: str,
        body: Optional[str] = None,
        template: Optional[str] = None,
        template_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Replace the body of an existing comment."""
        # FILL IN: reuse FEAT-637 template machinery from jira_add_comment;
        #          self.jira.comment(issue, comment_id).update(body=...) — bounded by spec §2 M1
        raise NotImplementedError

    async def jira_get_accessible_resources(self) -> Dict[str, Any]:
        """Return {cloud_id, site_url, sites, source} in any auth mode."""
        # FILL IN: 3LO → fetch_accessible_resources(access_token);
        #          static+KB → KB cloud_id/site; static, no KB → _edge/tenant_info
        #          — bounded by spec §2 M1
        raise NotImplementedError
```
**Why this shape**: follows the `to_thread` + `wait_for` pattern at L2956; writes get
`@requires_permission("jira.write")` before `@tool_schema` (L2854-2855).

**KB lookups in existing methods:**
```python
# FILL IN: In jira_get_issue_types (L2956), jira_get_projects (L3142),
#          jira_get_components (L3215): check self._kb first, return from KB
#          if the request is fully covered, otherwise fall back to live API
#          with a warning log "jira KB stale: ..."
#          — bounded by AC7, spec §2 M6 lookups table
```

### FILL IN checklist
- [ ] `jiratoolkit.py::__init__` — KB loading from kwarg/env, site identity check; bounded by AC10, S4
- [ ] `jiratoolkit.py::jira_create_issue_link` — `to_thread` + `wait_for`; bounded by spec §2 M1
- [ ] `jiratoolkit.py::jira_get_link_types` — `to_thread`; bounded by spec §2 M1
- [ ] `jiratoolkit.py::jira_get_create_fields` — KB resolve + live fallback; bounded by spec §2 M1
- [ ] `jiratoolkit.py::jira_edit_comment` — template rendering + comment.update; bounded by spec §2 M1
- [ ] `jiratoolkit.py::jira_get_accessible_resources` — multi-mode resolution; bounded by spec §2 M1
- [ ] `jiratoolkit.py::jira_get_issue_types` — KB fast-path; bounded by AC7
- [ ] `jiratoolkit.py::jira_get_projects` — KB fast-path; bounded by AC7
- [ ] `jiratoolkit.py::jira_get_components` — KB fast-path; bounded by AC7
- [ ] KB field-alias resolution in create/update calls; bounded by AC7
- [ ] KB limits enforcement before create/update; bounded by AC8
- [ ] `test_jira_parity_tools.py` — all tool tests; bounded by spec §4 M1
- [ ] `test_jira_kb_integration.py` — KB hit/miss/stale tests; bounded by spec §4 M6

---

## Acceptance Criteria

- [ ] The five M1 tools are registered and appear in `JiraToolkit().get_tools()` (AC1)
- [ ] `jira_get_accessible_resources` returns a result in every auth mode and never raises on a tenant_info failure (AC2)
- [ ] With a KB loaded, `jira_create_issue(issue_type="Story", project="NAV")` performs no issue-type lookup (AC7)
- [ ] An unknown type triggers a live lookup and logs `jira KB stale` (AC7)
- [ ] Summary/description limits from the KB are enforced before API calls (AC8)
- [ ] A missing or invalid KB file never stops the toolkit from loading (AC10)
- [ ] `ruff check` clean; no new dependency (AC11)

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_parity_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jira_kb_integration.py -q`

---

## Test Specification

See blueprint for test file skeletons. Key test rows from spec §4:
- `test_jira_parity_tools.py`: link/link-types/create-fields/edit-comment call the right `jira.JIRA` methods (mocked)
- `test_accessible_resources_modes`: 3LO → helper; static+KB → KB; static, no KB → tenant_info; failure → `source: unavailable`
- `test_jira_parity_contract`: generated tool names, `jira.write` on link/edit, exact call args
- `test_jira_kb_integration.py`: KB hit/miss/stale, site mismatch ignored, limits enforced

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug jiratoolkit-upgrades --feature-id FEAT-696`
2. **Read the spec** at `sdd/specs/jiratoolkit-upgrades.spec.md`
3. **Check dependencies** — TASK-4417 must be `"done"` (provides `JiraKnowledgeBase`)
4. **Verify the Codebase Contract** — re-read anchors in `jiratoolkit.py` (they may have drifted)
5. **Update status** in `sdd/tasks/index/jiratoolkit-upgrades.json` → `"in-progress"`
6. **Implement** — add input models, KB init, new tools, KB lookups
7. **Verify** acceptance criteria; run validation commands
8. **Commit** — stage only `jiratoolkit.py` and the two test files
9. **Close** with `scripts/sdd/close_task.sh TASK-4420 jiratoolkit-upgrades verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
