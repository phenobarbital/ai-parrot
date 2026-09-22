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
    # Check injection.jsonl
    cases = load_cases(FIXTURES / "injection.jsonl", "injection")
    assert all(c.language == "en" for c in cases)
    
    # Check routing.jsonl
    cases = load_cases(FIXTURES / "routing.jsonl", "routing")
    assert all(c.language == "en" for c in cases)
    
    # Check grounded.jsonl
    cases = load_cases(FIXTURES / "grounded.jsonl", "grounded")
    assert all(c.language == "en" for c in cases)
    
    # Check that all files end with a newline
    for file_path in [FIXTURES / "injection.jsonl", FIXTURES / "routing.jsonl", FIXTURES / "grounded.jsonl"]:
        content = file_path.read_text(encoding="utf-8")
        assert content.endswith("\n"), f"File {file_path} does not end with a newline"
