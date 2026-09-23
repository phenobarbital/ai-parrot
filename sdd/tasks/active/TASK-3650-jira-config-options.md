# TASK-3650: JiraToolkitConfig + JiraToolkit.config_options(default_project)

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3647
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10; brainstorm "dynamic options — Jira implements it". The Agent Studio drawer
renders Jira from this model; `default_project` becomes a multi-select fed by
`config_options`, evaluated only on the persisted spec (S7, handled by TASK-3660).

---

## Scope

- Create `jira_config.py` with `JiraToolkitConfig` (server_url, auth_type, username, password*,
  token*, default_project, verify_credentials). `*` = `json_schema_extra={"x-secret": True}`.
- Verify the accepted `auth_type` values in `JiraToolkit.__init__` / `parrot.interfaces.jira` and
  use them as the `Literal` (spec lists `basic_auth|token_auth|oauth` as *to verify*).
- On `JiraToolkit`: `config_model`, `options_params = frozenset({"default_project"})`,
  `default_user_overridable = frozenset({"username", "password", "token"})`,
  `secret_params = frozenset({"password", "token", "oauth_access_token", "oauth_access_token_secret", "oauth_key_cert"})`.
- `config_options("default_project")` → `ConfigOption(value=key, label=f"{key} — {name}")` from
  `await self._read_interface.list_projects()`; any other param → `NotImplementedError`.

**NOT in scope**: the options HTTP endpoint (TASK-3660).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` | CREATE | JiraToolkitConfig Pydantic model |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | config_model/options/overridable ClassVars + config_options |
| `packages/ai-parrot-tools/tests/test_jira_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.config_schema import ConfigOption  # created by TASK-3646
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):  # :600
    def __init__(self, server_url=None, auth_type=None, username=None, password=None, token=None,
                 oauth_consumer_key=None, oauth_key_cert=None, oauth_access_token=None,
                 oauth_access_token_secret=None, default_project=None, credential_resolver: Any = None,
                 workflow_paths: Optional[Dict[str, Union[str, List[str]]]] = None,
                 verify_credentials: bool = True, **kwargs): ...  # :671-687
    # project listing (inside the list-projects tool method):
    #   project_list = await self._read_interface.list_projects()   # :2267 — shape of each item: verify (dict or object with key/name)
# TOOL_REGISTRY["jira"] = "parrot_tools.jiratoolkit.JiraToolkit"  # parrot_tools/__init__.py:83
```

### Does NOT Exist
- ~~`parrot_tools.jira_config`~~ — this task creates it.
- ~~`JiraToolkit.list_project_keys()`~~ — no such helper; use `self._read_interface.list_projects()`.
- ~~oauth_* / credential_resolver / workflow_paths in the config model~~ — deliberately excluded (server-managed / advanced).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_config.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/test_jira_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit"
  ]
}
```

---

## Implementation Notes

- `list_projects()` may require the toolkit to be authenticated first; check how the existing
  tool method calls it (look above :2267 for a `_pre_execute`/`_ensure_open` step) and mirror it.
- Keep `config_options` free of logging credentials.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Inspect `auth_type` handling and the `list_projects()` item shape — *why*: the Literal and label mapping must match reality.
2. Create `jira_config.py` — *why*: dedicated module keeps the 2k-line toolkit file untouched except for 5 lines + one method.
3. Add ClassVars + `config_options` to `JiraToolkit`.
4. Test with a patched `_read_interface`.

### `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` (CREATE)
```python
"""JiraToolkit configuration model (FEAT-593)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_SECRET = {"x-secret": True}


class JiraToolkitConfig(BaseModel):
    """Operator-facing Jira toolkit configuration rendered by Agent Studio."""

    model_config = ConfigDict(extra="forbid")
    server_url: str | None = Field(default=None, description="Jira base URL, e.g. https://acme.atlassian.net")
    # FILL IN: replace with the verified auth_type values — bounded by JiraToolkit.__init__ / parrot.interfaces.jira
    auth_type: Literal["basic_auth", "token_auth", "oauth"] | None = None
    username: str | None = None
    password: str | None = Field(default=None, json_schema_extra=_SECRET)
    token: str | None = Field(default=None, json_schema_extra=_SECRET)
    default_project: str | None = Field(default=None, description="Default project key")
    verify_credentials: bool = True
```

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class JiraToolkit(AbstractToolkit):' jiratoolkit.py)
# FILL IN: insert right after the class docstring of `class JiraToolkit(AbstractToolkit):` (verified: jiratoolkit.py:600)
    #: FEAT-593 — Agent Studio configuration surface.
    config_model = JiraToolkitConfig
    options_params = frozenset({"default_project"})
    default_user_overridable = frozenset({"username", "password", "token"})
    secret_params = frozenset({"password", "token", "oauth_access_token", "oauth_access_token_secret", "oauth_key_cert"})

    async def config_options(self, param: str) -> list[ConfigOption]:
        """Dynamic choices for Agent Studio (FEAT-593): project keys for ``default_project``."""
        if param != "default_project":
            return await super().config_options(param)
        # FILL IN: ensure the client is ready the same way the list-projects tool does (see above :2267)
        projects = await self._read_interface.list_projects()
        # FILL IN: map each item (dict or object) to ConfigOption(value=<key>, label=f"{key} — {name}")
        raise NotImplementedError
```
**Why**: `super().config_options` keeps the base `NotImplementedError` contract for other params.
Add `from .jira_config import JiraToolkitConfig` and `from parrot.tools.config_schema import ConfigOption`
to the module imports.

### FILL IN checklist
- [ ] `auth_type` Literal values; bounded by verified JiraToolkit/JiraInterface handling
- [ ] client readiness before `list_projects()`; bounded by existing tool method pattern
- [ ] item → ConfigOption mapping; bounded by the verified item shape

---

## Acceptance Criteria

- [ ] `JiraToolkit.config_schema("jira")["source"] == "model"`; `password`/`token` have `x-secret`; `default_project` has `x-options` (AC6, AC12).
- [ ] `config_options("default_project")` returns ConfigOptions from a mocked `list_projects`.
- [ ] `config_options("server_url")` raises `NotImplementedError`.
- [ ] Existing `pytest packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py -q` still passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-tools/tests/test_jira_config.py -q`
- `pytest packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_jira_config.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot_tools.jiratoolkit import JiraToolkit


def test_schema_marks_secrets_and_options():
    schema = JiraToolkit.config_schema("jira")["schema"]
    props = schema["properties"]
    assert props["token"]["x-secret"] is True and props["password"]["x-secret"] is True
    assert props["default_project"]["x-options"] is True


@pytest.mark.asyncio
async def test_config_options_projects():
    kit = JiraToolkit.__new__(JiraToolkit)  # avoid network in __init__
    kit._read_interface = SimpleNamespace(list_projects=AsyncMock(return_value=[{"key": "TROC", "name": "Troc"}]))
    # FILL IN: stub whatever readiness hook config_options calls
    opts = await kit.config_options("default_project")
    assert opts[0].value == "TROC"


@pytest.mark.asyncio
async def test_other_param_not_implemented():
    kit = JiraToolkit.__new__(JiraToolkit)
    with pytest.raises(NotImplementedError):
        await kit.config_options("server_url")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
