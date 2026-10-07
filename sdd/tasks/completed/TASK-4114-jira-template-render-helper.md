# TASK-4114: Template resolution, context, strictness, length guard (`_render_jira_text`)

**Feature**: FEAT-637 — JiraToolkit Template Support
**Spec**: `sdd/specs/jiratoolkit-template-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4113
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** (G2, G3, G4, G8; AC5, AC6, AC7, AC8, AC9, AC11, AC14).
This is the single text-shaping seam every write path will call (spec S1). It
never performs Jira I/O.

---

## Scope

- Implement private helpers on `JiraToolkit`: `_validate_template_name`, `_template_candidates`, `_resolve_template_name`, `_build_template_context`, `_assert_template_variables`, `_guard_text_length`, `_render_jira_text`.
- Write `test_jiratoolkit_templates_render.py` exercising the helpers directly (no write tools).

**NOT in scope**: calling the helper from `jira_create_issue` / `jira_update_issue` / `jira_add_comment`, input-model fields and the `fields['description']` conflict (TASK-4115); `jira_list_templates` (TASK-4116).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | add the seven private helpers after `_project_of` |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_render.py` | CREATE | helper-level unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All already present after TASK-4113 (module scope of jiratoolkit.py):
from jinja2 import TemplateNotFound            # TASK-4113
from jinja2 import meta as jinja_meta          # TASK-4113
from parrot.template import TemplateEngine     # TASK-4113; verified packages/ai-parrot/src/parrot/template/__init__.py:1
# constants _TEMPLATE_SUFFIX, _MAX_JIRA_TEXT_CHARS, _TRUNCATION_MARKER; classes JiraTemplateError, JiraTemplateNotFound — TASK-4113
from typing import Literal                     # already at jiratoolkit.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
    @staticmethod
    def _project_of(issue: str) -> Optional[str]:   # line 1605-1611, upper-cases the key prefix ("NAV-8350" → "NAV")
    def _get_template_engine(self) -> Optional[TemplateEngine]   # TASK-4113

# packages/ai-parrot/src/parrot/template/engine.py
    async def render(self, name: str, params: Optional[Mapping[str, Any]] = None) -> str   # line 181-194
        # wraps TemplateError → ValueError, other errors → RuntimeError
    self.env   # jinja2.Environment (enable_async=True); env.get_template(name) raises TemplateNotFound
```
Verified jinja2 3.1.6 behaviour: `env.loader.get_source(env, name) -> (source, filename, uptodate)`;
`jinja_meta.find_undeclared_variables(env.parse(source))` returns a `set[str]`;
`FileSystemLoader.get_source(env, "../x")` raises `TemplateNotFound`.

### Does NOT Exist
- ~~`TemplateEngine.has_template()` / `.exists()` / `.list_templates()`~~ — probe with `engine.env.get_template(name)` catching `TemplateNotFound`.
- ~~any `_render_*` / `_template_*` helper in `jiratoolkit.py`~~ — none exist before this task.
- ~~an async hook inside `jira_update_issue._run`~~ — it is a blocking thread function; rendering must happen before it (spec S3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_render.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit._project_of",
    "sym:packages/ai-parrot/src/parrot/template/engine.py#TemplateEngine.render"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Candidate order and lower-casing are fixed by spec AC6:
  - `create`: `<project>/<issuetype>.j2` → `<project>/_default.j2` → `_default.j2`
  - `update`: `<project>/update.j2` → `update.j2`
  - `comment`: `<project>/comment.j2` → `comment.j2`
  Omit candidates whose project/issuetype is missing.
- Explicit `template`: try the name as given, then with `.j2` appended; neither exists ⇒ `JiraTemplateNotFound` (AC5).
- Strictness runs **before** `engine.render`, because `render` collapses errors into a generic `ValueError` (spec S9).
- Missing-variable message must list **all** names, sorted: `template 'nav/bug.j2' is missing variables: a, b`.
- Truncation: final length must equal exactly `_MAX_JIRA_TEXT_CHARS` with the marker counted inside (AC11).

---

## Implementation Blueprint

### Steps (in order)
1. Insert the helpers after `_project_of` — *why*: keeps template code next to the project-key helper it uses.
2. Write the pure helpers first (name validation, candidates, context, length guard) — *why*: they are trivially testable without an engine.
3. Write `_resolve_template_name`, `_assert_template_variables`, then `_render_jira_text` — *why*: the orchestrator composes the others in a fixed order.
4. Write the tests.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY — helpers part 1)
```python
# occurrences: 1 (verified: grep -c -F -x '    def _project_of(issue: str) -> Optional[str]:' jiratoolkit.py)
# AFTER — insert below the END of `_project_of` (its `return None`, verified: jiratoolkit.py:1611)

    # ── FEAT-637: Jira text templates ─────────────────────────────────────
    @staticmethod
    def _validate_template_name(name: str) -> str:
        """Reject traversal-shaped names; return the name unchanged otherwise.

        Raises:
            JiraTemplateError: name contains ``..``, starts with ``/`` or contains ``\\``.
        """
        # FILL IN: the three checks — bounded by spec AC14

    @staticmethod
    def _template_candidates(
        kind: Literal["create", "update", "comment"], project: Optional[str], issuetype: Optional[str]
    ) -> List[str]:
        """Ordered, lower-cased convention candidates for ``kind`` (spec AC6)."""
        # FILL IN: build the list per kind; skip entries needing a missing value — bounded by AC6

    @staticmethod
    def _build_template_context(
        call_fields: Dict[str, Any], template_params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Flat context: call fields overlaid by ``template_params`` (params win, spec AC7)."""
        context = dict(call_fields)
        context.update(template_params or {})
        return context

    def _guard_text_length(self, text: str, *, field: str) -> str:
        """Truncate ``text`` to the Jira cap with a marker inside the cap (spec AC11)."""
        if len(text) <= _MAX_JIRA_TEXT_CHARS:
            return text
        self.logger.warning(
            "Rendered Jira %s is %d chars > %d; truncating", field, len(text), _MAX_JIRA_TEXT_CHARS
        )
        return text[: _MAX_JIRA_TEXT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
```

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY — helpers part 2, directly after part 1)
```python
    def _resolve_template_name(
        self, engine: TemplateEngine, kind: str, template: Optional[str],
        project: Optional[str], issuetype: Optional[str],
    ) -> Optional[str]:
        """Explicit name (as given, then + ``.j2``) else first existing convention candidate.

        Raises:
            JiraTemplateNotFound: an explicit ``template`` resolves to nothing.
        """
        # FILL IN: explicit branch via self._validate_template_name + engine.env.get_template probes;
        #          convention branch via self._template_candidates; return None if nothing exists — AC5/AC6

    @staticmethod
    def _assert_template_variables(engine: TemplateEngine, name: str, context: Dict[str, Any]) -> None:
        """Fail before rendering when the template references undeclared variables (spec AC8)."""
        source, _, _ = engine.env.loader.get_source(engine.env, name)
        undeclared = jinja_meta.find_undeclared_variables(engine.env.parse(source))
        missing = sorted(undeclared - set(context) - set(engine.env.globals))
        if missing:
            raise JiraTemplateError(f"template '{name}' is missing variables: {', '.join(missing)}")

    async def _render_jira_text(
        self, kind: Literal["create", "update", "comment"], *, text: Optional[str],
        template: Optional[str], template_params: Optional[Dict[str, Any]],
        call_fields: Dict[str, Any], project: Optional[str], issuetype: Optional[str] = None,
    ) -> Optional[str]:
        """Compose Jira text from a template; the single seam for all write paths.

        Returns ``text`` unchanged (byte-for-byte) when no template applies.
        Never performs Jira I/O.

        Raises:
            JiraTemplateError: template requested but none configured, missing
                variables, or empty render.
            JiraTemplateNotFound: explicit template name not found.
        """
        engine = self._get_template_engine()
        if engine is None:
            if template:
                raise JiraTemplateError("a template was requested but no Jira templates are configured")
            return text
        name = self._resolve_template_name(engine, kind, template, project, issuetype)
        if name is None:
            return text
        context = self._build_template_context(call_fields, template_params)
        self._assert_template_variables(engine, name, context)
        rendered = await engine.render(name, context)
        # FILL IN: empty/whitespace ⇒ JiraTemplateError — bounded by spec AC9
        self.logger.debug("Rendered Jira %s from template %s", kind, name)
        return self._guard_text_length(rendered, field="body" if kind == "comment" else "description")
```
**Why this shape**: the order — resolve, build context, assert variables, render, guard — is fixed by spec §2 and guarantees that no partial or invalid text can leave the helper.

### `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_render.py` (CREATE)
```python
"""FEAT-637 TASK-4114 — template resolution, context, strictness and length guard."""
from unittest.mock import patch

import pytest
from parrot_tools.jiratoolkit import JiraTemplateError, JiraTemplateNotFound, JiraToolkit


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


@pytest.mark.asyncio
async def test_no_engine_passthrough():
    tk = _make()
    out = await tk._render_jira_text("create", text="raw", template=None, template_params=None,
                                     call_fields={}, project="NAV", issuetype="Bug")
    assert out == "raw"

# FILL IN: test_explicit_template_with_and_without_suffix — AC5
# FILL IN: test_explicit_template_missing_raises_not_found — AC5
# FILL IN: test_explicit_template_without_engine_raises — JiraTemplateError
# FILL IN: test_name_traversal_rejected (parametrize "../x", "/etc/x", "a\\b") — AC14
# FILL IN: test_convention_create_order (parametrize which of nav/bug.j2, nav/_default.j2, _default.j2 exist) — AC6
# FILL IN: test_convention_comment_and_update_kinds — AC6
# FILL IN: test_no_candidate_passthrough — AC6
# FILL IN: test_context_params_win — AC7
# FILL IN: test_missing_variables_named — message lists "a, b" — AC8
# FILL IN: test_empty_render_raises — AC9
# FILL IN: test_length_guard_truncates_with_marker — len == 32_767, endswith marker, caplog WARNING — AC11
```

### FILL IN checklist
- [ ] `_validate_template_name` checks — AC14
- [ ] `_template_candidates` per-kind lists — AC6
- [ ] `_resolve_template_name` explicit + convention branches — AC5/AC6
- [ ] empty-render check in `_render_jira_text` — AC9
- [ ] eleven test bodies

---

## Acceptance Criteria

- [ ] No engine and no `template` ⇒ `text` returned unchanged.
- [ ] Explicit name works with or without `.j2`; unknown name ⇒ `JiraTemplateNotFound` (spec AC5).
- [ ] Convention order and lower-casing exactly as spec AC6; no candidate ⇒ pass-through.
- [ ] Context = call fields overlaid by `template_params` (spec AC7).
- [ ] Undeclared variables ⇒ `JiraTemplateError` naming every missing variable, before rendering (spec AC8).
- [ ] Empty/whitespace render ⇒ `JiraTemplateError` (spec AC9).
- [ ] Overflow truncated to exactly 32 767 chars ending in the marker, with a WARNING (spec AC11).
- [ ] Traversal-shaped names rejected (spec AC14).

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_render.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_config.py -q`

Run inside the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the CREATE block. Spec §4 rows covered: explicit/suffix, not-found, no-engine, traversal, convention order, comment/update kinds, params win, missing variables, empty render, length guard.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-template-support --feature-id FEAT-637 ...`).
2. Confirm TASK-4113 is `done` in `sdd/tasks/index/jiratoolkit-template-support.json`.
3. Verify the Codebase Contract; mark `in-progress`; implement from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4114 jiratoolkit-template-support verified`, fill the Completion Note, commit.

---

## Completion Note

**Completed by**: sdd-worker (coder seat gpt-5.6-terra, codex, 1 attempt, 169s; reviewed by orchestrator)
**Date**: 2026-10-08
**Notes**: Delivery matches the task's Files table and acceptance criteria (spec AC5-AC9, AC11, AC14). Task validation: render + config + delegation tests = 47 passed; ruff clean. Review recorded (0 corrections).
**Merge-tier gate not re-run: known RED, pre-existing** (whole-directory ai-parrot-tools collection/failures on clean origin/dev; see TASK-4113 note, PR #1600, issue:265b7797ae9b, issue:1e9c207bd223). Closed as `partial`.

**Deviations from spec**:
