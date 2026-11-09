# TASK-5379: Capability flag on AbstractClient and the three provider overrides

**Feature**: FEAT-848 — Client tool-loop capability flag
**Spec**: `sdd/specs/client-tool-loop-capability.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (G1, G2). `AbstractClient` gains one declarative class attribute,
`supports_tool_loop: bool = True`, next to the existing declarative attributes `credential_env` and
`budget_supported_methods`. The three providers whose text `ask()` runs no tool loop declare `False`:
`TransformersClient` (hf), `JevClient` (jev) and `GeminiLiveClient` (google-live). The flag is
declarative only: `ask()` never reads it. Later tasks read it (TASK-5380 fail-fast, TASK-5381 bot
warning) and audit it (TASK-5382 guard test); this task only declares it.

---

## Scope

- Add `supports_tool_loop: bool = True` with its comment block to `AbstractClient`, right after
  `budget_supported_methods`.
- Add `supports_tool_loop: bool = False` with a one-line comment to `TransformersClient`, `JevClient` and
  `GeminiLiveClient`, right after each class's `client_name`.
- Create `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` with `test_default_is_true` and
  `test_known_false_classes`.

**NOT in scope**:
- The AST guard test, `TOOL_EXECUTION_METHODS`, `EXTERNAL_LOOP_CLIENTS`, the Claude bridge test (TASK-5382 —
  it appends to the test file this task creates).
- Any change to a provider's `ask()` / `ask_stream()` or warning text; any reader of the flag
  (TASK-5380, TASK-5381); documentation (TASK-5383).
- Declaring `False` on any other class (AC-3: only these three).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | declare `supports_tool_loop = True` after `budget_supported_methods` |
| `packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py` | MODIFY | `TransformersClient.supports_tool_loop = False` |
| `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` | MODIFY | `JevClient.supports_tool_loop = False` |
| `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` | MODIFY | `GeminiLiveClient.supports_tool_loop = False` |
| `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` | CREATE | default + known-False tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev @ d8832d3fc8` (2026-11-09).

### Verified Imports
```python
from parrot.clients.base import AbstractClient   # verified: packages/ai-parrot/tests/clients/test_credential_env.py:8
# Satellite modules (import only inside the test, through pytest.importorskip):
#   parrot.clients.hf.client      -> TransformersClient   (packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py:31)
#   parrot.clients.jev.client     -> JevClient            (packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py:119)
#   parrot.clients.google.live    -> GeminiLiveClient     (packages/ai-parrot-client-google/src/parrot/clients/google/live.py:328)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                    # :297
    client_type: str = "generic"                                 # :304
    client_name: str = "generic"                                 # :305
    credential_env: Optional[Tuple[str, ...]] = None             # :312 (declarative precedent, comment block :308-311)
    budget_supported_methods: FrozenSet[str] = frozenset()       # :322 (declarative precedent, comment block :319-321)
    def __init_subclass__(cls, **kwargs: Any) -> None: ...       # :324 (blank line :323 before it)

# packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py
class TransformersClient(AbstractClient):                        # :31
    client_type: str = "transformers"                            # :39
    client_name: str = "transformers"                            # :40
    # ask() :319 — `if tools: self.logger.warning("Tool calling not supported by TransformersClient")` :373-374

# packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py
class JevClient(AbstractClient):                                 # :119
    client_type: str = "jev"                                     # :156
    client_name: str = "jev"                                     # :157
    # ask() :496 — `if tools or use_tools: self.logger.warning("JevClient ignores tools: ...")` :546-547

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py
class GeminiLiveClient(AbstractClient):                          # :328
    client_type: str = "google_live"                             # :372
    client_name: str = "google_live"                             # :373
    # ask(self, question, system_prompt=None, history=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]  :1289 (no tools)
```

### Does NOT Exist
- ~~`AbstractClient.supports_tool_loop`~~ before this task, ~~`supports_tools`~~, ~~`has_tool_loop`~~ — nothing of the kind exists.
- ~~`AbstractClient.capabilities`~~ / ~~`client_capabilities`~~ — there is no capability object.
- ~~`parrot.clients.protocols.ToolLoopCapable`~~ — only `VoiceCapable` exists; add no Protocol.
- ~~`supports_stream_tool_loop`~~ — not added by this feature (spec §8).
- ~~`OpenAICodexClient.supports_tool_loop = False`~~ / ~~`ClaudeAgentClient.supports_tool_loop = False`~~ — both stay `True` (inherited); do not touch them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/clients/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/live.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/clients/test_tool_loop_capability.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient",
    "sym:packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py#TransformersClient",
    "sym:packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py#JevClient",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/live.py#GeminiLiveClient"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Declarative class attribute with a comment block, exactly like `credential_env` (`base.py:308-312`) and
`budget_supported_methods` (`base.py:319-322`). No property, no `__init__` plumbing.

### Key Constraints
- `base.py` gains **no import** (`test_import_hygiene.py` subprocess-checks `FORBIDDEN_ON_IMPORT`); `bool` is a builtin.
- `base.py` is the foundation of every provider — insert the attribute and nothing else.
- Code comments carry no line numbers (they rot); the spec's line references live in this task file.
- In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-hf/src:packages/ai-parrot-client-jev/src:packages/ai-parrot-client-google/src` — the shared venv is editable-installed against the main checkout.

### References in Codebase
- `packages/ai-parrot/tests/clients/test_credential_env.py` — test module style for a declarative client attribute.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the attribute in `base.py` after `budget_supported_methods` — *why*: G1 fixes the placement next to the other declarative attributes.
2. Insert the `False` override after `client_name` in the three providers — *why*: G2; the class body is where TASK-5382's audit and readers look.
3. Create the test file — *why*: AC-2/AC-3 need a test that the default is `True` and the three classes declare `False` on the class itself.
4. Run the Validation Commands — *why*: `test_import_hygiene.py` and `test_credential_env.py` prove `base.py` still imports cleanly and the sibling attribute still works (AC-7).

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'budget_supported_methods: FrozenSet[str] = frozenset()' packages/ai-parrot/src/parrot/clients/base.py)
# AFTER — insert below `    budget_supported_methods: FrozenSet[str] = frozenset()` (verified: base.py:322)

    # FEAT-848: whether text ask() executes enabled, registered tools and feeds results back
    # before returning (in-process or through an agent bridge, subject to existing limits).
    # No claim about ask_stream() or inline tools registration. AgenticRetriever fails fast
    # on False instead of reading tool_calls == 0 after a wasted call.
    supports_tool_loop: bool = True
```
**Why this shape**: the comment text is fixed by spec §3 M1. Keep exactly one blank line before the comment
block and keep the existing blank line before `def __init_subclass__` (`:323-324`). Do not touch
`__init_subclass__` or any method.

### `packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'client_name: str = "transformers"' packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py)
# AFTER — insert below `    client_name: str = "transformers"` (verified: hf/client.py:40)
    supports_tool_loop: bool = False  # FEAT-848: ask() warns and ignores tools; no tool loop
```
**Why**: G2. Leave the existing `if tools:` warning in `ask()` exactly as it is.

### `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'client_name: str = "jev"' packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py)
# AFTER — insert below `    client_name: str = "jev"` (verified: jev/client.py:157), above the `# env vars holding ...` comment
    supports_tool_loop: bool = False  # FEAT-848: ask() warns and ignores tools; no tool loop
```
**Why**: G2. The next line (`# env vars holding the server-side API key ...`) belongs to `credential_env`; insert above it.

### `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'client_name: str = "google_live"' packages/ai-parrot-client-google/src/parrot/clients/google/live.py)
# AFTER — insert below `    client_name: str = "google_live"` (verified: live.py:373), above the `# env vars holding ...` comment
    supports_tool_loop: bool = False  # FEAT-848: ask() takes no tools and yields voice; no text tool loop
```
**Why**: G2. `LiveToolAdapter` runs function calls inside the realtime session — that is not the text `ask()`
loop and must not flip the flag (spec §7).

### `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` (CREATE)
```python
"""FEAT-848 — AbstractClient.supports_tool_loop: the declared text ask() tool-loop capability."""

from __future__ import annotations

import pytest

from parrot.clients.base import AbstractClient

# Classes whose text ask() runs no tool loop (spec §6 provider audit): name -> (module, attribute).
KNOWN_FALSE: dict[str, tuple[str, str]] = {
    "TransformersClient": ("parrot.clients.hf.client", "TransformersClient"),
    "JevClient": ("parrot.clients.jev.client", "JevClient"),
    "GeminiLiveClient": ("parrot.clients.google.live", "GeminiLiveClient"),
}


def test_default_is_true() -> None:
    """The base class declares the flag itself, defaulting to True."""
    # FILL IN: assert AbstractClient.supports_tool_loop is True AND "supports_tool_loop" in vars(AbstractClient) — bounded by AC-2


@pytest.mark.parametrize("name", sorted(KNOWN_FALSE))
def test_known_false_classes(name: str) -> None:
    """hf / jev / google-live declare False on their own class body; skipped when the satellite is absent."""
    module_name, attribute = KNOWN_FALSE[name]
    module = pytest.importorskip(module_name)
    cls = getattr(module, attribute)
    # FILL IN: assert cls.supports_tool_loop is False AND "supports_tool_loop" in vars(cls) — bounded by AC-3
```
**Why this shape**: `vars(cls)` proves the value is declared on that class, not inherited. Use `is True` /
`is False`, never truthiness. TASK-5382 appends the guard test to this same file — keep the module docstring
and imports minimal so it can extend them.

### FILL IN checklist
- [ ] `test_tool_loop_capability.py::test_default_is_true` — two asserts; bounded by AC-2
- [ ] `test_tool_loop_capability.py::test_known_false_classes` — two asserts; bounded by AC-3

---

## Acceptance Criteria

- [ ] `AbstractClient.supports_tool_loop` is a class attribute declared in `base.py`, defaulting to `True`; `base.py` gains no import (spec AC-2, AC-7).
- [ ] `TransformersClient`, `JevClient` and `GeminiLiveClient` declare `supports_tool_loop = False`; no other class is changed (spec AC-3).
- [ ] All Validation Commands pass.
- [ ] `ruff check` passes on every file this task touches.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/clients/test_tool_loop_capability.py -q`
- `pytest packages/ai-parrot/tests/clients/test_credential_env.py -q`
- `pytest packages/ai-parrot/tests/clients/test_import_hygiene.py -q`

---

## Test Specification

See the CREATE block above: `test_default_is_true` and the parametrized `test_known_false_classes`
(one case per known-False class, each skipped only when its satellite is not installed).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug client-tool-loop-capability --feature-id FEAT-848`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/client-tool-loop-capability.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/client-tool-loop-capability.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5379 client-tool-loop-capability verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Seat: gpt-5.6-terra (codex). supports_tool_loop flag on AbstractClient + provider overrides. Merge-tier validation green (only baseline reds).

**Completed by**: sdd-worker
**Date**: 2026-11-09
**Notes**: supports_tool_loop flag on AbstractClient + provider overrides

**Deviations from spec**: none
