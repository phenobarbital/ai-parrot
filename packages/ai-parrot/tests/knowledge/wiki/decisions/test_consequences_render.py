"""Tests for deterministic consequence section rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.consequences import (
    ConsequenceReport,
    CoverageSummary,
    Finding,
    GoverningDossier,
    GoverningEntry,
    canonicalize_spec,
)
from parrot.knowledge.wiki.decisions.consequences_render import (
    CONSEQUENCES_HEADING,
    GOVERNING_HEADING,
    NOT_CONFIGURED_LINE,
    check_spec,
    render_consequences,
    render_governing,
    render_spec,
    splice_sections,
)
from parrot.knowledge.wiki.decisions.inventory import SnapshotManifest
from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, DecisionRef

SPEC = "# X\n\n## 1. Motivation\n\n## 2. Architectural Design\n\n## 8. Open Questions\n"


def _report(*, input_digest: str = "sha256:input", status: str = "pass") -> ConsequenceReport:
    """Build a fixed report fixture."""
    return ConsequenceReport(
        status=status,
        exit_code=0,
        input_digest=input_digest,
        evaluation_digest="sha256:evaluation",
        snapshot=SnapshotManifest(
            inventory={},
            taxonomy_digest="sha256:taxonomy",
            approvals_digest="sha256:approvals",
            structural_revision="sha256:structural",
            rules_version=1,
            config_digest="sha256:config",
        ),
        coverage=CoverageSummary(subsystems=["wiki"]),
    )


def _dossier() -> GoverningDossier:
    """Build a governing dossier with one complete and one sparse entry."""
    return GoverningDossier(
        searched_subsystems=["wiki"],
        entries=[
            GoverningEntry(
                decision_id="adr:doc:b",
                revision=2,
                title="B",
                statement="Use B",
                normative="requires",
                about=["wiki"],
                targets=["file:b.py"],
                rationale="Because",
                consequences="Stable",
                supersedes=[DecisionRef(decision_id="adr:doc:a", revision=1)],
                freshness="current",
            ),
            GoverningEntry(decision_id="adr:doc:a", revision=1),
        ],
    )


class FakeConsequenceService:
    """Minimal fixed evaluator used to exercise render/check I/O."""

    def __init__(self, root: Path, report: ConsequenceReport, dossier: GoverningDossier | None = None) -> None:
        self.root = root
        self.report = report
        self.dossier = dossier or GoverningDossier(empty_plane=True, searched_subsystems=["wiki"])
        self.governing_calls = 0

    async def evaluate(self, spec_path: Path) -> ConsequenceReport:
        """Return the currently configured report."""
        del spec_path
        return self.report

    async def governing(self, spec_path: Path, *, budget_tokens: int) -> GoverningDossier:
        """Return the currently configured dossier."""
        del spec_path, budget_tokens
        self.governing_calls += 1
        return self.dossier


def test_splice_idempotent() -> None:
    """Generated sections replace in place at stable anchors."""
    once = splice_sections(SPEC, "## Governing Decisions\n\nG\n", "## Consequences\n\nC\n")
    assert splice_sections(once, "## Governing Decisions\n\nG\n", "## Consequences\n\nC\n") == once
    assert once.index(GOVERNING_HEADING) < once.index("## 2.")
    assert once.index(CONSEQUENCES_HEADING) < once.index("## 8.")
    assert once.count(GOVERNING_HEADING) == once.count(CONSEQUENCES_HEADING) == 1


def test_splice_preserves_canonical_spec_input() -> None:
    """Generated output is excluded from evaluator input digests."""
    rendered = splice_sections(SPEC, "## Governing Decisions\n\nG\n", "## Consequences\n\nC\n")
    assert canonicalize_spec(rendered) == canonicalize_spec(SPEC)


def test_render_consequences_lists_every_finding() -> None:
    """The Markdown summary and JSON tail retain every finding."""
    report = _report().model_copy(
        update={
            "findings": [
                Finding(
                    kind="potential-conflict",
                    rule_version=1,
                    fingerprint="sha256:z",
                    participants=[DecisionRef(decision_id="adr:doc:z", revision=2)],
                    scope=["file:z.py"],
                    message="later advisory",
                ),
                Finding(
                    kind="contradiction",
                    rule_version=1,
                    fingerprint="sha256:a",
                    participants=[DecisionRef(decision_id="adr:doc:a", revision=1)],
                    scope=["file:a.py"],
                    blocking=True,
                    waived_by="approval:1",
                    message="blocking finding",
                ),
            ],
            "diagnostics": [DecisionDiagnostic(code="D2", path="z.py", message="diagnostic")],
        }
    )
    rendered = render_consequences(report)
    assert rendered.count("message: blocking finding") == 1
    assert rendered.count("message: later advisory") == 1
    assert rendered.index("`contradiction`") < rendered.index("`potential-conflict`")
    assert "[BLOCKING]" in rendered
    assert "waived_by: approval:1" in rendered
    assert '"findings": [' in rendered


def test_render_governing_missing_fields_and_budget_omissions() -> None:
    """Sparse entries are explicit and budget omissions are enumerable."""
    report = _report()
    full = render_governing(_dossier(), budget_tokens=10_000, report=report)
    assert full.index("adr:doc:a@1") < full.index("adr:doc:b@2")
    assert "- Title: not recorded" in full
    assert "- Supersedes: adr:doc:a@1" in full

    budgeted = render_governing(_dossier(), budget_tokens=1, report=report)
    assert "Omitted (budget):" in budgeted
    assert "- adr:doc:a" in budgeted and "- adr:doc:b" in budgeted


def test_render_governing_empty_plane_names_subsystems() -> None:
    """Configured empty planes still produce an explicit governing section."""
    rendered = render_governing(
        GoverningDossier(empty_plane=True, searched_subsystems=["server", "wiki"]),
        budget_tokens=1_000,
        report=_report(),
    )
    assert "No eligible decisions govern subsystems: server, wiki" in rendered


@pytest.mark.asyncio
async def test_render_byte_identical(tmp_path: Path) -> None:
    """A second render leaves bytes and modification time unchanged."""
    path = tmp_path / "spec.md"
    path.write_text(SPEC, encoding="utf-8")
    service = FakeConsequenceService(tmp_path, _report(), _dossier())

    await render_spec(service, Path("spec.md"), budget_tokens=10_000)
    first = path.read_bytes()
    first_mtime = path.stat().st_mtime_ns
    await render_spec(service, Path("spec.md"), budget_tokens=10_000)

    assert path.read_bytes() == first
    assert path.stat().st_mtime_ns == first_mtime
    assert service.governing_calls == 2


@pytest.mark.asyncio
async def test_check_detects_stale_and_missing(tmp_path: Path) -> None:
    """Check distinguishes changed digests from absent sections."""
    path = tmp_path / "spec.md"
    path.write_text(SPEC, encoding="utf-8")
    service = FakeConsequenceService(tmp_path, _report(), _dossier())
    await render_spec(service, Path("spec.md"), budget_tokens=10_000)
    assert (await check_spec(service, Path("spec.md"))).status == "current"

    service.report = _report(input_digest="sha256:changed")
    assert (await check_spec(service, Path("spec.md"))).status == "stale"

    text = path.read_text(encoding="utf-8")
    start = text.index(CONSEQUENCES_HEADING)
    end = text.index("## 8.", start)
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    assert (await check_spec(service, Path("spec.md"))).status == "missing"


@pytest.mark.asyncio
async def test_check_detects_body_tampering(tmp_path: Path) -> None:
    """Matching digest headers do not hide a modified consequence body."""
    path = tmp_path / "spec.md"
    path.write_text(SPEC, encoding="utf-8")
    service = FakeConsequenceService(tmp_path, _report(), _dossier())
    await render_spec(service, Path("spec.md"), budget_tokens=10_000)
    path.write_text(path.read_text(encoding="utf-8").replace("Findings:", "Findings: changed"), encoding="utf-8")
    assert (await check_spec(service, Path("spec.md"))).status == "stale"


@pytest.mark.asyncio
async def test_check_never_writes(tmp_path: Path) -> None:
    """Both current and stale checks preserve bytes and mtime."""
    path = tmp_path / "spec.md"
    path.write_text(SPEC, encoding="utf-8")
    service = FakeConsequenceService(tmp_path, _report(), _dossier())
    await render_spec(service, Path("spec.md"), budget_tokens=10_000)
    service.report = _report(input_digest="sha256:changed")
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    await check_spec(service, Path("spec.md"))
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime


@pytest.mark.asyncio
async def test_skipped_renders_single_line(tmp_path: Path) -> None:
    """Unconfigured repositories render one marker and no generated sections."""
    path = tmp_path / "spec.md"
    path.write_text(
        splice_sections(SPEC, "## Governing Decisions\n\nold\n", "## Consequences\n\nold\n"),
        encoding="utf-8",
    )
    service = FakeConsequenceService(tmp_path, _report(status="skipped"))
    await render_spec(service, Path("spec.md"), budget_tokens=1_000)
    await render_spec(service, Path("spec.md"), budget_tokens=1_000)
    rendered = path.read_text(encoding="utf-8")
    assert rendered.count(NOT_CONFIGURED_LINE) == 1
    assert GOVERNING_HEADING not in rendered
    assert CONSEQUENCES_HEADING not in rendered
    assert rendered.index(NOT_CONFIGURED_LINE) < rendered.index("## 2.")
    assert service.governing_calls == 0
    assert (await check_spec(service, Path("spec.md"))).status == "current"
