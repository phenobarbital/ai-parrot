# TASK-3646: config_schema module: JSON Schema envelope, introspection lift, secret heuristics

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (4), §3 Module 2, design research S8. One Draft 2020-12 envelope
`{slug, class_name, source, schema}` for every toolkit: `model_json_schema()` of a declared
`config_model`, or the constructor lifted into `properties`/`required`. Secret classification
is name heuristics + curated overlay (`secret_params`) — user decision 2026-09-23 (AC7). Params
whose type is not JSON-representable become `x-server-managed` (S6 mitigation).

---

## Scope

- Create `parrot/tools/config_schema.py` with `SECRET_NAME_HINTS`, `is_secret_name`,
  `ConfigOption`, `ToolkitSchemaEnvelope`, `introspect_config_schema`, `model_config_schema`,
  `build_schema_envelope`, `secret_paths`.
- Read class metadata with `getattr(cls, "<name>", default)` — the ClassVars
  (`config_model`, `secret_params`, `default_user_overridable`, `options_params`) are added to
  `AbstractToolkit` by TASK-3647, and wiki/infographic classes must work too.
- Unit tests over small fake classes and a small Pydantic model with a `oneOf` union.

**NOT in scope**: modifying `AbstractToolkit` (TASK-3647), the HTTP handler (TASK-3658).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/config_schema.py` | CREATE | Envelope model, introspection → JSON Schema, heuristics, secret_paths |
| `packages/ai-parrot/tests/tools/test_config_schema.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
import inspect  # stdlib
import types, typing  # stdlib (get_origin/get_args/Literal/Union)
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use
```python
# Reference only (do not import server code into core) —
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
def _introspect_params(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, dict[str, Any]]:  # :107
#   skips "self", *args, **kwargs; required = default is inspect.Parameter.empty; defaults JSON-coerced via _json_safe (:96)
# pydantic v2: BaseModel.model_json_schema() emits "$defs" + "oneOf"/"anyOf" for unions,
#   "discriminator": {"propertyName": ...} when Field(discriminator=...) is used.
```

### Does NOT Exist
- ~~`parrot.tools.config_schema`~~ — this task creates it.
- ~~`AbstractToolkit.config_model` / `.secret_params` / `.options_params` / `.default_user_overridable`~~ — added by TASK-3647; use `getattr(cls, ..., default)` here.
- ~~`MCPParamType` for toolkit schemas~~ — MCP-registry specific; do not reuse.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/config_schema.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_config_schema.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#_introspect_params"
  ]
}
```

---

## Implementation Notes

- Type mapping for introspection: `str`→string, `int`→integer, `float`→number, `bool`→boolean,
  `list[...]`/`List`/`tuple`→array, `dict`/`Dict`→object, `Literal[...]`→`enum`,
  `Optional[X]`/`X | None`→X's type (not required), string annotations (`"Foo"`) and anything
  else (classes, callables, `Any` excluded) → `x-server-managed: true`. Treat `Any` / empty
  annotation as `{}` (free-form), NOT server-managed.
- Draft marker: every envelope schema carries `"$schema": "https://json-schema.org/draft/2020-12/schema"`
  and `"type": "object"`.
- `secret_paths(schema, params)` walks params against schema properties, following `$ref` into
  `$defs`, and for arrays whose `items` is a `oneOf` with a discriminator picks the branch by
  the item's discriminator value. Returns dotted paths (`datasources.0.dsn`).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write the models + heuristics — *why*: names are the wire contract for the UI (TASK-3663 exports them).
2. Implement `introspect_config_schema` over `inspect.signature(cls.__init__)` — *why*: fallback for every toolkit without a config model.
3. Implement `model_config_schema` post-processing (`x-secret` from `json_schema_extra` or heuristics, `x-user-overridable`, `x-options`) — *why*: one renderer in the SPA.
4. Implement `secret_paths` — *why*: TASK-3659 uses it to split secrets out of submitted params.

### `packages/ai-parrot/src/parrot/tools/config_schema.py` (CREATE)
```python
"""Toolkit configuration JSON Schema (FEAT-593): one Draft 2020-12 envelope per toolkit."""
from __future__ import annotations

import inspect
import logging
import typing
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
SECRET_NAME_HINTS: frozenset[str] = frozenset(
    {"token", "password", "api_key", "secret", "dsn", "credentials", "access_token", "private_key"}
)


class ConfigOption(BaseModel):
    """One dynamic choice returned by ``AbstractToolkit.config_options``."""

    value: str
    label: str


class ToolkitSchemaEnvelope(BaseModel):
    """``GET /astudio/toolkits/{slug}/schema`` response."""

    model_config = ConfigDict(populate_by_name=True)
    slug: str
    class_name: str
    source: Literal["model", "introspection"]
    schema_: dict[str, Any] = Field(alias="schema")


def is_secret_name(name: str, curated: frozenset[str] = frozenset()) -> bool:
    """True when ``name`` is curated or contains any hint (case-insensitive substring)."""
    lowered = name.lower()
    return name in curated or any(hint in lowered for hint in SECRET_NAME_HINTS)


def _json_type(annotation: Any) -> dict[str, Any] | None:
    """Map an annotation to a JSON Schema fragment; ``None`` means server-managed."""
    # FILL IN: implement the mapping table from Implementation Notes (Optional unwrap, Literal→enum,
    #   list→array, dict→object, Any/empty→{}, str annotations & classes → None) — bounded by AC7


def introspect_config_schema(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Lift ``cls.__init__`` into a Draft 2020-12 object schema (see module notes)."""
    curated = frozenset(getattr(cls, "secret_params", frozenset()))
    overridable = frozenset(getattr(cls, "default_user_overridable", frozenset()))
    options = frozenset(getattr(cls, "options_params", frozenset()))
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in inspect.signature(cls.__init__).parameters.items():
        if pname == "self" or param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        # FILL IN: fragment = _json_type(param.annotation); None or pname in server_managed →
        #   {"x-server-managed": True} (never required); else add "default" (JSON-coerced) when
        #   present, required when no default; add x-secret / x-user-overridable / x-options flags
    return {"$schema": DRAFT_2020_12, "type": "object", "properties": properties, "required": required}


def model_config_schema(cls: type) -> dict[str, Any]:
    """``cls.config_model.model_json_schema()`` plus the ``x-*`` extensions."""
    schema = cls.config_model.model_json_schema()
    # FILL IN: for each top-level property set x-secret (keep an existing json_schema_extra
    #   "x-secret"; else is_secret_name), x-user-overridable (default_user_overridable), x-options
    #   (options_params); inside "$defs" set x-secret on properties by is_secret_name when missing
    schema["$schema"] = DRAFT_2020_12
    return schema


def build_schema_envelope(slug: str, cls: type, *, server_managed: frozenset[str] = frozenset()) -> ToolkitSchemaEnvelope:
    """``source='model'`` when ``cls.config_model`` is set, else ``'introspection'``."""
    if getattr(cls, "config_model", None) is not None:
        return ToolkitSchemaEnvelope(slug=slug, class_name=cls.__name__, source="model", schema=model_config_schema(cls))
    return ToolkitSchemaEnvelope(
        slug=slug, class_name=cls.__name__, source="introspection",
        schema=introspect_config_schema(cls, server_managed=server_managed),
    )


def secret_paths(schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Dotted paths of every value in ``params`` the schema marks ``x-secret``."""
    # FILL IN: recursive walk resolving "$ref" → schema["$defs"]; arrays with items.oneOf +
    #   discriminator.propertyName pick the branch whose const/enum matches item[prop] — bounded by spec §2 Data Models
    raise NotImplementedError
```
**Why this shape**: the envelope model is exported to TypeScript (TASK-3663), so its field names
are fixed. `getattr` defaults let the module work before and independently of TASK-3647.

### FILL IN checklist
- [ ] `_json_type` — annotation mapping table; bounded by AC7 (non-JSON → server-managed)
- [ ] `introspect_config_schema` loop body — defaults/required/flags; bounded by spec §2 Overview (4)
- [ ] `model_config_schema` — x-* post-processing; bounded by AC6
- [ ] `secret_paths` — `$ref`/`oneOf` walk; bounded by spec §2 Data Models note on dotted keys

---

## Acceptance Criteria

- [ ] Envelope for a class with `config_model` → `source == "model"`; without → `"introspection"` (AC6).
- [ ] A ctor param typed as an arbitrary class (e.g. `credential_resolver: SomeResolver`) → `x-server-managed: true`, not required (AC7).
- [ ] `token`, `dsn`, curated `secret_params` names → `x-secret: true` (AC7).
- [ ] `secret_paths` returns `datasources.1.api_key` for an airtable item in a `oneOf` list.
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/config_schema.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_config_schema.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_config_schema.py
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field
from parrot.tools.config_schema import build_schema_envelope, is_secret_name, secret_paths


class _Resolver: ...


class _Plain:
    secret_params = frozenset({"weird"})

    def __init__(self, server_url: str, token: Optional[str] = None, weird: str = "", max_rows: int = 5,
                 credential_resolver: _Resolver = None, **kwargs): ...


class _A(BaseModel):
    kind: Literal["a"]
    name: str
    dsn: Optional[str] = None


class _B(BaseModel):
    kind: Literal["b"]
    name: str
    api_key: Optional[str] = None


class _Cfg(BaseModel):
    datasources: list[Annotated[Union[_A, _B], Field(discriminator="kind")]] = []


class _Modeled:
    config_model = _Cfg


def test_introspection_envelope():
    env = build_schema_envelope("plain", _Plain)
    props = env.schema_["properties"]
    assert env.source == "introspection"
    assert env.schema_["required"] == ["server_url"]
    assert props["token"]["x-secret"] is True and props["weird"]["x-secret"] is True
    assert props["credential_resolver"]["x-server-managed"] is True
    assert props["max_rows"]["type"] == "integer"


def test_model_envelope():
    assert build_schema_envelope("m", _Modeled).source == "model"


def test_secret_paths_oneof():
    schema = build_schema_envelope("m", _Modeled).schema_
    params = {"datasources": [{"kind": "a", "name": "x", "dsn": "d"}, {"kind": "b", "name": "y", "api_key": "k"}]}
    assert sorted(secret_paths(schema, params)) == ["datasources.0.dsn", "datasources.1.api_key"]


def test_is_secret_name():
    assert is_secret_name("API_KEY") and not is_secret_name("server_url")
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
