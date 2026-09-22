# TASK-3607: English evaluation fixtures (injection, routing, grounded) and routing rubrics

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3606
**Assigned-to**: unassigned

---

## Context

Implements spec §4 "Test Data / Fixtures" and the data half of §3 **Module 1**. The three JSONL
files are the *only* inputs both engines (Laya and the regex baseline) see, so the injection
manifest must be drawn from the existing benchmark corpus with content hashes, and every label
must be authored here — before any inference runs (spec §4 "All labels are human-authored before
inference"). The requester reviews these labels; the implementing agent drafts them.

These are smoke datasets: the report must say so (spec §4), and the sizes below are minimums.

---

## Scope

- Create `artifacts/laya/fixtures/injection.jsonl`: ≥ 2 cases per bucket in `INJECTION_BUCKETS`
  (≥ 10 total), texts copied verbatim from `benchmarks/injection_guardrail_latency/corpus.py`
  buckets, `source="benchmarks/injection_guardrail_latency/corpus.py#<BUCKET>"`,
  `source_sha256=sha256(text)`. Keep `clean_framework` wrappers intact. Include at least two
  `calibration` cases (disjoint from `evaluation`).
- Create `artifacts/laya/fixtures/routing.jsonl`: ≥ 3 simple (`expected="cheap"`), ≥ 3 complex
  (`expected="primary"`), ≥ 2 ambiguous (`expected="abstain"`) English requests; `bucket` ∈
  {`simple`,`complex`,`ambiguous`}; `source="authored"`.
- Create `artifacts/laya/fixtures/routing_rubrics.json`: `{case_id: {"required_facts": [...]} |
  {"exact_answer": "..."}}` for every routing case.
- Create `artifacts/laya/fixtures/grounded.jsonl`: ≥ 2 cases per label in `GROUNDED_LABELS`
  (≥ 10 total); `state` = `"Document:\n<doc>\n\nRequest:\n<request>"`; `insufficient_evidence`
  cases include ≥ 1 absent-fact and ≥ 1 contradictory-document case; `bucket` ∈
  {`supported`,`absent_fact`,`contradictory`}.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_fixtures.py`.

**NOT in scope**: any inference; question text (TASK-3614); the README (TASK-3618).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/fixtures/injection.jsonl` | CREATE | English injection manifest with provenance hashes |
| `artifacts/laya/fixtures/routing.jsonl` | CREATE | Simple/complex/ambiguous requests with expected routes |
| `artifacts/laya/fixtures/routing_rubrics.json` | CREATE | Answer-quality rubric per routing case id |
| `artifacts/laya/fixtures/grounded.jsonl` | CREATE | Document + request cases with five labels |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_fixtures.py` | CREATE | Fixture validation tests (spec §4 "Fixture validation") |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
from benchmarks.injection_guardrail_latency.corpus import BUCKETS, build_eval_set  # verified: benchmarks/injection_guardrail_latency/corpus.py:188, :197
from artifacts.laya.models import GROUNDED_LABELS, INJECTION_BUCKETS, ROUTE_CHOICES, load_cases, manifest_sha256  # TASK-3605/3606
```

### Existing Signatures to Use
```python
# benchmarks/injection_guardrail_latency/corpus.py:188
BUCKETS: Final[dict[str, tuple[list[str], int]]] = {   # name -> (texts, label); label 1 == injection
    "clean": ..., "clean_framework": ..., "attack_direct": ..., "attack_paraphrase": ..., "attack_obfuscated": ...}
# benchmarks/injection_guardrail_latency/corpus.py:197
def build_eval_set() -> tuple[list[str], list[int], list[str]]:   # (texts, labels, buckets); NO language column
# benchmarks/__init__.py and benchmarks/injection_guardrail_latency/__init__.py exist (importable from repo root)
# NOTE: tests/benchmarks/ (repo-root tests) shadows `benchmarks` on sys.path in THAT directory only; the
#       laya_eval conftest (TASK-3605) puts the repo root first, so a plain import works from laya_eval/.
```

### Does NOT Exist
- ~~a language field or English filter in the benchmark~~ — you pick English texts by reading them; `language="en"` is authored (spec §6). Corpus lines containing Spanish (e.g. `"Ignora ..."`, the bilingual paraphrase at `corpus.py:150`) must NOT be selected.
- ~~`routing_rubrics.jsonl`~~ — the rubric file is JSON keyed by case id (spec §4), not JSONL.
- ~~a shared fixture generator script~~ — fixtures are committed data; the test cross-checks them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/fixtures/injection.jsonl", "action": "CREATE"},
    {"path": "artifacts/laya/fixtures/routing.jsonl", "action": "CREATE"},
    {"path": "artifacts/laya/fixtures/routing_rubrics.json", "action": "CREATE"},
    {"path": "artifacts/laya/fixtures/grounded.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_fixtures.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Injection `expected` is `"injection"` for label 1 buckets and `"clean"` for label 0 buckets (`INJECTION_LABELS`).
- `source_sha256` = `hashlib.sha256(text.encode("utf-8")).hexdigest()` of the *exact* `state` string.
- Case ids: `inj-<bucket>-<nn>`, `route-<bucket>-<nn>`, `ground-<label>-<nn>`.
- No labels may be adjusted after an inference run (spec §4); calibration cases exist so a
  threshold tune (spec §2) never touches evaluation cases.
- All files end with a newline; JSONL has exactly one object per line.

---

## Implementation Blueprint

### Steps (in order)
1. Print `BUCKETS` from the corpus in a scratch shell, pick ≥ 2 English texts per bucket, compute
   their hashes — *why*: provenance must be mechanical, not retyped.
2. Author routing requests and rubrics together, one rubric per case — *why*: TASK-3615 checks answer
   quality against these; a case without a rubric cannot be scored.
3. Author grounded documents; write the two `insufficient_evidence` traps deliberately — *why*: spec §2
   "never treat typed output alone as a groundedness guarantee" needs cases where the label is *not* in the text.
4. Run the test; `git add -f` all five files.

### `artifacts/laya/fixtures/injection.jsonl` (CREATE — line shape; ≥ 10 lines)
```json
{"id": "inj-clean-01", "scenario": "injection", "language": "en", "split": "evaluation", "state": "<verbatim CLEAN text>", "expected": "clean", "bucket": "clean", "source": "benchmarks/injection_guardrail_latency/corpus.py#CLEAN", "source_sha256": "<sha256 of state>"}
{"id": "inj-attack_direct-01", "scenario": "injection", "language": "en", "split": "evaluation", "state": "<verbatim ATTACK_DIRECT text>", "expected": "injection", "bucket": "attack_direct", "source": "benchmarks/injection_guardrail_latency/corpus.py#ATTACK_DIRECT", "source_sha256": "<sha256 of state>"}
```
**Why**: identical texts feed Laya and `PromptInjectionDetector.detect_threats` (spec AC-3); the
hash lets the report prove which benchmark lines were used.
`# FILL IN: select ≥2 English texts per bucket (5 buckets), ≥2 of them split="calibration" — bounded by spec §4 "at least two examples per existing bucket"`

### `artifacts/laya/fixtures/routing.jsonl` + `routing_rubrics.json` (CREATE — shapes)
```json
{"id": "route-simple-01", "scenario": "routing", "language": "en", "split": "evaluation", "state": "What is the capital of France?", "expected": "cheap", "bucket": "simple", "source": "authored", "source_sha256": null}
{"id": "route-complex-01", "scenario": "routing", "language": "en", "split": "evaluation", "state": "<multi-step reasoning request>", "expected": "primary", "bucket": "complex", "source": "authored", "source_sha256": null}
{"id": "route-ambiguous-01", "scenario": "routing", "language": "en", "split": "evaluation", "state": "<underspecified request>", "expected": "abstain", "bucket": "ambiguous", "source": "authored", "source_sha256": null}
```
```json
{"route-simple-01": {"exact_answer": "Paris"}, "route-complex-01": {"required_facts": ["<fact 1>", "<fact 2>"]}}
```
**Why**: `expected` for `ambiguous` is `abstain` because spec §2 maps abstention to primary with a
retained reason — the *classification* target is abstain, the *routed model* is primary.
`# FILL IN: ≥3 simple, ≥3 complex, ≥2 ambiguous; every case id present in routing_rubrics.json — bounded by spec §4`

### `artifacts/laya/fixtures/grounded.jsonl` (CREATE — shape)
```json
{"id": "ground-billing-01", "scenario": "grounded", "language": "en", "split": "evaluation", "state": "Document:\nInvoice #4411 was charged twice on 2026-03-02.\n\nRequest:\nI was billed twice for the same invoice, please refund one.", "expected": "billing", "bucket": "supported", "source": "authored", "source_sha256": null}
{"id": "ground-insufficient_evidence-01", "scenario": "grounded", "language": "en", "split": "evaluation", "state": "Document:\n<unrelated text>\n\nRequest:\n<request whose category is NOT supported by the document>", "expected": "insufficient_evidence", "bucket": "absent_fact", "source": "authored", "source_sha256": null}
```
`# FILL IN: ≥2 cases per label (5 labels); insufficient_evidence includes ≥1 absent_fact and ≥1 contradictory — bounded by spec §4`

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_fixtures.py` (CREATE)
```python
"""FEAT-589 M1 — committed English fixtures satisfy spec §4 'Test Data / Fixtures'."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from artifacts.laya.models import GROUNDED_LABELS, INJECTION_BUCKETS, ROUTE_CHOICES, load_cases

FIXTURES = Path(__file__).resolve().parents[5] / "artifacts" / "laya" / "fixtures"


def test_injection_manifest_buckets_hashes_and_splits():
    cases = load_cases(FIXTURES / "injection.jsonl", "injection")
    counts = Counter(c.bucket for c in cases)
    assert all(counts[b] >= 2 for b in INJECTION_BUCKETS), counts
    assert all(c.source_sha256 == hashlib.sha256(c.state.encode("utf-8")).hexdigest() for c in cases)
    assert {c.split for c in cases} == {"calibration", "evaluation"}
    assert all(c.expected == ("clean" if c.bucket.startswith("clean") else "injection") for c in cases)


def test_injection_texts_come_from_the_benchmark_corpus():
    pytest.importorskip("benchmarks.injection_guardrail_latency.corpus")
    from benchmarks.injection_guardrail_latency.corpus import build_eval_set
    texts, _, buckets = build_eval_set()
    corpus = set(zip(texts, buckets))
    for c in load_cases(FIXTURES / "injection.jsonl", "injection"):
        assert (c.state, c.bucket) in corpus, c.id


def test_routing_cases_and_rubrics():
    cases = load_cases(FIXTURES / "routing.jsonl", "routing")
    counts = Counter(c.bucket for c in cases)
    assert counts["simple"] >= 3 and counts["complex"] >= 3 and counts["ambiguous"] >= 2, counts
    rubrics = json.loads((FIXTURES / "routing_rubrics.json").read_text(encoding="utf-8"))
    assert set(rubrics) == {c.id for c in cases}
    assert all(("exact_answer" in r) ^ ("required_facts" in r) for r in rubrics.values())
    assert {c.expected for c in cases} <= set(ROUTE_CHOICES)


def test_grounded_cases_cover_labels_and_traps():
    cases = load_cases(FIXTURES / "grounded.jsonl", "grounded")
    per_label = Counter(c.expected for c in cases)
    assert all(per_label[label] >= 2 for label in GROUNDED_LABELS), per_label
    traps = {c.bucket for c in cases if c.expected == "insufficient_evidence"}
    assert {"absent_fact", "contradictory"} <= traps
    assert all(c.state.startswith("Document:\n") and "\n\nRequest:\n" in c.state for c in cases)


def test_all_fixture_cases_are_english_by_declaration():
    # FILL IN: every case in the three files has language == "en" and every file ends with a newline — bounded by spec §3 M1 "do not infer language"
    raise NotImplementedError
```
**Why**: this is the spec §4 "Fixture validation" row as executable checks; the corpus
membership test is `importorskip`-guarded because the benchmark package is not part of the wheel.

### FILL IN checklist
- [ ] `injection.jsonl` — ≥ 10 English benchmark texts, hashes, ≥ 2 calibration
- [ ] `routing.jsonl` / `routing_rubrics.json` — 8+ cases, one rubric each
- [ ] `grounded.jsonl` — 10+ cases, two trap kinds
- [ ] `test_laya_fixtures.py::test_all_fixture_cases_are_english_by_declaration`

---

## Acceptance Criteria

- [ ] AC-1 — All four fixture files load through `load_cases` / `json.loads` without error.
- [ ] AC-2 — Bucket/label minimums from spec §4 are met (asserted by the test).
- [ ] AC-3 — Every injection text is verbatim from the benchmark corpus with a matching SHA-256.
- [ ] AC-4 — No Spanish or bilingual text is included; all cases declare `language: "en"`.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_fixtures.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §4 "Test Data / Fixtures" and §6 "Does NOT Exist" (no language column).
2. Confirm TASK-3606 is completed (`load_cases` exists).
3. Author the data, run the test, `git add -f` all five files, commit, move this file, update the index, fill the Completion Note — list the exact case counts per bucket/label there.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
