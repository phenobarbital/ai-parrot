"""Contract tests for the shipped CVE analyst expert bundle."""

from parrot.bots.prompts.identity import IDENTITY_FILES
from parrot.experts.loader import BUNDLED_EXPERTS_DIR, parse_expert_bundle
from parrot.experts.rules import parse_rules

BUNDLE_DIR = BUNDLED_EXPERTS_DIR / "cve-analyst"


def test_bundled_manifest_validates() -> None:
    """The bundled manifest loads with its fixed policy and knowledge contract."""
    bundle = parse_expert_bundle(BUNDLE_DIR, origin="bundled")

    assert bundle.manifest.name == "cve-analyst"
    assert bundle.manifest.tier.value == "judgment"
    assert bundle.manifest.toolkits == ["CVEToolkit", "LLMWikiToolkit", "BookstoreToolkit"]
    assert bundle.manifest.capabilities == ["validate", "write", "review"]
    assert bundle.manifest.produces == ["vulnerability-report", "adr"]
    assert bundle.manifest.global_only is False
    assert any(source.source.value == "wiki" for source in bundle.manifest.knowledge)


def test_bundled_identity_files_complete() -> None:
    """Every canonical identity field is present, non-empty, and placeholder-free."""
    identity_dir = BUNDLE_DIR / "identity"
    actual_names = {path.stem for path in identity_dir.glob("*.md")}

    assert actual_names == set(IDENTITY_FILES)
    for field_name in IDENTITY_FILES:
        content = (identity_dir / f"{field_name}.md").read_text(encoding="utf-8")
        assert content.strip()
        assert "$" not in content


def test_bundled_rules_grammar() -> None:
    """Bundled governance follows the strict ALWAYS and NEVER grammar."""
    rules = parse_rules(BUNDLE_DIR / "rules" / "governance.md", layer="expert")

    assert len(rules.mandated) >= 3
    assert len(rules.forbidden) >= 2
    assert "NEVER delegate" in rules.forbidden


def test_knowledge_files_have_h1() -> None:
    """Every bundled Tier-1 knowledge document has a wiki page title."""
    knowledge_dir = BUNDLE_DIR / "knowledge"
    expected_names = {
        "cve-triage-method.md",
        "cvss-epss-kev.md",
        "workspace-impact-analysis.md",
    }
    knowledge_files = list(knowledge_dir.glob("*.md"))

    assert {path.name for path in knowledge_files} == expected_names
    for path in knowledge_files:
        assert path.read_text(encoding="utf-8").startswith("# ")
