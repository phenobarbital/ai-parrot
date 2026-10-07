"""Tests for JIRA_GROUNDING_LAYER (FEAT-138 TASK-945; localized by FEAT-638 TASK-4122)."""

import pytest

from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS, JIRA_GROUNDING_LAYER
from parrot.bots.prompts.layers import LayerPriority, PromptLayer, RenderPhase

LANGS = sorted(GROUNDING_SENTINELS)


def _ctx(lang: str) -> dict:
    row = GROUNDING_SENTINELS[lang]
    return {"sentinel_not_found": row["not_found"], "sentinel_error": row["error"]}


def _masked(lang: str) -> str:
    row = GROUNDING_SENTINELS[lang]
    rendered = JIRA_GROUNDING_LAYER.render(_ctx(lang))
    return rendered.replace(row["not_found"], "<NF>").replace(row["error"], "<ER>")


def test_jira_grounding_layer_metadata():
    assert isinstance(JIRA_GROUNDING_LAYER, PromptLayer)
    assert JIRA_GROUNDING_LAYER.name == "jira_grounding"
    assert JIRA_GROUNDING_LAYER.phase == RenderPhase.CONFIGURE
    assert int(JIRA_GROUNDING_LAYER.priority) == int(LayerPriority.BEHAVIOR) - 5


@pytest.mark.parametrize("lang", LANGS)
def test_jira_grounding_layer_contains_sentinel_phrases(lang):
    rendered = JIRA_GROUNDING_LAYER.render(_ctx(lang))
    assert GROUNDING_SENTINELS[lang]["not_found"] in rendered
    assert GROUNDING_SENTINELS[lang]["error"] in rendered
    assert "$sentinel" not in rendered


@pytest.mark.parametrize("lang", LANGS)
def test_jira_grounding_layer_load_bearing_rules_in_first_paragraph(lang):
    first_paragraph = JIRA_GROUNDING_LAYER.render(_ctx(lang)).split("\n\n", 1)[0]
    assert "fabricate" in first_paragraph.lower() or "fabrication" in first_paragraph.lower()
    assert GROUNDING_SENTINELS[lang]["not_found"] in first_paragraph
    assert GROUNDING_SENTINELS[lang]["error"] in first_paragraph


def test_jira_grounding_layer_english_has_no_spanish():
    rendered = JIRA_GROUNDING_LAYER.render(_ctx("en"))
    for phrase in [
        "No encontré",
        "Hubo un error",
        "disculpa",
        "consultando",
        GROUNDING_SENTINELS["es"]["not_found"],
        GROUNDING_SENTINELS["es"]["error"],
    ]:
        assert phrase not in rendered


def test_jira_grounding_layer_spanish_replaces_english_sentinels():
    rendered = JIRA_GROUNDING_LAYER.render(_ctx("es"))
    assert GROUNDING_SENTINELS["en"]["not_found"] not in rendered
    assert GROUNDING_SENTINELS["en"]["error"] not in rendered


def test_jira_grounding_rules_unchanged_across_languages():
    """Only the sentinel wording varies — every rule is identical in every language."""
    assert len({_masked(lang) for lang in LANGS}) == 1


def test_jira_grounding_layer_needs_injected_vars():
    """Documents the dependency on AbstractBot's injection (TASK-4121)."""
    assert "$sentinel_not_found" in JIRA_GROUNDING_LAYER.render({})
