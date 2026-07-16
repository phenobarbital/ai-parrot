---
type: Wiki Overview
title: 'TASK-1614: `PythonCodeSanitizer` allowlist-first AST gate (WS1)'
id: doc:sdd-tasks-completed-task-1614-pythoncodesanitizer-allowlist-gate-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: WS1 (spec §3 Module 4, G2). The shipped fix (`0f76129b1`) gates `python_repl`
  with
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.command_sanitizer
  rel: mentions
- concept: mod:parrot.security.python_sanitizer
  rel: mentions
- concept: mod:parrot.security.redaction
  rel: mentions
---

# TASK-1614: `PythonCodeSanitizer` allowlist-first AST gate (WS1)

**Feature**: FEAT-252 — REPL Sandbox + Gemini Response Contract + Secret Scrubber
**Spec**: `sdd/specs/repl-sandbox-response-contract-scrubber.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1611
**Assigned-to**: unassigned

---

## Context

WS1 (spec §3 Module 4, G2). The shipped fix (`0f76129b1`) gates `python_repl` with
an AST **denylist** (`_check_ast_security` + `BLOCKED_IMPORTS`/`BLOCKED_NAMES`/
`BLOCKED_ATTRIBUTES`). A denylist chases symptoms; the brainstorm thesis is to
constrain the **space** of allowed operations. This task adds an **allowlist-first
(deny-by-default)** AST gate with two profiles (`general`, `data_analysis`),
promotes the `bots/data.py` forbidden-IO prose into deterministic categorical
denial, and wires it into the REPL exec path.

> **Design note for the implementer (flagged at spec review):** the spec treats the
> allowlist as **replacing** the shipped denylist. Keep the denylist's categorical
> denials as a defense-in-depth layer *underneath* the allowlist (belt-and-suspenders)
> — i.e. allowlist decides first; the categorical denials still hard-fail even if a
> future allowlist edit would let something through. Do not silently delete
> `_check_ast_security`'s coverage; fold it into the categorical-denial set.

---

## Scope

- Create `parrot/security/python_sanitizer.py`:
  - `PythonExecutionPolicy` (frozen dataclass) — `level=SecurityLevel.RESTRICTIVE`,
    `default_deny=True`, `allowed_imports`, `allowed_builtins`, the categorical
    `deny_*` flags (env / introspection / dynamic-exec / data-IO), `isolation="in_process"`,
    `max_output_bytes`.
  - profile factories `general_profile()` and `data_analysis_profile()`
    (`data_analysis` widens the allowlist for pandas/numpy compute on materialized data).
  - `PythonCodeSanitizer.validate(code) -> ValidationResult` — AST walk: any node
    type / call target / import **not** on the allowlist → DENY; categorical denials
    enforced regardless.
- Wire into `PythonREPLTool`: accept `policy: PythonExecutionPolicy` (default the
  general profile); run `sanitizer.validate(code)` in the exec path; on `is_denied`
  return a **structured refusal** (no exec, no echo of the offending code).
- Promote `bots/data.py` forbidden-IO patterns into the `deny_data_io` categorical set
  (read_csv/read_excel/read_json/read_parquet, `open`, `pathlib.read_*`, `glob`,
  `os.listdir`, requests/urllib/httpx/aiohttp, DB drivers, outbound socket).

**NOT in scope**: subprocess isolation (Non-Goal); the scrubber (TASK-1612); the
Gemini client (TASK-1613); final allowlist calibration (Open Q O1 — ship a sane
default + a fixture, leave the exact set tunable).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/python_sanitizer.py` | CREATE | `PythonExecutionPolicy` + profiles + `PythonCodeSanitizer` |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | Export the new symbols |
| `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | MODIFY | Accept policy; run `validate`; structured refusal; keep denials as defense-in-depth |
| `packages/ai-parrot/tests/test_pythonrepl_security.py` | MODIFY | Extend with allowlist/profile/refusal tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# available after TASK-1611
from parrot.security.command_sanitizer import SecurityLevel, ValidationResult, CommandVerdict
# verified — current REPL imports
from parrot.security.redaction import redact_text   # pythonrepl.py:34
import ast                                           # used by _check_ast_security
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
def sanitize_input(query: str) -> str                          # line 43 (fence-strip only)
class PythonREPLArgs(BaseModel): code: str; debug: bool = False  # line 79
class PythonREPLTool(AbstractTool):                            # line 86
    name = "python_repl"; args_schema = PythonREPLArgs
    BLOCKED_IMPORTS: set = {...}      # line 106  (os, socket, subprocess, builtins, pathlib, ...)
    BLOCKED_NAMES: set = {...}        # line 126  (eval, exec, open, globals, locals, vars, __import__, ...)
    BLOCKED_ATTRIBUTES: set           # referenced at line 519
    def _check_ast_security(self, tree: ast.AST) -> Optional[str]   # line 504 (denylist — keep as defense-in-depth)
    def _redact_execution_output(self, output: str) -> str          # line 523
    def _execute_code(self, query, debug=False, ...)                # line 622 (ast.parse @ 644; exec @ 681)
    async def _execute(self, code: str, debug: bool = False, **kwargs) -> Dict[str, Any]  # line 766

# packages/ai-parrot/src/parrot/bots/data.py
#   forbidden-IO prose (system prompt) @ lines 296-300:
#     pd.read_csv/read_excel/read_json/read_parquet, open(...), pathlib.read_*, glob, os.listdir
#   (line 2960 pd.read_csv is the SANCTIONED catalog loader — do NOT treat as forbidden)

# ValidationResult shape (from TASK-1611): verdict, command, reasons, sanitized_command, risk_score;
#   .is_allowed / .is_denied properties. Reuse for the Python verdict (use `command`=code).
```

### Does NOT Exist
- ~~`parrot.security.python_sanitizer`~~ / ~~`PythonCodeSanitizer`~~ / ~~`PythonExecutionPolicy`~~ — this task CREATES them.
- ~~A subprocess/seccomp REPL~~ — Non-Goal; `isolation` stays `"in_process"`.
- ~~An allowlist anywhere today~~ — only the `BLOCKED_*` denylist exists.
- Do NOT remove `_inject_context_to_repl` (`tools/agent.py:404`) or the dataset
  `_repl_locals_getter` — in-process shared state must keep working (Risk R5).

---

## Implementation Notes

### Pattern to Follow
```python
@dataclass(frozen=True)
class PythonExecutionPolicy:
    level: SecurityLevel = SecurityLevel.RESTRICTIVE
    default_deny: bool = True
    allowed_imports: frozenset = frozenset({"navconfig","pandas","numpy","json","math","datetime","statistics","re"})
    allowed_builtins: frozenset = frozenset({"len","range","sum","sorted","min","max","print","enumerate","zip"})
    deny_env_access: bool = True
    deny_introspection: bool = True
    deny_dynamic_exec: bool = True
    deny_data_io: bool = True
    isolation: str = "in_process"
    max_output_bytes: int = 1_048_576

class PythonCodeSanitizer:
    def validate(self, code: str) -> ValidationResult:
        tree = ast.parse(code)
        # walk: import/name/call/attribute NOT allowlisted -> DENY; categorical denials always fire
```
- `allowed_imports` MUST include `navconfig`/`navconfig.logging` and the builtins
  tools depend on (the allowlist is import-friendly by design — it must not break infra).

### Key Constraints
- Allowlist-first, deny-by-default; categorical denials (env/introspection/dynamic-exec/
  data-IO) fire even if the allowlist would otherwise pass something.
- Structured refusal on deny: return the tool's standard error dict, no exec, no echo
  of offending code.
- Keep `general` tightest (Jira/GitHub agents get real data via tools, not the REPL);
  `data_analysis` widens only to pandas/numpy compute on already-materialized DataFrames.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/pythonrepl.py` — exec path + current denylist.
- `packages/ai-parrot-tools/.../shell_tool/security.py` — RESTRICTIVE allowlist posture to mirror.

---

## Acceptance Criteria

- [ ] `from parrot.security.python_sanitizer import PythonCodeSanitizer, PythonExecutionPolicy, general_profile, data_analysis_profile` resolves.
- [ ] `validate()` DENIES `os.environ`, `os.getenv`, `dict(os.environ)` under both profiles.
- [ ] DENIES introspection (`().__class__.__bases__`, `globals()`, `vars()`), dynamic exec (`eval`/`exec`/`compile`/`__import__`), and data-IO (`open`, `pd.read_csv`, `requests.get`).
- [ ] ALLOWS ordinary compute (`sum([1,2,3])`, pandas/numpy on a provided DataFrame) under the appropriate profile.
- [ ] A denied REPL submission returns a structured refusal (no execution, no echo of the offending code).
- [ ] `general` rejects something `data_analysis` permits (e.g. wider pandas surface) — profile differentiation proven.
- [ ] `_inject_context_to_repl` + dataset state path still function (no subprocess regression).
- [ ] `pytest packages/ai-parrot/tests/test_pythonrepl_security.py -v` passes (incl. `0f76129b1` cases).
- [ ] `ruff check` clean on new/changed files.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_pythonrepl_security.py (extend)
import pytest
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile, data_analysis_profile

@pytest.fixture
def gen():
    return PythonCodeSanitizer(general_profile())

class TestPythonAllowlistGate:
    @pytest.mark.parametrize("code", [
        "import os; os.environ", "dict(os.environ)", "os.getenv('X')",
        "().__class__.__bases__", "globals()", "eval('1+1')", "open('/etc/passwd')",
        "import pandas as pd; pd.read_csv('x.csv')",
    ])
    def test_denied(self, gen, code):
        assert gen.validate(code).is_denied

    @pytest.mark.parametrize("code", ["sum([1,2,3])", "x = [i*2 for i in range(5)]", "len('abc')"])
    def test_allowed(self, gen, code):
        assert gen.validate(code).is_allowed

    def test_profile_differentiation(self):
        wide = "df.merge(other, on='k').pivot_table(index='a')"
        assert PythonCodeSanitizer(data_analysis_profile()).validate(wide).is_allowed
```

---

## Agent Instructions
(standard — verify TASK-1611 in `completed/`; verify contract; keep denials as defense-in-depth.)

## Completion Note

Implemented by sdd-worker (FEAT-252). Created `parrot/security/python_sanitizer.py`
with `PythonExecutionPolicy` (frozen dataclass), `PythonCodeSanitizer.validate()`,
`general_profile()`, and `data_analysis_profile()`. All symbols exported from
`parrot.security.__init__`. Wired into `PythonREPLTool.__init__` (`policy` kwarg,
defaults to `general_profile()`) and `_execute_code` (allowlist gate fires before
the existing `_check_ast_security` denylist as defence-in-depth). Used
`CommandVerdict.ALLOWED`/`CommandVerdict.DENIED` (correct enum values). Existing
tests updated to accept `SecurityError:` prefix alongside `BlockedOperationError:`.
32 total tests pass (7 original + 25 new). `python_sanitizer.py` is ruff-clean.
