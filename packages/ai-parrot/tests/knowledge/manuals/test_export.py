"""FEAT-601 M14 — export bundle (AC22)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals import export as ex
from parrot.knowledge.manuals.models import (
    Applicability,
    EquipmentRef,
    Hazard,
    MediaLink,
    MediaRef,
    ManualCard,
    ManualVersion,
    PartRef,
    Procedure,
    SerialRange,
    Step,
    StepIdentity,
    Tip,
    ToolRef,
    content_hash,
)

FROZEN = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _text(quote: str = "Torque the bolt to 12 Nm.", node_id: str = "node-1") -> Extracted[str]:
    """Build one independently evidenced string value (``Step.text``/``Procedure.title`` are ``Extracted[str]``)."""
    return Extracted(value=quote, evidence=Evidence(node_id=node_id, quote=quote), confidence=0.9)


def _step(
    step_id: str,
    order: int,
    text: str = "Torque the bolt to 12 Nm.",
    torque: str | None = None,
    duration_minutes: int | None = None,
) -> Step:
    return Step(
        identity=StepIdentity(step_id=step_id, content_hash=content_hash(text)),
        order=order,
        text=_text(text),
        torque=_text(torque) if torque is not None else None,
        duration_minutes=(
            Extracted(value=duration_minutes, evidence=Evidence(node_id="node-1", quote=str(duration_minutes)))
            if duration_minutes is not None
            else None
        ),
    )


def _procedure(
    procedure_id: str,
    slug: str,
    kind: str,
    title: str = "Torque the bolt to 12 Nm.",
    steps: list[Step] | None = None,
) -> Procedure:
    return Procedure(
        procedure_id=procedure_id,
        slug=slug,
        kind=kind,
        title=_text(title),
        steps=steps or [],
    )


def _media_ref(
    media_id: str,
    kind: str,
    storage_key: str | None = None,
    uri: str | None = None,
    caption: str | None = None,
    label: str | None = None,
    page: int | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
) -> MediaRef:
    return MediaRef(
        media_id=media_id,
        kind=kind,
        storage_key=storage_key,
        uri=uri,
        caption=caption,
        label=label,
        page=page,
        t_start=t_start,
        t_end=t_end,
    )


def _tip(
    tip_id: str,
    text: str,
    origin: str = "technician",
    author_employee_id: str | None = None,
    created_at: datetime = FROZEN,
    active: bool = True,
    orphaned: bool = False,
    source_revision: str = "A",
    attached_step_id: str | None = None,
) -> Tip:
    return Tip(
        tip_id=tip_id,
        text=text,
        origin=origin,
        author_employee_id=author_employee_id,
        created_at=created_at,
        active=active,
        orphaned=orphaned,
        source_revision=source_revision,
        attached_step_id=attached_step_id,
    )


async def test_export_bundle_layout_and_manifest(tmp_path, fake_file_manager) -> None:
    """Test bundle layout, manifest SHA256s, determinism, and missing figures."""
    # Build a ManualCard with 2 procedures, figures with storage keys, one video segment
    card = ManualCard(
        manual_id="model-x",
        revision="B",
        source_sha256="abc123",
        procedures=[
            _procedure(
                "p1",
                "repair",
                "maintenance",
                steps=[
                    _step("m:p:1", 1, "Remove the cover.", torque="10 Nm"),
                    _step("m:p:2", 2, "Replace the bolt.", duration_minutes=5),
                ],
            ),
            _procedure(
                "p2",
                "clean",
                "inspection",
                steps=[
                    _step("m:p:3", 1, "Wipe the surface.", torque=None, duration_minutes=2),
                ],
            ),
        ],
        figures=[
            _media_ref("f1", "figure", storage_key="s3://bucket/f1.png", caption="Cover removed", page=5),
            _media_ref("f2", "figure", storage_key="s3://bucket/f2.png", caption="Bolt replaced", page=6),
            _media_ref("v1", "video_segment", uri="https://vendor.com/video.mp4", t_start=10.0, t_end=20.0),
        ],
        versions=[
            ManualVersion(n=1, revision="A", source_sha256="def456"),
            ManualVersion(n=2, revision="B", source_sha256="abc123"),
        ],
    )

    # Pre-load fake_file_manager with one figure and leave the other missing
    fake_file_manager.objects["s3://bucket/f1.png"] = b"figure1"
    fake_file_manager.missing.add("s3://bucket/f2.png")

    # Export twice with a frozen clock
    out_dir = tmp_path / "out"
    report1 = await ex.export_bundle(
        card,
        file_manager=fake_file_manager,
        out_dir=out_dir,
        zip_bundle=False,
        now=lambda: FROZEN,
    )
    report2 = await ex.export_bundle(
        card,
        file_manager=fake_file_manager,
        out_dir=out_dir,
        zip_bundle=False,
        now=lambda: FROZEN,
    )

    # Verify identical bytes
    assert report1.bundle_dir == report2.bundle_dir
    assert report1.zip_path is None
    assert report2.zip_path is None

    # Verify manifest SHA256s match files
    manifest1 = json.loads((report1.bundle_dir / "manifest.json").read_text())
    manifest2 = json.loads((report2.bundle_dir / "manifest.json").read_text())
    assert manifest1["files"] == manifest2["files"]

    # Verify procedures.json sorted/deterministic
    procedures1 = json.loads((report1.bundle_dir / "procedures.json").read_text())
    procedures2 = json.loads((report2.bundle_dir / "procedures.json").read_text())
    assert procedures1 == procedures2

    # Verify no http(s) outside videos.json
    for filename in ["manifest.json", "procedures.json", "captions.json"]:
        content = (report1.bundle_dir / filename).read_text()
        if filename == "videos.json":
            # videos.json should contain the video URI
            assert "https://vendor.com/video.mp4" in content
        else:
            # Other files should not contain http(s)
            assert "http" not in content
            assert "https" not in content

    # Verify figures_missing lists the missing one
    assert report1.figures_missing == ["f2"]
    assert report2.figures_missing == ["f2"]

    # Verify counters
    assert report1.procedures == 2
    assert report1.steps == 3
    assert report1.figures == 1
    assert report1.tips == 0
    assert report1.bytes > 0


async def test_export_excludes_orphaned_tips(tmp_path, fake_file_manager) -> None:
    """Test that orphaned and inactive tips are excluded from the bundle."""
    card = ManualCard(
        manual_id="model-x",
        revision="A",
        source_sha256="abc123",
        procedures=[
            _procedure(
                "p1",
                "repair",
                "maintenance",
                steps=[
                    _step("m:p:1", 1, "Remove the cover."),
                ],
            ),
        ],
        figures=[
            _media_ref("f1", "figure", storage_key="s3://bucket/f1.png"),
        ],
    )

    # Tips: active attached, orphaned, inactive
    tips = [
        _tip("t1", "Active tip", attached_step_id="m:p:1", active=True, orphaned=False),
        _tip("t2", "Orphaned tip", attached_step_id="m:p:1", active=True, orphaned=True),
        _tip("t3", "Inactive tip", attached_step_id="m:p:1", active=False, orphaned=False),
    ]

    fake_file_manager.objects["s3://bucket/f1.png"] = b"figure1"

    # Export with include_tips=True
    report1 = await ex.export_bundle(
        card,
        file_manager=fake_file_manager,
        out_dir=tmp_path / "out1",
        include_tips=True,
        tips=tips,
        zip_bundle=False,
    )

    # Export with include_tips=False
    report2 = await ex.export_bundle(
        card,
        file_manager=fake_file_manager,
        out_dir=tmp_path / "out2",
        include_tips=False,
        tips=tips,
        zip_bundle=False,
    )

    # Verify only the active tip is in procedures.json
    procedures1 = json.loads((report1.bundle_dir / "procedures.json").read_text())
    assert "repair" in procedures1["procedures"]
    assert "tips" in procedures1["procedures"]["repair"]
    assert len(procedures1["procedures"]["repair"]["tips"]) == 1
    assert procedures1["procedures"]["repair"]["tips"][0]["tip_id"] == "t1"

    # Verify no tips when include_tips=False
    procedures2 = json.loads((report2.bundle_dir / "procedures.json").read_text())
    assert "tips" not in procedures2["procedures"]["repair"]

    # Verify counters
    assert report1.tips == 1
    assert report2.tips == 0


async def test_export_includes_tips_attached_to_any_step(tmp_path, fake_file_manager) -> None:
    """A tip attached to a NON-LAST step of a multi-step procedure must still be exported.

    Regression test: ``render_procedures`` previously filtered ``attached_tips`` against a
    loop variable leaked from the steps ``for`` loop, so only tips attached to the highest-
    ``order`` step survived — any tip on an earlier step was silently dropped.
    """
    card = ManualCard(
        manual_id="model-x",
        revision="A",
        source_sha256="abc123",
        procedures=[
            _procedure(
                "p1",
                "repair",
                "maintenance",
                steps=[
                    _step("m:p:1", 1, "Remove the cover."),
                    _step("m:p:2", 2, "Torque the bolt to 12 Nm."),
                ],
            ),
        ],
    )
    tips = [
        _tip("t1", "Tip on first step", attached_step_id="m:p:1"),
        _tip("t2", "Tip on last step", attached_step_id="m:p:2"),
    ]

    report = await ex.export_bundle(
        card,
        file_manager=fake_file_manager,
        out_dir=tmp_path / "out",
        include_tips=True,
        tips=tips,
        zip_bundle=False,
    )

    procedures = json.loads((report.bundle_dir / "procedures.json").read_text())
    tip_ids = {tip["tip_id"] for tip in procedures["procedures"]["repair"]["tips"]}
    assert tip_ids == {"t1", "t2"}
    assert report.tips == 2
