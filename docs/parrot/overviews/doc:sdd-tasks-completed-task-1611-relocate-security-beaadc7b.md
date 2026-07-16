---
type: Wiki Overview
title: 'TASK-1611: Relocate the shared security engine into core (`parrot.security`)'
id: doc:sdd-tasks-completed-task-1611-relocate-security-engine-to-core-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation (spec §3 Module 1, G1). The compiled, deterministic security engine
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.command_sanitizer
  rel: mentions
- concept: mod:parrot_tools.shell_tool.security
  rel: mentions
---

# TASK-1611: Relocate the shared security engine into core (`parrot.security`)

**Feature**: FEAT-252 — REPL Sandbox + Gemini Response Contract + Secret Scrubber
**Spec**: `sdd/specs/repl-sandbox-response-contract-scrubber.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation (spec §3 Module 1, G1). The compiled, deterministic security engine
(`CommandSanitizer`/`SecurityPolicy`/`SecurityLevel`/`ValidationResult`/
`CommandVerdict`) lives in the **satellite** package `ai-parrot-tools`. The
dependency direction is `parrot_tools → core`, so core **cannot** import it
upward. WS1 (`PythonCodeSanitizer`) and WS3 (`OutputScrubber`) both need it, so
it must be relocated **down into core** `parrot.security` and re-exported to
`shell_tool`. This is the first task — everything else builds on it.

---

## Scope

- Create `parrot/security/command_sanitizer.py` containing the relocated engine:
  `SecurityLevel`, `CommandVerdict`, `ValidationResult`, `CommandRule`,
  `SecurityPolicy`, `CommandSanitizer` (and `CommandSecurityError`,
  `SecureShellMixin` if cleanly movable — otherwise leave shell-specific helpers
  in `shell_tool`).
- Turn `parrot_tools/shell_tool/security.py` into a **re-export shim**: import the
  relocated symbols from `parrot.security.command_sanitizer` so every existing
  `from parrot_tools.shell_tool.security import ...` keeps working **verbatim**.
- Export the generic primitives from `parrot/security/__init__.py` (`__all__`).
- No behavior change: RESTRICTIVE/MODERATE/PERMISSIVE verdicts must be identical
  before and after.

**NOT in scope**: `PythonCodeSanitizer` (TASK-1614), `OutputScrubber` (TASK-1612),
any Gemini-client work (TASK-1613), moving shell-execution/path logic that is
genuinely shell-only (keep it in `shell_tool` if extraction is awkward — code
duplication is explicitly acceptable per the brainstorm, but prefer relocation).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/command_sanitizer.py` | CREATE | Relocated engine (generic, shell-agnostic primitives) |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | Export relocated symbols in `__all__` |
| `packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py` | MODIFY | Re-export shim from core; keep shell-only helpers |
| `packages/ai-parrot/tests/test_command_sanitizer_core.py` | CREATE | Relocation + re-export + verdict-parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# CURRENT home (to be relocated) — verified packages/ai-parrot-tools/.../shell_tool/security.py
from parrot_tools.shell_tool.security import (
    SecurityLevel, CommandVerdict, ValidationResult, CommandRule,
    SecurityPolicy, CommandSanitizer,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py
class SecurityLevel(str, Enum):           # line 36 — RESTRICTIVE/MODERATE/PERMISSIVE (values 39-41)
class CommandVerdict(str, Enum):          # line 44
@dataclass(frozen=True)
class ValidationResult:                   # line 58
    verdict: CommandVerdict
    command: str
    reasons: Tuple[str, ...] = ()
    sanitized_command: Optional[str] = None
    risk_score: float = 0.0
    @property def is_allowed(self) -> bool   # line 76
    @property def is_denied(self) -> bool    # line 81
@dataclass
class CommandRule:                        # line 99
class CommandSecurityError(Exception):    # line 135
@dataclass
class SecurityPolicy:                     # line 321
    level: SecurityLevel = SecurityLevel.MODERATE   # line 358
    @classmethod
    def restrictive(cls, allowed_commands: Optional[Set[str]] = None,
                    sandbox_dir: Optional[str] = None,
                    command_rules: Optional[Dict[str, CommandRule]] = None) -> "SecurityPolicy"  # line 391
    @classmethod def moderate(...) -> "SecurityPolicy"     # line 428
    @classmethod def permissive(...) -> "SecurityPolicy"   # line 466
class CommandSanitizer:                   # line 564
    def validate(self, command: str) -> ValidationResult       # line 618
    def validate_batch(self, commands) -> List[ValidationResult]  # line 749
    def validate_path(self, path: str) -> ValidationResult     # line 1001
class SecureShellMixin:                   # line 1071 (shell-specific — may stay in shell_tool)

# Module imports only stdlib: logging, os, re, shlex, dataclasses, enum, pathlib, typing (lines 19-28)
```

### Existing core package (target)
```python
# packages/ai-parrot/src/parrot/security/__init__.py — current __all__ exports:
#   PromptInjectionDetector, SecurityEventLogger, ThreatLevel, PromptInjectionException,
#   QueryLanguage, QueryValidator, load_vault_keys, store/retrieve/delete_vault_credential,
#   oauth2_vault_name, VAULT_CRED_COLLECTION, encrypt_credential, decrypt_credential
# Sibling modules already present: prompt_injection.py, query_validator.py, vault_utils.py,
#   credentials_utils.py, redaction.py
```

### Does NOT Exist
- ~~`parrot.security.command_sanitizer`~~ — this task CREATES it.
- ~~`parrot.security.CommandSanitizer`~~ (top-level) — only after this task exports it.
- The engine has **no** `parrot.*` internal imports today (stdlib-only) — relocation is
  import-safe; do not invent core dependencies it doesn't have.

---

## Implementation Notes

### Pattern to Follow
- Mirror how `parrot/security/` already houses relocated utilities (FEAT-203 moved
  vault/prompt-injection into this package). Keep the module stdlib-only.
- Re-export shim shape in `shell_tool/security.py`:
  ```python
  from parrot.security.command_sanitizer import (
      SecurityLevel, CommandVerdict, ValidationResult, CommandRule,
      SecurityPolicy, CommandSanitizer, CommandSecurityError,
  )  # re-exported for backward compatibility (FEAT-252)
  ```
  Keep `__all__` in the shim so star-imports are unchanged.

### Key Constraints
- **Zero behavior change.** Parity test must prove identical verdicts.
- Keep every existing import path working — `parrot_tools` and any other caller.
- `parrot_tools → core` only; never make core import `parrot_tools`.
- Watch the `_MODERATE_SAFE_DEFAULTS` set and the per-command rule helpers — move
  them with the engine or keep them adjacent; do not split a frozen dataclass from
  its defaults.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py` — the source.
- `packages/ai-parrot/src/parrot/security/__init__.py` — export site.

---

## Acceptance Criteria

- [ ] `from parrot.security.command_sanitizer import SecurityPolicy, CommandSanitizer, SecurityLevel, ValidationResult, CommandVerdict` resolves.
- [ ] `from parrot_tools.shell_tool.security import CommandSanitizer, SecurityPolicy` still resolves (shim).
- [ ] Verdict parity: a fixed command set yields identical `ValidationResult.verdict` + `risk_score` pre/post relocation (RESTRICTIVE/MODERATE/PERMISSIVE).
- [ ] `pytest packages/ai-parrot/tests/test_command_sanitizer_core.py -v` passes.
- [ ] Existing shell_tool tests still pass: `pytest packages/ai-parrot-tools -k shell -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/security/command_sanitizer.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_command_sanitizer_core.py
import pytest
from parrot.security.command_sanitizer import (
    SecurityPolicy, CommandSanitizer, SecurityLevel, CommandVerdict,
)

class TestRelocatedEngine:
    def test_core_import_resolves(self):
        assert SecurityLevel.RESTRICTIVE.value == "restrictive"

    def test_shell_tool_reexport_is_same_object(self):
        from parrot_tools.shell_tool.security import CommandSanitizer as ShimCS
        assert ShimCS is CommandSanitizer

    def test_restrictive_denies_unlisted(self):
        pol = SecurityPolicy.restrictive(allowed_commands={"ls"})
        san = CommandSanitizer(pol)
        assert san.validate("rm -rf /").is_denied
        assert san.validate("ls").is_allowed
```

---

## Agent Instructions

(standard — see template; verify the contract before coding, update index, move to
`tasks/completed/` on done.)

## Completion Note

Implemented by sdd-worker (FEAT-252). The full `CommandSanitizer` / `SecurityPolicy` /
`SecurityLevel` / `CommandVerdict` / `ValidationResult` / `CommandRule` /
`CommandSecurityError` engine was copied verbatim (stdlib-only) to
`packages/ai-parrot/src/parrot/security/command_sanitizer.py`.
`parrot/security/__init__.py` exports all 7 symbols in `__all__`.
`parrot_tools/shell_tool/security.py` is now a re-export shim plus
the shell-specific `SecureShellMixin`. All 14 unit tests pass; ruff clean.
