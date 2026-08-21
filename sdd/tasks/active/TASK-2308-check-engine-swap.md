# TASK-2308: Swap check() onto the resolved engine + empty-input short-circuit

**Feature**: FEAT-439 — ONNX Backend for the Prompt-Injection Guardrail
**Spec**: `sdd/specs/onnx-injection-guardrail-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2307
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. TASK-2307 built the engine layer; this task makes
`PromptInjectionGuardrail.check()` consume it. The contract is
byte-for-byte behaviour preservation: only the "produce a probability"
step changes. This is what makes the feature a backend swap rather than
a redesign — every bypass, log, wrap, and quirk stays identical.

## Scope

In `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py`:

- Wire `__init__` to `_resolve_injection_engine()` (from TASK-2307),
  replacing the direct `_get_shared_injection_detector()` call while
  keeping `self._pytector_available` semantics coherent for the regex
  branch decision.
- In `check()`: replace the hardcoded
  `self._pytector_detector.detect_injection(scan_text)` call (line 180)
  with `engine.score(scan_text)` when an ML engine resolved; keep the
  identical threshold comparison (`probability > self.injection_probability_threshold`),
  identical threat-dict shape (`type`, `level: ThreatLevel.CRITICAL`,
  `description`, `probability`, `pattern`, `matched_text` preview of
  120 chars) — with `pattern` reflecting the engine
  (`"pytector-model"` stays for pytector; use `"onnx-model"` for ONNX so
  security events name the engine that flagged).
- Preserve the regex branch verbatim: when no ML engine resolved,
  `sanitized, threats = self._injection_detector.sanitize(content, strict=True)`
  (line 192) exactly as today.
- Add the empty-input short-circuit: empty or whitespace-only `content`
  returns PASS **before** framework stripping or any engine call
  (spec §2 edge case).
- Everything else in `check()` is untouched: trusted-source bypass,
  `strict_mode` bypass, `strip_framework_patterns`, security-event
  logging call and payload, the intentionally-preserved `max()` severity
  quirk (lines 210-215 and its comment), BLOCK report shape,
  `_wrap_flagged_input`.
- Unit tests proving flow preservation with a mocked engine.

**NOT in scope**: engine construction/resolution (TASK-2307); warm-up
(TASK-2309); executor offloading (follow-up feature — `score()` is still
called synchronously on the loop, as today); changing thresholds,
priority, stages, name, or `on_error`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | `__init__` engine wiring; `check()` probability step; empty-input short-circuit |
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` | MODIFY | Flow-preservation tests with mocked engine |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verify each anchor with `read`/`grep` before coding —
> TASK-2307 will have moved lines in this file; re-anchor first.

### Verified Imports (already in the module)

```python
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel,
)                                    # verified: security/__init__.py:8-13
from ..base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)                                    # verified: module lines 33-39
```

### Existing Signatures to Use (pre-TASK-2307 line numbers)

```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:  # line 149
    # line 164: trusted_source bypass → PASS
    # line 166: strict_mode bypass → PASS
    # line 171: sanitized = content; threats = []
    # line 177: scan_text = self._framework_sanitizer.strip_framework_patterns(content)
    # line 180: is_injection, probability = self._pytector_detector.detect_injection(scan_text)
    # line 181: if is_injection and probability > self.injection_probability_threshold:
    # lines 183-190: threat dict — {"type": "prompt_injection",
    #   "level": ThreatLevel.CRITICAL, "description": ..., "probability": ...,
    #   "pattern": "pytector-model", "matched_text": (scan_text or "")[:120]}
    # line 192: sanitized, threats = self._injection_detector.sanitize(content, strict=True)  # regex branch
    # lines 197-208: await self._security_logger.log_injection_attempt(...)  — payload unchanged
    # line 215: max_severity = max((t["level"] for t in threats), default=ThreatLevel.LOW)
    #   ^ NO key= — intentional legacy quirk, preserved (see comment lines 210-214)
    # lines 217-226: BLOCK branch — reason="prompt_injection_detected",
    #   report={"threats_detected": len(threats)}
    # lines 228-229: TRANSFORM branch — _wrap_flagged_input(sanitized, threats)

@staticmethod
def _wrap_flagged_input(text, threats) -> str:         # line 232 — DO NOT MODIFY

# security/prompt_injection.py
class SecurityEventLogger:                             # line 222
    async def log_injection_attempt(self, user_id, session_id, chatbot_id,
                                    threats, original_input, sanitized_input,
                                    metadata) -> ...   # line 231
class PromptInjectionDetector:
    def strip_framework_patterns(self, text: str) -> str:   # line 123
    def sanitize(...)                                        # line 191
```

### Engine interface (delivered by TASK-2307 — verify its final shape)

```python
class _InjectionScoringEngine(Protocol):
    engine_name: str      # "onnx" | "pytector"
    model_id: str
    def score(self, text: str) -> float: ...
_resolve_injection_engine()  # → engine | None (None ⇒ regex branch)
```

### Does NOT Exist

- ~~`GuardrailResult.metadata`~~ — check the real `GuardrailResult`
  fields in `bots/guardrails/base.py` before adding anything; BLOCK uses
  `reason` + `report`, TRANSFORM uses `content`. Do not invent fields.
- ~~An async `engine.score()`~~ — `score()` is sync by design in this
  feature; do not add executor plumbing (follow-up feature).
- ~~A `pattern="deberta-v2"` value~~ — engine-naming values are
  `"pytector-model"` (existing) and `"onnx-model"` (this task); nothing else.

---

## Implementation Notes

### Key Constraints
- Behaviour-parity is the acceptance bar: with the engine mocked to
  return the same probability pytector would, every existing test in
  `test_guardrails_prompt_injection.py` must pass without modifying
  their assertions (fixture wiring may need to target the new
  resolution function — keep the shim so `_get_shared_injection_detector`
  patching in old tests still works, or update fixtures minimally and
  keep assertions untouched).
- Empty-input check: `if not content or not content.strip(): PASS` —
  before stripping, before any engine.
- The security-event payload shape is consumed downstream; do not
  rename keys.

### References in Codebase
- `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` —
  existing fixture patches `_get_shared_injection_detector` at module
  scope (file docstring explains the MagicMock unpacking gotcha).

---

## Acceptance Criteria

- [ ] `check()` uses the resolved engine for the probability step; regex
      branch preserved verbatim when no engine resolved.
- [ ] Empty/whitespace input → PASS with no engine call (test proves the
      engine mock is never invoked).
- [ ] All pre-existing tests in
      `test_guardrails_prompt_injection.py` pass with assertions
      unmodified.
- [ ] Threat dict / security-event payload / BLOCK report / TRANSFORM
      wrap byte-identical shapes; `pattern` names the engine.
- [ ] `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -v` green.
- [ ] No change to `name`, `stages`, `priority`, `on_error`, `check()`
      signature, or the registered guardrail name.

---

## Test Specification

```python
class TestCheckFlowPreservation:
    async def test_empty_input_short_circuits_no_engine_call(self, ctx): ...
    async def test_whitespace_input_short_circuits(self, ctx): ...
    async def test_onnx_engine_probability_over_threshold_transforms(self, ctx): ...
    async def test_onnx_engine_below_threshold_passes(self, ctx): ...
    async def test_block_on_threat_with_onnx_engine(self, ctx): ...
    async def test_pattern_field_names_engine(self, ctx): ...
    async def test_regex_branch_when_no_engine(self, ctx): ...
    async def test_security_event_payload_shape_unchanged(self, ctx): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2307 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line numbers WILL have shifted
   after TASK-2307; re-anchor every reference first
4. **Update status** in `sdd/tasks/index/onnx-injection-guardrail-backend.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
