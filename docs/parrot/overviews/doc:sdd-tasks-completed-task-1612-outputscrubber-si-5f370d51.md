---
type: Wiki Overview
title: 'TASK-1612: `OutputScrubber` policy + single-seam hook at `AbstractTool.execute()`'
id: doc:sdd-tasks-completed-task-1612-outputscrubber-single-seam-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: WS3 (spec §3 Module 2, G4). Today `security/redaction.py` is a flat-marker
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.command_sanitizer
  rel: mentions
- concept: mod:parrot.security.redaction
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1612: `OutputScrubber` policy + single-seam hook at `AbstractTool.execute()`

**Feature**: FEAT-252 — REPL Sandbox + Gemini Response Contract + Secret Scrubber
**Spec**: `sdd/specs/repl-sandbox-response-contract-scrubber.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1611
**Assigned-to**: unassigned

---

## Context

WS3 (spec §3 Module 2, G4). Today `security/redaction.py` is a flat-marker
standalone module (`redact_text`/`redact_secrets`), and redaction is **not** hooked
at the single tool seam — it's scattered in the Gemini client. This task evolves it
into a policy-driven `OutputScrubber` (reason tags, audit log, idempotent,
allowlist-aware) and hooks it **once** at the verified single seam
`AbstractTool.execute()` so every tool inherits redaction, plus reuses it at the
channel egress in `bots/base.py`.

**Ordering matters (Risk R1):** this task MUST land before TASK-1613 removes the
~14 scattered `redact_*` calls from the Gemini client, so redaction coverage is
never momentarily lost.

---

## Scope

- Add `ScrubPolicy` dataclass + `OutputScrubber` class to
  `parrot/security/redaction.py`:
  - reason-tagged markers `***REDACTED:<reason>***` (env_dump / secret_kv / dsn /
    jwt / cloud_key / net_topology), configurable; default conservative.
  - **idempotent** `scrub(value)` — recurse dict/list/tuple/str; `scrub(scrub(x)) == scrub(x)`.
  - **audit log** via `self.logger`: record matched key/pattern tag + tool name **only**,
    never the secret value.
  - **allowlist-aware**: a configurable context allowlist so legitimate payloads
    (e.g. a ticket body containing `token=`) aren't clobbered.
  - reuse the relocated engine's compiled-pattern / policy posture (TASK-1611) where
    it fits; keep `redact_text`/`redact_secrets` working for backward compat during migration.
- Hook the scrubber **once** in `AbstractTool.execute()` — scrub `tool_result.result`
  (and error/metadata as appropriate) immediately before `return tool_result` (line 616).
- Reuse `OutputScrubber` at the `bots/base.py` egress (TELEGRAM/MSTEAMS) hop.

**NOT in scope**: removing the Gemini-client scatter (TASK-1613), the Python AST gate
(TASK-1614), the REPL's own `_redact_execution_output` (leave it — defense in depth).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/redaction.py` | MODIFY | Add `ScrubPolicy` + `OutputScrubber`; keep module fns |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | Export `OutputScrubber`, `ScrubPolicy` |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Hook scrubber once before `return tool_result` |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Reuse scrubber at egress formatting |
| `packages/ai-parrot/tests/test_output_scrubber.py` | CREATE | Scrubber unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# verified — packages/ai-parrot/src/parrot/security/redaction.py
from parrot.security.redaction import redact_text, redact_secrets, looks_sensitive_key
# verified — tools/abstract.py
from parrot.tools.abstract import AbstractTool, ToolResult
# available after TASK-1611
from parrot.security.command_sanitizer import SecurityPolicy, SecurityLevel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/redaction.py  (current — to evolve)
REDACTION_MARKER = "[REDACTED]"                                  # line 8
def looks_sensitive_key(key: Any) -> bool                        # line 38
def redact_text(text: str) -> str                               # line 43  (DICT_ITEM, ASSIGNMENT,
                                                                #            BEARER, JWT, AKIA, LONG_HEX)
def redact_secrets(value: Any) -> Any                           # line 54  (recurse dict/list/tuple)

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                    # line 46
    success: bool = True; status: str = "success"; result: Any  # lines 48-50
    error: Optional[str] = None; metadata: Dict[str, Any] = {}  # lines 51-52
class AbstractTool(...):
    async def execute(self, *args, **kwargs) -> ToolResult:     # line 473
        # raw_result -> tool_result normalized at lines 577-603
        # return tool_result                                    # line 616  <-- SCRUB HERE (once)

# packages/ai-parrot/src/parrot/bots/base.py
#   _sanitize_tool_data(tool_call.result)  -> JSON-safety only  # line 1282
#   OutputMode.TELEGRAM / OutputMode.MSTEAMS egress branch      # lines 1318-1319
```

### Does NOT Exist
- ~~`parrot.security.redaction.OutputScrubber`~~ / ~~`ScrubPolicy`~~ — this task CREATES them.
- ~~`from parrot.security import redact_text`~~ — NOT in `__init__.__all__`; import from `parrot.security.redaction`.
- ~~`AbstractTool.scrub_result()`~~ / any existing scrub hook in `execute()` — none today.
- `_sanitize_tool_data` is **NOT** secret redaction — do not assume it redacts.

---

## Implementation Notes

### Pattern to Follow
```python
@dataclass(frozen=True)
class ScrubPolicy:
    reason_tags: bool = True
    audit_log: bool = True
    allowlist: frozenset = frozenset()
    max_output_bytes: int = 1_048_576

class OutputScrubber:
    def __init__(self, policy: ScrubPolicy = ScrubPolicy()):
        self.policy = policy
        self.logger = logging.getLogger(__name__)
    def scrub(self, value: Any) -> Any:
        # idempotent; skip if already-marked; recurse; audit tag+tool only
        ...
```
- In `execute()`, scrub at exactly one place (before the single `return tool_result`),
  so every normalization branch is covered.

### Key Constraints
- **Idempotent** — re-scrubbing a scrubbed string is a no-op (guard on the marker).
- **Never log secret values** — audit records tag + tool name only.
- Keep `redact_text`/`redact_secrets` exported and working (TASK-1613 still calls them
  until it's refactored — though after this task they may delegate to `OutputScrubber`).
- Async-safe: `execute()` is async; `scrub` is sync/pure — fine to call inline.

### References in Codebase
- `packages/ai-parrot/src/parrot/security/redaction.py` — the module to evolve.
- `packages/ai-parrot/src/parrot/tools/abstract.py:473-616` — the seam.
- Reason-tag taxonomy: spec §5.2 / proposal §5.2 table (env_dump, secret_kv, dsn, jwt, cloud_key, net_topology).

---

## Acceptance Criteria

- [ ] `from parrot.security.redaction import OutputScrubber, ScrubPolicy` resolves; also exported via `parrot.security.__init__`.
- [ ] `KeysView(environ({...}))` value-dump → reason-tagged redaction (`***REDACTED:env_dump***` or per-kv tag).
- [ ] `scrub(scrub(x)) == scrub(x)` for representative secrets (idempotent).
- [ ] Audit log records matched tag + tool name, and **never** the secret value (assert via caplog).
- [ ] `AbstractTool.execute()` scrubs every result exactly once before return (covered for all tools incl. `python_repl`).
- [ ] Egress (`OutputMode.TELEGRAM`/`MSTEAMS`) reuses the scrubber.
- [ ] `pytest packages/ai-parrot/tests/test_output_scrubber.py -v` passes; existing `test_pythonrepl_security.py` still passes.
- [ ] `ruff check` clean on changed files.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_output_scrubber.py
import pytest
from parrot.security.redaction import OutputScrubber, ScrubPolicy

@pytest.fixture
def scrubber():
    return OutputScrubber(ScrubPolicy())

class TestOutputScrubber:
    def test_env_dump_redacted(self, scrubber):
        s = "KeysView(environ({'ODOO_EPSON_PRODUCTION_PASSWORD': 's3cr3t'}))"
        out = scrubber.scrub(s)
        assert "s3cr3t" not in out and "REDACTED" in out

    def test_idempotent(self, scrubber):
        s = "PASSWORD=hunter2"
        assert scrubber.scrub(scrubber.scrub(s)) == scrubber.scrub(s)

    def test_audit_never_logs_value(self, scrubber, caplog):
        scrubber.scrub("API_KEY=AKIAABCDEFGHIJKLMNOP")
        assert "AKIAABCDEFGHIJKLMNOP" not in caplog.text

    def test_recurses_structures(self, scrubber):
        out = scrubber.scrub({"token": "abc123", "ok": [{"secret": "xyz"}]})
        assert out["token"] != "abc123" and out["ok"][0]["secret"] != "xyz"
```

---

## Agent Instructions
(standard — verify contract first; this MUST land before TASK-1613.)

## Completion Note

Implemented by sdd-worker (FEAT-252). `ScrubPolicy` (frozen dataclass) and
`OutputScrubber` added to `parrot/security/redaction.py`. Both exported from
`parrot.security.__init__`. Single-seam hook added in `AbstractTool.execute()`
just before `return tool_result` (scrubs `result` and `error`). Egress scrub
added in `bots/base.py` for TELEGRAM/MSTEAMS output modes. 22 unit tests pass;
existing pythonrepl_security 7 tests still pass; ruff clean on changed files.
