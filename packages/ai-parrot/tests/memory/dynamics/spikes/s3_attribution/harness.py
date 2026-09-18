"""S3 spike harness: delivered-memory manifests, attribution strategies, grade-table rows, metrics, corpus IO."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)
SPIKE_DIR = (
    Path(__file__).resolve().parent
)  # coder-owned spike package dir — sdd-coder fidelity gate forbids commits under sdd/
Label = Literal["relevant", "not_relevant", "unknown"]
GradeRow = Literal["no_review", "again", "easy", "good_capped", "hard", "good"]

#: Jaccard threshold for `overlap_tokens` — an experiment input, not a frozen default (spec §3 G3).
OVERLAP_TOKEN_THRESHOLD = 0.3

#: Candidate attribution caps evaluated by the gate (spec §3 G3 "candidate cap 3 — experiment input").
CANDIDATE_CAPS: tuple[int | None, ...] = (1, 3, 5, None)

#: judgments.jsonl rows must never carry transcript/prompt/tool-output text (spec §4 Test Data).
_TRANSCRIPT_FORBIDDEN_KEYS = {"prompt", "transcript", "text", "tool_output", "response", "lesson_text"}


def sha256_text(text: str) -> str:
    """Stable digest used in place of any transcript content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_signature(signature: str) -> str:
    """Collapse whitespace/case so equivalent error signatures compare equal."""
    return " ".join(signature.strip().lower().split())


@dataclass(frozen=True)
class DeliveredRef:
    """One memory version delivered by final packing (spec §2 MemoryRef: namespace, kind, id, content_version)."""

    memory_id: str
    content_version: str
    kind: str  # "episode" | "brain"
    error_signature: str | None
    lesson_tokens: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Exposure:
    """Spec §2 MemoryExposure — created by final packing, not by the LLM."""

    exposure_id: str
    attempt_or_turn_id: str
    delivered: tuple[DeliveredRef, ...]
    packed_sha256: str


@dataclass(frozen=True)
class OutcomeEvidence:
    """Trusted-receipt shaped outcome (spec §2 ReviewSignal): verified, first attempt, corrections, error signature, recovery."""

    outcome_id: str
    verified: bool
    success: bool
    first_attempt: bool
    correction_count: int
    error_signature: str | None
    recovery_refs: tuple[str, ...]  # memory_ids whose correction/check artifact is structurally linked
    cited: tuple[str, ...]  # explicit citations (untrusted until validated against `delivered`)
    tool_tokens: frozenset[str] = field(default_factory=frozenset)
    source: str = "synthetic"  # "tool_runtime" | "coder_engine" | "synthetic"


@dataclass
class Item:
    """One judged outcome: exposure + evidence + independent labels per delivered memory."""

    item_id: str
    provenance: str  # "real" | "synthetic"
    exposure: Exposure
    evidence: OutcomeEvidence
    labels: dict[str, Label]
    judge: str
    judged_at: str
    strategy_outputs: dict[str, list[str]] = field(default_factory=dict)


Strategy = Callable[[Exposure, OutcomeEvidence], list[str]]


def cited(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    """Citations restricted to refs actually delivered by this exposure (cross-scope ids are dropped)."""
    delivered = {ref.memory_id for ref in exposure.delivered}
    return [mid for mid in evidence.cited if mid in delivered]


def overlap_tokens(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    """Jaccard(lesson_tokens, tool_tokens) >= OVERLAP_TOKEN_THRESHOLD; deterministic tie order by memory_id."""
    out: list[str] = []
    for ref in sorted(exposure.delivered, key=lambda r: r.memory_id):
        union = ref.lesson_tokens | evidence.tool_tokens
        if not union:
            continue
        jaccard = len(ref.lesson_tokens & evidence.tool_tokens) / len(union)
        if jaccard >= OVERLAP_TOKEN_THRESHOLD:
            out.append(ref.memory_id)
    return out


def overlap_error_signature(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    """Nonempty normalized signature equality only (spec §2 grade table row AGAIN)."""
    if not evidence.error_signature:
        return []
    normalized_evidence = _normalize_signature(evidence.error_signature)
    if not normalized_evidence:
        return []
    out: list[str] = []
    for ref in sorted(exposure.delivered, key=lambda r: r.memory_id):
        if ref.error_signature and _normalize_signature(ref.error_signature) == normalized_evidence:
            out.append(ref.memory_id)
    return out


def recovery_linkage(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    """memory_ids in evidence.recovery_refs ∩ delivered; NEVER prose equality (spec §2 "string equality ... does not establish it")."""
    delivered = {ref.memory_id for ref in exposure.delivered}
    return [mid for mid in evidence.recovery_refs if mid in delivered]


def combine(strategies: list[Strategy], cap: int | None) -> Strategy:
    """Union in strategy order, dedupe, truncate to cap (None = unbounded)."""

    def _combined(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
        seen: list[str] = []
        for strategy in strategies:
            for memory_id in strategy(exposure, evidence):
                if memory_id not in seen:
                    seen.append(memory_id)
        return seen if cap is None else seen[:cap]

    return _combined


def grade_row(
    evidence: OutcomeEvidence,
    *,
    attributed: bool,
    memory_error_signature: str | None,
    recovered: bool,
    overlap_only: bool,
) -> GradeRow:
    """Ordered table from spec §2 "Review Admission and Grade Precedence"; EASY -> good_capped when overlap_only.

    Admission (step 1-2 of spec §2) is folded into the first two checks: no attributable
    application or no verified outcome both yield "no_review" before the grade table even
    considers the outcome's success/failure branch.
    """
    if not attributed or not evidence.verified:
        return "no_review"
    if not evidence.success:
        # AGAIN: verified failure repeats the same nonempty normalized error signature.
        if (
            memory_error_signature
            and evidence.error_signature
            and _normalize_signature(memory_error_signature) == _normalize_signature(evidence.error_signature)
        ):
            return "again"
        return "no_review"
    # From here evidence.success is True.
    if recovered:
        # EASY: verified success fixes the cited error through a verified recovery linkage;
        # capped to GOOD when the attribution came from an overlap heuristic, not a citation.
        return "good_capped" if overlap_only else "easy"
    if evidence.correction_count > 0:
        # HARD: verified success with one or more confirmed corrections.
        return "hard"
    if evidence.first_attempt and evidence.correction_count == 0:
        # GOOD: verified success on the first attempt with zero corrections.
        return "good"
    return "no_review"


def metrics(items: list[Item], strategy_name: str) -> dict[str, float]:
    """Precision, false_reinforcement, missed_attribution, collision_rate for one strategy's stored outputs.

    - precision: attributed memories labeled relevant / all attributed memories with a known label.
    - false_reinforcement: fraction of not_relevant memories for which the grade table would still
      fire a grade (i.e. reinforce a memory that was judged irrelevant).
    - missed_attribution: fraction of relevant memories the strategy failed to attribute.
    - collision_rate: fraction of items where >=2 (labeled) memories are attributed and exactly one
      of them is relevant.
    - 'unknown' labels are ignored for precision/missed/false-reinforcement but their count is reported.
    """
    overlap_only = strategy_name != "cited"
    attributed_count = 0
    true_positive = 0
    false_reinforcement_count = 0
    missed_count = 0
    relevant_total = 0
    not_relevant_total = 0
    unknown_attributed = 0
    unknown_count = 0
    collisions = 0

    for item in items:
        outputs = set(item.strategy_outputs.get(strategy_name, []))
        relevant_attributed_in_item = 0
        known_attributed_in_item = 0
        for ref in item.exposure.delivered:
            label = item.labels.get(ref.memory_id, "unknown")
            is_attributed = ref.memory_id in outputs
            if label == "unknown":
                unknown_count += 1
                if is_attributed:
                    unknown_attributed += 1
                continue
            if label == "relevant":
                relevant_total += 1
                if is_attributed:
                    true_positive += 1
                    attributed_count += 1
                    relevant_attributed_in_item += 1
                    known_attributed_in_item += 1
                else:
                    missed_count += 1
            else:  # not_relevant
                not_relevant_total += 1
                if is_attributed:
                    attributed_count += 1
                    known_attributed_in_item += 1
                    recovered = ref.memory_id in item.evidence.recovery_refs
                    grade = grade_row(
                        item.evidence,
                        attributed=True,
                        memory_error_signature=ref.error_signature,
                        recovered=recovered,
                        overlap_only=overlap_only,
                    )
                    if grade != "no_review":
                        false_reinforcement_count += 1
        if known_attributed_in_item >= 2 and relevant_attributed_in_item == 1:
            collisions += 1

    return {
        "precision": (true_positive / attributed_count) if attributed_count else 0.0,
        "false_reinforcement": (false_reinforcement_count / not_relevant_total) if not_relevant_total else 0.0,
        "missed_attribution": (missed_count / relevant_total) if relevant_total else 0.0,
        "collision_rate": (collisions / len(items)) if items else 0.0,
        "attributed_count": float(attributed_count),
        "true_positive": float(true_positive),
        "relevant_total": float(relevant_total),
        "not_relevant_total": float(not_relevant_total),
        "unknown_count": float(unknown_count),
        "unknown_attributed": float(unknown_attributed),
        "items_count": float(len(items)),
    }


def _ref_to_dict(ref: DeliveredRef) -> dict[str, Any]:
    return {
        "memory_id": ref.memory_id,
        "content_version": ref.content_version,
        "kind": ref.kind,
        "error_signature": ref.error_signature,
    }


def _ref_from_dict(data: dict[str, Any]) -> DeliveredRef:
    return DeliveredRef(
        memory_id=data["memory_id"],
        content_version=data["content_version"],
        kind=data["kind"],
        error_signature=data.get("error_signature"),
        lesson_tokens=frozenset(),
    )


def item_to_record(item: Item) -> dict[str, Any]:
    """Serialize an Item to the hash-only, transcript-free judgments.jsonl row shape."""
    return {
        "item_id": item.item_id,
        "provenance": item.provenance,
        "exposure": {
            "exposure_id": item.exposure.exposure_id,
            "attempt_or_turn_id": item.exposure.attempt_or_turn_id,
            "packed_sha256": item.exposure.packed_sha256,
            "delivered": [_ref_to_dict(ref) for ref in item.exposure.delivered],
        },
        "evidence": {
            "outcome_id": item.evidence.outcome_id,
            "verified": item.evidence.verified,
            "success": item.evidence.success,
            "first_attempt": item.evidence.first_attempt,
            "correction_count": item.evidence.correction_count,
            "error_signature": item.evidence.error_signature,
            "recovery_refs": list(item.evidence.recovery_refs),
            "cited": list(item.evidence.cited),
            "source": item.evidence.source,
        },
        "outcome_sha256": sha256_text(f"{item.exposure.exposure_id}:{item.evidence.outcome_id}"),
        "labels": dict(item.labels),
        "judge": item.judge,
        "judged_at": item.judged_at,
        "strategy_outputs": {name: list(values) for name, values in item.strategy_outputs.items()},
    }


def record_to_item(record: dict[str, Any]) -> Item:
    """Parse one judgments.jsonl row back into an Item (tokens are not persisted, restored empty)."""
    exposure = Exposure(
        exposure_id=record["exposure"]["exposure_id"],
        attempt_or_turn_id=record["exposure"]["attempt_or_turn_id"],
        delivered=tuple(_ref_from_dict(ref) for ref in record["exposure"]["delivered"]),
        packed_sha256=record["exposure"]["packed_sha256"],
    )
    evidence = OutcomeEvidence(
        outcome_id=record["evidence"]["outcome_id"],
        verified=record["evidence"]["verified"],
        success=record["evidence"]["success"],
        first_attempt=record["evidence"]["first_attempt"],
        correction_count=record["evidence"]["correction_count"],
        error_signature=record["evidence"].get("error_signature"),
        recovery_refs=tuple(record["evidence"].get("recovery_refs", [])),
        cited=tuple(record["evidence"].get("cited", [])),
        tool_tokens=frozenset(),
        source=record["evidence"]["source"],
    )
    return Item(
        item_id=record["item_id"],
        provenance=record["provenance"],
        exposure=exposure,
        evidence=evidence,
        labels=dict(record["labels"]),
        judge=record["judge"],
        judged_at=record["judged_at"],
        strategy_outputs={name: list(values) for name, values in record.get("strategy_outputs", {}).items()},
    )


def load_corpus(path: Path = SPIKE_DIR / "judgments.jsonl") -> list[Item]:
    """Parse JSONL -> Item (tuples/frozensets restored); validate 50 rows, no transcript fields present."""
    items: list[Item] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            record = json.loads(raw_line)
            forbidden = _TRANSCRIPT_FORBIDDEN_KEYS & set(record.keys())
            if forbidden:
                raise ValueError(f"{path}:{line_no} carries forbidden transcript field(s): {sorted(forbidden)}")
            items.append(record_to_item(record))
    if len(items) != 50:
        raise ValueError(f"expected 50 judged items in {path}, found {len(items)}")
    return items


def write_corpus(items: list[Item], path: Path = SPIKE_DIR / "judgments.jsonl") -> None:
    """Write items as hash-only JSONL rows (one item per line, deterministic key order)."""
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item_to_record(item), sort_keys=True) + "\n")


# Untrusted-vs-trusted outcome source table (spec §2 Review Admission step 2) — source line refs
# verified against the Codebase Contract anchors this task carries.
UNTRUSTED_SOURCES: tuple[dict[str, str], ...] = (
    {
        "source": "EpisodicMemoryMixin._safe_record_ask outcome=EpisodeOutcome.SUCCESS, importance=3",
        "ref": "core/memory/episodic/mixin.py:477,479",
        "why_untrusted": "hard-coded for every conversation; no verification of the response's correctness",
    },
    {
        "source": 'record_tool_episode success = getattr(tool_result, "success", True)',
        "ref": "core/memory/episodic/store.py:260",
        "why_untrusted": "a tool_result without a `success` attribute silently defaults to success",
    },
    {
        "source": 'record_tool_episode status = getattr(tool_result, "status", "success")',
        "ref": "core/memory/episodic/store.py:262",
        "why_untrusted": "same default-to-success gap for the outcome status mapping",
    },
    {
        "source": "ToolInvocation.status default",
        "ref": "core/memory/compaction/models.py:71",
        "why_untrusted": "ToolStatus.COMPLETED is the dataclass default, not an observed result",
    },
    {
        "source": "empty corrections list",
        "ref": "spec §2 step 2",
        "why_untrusted": "absence of a correction is not proof of a correct first attempt",
    },
    {
        "source": "CoderReview.fix_commits reachability check alone (no memory ids)",
        "ref": "core/flows/dev_loop/sdd_coder/engine.py:1476-1486",
        "why_untrusted": "proves a fix commit exists and is reachable, not that it applied any cited memory",
    },
    {
        "source": 'exposure text-marker `"[coder-feedback:" in context`',
        "ref": "core/flows/dev_loop/sdd_coder/engine.py:1488-1492",
        "why_untrusted": "binary with_feedback/without_feedback cohort flag, carries no memory ids",
    },
)

# Trusted-receipt adapter proposal (spec §3 G3 "propose the trusted-receipt adapter table").
TRUSTED_RECEIPT_ADAPTERS: tuple[dict[str, str], ...] = (
    {
        "source": "tool_runtime",
        "adapter": "runtime tool executor must supply an explicit success/failure with an error signature "
        "(when failed) and correction count observed across retries of the SAME tool call — never "
        "derived from getattr(...) defaults.",
    },
    {
        "source": "coder_engine",
        "adapter": "SddCoderEngine.record_review's fix-commit reachability check (engine.py:1476-1486) "
        "plus the review's relevant passed-check ids; a bare merge or zero fix_commits is NOT "
        "sufficient — completion must be paired with at least one relevant passed check.",
    },
)


def write_report(results: dict[str, Any], *, commands: list[str], limitations: list[str]) -> Path:
    """Write metrics.json (raw results) and REPORT.md (rendered gate report) to SPIKE_DIR."""
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    (SPIKE_DIR / "metrics.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str) + "\n")

    corpus = results.get("corpus", {})
    strategies = results.get("strategies", {})

    lines: list[str] = []
    lines.append("# S3 (TASK-3384) — Attribution Precision and Verified-Outcome Evidence Schema — Gate Report")
    lines.append("")
    lines.append("## Commands")
    lines.append("")
    lines.append("```")
    lines.extend(commands)
    lines.append("```")
    lines.append("")
    lines.append("## Corpus Provenance")
    lines.append("")
    lines.append(f"- Total judged items: {corpus.get('total', 0)}")
    lines.append(f"- Real traces: {corpus.get('real', 0)}")
    lines.append(f"- Synthetic (labeled, declared): {corpus.get('synthetic', 0)}")
    lines.append(f"- Judge: {corpus.get('judge', 'unknown')}")
    lines.append("")
    lines.append("## Metrics per strategy x cap")
    lines.append("")
    lines.append(
        "| Strategy | Cap | Precision | False reinforcement | Missed attribution | Collision rate | Unknown labels |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for strategy_name, by_cap in strategies.items():
        for cap_key, row in by_cap.items():
            lines.append(
                f"| {strategy_name} | {cap_key} | {row['precision']:.3f} | {row['false_reinforcement']:.3f} | "
                f"{row['missed_attribution']:.3f} | {row['collision_rate']:.3f} | {int(row['unknown_count'])} |"
            )
    lines.append("")
    lines.append("## Untrusted-vs-Trusted Outcome Sources (spec §2 Review Admission step 2)")
    lines.append("")
    lines.append("### Untrusted (never sufficient alone)")
    lines.append("")
    lines.append("| Source | Line ref | Why untrusted |")
    lines.append("|---|---|---|")
    for row in UNTRUSTED_SOURCES:
        lines.append(f"| {row['source']} | {row['ref']} | {row['why_untrusted']} |")
    lines.append("")
    lines.append("### Proposed trusted-receipt adapters")
    lines.append("")
    lines.append("| Source | Adapter |")
    lines.append("|---|---|")
    for row in TRUSTED_RECEIPT_ADAPTERS:
        lines.append(f"| {row['source']} | {row['adapter']} |")
    lines.append("")
    lines.append("## Pass/Fail vs U3")
    lines.append("")
    lines.append(
        "- U3 (the target precision/false-reinforcement rubric) is an owner acceptance decision "
        "(spec §8 U3) — this gate reports the measured numbers above; PASS/FAIL is PENDING until "
        "the owner sets a target in amendment.md."
    )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for limitation in limitations:
        lines.append(f"- {limitation}")
    lines.append("")
    lines.append("See `amendment.md` in this directory for the proposed spec freeze.")

    report_path = SPIKE_DIR / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path
