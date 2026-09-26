"""Offline export bundle for one manual revision (FEAT-601 M14, Q9)."""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.models import ManualCard, Tip

logger = logging.getLogger(__name__)

BUNDLE_SCHEMA_VERSION = "1.0"


class BundleManifest(BaseModel):
    """Manifest of a manual export bundle (AC22)."""

    schema_version: str = BUNDLE_SCHEMA_VERSION
    manual_id: str
    revision: str
    version_n: int
    generated_at: datetime
    source_sha256: str
    files: dict[str, str] = Field(default_factory=dict)  # relative path → sha256


class ExportReport(BaseModel):
    """Report of a bundle export operation (AC22)."""

    bundle_dir: Path
    zip_path: Path | None = None
    procedures: int = 0
    steps: int = 0
    figures: int = 0
    figures_missing: list[str] = Field(default_factory=list)
    tips: int = 0
    bytes: int = 0
    files: dict[str, str] = Field(default_factory=dict)


def _dump(obj: Any) -> bytes:
    """Serialize an object to JSON with deterministic formatting."""
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def render_procedures(card: ManualCard, tips: Sequence[Tip]) -> dict[str, Any]:
    """Pure, sorted rendering of procedures/steps/applicability/hazards/prerequisites/media roles/active tips; no URLs.

    Args:
        card: The manual card to render.
        tips: All tips to consider (active, non-orphaned tips attached to steps are included).

    Returns:
        A dict with manual_id, revision, and procedures list (sorted by slug).
    """
    # Filter to active, non-orphaned tips
    live_tips = [t for t in tips if t.active and not t.orphaned]

    procedures_dict: dict[str, Any] = {}

    for procedure in sorted(card.procedures, key=lambda p: p.slug):
        procedure_data: dict[str, Any] = {
            "procedure_id": procedure.procedure_id,
            "slug": procedure.slug,
            "kind": procedure.kind,
            "title": procedure.title.value,
            "estimated_minutes": procedure.estimated_minutes,
            "active": procedure.active,
        }

        # Prerequisites: union of parts and tools (dedup by id, sorted)
        parts = {p.part_id for p in procedure.steps if p.parts}
        tools = {t.tool_id for t in procedure.steps if t.tools}
        prerequisites = {"parts": sorted(parts), "tools": sorted(tools)}
        procedure_data["prerequisites"] = prerequisites

        # Steps
        steps_data: list[dict[str, Any]] = []
        for step in sorted(procedure.steps, key=lambda s: s.order):
            step_data: dict[str, Any] = {
                "step_id": step.identity.step_id,
                "order": step.order,
                "text": step.text.value,
                "torque": step.torque.value if step.torque else None,
                "duration_minutes": step.duration_minutes.value if step.duration_minutes else None,
                "applicability": {
                    "models": step.applicability.models,
                    "serial_ranges": [
                        {"start": sr.start, "end": sr.end, "format": sr.format}
                        for sr in step.applicability.serial_ranges
                    ],
                },
                "hazards": [{"severity": h.severity, "text": h.text.value} for h in step.hazards],
                "media": [{"media_id": m.media_id, "role": m.role, "confidence": m.confidence} for m in step.media],
                "cross_refs": step.cross_refs,
            }
            steps_data.append(step_data)

        procedure_data["steps"] = steps_data

        # Tips attached to this procedure (key omitted entirely when tips are disabled)
        if tips:
            procedure_step_ids = {step_data["step_id"] for step_data in steps_data}
            attached_tips = [
                {
                    "tip_id": t.tip_id,
                    "text": t.text,
                    "created_at": t.created_at.isoformat(),
                }
                for t in live_tips
                if t.attached_step_id in procedure_step_ids
            ]
            procedure_data["tips"] = attached_tips

        procedures_dict[procedure.slug] = procedure_data

    return {
        "manual_id": card.manual_id,
        "revision": card.revision,
        "procedures": procedures_dict,
    }


async def export_bundle(
    card: ManualCard,
    *,
    file_manager: Any,
    out_dir: Path,
    include_tips: bool = True,
    zip_bundle: bool = True,
    tips: Sequence[Tip] = (),
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> ExportReport:
    """Write <manual_id>-<revision>.bundle/{manifest,procedures,captions,videos}.json + figures/<media_id>.png.

    Args:
        card: The manual card to export.
        file_manager: FileManagerInterface instance for downloading figures.
        out_dir: Output directory for the bundle.
        include_tips: Whether to include tips in the export.
        zip_bundle: Whether to create a .zip bundle.
        tips: All tips to consider (used if include_tips=True).
        now: Clock function for generated_at (default: UTC now).

    Returns:
        ExportReport with bundle path, zip path, and counters.
    """
    bundle = Path(out_dir) / f"{card.manual_id}-{card.revision}.bundle"
    (bundle / "figures").mkdir(parents=True, exist_ok=True)
    report = ExportReport(bundle_dir=bundle)

    # Prepare tips to use
    tips_to_use = tips if include_tips else ()

    # Render procedures
    procedures_json = _dump(render_procedures(card, tips_to_use))
    report.procedures = len(card.procedures)
    report.steps = sum(len(p.steps) for p in card.procedures)
    # Count only tips actually included in the bundle: active, non-orphaned, and
    # attached to a step that exists on this card — not the raw input count.
    step_ids = {step.identity.step_id for procedure in card.procedures for step in procedure.steps}
    report.tips = sum(1 for t in tips_to_use if t.active and not t.orphaned and t.attached_step_id in step_ids)

    # Collect all files to write
    files_to_write: dict[str, bytes] = {
        "procedures.json": procedures_json,
    }

    # Process figures
    figures_missing: list[str] = []
    for figure in card.figures:
        if figure.kind in ("figure", "photo") and figure.storage_key:
            dest = bundle / "figures" / f"{figure.media_id}.png"
            try:
                await file_manager.download_file(figure.storage_key, dest)
                report.figures += 1
            except FileNotFoundError:
                figures_missing.append(figure.media_id)
                logger.warning("Figure %s missing from storage, skipping", figure.media_id)

    if figures_missing:
        report.figures_missing = figures_missing

    # Process video segments (captions.json and videos.json)
    captions_data: list[dict[str, Any]] = []
    videos_data: list[dict[str, Any]] = []

    for figure in card.figures:
        if figure.kind == "video_segment" and figure.uri:
            videos_data.append(
                {
                    "media_id": figure.media_id,
                    "uri": figure.uri,
                    "t_start": figure.t_start,
                    "t_end": figure.t_end,
                    "label": figure.label or figure.media_id,
                }
            )
        elif figure.kind in ("figure", "photo") and figure.caption:
            captions_data.append(
                {
                    "media_id": figure.media_id,
                    "label": figure.label or figure.media_id,
                    "page": figure.page,
                    "caption": figure.caption,
                }
            )

    if captions_data:
        files_to_write["captions.json"] = _dump(captions_data)

    if videos_data:
        files_to_write["videos.json"] = _dump(videos_data)

    # Write all JSON files and compute their SHA256s
    for filename, content in files_to_write.items():
        filepath = bundle / filename
        filepath.write_bytes(content)
        report.bytes += len(content)
        file_hash = hashlib.sha256(content).hexdigest()
        report.files[filename] = file_hash

    # Write manifest last (its SHA256s cover all other files)
    version_n = card.versions[-1].n if card.versions else 1
    manifest = BundleManifest(
        schema_version=BUNDLE_SCHEMA_VERSION,
        manual_id=card.manual_id,
        revision=card.revision,
        version_n=version_n,
        generated_at=now(),
        source_sha256=card.source_sha256,
        files=report.files,
    )
    manifest_path = bundle / "manifest.json"
    manifest_path.write_bytes(_dump(manifest.model_dump(mode="json")))
    report.bytes += len(manifest_path.read_bytes())
    report.files["manifest.json"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    # Optional zip bundle
    if zip_bundle:
        zip_path = bundle.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for filepath in bundle.rglob("*"):
                if filepath.is_file():
                    arcname = filepath.relative_to(bundle)
                    # Use deterministic date_time (1980-01-01)
                    zinfo = zipfile.ZipInfo.from_file(filepath, arcname)
                    zinfo.date_time = (1980, 1, 1, 0, 0, 0)
                    zf.writestr(zinfo, filepath.read_bytes())
        report.zip_path = zip_path

    logger.info("export_bundle: %s → %s", card.manual_id, bundle)
    return report
