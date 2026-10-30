# TASK-4829: Content-free security events — `SecurityEventLogger.log_security_category_event`

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 item 8 + §3 Module 6 (design-research S2, verified). The existing
`SecurityEventLogger.log_injection_attempt` logs `threat['matched_text']` to the
application log (`security/prompt_injection.py:333`) and persists `original_input` /
`sanitized_input` (`:343-344`, `:386-387`). For prompt-leakage events that would write
the **system prompt itself** to logs and the DB. The new categories (jailbreak,
prompt_leakage) MUST use a sibling method whose signature cannot carry content.
The existing method stays untouched (injection behavior unchanged).

---

## Scope

- Add `async def log_security_category_event(...)` (keyword-only) to `SecurityEventLogger`.
- Application log line: category, severity, score, user/session/bot, counts — no text.
- DB row (when `db_pool`): same `navigator.security_events` table, `event_type=category`,
  `threat_details` = `{"score": ..., "counts": {...}}`, `original_input`/`sanitized_input` = `None`
  (both columns are nullable — `security/security_events.sql:10-11`).
- Tests asserting no content reaches logger or DB args.

**NOT in scope**: changing `log_injection_attempt`; any guardrail.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/prompt_injection.py` | MODIFY | new content-free method |
| `packages/ai-parrot/tests/unit/test_security_category_events.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.prompt_injection import SecurityEventLogger, ThreatLevel  # :297, :14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/prompt_injection.py
from datetime import datetime, timezone          # :7
class ThreatLevel(Enum): LOW/MEDIUM/HIGH/CRITICAL  # :14-19 (values lower-case strings)
class SecurityEventLogger:                       # :297
    def __init__(self, db_pool=None, logger=None)  # :302
    async def log_injection_attempt(...)         # :306 — UNCHANGED
    async def _log_to_database(...)              # :349 — INSERT INTO navigator.security_events (... 10 cols) :362-375;
                                                 #   `async with await self.db_pool.acquire() as conn:` :377
# DDL: security/security_events.sql — user_id/session_id NOT NULL; original_input/sanitized_input nullable
```

### Does NOT Exist
- ~~`log_security_category_event`~~ — created here.
- ~~a `content`/`text`/`matched_text` parameter on the new method~~ — must never exist (that is the point).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/security/prompt_injection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_security_category_events.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/prompt_injection.py#SecurityEventLogger",
    "sym:packages/ai-parrot/src/parrot/security/prompt_injection.py#SecurityEventLogger._log_to_database"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the method between `log_injection_attempt` and `_log_to_database` — *why*: sibling, existing paths untouched.
2. Tests: caplog + fake db_pool capture.

### `packages/ai-parrot/src/parrot/security/prompt_injection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _log_to_database(' prompt_injection.py)
# BEFORE — insert above `    async def _log_to_database(` (verified: security/prompt_injection.py:349)
    async def log_security_category_event(
        self,
        *,
        category: str,
        severity: ThreatLevel,
        score: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        chatbot_id: Optional[str] = None,
        counts: Optional[Dict[str, int]] = None,
    ) -> None:
        """Log a security detection WITHOUT any input/output/prompt text (FEAT-761).

        Used by the jailbreak and prompt-leakage guardrails, whose offending
        content may be the system prompt itself. The signature deliberately
        has no content parameter. Never raises (DB failures are logged).

        Args:
            category: Detection category (``"jailbreak"``, ``"prompt_leakage"``).
            severity: Highest severity of the detection.
            score: Optional model/matcher score in ``[0, 1]``.
            user_id: Requesting user, ``"anonymous"`` when unknown.
            session_id: Session, ``"unknown"`` when unknown.
            chatbot_id: Bot identifier.
            counts: Non-content counters (e.g. ``{"matched_segments": 2}``).
        """
        # FILL IN: one self.logger.warning line (category/severity/score/user/session/bot/counts);
        # if self.db_pool: INSERT into navigator.security_events with event_type=category,
        # severity.value, threat_details={"score": score, "counts": counts or {}}, original_input=None,
        # sanitized_input=None, metadata={}, datetime.now(timezone.utc); wrap in try/except -> logger.error
        # (no exception text that could echo content — log type(e).__name__) — bounded by "no content anywhere"
```

### `packages/ai-parrot/tests/unit/test_security_category_events.py` (CREATE)
```python
"""FEAT-761 TASK-4829 — content-free security events."""
import inspect

import pytest

from parrot.security.prompt_injection import SecurityEventLogger, ThreatLevel

# FILL IN: tests — signature has no content-like parameter (inspect.signature names);
# caplog line contains category/severity, not a sentinel string passed nowhere;
# fake db_pool (async acquire -> async ctx manager -> conn.execute capture) gets None for both input cols
# and event_type == category; DB failure is logged, not raised; defaults anonymous/unknown for NOT NULL cols
```

### FILL IN checklist
- [ ] method body (log + DB)
- [ ] tests

---

## Acceptance Criteria

- [ ] New method has no parameter able to carry content.
- [ ] DB row writes `NULL` for `original_input`/`sanitized_input`; `user_id`/`session_id` never `NULL`.
- [ ] `log_injection_attempt` unchanged (existing tests green).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_security_category_events.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Re-verify anchors; mark `in-progress`; implement; complete `# FILL IN:`.
3. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only listed files; `scripts/sdd/close_task.sh TASK-4829 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: sonnet · Backend: native · Attempts: 1 · Tokens: ~73k)
**Date**: 2026-10-27
**Notes**: SecurityEventLogger.log_security_category_event added (content-free); 4 new tests; merge-tier validation green. A hook-written sdd/ledger/events.jsonl was swept into the coder commit and stripped before merge (not a coder defect). Closed via close_task.sh (no durable review-evidence artifact writable).

**Deviations from spec**: none
