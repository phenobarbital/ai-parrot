# TASK-4833: `PromptInjectionGuardrail(scan_tool_output=True)` — TOOL_OUTPUT stage, TRANSFORM-only

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4825, TASK-4828
**Assigned-to**: unassigned

---

## Context

Spec §2 item 4 + §3 Module 5 (first half). Resolved decisions: `scan_tool_output`
**off by default, global** (no per-tool opt-out in v1). At TOOL_OUTPUT the verdict
space is capped at TRANSFORM (wrap with the existing untrusted-content markers) + a
non-content report — **never BLOCK** for tool content, regardless of
`block_on_threat` (one poisoned RAG document must not kill the turn).

How stages are wired (verified): `build_pipelines_from_config` adds each guardrail to
the pipeline of every stage in `guardrail.stages` (`config.py:103-105`), reading the
**instance** attribute. `PromptInjectionGuardrail.stages` is a ClassVar
`{INPUT}` (`prompt_injection.py:683`), so `scan_tool_output=True` must set an instance
`self.stages = {INPUT, TOOL_OUTPUT}`.

Depends on TASK-4825 (TRANSFORM reports surface in `flag_reports`, and per-stage
priority so injection runs after `SecretsGuardrail` at TOOL_OUTPUT — both are priority
10 today) and TASK-4828 (same file, `score_async` already in `check()`).

---

## Scope

- Add `scan_tool_output: bool = False` to `PromptInjectionGuardrail.__init__`.
- When True: `self.stages = {INPUT, TOOL_OUTPUT}` and
  `self.priority = {INPUT: 10, TOOL_OUTPUT: 20}` (after secrets' 10 at TOOL_OUTPUT —
  secrets must scrub first, FEAT-396 ordering invariant).
- In `check()`: at `ctx.stage == TOOL_OUTPUT`, never BLOCK — return
  `TRANSFORM(content=wrapped, report={...})`; idempotent — content already wrapped
  (starts with `<potentially_unsafe_input`) → PASS. The existing `trusted_source`
  bypass is left as-is (the tool seam passes no extras, so it never triggers there).
- Report (non-content): `{"threats_detected": n, "max_severity": "...", "stage": "tool_output", "tool_name": ctx.tool_name}`.
- Tests.

**NOT in scope**: retrieval (vector-context) scanning (TASK-4834); changing INPUT behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | policy flag + stage branch |
| `packages/ai-parrot/tests/unit/test_guardrails_scan_tool_output.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail  # :648
from parrot.bots.guardrails.base import GuardrailAction, GuardrailContext, GuardrailStage
from parrot.bots.guardrails.config import build_pipelines_from_config               # config.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
class PromptInjectionGuardrail(Guardrail):                     # :648
    name = "prompt_injection"                                  # :682
    stages: ClassVar[set] = {GuardrailStage.INPUT}             # :683
    priority = 10                                              # :684
    def __init__(self, strict_mode=True, block_on_threat=False,
                 injection_probability_threshold=0.98, **kwargs)   # :686-692
        self.injection_probability_threshold = ...             # :708
        self.on_error = "fail_closed" if block_on_threat else "fail_open"   # :709
    async def check(self, content, ctx) -> GuardrailResult:    # :743
        if ctx.extras.get("trusted_source", False): PASS       # :758
        ... threats ...; if not threats: PASS                  # :797
        await self._security_logger.log_injection_attempt(...) # :800-811
        BLOCK branch                                           # :821-830
        wrapped = self._wrap_flagged_input(sanitized, threats) # :832
        return GuardrailResult(action=TRANSFORM, content=wrapped)  # :833
    @staticmethod def _wrap_flagged_input(text, threats) -> str   # :836 — output starts with '<potentially_unsafe_input'

# packages/ai-parrot/src/parrot/bots/guardrails/builtin/secrets.py
class SecretsGuardrail: priority = 10  # :49 — stages include TOOL_OUTPUT

# TOOL_OUTPUT seam: packages/ai-parrot/src/parrot/tools/abstract.py:188-196
#   GuardrailContext(stage=TOOL_OUTPUT, agent_name=tool_name, tool_name=tool_name)  (no extras)
#   returns (outcome.content or value, outcome.flag_reports)

# TASK-4825: Guardrail.priority may be dict[GuardrailStage, int]; TRANSFORM reports surface.
```

### Does NOT Exist
- ~~`PromptInjectionGuardrail.scan_tool_output`~~ — created here (TASK-4834 reads it via `getattr`).
- ~~`exclude_tools` / per-tool opt-out~~ — explicitly out of v1.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_scan_tool_output.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail.check",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail._wrap_flagged_input"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the ctor flag and instance stages/priority — *why*: config routes by instance `stages`.
2. Add the TOOL_OUTPUT branch before the BLOCK decision — *why*: the cap must win over `block_on_threat`.
3. Idempotency guard at the top of the TOOL_OUTPUT path — *why*: re-runs must not nest markers.
4. Tests through `build_pipelines_from_config` (real pipeline ordering with secrets).

### `prompt_injection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        injection_probability_threshold: float = 0.98,' prompt_injection.py)
# AFTER — insert below `        injection_probability_threshold: float = 0.98,` (verified: :690)
        scan_tool_output: bool = False,
```
```python
# occurrences: 1 (verified: grep -c '        self.on_error = "fail_closed" if block_on_threat else "fail_open"' prompt_injection.py)
# AFTER — insert below that line (verified: :709)
        # FEAT-761: opt-in scanning of tool / retrieval content. Instance
        # attributes on purpose — `build_pipelines_from_config` routes by the
        # instance's `stages`, and the ClassVar default must stay INPUT-only.
        self.scan_tool_output = scan_tool_output
        if scan_tool_output:
            self.stages = {GuardrailStage.INPUT, GuardrailStage.TOOL_OUTPUT}
            # after SecretsGuardrail (10) at TOOL_OUTPUT: scrub secrets first
            self.priority = {GuardrailStage.INPUT: 10, GuardrailStage.TOOL_OUTPUT: 20}
```
Document `scan_tool_output` in the `__init__` docstring Args.
```python
# occurrences: 1 (verified: grep -c '        if not threats:' prompt_injection.py)
# AFTER — insert below the `if not threats: return PASS` pair (verified: :797-798)
        if ctx.stage == GuardrailStage.TOOL_OUTPUT:
            # FILL IN: log via self._security_logger.log_injection_attempt exactly like INPUT (same args;
            # chatbot_id from ctx.extras.get("chatbot_id", ""), metadata adds "tool_name": ctx.tool_name);
            # then return GuardrailResult(TRANSFORM, content=self._wrap_flagged_input(sanitized, threats),
            # report={"threats_detected": len(threats), "max_severity": max_threat_level(threats).value,
            #         "stage": "tool_output", "tool_name": ctx.tool_name})
            # — bounded by "never BLOCK at TOOL_OUTPUT, report carries no content"
```
```python
# Idempotency: at the top of check(), right after the empty-input short-circuit (verified: :765-766):
        if ctx.stage == GuardrailStage.TOOL_OUTPUT and content.lstrip().startswith("<potentially_unsafe_input"):
            return GuardrailResult(action=GuardrailAction.PASS)
```

### `packages/ai-parrot/tests/unit/test_guardrails_scan_tool_output.py` (CREATE)
```python
"""FEAT-761 TASK-4833 — injection scanning at TOOL_OUTPUT."""
import pytest

from parrot.bots.guardrails.base import GuardrailAction, GuardrailContext, GuardrailStage
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail
from parrot.bots.guardrails.config import build_pipelines_from_config

# FILL IN: use the existing fake-engine helper pattern (tests/_injection_test_helpers.py) to force
# a high score; tests:
#  - default: stages == {INPUT}, TOOL_OUTPUT pipeline lacks it (compat)
#  - scan_tool_output=True: in INPUT and TOOL_OUTPUT pipelines; after secrets at TOOL_OUTPUT
#  - TOOL_OUTPUT detection -> TRANSFORM + report (no content), even with block_on_threat=True
#  - INPUT behavior unchanged with block_on_threat=True (still BLOCK)
#  - already-wrapped content -> PASS (no nesting)
#  - report surfaces in PipelineOutcome.flag_reports["prompt_injection"]
```

### FILL IN checklist
- [ ] TOOL_OUTPUT branch (log + wrap + report)
- [ ] tests

---

## Acceptance Criteria

- [ ] Default construction is bit-identical to today (stages, priority, verdicts).
- [ ] With `scan_tool_output=True`, TOOL_OUTPUT never returns BLOCK; returns TRANSFORM + report.
- [ ] Secrets scrub before injection scan at TOOL_OUTPUT.
- [ ] Re-scanning wrapped content is a PASS.
- [ ] Existing injection suites green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_scan_tool_output.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_secrets.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4825 and TASK-4828 are `done`; re-verify anchors (line numbers shift after 4827/4828 — trust `grep -c`, not `:NN`).
3. Mark `in-progress`; implement; complete `# FILL IN:`.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4833 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
