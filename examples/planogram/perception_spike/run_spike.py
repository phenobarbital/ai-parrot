"""Perception spike CLI (FEAT-574): measure propose_shapes on a private sample + synthetic cases."""

from __future__ import annotations

import argparse
import datetime
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile, propose_shapes

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate  # noqa: E402  (sibling module; examples/ is not a package)

logger = logging.getLogger("perception_spike")

#: The spike's HYPOTHESIS for ProductOnShelves (fractions of the evaluated image). Unvalidated until the gates pass.
CANDIDATE_PROFILES: List[ShapeProfile] = [
    PRICE_TAG_PROFILE,
    ShapeProfile(
        name="product_body",
        kind="product",
        min_width=0.06,
        max_width=0.30,
        min_height=0.08,
        max_height=0.45,
        min_aspect=0.5,
        max_aspect=2.5,
        polarity="edge",
        min_rectangularity=0.70,
        min_contrast_std=5.0,
    ),
    ShapeProfile(
        name="product_box",
        kind="box",
        min_width=0.04,
        max_width=0.20,
        min_height=0.05,
        max_height=0.25,
        min_aspect=0.4,
        max_aspect=2.0,
        polarity="edge",
        min_rectangularity=0.80,
        min_contrast_std=5.0,
    ),
    ShapeProfile(
        name="backlit_zone",
        kind="backlit",
        min_width=0.40,
        max_width=1.0,
        min_height=0.06,
        max_height=0.35,
        min_aspect=1.5,
        max_aspect=12.0,
        polarity="bright",
        min_rectangularity=0.80,
        min_contrast_std=5.0,
        thresholds=(200, 220, 240),
    ),
    ShapeProfile(
        name="electronic_tag",
        kind="price_tag",
        min_width=0.03,
        max_width=0.12,
        min_height=0.02,
        max_height=0.08,
        min_aspect=1.2,
        max_aspect=4.0,
        polarity="bright",
    ),
]

_W, _H = 1600, 1200
_WALL = (60, 60, 60)
_FIXTURE = (300, 1300)  # x-span of the target fixture in the synthetic scenes


def _draw_product(img: np.ndarray, x: int, y_bottom: int, w: int, h: int) -> Tuple[int, int, int, int]:
    """Low-contrast product body with a darker outline standing on a board; returns its box."""
    x2, y1 = x + w, y_bottom - h
    cv2.rectangle(img, (x, y1), (x2, y_bottom), (95, 95, 95), -1)
    cv2.rectangle(img, (x, y1), (x2, y_bottom), (25, 25, 25), 3)
    return x, y1, x2, y_bottom


def _draw_tag(img: np.ndarray, x: int, y: int, w: int = 110, h: int = 40) -> Tuple[int, int, int, int]:
    """Bright price label with a dark text stroke; returns its box."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (245, 245, 245), -1)
    cv2.line(img, (x + 8, y + h // 2), (x + w - 8, y + h // 2), (20, 20, 20), 3)
    return x, y, x + w, y + h


def _scene(
    *, with_anchors: bool, distractors: bool, crop_right: Optional[int] = None
) -> Tuple[np.ndarray, List["evaluate.AnnotatedObject"]]:
    """Draw a two-shelf fixture; annotations are produced by the same draw calls (never hand-typed)."""
    img = np.full((_H, _W, 3), _WALL, dtype=np.uint8)
    objects: List[evaluate.AnnotatedObject] = []
    if with_anchors:
        cv2.rectangle(img, (_FIXTURE[0], 60), (_FIXTURE[1], 230), (250, 250, 250), -1)
        cv2.putText(img, "BRAND", (_FIXTURE[0] + 350, 180), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (40, 40, 200), 8)
        objects.append(evaluate.AnnotatedObject(id="backlit", kind="backlit", box=(_FIXTURE[0], 60, _FIXTURE[1], 230)))
    for row, board_y in enumerate((650, 1000)):
        cv2.rectangle(img, (_FIXTURE[0], board_y), (_FIXTURE[1], board_y + 14), (140, 140, 140), -1)
        for col in range(3):
            x = _FIXTURE[0] + 60 + col * 320
            box = _draw_product(img, x, board_y - 4, 220, 260)
            objects.append(evaluate.AnnotatedObject(id=f"p{row}{col}", kind="product", box=box, slot_target=True))
            if with_anchors:
                tag = _draw_tag(img, x + 50, board_y + 20)
                objects.append(evaluate.AnnotatedObject(id=f"t{row}{col}", kind="price_tag", box=tag))
    if distractors:
        for row, board_y in enumerate((650, 1000)):
            box = _draw_product(img, 40, board_y - 4, 200, 240)
            objects.append(evaluate.AnnotatedObject(id=f"d{row}", kind="product", box=box, membership="off_fixture"))
    if crop_right is not None:
        img = np.ascontiguousarray(img[:, :crop_right])
        kept: List[evaluate.AnnotatedObject] = []
        for obj in objects:
            x1, y1, x2, y2 = obj.box
            if x1 >= crop_right:
                continue
            clipped = (x1, y1, min(x2, crop_right), y2)
            visible = (clipped[2] - x1) / max(1, x2 - x1)
            kept.append(obj.model_copy(update={"box": clipped, "slot_target": obj.slot_target and visible >= 0.5}))
        objects = kept
    return img, objects


def synthetic_cases() -> Dict[str, Tuple[np.ndarray, "evaluate.PhotoAnnotation"]]:
    """Drawn images + generated annotations: full_wall, partial_shelf, absent_anchors, adjacent_fixture."""
    specs = {
        "full_wall": ({"with_anchors": True, "distractors": False}, ["full_view"]),
        "partial_shelf": ({"with_anchors": True, "distractors": False, "crop_right": 1100}, ["partial_view"]),
        "absent_anchors": ({"with_anchors": False, "distractors": False}, ["absent_anchors"]),
        "adjacent_fixture": ({"with_anchors": True, "distractors": True}, ["adjacent_fixture"]),
    }
    cases: Dict[str, Tuple[np.ndarray, evaluate.PhotoAnnotation]] = {}
    for name, (kwargs, conditions) in specs.items():
        img, objects = _scene(**kwargs)
        annotation = evaluate.PhotoAnnotation(
            image=f"synthetic_{name}", image_size=(img.shape[1], img.shape[0]), conditions=conditions, objects=objects
        )
        cases[name] = (img, annotation)
    return cases


def load_sample(
    photos_dir: Optional[Path], annotations_dir: Optional[Path]
) -> List[Tuple[np.ndarray, "evaluate.PhotoAnnotation"]]:
    """Pairs (image, annotation) by file stem. Missing dirs or no pairs -> [] (never raises)."""
    if not photos_dir or not annotations_dir or not photos_dir.is_dir() or not annotations_dir.is_dir():
        logger.info("No private sample supplied (0 photos).")
        return []
    pairs: List[Tuple[np.ndarray, evaluate.PhotoAnnotation]] = []
    skipped = 0
    for ann_path in sorted(annotations_dir.glob("*.json")):
        photo = next(
            (p for p in photos_dir.glob(f"{ann_path.stem}.*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")), None
        )
        if photo is None:
            skipped += 1
            continue
        try:
            annotation = evaluate.PhotoAnnotation.model_validate(json.loads(ann_path.read_text()))
            image = cv2.imread(str(photo), cv2.IMREAD_COLOR)
        except Exception:  # noqa: BLE001 - a broken private file must not stop the spike
            skipped += 1
            continue
        if image is None:
            skipped += 1
            continue
        pairs.append((image, annotation))
    logger.info("Loaded %d annotated photo(s); skipped %d.", len(pairs), skipped)
    return pairs


def resolve_membership(dotted: Optional[str]) -> Optional[Callable[..., Sequence[bool]]]:
    """importlib.import_module(dotted).admit when given; None otherwise or on ImportError (logged)."""
    if not dotted:
        return None
    try:
        module = importlib.import_module(dotted)
    except ImportError as exc:
        logger.warning("Membership module %s not importable (%s); membership gate stays untested.", dotted, exc)
        return None
    admit = getattr(module, "admit", None)
    if not callable(admit):
        logger.warning("Membership module %s has no callable 'admit'; membership gate stays untested.", dotted)
        return None
    return admit


def _to_proposals(
    candidates: Sequence[ShapeCandidate],
    image_size: Tuple[int, int],
    admit: Optional[Callable[..., Sequence[bool]]],
) -> List["evaluate.Proposal"]:
    """Reduce proposer output to evaluator proposals, applying the membership function when given."""
    admitted: Sequence[Optional[bool]] = [None] * len(candidates)
    if admit is not None:
        try:
            admitted = list(admit(candidates, image_size))
        except Exception as exc:  # noqa: BLE001 - a failing hypothesis is data, not a crash
            logger.warning("Membership function failed (%s); treating admission as untested.", exc)
    return [
        evaluate.Proposal(profile=c.profile, kind=c.kind, box=(c.x1, c.y1, c.x2, c.y2), admitted=a)
        for c, a in zip(candidates, admitted, strict=True)
    ]


def _fmt(value: Optional[float]) -> str:
    """Two-decimal ratio or an em dash."""
    return "—" if value is None else f"{value:.2f}"


def render_report(
    photos: Sequence["evaluate.PhotoResult"],
    synthetic: Dict[str, bool],
    outcome: str,
    gates: Dict[str, str],
    profiles: Sequence[ShapeProfile],
    args: argparse.Namespace,
    synthetic_results: Optional[Dict[str, "evaluate.PhotoResult"]] = None,
) -> str:
    """Markdown with the fixed sections of docs/pipelines/planogram-perception-spike.md."""
    evaluable = [p for p in photos if p.slot_recall is not None]
    exercised = sorted({c for p in evaluable for c in p.conditions})
    membership_detail = (
        "no membership module supplied" if not args.membership_module else f"module `{args.membership_module}`"
    )
    lines: List[str] = [
        "# Planogram perception spike — FEAT-574",
        "",
        f"**Outcome**: {outcome}",
        f"**Date**: {datetime.date.today().isoformat()} · **IoU threshold**: {args.iou} · "
        f"**Work width**: {args.work_width} · **Evaluable photos**: {len(evaluable)}",
        "",
        "> Engineering gates on a small private sample — not population accuracy claims.",
        "> Photos and annotations are private and git-ignored; this file holds aggregates only.",
        "",
        "## Gates",
        "| Gate | State | Detail |",
        "|---|---|---|",
        f"| product-slot recall ≥ 0.90 on each evaluable photo | {gates['slot_recall']} | "
        f"{len(evaluable)} evaluable photo(s) |",
        f"| product-slot precision ≥ 0.90 on each evaluable photo | {gates['slot_precision']} | "
        f"{len(evaluable)} evaluable photo(s) |",
        f"| zero off-fixture observations admitted | {gates['off_fixture_admitted']} | {membership_detail} |",
        f"| synthetic cases (partial shelf, absent anchors, adjacent fixture) | {gates['synthetic']} | "
        + ", ".join(f"{k}: {'passed' if synthetic.get(k) else 'failed'}" for k in evaluate.SYNTHETIC_GATE_CASES)
        + " |",
        "",
        "## Conditions exercised",
        "",
        f"Real photos: {', '.join(exercised) if exercised else 'none'}. "
        f"Required: {', '.join(evaluate.REQUIRED_CONDITIONS)}. "
        "`repeated_skus` is not applicable at proposal level (identity is decided later).",
        "",
        "## Per-photo, per-profile precision / recall",
        "",
    ]
    if evaluable:
        lines += ["| Photo | Profile | TP | FP | FN | Precision | Recall |", "|---|---|---|---|---|---|---|"]
        for photo in evaluable:
            for m in photo.per_profile:
                lines.append(
                    f"| photo {photo.index} | {m.profile} | {m.true_positives} | {m.false_positives} | "
                    f"{m.false_negatives} | {_fmt(m.precision)} | {_fmt(m.recall)} |"
                )
    else:
        lines.append("No evaluable private photo was supplied.")
    lines += ["", "## Off-fixture proposals and admissions", ""]
    if evaluable:
        lines += ["| Photo | Off-fixture proposals | Admitted |", "|---|---|---|"]
        for photo in evaluable:
            admitted = "untested" if photo.off_fixture_admitted is None else str(photo.off_fixture_admitted)
            lines.append(f"| photo {photo.index} | {photo.off_fixture_proposals} | {admitted} |")
    else:
        lines.append("Not measured (no private photos).")
    lines += [
        "",
        "## Synthetic cases",
        "",
        "| Case | Slot precision | Slot recall | Off-fixture proposals | Passed |",
        "|---|---|---|---|---|",
    ]
    for name, result in (synthetic_results or {}).items():
        lines.append(
            f"| {name} | {_fmt(result.slot_precision)} | {_fmt(result.slot_recall)} | "
            f"{result.off_fixture_proposals} | {'yes' if synthetic.get(name) else 'no'} |"
        )
    lines += ["", "## Candidate profiles evaluated", "", "```json"]
    lines.append(json.dumps([p.model_dump(mode="json") for p in profiles], indent=2))
    lines += ["```", "", "## Accepted profiles", "", "```json"]
    accepted = [p.model_dump(mode="json") for p in profiles] if outcome == "passed" else []
    lines.append(json.dumps(accepted, indent=2))
    lines += ["```", "", "## Failures and untested conditions", ""]
    notes = [f"- gate `{name}`: {state}" for name, state in gates.items() if state != "passed"]
    notes += [f"- synthetic case `{k}` failed" for k, ok in synthetic.items() if not ok]
    missing = [c for c in evaluate.REQUIRED_CONDITIONS if c not in exercised]
    if missing:
        notes.append(f"- required conditions never exercised on a real photo: {', '.join(missing)}")
    if len(evaluable) < evaluate.MIN_EVALUABLE_PHOTOS:
        notes.append(f"- fewer than {evaluate.MIN_EVALUABLE_PHOTOS} evaluable photos ({len(evaluable)})")
    lines += notes or ["- none"]
    lines += [
        "",
        "## Consequence",
        "",
        '`ProductOnShelves` keeps `perception_mode="llm_detector"` unless **Outcome** is `passed`.',
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Exit code 0 for every outcome (the outcome is data, not an error)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos-dir", type=Path, default=None)
    parser.add_argument("--annotations-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--work-width", type=int, default=2048)
    parser.add_argument("--membership-module", type=str, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    kind_of_profile = {p.name: p.kind for p in CANDIDATE_PROFILES}
    admit = resolve_membership(args.membership_module)

    photos: List[evaluate.PhotoResult] = []
    for index, (image, annotation) in enumerate(load_sample(args.photos_dir, args.annotations_dir), start=1):
        candidates = propose_shapes(image, CANDIDATE_PROFILES, work_width=args.work_width)
        proposals = _to_proposals(candidates, (image.shape[1], image.shape[0]), admit)
        photos.append(evaluate.evaluate_photo(index, annotation, proposals, kind_of_profile, args.iou))

    synthetic: Dict[str, bool] = {}
    synthetic_results: Dict[str, evaluate.PhotoResult] = {}
    for index, (name, (image, annotation)) in enumerate(synthetic_cases().items(), start=1):
        candidates = propose_shapes(image, CANDIDATE_PROFILES, work_width=args.work_width)
        proposals = _to_proposals(candidates, (image.shape[1], image.shape[0]), admit)
        result = evaluate.evaluate_photo(index, annotation, proposals, kind_of_profile, args.iou)
        synthetic_results[name] = result
        synthetic[name] = (
            result.slot_recall is not None
            and result.slot_recall >= 0.90
            and result.slot_precision is not None
            and result.slot_precision >= 0.90
        )

    outcome, gates = evaluate.decide_outcome(photos, synthetic)
    report = render_report(photos, synthetic, outcome, gates, CANDIDATE_PROFILES, args, synthetic_results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    logger.info("Spike outcome: %s (report written).", outcome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
