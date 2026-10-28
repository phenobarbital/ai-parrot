# TASK-4835: `JailbreakGuardrail` + `warmup_jailbreak_model()`

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4827, TASK-4828, TASK-4829, TASK-4832
**Assigned-to**: unassigned

---

## Context

Spec §2 item 3 + §3 Module 4. INPUT guardrail mirroring `PromptInjectionGuardrail`'s
flow, scoring through the chassis (TASK-4827/4828) with its own engine spec
(`PARROT_JAILBREAK_*`), content-free events (TASK-4829), and the **default model,
graph path, positive labels and threshold taken from the committed bake-off manifest**
(TASK-4832, `benchmarks/injection_guardrail_latency/results-jailbreak/manifest.json`).
If the manifest's winner is `null`, `default_model_id` is `""` and resolution uses only
`PARROT_JAILBREAK_ONNX_DIR` / `PARROT_JAILBREAK_ONNX_MODEL` (heuristic floor otherwise).

Verdicts (mirror injection): ML score > threshold ⇒ CRITICAL; heuristic-floor hit ⇒
HIGH. `block_on_threat=True` + CRITICAL/HIGH ⇒ BLOCK (reason `"jailbreak_detected"`,
report `{"threats_detected": n}`); otherwise TRANSFORM-wrap (reusing
`PromptInjectionGuardrail._wrap_flagged_input`) + report. Priority 11 (after injection).

---

## Scope

- Create `builtin/jailbreak.py`: `_JAILBREAK_SPEC: EngineSpec`, `_HEURISTIC_PATTERNS`
  (module-level ES/EN regex data — per-guardrail ownership, spec §8), `JailbreakGuardrail`,
  `warmup_jailbreak_model()`.
- Tests, including a consistency test: constants == committed manifest winner.

**NOT in scope**: registry registration (done lazily by TASK-4826); docs (TASK-4838).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/jailbreak.py` | CREATE | guardrail + warmup |
| `packages/ai-parrot/tests/unit/test_guardrails_jailbreak.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)  # base.py
from parrot.bots.guardrails.builtin._engine_chassis import (
    EngineSpec, resolve_engine, score_async, warmup_model,
)  # TASK-4827 / TASK-4828
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail  # :648 (for _wrap_flagged_input)
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel, max_threat_level,
)  # :102, :297, :14, :62
```

### Existing Signatures to Use
```python
# PromptInjectionGuardrail (pattern to mirror) — prompt_injection.py:648-833
#   trusted_source bypass :758; strict_mode gate :760; empty short-circuit :765;
#   framework strip: self._framework_sanitizer.strip_framework_patterns(content) :776
#   BLOCK shape :826-830; TRANSFORM :832-833; on_error from block_on_threat :709
@staticmethod PromptInjectionGuardrail._wrap_flagged_input(text: str, threats: list[dict]) -> str  # :836
#   uses threat keys: probability, description, pattern
# SecurityEventLogger.log_security_category_event(*, category, severity, score, user_id, session_id, chatbot_id, counts)  # TASK-4829
# EngineSpec(category, env_prefix, default_model_id, known_graph_paths, kind, positive_label_match, max_length)  # TASK-4827
```

### Does NOT Exist
- ~~`parrot.bots.guardrails.builtin.jailbreak`~~ — created here.
- ~~`SecurityEventLogger.log_injection_attempt` for jailbreak~~ — MUST NOT be used (logs content).
- ~~a pytector fallback for jailbreak~~ — chain is env dir → cached snapshot → heuristic floor.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/jailbreak.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_jailbreak.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail._wrap_flagged_input",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/base.py#Guardrail",
    "sym:packages/ai-parrot/src/parrot/security/prompt_injection.py#PromptInjectionDetector"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the committed manifest; fill the four `_DEFAULT_*` constants from its winner — *why*: the default is decided by evidence, never by hand.
2. Write the module (block below) — *why*: mirrors injection 1:1 so operators get identical policy semantics.
3. Tests including manifest consistency.

### `packages/ai-parrot/src/parrot/bots/guardrails/builtin/jailbreak.py` (CREATE)
```python
"""JailbreakGuardrail — INPUT detection of instruction-override / boundary-bypass attempts (FEAT-761).

Engine: chassis-resolved ONNX model (``PARROT_JAILBREAK_ONNX_DIR`` ->
cached HF snapshot -> heuristic floor). The default model is the winner of
the committed bake-off (benchmarks/injection_guardrail_latency/
results-jailbreak/manifest.json); call ``await warmup_jailbreak_model()`` at
host startup to download it — construction never downloads.
"""
import logging
import re
from typing import Any, ClassVar

from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel, max_threat_level,
)

from ..base import Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage
from ._engine_chassis import EngineSpec, resolve_engine, score_async, warmup_model
from .prompt_injection import PromptInjectionGuardrail

logger = logging.getLogger(__name__)

# FILL IN: values from results-jailbreak/manifest.json winner ("" / defaults when winner is null)
_DEFAULT_MODEL_ID: str = ""
_DEFAULT_GRAPH_PATH: str = "onnx/model.onnx"
_DEFAULT_POSITIVE_LABELS: tuple[str, ...] = ("jailbreak", "malicious")
_DEFAULT_THRESHOLD: float = 0.9

_JAILBREAK_SPEC = EngineSpec(
    category="jailbreak",
    env_prefix="PARROT_JAILBREAK",
    default_model_id=_DEFAULT_MODEL_ID,
    known_graph_paths={_DEFAULT_MODEL_ID: _DEFAULT_GRAPH_PATH} if _DEFAULT_MODEL_ID else {},
    kind="classifier",
    positive_label_match=_DEFAULT_POSITIVE_LABELS,
)

#: Heuristic floor (no model resolved). Data, not logic — ES/EN, compiled once.
_HEURISTIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    # FILL IN: >= 12 patterns: DAN/developer mode, "ignore (all )?(previous|prior) instructions",
    # "you are no longer (an AI|bound)", "pretend you have no (rules|restrictions)",
    # ES: "ignora (todas )?las instrucciones (anteriores|previas)", "modo desarrollador",
    # "ya no tienes (reglas|restricciones)", "actúa como si no tuvieras (límites|filtros)" …
))


class JailbreakGuardrail(Guardrail):
    """INPUT guardrail for jailbreak attempts; policy parity with ``prompt_injection``."""
    name = "jailbreak"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 11

    def __init__(
        self,
        strict_mode: bool = True,
        block_on_threat: bool = False,
        jailbreak_probability_threshold: float = _DEFAULT_THRESHOLD,
        **kwargs: Any,
    ) -> None:
        """Resolve the engine offline (never downloads); heuristic floor when none."""
        self.strict_mode = strict_mode
        self.block_on_threat = block_on_threat
        self.jailbreak_probability_threshold = jailbreak_probability_threshold
        self.on_error = "fail_closed" if block_on_threat else "fail_open"
        self.logger = logging.getLogger(__name__)
        self._framework_sanitizer = PromptInjectionDetector(logger=self.logger)
        # None => heuristic floor. The chassis returns None when neither the env
        # dir nor a cached snapshot of the default model is usable.
        self._engine = resolve_engine(_JAILBREAK_SPEC)
        self._security_logger = SecurityEventLogger(logger=self.logger)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """PASS / TRANSFORM-wrap (+report) / BLOCK per policy; never logs content."""
        # FILL IN: trusted_source / strict_mode / empty short-circuits (mirror :758-766);
        # scan_text = framework strip; ML: score = await score_async(self._engine, scan_text) > threshold
        # -> threat {"type":"jailbreak","level":CRITICAL,"probability":score,"pattern":"onnx-model",
        #            "description":"High probability jailbreak attempt"} (NO matched_text);
        # else heuristic floor -> HIGH threat with pattern "heuristic";
        # log via log_security_category_event(category="jailbreak", severity=max_threat_level(threats), score=...);
        # BLOCK(reason="jailbreak_detected", report={"threats_detected": n}) when block_on_threat and CRITICAL/HIGH;
        # else TRANSFORM(content=PromptInjectionGuardrail._wrap_flagged_input(content, threats),
        #                report={"threats_detected": n, "max_severity": ..., "engine": "onnx"|"heuristic"})


async def warmup_jailbreak_model(force_download: bool = False) -> str:
    """The only jailbreak download site; returns ``"onnx"`` or ``"none"``. Never raises."""
    return await warmup_model(_JAILBREAK_SPEC, force_download=force_download)
```
**Why this shape**: same policy surface/verdict semantics as injection (spec Goal 1);
the wrap is reused so the LLM sees one consistent untrusted-input marker. With an empty
`_DEFAULT_MODEL_ID` (null winner) the cache probe has nothing to look up, so the chassis's
`_do_resolve` must treat an empty model id as "skip the cache step" — verify that branch
exists in TASK-4827's implementation and add a test for it here.

### `packages/ai-parrot/tests/unit/test_guardrails_jailbreak.py` (CREATE)
```python
"""FEAT-761 TASK-4835 — JailbreakGuardrail."""
import json
from pathlib import Path

import pytest

from parrot.bots.guardrails.builtin import _engine_chassis as chassis
from parrot.bots.guardrails.builtin import jailbreak as jb

# FILL IN: autouse chassis._reset_chassis_state(); fake engine via monkeypatch of jb.resolve_engine;
# tests: threshold gate; TRANSFORM wrap + report default; BLOCK + fail_closed when block_on_threat;
# trusted_source/strict_mode bypass; heuristic floor ES and EN hits with no engine; benign ES not flagged by floor;
# security logger receives NO content (spy on log_security_category_event, assert no content kwarg/value);
# manifest consistency: _DEFAULT_MODEL_ID/_DEFAULT_THRESHOLD/_DEFAULT_GRAPH_PATH equal manifest winner (or "" when null);
# importing jailbreak does not import onnxruntime
```

### FILL IN checklist
- [ ] constants from manifest
- [ ] heuristic patterns
- [ ] `check()` body
- [ ] tests

---

## Acceptance Criteria

- [ ] Default constants equal the committed manifest winner (test-enforced).
- [ ] Verdict/policy semantics match `prompt_injection` (TRANSFORM default, BLOCK + fail_closed opt-in).
- [ ] Heuristic floor works with no model; never downloads at construction.
- [ ] No content in reports or security events.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_jailbreak.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4827/4828/4829/4832 are `done`; read the manifest first.
3. Mark `in-progress`; implement; complete `# FILL IN:`.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4835 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 174.7s)
**Date**: 2026-10-28
**Notes**: JailbreakGuardrail + warmup added. Defaults taken from the committed bake-off manifest: madhurjindal/Jailbreak-Detector-Large, onnx/model.onnx, threshold 0.044844940304756165 (verified against manifest by worker; consistency test enforces it). Merge-tier validation green. Closed via close_task.sh (no durable review-evidence artifact writable). Caveats on the pin (thin 0.19 ms latency margin, threshold fitted to a 25-item ES-benign bucket, budget amended 30->45 ms) are in the bake-off README.

**Deviations from spec**: none
