# TASK-5138: Resolver module parrot/llm_defaults.py

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5137
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (G1, G2). Single place that resolves a component's `(provider, model)` from `<COMPONENT>_LLM` → `DEFAULT_LLM` → builtin, and its API key from `<COMPONENT>_<PROVIDER>_API_KEY` → legacy vars → None.

---

## Scope

- Create `parrot/llm_defaults.py` with `ComponentLLM`, `resolve_component_llm`, `provider_key_token`, `resolve_component_api_key` exactly per the spec skeleton.
- Write unit tests for cascade order, bare-model inheritance, malformed values, Google-family token mapping and key cascade.

**NOT in scope**: Wiring into crew/experts/handler (TASK-5140/5141/5142). Usage tagging (TASK-5139).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/llm_defaults.py` | CREATE | Resolver |
| `packages/ai-parrot/tests/unit/test_llm_defaults.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
from navconfig import config  # verified: parrot/conf.py:6
from parrot import conf  # module object; read attrs via getattr (credentials.py:18 pattern)
from parrot.clients.factory import SUPPORTED_CLIENTS  # verified: crew.py:60 — import LAZILY inside the function
from parrot.bots.flows.crew.credentials import GOOGLE_PROVIDER_KEYS  # verified: credentials.py:24 — import LAZILY
```

### Existing Signatures to Use
```python
# parrot/bots/flows/crew/credentials.py:24
GOOGLE_PROVIDER_KEYS: frozenset[str] = frozenset({"google", "gemini-live", "google-compat"})
# parrot/conf.py (after TASK-5137)
DEFAULT_LLM: str | None
```

### Does NOT Exist
- ~~`parrot.llm_defaults`~~ — created here
- ~~`AbstractBot._parse_llm_string` as a free function~~ — it is a bound method (`bots/abstract.py:847`); do NOT import it, parse `provider:model` locally with `str.partition(':')`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/llm_defaults.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_llm_defaults.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#GOOGLE_PROVIDER_KEYS"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No module-scope import of `parrot.clients.*` or `parrot.bots.*` — conf import-cycle risk (spec §7). Import inside functions.
- Read env with `config.get(name)` at call time (never at import) so monkeypatching works.
- Never log key values.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. Create the module from the blueprint — *why*: fixed public API used by three tasks.
2. Fill the parse/validate branch — *why*: AC6.
3. Write tests with a fixture patching `navconfig.config.get` via a dict — *why*: hermetic env.

### `packages/ai-parrot/src/parrot/llm_defaults.py` (CREATE)
```python
"""Per-component LLM defaults (FEAT-796).

Resolves ``<COMPONENT>_LLM`` -> ``DEFAULT_LLM`` -> builtin (all ``provider:model``) and
``<COMPONENT>_<PROVIDER>_API_KEY`` -> legacy vars -> ``None``. Key values are never logged.
"""
from __future__ import annotations

from typing import Literal, Optional, Sequence

from navconfig import config
from pydantic import BaseModel

from parrot import conf


class ComponentLLM(BaseModel):
    """Resolved provider/model for a component plus where it came from."""

    provider: str
    model: str
    source: Literal["component", "global", "builtin"]


def _split(value: str, *, var: str, default_provider: str) -> tuple[str, str]:
    """Split ``provider:model`` (bare ``model`` inherits ``default_provider``).

    Raises:
        ValueError: naming ``var`` when the value is empty, has an empty side,
            or the provider is not a ``SUPPORTED_CLIENTS`` key.
    """
    from parrot.clients.factory import SUPPORTED_CLIENTS  # noqa: PLC0415 — conf import cycle

    # FILL IN: strip; partition on ':'; bare model -> (default_provider, model);
    #          empty provider/model or provider.lower() not in SUPPORTED_CLIENTS
    #          -> raise ValueError(f"{var}: ...") — bounded by AC6
    raise NotImplementedError


def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM:
    """Resolve ``<COMPONENT>_LLM`` -> ``DEFAULT_LLM`` -> ``builtin``."""
    builtin_provider, builtin_model = builtin.split(":", 1)
    var = f"{component.upper()}_LLM"
    value = config.get(var)
    if value:
        provider, model = _split(value, var=var, default_provider=builtin_provider)
        return ComponentLLM(provider=provider, model=model, source="component")
    global_value = getattr(conf, "DEFAULT_LLM", None)
    if global_value:
        provider, model = _split(global_value, var="DEFAULT_LLM", default_provider=builtin_provider)
        return ComponentLLM(provider=provider, model=model, source="global")
    return ComponentLLM(provider=builtin_provider, model=builtin_model, source="builtin")


def provider_key_token(provider: str) -> str:
    """``google``/``gemini-live``/``google-compat`` -> ``GOOGLE``; else upper snake case."""
    from parrot.bots.flows.crew.credentials import GOOGLE_PROVIDER_KEYS  # noqa: PLC0415

    if provider.lower() in GOOGLE_PROVIDER_KEYS:
        return "GOOGLE"
    return provider.upper().replace("-", "_")


def resolve_component_api_key(
    components: Sequence[str], provider: str, *, legacy: Sequence[str] = ()
) -> Optional[str]:
    """First set ``<C>_<TOKEN>_API_KEY`` for C in ``components``, then ``legacy`` vars, else None."""
    token = provider_key_token(provider)
    for name in [f"{c.upper()}_{token}_API_KEY" for c in components] + list(legacy):
        value = config.get(name)
        if value:
            return value
    return None
```
**Why**: names/signatures are fixed by spec §3 M1; three downstream tasks import them.

### FILL IN checklist
- [ ] `_split` — parsing + validation; bounded by AC6 (ValueError names the var)

---

## Acceptance Criteria

- [ ] All four public names importable from `parrot.llm_defaults`
- [ ] Cascade order component → DEFAULT_LLM → builtin, `source` correct
- [ ] Malformed `<C>_LLM` raises ValueError naming the variable
- [ ] Google family → `GOOGLE` token
- [ ] Key cascade per-component then legacy then None; never logged
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_llm_defaults.py -q`

---

## Test Specification

```python
import pytest
from parrot import llm_defaults as ld


@pytest.fixture
def env(monkeypatch):
    values: dict = {}
    monkeypatch.setattr(ld.config, "get", lambda k, fallback=None: values.get(k, fallback))
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", None, raising=False)
    return values

def test_resolve_builtin_when_unset(env): ...
def test_component_var_wins_over_global(env, monkeypatch): ...
def test_global_used_when_component_unset(env, monkeypatch): ...
def test_bare_model_inherits_builtin_provider(env): ...
def test_malformed_raises_named_var(env): ...  # CREW_LLM="nope:x" -> match "CREW_LLM"
def test_provider_token_google_family(): ...
def test_api_key_cascade_order(env): ...  # <C>_GOOGLE_API_KEY in order -> legacy -> None
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5138 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
