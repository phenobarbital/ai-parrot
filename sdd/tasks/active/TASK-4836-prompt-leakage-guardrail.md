# TASK-4836: `PromptLeakageGuardrail` — INPUT extraction heuristics + OUTPUT shingle/fuzzy/canary leak detection

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4825, TASK-4829, TASK-4830
**Assigned-to**: unassigned

---

## Context

Spec §2 item 5 + §3 Module 6. Resolved decisions folded in: rendered per-turn prompt is
the reference (arrives as `ctx.extras["system_prompt"]`, wired by TASK-4837 — this task
reads it and no-ops when absent); canary ships in v1; INPUT side is heuristics-only;
streaming v1 limitation accepted and marked; priorities INPUT 12 / OUTPUT 220;
rapidfuzz is a core dep (TASK-4830), imported lazily.

### Detection algorithm (decided here — implement exactly)
OUTPUT, given prompt `P` and response `R`:
1. **Canary** (if policy `canary`): normalized substring (`lower()`, whitespace runs →
   single space) of canary in normalized `R` ⇒ CRITICAL.
2. **Word tokens with offsets**: `re.finditer(r"\w+", text)` on the ORIGINAL strings,
   comparing `m.group().lower()` — offsets stay mappable to `R` for redaction.
3. **Shingles**: n-grams (`ngram_size`, default 8) of `P`'s tokens; if `P` has fewer than
   `min_prompt_shingles` shingles ⇒ OUTPUT check is a no-op PASS (short prompts would FP
   on topic words). Hit ratio = |shingles(P) ∩ shingles(R)| / |shingles(P)|;
   ratio ≥ `shingle_hit_threshold` ⇒ leak (HIGH). Matched `R` token spans are collected.
4. **Fuzzy segments** (localized edited copies): split `P`'s tokens into segments of
   `3 * ngram_size` words; for each segment call
   `rapidfuzz.fuzz.partial_ratio_alignment(segment_text_lower, R.lower())`; score ≥
   `fuzzy_threshold` ⇒ leak (HIGH), collect `dest_start:dest_end` span.
5. Verdict: no hit ⇒ PASS. Hit ⇒ log content-free event; `block_on_threat` and
   CRITICAL/HIGH ⇒ BLOCK(`"prompt_leakage_detected"`); else TRANSFORM: merge spans,
   replace each with `[redacted: system-prompt disclosure]`.
6. Report (never text): `{"severity", "shingle_hit_ratio", "matched_segments",
   "canary_hit", "redacted_spans", "stream_checked"}` — `stream_checked:"final_only"`
   when `ctx.method == "ask_stream"`.

INPUT: module-level ES/EN extraction-attempt regexes ⇒ HIGH ⇒ TRANSFORM-wrap (reuse
`PromptInjectionGuardrail._wrap_flagged_input`) or BLOCK per policy.

---

## Scope

- Create `builtin/prompt_leakage.py`: `LeakagePolicy`, `_EXTRACTION_PATTERNS`,
  `PromptLeakageGuardrail` (`requires_system_prompt = True`).
- Tests incl. a perf check (2 KB prompt, 4 KB response, p99 < 5 ms after warm import).

**NOT in scope**: plumbing `system_prompt` into OUTPUT extras (TASK-4837); streaming
withholding adapter (follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_leakage.py` | CREATE | guardrail + policy |
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_leakage.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)  # base.py
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail  # :648 (_wrap_flagged_input :836)
from parrot.security.prompt_injection import SecurityEventLogger, ThreatLevel, max_threat_level  # :297, :14, :62
# lazy, inside the matcher only:
from rapidfuzz import fuzz   # rapidfuzz>=3.0 — fuzz.partial_ratio_alignment(s1, s2) -> ScoreAlignment(score, src_start, src_end, dest_start, dest_end)
```

### Existing Signatures to Use
```python
# Pattern for a Pydantic policy: parrot/bots/guardrails/builtin/moderation.py:33 ModerationPolicy
# TASK-4825: Guardrail.priority may be dict; Guardrail.requires_system_prompt ClassVar[bool]
# TASK-4829: SecurityEventLogger.log_security_category_event(*, category, severity, score, user_id, session_id, chatbot_id, counts)
# OUTPUT ctx (bots/abstract.py:2785-2799): method = "get_response" | "ask" | "ask_stream"; extras has
#   "chatbot_id", "ai_message", and (after TASK-4837) "system_prompt"
```

### Does NOT Exist
- ~~`parrot.bots.guardrails.builtin.prompt_leakage`~~ — created here.
- ~~`ctx.extras["system_prompt"]` before TASK-4837~~ — absent ⇒ OUTPUT check must PASS (never raise).
- ~~`rapidfuzz` at module import time~~ — import inside the matcher function.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_leakage.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_prompt_leakage.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail._wrap_flagged_input",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/moderation.py#ModerationPolicy"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `LeakagePolicy` + pattern data — *why*: policy is the registry-dict config surface.
2. Pure matcher `_detect_leak(prompt, response, policy) -> _LeakMatch` (no I/O) — *why*: testable + benchmarkable alone.
3. `check()` dispatch by stage — *why*: one guardrail, two stage behaviors.
4. Tests (verbatim leak, edited leak, paraphrase no-FP, short prompt no-op, canary, ES/EN INPUT, content-free report/log, perf).

### `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_leakage.py` (CREATE)
```python
"""PromptLeakageGuardrail — system-prompt extraction attempts (INPUT) and disclosures (OUTPUT). FEAT-761.

OUTPUT detection is deterministic: canary -> word-shingle overlap ->
rapidfuzz segment alignment, against the turn's rendered system prompt in
``ctx.extras["system_prompt"]``. Streaming turns are checked on the final
message only (v1): chunks already sent cannot be retracted — reports carry
``stream_checked: "final_only"``.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from parrot.security.prompt_injection import SecurityEventLogger, ThreatLevel, max_threat_level

from ..base import Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage
from .prompt_injection import PromptInjectionGuardrail

logger = logging.getLogger(__name__)

REDACTION_MARKER = "[redacted: system-prompt disclosure]"
_WORD = re.compile(r"\w+")


class LeakagePolicy(BaseModel):
    """Policy for :class:`PromptLeakageGuardrail` (registry dict config keys)."""
    ngram_size: int = Field(default=8, ge=3)
    min_prompt_shingles: int = Field(default=12, ge=1)
    shingle_hit_threshold: float = Field(default=0.12, gt=0.0, le=1.0)
    fuzzy_threshold: int = Field(default=85, ge=50, le=100)
    canary: str | None = None
    block_on_threat: bool = False
    strict_mode: bool = True


_EXTRACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    # FILL IN: >= 12 ES/EN: "repeat (all )?(the )?(text|instructions|everything) above",
    # "(print|show|reveal|output) (your|the) (system )?(prompt|instructions)( verbatim)?",
    # "what (were|are) your (initial|original|system) instructions",
    # ES: "repite (todo|tus instrucciones|el texto) (anterior|de arriba)",
    # "(muestra|revela|imprime)(me)? (tu|el) (prompt|mensaje) (de sistema|inicial)",
    # "cuáles son tus instrucciones (iniciales|originales|de sistema)" …
))


@dataclass
class _LeakMatch:
    canary_hit: bool = False
    shingle_hit_ratio: float = 0.0
    matched_segments: int = 0
    spans: list[tuple[int, int]] = field(default_factory=list)   # char spans in the ORIGINAL response

    @property
    def leaked(self) -> bool:
        return self.canary_hit or bool(self.spans)


def _detect_leak(prompt: str, response: str, policy: LeakagePolicy) -> _LeakMatch:
    """Pure deterministic matcher (algorithm in TASK-4836 Context, steps 1-4)."""
    # FILL IN: exactly the 4-step algorithm; shingle spans come from response token offsets
    # (m.start() of first token .. m.end() of last token of each matched n-gram); merge overlapping spans;
    # `from rapidfuzz import fuzz` here (lazy) — bounded by perf gate p99 < 5 ms (2 KB/4 KB) and "no I/O"


def _redact(response: str, spans: list[tuple[int, int]]) -> str:
    """Replace merged spans right-to-left with REDACTION_MARKER."""
    # FILL IN


class PromptLeakageGuardrail(Guardrail):
    """System-prompt extraction (INPUT) and disclosure (OUTPUT) guardrail."""
    name = "prompt_leakage"
    stages: ClassVar[set] = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}
    priority = {GuardrailStage.INPUT: 12, GuardrailStage.OUTPUT: 220}
    requires_system_prompt: ClassVar[bool] = True

    def __init__(self, **policy: Any) -> None:
        """Accept :class:`LeakagePolicy` fields as kwargs (registry dict config); unknown keys ignored."""
        known = {k: v for k, v in policy.items() if k in LeakagePolicy.model_fields}
        self.policy = LeakagePolicy(**known)
        self.on_error = "fail_closed" if self.policy.block_on_threat else "fail_open"
        self.logger = logging.getLogger(__name__)
        self._security_logger = SecurityEventLogger(logger=self.logger)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Dispatch to INPUT heuristics or OUTPUT matcher; never puts text in reports/logs."""
        # FILL IN: trusted_source / strict_mode / empty short-circuits;
        # INPUT: any _EXTRACTION_PATTERNS hit -> HIGH threat {"type":"prompt_leakage","level":HIGH,
        #   "pattern":"extraction-heuristic","description":"System prompt extraction attempt"} -> event -> BLOCK|TRANSFORM-wrap;
        # OUTPUT: prompt = ctx.extras.get("system_prompt"); not a non-empty str -> PASS;
        #   match = _detect_leak(prompt, content, self.policy); not leaked -> PASS;
        #   severity CRITICAL if canary_hit else HIGH; event (score=shingle_hit_ratio, counts={...});
        #   BLOCK(reason="prompt_leakage_detected", report=...) if block_on_threat else
        #   TRANSFORM(content=_redact(content, match.spans) or REDACTION_MARKER when only canary, report=...)
        # — bounded by "report keys: severity, shingle_hit_ratio, matched_segments, canary_hit, redacted_spans, stream_checked"
```

### `packages/ai-parrot/tests/unit/test_guardrails_prompt_leakage.py` (CREATE)
```python
"""FEAT-761 TASK-4836 — PromptLeakageGuardrail."""
import time

import pytest

from parrot.bots.guardrails.base import GuardrailAction, GuardrailContext, GuardrailStage
from parrot.bots.guardrails.builtin.prompt_leakage import (
    LeakagePolicy, PromptLeakageGuardrail, REDACTION_MARKER, _detect_leak,
)

# FILL IN: fixture: realistic ~2 KB system prompt (EN with an ES paragraph) + responses:
#  verbatim paragraph leak -> TRANSFORM, marker present, rest of answer intact;
#  lightly edited leak (line breaks/punctuation/casing changed) -> detected via fuzzy;
#  benign capability answer paraphrasing the prompt -> PASS (no FP);
#  prompt below min_prompt_shingles -> PASS; missing extras["system_prompt"] -> PASS;
#  canary in response -> CRITICAL, BLOCK when block_on_threat;
#  ctx.method="ask_stream" -> report["stream_checked"] == "final_only";
#  INPUT ES/EN extraction attempts flagged; benign ES "repite la última frase, por favor" not flagged;
#  report values contain no prompt/response substrings; security logger spy gets no content;
#  priority_for(INPUT)==12, priority_for(OUTPUT)==220; perf: p99 of 200 _detect_leak runs < 5 ms
```

### FILL IN checklist
- [ ] extraction patterns
- [ ] `_detect_leak` (4-step algorithm) + `_redact`
- [ ] `check()` dispatch
- [ ] tests incl. perf

---

## Acceptance Criteria

- [ ] Verbatim and lightly-edited disclosures detected; benign paraphrase not flagged.
- [ ] Canary ⇒ CRITICAL; `block_on_threat` ⇒ BLOCK + fail_closed.
- [ ] Missing `system_prompt` extra ⇒ PASS, never raises.
- [ ] Reports/events never contain prompt or response text; `stream_checked` on streaming turns.
- [ ] `_detect_leak` p99 < 5 ms on the 2 KB / 4 KB fixture.
- [ ] rapidfuzz imported lazily (importing the module does not import rapidfuzz).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_leakage.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4825/4829/4830 are `done`.
3. Mark `in-progress`; implement the algorithm exactly as specified in Context; complete `# FILL IN:`.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4836 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
