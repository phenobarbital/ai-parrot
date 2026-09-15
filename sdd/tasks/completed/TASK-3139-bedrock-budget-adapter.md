# TASK-3139: `BedrockBudgetAdapter` — Local Counting, Usage Normalization, Finalization Payload, Strict-Qualification Registry

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3133
**Assigned-to**: unassigned

---

## Context

Module 4 (spec §3 "Module 4: Bedrock Counting, Transport and Finalization"), pure
adapter half. Two new modules in the **ai-parrot-client-amazon** satellite:

- `parrot/clients/amazon/budget.py` — `BedrockBudgetAdapter` (spec skeleton:
  `count_input`, `normalize_usage`, `prepare_finalization`) plus a shared canonical-JSON
  estimator used later by `MantleBudgetAdapter` (TASK-3142 appends its class **to this
  same module**; this task establishes the file first — spec §7 "M4 establishes Amazon
  adapter common code before M5").
- `parrot/clients/amazon/budget_qualifications.py` — `STRICT_QUALIFICATIONS` (empty),
  `QualificationKey`, `match_qualification()`, and `probe_count_tokens_support()` that
  inspects the installed botocore service model **without credentials or network**.

No client edits here (TASK-3140/3141) → `parallel: true` with TASK-3134..3138.

---

## Scope

- `count_input(payload, *, route, mode) -> TokenEstimate`: canonical, deterministic JSON
  (`sort_keys=True, separators=(",", ":"), ensure_ascii=False`) of all token-bearing
  prepared fields — for `route="converse"`: `system`, `messages`, `toolConfig`,
  `inferenceConfig` is **excluded** (not tokens), `modelId` excluded; for
  `route="invoke_model"`: `system`, `messages`, `tools`. Count with `TiktokenCounter`
  when its encoding is already available locally, else `HeuristicCounter`; never trigger
  a download (spec §2.2). `method` names the counter (`"tiktoken:o200k_base"` /
  `"heuristic"`); `quality="estimated"`; `request_fingerprint = sha256(canonical json + route + modelId)`.
  In `mode="strict"`: look up `match_qualification(...)`; if none → raise `BudgetUnsupported`
  before any inference (spec §2.5).
- `normalize_usage(raw, *, route) -> BudgetUsage`:
  - `converse`: input = `inputTokens + cacheReadInputTokens + cacheWriteInputTokens`,
    output = `outputTokens`; ignore `totalTokens`; missing `inputTokens`/`outputTokens` →
    `BudgetAccountingError` ("unknown, never zero"); negatives → `BudgetAccountingError`.
  - `invoke_model` (Anthropic-native body `usage`): input = `input_tokens +
    cache_read_input_tokens + cache_creation_input_tokens` (absent categories count 0 but
    `input_tokens` itself must be present), output = `output_tokens`.
  - `details` retains every raw category as ints; `provider="bedrock"`; `route` echoed.
- `prepare_finalization(frame) -> dict`: given a frame dict with keys
  `payload` (the last Converse payload), `completed_tool_calls` (list of `ToolCall`-like
  dicts with `id`, `name`, `arguments`, `result`), `pending_tool_calls` (same, no result),
  `answer_text` — return a **new** payload with `toolConfig` removed, every
  `toolUse`/`toolResult` content block rewritten as deterministic text blocks
  (`[tool call <id>] <name>(<json args>) -> <result | UNEXECUTED>`) in original order, the
  original `system` retained, and one appended user text block with the fixed instruction
  `FINALIZATION_INSTRUCTION` ("Answer from the information already available. Do not request tools.").
- Qualification module: `STRICT_QUALIFICATIONS: tuple[QualificationRecord, ...] = ()`;
  `QualificationKey` fields per spec §2.5 (model, endpoint/region, route, request-shape
  flags `tools/schema/cache/thinking/stream`, `botocore_version`, `aiobotocore_version`,
  `count_method`, `output_cap_semantics`, `evidence_ref`); `match_qualification(key,
  registry=STRICT_QUALIFICATIONS)` exact match only; `probe_count_tokens_support()`
  returns `False` when `botocore.session.get_session().get_service_model("bedrock-runtime").operation_names`
  lacks `"CountTokens"` (installed 1.35.36 → False).
- Tests `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py`:
  "Bedrock accounting" (cache fixture 100/800/50/50 → input 950, total 1000), "Strict
  qualification" (empty registry refuses; injected synthetic record matches; changed
  version/model/route/shape denies; probe returns False on installed SDK), and the
  payload-level part of "Finalization" (tool blocks → text, `toolConfig` gone).

**NOT in scope**: any edit to `bedrock.py` (TASK-3140/3141), `MantleBudgetAdapter` (TASK-3142), live probes (TASK-3145).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` | CREATE | `BedrockBudgetAdapter` + shared estimator helpers |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget_qualifications.py` | CREATE | Empty strict registry, key, matcher, offline probe |
| `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py` | CREATE | Accounting / strict / finalization-payload tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11.

### Verified Imports
```python
from parrot.models.token_budget import TokenEstimate, BudgetUsage            # TASK-3132
from parrot.core.exceptions import BudgetUnsupported, BudgetAccountingError  # TASK-3132
from parrot.memory.compaction.tokens import TiktokenCounter, HeuristicCounter, TokenCounter   # verified: memory/compaction/tokens.py:40, :70, :30
from parrot.models.basic import CompletionUsage                              # verified: models/basic.py:48 (reference only — NOT the budget shape)
import hashlib, json, importlib.metadata                                     # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/compaction/tokens.py
class TokenCounter(Protocol):                       # line 30
    def count(self, text: str) -> int               # line 35
class TiktokenCounter:                              # line 40
    def __init__(self, encoding: str = "o200k_base") -> None   # line 43  — may import tiktoken and load an encoding (can download!)
    def count(self, text: str) -> int               # line 51
class HeuristicCounter:                             # line 70
    def count(self, text: str) -> int               # line 75
def get_default_counter() -> TokenCounter           # line 89

# packages/ai-parrot/src/parrot/models/basic.py:147 — existing Bedrock normalization to COPY THE KEY NAMES FROM (not the arithmetic):
@classmethod
def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":
    # reads usage["inputTokens"], usage["outputTokens"], usage.get("cacheReadInputTokens", 0), usage.get("cacheWriteInputTokens", 0)

# Converse payload shape produced by BedrockConverseBase (bedrock.py:880-890, 1185-1197):
#   {"modelId": str, "messages": [{"role", "content": [{"text"} | {"toolUse": {...}} | {"toolResult": {...}}]}],
#    "system": [{"text": ...}], "inferenceConfig": {...}, "toolConfig": {"tools": [...]}, optional "guardrailConfig", "additionalModelRequestFields"}
# Native invoke_model body (bedrock.py:697-706): {"anthropic_version", "max_tokens", "messages", "temperature"?, "system"?}
```

### Does NOT Exist
- ~~`parrot.clients.amazon.budget`~~, ~~`budget_qualifications`~~ — created here.
- ~~`CountTokens` / `count_tokens` on the installed `bedrock-runtime` service model~~ — botocore 1.35.36 has neither the operation nor `ConverseTokensRequest` (spec §2.5); `probe_count_tokens_support()` must return `False` today and the tests assert that.
- ~~A passing entry in `STRICT_QUALIFICATIONS`~~ — ships **empty**; tests inject synthetic records via the `registry=` parameter, never by mutating the module tuple.
- ~~`TiktokenCounter` guaranteed offline~~ — `tiktoken.get_encoding` may download; wrap construction in a helper that checks `tiktoken` is importable AND the encoding is already cached (`tiktoken_ext` / `TIKTOKEN_CACHE_DIR`) — if uncertain, use `HeuristicCounter` (spec §2.2 "Do not initiate a tokenizer download from an inference hot path").
- ~~`BudgetUsage.total_tokens` from provider `totalTokens`~~ — computed field; never pass it.

---

## Implementation Notes

### Pattern to Follow
```python
def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
```

### Key Constraints
- `count_input` must be **pure** w.r.t. the payload (no mutation) and deterministic: same
  payload → same fingerprint. Any payload/model change after counting requires recounting —
  the caller (TASK-3140) recomputes the fingerprint at reservation; expose
  `fingerprint(payload, *, route) -> str` as a public helper so it can.
- Estimated-mode `TokenEstimate.quality` is `"estimated"`; only a matched qualification can
  produce `"exact"`, and since the registry is empty that branch is reachable only with an
  injected registry in tests (`count_input(..., registry=...)` optional kwarg).
- `prepare_finalization` must **never** fabricate a result: pending calls render as
  `-> UNEXECUTED`; completed ones render `str(result)`. Order preserved. `toolChoice` (inside
  `toolConfig`) disappears with `toolConfig`.
- Keep the module free of `aioboto3` imports; only `budget_qualifications.probe_count_tokens_support`
  imports `botocore` lazily inside the function.
- `MantleBudgetAdapter` is **not** defined here; leave a module docstring note that TASK-3142 appends it.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/basic.py:147-166` — Bedrock usage key names.
- `packages/ai-parrot-client-amazon/tests/unit/test_bedrock_multiround_usage.py:1-60` — test-file style for this package.

---

## Implementation Blueprint

### Steps (in order)
1. Create `budget_qualifications.py` — *why*: `count_input(mode="strict")` needs the matcher; keeping it separate mirrors spec §3 M4 paths.
2. Create `budget.py` with helpers + `BedrockBudgetAdapter` — *why*: spec skeleton signatures are fixed.
3. Write tests using the spec §4 fixtures.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget_qualifications.py` (CREATE)
```python
"""Strict-qualification registry for Bedrock/Mantle question budgets (FEAT-550, spec §2.5).

Ships EMPTY on purpose: on the inspected environment (botocore 1.35.36, openai 3.3.1)
no model/route/SDK combination is qualified for strict admission. Records are only
added after an opt-in live probe (see examples/clients/smoke/smoke_token_budget_qualification.py).
"""
from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualificationKey:
    """Exact tuple that must match for strict admission — no wildcards (spec §2.5)."""

    model: str
    endpoint: str            # region or Mantle base_url host
    route: str               # "converse" | "invoke_model" | "chat_completions"
    tools: bool
    schema: bool
    cache: bool
    thinking: bool
    stream: bool
    sdk_versions: tuple[tuple[str, str], ...]   # (("botocore","1.35.36"), ("aiobotocore","2.15.2")) — sorted by name
    count_method: str
    output_cap_semantics: str


@dataclass(frozen=True)
class QualificationRecord:
    """A passing probe record; `evidence_ref` points at the committed artifacts/logs entry."""

    key: QualificationKey
    qualification_id: str
    evidence_ref: str


STRICT_QUALIFICATIONS: tuple[QualificationRecord, ...] = ()


def installed_sdk_versions(*names: str) -> tuple[tuple[str, str], ...]:
    """Return sorted (name, version) pairs for installed distributions; missing → "absent"."""
    out = []
    for n in sorted(names):
        try:
            out.append((n, importlib.metadata.version(n)))
        except importlib.metadata.PackageNotFoundError:
            out.append((n, "absent"))
    return tuple(out)


def match_qualification(key: QualificationKey, *, registry: tuple[QualificationRecord, ...] = STRICT_QUALIFICATIONS) -> Optional[QualificationRecord]:
    """Exact-match lookup; returns None when unqualified."""
    for rec in registry:
        if rec.key == key:
            return rec
    return None


def probe_count_tokens_support() -> bool:
    """True only if the INSTALLED botocore service model exposes Runtime CountTokens (no network, no credentials)."""
    try:
        import botocore.session
        model = botocore.session.get_session().get_service_model("bedrock-runtime")
        return "CountTokens" in set(model.operation_names)
    except Exception as exc:  # noqa: BLE001 — absence of the SDK is "unsupported", not an error
        logger.debug("CountTokens probe failed: %s", exc)
        return False


__all__ = ["QualificationKey", "QualificationRecord", "STRICT_QUALIFICATIONS", "installed_sdk_versions", "match_qualification", "probe_count_tokens_support"]
```
**Why this shape**: spec §2.5 fixes the key dimensions and forbids wildcards; equality on a frozen dataclass is the exact match. The probe reads the installed schema only, so strict never silently "works" on 1.35.36.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` (CREATE)
```python
"""Bedrock (and, appended by TASK-3142, Mantle) question-budget adapters (FEAT-550, spec §3 M4/M5).

Counting is a local estimate unless a strict qualification matches; usage normalization
follows spec §2.2 (all input categories summed once, provider totals ignored).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from parrot.core.exceptions import BudgetAccountingError, BudgetUnsupported          # TASK-3132
from parrot.memory.compaction.tokens import HeuristicCounter, TokenCounter           # verified tokens.py:70/:30
from parrot.models.token_budget import BudgetUsage, TokenEstimate                    # TASK-3132

from .budget_qualifications import QualificationKey, QualificationRecord, STRICT_QUALIFICATIONS, installed_sdk_versions, match_qualification

logger = logging.getLogger(__name__)

FINALIZATION_INSTRUCTION = "Answer from the information already available. Do not request tools."
_CONVERSE_TOKEN_FIELDS = ("system", "messages", "toolConfig")
_NATIVE_TOKEN_FIELDS = ("system", "messages", "tools")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON for counting and fingerprints (spec §2.2)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def local_counter() -> tuple[TokenCounter, str]:
    """Return (counter, method_name); prefer an already-available tiktoken encoding, never download."""
    # FILL IN: try `from parrot.memory.compaction.tokens import TiktokenCounter` and construct it only when the encoding is cached locally
    #          (e.g. tiktoken importable AND encoding load succeeds with network disabled / TIKTOKEN_CACHE_DIR present); on any failure
    #          return (HeuristicCounter(), "heuristic"). Bounded by spec §2.2 "Do not initiate a tokenizer download from an inference hot path".
    return HeuristicCounter(), "heuristic"


def fingerprint(payload: dict[str, Any], *, route: str) -> str:
    """sha256 over canonical token-bearing fields + route + model id."""
    fields = _CONVERSE_TOKEN_FIELDS if route == "converse" else _NATIVE_TOKEN_FIELDS
    body = {k: payload.get(k) for k in fields if k in payload}
    model = payload.get("modelId") or payload.get("model") or ""
    return hashlib.sha256(f"{route}|{model}|{canonical_json(body)}".encode("utf-8")).hexdigest()


class BedrockBudgetAdapter:
    """Prepared-payload counting and usage normalization for Runtime text APIs."""

    provider = "bedrock"

    def __init__(self, *, counter: Optional[TokenCounter] = None, method: Optional[str] = None) -> None:
        self.logger = logging.getLogger(__name__)
        if counter is None:
            counter, method = local_counter()
        self._counter, self._method = counter, method or "heuristic"

    async def count_input(
        self, payload: dict[str, Any], *, route: str, mode: str,
        registry: tuple[QualificationRecord, ...] = STRICT_QUALIFICATIONS, endpoint: str = "",
    ) -> TokenEstimate:
        """Estimate locally or require an exact qualified Runtime counting path."""
        fp = fingerprint(payload, route=route)
        if mode == "strict":
            key = self._qualification_key(payload, route=route, endpoint=endpoint)
            rec = match_qualification(key, registry=registry)
            if rec is None:
                raise BudgetUnsupported(f"no strict qualification for {key.model} via {route} on installed SDKs")
            # FILL IN: exact path — only reachable with an injected registry; return quality="exact", method=rec.key.count_method,
            #          qualification_id=rec.qualification_id. Bounded by spec §2.5 (no uncounted strict requests).
            raise NotImplementedError
        fields = _CONVERSE_TOKEN_FIELDS if route == "converse" else _NATIVE_TOKEN_FIELDS
        text = canonical_json({k: payload.get(k) for k in fields if k in payload})
        n = self._counter.count(text)
        self.logger.debug("count_input route=%s method=%s tokens=%d", route, self._method, n)
        return TokenEstimate(input_tokens=n, method=self._method, quality="estimated", request_fingerprint=fp)

    def normalize_usage(self, raw: dict[str, Any], *, route: str) -> BudgetUsage:
        """Normalize disjoint cache/input/output categories; reject missing usage."""
        if not isinstance(raw, dict):
            raise BudgetAccountingError("usage missing or not a mapping")
        if route == "converse":
            keys = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")
            req_in, req_out = "inputTokens", "outputTokens"
        else:
            keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            req_in, req_out = "input_tokens", "output_tokens"
        # FILL IN: require req_in/req_out present and int-like >= 0 else BudgetAccountingError; sum the input categories present;
        #          details = {k: int(raw[k]) for present k}; model = raw.get("model", "") — bounded by spec §2.2 Normalization bullets 1-2.
        raise NotImplementedError

    def prepare_finalization(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Preserve completed evidence as text and remove tool-generation fields."""
        payload = json.loads(canonical_json(frame["payload"]))  # deep copy, never mutate the caller's payload
        payload.pop("toolConfig", None)
        # FILL IN: rewrite every message content block: {"toolUse":…} -> {"text": "[tool call <id>] <name>(<args json>)"},
        #          {"toolResult":…} -> {"text": "[tool result <id>] <text|UNEXECUTED>"}; use frame["pending_tool_calls"] ids to mark UNEXECUTED;
        #          append {"role":"user","content":[{"text": FINALIZATION_INSTRUCTION}]} (merge into last user turn if roles would collide).
        #          Bounded by spec §2.3 "render their name, call ID, arguments, and completed result as deterministic text … never fabricate results".
        raise NotImplementedError

    def _qualification_key(self, payload: dict[str, Any], *, route: str, endpoint: str) -> QualificationKey:
        return QualificationKey(
            model=str(payload.get("modelId") or payload.get("model") or ""), endpoint=endpoint, route=route,
            tools="toolConfig" in payload or "tools" in payload, schema=False,
            cache=any("cachePoint" in b for m in payload.get("messages", []) for b in m.get("content", []) if isinstance(b, dict)),
            thinking="additionalModelRequestFields" in payload, stream=False,
            sdk_versions=installed_sdk_versions("botocore", "aiobotocore", "aioboto3"),
            count_method="runtime_count_tokens", output_cap_semantics="converse_maxTokens",
        )


__all__ = ["BedrockBudgetAdapter", "FINALIZATION_INSTRUCTION", "canonical_json", "fingerprint", "local_counter"]
```
**Why this shape**: the three skeleton methods are copied verbatim from spec §3 M4. `fingerprint` is public because TASK-3140 must re-check it at reservation time (spec §2.2 "recheck the request fingerprint"). `schema`/`stream` flags are set by the caller-specific keys later; the key builder is a starting point that TASK-3140 may extend with `stream=True` for `_sdk_stream`.

### `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py` (CREATE)
```python
"""FEAT-550 M4 — Bedrock accounting, strict qualification and finalization payload (spec §4 rows)."""
from __future__ import annotations

import pytest

from parrot.clients.amazon.budget import BedrockBudgetAdapter, FINALIZATION_INSTRUCTION, fingerprint
from parrot.clients.amazon.budget_qualifications import (
    QualificationKey, QualificationRecord, STRICT_QUALIFICATIONS, installed_sdk_versions, match_qualification, probe_count_tokens_support,
)
from parrot.core.exceptions import BudgetAccountingError, BudgetUnsupported
from parrot.models.basic import CompletionUsage

CACHE_USAGE = {"inputTokens": 100, "cacheReadInputTokens": 800, "cacheWriteInputTokens": 50, "outputTokens": 50, "totalTokens": 1000}


class TestBedrockAccounting:
    def test_converse_cache_fields_summed_once(self):
        u = BedrockBudgetAdapter().normalize_usage(CACHE_USAGE, route="converse")
        assert (u.input_tokens, u.output_tokens, u.total_tokens) == (950, 50, 1000)
        assert CompletionUsage.from_bedrock(CACHE_USAGE).prompt_tokens == 100  # established semantics untouched

    def test_missing_aggregate_is_unknown_not_zero(self):
        with pytest.raises(BudgetAccountingError):
            BedrockBudgetAdapter().normalize_usage({"outputTokens": 5}, route="converse")

    def test_native_body_categories(self):
        # FILL IN: {"input_tokens": 10, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 1, "output_tokens": 2} -> 16/2. Bounded by spec §2.2 bullet 2.
        raise NotImplementedError

    async def test_count_is_deterministic_and_fingerprint_changes_with_payload(self):
        # FILL IN: same payload twice -> equal input_tokens & fingerprint; adding a message changes fingerprint; method in {"heuristic", "tiktoken:o200k_base"}.
        raise NotImplementedError


class TestStrictQualification:
    def test_registry_ships_empty_and_probe_false_on_installed_sdk(self):
        assert STRICT_QUALIFICATIONS == ()
        assert probe_count_tokens_support() is False  # botocore 1.35.36 has no CountTokens (spec §2.5)

    async def test_strict_refused_without_qualification(self):
        with pytest.raises(BudgetUnsupported):
            await BedrockBudgetAdapter().count_input({"modelId": "m", "messages": []}, route="converse", mode="strict")

    async def test_injected_exact_match_succeeds_and_any_change_denies(self):
        # FILL IN: build the key via adapter._qualification_key for a payload, inject QualificationRecord(key, "q1", "artifacts/logs/x"),
        #          count_input(..., mode="strict", registry=(rec,)) -> quality == "exact"; then a payload with tools / a different modelId /
        #          a registry whose sdk_versions differ -> BudgetUnsupported. Bounded by spec §2.5 "No wildcard qualification".
        raise NotImplementedError


class TestFinalizationPayload:
    def test_tool_blocks_become_text_and_toolconfig_removed(self):
        # FILL IN: frame with one completed toolUse/toolResult pair and one pending toolUse -> no "toolUse"/"toolResult" keys remain,
        #          "UNEXECUTED" present exactly once, FINALIZATION_INSTRUCTION is the last text, original payload untouched. Bounded by spec §2.3.
        raise NotImplementedError
```
**Why**: spec §4 fixture values (100/800/50/50 → 950/1000) and rows "Bedrock accounting", "Strict qualification", "Finalization" (payload part).

### FILL IN checklist
- [ ] `budget.py::local_counter` — offline tiktoken detection; bounded by spec §2.2 no-download rule
- [ ] `budget.py::BedrockBudgetAdapter.count_input` strict-exact branch; bounded by spec §2.5
- [ ] `budget.py::BedrockBudgetAdapter.normalize_usage` — presence/negativity checks + sums; bounded by spec §2.2 bullets 1-2
- [ ] `budget.py::BedrockBudgetAdapter.prepare_finalization` — block rewriting; bounded by spec §2.3
- [ ] all test FILL IN bodies

---

## Acceptance Criteria

- [ ] `from parrot.clients.amazon.budget import BedrockBudgetAdapter` and `from parrot.clients.amazon.budget_qualifications import STRICT_QUALIFICATIONS, probe_count_tokens_support` work
- [ ] Cache fixture normalizes to input 950 / output 50 / total 1000; `CompletionUsage.from_bedrock` semantics unchanged
- [ ] Missing `inputTokens`/`outputTokens` or negative values raise `BudgetAccountingError`
- [ ] `STRICT_QUALIFICATIONS == ()`; `probe_count_tokens_support()` is `False` on the installed SDK; strict `count_input` raises `BudgetUnsupported` unless an injected exact record matches
- [ ] `prepare_finalization` removes `toolConfig`, renders tool protocol as ordered text, marks pending calls `UNEXECUTED`, never mutates the input
- [ ] No network/tokenizer download in tests (run with network disabled or assert method is `heuristic` when tiktoken cache absent)
- [ ] `pytest packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py -v` passes; `ruff check` clean on both new modules

---

## Test Specification

Scaffold above. Add `test_totaltokens_never_readded` (raw with inflated `totalTokens=99999` still yields 1000).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.2 (Normalization), §2.3 (finalization frame), §2.5, §3 Module 4
2. **Check dependencies** — TASK-3133 in `sdd/tasks/completed/` (only records/errors are actually imported; the ledger is not)
3. **Verify the Codebase Contract** — `python -c "import botocore.session as s; print('CountTokens' in s.get_session().get_service_model('bedrock-runtime').operation_names)"` must print `False`
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3139-bedrock-budget-adapter.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker orchestrator (parrot-sdd-coder native haiku seat)
**Date**: 2026-09-11
**Notes**: Implemented `BedrockBudgetAdapter` (local counting via tiktoken-or-heuristic
fallback, usage normalization for both Converse cache-aware fields and native
Anthropic-shaped body categories, deterministic fingerprinting, `prepare_finalization`
tool-protocol-to-text rewriting with `toolConfig` removal and `UNEXECUTED` markers for
pending calls) and `budget_qualifications.py` (empty `STRICT_QUALIFICATIONS` registry,
`QualificationKey`/`QualificationRecord`, exact-match `match_qualification`, offline
`probe_count_tokens_support()` returning `False` on the installed botocore SDK).
Verified: `pytest packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py -v`
→ 9 passed (cache-field summation to 950/50/1000, missing-field → `BudgetAccountingError`,
native body categories, deterministic fingerprint, empty strict registry + `False` probe,
strict refusal without a qualification match, injected exact-match success, finalization
payload rewriting, `totalTokens` never re-added even when inflated in the raw payload);
`ruff check` clean on both new modules; imports and `STRICT_QUALIFICATIONS == ()` /
`probe_count_tokens_support() is False` spot-checked directly in the orchestrator worktree.

**Deviations from spec**: none

Seat: haiku (native) · Backend: n/a · Model: haiku · Attempts: 1 · Duration: 310.1s · Tokens: 90768 (subagent_tokens, in+out combined) · Tool uses: 42
