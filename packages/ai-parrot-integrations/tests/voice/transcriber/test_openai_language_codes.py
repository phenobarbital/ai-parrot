"""FEAT-781 / issue:461ceca67d43 — the Whisper backend never makes up an ISO 639-1 code."""

import pytest

from parrot.voice.transcriber.openai_backend import OpenAIWhisperBackend, _iso_language


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("malay", "ms"),
        ("welsh", "cy"),
        ("Spanish", "es"),
        ("en", "en"),
        ("en-US", "en"),
        ("zh_Hant", "zh"),
        ("klingon", None),
        ("", None),
        (None, None),
    ],
)
def test_iso_language(value, expected):
    assert _iso_language(value) == expected


def _lang(payload: dict, hint=None) -> str:
    return OpenAIWhisperBackend._parse_result("whisper-1", payload, hint)[1]


def test_parse_result_maps_unmapped_short_names_correctly():
    assert _lang({"text": "x", "language": "malay"}) == "ms"
    assert _lang({"text": "x", "language": "welsh"}) == "cy"


def test_parse_result_unknown_name_falls_back_to_hint_then_en():
    assert _lang({"text": "x", "language": "klingon"}, hint="spanish") == "es"
    assert _lang({"text": "x", "language": "klingon"}, hint="fr-FR") == "fr"
    assert _lang({"text": "x", "language": "klingon"}) == "en"


def test_parse_result_gpt_transcribe_code():
    assert _lang({"text": "x", "languages": [{"code": "de"}]}) == "de"
