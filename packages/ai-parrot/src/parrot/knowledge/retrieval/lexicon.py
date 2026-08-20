"""`MarkerLexicon` — locale-aware (ES/EN) markers for the query classifier.

Spec §4.2. Markers live in a frozen, versioned, declarative lexicon so the
`QueryClassifier` (TASK-2278) stays declarative and testable rather than a
pile of inline regexes. Precompiled once, at lexicon construction, so
lookups stay sub-millisecond (spec §4: "the classifier must never be the
thing that costs latency").
"""

from __future__ import annotations

import logging
import re
import unicodedata
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class Interrogative(StrEnum):
    """Which interrogative word (if any) a query opens with (spec §4.2)."""

    WHAT = "what"
    WHERE = "where"
    WHO = "who"
    WHY = "why"
    HOW = "how"
    NONE = "none"


def normalize_text(text: str) -> str:
    """Lowercase and strip accents so ``por qué``/``por que`` match alike.

    Args:
        text: Raw input text.

    Returns:
        Lowercased text with combining diacritical marks removed (NFKD
        normalization, then combining marks dropped).
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _compile_marker_group(markers: tuple[str, ...]) -> re.Pattern[str]:
    """Compile a tuple of markers into one word-boundaried alternation.

    Args:
        markers: Marker strings, as authored (may contain accents/spaces).

    Returns:
        A single compiled pattern matching any marker, accent-normalized.
    """
    normalized_markers = sorted({normalize_text(m) for m in markers}, key=len, reverse=True)
    alternation = "|".join(re.escape(m) for m in normalized_markers)
    return re.compile(rf"\b(?:{alternation})\b")


class MarkerLexicon(BaseModel):
    """Frozen, versioned marker groups the classifier's features key off.

    Attributes:
        version: Bumped whenever markers change, so a replayed trace can
            tell which lexicon version produced a given `QueryFeatures`.
        relational_verbs: Verbs/phrases signalling a `RELATIONAL` query
            (spec §4.1) — "who calls X", "what does X use", etc.
        causal_markers: Markers signalling a `RATIONALE` query — "why",
            "por qué", "razón", etc.
        aggregation_markers: Markers signalling a `GLOBAL_SUMMARY` query —
            "overview", "cómo funciona", etc.
        interrogative_groups: Ordered ``(Interrogative, markers)`` pairs.
            Order is priority: checked first-match-wins, so ``"por qué"``
            (WHY) is checked before bare ``"qué"`` (WHAT) — a query
            containing "por qué" must resolve to WHY, never WHAT.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "v1"
    relational_verbs: tuple[str, ...]
    causal_markers: tuple[str, ...]
    aggregation_markers: tuple[str, ...]
    interrogative_groups: tuple[tuple[Interrogative, tuple[str, ...]], ...]


class CompiledMarkerLexicon:
    """Precompiled view of a `MarkerLexicon` — built once, reused per call.

    Regex compilation happens here, at construction, never inside
    `extract_features` — that is the whole point of precompiling (spec §4:
    the classifier must never cost latency).
    """

    def __init__(self, lexicon: MarkerLexicon) -> None:
        """Compile every marker group in `lexicon` into a `re.Pattern`.

        Args:
            lexicon: The `MarkerLexicon` to compile.
        """
        self.lexicon = lexicon
        self.relational_re = _compile_marker_group(lexicon.relational_verbs)
        self.causal_re = _compile_marker_group(lexicon.causal_markers)
        self.aggregation_re = _compile_marker_group(lexicon.aggregation_markers)
        # "how does ... work" (spec §4.2) is a discontinuous template, not a
        # literal marker — compiled separately rather than escaped verbatim.
        self.aggregation_template_re = re.compile(r"\bhow does\b.*\bwork\b")
        self.interrogative_patterns: tuple[tuple[Interrogative, re.Pattern[str]], ...] = tuple(
            (interrogative, _compile_marker_group(markers))
            for interrogative, markers in lexicon.interrogative_groups
        )


#: The default ES/EN lexicon (spec §4.2). ES and EN entries are symmetric —
#: every group carries a counterpart in both languages.
DEFAULT_LEXICON = MarkerLexicon(
    version="v1",
    relational_verbs=(
        "calls",
        "uses",
        "imports",
        "depends",
        "extends",
        "quien llama",
        "usa",
        "importa",
        "depende",
        "hereda",
    ),
    causal_markers=(
        "why",
        "rationale",
        "reason",
        "por que",
        "razon",
        "decision",
        "motivo",
    ),
    aggregation_markers=(
        "overview",
        "architecture",
        "summary",
        "como funciona",
        "arquitectura",
        "resumen",
        "todos los",
    ),
    interrogative_groups=(
        # WHY before WHAT/WHO/WHERE/HOW: "por qué" must never be classified
        # as bare "qué" (WHAT).
        (Interrogative.WHY, ("why", "por que")),
        (Interrogative.WHO, ("who", "quien")),
        (Interrogative.WHERE, ("where", "donde")),
        (Interrogative.HOW, ("how", "como")),
        (Interrogative.WHAT, ("what", "que")),
    ),
)

#: Precompiled once at import time — reused by every `extract_features` call.
DEFAULT_COMPILED_LEXICON = CompiledMarkerLexicon(DEFAULT_LEXICON)
