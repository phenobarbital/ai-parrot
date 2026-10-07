"""Keeps the output-language docs and catalogs in sync (FEAT-638 TASK-4126)."""
from pathlib import Path

# Minimal imports to avoid Cython compilation issues
REPO = Path(__file__).resolve().parents[5]
GUIDE = REPO / "docs" / "prompts" / "output-language.md"
JIRA_LAYERS_DOC = REPO / "docs" / "jira-specialist-prompt-layers.md"
REFERENCE = REPO / "docs" / "prompts" / "layers-reference.md"


def test_guide_exists_and_has_contribution_section():
    """Test that the guide exists and has the required sections."""
    assert GUIDE.exists(), "Guide file does not exist"
    text = GUIDE.read_text(encoding="utf-8")
    assert "## Adding a language" in text, "Missing 'Adding a language' section"
    for symbol in ("SUPPORTED_LANGUAGES", "GROUNDING_SENTINELS", "JIRA_MESSAGES"):
        assert symbol in text, f"Missing symbol: {symbol}"


def test_guide_lists_supported_languages():
    """Test that the guide lists supported languages."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "`en`" in text and "English" in text, "Missing English language"
    assert "`es`" in text and "Spanish" in text, "Missing Spanish language"


def test_jira_layers_doc_updated():
    """Test that the Jira layers doc no longer forbids localising sentinels."""
    text = JIRA_LAYERS_DOC.read_text(encoding="utf-8")
    assert "Do not localise the sentinel phrases" not in text, "Old anti-pattern still present"
    assert "Do not hardcode the sentinel phrases" in text, "New anti-pattern not found"


def test_layers_reference_documents_output_language():
    """Test that the layers reference documents the output language layer."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert "OUTPUT_LANGUAGE_LAYER" in text, "Missing OUTPUT_LANGUAGE_LAYER"
    assert "`output_language`" in text, "Missing output_language reference"
    assert "$sentinel_not_found" in text, "Missing sentinel variable"


def test_layers_reference_has_registry_row():
    """Test that the registry includes the output_language row."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert "| `output_language` | `OUTPUT_LANGUAGE_LAYER` | 59 | CONFIGURE | Bot-level output language (FEAT-638) |" in text, "Missing registry row"


def test_layers_reference_has_assembled_order():
    """Test that the assembled order includes the output language layer."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert "59  OUTPUT_LANGUAGE_LAYER   ← (when the bot sets `language`)" in text, "Missing assembled order entry"
