"""Tests for the narration lexicon loader (FEAT-649, TASK-4213)."""

import pytest

from parrot_formdesigner.audio.narration import load_lexicon, load_locale_document, locale_chain, normalize

EXPECTED_KEYS = {
    "question", "question_with_prompt", "hint_bridge", "options_intro", "option_item", "options_count_only",
    "boolean_prompt", "required_mark", "confirm_readback", "confirm_option", "no_match", "required_reject",
    "skipped", "section_intro", "computed_statement", "review_intro", "review_item", "review_item_skipped",
    "review_all_correct", "review_edit_ack", "plausibility_flag", "plausibility_keep", "submitted",
    "resume_welcome", "command_ack_repeat", "command_ack_back", "command_ack_skip", "command_ack_help",
    "command_ack_stop", "command_ack_next", "command_ack_send", "command_ack_change",
}
COMMAND_KEYS = {"repeat", "back", "skip", "help", "stop", "next", "send", "change", "yes", "no"}


class TestLexicon:
    def test_locale_chain(self):
        assert locale_chain("es-MX") == ["es-MX", "es", "en"]
        assert locale_chain("en") == ["en"]

    def test_fallback(self):
        assert load_lexicon("es-MX").locale == "es"
        assert load_lexicon("fr").locale == "en"

    @pytest.mark.parametrize("locale", ["en", "es"])
    def test_templates_and_commands_complete(self, locale):
        _, doc = load_locale_document(locale)
        assert set(doc["templates"]) == EXPECTED_KEYS
        assert set(doc["lexicon"]["commands"]) == COMMAND_KEYS

    @pytest.mark.parametrize("locale", ["en", "es"])
    def test_yes_no_are_strings(self, locale):
        lex = load_lexicon(locale)
        assert lex.yes and lex.no
        assert all(isinstance(x, str) for x in lex.yes + lex.no)
        assert all(isinstance(x, str) for x in lex.commands["yes"] + lex.commands["no"])

    def test_normalize_pipeline(self):
        es = load_lexicon("es")
        assert normalize("¡Sí, por favor!", es) == "si"
        assert normalize("Opción   3", es) == "opcion 3"

    def test_phrases_stored_normalised(self):
        es = load_lexicon("es")
        assert "atras" in es.commands["back"]
        assert "septimo" in es.ordinals
        assert "ultimo" in es.ordinals and es.ordinals["ultimo"] == -1
        assert "por favor" in es.fillers
