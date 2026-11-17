"""Tests for the package-bundled CVE remediation expert (FEAT-778 M13)."""

from __future__ import annotations

from parrot.bots.prompts.identity import IDENTITY_FILES
from parrot.experts.loader import BUNDLED_EXPERTS_DIR, parse_expert_bundle
from parrot.experts.models import ExpertTier, KnowledgeSourceKind
from parrot.experts.rules import parse_rules

_BUNDLE_DIR = BUNDLED_EXPERTS_DIR / "cve-remediation"


def test_bundled_manifest_validates() -> None:
    """The remediation bundle parses with its required manifest contract."""
    bundle = parse_expert_bundle(_BUNDLE_DIR, origin="bundled")

    assert bundle.manifest.name == "cve-remediation"
    assert bundle.manifest.tier is ExpertTier.TEMPLATED
    assert bundle.manifest.capabilities == ["write"]
    assert "CVEToolkit" in bundle.manifest.toolkits
    assert any(source.source is KnowledgeSourceKind.WIKI for source in bundle.manifest.knowledge)


def test_bundled_identity_files_complete() -> None:
    """All required identity fields exist, are readable, and contain no placeholders."""
    bundle = parse_expert_bundle(_BUNDLE_DIR, origin="bundled")

    for field_name in IDENTITY_FILES:
        field_path = bundle.identity_dir / f"{field_name}.md"
        content = field_path.read_text(encoding="utf-8").strip()
        assert content
        assert "$" not in content


def test_bundled_rules_grammar() -> None:
    """The governance document satisfies the expert ALWAYS and NEVER grammar."""
    rules = parse_rules(_BUNDLE_DIR / "rules" / "governance.md", layer="expert")

    assert len(rules.mandated) >= 3
    assert len(rules.forbidden) >= 2
    assert "NEVER delegate" in rules.forbidden


def test_plan_template_has_required_sections() -> None:
    """The bundled template contains every section required for a remediation plan."""
    template_path = _BUNDLE_DIR / "knowledge" / "remediation-plan-template.md"
    template = template_path.read_text(encoding="utf-8")

    assert template.startswith("# ")
    for section in (
        "## CVE",
        "## Affected package and version",
        "## Target version and rationale",
        "## Manifest change",
        "## Verification",
        "## Rollback",
    ):
        assert section in template
