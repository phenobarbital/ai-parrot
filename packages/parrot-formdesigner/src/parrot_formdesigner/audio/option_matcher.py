"""Deterministic transcript → option matching (FEAT-649, Module 4)."""
from __future__ import annotations

import difflib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.types import FieldType
from .models import OptionMatch, ReviewItemData
from .narration.lexicon import Lexicon, normalize

try:  # optional accelerator, never a declared dependency
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:  # pragma: no cover - depends on environment
    _rf_fuzz = None

_TIE_DELTA = 0.05
_NUMERIC_TYPES = frozenset({FieldType.LIKERT, FieldType.NPS, FieldType.RANKING})
# Words that may surround a number without changing its meaning ("la 3", "opción 3", "the second one").
_FILLER_TOKENS = frozenset({
    "la", "el", "lo", "las", "los", "opcion", "opciones", "numero", "de", "del", "al", "option", "number",
    "the", "a", "an", "one", "of", "choice", "item",
})
_STATUS_RANK = {"accepted": 0, "confirm": 1, "no_match": 2}


class MatchOutcome(BaseModel):
    """Result of matching one transcript against a question's options."""

    status: Literal["accepted", "confirm", "no_match"]
    match: OptionMatch | None = None
    alternatives: list[OptionMatch] = Field(default_factory=list)
    matches: list[OptionMatch] = Field(default_factory=list)   # MULTI_SELECT results


def _enabled(options: list[dict]) -> list[dict]:
    """Drop disabled options (S4); a missing ``disabled`` key means enabled."""
    return [o for o in options if not o.get("disabled", False)]


def _candidate(opt: dict, method: str, score: float) -> OptionMatch:
    return OptionMatch(value=opt["value"], label=str(opt.get("label", opt["value"])), method=method, score=score)


def _norm_label(opt: dict, lexicon: Lexicon) -> str:
    return normalize(str(opt.get("label", "")), lexicon)


def _norm_value(opt: dict, lexicon: Lexicon) -> str:
    return normalize(str(opt["value"]), lexicon)


def _has_phrase(text: str, phrase: str) -> bool:
    """Whole-word phrase containment on already-normalised strings."""
    return bool(phrase) and f" {phrase} " in f" {text} "


def _number_tokens(text: str, lexicon: Lexicon) -> tuple[list[int], list[int], bool]:
    """Return (ordinal values, cardinal/digit values, only_filler_otherwise)."""
    ordinals: list[int] = []
    cardinals: list[int] = []
    clean = True
    for tok in text.split():
        if tok in lexicon.ordinals:
            ordinals.append(lexicon.ordinals[tok])
        elif tok in lexicon.cardinals:
            cardinals.append(lexicon.cardinals[tok])
        elif re.fullmatch(r"\d+", tok):
            cardinals.append(int(tok))
        elif tok not in _FILLER_TOKENS:
            clean = False
    return ordinals, cardinals, clean


def _single_number(text: str, lexicon: Lexicon) -> int | None:
    """Resolve a transcript that is just a (possibly decorated) number; ordinals win over cardinals."""
    ordinals, cardinals, clean = _number_tokens(text, lexicon)
    if not clean:
        return None
    if ordinals:
        return ordinals[0]
    if len(set(cardinals)) == 1:
        return cardinals[0]
    return None


def _by_exact(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    """Normalised equality against value or label."""
    if not text:
        return []
    return [
        _candidate(o, "exact", 1.0)
        for o in options
        if text in (_norm_value(o, lexicon), _norm_label(o, lexicon))
    ]


def _by_ordinal(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    """Ordinal / cardinal / digit → 1-based index into the enabled options; -1 is the last."""
    n = _single_number(text, lexicon)
    if n is None or not options:
        return []
    if n == -1:
        return [_candidate(options[-1], "ordinal", 1.0)]
    if 1 <= n <= len(options):
        return [_candidate(options[n - 1], "ordinal", 1.0)]
    return []


def _by_yes_no(text: str, options: list[dict], lexicon: Lexicon, field_type: FieldType) -> list[OptionMatch]:
    """BOOLEAN only: lexicon yes → True, no → False."""
    if field_type != FieldType.BOOLEAN or not text:
        return []

    def _hit(phrases: list[str]) -> bool:
        return any(text == p or text.startswith(p + " ") for p in phrases)

    is_yes, is_no = _hit(lexicon.yes), _hit(lexicon.no)
    if is_yes == is_no:
        return []
    value = is_yes
    phrases = lexicon.yes if value else lexicon.no
    return [OptionMatch(value=value, label=phrases[0] if phrases else str(value), method="yes_no", score=1.0)]


def _by_numeric(text: str, options: list[dict], lexicon: Lexicon, field_type: FieldType) -> list[OptionMatch]:
    """LIKERT/NPS/RANKING: spoken number → option whose value/label is that number."""
    if field_type not in _NUMERIC_TYPES:
        return []
    ordinals, cardinals, clean = _number_tokens(text, lexicon)
    if not clean or ordinals or len(set(cardinals)) != 1:
        return []
    n = str(cardinals[0])
    hits = [o for o in options if n in (_norm_value(o, lexicon), _norm_label(o, lexicon))]
    if hits:
        return [_candidate(o, "numeric", 1.0) for o in hits]
    if not options and field_type == FieldType.NPS and 0 <= cardinals[0] <= 10:
        return [OptionMatch(value=cardinals[0], label=n, method="numeric", score=1.0)]
    return []


def _by_contains(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    """Options whose normalised label is inside the text (or the text inside the label)."""
    if not text:
        return []
    hits: list[OptionMatch] = []
    for o in options:
        label = _norm_label(o, lexicon)
        if not label:
            continue
        if _has_phrase(text, label) or (len(text) >= 3 and _has_phrase(label, text)):
            hits.append(_candidate(o, "contains", 0.9))
    return hits


def _ratio(a: str, b: str) -> float:
    if _rf_fuzz is not None:
        return float(_rf_fuzz.ratio(a, b)) / 100.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _by_fuzzy(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    """Similarity ratio per option label, best first."""
    scored = [_candidate(o, "fuzzy", _ratio(text, _norm_label(o, lexicon))) for o in options]
    return sorted(scored, key=lambda m: m.score, reverse=True)


def _match_single(text: str, options: list[dict], *, field_type: FieldType, lexicon: Lexicon) -> list[OptionMatch]:
    """Run the methods in the fixed order; return the first non-empty candidate list (best first)."""
    finders = [lambda: _by_exact(text, options, lexicon)]
    if field_type not in _NUMERIC_TYPES:  # a spoken "3" on a scale is a value, not a position
        finders.append(lambda: _by_ordinal(text, options, lexicon))
    finders += [
        lambda: _by_yes_no(text, options, lexicon, field_type),
        lambda: _by_numeric(text, options, lexicon, field_type),
        lambda: _by_contains(text, options, lexicon),
        lambda: _by_fuzzy(text, options, lexicon),
    ]
    for finder in finders:
        found = finder()
        if found:
            return sorted(found, key=lambda m: m.score, reverse=True)
    return []


def _decide(text: str, enabled: list[dict], *, field_type: FieldType, lexicon: Lexicon, threshold: float,
            confirm_floor: float, factor: float) -> MatchOutcome:
    """Single-value decision: scoring, thresholds and tie rule."""
    ranked = [
        m.model_copy(update={"score": m.score * factor})
        for m in _match_single(text, enabled, field_type=field_type, lexicon=lexicon)
    ]
    if not ranked:
        return MatchOutcome(status="no_match")
    best = ranked[0]
    if len(ranked) > 1 and best.score - ranked[1].score < _TIE_DELTA and ranked[1].score >= confirm_floor:
        return MatchOutcome(status="confirm", match=best, alternatives=ranked[:2])
    if best.score >= threshold:
        return MatchOutcome(status="accepted", match=best, alternatives=ranked[1:3])
    if best.score >= confirm_floor:
        return MatchOutcome(status="confirm", match=best, alternatives=ranked[1:3])
    return MatchOutcome(status="no_match", alternatives=ranked[:3])


def _split_conjunctions(text: str, lexicon: Lexicon) -> list[str]:
    """Split a normalised transcript on whole-word conjunctions."""
    conj = set(lexicon.conjunctions)
    pieces: list[str] = []
    current: list[str] = []
    for tok in text.split():
        if tok in conj:
            if current:
                pieces.append(" ".join(current))
            current = []
        else:
            current.append(tok)
    if current:
        pieces.append(" ".join(current))
    return pieces


def match_option(transcript: str, options: list[dict], *, field_type: FieldType, lexicon: Lexicon, threshold: float = 0.8,
                 confirm_floor: float = 0.6, stt_confidence: float | None = None, multi: bool = False) -> MatchOutcome:
    """exact → ordinal → yes/no → numeric → unique contains → fuzzy; disabled options never match; ties → confirm."""
    factor = stt_confidence if stt_confidence is not None else 1.0
    text = normalize(transcript, lexicon)
    enabled = _enabled(options)
    kwargs: dict[str, Any] = {
        "field_type": field_type, "lexicon": lexicon, "threshold": threshold,
        "confirm_floor": confirm_floor, "factor": factor,
    }
    if not multi:
        return _decide(text, enabled, **kwargs)

    if text and text in lexicon.none:
        return MatchOutcome(status="accepted")
    if text and text in lexicon.all:
        every = [_candidate(o, "exact", 1.0 * factor) for o in enabled]
        return MatchOutcome(status="accepted" if every else "no_match", matches=every)
    # Whole-text exact first so labels that contain a conjunction ("Rojo y verde") survive.
    whole = _by_exact(text, enabled, lexicon)
    if whole:
        scored = [m.model_copy(update={"score": m.score * factor}) for m in whole[:1]]
        status = "accepted" if scored[0].score >= threshold else "confirm"
        return MatchOutcome(status=status, match=scored[0], matches=scored)
    kept: list[OptionMatch] = []
    worst = "accepted"
    for piece in _split_conjunctions(text, lexicon):
        out = _decide(piece, enabled, **kwargs)
        if out.match is None or out.match.score < confirm_floor:
            continue
        if _STATUS_RANK[out.status] > _STATUS_RANK[worst]:
            worst = out.status
        if all(out.match.value != k.value for k in kept):
            kept.append(out.match)
    if not kept:
        return MatchOutcome(status="no_match")
    return MatchOutcome(status=worst, match=kept[0], matches=kept)  # type: ignore[arg-type]


def match_review_item(transcript: str, items: list[ReviewItemData], lexicon: Lexicon) -> int | None:
    """'cambiar la N' / label match → item position; None when not a change request."""
    text = normalize(transcript, lexicon)
    phrase = next((p for p in sorted(lexicon.review_change, key=len, reverse=True) if _has_phrase(text, p)), None)
    if phrase is None or not items:
        return None
    rest = f" {text} ".replace(f" {phrase} ", " ", 1).strip()
    positions = {it.position for it in items}
    n = _single_number(rest, lexicon)
    if n is not None:
        if n == -1:
            return max(positions)
        return n if n in positions else None
    if not rest:
        return None
    labels = [(it.position, normalize(it.label, lexicon)) for it in items]
    exact = [pos for pos, lab in labels if lab == rest]
    if len(exact) == 1:
        return exact[0]
    contains = [pos for pos, lab in labels if lab and (_has_phrase(rest, lab) or _has_phrase(lab, rest))]
    return contains[0] if len(contains) == 1 else None
