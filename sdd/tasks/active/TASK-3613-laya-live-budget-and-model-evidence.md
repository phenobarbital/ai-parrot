# TASK-3613: Live-call budget, live preflight and provider model-evidence extraction

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3605
**Assigned-to**: unassigned

---

## Context

Spec §2 fixes three live-mode rules that this task turns into small, pure, testable units in a new
`artifacts/laya/live.py`:

1. **Preflight** — `--live` requires `--primary-api-model`, `--cheap-api-model`, a positive
   `--max-live-calls` and an `ANTHROPIC_API_KEY` in the environment; anything missing is
   `live_config_missing` and no request is made. Without `--live`, no call is ever made.
2. **Logical-call cap** — counts `Agent.ask` calls across both arms, including failed calls;
   a slot is reserved *before* dispatch; a pair needs two remaining slots; a cap hit is
   `call_cap_reached`. The cap is not an HTTP-attempt or money cap (client retries/fallback).
3. **Model evidence** — the provider-returned model is read from `AIMessage.raw_response["model"]`
   when the raw response is a dict; `AIMessage.model` alone is insufficient (the factory copies the
   requested model, `responses.py:564-598`). Fallback metadata (`used_fallback_model`,
   `original_model`, `fallback_model`, `client.py:775-780`) is recorded separately. Missing raw
   evidence ⇒ `actual_model=None` and `model_unverified`.

TASK-3615 appends the paired runner to this same file.

---

## Scope

- Create `artifacts/laya/live.py`: `LivePreflightError`, `preflight_live(config, env) -> None`,
  `LiveCallBudget`, `ModelEvidence` (Pydantic), `extract_model_evidence(message, requested_model) -> ModelEvidence`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py` (spec §4 rows "Live configuration/cap", "Model evidence").

**NOT in scope**: building the `AnthropicClient` or the agent (TASK-3616); running pairs (TASK-3615).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/live.py` | CREATE | Preflight, logical-call budget, model-evidence extraction |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py` | CREATE | Cap/preflight/evidence tests with real `AIMessage` objects |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
from parrot.models.responses import AIMessage       # verified: packages/ai-parrot/src/parrot/models/responses.py:75
from parrot.models.basic import CompletionUsage     # verified: packages/ai-parrot/src/parrot/models/basic.py:48
from artifacts.laya.models import ERROR_CODES, EvaluationConfig   # TASK-3605
from pydantic import BaseModel, ConfigDict
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                       # :75
    model: str                                    # :98  — "The model used for generation" (set from the REQUESTED model by factories)
    provider: str                                 # :99
    usage: CompletionUsage                        # :101
    raw_response: Optional[Dict[str, Any]]        # :127 — original provider response
    metadata: Dict[str, Any] = Field(default_factory=dict)   # :152
    @staticmethod
    def from_claude(response: Dict[str, Any], input_text: str, model: str, ...) -> AIMessage   # :561-598: model=model (argument), raw_response=response
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:775-780
#   if used_fallback: ai_message.metadata["used_fallback_model"] = True; ["original_model"] = model; ["fallback_model"] = self._fallback_model
# packages/ai-parrot/src/parrot/models/basic.py:48  CompletionUsage(prompt_tokens|input_tokens, completion_tokens|output_tokens, total_tokens) — both vocabularies accepted
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:173  self.api_key = api_key or config.get("ANTHROPIC_API_KEY")
```

### Does NOT Exist
- ~~`AIMessage.actual_model` / `AIMessage.provider_model`~~ — no such field; evidence is `raw_response.get("model")`.
- ~~a guarantee that `raw_response` is a dict~~ — it is `Optional[Dict]`; treat non-dict/None as unverified.
- ~~an HTTP-attempt counter on the client~~ — the budget counts logical `ask` calls only; say so in the reason strings.
- ~~a default cheap model~~ — `cheap_api_model` must be supplied; no inference from names or from `fallback_model` (spec §4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/live.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_claude",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#CompletionUsage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `preflight_live` takes `env: Mapping[str, str]` (default `os.environ`) so tests never touch real env.
- `LiveCallBudget.reserve()` returns a bool; `reserve_pair()` requires `remaining >= 2` and reserves
  both at once (spec §2 "Require two remaining slots before starting a pair"); a failed call still
  consumes its slot — there is no `release()`.
- `ModelEvidence.verified` is `True` only when `actual_model` came from `raw_response["model"]`;
  a mismatch between requested and actual stays visible (`mismatch: bool`), never corrected.

---

## Implementation Blueprint

### Steps (in order)
1. `preflight_live` — *why*: refuses before any request (spec §2 "Live preflight rejects missing inputs before requests").
2. `LiveCallBudget` — *why*: the pair runner (TASK-3615) needs `reserve_pair` semantics fixed here.
3. `extract_model_evidence` — *why*: spec §9 S5 REJECTed "treat returned model as proof"; this is the replacement.
4. Tests, `git add -f`.

### `artifacts/laya/live.py` (CREATE)
```python
"""Live-mode guards for the Laya evaluation: preflight, logical-call cap, model evidence (spec §2)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:75

from artifacts.laya.models import EvaluationConfig

API_KEY_ENV = "ANTHROPIC_API_KEY"  # verified: client.py:173 — the client itself reads this name


class LivePreflightError(ValueError):
    """Live configuration incomplete; ``error_code`` is always ``live_config_missing``."""

    error_code = "live_config_missing"


def preflight_live(config: EvaluationConfig, env: Mapping[str, str] | None = None) -> None:
    """Reject a live run before any request when model IDs, cap or API key are missing (spec §2).

    Raises:
        LivePreflightError: listing every missing input at once.
    """
    if not config.live:
        return
    env = os.environ if env is None else env
    missing: list[str] = []
    if not config.primary_api_model:
        missing.append("--primary-api-model")
    if not config.cheap_api_model:
        missing.append("--cheap-api-model")
    if config.max_live_calls <= 0:
        missing.append("--max-live-calls (> 0)")
    if not env.get(API_KEY_ENV):
        missing.append(f"{API_KEY_ENV} (environment)")
    if missing:
        raise LivePreflightError(f"live mode requires: {', '.join(missing)}")


class LiveCallBudget:
    """Cap on logical ``Agent.ask`` calls across both arms, failed calls included (spec §2)."""

    NOT_A_MONEY_CAP = "logical-call cap: not an HTTP-attempt or money cap (client retries/fallback may add requests)"

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def reserve(self) -> bool:
        """Reserve one slot BEFORE dispatch; False when exhausted (-> ``call_cap_reached``)."""
        if self.remaining <= 0:
            return False
        self.used += 1
        return True

    def reserve_pair(self) -> bool:
        """Reserve two slots atomically; a pair never starts with one slot left (spec §2)."""
        if self.remaining < 2:
            return False
        self.used += 2
        return True


class ModelEvidence(BaseModel):
    """What we can prove about which model answered (spec §2 'Record requested, selected, reported and provider-returned')."""

    model_config = ConfigDict(extra="forbid")
    requested_model: str | None
    reported_model: str | None          # AIMessage.model — NOT proof (factory echoes the request)
    actual_model: str | None            # raw_response["model"] when available
    verified: bool
    mismatch: bool
    fallback_metadata: dict[str, Any] | None
    usage: dict[str, Any] | None
    error_code: str | None              # "model_unverified" when actual_model is None


def extract_model_evidence(message: AIMessage, requested_model: str | None) -> ModelEvidence:
    """Prefer the raw provider model; keep fallback metadata separate; never substitute or 'correct' anything."""
    raw = message.raw_response if isinstance(message.raw_response, dict) else None
    actual = raw.get("model") if raw and isinstance(raw.get("model"), str) else None
    meta = message.metadata or {}
    fallback = {k: meta[k] for k in ("used_fallback_model", "original_model", "fallback_model") if k in meta} or None
    # FILL IN: usage = message.usage.model_dump() if message.usage else None — bounded by spec §2 "usage"
    return ModelEvidence(requested_model=requested_model, reported_model=message.model, actual_model=actual,
                         verified=actual is not None, mismatch=bool(actual and requested_model and actual != requested_model),
                         fallback_metadata=fallback, usage=None, error_code=None if actual else "model_unverified")
```
**Why this shape**: `from_claude` sets `model=` from its *argument* and `raw_response=response`
(`responses.py:585-596`), so only the raw dict can prove what ran. The three fallback keys are the
exact ones the Anthropic client writes (`client.py:777-780`).

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py` (CREATE)
```python
"""FEAT-589 M4 — live preflight, logical-call cap and model-evidence extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

from artifacts.laya.models import EvaluationConfig
from artifacts.laya.live import LiveCallBudget, LivePreflightError, extract_model_evidence, preflight_live


def _cfg(**kw) -> EvaluationConfig:
    base = dict(worker_python=Path("/bin/python3"), checkpoint_path=Path("/tmp/c"), checkpoint_revision="r", output_dir=Path("/tmp/o"))
    base.update(kw)
    return EvaluationConfig(**base)


def _msg(model="req-model", raw=None, metadata=None) -> AIMessage:
    return AIMessage(input="q", output="a", model=model, provider="claude", raw_response=raw, metadata=metadata or {},
                     usage=CompletionUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5))


def test_preflight_is_a_noop_without_live_flag():
    preflight_live(_cfg(live=False), env={})


def test_preflight_lists_every_missing_input_before_any_request():
    with pytest.raises(LivePreflightError) as ei:
        preflight_live(_cfg(live=True), env={})
    msg = str(ei.value)
    assert all(part in msg for part in ("--primary-api-model", "--cheap-api-model", "--max-live-calls", "ANTHROPIC_API_KEY"))
    assert ei.value.error_code == "live_config_missing"


def test_preflight_passes_with_all_inputs():
    preflight_live(_cfg(live=True, primary_api_model="p", cheap_api_model="c", max_live_calls=2), env={"ANTHROPIC_API_KEY": "k"})


def test_budget_counts_both_arms_and_refuses_partial_pair():
    b = LiveCallBudget(3)
    assert b.reserve_pair() and b.remaining == 1
    assert not b.reserve_pair()       # one slot left: no partial pair
    assert b.reserve() and not b.reserve()


def test_failed_calls_still_consume_slots():
    # FILL IN: reserve(), simulate failure (no release API exists), assert used == 1 — bounded by spec §2 "including failed calls"
    raise NotImplementedError


def test_raw_provider_model_is_preferred_and_mismatch_stays_visible():
    ev = extract_model_evidence(_msg(model="claude-x", raw={"model": "claude-x-20260101", "content": []}), "claude-x")
    assert ev.verified and ev.actual_model == "claude-x-20260101" and ev.reported_model == "claude-x"
    assert ev.mismatch and ev.error_code is None


def test_requested_only_metadata_cannot_establish_actual_execution():
    ev = extract_model_evidence(_msg(model="claude-x", raw=None), "claude-x")
    assert not ev.verified and ev.actual_model is None and ev.error_code == "model_unverified"


def test_fallback_metadata_is_recorded_separately():
    ev = extract_model_evidence(_msg(raw={"model": "fb"}, metadata={"used_fallback_model": True, "original_model": "a", "fallback_model": "fb"}), "a")
    assert ev.fallback_metadata == {"used_fallback_model": True, "original_model": "a", "fallback_model": "fb"} and ev.actual_model == "fb"
```
**Why**: spec §4 rows "Live configuration/cap" ("No calls by default; missing IDs fail preflight; both
arms counted; no partial pair after cap") and "Model evidence" ("Raw provider model preferred;
requested-only metadata cannot establish actual execution; fallback visible").

### FILL IN checklist
- [ ] `live.py::extract_model_evidence` — usage dump
- [ ] `test_laya_live.py::test_failed_calls_still_consume_slots`

---

## Acceptance Criteria

- [ ] AC-1 — Preflight is inert without `--live`, and with `--live` names every missing input in one error.
- [ ] AC-2 — `reserve_pair()` refuses with one slot left; failed calls are not refunded.
- [ ] AC-3 — Evidence prefers `raw_response["model"]`, marks `model_unverified` without it, and surfaces mismatches and fallback metadata without substitution.
- [ ] `ruff check artifacts/laya/live.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 live paragraphs (cap, evidence) and §9 S5.
2. Confirm TASK-3605 is completed; re-verify `responses.py:561-598` and `client.py:775-780` with `sed -n`.
3. Implement from the Blueprint; run the Validation Command; `git add -f` both files; commit; move this file; update the index; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
