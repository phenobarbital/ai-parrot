"""Offline-default CLI for the FEAT-580 LSP pilot (spec §3 Module 5).

``python -m benchmarks.sdd_lsp --manifest <path> --output-dir <dir>``
validates the manifest and previews the planned attempt matrix WITHOUT
ever launching a subprocess -- the runner
(:func:`benchmarks.sdd_lsp.runner.run_pilot`) is called only when
``--live`` is explicitly passed, alongside a complete manifest (spec §3
M5: "No live default; ``--live`` and a complete manifest are required").
A report produced without ``--live`` stays ``synthetic`` and cannot
satisfy the live adoption gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from benchmarks.sdd_lsp.models import PilotManifest, PriceBook
from benchmarks.sdd_lsp.report import build_report_document, write_reports
from benchmarks.sdd_lsp.runner import build_attempt_matrix, run_pilot

__all__ = ("build_arg_parser", "main")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.sdd_lsp",
        description="FEAT-580 LSP pilot: plan, run, and evaluate the five-arm evaluation.",
    )
    parser.add_argument("--manifest", required=True, type=Path, help="Path to a PilotManifest JSON file.")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Directory for per-attempt work and the written reports."
    )
    parser.add_argument(
        "--prices",
        type=Path,
        default=None,
        help="Optional PriceBook JSON file for cost-based gate evaluation (default: empty/unpriced).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Actually launch the manifest's configured seats via the runner. Without this flag, "
        "the manifest is only validated and its planned matrix is previewed -- no subprocess is ever launched.",
    )
    return parser


def _load_manifest(path: Path) -> PilotManifest:
    return PilotManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _load_prices(path: Path | None) -> PriceBook:
    if path is None:
        return PriceBook()
    return PriceBook.model_validate_json(path.read_text(encoding="utf-8"))


async def _amain(argv: list[str] | None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    manifest = _load_manifest(args.manifest)
    prices = _load_prices(args.prices)

    if not args.live:
        matrix = build_attempt_matrix(manifest)
        print(
            f"[offline] manifest valid: {len(matrix)} planned attempts across {len(manifest.arms)} arms "
            f"({manifest.repetitions} repetitions x {len(manifest.task_ids)} tasks). "
            "No subprocess was launched. Pass --live to actually run the pilot."
        )
        return 0

    report = await run_pilot(manifest, args.output_dir)
    document = build_report_document(report, prices)
    json_path, md_path = write_reports(document, args.output_dir)
    gate = document["gate"]
    print(f"decision: {gate['decision']}")
    print(f"reasons: {json.dumps(gate['reasons'])}")
    print(f"reports written: {json_path}, {md_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    sys.exit(main())
