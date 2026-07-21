# TASK-1721: Catalog registry + component contract

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1720
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3, "Catalog registry + component contract"). The catalog is the security allowlist at the heart of G1: envelopes are validated against registered `ComponentDefinition`s, so only known components ever reach a renderer. It also carries the mandatory-lowering contract (G4/D8 — every custom component ships a pure deterministic `lower()` to a Basic Catalog tree, enforced at registration, not by convention) and the `requires_actions` gate (G2/D10b — LLM-produced envelopes may not contain action-bearing components in v1).

---

## Scope

- Create `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/` with `base.py` + `__init__.py`.
- Implement `ComponentDefinition` (Pydantic v2) per spec §2 Data Models: `name: str`, `catalog_id: str = "https://parrot.dev/catalogs/v1"`, `schema_: Dict[str, Any]` (jsonschema for the component payload), `instructions: str` (embedded LLM guidance per the A2UI spec), `requires_actions: bool = False`.
- Implement the `@register_component(name, *, requires_actions=False)` decorator and the catalog registry (lookup by name, listing, catalog-wide `instructions` aggregation for the LLM producer to consume later).
- **ENFORCE the mandatory `lower()` contract at registration time**: a component class that does not implement a callable `lower(component, data_model) -> BasicTree` CANNOT register — registration raises a structured error. This is enforcement, not convention (spec acceptance G4).
- Implement allowlist validation of envelopes: walk a `CreateSurface` envelope's component tree; any component name not registered in the catalog → structured validation error naming the offending component.
- Implement `requires_actions` enforcement for LLM-produced envelopes: validation entry point takes a producer origin (tool vs LLM); an LLM-produced envelope containing any `requires_actions=True` component fails validation in v1.
- Write unit tests: unknown-component rejection, registration-without-`lower()` rejection, `requires_actions` LLM rejection (and tool-produced acceptance), decorator registration round-trip.

**NOT in scope**:
- The nine concrete v1 components and their lowerings/golden files (Module 3, separate per-component tasks incl. TASK-1724).
- Renderer registry / capabilities (TASK-1723 / Module 4).
- The LLM producer validate-retry loop itself (Module 9) — this task only provides the validation entry point it will call.
- Basic Catalog *rendering* — `lower()` output is a data tree; renderers live in the satellite.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | CREATE | `ComponentDefinition`, component-contract ABC/protocol with `lower()`, registry internals |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | CREATE | `register_component` decorator, catalog lookup/list, envelope allowlist validation |
| `packages/ai-parrot/tests/outputs/a2ui/test_catalog.py` | CREATE | Registration contract, allowlist, requires_actions tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.models import CreateSurface  # created by TASK-1720 — verify exact export names in a2ui/__init__.py before use
from parrot.outputs.formats import register_renderer, get_renderer  # pattern reference ONLY — verified: outputs/formats/__init__.py:47/:62
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:47-60 — the decorator
# registration pattern to FOLLOW (on the NEW A2UI registry; do not touch this file):
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
    def decorator(cls):
        RENDERERS[mode] = cls
        if system_prompt:
            _PROMPTS[mode] = system_prompt
        return cls
    return decorator

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:16-17 — registry-dict shape:
RENDERERS: Dict[OutputMode, Type[Renderer]] = {}
_PROMPTS: Dict[OutputMode, str] = {}
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.catalog`~~ — this task creates it.
- ~~Any existing component-catalog or allowlist machinery~~ — legacy `formats/` registry maps `OutputMode → renderer class` only; there is no component-level allowlist anywhere.
- ~~`BasicTree` as an existing type~~ — the Basic Catalog tree type is defined by this feature (this task may define it minimally as a type alias/model for the `lower()` return contract; Module 3 fleshes it out).
- ~~`ActionRouter` / any action dispatch~~ — FEAT-B territory; `requires_actions` here is a validation flag only.

### Key Constraints (spec G1/G8)
- Zero new core dependencies. jsonschema validation of component payloads may use a light structural check or defer full-schema validation — do NOT add the `jsonschema` package to core without checking it is already a core dependency (`grep jsonschema packages/ai-parrot/pyproject.toml` first; if absent, validate structurally with pydantic/stdlib).
- One-way import rule: never import agents, DatasetManager, or LLM clients.
- No `exec(`/`eval(`.

---

## Implementation Notes

### Pattern to Follow
Decorator registration exactly as `register_renderer` in `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:47` (module-level registry dict + decorator that inserts and returns the class) — but on the new A2UI catalog registry, keyed by component `name`, and with the added registration-time `lower()` enforcement:

```python
# Shape (plan-level, not implementation): inside the decorator, before inserting
# into the registry, verify `callable(getattr(cls, "lower", None))`; if not,
# raise a structured registration error — component cannot register without lower().
```

### Key Constraints
- `lower()` contract per spec §2 New Public Interfaces: `def lower(self, component, data_model) -> BasicTree` — pure and deterministic (D8); document purity in the contract docstring (golden-file tests in Module 3 rely on it).
- `schema_` uses the trailing-underscore field name (spec §2) to avoid shadowing `BaseModel.schema`; keep the wire/dump alias consistent.
- Allowlist validation must report ALL unknown components found (structured error), not just the first, to feed Module 9's retry re-prompt.
- Validation entry point signature should make producer origin explicit (e.g. an enum/flag parameter), because `requires_actions` rejection applies ONLY to LLM-produced envelopes — tool builders may emit `requires_actions` components (they degrade to deep links at render time, Module 5/8).
- Google-style docstrings, strict type hints, `logging.getLogger(__name__)`-style logger if module-level logging is needed.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` — decorator registration pattern.
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` (TASK-1720) — envelope models to validate.
- Spec §3 Module 3 — the nine components that will register through this decorator (Infographic, Report, Map, Chart, DataTable, KPICard, Card, Timeline, Form).

---

## Acceptance Criteria

- [ ] `@register_component` registers a component with `ComponentDefinition` metadata; lookup and listing work.
- [ ] Registration of a component class without a callable `lower()` raises a structured error — enforced at registration time (spec G4).
- [ ] Envelope allowlist validation: unknown component name → structured validation error naming the component (`test_envelope_rejects_unknown_component`).
- [ ] LLM-produced envelope containing a `requires_actions=True` component fails validation; the same envelope from a tool producer passes (`test_llm_envelope_rejects_requires_actions`).
- [ ] `ComponentDefinition.catalog_id` defaults to `https://parrot.dev/catalogs/v1`.
- [ ] `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing; no new core deps.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog.py -v` (and existing `tests/outputs/a2ui/` still green)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/`
- [ ] Imports work: `from parrot.outputs.a2ui.catalog import register_component, ComponentDefinition`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_catalog.py
import pytest


class TestComponentRegistration:
    def test_register_component_roundtrip(self):
        """A component registered via @register_component is retrievable by name with its ComponentDefinition."""
        ...

    def test_register_without_lower_rejected(self):
        """A component class lacking a callable lower() cannot register (structured error)."""
        ...

    def test_catalog_id_default(self):
        """ComponentDefinition.catalog_id defaults to https://parrot.dev/catalogs/v1."""
        ...


class TestEnvelopeValidation:
    def test_envelope_rejects_unknown_component(self):
        """Allowlist: an envelope referencing an unregistered component name fails with a structured error."""
        ...

    def test_llm_envelope_rejects_requires_actions(self):
        """LLM-produced envelope containing a requires_actions component fails validation in v1."""
        ...

    def test_tool_envelope_allows_requires_actions(self):
        """Tool-produced envelope with a requires_actions component passes validation."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1721-a2ui-catalog-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Created `parrot.outputs.a2ui.catalog` (`base.py` + `__init__.py`).
`base.py` defines `ComponentDefinition` (with `schema_`/wire-alias `schema`,
`catalog_id` defaulting to `https://parrot.dev/catalogs/v1`, `requires_actions`),
the `BasicNode`/`BasicTree` lowering-return contract (minimal, fleshed out in
Module 3), `ProducerOrigin` enum, `RegisteredComponent`, and structured errors
(`CatalogError`, `ComponentContractError`, `CatalogValidationError` carrying
`unknown_components`/`action_components`). `__init__.py` implements
`@register_component` (mirrors `formats.register_renderer`) with registration-time
enforcement of a callable `lower()`, plus `get_component`/`list_components`/
`catalog_instructions`/`unregister_component` and `validate_envelope` (reports ALL
unknown components; LLM-origin rejects `requires_actions` components, tool-origin
allows them). 28 tests pass (10 new); ruff clean; no exec/eval; no new core deps.

**Deviations from spec**: none. Convention established for Module 3: components
expose class attributes `SCHEMA` (dict) and `INSTRUCTIONS` (str), which the
decorator folds into the `ComponentDefinition` (the spec's `register_component`
signature carries only `name`/`requires_actions`, so schema+instructions come from
the class). jsonschema is not a core dep, so payload validation is structural
(allowlist) only — full JSON-Schema validation deferred.
