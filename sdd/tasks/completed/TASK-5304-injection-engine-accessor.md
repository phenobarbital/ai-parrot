# TASK-5304: Public injection scoring engine accessor

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the accessor half of spec §3 **Module 5** (brainstorm decision: the public accessor
lives in `parrot.security.prompt_injection`). Import-time scoring of segments (TASK-5305) needs the
same ML engine the `PromptInjectionGuardrail` resolves, but that engine and its Protocol are
module-private today (`bots/guardrails/builtin/prompt_injection.py:167`, `:514`).

---

## Scope

- Add the public Protocol `InjectionScoringEngine` and `get_injection_scoring_engine()` to
  `security/prompt_injection.py`; re-export both from `security/__init__.py`.
- In the guardrail module, replace the private Protocol class with an alias of the public one:
  `_InjectionScoringEngine = InjectionScoringEngine`.
- Write `tests/unit/test_security_injection_engine_accessor.py`.

**NOT in scope**: moving the resolution chain (it stays where it is — that module owns the
pytector/onnxruntime import boundary by documented invariant, its docstring lines 8-25); any
behaviour change in the guardrail.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/prompt_injection.py` | MODIFY | Protocol + accessor |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | Re-export |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | Alias the private Protocol |
| `packages/ai-parrot/tests/unit/test_security_injection_engine_accessor.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Optional, Dict, Any, List, Tuple   # security/prompt_injection.py:4 (extend with Protocol, runtime_checkable)
from parrot.bots.guardrails.builtin.prompt_injection import _resolve_injection_engine  # :514 — FUNCTION-SCOPED import only
```

### Existing Signatures to Use
```python
# security/prompt_injection.py
class ThreatLevel(Enum)                                       # :14
class PromptInjectionDetector                                 # :102
class SecurityEventLogger:                                    # :297 — insert the new symbols above this line

# security/__init__.py
from .prompt_injection import (                               # :8
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel, THREAT_LEVEL_ORDER, max_threat_level,
    PromptInjectionException                                  # :14 (last name, no trailing comma)
)                                                             # :15

# bots/guardrails/builtin/prompt_injection.py
from parrot.security.prompt_injection import (                # :47-52 — already imports from parrot.security
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel, max_threat_level,
)
@runtime_checkable
class _InjectionScoringEngine(Protocol):                      # :166-179 (decorator on :166)
    engine_name: str; model_id: str
    def score(self, text: str) -> float: ...
def _resolve_injection_engine(force_reresolve: bool = False) -> _InjectionScoringEngine | None  # :514 — memoized, never raises
```

### Does NOT Exist
- ~~`InjectionScoringEngine`, `get_injection_scoring_engine`~~ in `parrot.security` — created here
- ~~a module-level import of `parrot.bots` in `parrot.security`~~ — must stay absent (layering; AC-2)
- ~~`parrot.security.injection_engine` module~~ — do not create a new module; the spec fixes the location

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/security/prompt_injection.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/security/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_security_injection_engine_accessor.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_resolve_injection_engine",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_InjectionScoringEngine",
    "sym:packages/ai-parrot/src/parrot/security/prompt_injection.py#PromptInjectionDetector"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The accessor imports `_resolve_injection_engine` **inside the function** — *because*
  `parrot.security` must not import `parrot.bots` at import time, and the guardrail module already
  imports `parrot.security.prompt_injection` (a module-level import would also be circular).
- The accessor never raises: on `ImportError` (or any `Exception`) it logs a warning and returns
  `None` — *because* callers fall back to the regex detector (spec §2 *Injection scoring*).
- Keep the private name `_InjectionScoringEngine` in the guardrail module — *because* 48 test
  references use it (`tests/unit/test_guardrails_prompt_injection.py` and six other files).
- The public Protocol is `@runtime_checkable` like the private one, so `isinstance` checks in
  existing tests keep working.

---

## Implementation Blueprint

### Steps (in order)
1. Add the Protocol and accessor to `security/prompt_injection.py`.
2. Re-export from `security/__init__.py`.
3. Replace the guardrail's private class with the alias.
4. Write the tests; run the existing guardrail tests.

### `packages/ai-parrot/src/parrot/security/prompt_injection.py` (MODIFY)
```python
# MODIFY — line `from typing import Optional, Dict, Any, List, Tuple` (verified: security/prompt_injection.py:4)
# occurrences: 1 (verified: grep -c '^from typing import' security/prompt_injection.py)
from typing import Optional, Dict, Any, List, Protocol, Tuple, runtime_checkable

# BEFORE — insert above `class SecurityEventLogger:` (verified: security/prompt_injection.py:297)
# occurrences: 1 (verified: grep -c '^class SecurityEventLogger:' security/prompt_injection.py)
@runtime_checkable
class InjectionScoringEngine(Protocol):
    """Public contract of a resolved ML prompt-injection scorer.

    ``score`` returns an injection probability in ``[0, 1]``. Implementations are thread-safe
    and must be called off the event loop (``asyncio.to_thread``).
    """

    engine_name: str
    model_id: str

    def score(self, text: str) -> float:
        """Return the injection probability for ``text``."""
        ...


def get_injection_scoring_engine(force_reresolve: bool = False) -> Optional[InjectionScoringEngine]:
    """Return the process-wide ML engine the PromptInjectionGuardrail uses, or ``None`` (regex only).

    The resolution chain lives in ``parrot.bots.guardrails.builtin.prompt_injection``, which owns the
    pytector/onnxruntime import boundary; it is imported lazily here so ``parrot.security`` never
    imports ``parrot.bots`` at module import time. Never raises.
    """
    # FILL IN: function-scoped import of _resolve_injection_engine; return its result; on Exception log
    # logger.warning(...) and return None — bounded by AC-1, AC-2
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/security/__init__.py` (MODIFY)
```python
# MODIFY — the line `    PromptInjectionException` (verified: security/__init__.py:14)
# occurrences: 1 (verified: grep -c '    PromptInjectionException' security/__init__.py)
    PromptInjectionException,
    InjectionScoringEngine,
    get_injection_scoring_engine,
```

### `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` (MODIFY)
```python
# REPLACE — the decorator + class block starting at `class _InjectionScoringEngine(Protocol):`
#   (verified: :166-179; the `@runtime_checkable` decorator sits on :166)
# occurrences: 1 (verified: grep -c '^class _InjectionScoringEngine(Protocol):' prompt_injection.py)
# Also add `InjectionScoringEngine` to the existing `from parrot.security.prompt_injection import (...)` (:47-52).
#: Module-private alias kept for existing callers/tests; the contract is public since FEAT-840.
_InjectionScoringEngine = InjectionScoringEngine
# FILL IN: drop `Protocol`/`runtime_checkable` from the `typing` import ONLY if ruff reports them unused
#   — bounded by "no behaviour change"
```

### FILL IN checklist
- [ ] accessor body; bounded by AC-1, AC-2
- [ ] guardrail alias and import cleanup; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: `get_injection_scoring_engine()` returns the same object as `_resolve_injection_engine()` (monkeypatch the resolver to return a sentinel engine and compare identity); when the import or the resolver raises it returns `None`.
- [ ] AC-2: in a fresh interpreter, `import parrot.security.prompt_injection` leaves no `parrot.bots*` key in `sys.modules` (run it with `subprocess` and `sys.executable`).
- [ ] AC-3: `_InjectionScoringEngine is InjectionScoringEngine`; `tests/unit/test_guardrails_prompt_injection.py` passes unchanged.
- [ ] `ruff check` on the three source files passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_security_injection_engine_accessor.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_security_injection_engine_accessor.py
import subprocess
import sys

from parrot.security.prompt_injection import InjectionScoringEngine, get_injection_scoring_engine


class _Fake:
    engine_name = "fake"
    model_id = "fake"

    def score(self, text: str) -> float:
        return 0.5


def test_accessor_returns_guardrail_engine(monkeypatch):
    import parrot.bots.guardrails.builtin.prompt_injection as gr
    fake = _Fake()
    monkeypatch.setattr(gr, "_resolve_injection_engine", lambda force_reresolve=False: fake)
    assert get_injection_scoring_engine() is fake
    assert isinstance(fake, InjectionScoringEngine)


def test_accessor_never_raises(monkeypatch):
    # FILL IN: resolver raising RuntimeError → None — AC-1
    ...


def test_security_import_does_not_load_bots():
    code = "import sys, parrot.security.prompt_injection; print(any(k.startswith('parrot.bots') for k in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out.splitlines()[-1] == "False"


def test_guardrail_protocol_alias():
    import parrot.bots.guardrails.builtin.prompt_injection as gr
    assert gr._InjectionScoringEngine is InjectionScoringEngine
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5304 — Public injection scoring engine accessor`), then close with
   `parrot sdd task close TASK-5304 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

Added InjectionScoringEngine Protocol + get_injection_scoring_engine (lazy import, never raises) in parrot.security; guardrail aliases the Protocol. 4 new tests + 45 existing guardrail tests pass.

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-07
**Notes**: tests run with a scratchpad-only shim for navconfig's read-only log dir (environment, not committed)
**Deviations from spec**: none
