"""TextMatcher.check_text_match: ``exact`` is a whole-phrase match, never a fuzzy one."""

import pytest

from parrot.models.compliance import TextMatcher
from parrot.models.detections import TextRequirement


def _match(required: str, features: list[str], match_type: str, **kwargs):
    return TextMatcher.check_text_match(
        required_text=required, visual_features=features, match_type=match_type, **kwargs
    )


@pytest.mark.parametrize(
    ("required", "feature"),
    [
        ("EcoTank Printers", "EcoTank Printers"),
        ("EcoTank Printers", "EPSON EcoTank Printers 100 MILLION SOLD"),
        ("Hello Savings", "Goodbye Cartridges. Hello Savings."),
        ("Why is Epson EcoTank", "Why Is Epson EcoTank a Better Way to Print?"),
        ("Cartridge-free Printing", "cartridge free printing"),
        ("EcoTank Printers", "ocr:EcoTank  Printers"),
    ],
)
def test_exact_finds_the_whole_phrase(required: str, feature: str) -> None:
    result = _match(required, ["unrelated text", feature], "exact")
    assert result.found is True
    assert result.confidence == 1.0
    assert result.match_type == "exact"


@pytest.mark.parametrize(
    ("required", "feature"),
    [
        ("Hello Savings", "Hello Savers"),
        ("Goodbye Cartridges", "Goodbye Cartridge"),
        ("Special Offer", "Special Offers"),
        ("EPSON", "EPSONS ecotank"),
        ("EcoTank Printers", "EcoTank"),
        ("EcoTank Printers", "Eco Tank Printers"),
        ("Choose The Right EcoTank For You", "Choose The Right EcoTank"),
    ],
)
def test_exact_rejects_near_misses(required: str, feature: str) -> None:
    result = _match(required, [feature], "exact", confidence_threshold=0.0)
    assert result.found is False
    assert result.confidence == 0.0
    assert result.match_type == "exact"


def test_exact_never_joins_phrases_across_features() -> None:
    assert _match("Goodbye Cartridges", ["Goodbye", "Cartridges"], "exact").found is False


def test_exact_case_sensitive() -> None:
    assert _match("EPSON", ["EPSON EcoTank"], "exact", case_sensitive=True).found is True
    assert _match("EPSON", ["Epson EcoTank"], "exact", case_sensitive=True).found is False
    assert _match("EPSON", ["Epson EcoTank"], "exact").found is True


def test_exact_without_evidence_or_text() -> None:
    assert _match("EPSON", [], "exact").found is False
    assert _match("!!!", ["EPSON"], "exact").found is False


def test_contains_stays_a_substring_match() -> None:
    assert _match("EPSON", ["EPSONS ecotank"], "contains").found is True
    assert _match("Goodbye Cartridges", ["Goodbye Cartridge"], "contains").found is False


def test_auto_keeps_its_fuzzy_fallback() -> None:
    result = _match("Hello Savings", ["Hello Savers"], "auto", confidence_threshold=0.7)
    assert result.found is True
    assert result.match_type == "fuzzy"


def test_exact_requirement_round_trip() -> None:
    requirement = TextRequirement(required_text="Hello Savings", match_type="exact")
    result = _match(requirement.required_text, ["Hello Savers"], requirement.match_type)
    assert result.found is False
