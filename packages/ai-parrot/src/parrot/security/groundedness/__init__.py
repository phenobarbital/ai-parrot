"""Deterministic groundedness scoring (FEAT-398, detection-only).

Extracts verifiable hard-data atoms (money, percent, number, date,
identifier) from an agent's final answer and scores them against the
turn's own tool-call evidence — a deterministic, stdlib-only alternative
to an LLM-judge hallucination check. Detection only: this package never
mutates, masks, or blocks a response.

See ``sdd/specs/deterministic-groundedness-scoring.spec.md`` for the full
design. This package exposes Module 1 (atom extraction and normalization),
Module 2 (evidence index, scorer, policy/report models), and Module 3
(``GroundednessGuardrail`` — the FLAG-only OUTPUT-pipeline plugin that
wires the scorer into the unified guardrails infrastructure, FEAT-396).
"""
from .evidence import EvidenceIndex
from .extractors import extract_atoms
from .guardrail import GroundednessGuardrail
from .models import Atom, AtomKind
from .policy import AtomVerdict, GroundednessPolicy, GroundednessReport
from .scorer import GroundednessScorer

__all__ = [
    "Atom",
    "AtomKind",
    "AtomVerdict",
    "EvidenceIndex",
    "GroundednessGuardrail",
    "GroundednessPolicy",
    "GroundednessReport",
    "GroundednessScorer",
    "extract_atoms",
]
