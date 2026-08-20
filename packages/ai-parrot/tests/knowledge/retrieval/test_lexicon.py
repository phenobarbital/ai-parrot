"""Tests for TASK-2277: `MarkerLexicon` (ES/EN).

Spec: sdd/specs/graphindex-retriever.spec.md §4.2.
"""

from parrot.knowledge.retrieval.lexicon import (
    DEFAULT_COMPILED_LEXICON,
    DEFAULT_LEXICON,
    Interrogative,
    normalize_text,
)

_ES_EN_PAIRS = {
    "relational_verbs": [("calls", "quien llama"), ("uses", "usa"), ("imports", "importa")],
    "causal_markers": [("why", "por que"), ("reason", "razon")],
    "aggregation_markers": [("overview", "resumen"), ("architecture", "arquitectura")],
}


def test_es_en_marker_symmetry() -> None:
    for group_name, pairs in _ES_EN_PAIRS.items():
        markers = {normalize_text(m) for m in getattr(DEFAULT_LEXICON, group_name)}
        for en, es in pairs:
            assert normalize_text(en) in markers, f"{group_name}: missing EN {en!r}"
            assert normalize_text(es) in markers, f"{group_name}: missing ES {es!r}"


def test_interrogative_groups_cover_all_non_none_members() -> None:
    covered = {i for i, _ in DEFAULT_LEXICON.interrogative_groups}
    assert covered == {
        Interrogative.WHAT,
        Interrogative.WHERE,
        Interrogative.WHO,
        Interrogative.WHY,
        Interrogative.HOW,
    }


def test_why_checked_before_what() -> None:
    order = [i for i, _ in DEFAULT_LEXICON.interrogative_groups]
    assert order.index(Interrogative.WHY) < order.index(Interrogative.WHAT)


def test_por_que_matches_why_not_what() -> None:
    normalized = normalize_text("¿por qué falla esto?")
    for interrogative, pattern in DEFAULT_COMPILED_LEXICON.interrogative_patterns:
        if pattern.search(normalized):
            assert interrogative == Interrogative.WHY
            break
    else:
        raise AssertionError("expected a WHY match")


def test_bare_que_matches_what() -> None:
    normalized = normalize_text("¿qué hace esta función?")
    for interrogative, pattern in DEFAULT_COMPILED_LEXICON.interrogative_patterns:
        if pattern.search(normalized):
            assert interrogative == Interrogative.WHAT
            break
    else:
        raise AssertionError("expected a WHAT match")


def test_accent_insensitive_causal_match() -> None:
    assert DEFAULT_COMPILED_LEXICON.causal_re.search(normalize_text("por qué"))
    assert DEFAULT_COMPILED_LEXICON.causal_re.search(normalize_text("por que"))


def test_aggregation_template_how_does_x_work() -> None:
    normalized = normalize_text("how does the outputs module work")
    assert DEFAULT_COMPILED_LEXICON.aggregation_template_re.search(normalized)


def test_normalize_text_strips_accents_and_lowercases() -> None:
    assert normalize_text("Por Qué") == "por que"
    assert normalize_text("CÓMO") == "como"


def test_lexicon_is_frozen() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DEFAULT_LEXICON.version = "v2"  # type: ignore[misc]
