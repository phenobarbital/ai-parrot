# TASK-3647: AbstractToolkit config hooks (ClassVars, config_schema, config_options)

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3646
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (AbstractToolkit part) and §2 Overview (8). Toolkits declare their config
metadata through ClassVars; `config_options(param)` is the optional dynamic-options hook.
`_generate_tools` exposes every public method not in its management tuple as an LLM tool, so
both new names MUST be added to that tuple (verified trap).

---

## Scope

- Add ClassVars after `auto_open: bool = False`: `config_model`, `secret_params`,
  `default_user_overridable`, `options_params`.
- Add `@classmethod config_schema(cls, slug)` returning the envelope dict (`by_alias=True`).
- Add `async def config_options(self, param) -> list[ConfigOption]` raising `NotImplementedError`.
- Add `"config_schema"`, `"config_options"` to the `_generate_tools` management tuple.
- Tests: a toolkit subclass exposes neither name as a tool; envelope delegates correctly.

**NOT in scope**: any concrete toolkit's config model (TASK-3649/3650/3651).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | Add config ClassVars, config_schema classmethod, config_options hook, exclusion tuple entries |
| `packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.config_schema import ConfigOption, build_schema_envelope  # created by TASK-3646
from typing import ClassVar  # stdlib
from pydantic import BaseModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                 # :206
    exclude_tools: tuple[str, ...] = ()     # :243
    tool_prefix: str | None = None          # :257
    credential_provider: str | None = None  # :312
    auto_open: bool = False                 # :319  ← anchor
    def __init__(self, **kwargs): ...       # :321
    # _generate_tools: `for name in dir(self)` (:545), skips "_" names (:547), then:
    #   if name in ("get_tools", "get_tools_filtered", "get_tools_sync", "get_tool",
    #               "list_tool_names", "start", "stop", "cleanup", *self.exclude_tools): continue   # :551-561
```

### Does NOT Exist
- ~~`AbstractToolkit.config_model` / `config_schema` / `config_options` / `secret_params` / `options_params` / `default_user_overridable`~~ — this task adds them.
- ~~`AbstractToolkit.user_overridable`~~ — the ClassVar is named `default_user_overridable` (operator toggles the real list per agent).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._generate_tools"
  ]
}
```

---

## Implementation Notes

- Import `config_schema` lazily inside `config_schema()` if a circular import appears
  (`parrot.tools.config_schema` imports only pydantic/stdlib, so a top-level import should be fine).
- `default_user_overridable` is only the *default toggle* rendered by the UI; the persisted
  `ToolkitSpec.user_overridable` list is authoritative.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the four ClassVars below the `auto_open` anchor — *why*: config_schema module reads them via getattr.
2. Add the two methods near `get_toolkit_info` (:693) — *why*: keep public API grouped.
3. Extend the management tuple — *why*: otherwise `config_options` becomes an LLM-callable tool.
4. Write tests.

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY — ClassVars)
```python
# occurrences: 1 (verified: grep -c '    auto_open: bool = False' packages/ai-parrot/src/parrot/tools/toolkit.py)
# AFTER — insert below `    auto_open: bool = False` (verified: toolkit.py:319)

    #: FEAT-593 — optional Pydantic model describing this toolkit's configuration. When set,
    #: ``config_schema()`` publishes its ``model_json_schema()``; otherwise the constructor is
    #: introspected.
    config_model: ClassVar[type[BaseModel] | None] = None
    #: FEAT-593 — curated constructor params that are secrets (stored in the vault, masked on GET).
    secret_params: ClassVar[frozenset[str]] = frozenset()
    #: FEAT-593 — params whose "users may override" toggle defaults to on in Agent Studio.
    default_user_overridable: ClassVar[frozenset[str]] = frozenset()
    #: FEAT-593 — params for which ``config_options()`` returns dynamic choices.
    options_params: ClassVar[frozenset[str]] = frozenset()
```
**Why**: ClassVars (not instance attributes) so the schema can be built without instantiating.

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY — methods)
```python
# occurrences: 1 (verified: grep -c '    def get_toolkit_info(self) -> dict\[str, Any\]:' toolkit.py)
# BEFORE — insert above `    def get_toolkit_info(self) -> dict[str, Any]:` (verified: toolkit.py:693)

    @classmethod
    def config_schema(cls, slug: str) -> dict[str, Any]:
        """Return the FEAT-593 JSON Schema envelope ``{slug, class_name, source, schema}``."""
        from .config_schema import build_schema_envelope  # pylint: disable=import-outside-toplevel

        return build_schema_envelope(slug, cls).model_dump(by_alias=True)

    async def config_options(self, param: str) -> list["ConfigOption"]:
        """Dynamic choices for ``param`` (FEAT-593). Never exposed as an LLM tool.

        Raises:
            NotImplementedError: the toolkit offers no dynamic options for ``param``.
        """
        raise NotImplementedError(f"{type(self).__name__} has no dynamic options for {param!r}")
```

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY — exclusion tuple)
```python
# occurrences: 1 (verified: grep -c '                "cleanup",' toolkit.py) — context:
#                 "stop",
#                 "cleanup",
#                 *self.exclude_tools,
# AFTER `                "cleanup",` (verified: toolkit.py:559) insert:
                "config_schema",
                "config_options",
```
**Why**: `_generate_tools` treats every public attribute as a tool candidate (:545-561).

### FILL IN checklist
- [ ] Confirm `ClassVar`, `BaseModel` and a `TYPE_CHECKING` import of `ConfigOption` exist at the top of toolkit.py (add them if missing) — bounded by ruff clean

---

## Acceptance Criteria

- [ ] `AbstractToolkit.config_model is None` and the three frozensets default empty.
- [ ] A subclass's `get_tools()` names contain neither `config_schema` nor `config_options`.
- [ ] `SubClass.config_schema("x")["source"] == "introspection"` and has `"schema"` key.
- [ ] `await instance.config_options("p")` raises `NotImplementedError`.
- [ ] Existing toolkit tests still pass: `pytest packages/ai-parrot/tests/test_core_tools.py -q`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py -q`
- `pytest packages/ai-parrot/tests/test_core_tools.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_toolkit_config_hooks.py
import pytest
from parrot.tools.toolkit import AbstractToolkit


class _Kit(AbstractToolkit):
    def __init__(self, server_url: str = "", **kwargs):
        super().__init__(**kwargs)
        self.server_url = server_url

    async def ping(self) -> str:
        """Ping."""
        return "pong"


def test_hooks_not_llm_tools():
    names = {t.name for t in _Kit().get_tools_sync()}  # FILL IN: use the sync accessor that exists (get_tools_sync :602)
    assert "ping" in names or any(n.endswith("ping") for n in names)
    assert not any("config_schema" in n or "config_options" in n for n in names)


def test_config_schema_envelope():
    env = _Kit.config_schema("kit")
    assert env["slug"] == "kit" and env["source"] == "introspection" and "schema" in env


@pytest.mark.asyncio
async def test_config_options_default_raises():
    with pytest.raises(NotImplementedError):
        await _Kit().config_options("server_url")
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
