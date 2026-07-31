---
type: Wiki Overview
title: 'Feature Specification: REPL Sandbox + Gemini Response Contract + Secret Scrubber'
id: doc:sdd-specs-repl-sandbox-response-contract-scrubber-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A production `JiraSpecialist` agent (model `gemini-3`) running an autonomous
  loop
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.command_sanitizer
  rel: mentions
- concept: mod:parrot.security.python_sanitizer
  rel: mentions
- concept: mod:parrot.security.redaction
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot_tools.shell_tool
  rel: mentions
- concept: mod:parrot_tools.shell_tool.security
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: REPL Sandbox + Gemini Response Contract + Secret Scrubber

**Feature ID**: FEAT-252
**Date**: 2026-06-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor)

> **Prior exploration**: `sdd/proposals/repl-sandbox-response-contract-scrubber.proposal.md`
> (research-grounded, enrichment mode, all 4 design decisions resolved). Supersedes
> `sdd/proposals/brainstorm-repl-sandbox-response-contract-scrubber.md` (revision 2).
> **Research audit**: `sdd/state/FEAT-252/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

A production `JiraSpecialist` agent (model `gemini-3`) running an autonomous loop
called `python_repl`, evaluated `os.environ.keys()`, and the **`repr` of the
resulting `KeysView` serialized the entire environment *with values***. That string
became the tool result, fed back into the model context, echoed as the final answer,
rendered to Telegram, and logged in cleartext to CloudWatch. Three stacked failures,
each sufficient alone: (1) `python_repl` ran in-process with full `os.environ`;
(2) the Gemini client surfaced raw tool output as the final response; (3) no
deterministic redaction existed at any hop.

A **tactical fix is already committed** on `dev` (`0f76129b1` "security on llm clients
and agents") [F010]. It closes the *known* vector but **diverges from the intended
design on all three workstreams**: it is an AST **denylist** rather than an
allowlist-first gate (WS1) [F002]; redaction is **scattered across ~14 call sites** in
the Gemini client with **no single response chokepoint** and `default_api` hunting
still enabled (WS2) [F003]; and the redactor is a flat-marker standalone module, **not**
a policy-driven scrubber hooked at the single `AbstractTool.execute()` seam, and not
built on the existing `shell_tool` security engine (WS3 + foundation) [F004, F005, F001].

This feature **consolidates the tactical fix into the strategic containment contract**.

### Goals

- **G1 — Foundation.** A single deterministic security engine lives in core
  (`parrot.security`), reused by `shell_tool` and by the two new sanitizers.
- **G2 — WS1.** `python_repl` enforces an **allowlist-first (deny-by-default)** AST
  policy with `general` and `data_analysis` profiles; the `bots/data.py` forbidden-IO
  list is promoted to deterministic categorical denial under every profile.
- **G3 — WS2 (primary containment).** Every Gemini terminal path funnels through one
  deterministic `_resolve_final_response` chokepoint that classifies provenance, never
  ships a verbatim tool-result echo or raw code-exec stdout, gates `default_api`/
  `tool_code` hunting, and returns a **typed "no answer produced"** on empty-after-tools.
- **G4 — WS3.** A policy-driven `OutputScrubber` (reason-tagged, audited, idempotent,
  allowlist-aware) is hooked **once** at `AbstractTool.execute()` (in-bound) and reused
  for channel egress, so every tool inherits redaction.
- **G5 — No regression.** The shipped `0f76129b1` behavior and tests
  (`test_pythonrepl_security.py`, `test_google_client.py`) keep passing; redaction
  coverage is never momentarily lost during the WS2 refactor.

### Non-Goals (explicitly out of scope)

- **Moving secrets out of `os.environ`** — rejected in brainstorm (Q1). Infra uses
  `python-dotenv` + K8S env injection; structural change deferred. *Consequence*: the
  env-access gate (G2) and the in-bound scrubber (G4) are **load-bearing, not redundant**.
- **Subprocess / seccomp isolation of the REPL** — deferred; the `data_analysis` path
  shares in-process namespace state [F008].
- Credential rotation / log purge (operational, already in flight).
- Per-tenant data-plane authorization (`AuthorizingDataSource` track).

---

## 2. Architectural Design

### Overview

Four workstreams over one shared primitive. The **foundation** relocates
`shell_tool`'s compiled, deterministic `CommandSanitizer`/`SecurityPolicy`/
`SecurityLevel`/`ValidationResult` down into core `parrot.security` (dependency
direction is `parrot_tools → core`, so core cannot import upward — the shared code
**must** sit in core, and `parrot_tools` re-imports it) [F001, F009]. On that engine:

- **WS1** adds `PythonExecutionPolicy` + `PythonCodeSanitizer` — an AST **allowlist**
  gate (deny-by-default), replacing the shipped denylist in `PythonREPLTool`. Two
  profiles: `general` (Jira/GitHub agents — tightest) and `data_analysis`
  (pandas/numpy compute on already-materialized DataFrames). The `bots/data.py`
  forbidden-IO prose [F007] becomes categorical denial under both.
- **WS3** evolves `security/redaction.py` [F005] into a policy `OutputScrubber`
  (reason tags `***REDACTED:<reason>***`, audit log of matched key/pattern + tool name
  only, idempotent, allowlist-aware), hooked **once** at the verified single seam
  `AbstractTool.execute()` [F004] and reused at the `bots/base.py` egress hop [F006].
- **WS2** (primary) introduces `_resolve_final_response` in the Gemini client: a single
  deterministic gate all 6 `AIMessageFactory.from_gemini(...)` terminal sites [F003]
  funnel through. It classifies provenance (synthesis vs tool-echo vs code-exec stdout),
  suppresses echoes, scrubs (reusing WS3) last, returns a typed empty on no-answer, and
  gates `default_api`/`tool_code`. A **closed tool manifest** in the system prompt
  removes the motive to hunt non-existent tools.

**Sequencing (dependency-ordered):** Foundation → WS3 (seam + scrubber) → WS2
(reuses scrubber; removes the scattered calls *after* the seam exists, so coverage is
never lost) → WS1 (allowlist gate). This refines the brainstorm's WS3-first ordering to
guarantee G5.

### Component Diagram

```
parrot.security (core)
  ├─ command_sanitizer  ←─ relocated from shell_tool  ─→ re-exported to parrot_tools.shell_tool
  │     SecurityLevel / SecurityPolicy / CommandSanitizer / ValidationResult / CommandVerdict
  ├─ python_sanitizer   (NEW, WS1)
  │     PythonExecutionPolicy / PythonCodeSanitizer ──→ PythonREPLTool._execute()
  └─ redaction → OutputScrubber (WS3, evolved)
        ├─ hooked once at AbstractTool.execute()        (in-bound, emplacement a)
        ├─ reused at bots/base.py egress (TELEGRAM/MS)  (emplacement b)
        └─ reused by GoogleClient._resolve_final_response (WS2)

GoogleClient (WS2)
  ask / ask_stream / resume / invoke ─┐
  _handle_multiturn_function_calls ───┴─→ _resolve_final_response() ─→ AIMessageFactory.from_gemini()
                                              (provenance + echo-suppress + scrub + typed-empty)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_tools.shell_tool.security` | relocate + re-export | primitives move to core; shell_tool imports from core (G1) |
| `PythonREPLTool._execute` (`tools/pythonrepl.py:766`) | wraps | run `PythonCodeSanitizer.validate(code)` before exec; structured refusal on deny |
| `AbstractTool.execute` (`tools/abstract.py:473`) | hooks | scrub `tool_result.result` once before return (G4) |
| `GoogleClient` 6× `from_gemini` (`clients/google/client.py`) | refactor | all terminal text via `_resolve_final_response` (G3) |
| `bots/base.py` `_sanitize_tool_data` / `OutputMode` (`1282`,`1318`) | augments | egress reuses `OutputScrubber` (G4) |
| `bots/data.py` forbidden-IO prose (`296-300`) | promotes | prompt guidance → deterministic denial (G2) |
| `tools/agent.py:_inject_context_to_repl` + `dataset_manager` getter | preserves | in-process REPL state must keep working (Non-Goal: subprocess) |

### Data Models

```python
# parrot/security/python_sanitizer.py  (NEW)
from dataclasses import dataclass, field
from parrot.security.command_sanitizer import SecurityLevel, ValidationResult, CommandVerdict

@dataclass(frozen=True)
class PythonExecutionPolicy:
    level: SecurityLevel = SecurityLevel.RESTRICTIVE
    default_deny: bool = True
    allowed_imports: frozenset = frozenset({"navconfig", "pandas", "numpy", "json",
                                            "math", "datetime", "statistics", "re"})
    allowed_builtins: frozenset = frozenset({"len", "range", "sum", "sorted", "min",
                                             "max", "print", "enumerate", "zip", ...})
    deny_env_access: bool = True          # os.environ, getenv/putenv, dict(os.environ)
    deny_introspection: bool = True       # __class__/__bases__/__subclasses__/globals()/...
    deny_dynamic_exec: bool = True        # eval/exec/compile/__import__(dynamic)
    deny_data_io: bool = True             # the bots/data.py set (Q4)
    isolation: str = "in_process"         # subprocess deferred (Non-Goal)
    max_output_bytes: int = 1_048_576

# profile factories
def general_profile() -> PythonExecutionPolicy: ...
def data_analysis_profile() -> PythonExecutionPolicy: ...   # wider allowlist for pandas/numpy

# parrot/security/redaction.py  (EVOLVE)
@dataclass(frozen=True)
class ScrubPolicy:
    reason_tags: bool = True              # ***REDACTED:<reason>*** vs flat [REDACTED]
    audit_log: bool = True                # record matched key/pattern + tool name ONLY, never value
    allowlist: frozenset = frozenset()    # contexts not to clobber (e.g. ticket body 'token=')
    max_output_bytes: int = 1_048_576
```

### New Public Interfaces

```python
# parrot/security/python_sanitizer.py
class PythonCodeSanitizer:
    """Allowlist-first AST gate. RESTRICTIVE: deny any node/call/import not allowlisted."""
    def __init__(self, policy: PythonExecutionPolicy = ...): ...
    def validate(self, code: str) -> ValidationResult:   # reuse the shell_tool verdict type
        ...

# parrot/security/redaction.py
class OutputScrubber:
    def __init__(self, policy: ScrubPolicy = ...): ...
    def scrub(self, value: Any) -> Any:                  # idempotent; recurse dict/list/tuple/str
        ...
    # backward-compatible module fns redact_text/redact_secrets remain during migration

# parrot/clients/google/client.py
def _resolve_final_response(self, candidate_text: str, all_tool_calls: list,
                            code_exec_output: list | None) -> str:
    """Single source of truth for 'what is a final response': provenance + echo-suppress
       + typed-empty + scrub (last). Every terminal path funnels through here."""
```

---

## 3. Module Breakdown

### Module 1: Relocate shared security engine to core  *(G1 — foundation)*
- **Path**: `parrot/security/command_sanitizer.py` (new) + re-export shim in
  `parrot_tools/shell_tool/security.py`
- **Responsibility**: Move `SecurityLevel`, `CommandVerdict`, `ValidationResult`,
  `CommandRule`, `SecurityPolicy`, `CommandSanitizer` into core; `shell_tool` imports
  them from core (no behavior change). Code duplication acceptable if a clean extraction
  is awkward (brainstorm-allowed) — but relocation is the chosen approach (U4).
- **Depends on**: nothing (must land first).

### Module 2: `OutputScrubber` + single-seam hook  *(G4 — WS3)*
- **Path**: `parrot/security/redaction.py` (evolve) + hook in `parrot/tools/abstract.py`
  + egress reuse in `parrot/bots/base.py`
- **Responsibility**: Policy-driven scrubber (reason tags, audit, idempotent,
  allowlist-aware) built on Module 1's primitives; hooked once at `AbstractTool.execute()`
  before `return tool_result`; reused at the TELEGRAM/MSTEAMS egress. Keep
  `redact_text`/`redact_secrets` working during migration.
- **Depends on**: Module 1.

### Module 3: `_resolve_final_response` chokepoint  *(G3 — WS2, primary)*
- **Path**: `parrot/clients/google/client.py`
- **Responsibility**: Introduce the chokepoint; route all 6 `from_gemini` terminals
  through it; **remove the ~14 scattered `redact_*` calls** (now covered by the
  chokepoint + Module 2 seam); provenance classify (synthesis/tool-echo/code-exec);
  suppress echoes; typed "no answer produced" on empty-after-tools; gate
  `default_api`/`tool_code`; add the **closed tool manifest** to the system prompt.
- **Depends on**: Module 2 (must exist before scattered calls are removed — G5).

### Module 4: `PythonCodeSanitizer` allowlist gate  *(G2 — WS1)*
- **Path**: `parrot/security/python_sanitizer.py` (new) + wire into
  `parrot/tools/pythonrepl.py`; promote `parrot/bots/data.py` forbidden-IO list
- **Responsibility**: Allowlist-first AST gate with `general`/`data_analysis` profiles;
  replace/augment the shipped `_check_ast_security` denylist; categorical denials
  (env/introspection/dynamic-exec/data-IO) enforced under every profile; structured
  refusal (no exec, no echo of offending code) on deny.
- **Depends on**: Module 1.

### Module 5: Non-regression + new tests  *(G5)*
- **Path**: `packages/ai-parrot/tests/` (extend `test_pythonrepl_security.py`,
  `test_google_client.py`; add scrubber + sanitizer + chokepoint tests)
- **Responsibility**: Lock the incident scenario + the four contracts; assert no
  redaction-coverage gap across the WS2 refactor.
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_command_sanitizer_relocated_import` | M1 | `parrot.security.command_sanitizer` exports + `shell_tool` re-export both resolve |
| `test_shell_tool_behavior_unchanged` | M1 | RESTRICTIVE/MODERATE/PERMISSIVE verdicts identical pre/post relocation |
| `test_scrubber_env_dump_redacted` | M2 | `KeysView(environ(...))` value-dump → reason-tagged redaction |
| `test_scrubber_idempotent` | M2 | `scrub(scrub(x)) == scrub(x)` |
| `test_scrubber_audit_no_value` | M2 | audit log records key/tag + tool name, never the secret value |
| `test_abstracttool_execute_scrubs_once` | M2 | every `execute()` return path scrubbed; non-tool callers unaffected |
| `test_resolve_final_response_suppresses_echo` | M3 | verbatim tool-result echo not shipped as answer |
| `test_resolve_final_response_typed_empty` | M3 | empty-after-tools → typed "no answer produced", not raw stdout |
| `test_default_api_gated` | M3 | `default_api`/non-existent-tool `tool_code` → typed "tool not available" |
| `test_all_terminals_funnel` | M3 | all 6 `from_gemini` sites route through `_resolve_final_response` |
| `test_python_sanitizer_denies_env` | M4 | `os.environ`, `os.getenv`, `dict(os.environ)` denied under both profiles |
| `test_python_sanitizer_denies_introspection_and_io` | M4 | `__subclasses__`, `globals()`, `open`, `pd.read_csv`, `eval` denied |
| `test_python_sanitizer_allows_compute` | M4 | pandas/numpy compute on materialized data allowed (calibration fixture) |

### Integration Tests
| Test | Description |
|---|---|
| `test_incident_scenario_contained` | End-to-end: REPL `os.environ.keys()` → denied by gate AND scrubbed if surfaced AND not echoed by `_resolve_final_response` |
| `test_data_analysis_repl_state_preserved` | `_inject_context_to_repl` + DataFrame getter still work under the gate (no subprocess regression) |
| `test_no_redaction_gap_during_refactor` | Secrets never leak through any Gemini terminal after scattered calls are removed |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_environ():
    return {"REDIS_DB": "1", "ODOO_EPSON_PRODUCTION_PASSWORD": "s3cr3t"}

@pytest.fixture
def general_policy():  # parrot.security.python_sanitizer.general_profile()
    ...
```

---

## 5. Acceptance Criteria

> Complete when ALL are true:

- [ ] **G1** `parrot/security/command_sanitizer.py` exists with
      `SecurityLevel/SecurityPolicy/CommandSanitizer/ValidationResult/CommandVerdict`;
      `parrot_tools.shell_tool.security` re-exports them; shell_tool tests unchanged.
- [ ] **G2** `PythonCodeSanitizer` denies env-access, introspection-to-escape,
      dynamic-exec, and the `bots/data.py` data-IO set under **both** profiles by
      default (allowlist-first); `general` is tighter than `data_analysis`.
- [ ] **G2** A denied REPL submission returns a **structured refusal** — no execution,
      no echo of the offending code.
- [ ] **G3** All 6 `AIMessageFactory.from_gemini(...)` terminal sites funnel through
      `_resolve_final_response`; a grep finds **zero** scattered `redact_*` calls left
      in `google/client.py`.
- [ ] **G3** A verbatim/near-verbatim tool-result echo is never shipped as the answer;
      empty-after-tools returns a **typed "no answer produced"** (no raw stdout fallback).
- [ ] **G3** `default_api` import attempts / non-existent-tool `tool_code` produce a
      typed "tool not available"; the system prompt states the **closed tool manifest**.
- [ ] **G4** `OutputScrubber` is invoked exactly once at `AbstractTool.execute()` for
      every tool result; reason-tagged (`***REDACTED:<reason>***`); audit log records
      key/tag + tool name only, **never the value**; `scrub` is idempotent.
- [ ] **G4** Egress (`OutputMode.TELEGRAM`/`MSTEAMS`) reuses the scrubber.
- [ ] **G5** `test_pythonrepl_security.py` and `test_google_client.py` from `0f76129b1`
      still pass; `test_no_redaction_gap_during_refactor` passes.
- [ ] All unit + integration tests pass (`pytest packages/ai-parrot/tests -v`).
- [ ] No breaking change to `PythonREPLTool`/`AbstractTool`/`GoogleClient` public APIs.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All entries verified by `read` on
> 2026-06-23 at the current `dev` HEAD (post `0f76129b1`).

### Verified Imports
```python
# verified — tools/abstract.py
from parrot.tools.abstract import AbstractTool, ToolResult          # ToolResult @ abstract.py:46
# verified — committed scrubber (NOTE: imported directly, NOT yet in security/__init__.__all__)
from parrot.security.redaction import redact_text, redact_secrets, looks_sensitive_key  # redaction.py:38-54
# verified — shell_tool engine (current home, to be relocated in M1)
from parrot_tools.shell_tool.security import (
    SecurityLevel, CommandVerdict, ValidationResult, SecurityPolicy, CommandSanitizer,
)  # security.py:36,44,58,321,564
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
def sanitize_input(query: str) -> str:                                   # line 43 (fence-strip only)
class PythonREPLArgs(BaseModel):                                          # line 79
    code: str; debug: bool = False
class PythonREPLTool(AbstractTool):                                       # line 86
    name = "python_repl"; args_schema = PythonREPLArgs
    BLOCKED_IMPORTS: set = {...}                                          # line 106 (denylist — to replace)
    BLOCKED_NAMES: set = {...}                                            # line 126
    def _check_ast_security(self, tree: ast.AST) -> Optional[str]:        # line 504 (denylist walk)
    def _redact_execution_output(self, output: str) -> str:              # line 523 -> redact_text
    def _execute_code(self, query, debug=False, ...)                     # line 622
    async def _execute(self, code: str, debug: bool = False, **kwargs) -> Dict[str, Any]:  # line 766

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                             # line 46
    success: bool = True; status: str = "success"; result: Any
    error: Optional[str] = None; metadata: Dict[str, Any] = {}          # + files/images/voice_text
class AbstractTool(...):
    async def execute(self, *args, **kwargs) -> ToolResult:              # line 473; normalizes raw_result
                                                                         #   -> tool_result @ 577-603; return @ 616

# packages/ai-parrot/src/parrot/clients/google/client.py
async def _handle_multiturn_function_calls(...)                          # line 1580
def _get_function_calls_from_response(self, response) -> List            # line 2066
def _safe_extract_text(self, response) -> str                           # line 2107
def _parse_tool_code_blocks(self, text: str) -> List                    # line 1958 (default_api regex @ 1966)
async def ask(...)                                                       # line 2391
async def ask_stream(...)                                                # line 3294
async def resume(self, session_id, user_input, state) -> AIMessage       # line 4816
async def invoke(...)                                                    # line 4929
# AIMessageFactory.from_gemini(...) terminal sites: 3146, 3796, 4323, 4505, 4802, 4917

# packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py
class SecurityLevel(str, Enum): RESTRICTIVE/MODERATE/PERMISSIVE          # line 36
@dataclass(frozen=True)
class ValidationResult:                                                  # line 58
    verdict: CommandVerdict; command: str; reasons: Tuple[str,...] = ()
    sanitized_command: Optional[str] = None; risk_score: float = 0.0
    @property def is_allowed / is_denied
@dataclass
class SecurityPolicy:                                                    # line 321
    level: SecurityLevel = SecurityLevel.MODERATE
    @classmethod def restrictive(cls, allowed_commands=None, sandbox_dir=None,
                                 command_rules=None) -> SecurityPolicy   # line 391
class CommandSanitizer:                                                  # line 564
    def validate(self, command: str) -> ValidationResult                # line 618

# scatter to remove in M3 (redact_text/redact_secrets call sites in google/client.py):
#   1301, 1335, 1354, 1397, 1754, 1775, 3206, 3208, 3221, 3223, 3618, 4790
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PythonCodeSanitizer.validate` | `PythonREPLTool._execute` | call before exec | `pythonrepl.py:766` |
| `OutputScrubber.scrub` | `AbstractTool.execute` | call before `return tool_result` | `abstract.py:616` |
| `OutputScrubber.scrub` | `bots/base.py` egress | TELEGRAM/MSTEAMS formatting | `bots/base.py:1318` |
| `_resolve_final_response` | 6× `from_gemini` | single chokepoint | `google/client.py:3146..4917` |
| `command_sanitizer` (core) | `shell_tool.security` | re-export shim | `shell_tool/security.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.security.python_sanitizer`~~ — **new in M4** (no `PythonCodeSanitizer`/`PythonExecutionPolicy` anywhere yet).
- ~~`parrot.security.redaction.OutputScrubber`~~ — **new in M2**; today only module-level `redact_text`/`redact_secrets`/`looks_sensitive_key` exist (`redaction.py:38-70`).
- ~~`parrot.security.command_sanitizer`~~ — **new in M1**; the engine lives only in `parrot_tools.shell_tool.security` today.
- ~~`GoogleClient._resolve_final_response`~~ / `_synthesize_or_safe_fallback` / `classify_provenance` — **new in M3** (grep: absent).
- ~~`from parrot.security import redact_text`~~ — NOT exported in `security/__init__.__all__`; must import from `parrot.security.redaction`.
- ~~forced-synthesis block in the Gemini loop~~ — commented out / skipped today (`client.py:1652`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Reuse `shell_tool` `SecurityPolicy.restrictive()` + `SecurityLevel` + the
  `ValidationResult`/`CommandVerdict` verdict shape for the Python gate [F001].
- **Single-seam interception** at `AbstractTool.execute()` — never per-call-site [F004].
- Async-first; `self.logger` for audit; Pydantic/dataclass for all policies.
- `OutputScrubber` runs **last** in `_resolve_final_response`, after provenance/echo logic.

### Known Risks / Gotchas
- **R1 — Redaction-coverage gap.** M3 removes ~14 scattered `redact_*` calls; the
  Module-2 seam **must** be live first. Enforced by ordering (M2 → M3) + G5 test.
- **R2 — Allowlist over-tightening.** A too-narrow allowlist rejects genuine
  pandas/numpy analysis → needs calibration over real `python_repl` usage (Open Q O1).
- **R3 — Streaming drift.** Funneling 6 exits (incl. `ask_stream`) through one
  chokepoint risks latency/behavior drift; the typed-empty decision avoids the
  forced-synthesis latency the LiveAvatar track is sensitive to.

…(truncated)…
