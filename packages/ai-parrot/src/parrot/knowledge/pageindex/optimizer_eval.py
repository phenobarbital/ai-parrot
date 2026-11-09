"""Evaluation harness for the PageIndex tree optimizer (FEAT-846 M6). Numbers only, never node titles.

Usage::

    python -m parrot.knowledge.pageindex.optimizer_eval <pdf|dir>... [--llm provider:model] [--out DIR]

Each PDF is imported into a temporary storage directory with ``optimize_on_import=False`` (layout structure, no
summaries), then optimized with ``optimize(apply=True)``. The report holds counts, token statistics and the PDF
file stem only, so a report over a non-redistributable PDF can be quoted.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from pydantic import BaseModel, PrivateAttr

from parrot.knowledge.pageindex import PageIndexToolkit
from parrot.knowledge.pageindex.optimizer import OptimizerSettings, owned_tokens
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger(__name__)
DEFAULT_OUT = Path("artifacts/logs/optimizer_eval")
_TREE_NAME = "optimizer_eval"
_MIN_TREES_FOR_SUGGESTION = 3


class EvalSettings(BaseModel):
    """Optimizer settings under evaluation."""

    target_leaf_tokens: int
    min_leaf_tokens: int
    llm: Optional[str] = None


class TreeMetrics(BaseModel):
    """Metrics for one evaluated PDF: numbers and the file-stem label only, never a node title."""

    label: str
    pages: Optional[int]
    nodes_before: int
    nodes_after: int
    leaves_before: int
    leaves_after: int
    leaf_tokens_p50: int
    leaf_tokens_p90: int
    leaf_tokens_max: int
    leaves_over_target_before: int
    leaves_over_target_after: int
    key_items: int
    summary_words_mean: float
    llm_calls: int
    seconds: float
    llm_heading_splits: int

    # Owned tokens of every leaf of the layout-built (pre-optimizer) tree; feeds the suggested target and is never
    # serialized into the report.
    _layout_leaf_tokens: list[int] = PrivateAttr(default_factory=list)


class EvalReport(BaseModel):
    """Corpus evaluation report."""

    created_at: str
    settings: EvalSettings
    results: list[TreeMetrics]
    suggested_target_leaf_tokens: Optional[int]

    # Where evaluate_corpus wrote the report; not serialized.
    _path: Optional[Path] = PrivateAttr(default=None)


def _percentile(values: Sequence[int], q: float) -> float:
    """Return the linearly interpolated ``q`` percentile (0-100) of ``values``; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _round_100(value: float) -> int:
    """Round half up to the nearest multiple of 100."""
    return int(math.floor(value / 100.0 + 0.5)) * 100


def _leaf_tokens(structure: list[dict[str, Any]], revisions: dict[Any, Any]) -> list[int]:
    """Owned tokens of every revision-backed leaf of ``structure``."""
    tokens: list[int] = []
    for node in structure_to_list(structure):
        if node.get("nodes"):
            continue
        revision = revisions.get((node.get("doc_id"), node.get("revision")))
        if revision is not None:
            tokens.append(owned_tokens(node, revision))
    return tokens


def _count_leaves(structure: list[dict[str, Any]]) -> int:
    """Number of leaf nodes in ``structure``."""
    return sum(1 for node in structure_to_list(structure) if not node.get("nodes"))


def _summary_words_mean(structure: list[dict[str, Any]]) -> float:
    """Mean word count over the nodes that carry a non-empty summary; 0.0 when none does."""
    counts = [
        len(str(node.get("summary")).split()) for node in structure_to_list(structure) if node.get("summary")
    ]
    return round(sum(counts) / len(counts), 3) if counts else 0.0


def _key_items(structure: list[dict[str, Any]]) -> int:
    """Total number of key items across ``structure``."""
    return sum(len(node.get("key_items") or []) for node in structure_to_list(structure))


def _pages(revisions: dict[Any, Any]) -> Optional[int]:
    """Page count recorded on the imported revision, when known."""
    for revision in revisions.values():
        pages = getattr(getattr(revision, "source", None), "pages", None)
        if pages is not None:
            return int(pages)
    return None


def _make_adapter(llm: Optional[str]) -> Optional[Any]:
    """Build a PageIndex LLM adapter from a ``provider:model`` spec; ``None`` keeps the run deterministic."""
    if not llm:
        return None
    from parrot.clients.factory import LLMFactory
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

    _, model = LLMFactory.parse_llm_string(llm)
    return PageIndexLLMAdapter(client=LLMFactory.create(llm), model=model)


async def evaluate_pdf(pdf: Path, *, settings: EvalSettings, storage_dir: Path) -> TreeMetrics:
    """Import ``pdf`` into ``storage_dir`` (optimize_on_import=False), then optimize(apply=True); measure."""
    toolkit = PageIndexToolkit(
        adapter=_make_adapter(settings.llm),
        storage_dir=storage_dir,
        scan_injection=False,
        optimize_on_import=False,
        optimizer_settings=OptimizerSettings(
            target_leaf_tokens=settings.target_leaf_tokens,
            min_leaf_tokens=settings.min_leaf_tokens,
            llm_passes=settings.llm is not None,
        ),
    )
    started = time.perf_counter()
    await toolkit.create_tree(_TREE_NAME)
    await toolkit.import_pdf(_TREE_NAME, str(pdf), with_summaries=False, structure_mode="layout")

    before = list((await toolkit.get_tree(_TREE_NAME)).get("structure") or [])
    before_revisions = toolkit._revisions_for(_TREE_NAME, before)
    layout_leaf_tokens = await asyncio.to_thread(_leaf_tokens, before, before_revisions)
    leaves_before = _count_leaves(before)

    report = await toolkit.optimize(_TREE_NAME, apply=True, llm_passes=settings.llm is not None)
    seconds = round(time.perf_counter() - started, 3)
    if report.get("errors"):
        logger.warning("optimizer reported %d error(s) for %s", len(report["errors"]), pdf.stem)

    after = list((await toolkit.get_tree(_TREE_NAME)).get("structure") or [])
    after_revisions = toolkit._revisions_for(_TREE_NAME, after)
    leaf_tokens = await asyncio.to_thread(_leaf_tokens, after, after_revisions)

    metrics = TreeMetrics(
        label=pdf.stem,
        pages=_pages(after_revisions or before_revisions),
        nodes_before=int(report.get("nodes_before", 0)),
        nodes_after=int(report.get("nodes_after", 0)),
        leaves_before=leaves_before,
        leaves_after=_count_leaves(after),
        leaf_tokens_p50=int(round(_percentile(leaf_tokens, 50))),
        leaf_tokens_p90=int(round(_percentile(leaf_tokens, 90))),
        leaf_tokens_max=max(leaf_tokens, default=0),
        leaves_over_target_before=int(report.get("leaves_over_target_before", 0)),
        leaves_over_target_after=int(report.get("leaves_over_target_after", 0)),
        key_items=_key_items(after),
        summary_words_mean=_summary_words_mean(after),
        llm_calls=int(report.get("llm_calls_made", 0)),
        seconds=seconds,
        llm_heading_splits=sum(1 for action in report.get("expanded") or [] if action.get("source") == "llm"),
    )
    metrics._layout_leaf_tokens = layout_leaf_tokens
    return metrics


def suggest_target(results: Sequence[TreeMetrics]) -> Optional[int]:
    """p75 of the layout-built leaf tokens of all trees, rounded to 100; ``None`` with fewer than three trees."""
    if len(results) < _MIN_TREES_FOR_SUGGESTION:
        return None
    pooled = [tokens for result in results for tokens in result._layout_leaf_tokens]
    if not pooled:
        return None
    return _round_100(_percentile(pooled, 75))


def _write_report(path: Path, text: str) -> None:
    """Create the report directory and write ``text`` to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def evaluate_corpus(pdfs: list[Path], *, settings: EvalSettings, out_dir: Path = DEFAULT_OUT) -> EvalReport:
    """Writes ``optimizer_eval-<ts>.json``; suggested target = p75 of post-layout leaf tokens rounded to 100."""
    results: list[TreeMetrics] = []
    with tempfile.TemporaryDirectory(prefix="optimizer_eval-") as tmp:
        for index, pdf in enumerate(pdfs):
            results.append(await evaluate_pdf(pdf, settings=settings, storage_dir=Path(tmp) / f"{index:03d}"))
    created_at = datetime.now(timezone.utc)
    report = EvalReport(
        created_at=created_at.isoformat(),
        settings=settings,
        results=results,
        suggested_target_leaf_tokens=suggest_target(results),
    )
    path = out_dir / f"optimizer_eval-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    await asyncio.to_thread(_write_report, path, report.model_dump_json(indent=2) + "\n")
    report._path = path
    logger.info("Wrote optimizer evaluation report to %s", path)
    return report


def tuned_target(report: EvalReport, current: OptimizerSettings) -> Optional[int]:
    """Suggestion inside [2*min_leaf_tokens, 2*target_leaf_tokens], else None."""
    s = report.suggested_target_leaf_tokens
    if s is None:
        return None
    return s if 2 * current.min_leaf_tokens <= s <= 2 * current.target_leaf_tokens else None


def _expand_inputs(inputs: Sequence[str]) -> list[Path]:
    """Expand directories to their ``*.pdf`` files (sorted); keep files as given."""
    pdfs: list[Path] = []
    for value in inputs:
        path = Path(value)
        if path.is_dir():
            pdfs.extend(sorted(child for child in path.glob("*.pdf") if child.is_file()))
        else:
            pdfs.append(path)
    return pdfs


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m parrot.knowledge.pageindex.optimizer_eval <pdf|dir>...``"""
    defaults = OptimizerSettings()
    parser = argparse.ArgumentParser(description="Evaluate the PageIndex tree optimizer over PDFs.")
    parser.add_argument("inputs", nargs="+", metavar="PDF_OR_DIR")
    parser.add_argument("--target-leaf-tokens", type=int, default=defaults.target_leaf_tokens)
    parser.add_argument("--min-leaf-tokens", type=int, default=defaults.min_leaf_tokens)
    parser.add_argument("--llm", default=None, help="provider:model; default none (deterministic run)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    pdfs = _expand_inputs(args.inputs)
    missing = [str(pdf) for pdf in pdfs if not pdf.is_file()]
    if missing or not pdfs:
        parser.error(f"no PDF found: {', '.join(missing) or ' '.join(args.inputs)}")

    settings = EvalSettings(
        target_leaf_tokens=args.target_leaf_tokens, min_leaf_tokens=args.min_leaf_tokens, llm=args.llm
    )
    report = asyncio.run(evaluate_corpus(pdfs, settings=settings, out_dir=args.out))
    sys.stdout.write(f"report: {report._path}\n")
    sys.stdout.write(f"tuned_target: {tuned_target(report, defaults)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
