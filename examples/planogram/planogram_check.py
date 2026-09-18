#!/usr/bin/env python3
"""Autonomous planogram compliance check (FEAT-565) — thin CLI over ``plancheck.pipeline.run_check``.

Example:
    python examples/planogram/planogram_check.py --catalog my_catalog.json --output results/run1
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from plancheck.models import Settings
from plancheck.pipeline import run_check
from plancheck.reference import emit_catalog_template, load_planogram
from plancheck.vision import VisionError

logger = logging.getLogger("planogram_check")
HERE = Path(__file__).resolve().parent
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})
EXIT_OK, EXIT_INVALID, EXIT_ERRORS = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors exit 1 (argparse's default 2 means 'completed with errors' here)."""

    def error(self, message: str) -> NoReturn:
        logger.error("%s: %s", self.prog, message)
        raise SystemExit(EXIT_INVALID)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser — option set fixed by spec §2 'User-facing behaviour'."""
    parser = _Parser(prog="planogram_check", description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--images-dir", type=Path, default=None, help=f"Photo directory (default: {HERE / 'images'})")
    source.add_argument("--images", type=Path, nargs="+", default=None, help="Explicit photo files")
    parser.add_argument("--planogram", type=Path, default=HERE / "planogram_page1.json")
    parser.add_argument("--catalog", type=Path, default=None, help="REQUIRED for a run: part-number ↔ descriptor catalog")
    parser.add_argument("--output", type=Path, default=None, help="NEW directory for the artefacts (must not exist)")
    parser.add_argument("--llm", default="google:gemini-3.8-flash", help="provider:model for identification")
    parser.add_argument("--ocr-llm", default=None, help="provider:model for the price fallback (default: --llm)")
    parser.add_argument("--base-url", default=None, help="Base URL for local OpenAI-compatible servers")
    parser.add_argument("--prices", type=Path, default=None, help="Optional {sku: price} JSON → price compliance")
    parser.add_argument("--roi", type=float, nargs=4, metavar=("L", "T", "R", "B"), default=None)
    parser.add_argument("--verify-pass", action=argparse.BooleanOptionalAction, default=None,
                        help="Closed-set verification pass (default: on for cloud, off for local backends)")
    parser.add_argument("--no-marks", dest="marks", action="store_false", help="Send strips without Set-of-Marks outlines")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--cache-dir", type=Path, default=HERE / "results" / ".plancheck_cache")
    parser.add_argument("--visit-id", default="visit")
    parser.add_argument("--emit-catalog-template", type=Path, default=None, metavar="PATH",
                        help="Write a catalog skeleton for the planogram and exit")
    return parser


def _discover_images(args: argparse.Namespace) -> list[Path]:
    """Resolve the photo list. Raises ``ValueError``/``FileNotFoundError`` on a missing or empty selection."""
    if args.images is not None:
        images = [Path(p) for p in args.images]
        for p in images:
            if not p.exists():
                raise FileNotFoundError(f"Image file not found: {p}")
        return sorted(images)
    
    # Use directory
    dir_path = args.images_dir if args.images_dir is not None else HERE / "images"
    if not dir_path.exists():
        raise FileNotFoundError(f"Images directory not found: {dir_path}")
    
    images = [f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        raise ValueError(f"No images found in directory: {dir_path}")
    
    return sorted(images)


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Validate run arguments and build ``Settings`` with absolute paths. Raises ``ValueError``."""
    if args.catalog is None:
        raise ValueError(
            "--catalog is required. Create one with --emit-catalog-template <path>, fill it in, then pass it."
        )
    if args.output is None:
        raise ValueError("--output <new directory> is required.")
    
    # Validate ROI
    if args.roi is not None:
        L, T, R, B = args.roi
        if not (0 <= L < R <= 1 and 0 <= T < B <= 1):
            raise ValueError("--roi must satisfy 0 <= L < R <= 1 and 0 <= T < B <= 1")
    
    # Validate concurrency
    if not (1 <= args.concurrency <= 16):
        raise ValueError("--concurrency must be between 1 and 16")
    
    # Build absolute paths
    images = [str(p.expanduser().resolve()) for p in _discover_images(args)]
    planogram = str(args.planogram.expanduser().resolve())
    catalog = str(args.catalog.expanduser().resolve())
    output = str(args.output.expanduser().resolve())
    cache_dir = str(args.cache_dir.expanduser().resolve())
    prices = str(args.prices.expanduser().resolve()) if args.prices else None
    
    return Settings(
        images=images,
        planogram=planogram,
        catalog=catalog,
        output=output,
        cache_dir=cache_dir,
        prices=prices,
        llm=args.llm,
        ocr_llm=args.ocr_llm,
        base_url=args.base_url,
        roi=tuple(args.roi) if args.roi else None,
        verify_pass=args.verify_pass,
        marks=args.marks,
        concurrency=args.concurrency,
        visit_id=args.visit_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        0 complete · 2 complete with recorded model/OCR errors (results written) · 1 invalid input.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # _Parser.error → 1 ; --help → 0
        return int(exc.code or 0)
    try:
        if args.emit_catalog_template is not None:
            planogram = load_planogram(args.planogram.expanduser().resolve())
            emit_catalog_template(planogram, args.emit_catalog_template.expanduser().resolve())
            logger.info("Catalog template written to %s", args.emit_catalog_template)
            return EXIT_OK
        settings = _settings_from_args(args)
        report = asyncio.run(run_check(settings))
    except (FileExistsError, FileNotFoundError, ValueError, VisionError) as exc:
        logger.error("Invalid input: %s", exc)
        return EXIT_INVALID
    
    # Log summary
    logger.info(
        "Strict %%: %.2f, Lenient %%: %.2f, Coverage: %.2f, Output: %s",
        report.compliance.strict_pct or 0,
        report.compliance.lenient_pct or 0,
        report.compliance.coverage,
        settings.output,
    )
    
    # Handle errors
    if report.run.errors:
        for error in report.run.errors:
            logger.warning("Error: %s", error)
        return EXIT_ERRORS
    
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
