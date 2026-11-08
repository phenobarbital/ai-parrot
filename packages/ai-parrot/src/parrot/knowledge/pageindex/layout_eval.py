"""Deterministic evaluation of layout-built PDF structure against LLM-built reference trees (FEAT-845)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.builder import build_page_index
from parrot.knowledge.pageindex.layout_structure import CandidateScore
from parrot.knowledge.pageindex.segments import _titles_match, normalize_title

logger = logging.getLogger(__name__)
DEFAULT_OUT = Path("artifacts/logs/layout_eval")


class EvalPair(BaseModel):
    """A PDF and reference-tree pair to evaluate."""

    label: str
    pdf: Path
    reference: Path
    internal: bool = False


class EvalResult(BaseModel):
    """Metrics from evaluating one PDF/reference pair."""

    label: str
    internal: bool
    pages: int
    structure_source: str
    chosen_confidence: Optional[float]
    candidates: list[CandidateScore]
    reference_nodes: int
    layout_nodes: int
    recall_top: float
    recall_all: float
    page_agreement: float
    seconds: float
    unmatched_titles: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    """Complete deterministic layout-evaluation report."""

    created_at: str
    min_confidence: float
    recall_floor: float
    results: list[EvalResult]
    suggested_min_confidence: Optional[float]


def _walk(nodes: Sequence[dict[str, Any]], depth: int = 1) -> list[tuple[int, dict[str, Any]]]:
    """Return ``(depth, node)`` pairs in pre-order."""
    out: list[tuple[int, dict[str, Any]]] = []
    for node in nodes:
        out.append((depth, node))
        out.extend(_walk(node.get("nodes") or [], depth + 1))
    return out


def _pair_score(result: EvalResult) -> float:
    """Return the best candidate confidence used for threshold selection."""
    return max((candidate.confidence for candidate in result.candidates), default=0.0)


def _floor05(value: float) -> float:
    """Round a value down to a 0.05 boundary."""
    return round(math.floor(round(value / 0.05, 9)) * 0.05, 2)


async def evaluate_pair(pair: EvalPair, *, min_confidence: float) -> EvalResult:
    """Build a layout-only PageIndex tree and compare it with a reference tree."""
    started = time.perf_counter()
    built = await build_page_index(
        str(pair.pdf),
        adapter=None,
        options={
            "structure_mode": "layout",
            "structure_min_confidence": min_confidence,
            "if_add_node_summary": "no",
            "if_add_doc_description": "no",
        },
    )
    seconds = round(time.perf_counter() - started, 3)
    reference = json.loads(pair.reference.read_text(encoding="utf-8"))["structure"]

    reference_nodes = [
        (depth, node) for depth, node in _walk(reference) if normalize_title(str(node.get("title", ""))) != "preface"
    ]
    layout_nodes = _walk(built["structure"])
    matches: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    unmatched_titles: list[str] = []

    for depth, reference_node in reference_nodes:
        reference_title = str(reference_node.get("title", ""))
        normalized_reference = normalize_title(reference_title)
        match = next(
            (
                layout_node
                for _, layout_node in layout_nodes
                if normalize_title(str(layout_node.get("title", ""))) == normalized_reference
            ),
            None,
        )
        if match is None:
            match = next(
                (
                    layout_node
                    for _, layout_node in layout_nodes
                    if _titles_match(reference_title, str(layout_node.get("title", "")))
                ),
                None,
            )
        if match is None:
            if not pair.internal:
                unmatched_titles.append(reference_title)
            continue
        matches.append((depth, reference_node, match))

    top_reference_count = sum(depth == 1 for depth, _ in reference_nodes)
    top_match_count = sum(depth == 1 for depth, _, _ in matches)
    recall_top = top_match_count / top_reference_count if top_reference_count else 0.0
    recall_all = len(matches) / len(reference_nodes) if reference_nodes else 0.0
    agreed_pages = sum(
        abs(int(reference_node["start_index"]) - int(layout_node["start_index"])) <= 1
        for _, reference_node, layout_node in matches
    )
    page_agreement = agreed_pages / len(matches) if matches else 0.0
    report = built["structure_report"]

    return EvalResult(
        label=pair.label,
        internal=pair.internal,
        pages=len(built["_pages"]),
        structure_source=built["structure_source"],
        chosen_confidence=report.get("confidence"),
        candidates=[CandidateScore.model_validate(candidate) for candidate in report.get("candidates", [])],
        reference_nodes=len(reference_nodes),
        layout_nodes=len(layout_nodes),
        recall_top=recall_top,
        recall_all=recall_all,
        page_agreement=page_agreement,
        seconds=seconds,
        unmatched_titles=unmatched_titles,
    )


def suggest_threshold(results: Sequence[EvalResult], *, recall_floor: float = 0.8) -> Optional[float]:
    """Suggest a threshold that separates pairs above and below the recall floor."""
    good_scores = [_pair_score(result) for result in results if result.recall_all >= recall_floor]
    if not good_scores:
        return None

    bad_scores = [_pair_score(result) for result in results if result.recall_all < recall_floor]
    min_good = min(good_scores)
    if not bad_scores:
        return _floor05(min_good)

    threshold = _floor05(max(bad_scores) + 0.05)
    return threshold if threshold <= min_good else None


def main(argv: Optional[list[str]] = None) -> int:
    """Run layout evaluation and write timestamped JSON and markdown reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", required=True, metavar="LABEL=PDF::TREE")
    parser.add_argument("--internal", action="append", default=[], metavar="LABEL")
    parser.add_argument("--min-confidence", type=float, default=0.6)
    parser.add_argument("--recall-floor", type=float, default=0.8)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    internal_labels = set(args.internal)
    pairs: list[EvalPair] = []
    for value in args.pair:
        try:
            label, paths = value.split("=", 1)
            pdf, reference = paths.split("::", 1)
        except ValueError:
            parser.error(f"malformed --pair {value!r}; expected LABEL=PDF::TREE")
        if not label or not pdf or not reference:
            parser.error(f"malformed --pair {value!r}; expected LABEL=PDF::TREE")
        pairs.append(
            EvalPair(
                label=label,
                pdf=Path(pdf),
                reference=Path(reference),
                internal=label in internal_labels,
            )
        )

    async def evaluate_all() -> list[EvalResult]:
        results: list[EvalResult] = []
        for pair in pairs:
            results.append(await evaluate_pair(pair, min_confidence=args.min_confidence))
        return results

    results = asyncio.run(evaluate_all())
    created_at = datetime.now(timezone.utc)
    report = EvalReport(
        created_at=created_at.isoformat(),
        min_confidence=args.min_confidence,
        recall_floor=args.recall_floor,
        results=results,
        suggested_min_confidence=suggest_threshold(results, recall_floor=args.recall_floor),
    )

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    json_path = args.out / f"{stamp}.json"
    markdown_path = args.out / f"{stamp}.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    markdown_lines = [
        "# Layout evaluation",
        "",
        f"Created: {report.created_at}",
        f"Minimum confidence: {report.min_confidence}",
        "",
        "| Pair | Pages | Source | Chosen confidence | Candidate confidences | Reference nodes | Layout nodes | Recall top | Recall all | Page agreement | Seconds |",
        "|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        candidate_confidences = ", ".join(
            f"{candidate.source}={candidate.confidence:.3f}" for candidate in result.candidates
        )
        chosen_confidence = "n/a" if result.chosen_confidence is None else f"{result.chosen_confidence:.3f}"
        markdown_lines.append(
            f"| {result.label} | {result.pages} | {result.structure_source} | {chosen_confidence} | "
            f"{candidate_confidences or 'none'} | {result.reference_nodes} | {result.layout_nodes} | "
            f"{result.recall_top:.3f} | {result.recall_all:.3f} | {result.page_agreement:.3f} | "
            f"{result.seconds:.3f} |"
        )
        if not result.internal and result.unmatched_titles:
            markdown_lines.extend(["", f"Unmatched titles ({result.label}):"])
            markdown_lines.extend(f"- {title}" for title in result.unmatched_titles)
    markdown_lines.extend(["", f"Suggested minimum confidence: {report.suggested_min_confidence}", ""])
    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    logger.info("Wrote layout evaluation JSON report to %s", json_path)
    logger.info("Wrote layout evaluation markdown report to %s", markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
