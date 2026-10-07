---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# projects / tags (FEAT-576) — carried verbatim from the proposal.
projects: [ai-parrot-tools]
tags: [jira, jiratoolkit, templates, jinja2, tool-configuration]
---

# Feature Specification: JiraToolkit Template Support — Jinja2 composition of issue descriptions and comment bodies

**Feature ID**: FEAT-637
**Date**: 2026-10-07
**Author**: Jesus Lara (with Claude Code)
**Status**: approved
**Target version**: 0.30.0
**Source**: `sdd/proposals/jiratoolkit-template-support.proposal.md` (accepted; research audit in `sdd/state/FEAT-637/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

When an agent (or a flow such as the dev-loop `ResearchNode`) creates a Jira
ticket, the team often requires the description to follow house rules: a fixed
section layout, mandatory "Requirements / Acceptance / Context" blocks,
project-specific boilerplate. Today `JiraToolkit` passes the `description` and
comment `body` strings to the Jira client **verbatim** — every caller
hand-builds its own text (e.g. the f-string in `ResearchNode._render_body`),
and an LLM-driven agent has no way to be held to a layout. The request:

> a template is a file with placeholders (like or potentially jinja2
> template) where "description" of Jira ticket is composed before passed to
> the Jira ticket creation, template composition can be usable also for
> adding comments.

### Goals

- **G1** — A Jinja2 template, loaded from a configured directory
  (`templates_dir` kwarg / `JIRA_TEMPLATES_DIR`) or supplied in memory
  (`templates=` mapping), composes the final text for `jira_create_issue`
  (description), `jira_update_issue` (description) and `jira_add_comment`
  (body). *(U1, U5)*
- **G2** — Selection: an explicit `template=` name wins; otherwise a
  per-project convention is tried (`<project>/<issuetype>.j2` …
  `_default.j2` for create; `<project>/comment.j2` / `comment.j2` for
  comments; `<project>/update.j2` / `update.j2` for updates); otherwise the
  text passes through unchanged. *(U2, S3)*
- **G3** — The template context is the call's own arguments merged with
  `template_params` (params win), so `{{ description }}` / `{{ body }}` wrap
  the caller's text — composition, not replacement. *(Q3, S5)*
- **G4** — Strict placeholders: a template referencing variables the caller
  did not provide fails the tool call **before any Jira request**, naming
  every missing variable. *(U3, S9)*
- **G5** — Rendered output is Jira wiki markup: the engine never
  HTML-escapes. *(C4)*
- **G6** — Both operator-driven (auto-applied convention) and LLM-driven
  (`jira_list_templates` + `template` parameter) use. *(U4)*
- **G7** — Zero behaviour change for callers that configure no templates and
  pass no `template` — the Jira payload is byte-for-byte identical. *(C5)*
- **G8** — Rendered text longer than Jira's 32 767-character field limit is
  truncated to the cap with a visible marker and a logged warning. *(Q2, S7)*

### Non-Goals (explicitly out of scope)

- Markdown → ADF / wiki-markup conversion. None exists today (F014);
  templates emit final Jira markup.
- Changing `JiraInterface` (read-only side) or the pycontribs `JIRA` client.
- Exposing `templates_dir` in `JiraToolkitConfig` (Agent Studio) — declined
  in U1; may be a follow-up.
- Migrating `ResearchNode._render_body` or `/sdd-tojira` to templates
  (follow-up candidates; their own length guards stay as they are — S7).
- Templating `summary` or any non-text Jira field.
- Changes to `parrot/template/engine.py` — the toolkit wraps the engine as
  is (S1/S4/S9 resolved without engine edits).
- A toolkit-agnostic "template mixin" for msword/powerpoint/pdfprint
  (proposal §6 alternative, not pursued).

---

## 2. Architectural Design

### Overview

All template logic lives inside `JiraToolkit`
(`packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`) behind **one**
private async helper, `_render_jira_text()`, which every write path calls at
its single text-shaping point — after the path has resolved defaults and the
canonical issue type (so convention lookup sees the real project/issuetype),
and before the Jira payload is assembled (S1):

- `jira_create_issue` — before `issue_fields["description"] = description`
  (jiratoolkit.py:1865-1866).
- `jira_update_issue` — before `update_fields["description"] = description`
  (jiratoolkit.py:1956-1957).
- `jira_add_comment` — before `self.jira.add_comment(...)`
  (jiratoolkit.py:2050).

The helper uses the core async engine `parrot.template.TemplateEngine`,
built **lazily on first use** with a Jira-safe `JinjaConfig`:
`autoescape=False` (Jira markup is not HTML), `StrictUndefined` (engine
default), and only the stdlib extensions `jinja2.ext.do` +
`jinja2.ext.loopcontrols` (the engine's default extension list pulls three
third-party packages that neither distribution declares in `pyproject.toml`).
Filesystem templates come from `templates_dir` (constructor kwarg, else
`JIRA_TEMPLATES_DIR` via the toolkit's `_cfg()` precedence); in-memory
templates from the `templates` mapping take precedence over files (the
engine's `ChoiceLoader([DictLoader, FileSystemLoader])` order). A configured
directory that does not exist logs a WARNING and is dropped; toolkit
construction never fails because of templates (S8).

**Selection** (G2): `template=` is used as given, then with `.j2` appended;
it must exist (`JiraTemplateNotFound`). Without it, the convention candidates
for the path's *kind* are tried in order, lower-cased, and the first that
exists wins; none ⇒ pass-through. Names containing `..`, starting with `/`
or containing `\` are rejected up front (S4). For update and comment the
project comes from the issue key via the existing `_project_of()` — no
metadata fetch (S3).

**Context** (G3): a flat, JSON-serializable dict of the call's own arguments
*as passed* (post-default, pre-resolution — no accountIds, no component ids,
no Jira objects) merged with `template_params`, which override on clash
(S5). Convention selection itself uses the resolved project and canonical
issuetype.

**Strictness** (G4): before rendering, the helper parses the template source
(`env.loader.get_source` + `jinja2.meta.find_undeclared_variables`), subtracts
the context keys and `env.globals`, and raises `JiraTemplateError` listing
every missing name (S9). A template that renders to empty/whitespace is also
an error. When a template is applied and `fields` already carries a
`description`, the call fails with `JiraTemplateError` instead of letting the
`fields` merge silently overwrite the rendered text (S6).

**Length** (G8): the final rendered string is capped at
`_MAX_JIRA_TEXT_CHARS = 32_767`; overflow is truncated so that the trailing
marker `"\n\n... (truncated)"` fits inside the cap, with a WARNING (S7).

**Discovery** (G6): a new read tool `jira_list_templates` returns the logical
template names (`env.list_templates()` filtered to `*.j2`), optionally
narrowed by project prefix — never filesystem paths or template source.

### Component Diagram
```
jira_create_issue ─┐                                  ┌─ TemplateEngine (parrot.template)
jira_update_issue ─┼─► _render_jira_text(kind, …) ───►│   env: autoescape=False, StrictUndefined
jira_add_comment  ─┘        │                         │   ChoiceLoader[DictLoader(templates),
                            │                         │                FileSystemLoader(templates_dir)]
                            ├─ _resolve_template_name()   (explicit → convention → None)
                            ├─ _build_template_context()  (call fields ∪ template_params)
                            ├─ _assert_template_variables()  (jinja2.meta → JiraTemplateError)
                            └─ _guard_text_length()      (32 767 cap, marker)
jira_list_templates ──────────────────────────────────► env.list_templates()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JiraToolkit.__init__` (jiratoolkit.py:698) | extends | new kwargs `templates_dir`, `templates`; `_cfg("JIRA_TEMPLATES_DIR")` |
| `JiraToolkit.jira_create_issue` (:1781) | modifies | calls `_render_jira_text("create", …)` after `_validate_issue_type` |
| `JiraToolkit.jira_update_issue` (:1916) | modifies | calls `_render_jira_text("update", …)`; `jira_update_ticket(**kwargs)` alias (:3384) inherits it |
| `JiraToolkit.jira_add_comment` (:2027) | modifies | calls `_render_jira_text("comment", …)`; `body` becomes optional |
| `CreateIssueInput` / `UpdateIssueInput` / `AddCommentInput` (:375 / :408 / :455) | extends | `template`, `template_params` fields |
| `parrot.template.TemplateEngine` + `JinjaConfig` (engine.py:47 / :26) | uses | unchanged; wrapped lazily |
| `AbstractToolkit._generate_tools` (parrot/tools/toolkit.py:575) | relies on | underscore-prefixed helpers are never exposed; `jira_list_templates` is auto-registered |
| `JiraToolkit._pre_execute` (:999) | relies on | runs before `jira_list_templates` like every tool (auth error surfaces there) |
| `test_jiratoolkit_delegation.py::INIT_PARAMS_BASELINE` (:23) | modifies | baseline extended with the two new kwargs |

### Data Models
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (additions)

class JiraTemplateError(ValueError):
    """A Jira text template could not be applied (missing variables, empty render,
    conflicting ``fields['description']``, no templates configured, bad name)."""

class JiraTemplateNotFound(JiraTemplateError):
    """An explicitly requested template name does not exist in any loader."""

class ListTemplatesInput(BaseModel):
    """Input for listing available Jira text templates."""
    project: Optional[str] = Field(default=None, description="Only templates under this project folder, e.g. 'NAV'")

# Fields added to CreateIssueInput, UpdateIssueInput and AddCommentInput:
template: Optional[str] = Field(
    default=None,
    description=("Template name used to compose the text (e.g. 'nav/bug' or 'nav/bug.j2'); "
                 "see jira_list_templates. Omit to apply the configured convention template, if any."),
)
template_params: Optional[Dict[str, Any]] = Field(
    default=None,
    description="Extra variables available to the template; they override same-named call fields.",
    json_schema_extra={"x-exclude-form": True},
)
# AddCommentInput.body becomes Optional[str] (S2); required unless a template resolves.
```

**Template context (frozen shape, S5)** — flat dict, all values JSON-serializable, as passed by the caller:

| kind | keys |
|---|---|
| `create` | `project` (post-default), `summary`, `issuetype` (canonical), `description`, `assignee`, `priority`, `labels`, `components`, `due_date`, `parent`, `original_estimate` |
| `update` | `issue`, `project` (from key), `summary`, `description`, `labels`, `due_date`, `priority`, `issuetype` (dicts as passed) |
| `comment` | `issue`, `project` (from key), `body`, `is_internal` |

`template_params` entries are merged last and win on clash. `fields` is never
part of the context.

### New Public Interfaces
```python
# Tool-facing (auto-registered by AbstractToolkit._generate_tools)
@tool_schema(ListTemplatesInput)
async def jira_list_templates(self, project: Optional[str] = None) -> Dict[str, Any]:
    """List the Jira text templates available to jira_create_issue / jira_update_issue /
    jira_add_comment. Returns {"ok": True, "templates": [...names...], "templates_dir": str|None}."""

# Constructor (new keyword-only-by-position kwargs appended after verify_credentials)
JiraToolkit(..., verify_credentials: bool = True,
            templates_dir: Optional[Union[str, Path]] = None,
            templates: Optional[Mapping[str, str]] = None, **kwargs)

# Config key
JIRA_TEMPLATES_DIR   # navconfig / env, resolved via _cfg(); explicit kwarg wins
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Config & engine bootstrap | yes | kwargs + `_cfg("JIRA_TEMPLATES_DIR")`; lazy `_get_template_engine()`; `JinjaConfig(autoescape=False, extensions=["jinja2.ext.do","jinja2.ext.loopcontrols"])`; missing dir ⇒ WARNING + drop; errors + constants below | — |
| M2: Resolution & rendering helper | yes | candidate order per kind fixed in §2; name validation rule; context table; `jinja2.meta` pre-check; cap 32 767 + marker | — |
| M3: Write-path integration | yes | exact insertion anchors in §6; `fields['description']` conflict ⇒ `JiraTemplateError`; `body` optional | — |
| M4: `jira_list_templates` | yes | `env.list_templates()` filtered `.j2`, sorted, optional project prefix (lower-cased) | — |
| M5: Tests, baseline, docs | yes | matrix in §4; `INIT_PARAMS_BASELINE` += 2 entries; `docs/tools/jira-templates.md` | — |

### Module 1: Configuration & engine bootstrap
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: accept/resolve template configuration, define the error
  types and constants, build the Jira-safe `TemplateEngine` lazily.
- **Depends on**: `parrot.template.TemplateEngine` / `JinjaConfig` (existing).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # modifies packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
  from pathlib import Path                                   # new import (verified absent)
  from typing import Mapping                                 # add to the existing typing import (:30)
  from jinja2 import TemplateNotFound, meta as jinja_meta    # verified: jinja2 3.1.6
  from parrot.template import JinjaConfig, TemplateEngine    # verified: parrot/template/__init__.py:1

  _TEMPLATE_SUFFIX = ".j2"
  _MAX_JIRA_TEXT_CHARS = 32_767           # Jira Cloud text-field limit (description and comment)
  _TRUNCATION_MARKER = "\n\n... (truncated)"
  _JIRA_TEMPLATE_EXTENSIONS = ("jinja2.ext.do", "jinja2.ext.loopcontrols")

  class JiraTemplateError(ValueError): ...          # see §2 Data Models
  class JiraTemplateNotFound(JiraTemplateError): ...

  class JiraToolkit(AbstractToolkit):               # verified: jiratoolkit.py:596
      def __init__(self, ..., verify_credentials: bool = True,          # verified: :712
                   templates_dir: Optional[Union[str, Path]] = None,
                   templates: Optional[Mapping[str, str]] = None,
                   **kwargs):
          """... adds: ``self.templates_dir: Optional[Path]`` (kwarg, else
          ``_cfg('JIRA_TEMPLATES_DIR')``; WARNING + None when the path is not a
          directory), ``self._inline_templates: Dict[str, str]`` and
          ``self._template_engine: Optional[TemplateEngine] = None`` (lazy)."""

      def _get_template_engine(self) -> Optional[TemplateEngine]:
          """Build the engine on first call: ``TemplateEngine(template_dirs=[self.templates_dir]
          if set else None, config=JinjaConfig(autoescape=False,
          extensions=list(_JIRA_TEMPLATE_EXTENSIONS)))`` then ``add_templates(self._inline_templates)``.
          Returns None when neither a directory nor inline templates are configured."""
  ```

### Module 2: Resolution & rendering helper
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: pick the template, build the context, enforce
  strictness, render, guard length. Pure with respect to Jira transport.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py (private helpers on JiraToolkit)
  @staticmethod
  def _validate_template_name(name: str) -> str:
      """Reject names containing '..', a leading '/', or a backslash (JiraTemplateError);
      return the name unchanged otherwise."""

  def _template_candidates(self, kind: Literal["create", "update", "comment"],
                           project: Optional[str], issuetype: Optional[str]) -> List[str]:
      """Ordered, lower-cased convention candidates:
      create  → ['<project>/<issuetype>.j2', '<project>/_default.j2', '_default.j2']
      update  → ['<project>/update.j2', 'update.j2']
      comment → ['<project>/comment.j2', 'comment.j2']
      Entries needing a missing project/issuetype are omitted."""

  def _resolve_template_name(self, engine: TemplateEngine, kind: str, template: Optional[str],
                             project: Optional[str], issuetype: Optional[str]) -> Optional[str]:
      """Explicit ``template`` (as given, then + '.j2') must exist → JiraTemplateNotFound;
      else first existing convention candidate (via ``engine.env.get_template``); else None."""

  @staticmethod
  def _build_template_context(call_fields: Dict[str, Any],
                              template_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
      """Flat dict: ``dict(call_fields)`` updated with ``template_params`` (params win)."""

  @staticmethod
  def _assert_template_variables(engine: TemplateEngine, name: str, context: Dict[str, Any]) -> None:
      """``jinja_meta.find_undeclared_variables(env.parse(source))`` − context − env.globals;
      non-empty ⇒ JiraTemplateError("template '<name>' is missing variables: a, b")."""

  def _guard_text_length(self, text: str, *, field: str) -> str:
      """Return ``text`` unchanged when ≤ _MAX_JIRA_TEXT_CHARS; otherwise truncate so that
      ``text + _TRUNCATION_MARKER`` fits exactly within the cap and log a WARNING."""

  async def _render_jira_text(self, kind: Literal["create", "update", "comment"], *,
                              text: Optional[str], template: Optional[str],
                              template_params: Optional[Dict[str, Any]],
                              call_fields: Dict[str, Any], project: Optional[str],
                              issuetype: Optional[str] = None) -> Optional[str]:
      """Single text-shaping seam for all write paths.
      - engine None and template None → return ``text`` unchanged (byte-for-byte).
      - engine None and template given → JiraTemplateError('no templates configured').
      - resolve name (explicit → convention); None → return ``text`` unchanged.
      - context = _build_template_context(call_fields, template_params); assert variables;
        ``await engine.render(name, context)``; empty/whitespace result → JiraTemplateError.
      - return _guard_text_length(rendered, field='description'|'body').
      Never performs Jira I/O."""
  ```

### Module 3: Write-path integration
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: wire the three input models and three write tools to the
  helper; enforce the `fields['description']` conflict rule; make comment
  `body` optional.
- **Depends on**: Module 2.
- **Interface Skeleton**:
  ```python
  # modifies CreateIssueInput (:375-405), UpdateIssueInput (:408-437), AddCommentInput (:455-467)
  #   + fields `template`, `template_params` (see §2 Data Models); AddCommentInput.body: Optional[str] = Field(default=None, ...)

  async def jira_create_issue(self, project=None, summary="", issuetype=None, description=None, ...,
                              fields=None, template: Optional[str] = None,
                              template_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:  # verified: :1781
      """... After ``canonical_issuetype`` (:1856): description = await self._render_jira_text(
      "create", text=description, template=template, template_params=template_params,
      call_fields={project, summary, issuetype=canonical_issuetype, description, assignee, priority,
      labels, components, due_date, parent, original_estimate}, project=project,
      issuetype=canonical_issuetype). If a template was applied and ``fields`` contains
      'description' → JiraTemplateError before building issue_fields."""

  async def jira_update_issue(self, issue, summary=None, description=None, ..., fields=None,
                              template: Optional[str] = None,
                              template_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:  # verified: :1916
      """... project = self._project_of(issue) (verified :1605); description rendered with kind
      'update' before ``update_fields['description']`` (:1956); same ``fields`` conflict rule.
      ``jira_update_ticket(**kwargs)`` (:3384) forwards the new kwargs unchanged."""

  async def jira_add_comment(self, issue: str, body: Optional[str] = None, is_internal: bool = False,
                             attachments: Optional[List[str]] = None, template: Optional[str] = None,
                             template_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:  # verified: :2027
      """... body = await self._render_jira_text('comment', text=body, ...,
      call_fields={issue, project, body, is_internal}, project=self._project_of(issue));
      if the result is None/empty → ValueError('body is required when no template applies')
      before ``self.jira.add_comment`` (:2050)."""
  ```

### Module 4: `jira_list_templates` tool
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: agent-facing discovery of template names.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  class ListTemplatesInput(BaseModel): ...     # see §2 Data Models

  @tool_schema(ListTemplatesInput)             # pattern verified: :2270 (jira_get_projects, unrestricted read)
  async def jira_list_templates(self, project: Optional[str] = None) -> Dict[str, Any]:
      """Return {"ok": True, "templates": sorted names ending in '.j2' from
      engine.env.list_templates() (filtered to '<project.lower()>/' when given),
      "templates_dir": str(self.templates_dir) or None}. With no engine: templates=[]."""
  ```

### Module 5: Tests, signature baseline, docs
- **Path**: `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates.py` (new),
  `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py` (baseline),
  `docs/tools/jira-templates.md` (new)
- **Responsibility**: the §4 matrix; extend `INIT_PARAMS_BASELINE` with
  `"templates_dir", "templates"` (inserted before `"kwargs"`); operator doc
  (config keys, convention layout, context table, error behaviour, example
  `nav/bug.j2`).
- **Depends on**: Modules 3 and 4.

---

## 4. Test Specification

### Unit Tests — `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates.py`

Fixtures follow `test_jiratoolkit_oauth.py`: `patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA)`,
autouse `_clean_env` (extended with `JIRA_TEMPLATES_DIR`) and `_stub_nav_config`; the toolkit is
built with `auth_type="token_auth", server_url=..., token=..., verify_credentials=False`; a
`tmp_path` templates dir and `templates={...}` mappings; `self.jira` replaced by a `MagicMock`
whose `create_issue` / `add_comment` / `issue().update` record their kwargs.

| Test | Module | Description |
|---|---|---|
| `test_no_templates_payload_unchanged` | M3 | no dir, no mapping, no `template` ⇒ `create_issue(fields=...)` payload identical to today (description verbatim, no extra keys) |
| `test_engine_is_lazy_and_none_without_config` | M1 | `_template_engine is None` after init; `_get_template_engine()` returns None |
| `test_missing_templates_dir_warns_and_drops` | M1 | `JIRA_TEMPLATES_DIR=/nope` ⇒ WARNING logged, `templates_dir is None`, construction succeeds |
| `test_kwarg_wins_over_env` | M1 | `templates_dir=` kwarg beats `JIRA_TEMPLATES_DIR` |
| `test_autoescape_disabled` | M1 | template `{code}{{ description }}{code} <b>` renders raw (`<b>` and braces intact) |
| `test_inline_templates_shadow_filesystem` | M1 | same name in `templates=` and on disk ⇒ inline wins |
| `test_explicit_template_with_and_without_suffix` | M2 | `template="nav/bug"` and `"nav/bug.j2"` both resolve |
| `test_explicit_template_missing_raises_not_found` | M2 | `JiraTemplateNotFound`; `create_issue` never called |
| `test_explicit_template_without_engine_raises` | M2 | no config + `template=` ⇒ `JiraTemplateError` |
| `test_name_traversal_rejected` | M2 | `../x`, `/etc/x`, `a\b` ⇒ `JiraTemplateError` |
| `test_convention_create_order` | M2 | `nav/bug.j2` → `nav/_default.j2` → `_default.j2` (parametrized), lower-cased from `project="NAV"`, `issuetype="Bug"` |
| `test_convention_comment_and_update_kinds` | M2 | comment uses `nav/comment.j2`/`comment.j2`; update uses `nav/update.j2`/`update.j2`; project derived from `issue="NAV-1"` |
| `test_explicit_overrides_convention` | M2 | both present ⇒ explicit used |
| `test_context_params_win` | M2 | `summary` given both as call field and in `template_params` ⇒ params value rendered |
| `test_context_contains_only_frozen_keys` | M2 | `{{ assignee }}` renders the raw email, no `accountId` key available; `fields` not in context |
| `test_missing_variables_named_and_no_transport` | M2 | template uses `{{ a }} {{ b }}`; error message lists `a, b`; `create_issue` not called |
| `test_empty_render_raises` | M2 | template rendering to whitespace ⇒ `JiraTemplateError` |
| `test_length_guard_truncates_with_marker` | M2 | rendered 40 000 chars ⇒ len == 32 767, endswith marker, WARNING logged |
| `test_fields_description_conflict_raises` | M3 | template applied + `fields={"description": ...}` ⇒ `JiraTemplateError` (create and update) |
| `test_fields_description_without_template_passthrough` | M3 | no template ⇒ `fields` merge behaves exactly as today |
| `test_update_renders_before_update_fields` | M3 | `issue().update(fields={"description": rendered})` |
| `test_update_ticket_alias_forwards_template_kwargs` | M3 | `jira_update_ticket(issue=..., template=...)` reaches the renderer |
| `test_comment_template_only_body_optional` | M3 | `body=None` + template ⇒ comment posted with rendered text |
| `test_comment_without_body_or_template_raises` | M3 | `ValueError`, no transport |
| `test_comment_body_wrapped_by_template` | M3 | `{{ body }}` composition |
| `test_list_templates_names_only` | M4 | returns sorted `.j2` names, no paths; `project="NAV"` filters to `nav/` prefix; no engine ⇒ `[]` |
| `test_list_templates_is_unrestricted_read` | M4 | no `_required_permissions` on `jira_list_templates` |
| `test_init_signature_unchanged` (updated) | M5 | `INIT_PARAMS_BASELINE` carries `templates_dir`, `templates` before `kwargs` |

### Integration Tests
| Test | Description |
|---|---|
| `packages/ai-parrot/tests/test_jiratoolkit_permissions.py` (existing, unchanged) | still passes: write tools keep `jira.write`; new read tool is unrestricted |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_kind_routing.py` (existing, unchanged) | `ResearchNode` → `jira_create_issue` call shape unaffected (no template kwargs passed) |

### Test Data / Fixtures
```python
@pytest.fixture
def templates_dir(tmp_path):
    (tmp_path / "nav").mkdir()
    (tmp_path / "nav" / "bug.j2").write_text("h2. Bug\n{{ description }}\n\nReporter: {{ reporter }}")
    (tmp_path / "nav" / "comment.j2").write_text("(bot) {{ body }}")
    (tmp_path / "_default.j2").write_text("h2. {{ summary }}\n{{ description }}")
    return tmp_path

@pytest.fixture
def toolkit(templates_dir):
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        tk = JiraToolkit(auth_type="token_auth", server_url="https://x.atlassian.net",
                         token="t", verify_credentials=False, templates_dir=templates_dir)
    tk.jira = MagicMock()
    return tk
```

Validation commands:
```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest \
  packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates.py \
  packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py \
  packages/ai-parrot/tests/test_jiratoolkit_permissions.py -q
ruff check packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates.py
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — With no `templates_dir`, no `JIRA_TEMPLATES_DIR`, no `templates` and no `template=`, the `fields` dict passed to `JIRA.create_issue`, the `update(fields=…)` call and the `add_comment(...)` call are byte-for-byte identical to the pre-feature behaviour (G7).
- [ ] AC2 — `templates_dir=` kwarg > `JIRA_TEMPLATES_DIR` (navconfig/env) precedence; a missing directory logs a WARNING and does not raise (G1, S8).
- [ ] AC3 — In-memory `templates=` entries shadow same-named filesystem templates.
- [ ] AC4 — The engine renders with autoescape disabled: `{code}`, `*bold*`, `<`, `>` survive verbatim (G5).
- [ ] AC5 — `template=` is honoured with or without the `.j2` suffix; a non-existent explicit name raises `JiraTemplateNotFound` and no Jira call is made (G2).
- [ ] AC6 — Convention lookup order and lower-casing per kind exactly as §2 (`create`: `<project>/<issuetype>.j2` → `<project>/_default.j2` → `_default.j2`; `comment`: `<project>/comment.j2` → `comment.j2`; `update`: `<project>/update.j2` → `update.j2`); no candidate ⇒ pass-through (G2, S3).
- [ ] AC7 — Context = frozen call-field table (§2) ∪ `template_params`, params win; `fields` is never in the context; no resolved accountIds/component ids (G3, S5).
- [ ] AC8 — A template referencing undeclared variables fails with `JiraTemplateError` whose message names every missing variable, before any Jira request (G4, S9).
- [ ] AC9 — A template rendering to empty/whitespace raises `JiraTemplateError`.
- [ ] AC10 — Template applied + `fields["description"]` present ⇒ `JiraTemplateError` (create and update) (S6).
- [ ] AC11 — Rendered text > 32 767 chars is truncated so that text + marker == 32 767 chars, with a WARNING; applies to description and comment (G8, S7).
- [ ] AC12 — `jira_add_comment` accepts `body=None` when a template resolves; raises `ValueError` without transport when neither body nor template applies (S2).
- [ ] AC13 — `jira_list_templates` returns sorted logical `.j2` names (optionally filtered by project prefix), never paths or source; it carries no `jira.write` permission (G6, S4).
- [ ] AC14 — Template names containing `..`, a leading `/`, or `\` are rejected with `JiraTemplateError`.
- [ ] AC15 — `jira_update_ticket(**kwargs)` forwards `template` / `template_params`.
- [ ] AC16 — `INIT_PARAMS_BASELINE` updated deliberately; `test_init_signature_unchanged`, `test_write_methods_still_use_self_jira` and `test_jiratoolkit_permissions.py` pass.
- [ ] AC17 — `parrot/template/engine.py`, `jira_config.py`, `parrot/interfaces/jira.py` and `research.py` are not modified (non-goals).
- [ ] AC18 — `docs/tools/jira-templates.md` documents config keys, convention layout, context table, error behaviour and a worked `nav/bug.j2` example.
- [ ] AC19 — `ruff check` clean on touched files; all §4 tests pass under the stated `PYTHONPATH`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against commit `77a870889` (dev, 2026-10-07).

### Verified Imports
```python
from parrot.template import JinjaConfig, TemplateEngine          # verified: packages/ai-parrot/src/parrot/template/__init__.py:1
from jinja2 import TemplateNotFound, StrictUndefined, meta         # verified: jinja2 3.1.6 in .venv; engine.py:9-20 imports the same module
from jinja2.exceptions import UndefinedError                       # verified: jinja2 3.1.6
from .toolkit import AbstractToolkit                               # verified: jiratoolkit.py:55 (re-export of parrot.tools.toolkit)
from .decorators import tool_schema, requires_permission           # verified: jiratoolkit.py:56 (re-export of parrot.tools.decorators:39 / :9)
from parrot_tools.jiratoolkit import JiraToolkit                   # verified: tests/unit/test_jiratoolkit_delegation.py:17-21
```
Existing imports in `jiratoolkit.py` (:29-57): `typing` has `Any, Dict, List, Optional, Sequence, Union, Literal, TypedDict` — **`Mapping` and `pathlib.Path` are NOT imported** (verified by grep); add them.

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class CreateIssueInput(BaseModel):            # line 375-405; description: Optional[str] (:379); fields: Optional[Dict[str, Any]] with x-exclude-form (:401-405)
class UpdateIssueInput(BaseModel):            # line 408-437; description: Optional[str] (:413); fields (:437)
class AddCommentInput(BaseModel):             # line 455-467; body: str (:459) REQUIRED today; is_internal (:460); attachments (:461-467)
class JiraToolkit(AbstractToolkit):           # line 596
    config_model = JiraToolkitConfig          # line 659 (jira_config.py:12-24, extra="forbid") — NOT modified
    _DEFAULT_WORKFLOW_KEY = "_DEFAULT"        # line 693
    def __init__(self, server_url=None, auth_type=None, username=None, password=None, token=None,
                 oauth_consumer_key=None, oauth_key_cert=None, oauth_access_token=None,
                 oauth_access_token_secret=None, default_project=None, credential_resolver=None,
                 workflow_paths: Optional[Dict[str, Union[str, List[str]]]] = None,
                 verify_credentials: bool = True, **kwargs)                       # line 698-716
        def _cfg(key: str, default: Optional[str] = None) -> Optional[str]      # line 718-723 (navconfig → env)
        self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")                   # line 772 (last JIRA_DEFAULT_* line)
        self.workflow_paths: Dict[str, List[str]] = {}                          # line 788 (per-project map precedent, :774-803)
        self._auth_error: Optional[str] = None                                  # line 810
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None          # line 999 (runs before every tool)
    @staticmethod
    def _project_of(issue: str) -> Optional[str]                                # line 1605-1611 ("NAV-8350" → "NAV")
    @requires_permission("jira.write")                                          # line 1779
    @tool_schema(CreateIssueInput)                                              # line 1780
    async def jira_create_issue(self, project=None, summary="", issuetype=None, description=None,
                                assignee=None, priority=None, labels=None, components=None,
                                due_date=None, parent=None, original_estimate=None,
                                fields=None) -> Dict[str, Any]                  # line 1781-1795
        canonical_issuetype = await self._validate_issue_type(project, issuetype)  # line 1856
        if description:                                                         # line 1865
            issue_fields["description"] = description                           # line 1866
        if fields: issue_fields.update(fields)                                  # ~line 1890 (fields merge AFTER description)
            return self.jira.create_issue(fields=issue_fields)                  # line 1895
    @tool_schema(UpdateIssueInput)                                              # line 1915
    async def jira_update_issue(self, issue, summary=None, description=None, assignee=None,
                                acceptance_criteria=None, original_estimate=None, time_tracking=None,
                                affected_versions=None, due_date=None, labels=None, issuetype=None,
                                priority=None, fields=None) -> Dict[str, Any]   # line 1916-1931
        if description is not None:                                             # line 1956
            update_fields["description"] = description                          # line 1957
        def _run(): obj = self.jira.issue(issue); obj.update(**update_kwargs)   # line 1990-1994 (blocking fetch — no async hook)
    @tool_schema(AddCommentInput)                                               # line 2026
    async def jira_add_comment(self, issue: str, body: str, is_internal: bool = False,
                               attachments: Optional[List[str]] = None) -> Dict[str, Any]  # line 2027-2032
            return self.jira.add_comment(issue, body, is_internal=is_internal)  # line 2050
        comment = await asyncio.to_thread(_run)                                 # line 2052
    @tool_schema(GetProjectsInput)                                              # line 2270 — unrestricted read-tool pattern
    async def jira_get_projects(self) -> Dict[str, Any]                         # line 2271
    @requires_permission("jira.write") @tool_schema(UpdateIssueInput)           # line 3382-3383
    async def jira_update_ticket(self, **kwargs) -> Dict[str, Any]              # line 3384-3386 (forwards to jira_update_issue)

# packages/ai-parrot/src/parrot/template/engine.py
@dataclass
class JinjaConfig:                            # line 26-44
    template_dirs: list[Path]; extensions: list[str] (default includes jinja2_time / jinja2_iso8601 / jinja2_humanize_extension)
    autoescape: Any = select_autoescape(["html","xml","j2","jinja","jinja2"])   # line 40 — MUST be overridden to False
    undefined: Any = StrictUndefined                                           # line 41
class TemplateEngine:                         # line 47-242
    def __init__(self, template_dirs=None, *, extensions=None, bytecode_cache_dir=None, filters=None,
                 globals_=None, config: Optional[JinjaConfig] = None, debug=False)  # line 56-66
        # raises ValueError("Template directory not found") for a missing dir       # line 78-84
        self.env = Environment(loader=ChoiceLoader([DictLoader, FileSystemLoader]) | DictLoader, enable_async=True, ...)  # line 102-118
    def add_templates(self, templates: Mapping[str, str]) -> None              # line 164-170
    def get_template(self, name: str)   # raises FileNotFoundError on miss      # line 172-179
    async def render(self, name: str, params=None) -> str   # TemplateError → ValueError  # line 181-194
    async def render_string(self, source: str, params=None) -> str             # line 196-208

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None)   # line 39 (sets func._args_schema / _tool_description)
def requires_permission(*permissions: str)                                     # line 9

# packages/ai-parrot/src/parrot/tools/toolkit.py
def _generate_tools(self) -> None   # line 575; skips names starting with "_" (:583) and get_tools/config_options/… (:587-599)

# packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py
INIT_PARAMS_BASELINE: tuple[str, ...] = (..., "workflow_paths", "verify_credentials", "kwargs")  # line 23-39
def test_init_signature_unchanged(self)   # line 105-107
def test_write_methods_still_use_self_jira(self)   # line 190-195 — "self.jira" must remain in create/comment source
with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):   # line 90 (construction pattern)
```

Verified jinja2 3.1.6 behaviour (`.venv`): `Environment.list_templates()` works through `ChoiceLoader`;
`env.loader.get_source(env, name) -> (source, filename, uptodate)`;
`jinja2.meta.find_undeclared_variables(env.parse(source))` returns the undeclared names;
`FileSystemLoader.get_source(env, "../etc/passwd")` raises `TemplateNotFound`.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JiraToolkit._get_template_engine()` | `TemplateEngine(template_dirs=…, config=JinjaConfig(...))` + `add_templates()` | constructor + method call | engine.py:56, :164 |
| `_render_jira_text("create")` | `jira_create_issue` after `canonical_issuetype` | method call | jiratoolkit.py:1856-1866 |
| `_render_jira_text("update")` | `jira_update_issue` before `update_fields["description"]` | method call | jiratoolkit.py:1956-1957 |
| `_render_jira_text("comment")` | `jira_add_comment` before `_run` | method call | jiratoolkit.py:2049-2052 |
| `_assert_template_variables` | `engine.env.loader.get_source` + `jinja2.meta` | function call | engine.py:102-118; jinja2 3.1.6 |
| `jira_list_templates` | `engine.env.list_templates()` | method call | jinja2 3.1.6 |
| `templates_dir` config | `_cfg("JIRA_TEMPLATES_DIR")` | existing helper | jiratoolkit.py:718-723 |
| project for update/comment | `JiraToolkit._project_of(issue)` | staticmethod call | jiratoolkit.py:1605 |

### Does NOT Exist (Anti-Hallucination)
- ~~any `template`, `jinja`, `render` symbol in `jiratoolkit.py`~~ — none today (F002); everything in §3 is new.
- ~~`TemplateEngine.list_templates()`~~ — not a method; use `engine.env.list_templates()`.
- ~~`TemplateEngine.has_template()` / `.exists()`~~ — do not exist; probe with `engine.env.get_template(name)` catching `TemplateNotFound`, or `engine.get_template` catching `FileNotFoundError`.
- ~~`JinjaConfig(undefined="strict")`~~ — `undefined` takes a class (`StrictUndefined`), already the default.
- ~~`JiraToolkitConfig.templates_dir`~~ — intentionally NOT added (U1); `extra="forbid"` would reject it anyway.
- ~~`pathlib.Path` / `typing.Mapping` in `jiratoolkit.py`~~ — not imported yet; M1 adds them.
- ~~a markdown→ADF converter (`to_adf`, `markdown_to_jira`)~~ — none in the toolkit or interfaces (F014).
- ~~`JiraInterface` write methods~~ — the read interface is read-only (`test_no_write_methods_exposed`).
- ~~`ResearchNode` passing `template=`~~ — it passes `summary/issuetype/description/assignee/fields` only (research.py:363-369); do not change it.
- ~~`packages/ai-parrot-tools/tests/conftest.py`~~ — only `tests/unit/conftest.py` exists (NavigatorToolkit fixtures; nothing Jira-related to reuse).

### Edit Sites (Blueprint Anchors)

Verified against: `77a870889` (anchors re-counted with `grep -c -F -x`).

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M1 imports) | `from .jira_config import JiraToolkitConfig` | `jiratoolkit.py:57` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 CreateIssueInput fields) | `    original_estimate: Optional[str] = Field(default=None, description="Original time estimate, e.g. '8h', '2d', '30m'")` | `jiratoolkit.py:399` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 UpdateIssueInput fields) | `    fields: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary field updates dict")` | `jiratoolkit.py:437` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 AddCommentInput body/fields) | `    is_internal: bool = Field(default=False, description="If true, mark as internal (Service Desk)")` | `jiratoolkit.py:460` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M1 class constants, after) | `    _DEFAULT_WORKFLOW_KEY = "_DEFAULT"` | `jiratoolkit.py:693` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M1 `__init__` kwargs) | `        verify_credentials: bool = True,` | `jiratoolkit.py:712` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M1 config resolution, after) | `        self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")` | `jiratoolkit.py:772` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M1 engine attr, before) | `        self._auth_error: Optional[str] = None` | `jiratoolkit.py:810` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M2 helpers, insert after `_project_of`) | `    def _project_of(issue: str) -> Optional[str]:` | `jiratoolkit.py:1605` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 create signature) | `    @tool_schema(CreateIssueInput)` | `jiratoolkit.py:1780` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 create render point) | `        canonical_issuetype = await self._validate_issue_type(project, issuetype)` | `jiratoolkit.py:1856` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 create description) | `            issue_fields["description"] = description` | `jiratoolkit.py:1866` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 update signature) | `    @tool_schema(UpdateIssueInput)` — **2 occurrences**; use the one directly followed by `    async def jira_update_issue(` (:1916), NOT the `jira_update_ticket` alias at :3383 | `jiratoolkit.py:1915` | 2 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 update description) | `            update_fields["description"] = description` | `jiratoolkit.py:1957` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 comment signature) | `    @tool_schema(AddCommentInput)` | `jiratoolkit.py:2026` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 comment render point) | `            return self.jira.add_comment(issue, body, is_internal=is_internal)` | `jiratoolkit.py:2050` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M4 tool, insert before) | `    @tool_schema(GetProjectsInput)` | `jiratoolkit.py:2270` | 1 |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py` | MODIFY (M5 baseline) | `    "verify_credentials",` | `test_jiratoolkit_delegation.py:38` | 1 |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates.py` | CREATE | — | — | — |
| `docs/tools/jira-templates.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Lazy engine with a `JinjaConfig` override** — `infographic_toolkit.py:307-321`
  builds `TemplateEngine(template_dirs=…, config=JinjaConfig(autoescape=True))`
  only when templates are configured; mirror it with `autoescape=False`.
- **`_cfg()` precedence** (explicit kwarg > navconfig > env) — jiratoolkit.py:718-772;
  `JIRA_TEMPLATES_DIR` joins the `JIRA_DEFAULT_*` family.
- **Per-project convention keyed by upper-cased project** — `workflow_paths`
  (:774-803) and `_project_of()` (:1605); the template convention lower-cases
  for the filesystem lookup instead.
- **Transport inside `asyncio.to_thread(_run)`** stays untouched; rendering
  happens before `_run` is defined, in the async part of each method.
- **`x-exclude-form`** on dict-typed fields (`fields`, :401-405) — reuse for
  `template_params`.
- **Unrestricted read tools carry only `@tool_schema`** (`jira_get_projects`,
  :2270); `jira_list_templates` follows that, and must NOT appear in
  `test_write_methods_annotated`'s list.
- **Tests**: `patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA)` + autouse env
  cleaners from `test_jiratoolkit_oauth.py:45-76`.
- Logging through `self.logger` (set at :727); `black` 120 cols; Google
  docstrings; every new tool method has a docstring (it is the LLM description).

### Known Risks / Gotchas
- **Autoescape**: `JinjaConfig.autoescape` defaults to `select_autoescape([... "j2", "jinja", "jinja2"])`
  — with the `.j2` convention every template would be HTML-escaped. Always
  pass `autoescape=False`; AC4 guards it.
- **Engine extension defaults**: `JinjaConfig.extensions` lists
  `jinja2_time`, `jinja2_iso8601`, `jinja2_humanize_extension` — installed in
  the dev venv but **undeclared** in both `pyproject.toml`s. The Jira engine
  passes `extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"]` so a
  production install without those packages cannot fail at first render.
- **`TemplateEngine.__init__` raises on a missing dir** (engine.py:78-84):
  validate `templates_dir` in `__init__` (WARNING + drop) so the engine never
  sees a bad path (S8).
- **`TemplateEngine.render` collapses errors** into `ValueError`/`RuntimeError`
  (engine.py:181-194): the missing-variable check must run *before* `render`
  via `jinja2.meta` to satisfy U3; `TemplateNotFound` is probed separately
  (S9).
- **`fields` merge happens after `description`** in create (:~1890) and update
  — hence the explicit conflict rule (S6); without a template the merge is
  untouched (AC1).
- **`_pre_execute` gates every tool**, including `jira_list_templates`: an
  unauthenticated toolkit raises `AuthorizationRequired` before listing. This
  is consistent with every other tool and accepted; documented in
  `docs/tools/jira-templates.md`.
- **Signature pin**: `test_init_signature_unchanged` must be updated in the
  same task as the kwargs (AC16). The kwargs are appended *after*
  `verify_credentials` so positional callers (none known) are unaffected.
- **`test_write_methods_still_use_self_jira`** inspects the source of
  `jira_add_comment` / `jira_create_issue` for the literal `self.jira` — keep
  the transport lines inside those methods (do not move `_run` into the
  helper).
- **Comment `body` optional** changes the LLM-facing schema (required → optional);
  the docstring must tell the model that a body is required unless a template
  applies (S2).
- **Concurrent feature overlap**: brainstorms committed on dev today also
  touch `jira_add_comment` / `AddCommentInput` —
  `sdd/proposals/jiratoolkit-docx-support.brainstorm.md` (attachment helper
  convergence, lines 2055-2079) and
  `sdd/proposals/jiraspecialist-agent-multilang.brainstorm.md` Option B
  (write-side translate gate). Whichever lands second rebases; the render seam
  sits *before* `_run`, the attachment loop *after*, so a textual merge is
  expected, not a redesign.
- **Jira wiki markup vs ADF**: the pycontribs client used here speaks REST v2
  text; templates must be written in wiki markup (`h2.`, `{code}`, `*bold*`),
  not Markdown — the docs example must say so.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `jinja2` | `>=3.1` (already declared: ai-parrot `pyproject.toml:466`, ai-parrot-tools `pyproject.toml:52`) | template engine — **no new dependency** |

---

## 8. Open Questions

- [x] **Where do templates live / how configured?** — *Resolved in proposal (U1)*: Dir + in-memory mapping — `templates_dir` kwarg / `JIRA_TEMPLATES_DIR` env for files, plus an optional `templates={name: source}` mapping for programmatic use (mirrors infographic_toolkit). Agent Studio exposure not required. → §2 Overview, §3 M1.
- [x] **How is a template selected?** — *Resolved in proposal (U2)*: Explicit wins, convention fallback — `template='bug'` when given; otherwise look up `<PROJECT>/<issuetype>` then `_default` (like workflow_paths); otherwise no template. → §2, §3 M2, AC5/AC6.
- [x] **Missing placeholder policy?** — *Resolved in proposal (U3)*: Strict — fail with names: the tool call fails with a clear error listing the missing variables (StrictUndefined). → §3 M2, AC8.
- [x] **LLM-facing or operator-only?** — *Resolved in proposal (U4)*: Both — operator config auto-applies a default; the agent may list templates (`jira_list_templates`) and override by name via a `template` tool parameter. → §3 M4, AC13.
- [x] **Include `jira_update_issue`?** — *Resolved in proposal (U5)*: Create + comment + update — same `template` / `template_params` seam on all three write paths. → §3 M3, AC15.
- [x] **Convention key shape and extension?** — *Resolved at spec time*: `<project>/<issuetype>.j2`, lowercase (e.g. `nav/bug.j2` → `nav/_default.j2` → `_default.j2`); comments use `<project>/comment.j2` → `comment.j2`. → AC6.
- [x] **Overflow behaviour?** — *Resolved at spec time*: truncate with marker (cut to the cap minus a `... (truncated)` marker, log a WARNING). → AC11.
- [x] **Template context and clash precedence?** — *Resolved at spec time*: call fields + params, params win; no resolved values (accountIds) injected. → §2 Data Models, AC7.
- [x] **Update-path convention without an issuetype (S3)?** — *Resolved via design research*: no metadata fetch; update uses its own kind (`<project>/update.j2` → `update.j2`) with the project from the issue key. → AC6.
- [x] **Q1 — Should a later iteration let update/comment templates see the issue's current `issuetype` / `summary` (one extra read via `JiraInterface`)?** — *Owner: Jesus Lara*; deferred, not needed for v1 (S3 kept fetch-free).: notation in a follow-up
- [x] **Q2 — Expose `templates_dir` in `JiraToolkitConfig` for Agent Studio in a follow-up?** — *Owner: Jesus Lara*; declined for v1 (U1).: yes

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal**
> (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning high) · Status: completed
> · Transcript: `sdd/state/FEAT-637/design_research/` (brief, suggestions.json, codex.log, run.json, triage.md).
> All 10 suggestions' `affected_paths` passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Centralize rendering and template selection (architecture) | CONFIRM | one `_render_jira_text()` seam called after defaults/canonical-issuetype resolution in every write path; `engine.py` untouched | §2 Overview, §3 M2 |
| S2 | Permit template-only comments (api) | CONFIRM | `AddCommentInput.body` → `Optional[str]`; reject only when neither body nor template applies | §3 M3, AC12 |
| S3 | Define update fallback metadata resolution (architecture) | CONFIRM | verified: update fetches the issue inside the blocking `_run` (:1990-1994); resolved with a fetch-free per-kind convention (`<project>/update.j2`) and `_project_of()` | §2, §3 M2, AC6, §8 Q1 |
| S4 | Make template names canonical and listable (api) | CONFIRM | names = loader names; `.j2` optional on input; lower-casing only for convention; traversal names rejected; listing returns names only; no engine change | §3 M2/M4, AC5/AC13/AC14 |
| S5 | Freeze the template context shape (risk) | CONFIRM | frozen per-kind key table, flat and serializable, params win, no resolved ids | §2 Data Models, AC7 |
| S6 | Resolve conflicts with arbitrary `fields` (risk) | CONFIRM | template applied + `fields['description']` ⇒ `JiraTemplateError` | §3 M3, AC10 |
| S7 | Centralized, field-specific length guard (risk) | CONFIRM (toolkit) / REJECT (`research.py` leg) | guard on the final rendered value for description and comment, marker inside the cap; `research.py` is a non-goal and keeps its own guard | §3 M2, AC11, §1 Non-Goals |
| S8 | Missing template dirs must not hide config errors (architecture) | CONFIRM | lazy engine; configured-but-missing dir ⇒ WARNING + dropped; construction never raises | §3 M1, AC2 |
| S9 | Aggregate missing-variable diagnostics (risk) | CONFIRM | `jinja2.meta` pre-check naming every missing variable; `JiraTemplateNotFound` distinct; raised before transport | §3 M2, AC8 |
| S10 | Rendering test matrix (testing) | CONFIRM | new `test_jiratoolkit_templates.py` matrix; delegation test only gets the baseline update | §4 |

Summary: **10** confirmed (S7 partially: its `research.py` leg rejected) · **0** rejected outright · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-637-jiratoolkit-template-support`
  (from `origin/dev`); the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph** (evidence: §3 "Depends on"):
  - M2 → M1 (M2 calls `_get_template_engine()` and uses the M1 error classes/constants).
  - M3 → M2 (the three write paths call `_render_jira_text`).
  - M4 → M1 (`jira_list_templates` needs the engine).
  - M5 → M3, M4 (tests exercise the wired tools; baseline update needs M1's kwargs).
  - M3 and M4 have no edge between them and may run concurrently.
- **Shared files**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  is modified by M1–M4 (their tasks are serialized by `/sdd-task`);
  `test_jiratoolkit_delegation.py` by M5 only.
- **Exclusive resources**: none (no extension rebuild, no lockfile, no migration).
- **Cross-feature dependencies**: none must merge first. Watch the two
  brainstorms noted in §7 (docx-support, multilang) that plan edits around
  `jira_add_comment` / `AddCommentInput` — coordinate the merge order.
- **Validation inside the worktree**: `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`
  (see §4 commands); never `uv sync` in the worktree.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-07 | Jesus Lara / Claude Code | Initial draft from accepted proposal FEAT-637 + codex design research (10/10 confirmed) |
