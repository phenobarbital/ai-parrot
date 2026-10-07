# TASK-4113: Template configuration, error types and lazy Jira-safe engine

**Feature**: FEAT-637 — JiraToolkit Template Support
**Spec**: `sdd/specs/jiratoolkit-template-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** (G1, G5, AC2, AC3, AC4, AC16). Adds the
configuration surface (`templates_dir` / `JIRA_TEMPLATES_DIR` / `templates=`),
the two error types and module constants, and a lazily built
`TemplateEngine` configured for Jira wiki markup (autoescape OFF). Every later
task builds on these names.

---

## Scope

- Add imports `Path`, `Mapping`, `jinja2.TemplateNotFound`, `jinja2.meta`, `parrot.template.{JinjaConfig, TemplateEngine}`.
- Add module constants `_TEMPLATE_SUFFIX`, `_MAX_JIRA_TEXT_CHARS`, `_TRUNCATION_MARKER`, `_JIRA_TEMPLATE_EXTENSIONS`.
- Add `JiraTemplateError(ValueError)` and `JiraTemplateNotFound(JiraTemplateError)`.
- Add `templates_dir` and `templates` kwargs to `JiraToolkit.__init__`, appended after `verify_credentials` and before `**kwargs`.
- Resolve `templates_dir` (kwarg > `_cfg("JIRA_TEMPLATES_DIR")`); a non-directory path logs a WARNING and becomes `None`.
- Add `_get_template_engine()` (lazy, cached, returns `None` when nothing is configured).
- Extend `INIT_PARAMS_BASELINE` with `"templates_dir", "templates"` before `"kwargs"`.
- Write `test_jiratoolkit_templates_config.py`.

**NOT in scope**: template selection, context, rendering, length guard (TASK-4114); write-path wiring and input-model fields (TASK-4115); `jira_list_templates` (TASK-4116); docs (TASK-4117); any change to `parrot/template/engine.py` or `jira_config.py` (spec AC17).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | imports, constants, error classes, `__init__` kwargs, `_get_template_engine()` |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py` | MODIFY | extend `INIT_PARAMS_BASELINE` |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_config.py` | CREATE | config/engine unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against dev `d79fdf0b5` (no code drift since spec base `77a870889`).

### Verified Imports
```python
from parrot.template import JinjaConfig, TemplateEngine   # verified: packages/ai-parrot/src/parrot/template/__init__.py:1
from jinja2 import TemplateNotFound, meta as jinja_meta    # verified: jinja2 3.1.6 in .venv
from pathlib import Path                                   # stdlib — NOT yet imported in jiratoolkit.py
from parrot_tools.jiratoolkit import JiraToolkit           # verified: tests/unit/test_jiratoolkit_delegation.py:17-21
```
`jiratoolkit.py:30` today: `from typing import Any, Dict, List, Optional, Sequence, Union, Literal, TypedDict` — add `Mapping` to it.

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
from .jira_config import JiraToolkitConfig                       # line 57 (last import line)
class JiraToolkit(AbstractToolkit):                              # line 596
    _DEFAULT_WORKFLOW_KEY = "_DEFAULT"                           # line 693
    def __init__(self, ..., workflow_paths=None,
                 verify_credentials: bool = True, **kwargs)      # line 698-716; verify_credentials at :712
        def _cfg(key: str, default: Optional[str] = None) -> Optional[str]   # line 718-723 (navconfig → env)
        self.logger = logging.getLogger(__name__)                # line 725
        self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")    # line 772
        self._auth_error: Optional[str] = None                   # line 810
        # NOTE: __init__ has early `return`s after :810 (oauth2_3lo, unauthenticated, bad creds);
        #       every template attribute MUST be set BEFORE line 810.

# packages/ai-parrot/src/parrot/template/engine.py
@dataclass class JinjaConfig:   # line 26-44; fields template_dirs, extensions, autoescape, undefined (StrictUndefined default)
class TemplateEngine:           # line 47
    def __init__(self, template_dirs=None, *, extensions=None, bytecode_cache_dir=None,
                 filters=None, globals_=None, config: Optional[JinjaConfig] = None, debug=False)  # line 56-66
        # raises ValueError for a missing dir (line 78-84)
    def add_templates(self, templates: Mapping[str, str]) -> None   # line 164-170
    self.env  # jinja2.Environment; loader = ChoiceLoader([DictLoader, FileSystemLoader]) (line 102-118)

# packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py
INIT_PARAMS_BASELINE = (..., "workflow_paths", "verify_credentials", "kwargs")   # line 23-39; "verify_credentials", at :38
with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):                          # line 90

# packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py — fixtures to copy
def _clean_env(monkeypatch)        # line 45-62 (autouse; delete JIRA_* env vars)
def _stub_nav_config(monkeypatch)  # line 65-70 (autouse; parrot_tools.jiratoolkit.nav_config = None)
class _FakeJIRA                    # line 20-28
```

### Does NOT Exist
- ~~`JinjaConfig(undefined="strict")`~~ — takes a class; `StrictUndefined` is already the default.
- ~~`TemplateEngine.list_templates()` / `.has_template()`~~ — not methods (use `engine.env`).
- ~~`JiraToolkitConfig.templates_dir`~~ — must NOT be added (spec Non-Goals; §8 Q2 is a follow-up).
- ~~`packages/ai-parrot-tools/tests/conftest.py`~~ — does not exist; `tests/unit/conftest.py` holds only NavigatorToolkit fixtures. Do not add Jira fixtures to any conftest.
- ~~`self.templates_dir` / `self._template_engine`~~ — do not exist yet; this task creates them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_config.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/template/engine.py#TemplateEngine",
    "sym:packages/ai-parrot/src/parrot/template/engine.py#JinjaConfig",
    "sym:packages/ai-parrot/src/parrot/template/engine.py#TemplateEngine.add_templates",
    "sym:packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py#INIT_PARAMS_BASELINE"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `autoescape=False` is mandatory: `JinjaConfig`'s default `select_autoescape([... "j2" ...])` would HTML-escape every `.j2` template (AC4).
- Pass `extensions=list(_JIRA_TEMPLATE_EXTENSIONS)` inside the `JinjaConfig` — the engine's default list includes `jinja2_time`, `jinja2_iso8601`, `jinja2_humanize_extension`, which no `pyproject.toml` declares.
- Toolkit construction must never raise because of templates (spec S8).
- Set all template attributes before `self._auth_error` (:810) — later code paths `return` early.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:307-321` — lazy-engine pattern to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and constants — *why*: every later task references these exact names.
2. Add the two error classes at module level, right after the constants — *why*: TASK-4114/4115 raise them and tests import them from `parrot_tools.jiratoolkit`.
3. Add the two kwargs to `__init__` after `verify_credentials` — *why*: appending keeps every existing positional/keyword caller valid.
4. Resolve config after `self.default_estimate` and before `self._auth_error` — *why*: early returns after :810 would skip it.
5. Add `_get_template_engine()` after `__init__` — *why*: lazy build means a missing optional extension or dir can never break construction.
6. Update `INIT_PARAMS_BASELINE` and write the tests.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY — imports & module scope)
```python
# occurrences: 1 (verified: grep -c -F -x 'from .jira_config import JiraToolkitConfig' jiratoolkit.py)
# AFTER — insert below `from .jira_config import JiraToolkitConfig` (verified: jiratoolkit.py:57)
from pathlib import Path

from jinja2 import TemplateNotFound  # noqa: F401  (used by TASK-4114)
from jinja2 import meta as jinja_meta  # noqa: F401  (used by TASK-4114)
from parrot.template import JinjaConfig, TemplateEngine

#: Suffix every Jira text template file carries.
_TEMPLATE_SUFFIX = ".j2"
#: Jira Cloud limit for description and comment text fields.
_MAX_JIRA_TEXT_CHARS = 32_767
#: Appended (inside the cap) when rendered text is truncated.
_TRUNCATION_MARKER = "\n\n... (truncated)"
#: Stdlib-only extensions: the engine default pulls undeclared third-party packages.
_JIRA_TEMPLATE_EXTENSIONS = ("jinja2.ext.do", "jinja2.ext.loopcontrols")


class JiraTemplateError(ValueError):
    """A Jira text template could not be applied.

    Raised for missing variables, an empty render, a conflicting
    ``fields['description']``, an invalid name, or a template requested while
    no templates are configured.
    """


class JiraTemplateNotFound(JiraTemplateError):
    """An explicitly requested template name does not exist in any loader."""
```
Also change line 30 to add `Mapping` to the `typing` import. Remove the `# noqa: F401` markers only if TASK-4114 is merged in the same branch before linting — otherwise keep them so `ruff` stays clean.

**Why this shape**: names, values and placement are fixed by spec §3 M1 and reused verbatim by later tasks.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY — `__init__` signature)
```python
# occurrences: 1 (verified: grep -c -F -x '        verify_credentials: bool = True,' jiratoolkit.py)
# AFTER — insert below `        verify_credentials: bool = True,` (verified: jiratoolkit.py:712)
        templates_dir: Optional[Union[str, Path]] = None,
        templates: Optional[Mapping[str, str]] = None,
```

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY — config resolution)
```python
# occurrences: 1 (verified: grep -c -F -x '        self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")' jiratoolkit.py)
# AFTER — insert below `        self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")` (verified: jiratoolkit.py:772)

        # FEAT-637 — Jira text templates. Explicit kwarg > navconfig/env.
        # A configured path that is not a directory is dropped with a WARNING
        # so a typo is diagnosable but never breaks toolkit construction.
        _tpl_dir = templates_dir or _cfg("JIRA_TEMPLATES_DIR")
        self.templates_dir: Optional[Path] = None
        if _tpl_dir:
            _candidate = Path(_tpl_dir).expanduser()
            if _candidate.is_dir():
                self.templates_dir = _candidate.resolve()
            else:
                self.logger.warning("Jira templates_dir %s is not a directory; ignoring it", _candidate)
        self._inline_templates: Dict[str, str] = dict(templates or {})
        self._template_engine: Optional[TemplateEngine] = None
```
Also extend the class docstring's "Recognized config/env keys" list with `JIRA_TEMPLATES_DIR`.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY — engine factory)
```python
# occurrences: 1 (verified: grep -c -F -x '    def _verify_static_credentials(self) -> None:' jiratoolkit.py)
# BEFORE — insert above `    def _verify_static_credentials(self) -> None:` (verified: jiratoolkit.py:855)
    def _get_template_engine(self) -> Optional[TemplateEngine]:
        """Return the lazily built Jira-safe template engine.

        Returns:
            ``None`` when neither ``templates_dir`` nor inline ``templates`` are
            configured; otherwise a cached ``TemplateEngine`` with autoescape
            disabled (Jira wiki markup is not HTML) and ``StrictUndefined``.
        """
        if self._template_engine is not None:
            return self._template_engine
        if self.templates_dir is None and not self._inline_templates:
            return None
        engine = TemplateEngine(
            template_dirs=[self.templates_dir] if self.templates_dir else None,
            config=JinjaConfig(autoescape=False, extensions=list(_JIRA_TEMPLATE_EXTENSIONS)),
        )
        if self._inline_templates:
            engine.add_templates(self._inline_templates)
        self._template_engine = engine
        return engine
```
**Why**: `JinjaConfig(template_dirs=...)` is a mutable dataclass field — pass dirs via the `template_dirs` argument (as above), not inside the config. Inline templates shadow files because the engine's `ChoiceLoader` tries the `DictLoader` first (AC3).

### `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F -x '    "verify_credentials",' test_jiratoolkit_delegation.py)
# AFTER — insert below `    "verify_credentials",` (verified: test_jiratoolkit_delegation.py:38)
    "templates_dir",
    "templates",
```

### `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_config.py` (CREATE)
```python
"""FEAT-637 TASK-4113 — template configuration and lazy engine."""
import logging
from unittest.mock import patch

import pytest
from parrot_tools.jiratoolkit import JiraTemplateError, JiraTemplateNotFound, JiraToolkit


class _FakeJIRA:
    def __init__(self, *args, **kwargs) -> None:
        self.args, self.kwargs = args, kwargs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("JIRA_INSTANCE", "JIRA_AUTH_TYPE", "JIRA_TEMPLATES_DIR", "JIRA_DEFAULT_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


def _make(**kwargs) -> JiraToolkit:
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        return JiraToolkit(auth_type="token_auth", server_url="https://x.atlassian.net",
                           token="t", verify_credentials=False, **kwargs)


def test_engine_is_lazy_and_none_without_config():
    tk = _make()
    assert tk._template_engine is None and tk._get_template_engine() is None

# FILL IN: test_missing_templates_dir_warns_and_drops (caplog WARNING, templates_dir is None) — AC2
# FILL IN: test_env_var_used_and_kwarg_wins_over_env (two tmp dirs, monkeypatch.setenv) — AC2
# FILL IN: test_autoescape_disabled — inline {"t.j2": "{code}{{ x }}{code} <b>"}; await engine.render("t.j2", {"x": "<i>"}) == raw text — AC4
# FILL IN: test_inline_templates_shadow_filesystem — same name on disk and inline ⇒ inline text — AC3
# FILL IN: test_engine_cached — two calls return the same object
# FILL IN: test_error_hierarchy — issubclass(JiraTemplateNotFound, JiraTemplateError) and issubclass(JiraTemplateError, ValueError)
```

### FILL IN checklist
- [ ] Six test bodies listed in the CREATE block — bounded by AC2/AC3/AC4.
- [ ] Docstring update listing `JIRA_TEMPLATES_DIR`.
- [ ] Decide whether the `# noqa: F401` markers are still needed after linting.

---

## Acceptance Criteria

- [ ] `JiraToolkit(...)` without template config behaves exactly as before; `_get_template_engine()` returns `None`.
- [ ] `templates_dir` kwarg beats `JIRA_TEMPLATES_DIR`; a missing directory logs a WARNING and does not raise (spec AC2).
- [ ] Inline templates shadow same-named files (spec AC3).
- [ ] Rendering through the engine keeps `{code}`, `<`, `>` verbatim (spec AC4).
- [ ] `INIT_PARAMS_BASELINE` updated; `test_init_signature_unchanged` passes (spec AC16).
- [ ] `ruff check` clean on the three touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_templates_config.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py -q`

Run inside the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the CREATE block above. Spec §4 rows covered: `test_engine_is_lazy_and_none_without_config`, `test_missing_templates_dir_warns_and_drops`, `test_kwarg_wins_over_env`, `test_autoescape_disabled`, `test_inline_templates_shadow_filesystem`, `test_init_signature_unchanged`.

Deviation from spec §4 (declared): the spec lists one test module; tests are split per task (`test_jiratoolkit_templates_{config,render,writes}.py`, `test_jiratoolkit_list_templates.py`) so tasks touching `jiratoolkit.py` do not also contend on one test file.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug jiratoolkit-template-support --feature-id FEAT-637 --spec sdd/specs/jiratoolkit-template-support.spec.md --index sdd/tasks/index/jiratoolkit-template-support.json`
2. Read the spec; verify the Codebase Contract above (`grep -c -F -x` each anchor).
3. Mark `in-progress` in the per-spec index and commit only that file.
4. Implement from the blueprint; complete every `FILL IN`.
5. Run the Validation Commands; commit only the listed files.
6. Close with `scripts/sdd/close_task.sh TASK-4113 jiratoolkit-template-support verified`, fill the Completion Note, commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
