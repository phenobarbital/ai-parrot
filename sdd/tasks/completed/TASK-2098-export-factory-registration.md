# TASK-2098: Package export + LLMFactory registration

**Feature**: FEAT-407 — Bedrock Mantle Client
**Spec**: `sdd/specs/bedrock-mantle-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2097
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2: make `BedrockMantleClient` (created in TASK-2097)
reachable the two ways every AI-Parrot client is reachable — as a
package export (`from parrot.clients.nova import BedrockMantleClient`)
and via `LLMFactory` string specs (`"bedrock-mantle:<model>"`,
`"mantle:<model>"`) so agents/crews can select it anywhere an `llm`
string is accepted.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/clients/nova/__init__.py`:
  import `BedrockMantleClient` from `.mantle` and add it to `__all__`.
- Modify `packages/ai-parrot/src/parrot/clients/factory.py`:
  - Add a `_lazy_bedrock_mantle()` loader following the `_lazy_nova`
    pattern (docstring included, `# FEAT-407` reference).
  - Register keys `"bedrock-mantle"` and `"mantle"` in
    `SUPPORTED_CLIENTS`, pointing at the lazy loader, with a short
    `# FEAT-407` comment distinguishing it from `"bedrock"` (FEAT-232),
    `"bedrock-converse"` (FEAT-302), and `"nova"` (FEAT-315).

**NOT in scope**: any change to `mantle.py` itself (TASK-2097); tests
and docs (TASK-2099); touching `PROVIDER_BACKEND` or any other factory
mapping.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/__init__.py` | MODIFY | Export `BedrockMantleClient` |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | Lazy loader + 2 `SUPPORTED_CLIENTS` keys |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.nova.mantle import BedrockMantleClient  # created by TASK-2097 — verify it exists before starting
from parrot.clients.nova import NovaClient                  # verified: packages/ai-parrot/src/parrot/clients/nova/__init__.py:8
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/__init__.py (current full content, lines 1-11)
"""Amazon Nova client subpackage (FEAT-315). ..."""
from __future__ import annotations

from .client import NovaClient

__all__ = ["NovaClient"]
```

```python
# packages/ai-parrot/src/parrot/clients/factory.py — lazy-loader pattern to copy
def _lazy_nova():
    """Lazy loader for :class:`NovaClient` (FEAT-315). ..."""
    from .nova import NovaClient
    return NovaClient

# packages/ai-parrot/src/parrot/clients/factory.py — SUPPORTED_CLIENTS (excerpt)
SUPPORTED_CLIENTS = {
    "claude": AnthropicClient,
    "bedrock": AnthropicClient,            # FEAT-232 backend-injected
    "bedrock-converse": _lazy_bedrock_converse,  # FEAT-302
    "nova": _lazy_nova,                    # FEAT-315
    "openai": OpenAIClient,
    ...
    "claude-agent": _lazy_claude_agent,
    "claude-code": _lazy_claude_agent,
}
```

```python
# packages/ai-parrot/src/parrot/clients/factory.py — LLMFactory (API outline)
class LLMFactory:
    def parse_llm_string(llm): ...   # 'provider:model' or 'provider'
    def create(llm, model_args, tool_manager): ...
```

### Does NOT Exist

- ~~`"bedrock-mantle"` / `"mantle"` keys in `SUPPORTED_CLIENTS`~~ —
  THIS task adds them.
- ~~`_lazy_bedrock_mantle` in factory.py~~ — THIS task adds it.
- ~~`register_client` decorator for LLM clients~~ — clients are
  registered by direct dict entry in `SUPPORTED_CLIENTS`, not via the
  `parrot.registry` decorators (those are for agents/bots).
- ~~`parrot.clients.mantle`~~ — the module is
  `parrot.clients.nova.mantle` (inside the nova subpackage).

---

## Implementation Notes

### Pattern to Follow

```python
def _lazy_bedrock_mantle():
    """Lazy loader for :class:`BedrockMantleClient` (FEAT-407).

    Keeps the same deferred-import pattern as :func:`_lazy_nova` /
    :func:`_lazy_bedrock_converse`.
    """
    from .nova.mantle import BedrockMantleClient
    return BedrockMantleClient
```

Register both keys adjacent to the other Bedrock entries so the
Bedrock family reads as a block.

### Key Constraints

- Lazy loader (NOT a top-level import in factory.py) — keeps import
  cost off the common path, consistent with nova/bedrock-converse.
- Do not reorder or reformat unrelated `SUPPORTED_CLIENTS` entries.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/factory.py` — loader + registration pattern
- `packages/ai-parrot/src/parrot/clients/nova/__init__.py` — export pattern

---

## Acceptance Criteria

- [ ] `from parrot.clients.nova import BedrockMantleClient` works
- [ ] `LLMFactory` resolves `"bedrock-mantle:openai.gpt-oss-120b"` to a `BedrockMantleClient` with the model set
- [ ] `LLMFactory` resolves the `"mantle"` alias identically
- [ ] Existing keys still resolve (spot-check `"nova"`, `"openai"`, `"bedrock-converse"`)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/factory.py packages/ai-parrot/src/parrot/clients/nova/__init__.py`

---

## Test Specification

> Formal tests land in TASK-2099 (`test_factory_creates_mantle_client`).
> Inline verification for THIS task:

```python
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.nova import BedrockMantleClient

assert "bedrock-mantle" in SUPPORTED_CLIENTS
assert "mantle" in SUPPORTED_CLIENTS
assert SUPPORTED_CLIENTS["bedrock-mantle"]() is BedrockMantleClient
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2097 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/bedrock-mantle-client.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2098-export-factory-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-03
**Notes**: Exported `BedrockMantleClient` from `parrot/clients/nova/__init__.py`
(added to `__all__`, kept isort-sorted per ruff RUF022). Added
`_lazy_bedrock_mantle()` to `factory.py` following the `_lazy_nova`
pattern, and registered `"bedrock-mantle"` / `"mantle"` in
`SUPPORTED_CLIENTS` adjacent to the other Bedrock-family entries with a
`# FEAT-407` comment. Verified via inline script: both keys resolve to
`BedrockMantleClient`, `LLMFactory.create("bedrock-mantle:openai.gpt-oss-120b")`
and the `"mantle"` alias both return a configured instance with the model
set, and existing `"nova"`/`"openai"`/`"bedrock-converse"` keys still
resolve correctly. `ruff check` clean on both touched files (pre-existing
unrelated lint debt in `factory.py` — Dict/Tuple/Optional style, TRY004 —
left untouched, out of scope for this task).

**Deviations from spec**: none
