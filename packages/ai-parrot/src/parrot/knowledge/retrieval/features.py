"""`QueryFeatures` extractor — pure, sub-millisecond feature extraction.

Spec §4.2. The classifier's design principle: **it must never be the thing
that costs latency**. `extract_features` is a pure function — no I/O, no
LLM call, no clock (INV-3) — over cheap lexical markers (`MarkerLexicon`)
and the in-process `DerivedSymbolIndex` (TASK-2276, replacing the symbol
trie §4.2 originally — and incorrectly — assumed already existed).
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.lexicon import (
    DEFAULT_COMPILED_LEXICON,
    Interrogative,
    normalize_text,
)
from parrot.knowledge.retrieval.models import NodeRef
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

logger = logging.getLogger(__name__)

# Code-literal detection (spec §4.2: "backticks, snake_case, CamelCase,
# dotted paths"). Deliberately run against the ORIGINAL (case-preserved)
# query text, not the accent-normalized/lowercased form used for markers —
# CamelCase detection depends on case.
_BACKTICK_RE = re.compile(r"`[^`]+`")
_SNAKE_CASE_RE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]*\b")
_CAMEL_CASE_RE = re.compile(r"\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b")
_DOTTED_PATH_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")

# Candidate symbol-name tokens worth attempting a `DerivedSymbolIndex`
# lookup against — the same shapes `_has_code_literal` fires on, plus the
# backtick-quoted content itself (without the backticks).
_CANDIDATE_TOKEN_RE = re.compile(
    r"`([^`]+)`"
    r"|\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b"
    r"|\b([A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*)\b"
    r"|\b([a-z][a-z0-9]*_[a-z0-9_]*)\b"
)


class QueryFeatures(BaseModel):
    """Pure, cheap features extracted from a query (spec §4.2).

    Attributes:
        resolved_symbols: Distinct `NodeRef`s resolved from code-literal
            tokens in the query, via `DerivedSymbolIndex` — exact hits in
            the derived symbol index (TASK-2276), never a fuzzy/embedding
            match.
        anchor_count: Number of distinct resolved anchors — ambiguity
            (multiple candidates per token) is NOT collapsed, so this can
            legitimately exceed the number of code-literal tokens.
        has_relational_verb: A relational marker (calls/uses/imports/...,
            quién llama/usa/..., §4.2) was found.
        has_causal_marker: A causal marker (why/por qué/razón/...) was
            found.
        has_aggregation_marker: An aggregation marker (overview/cómo
            funciona/..., or the "how does ... work" template) was found.
        has_code_literal: A backtick span, snake_case, CamelCase, or dotted
            path was found in the raw query text.
        token_count: Whitespace-delimited token count of the raw query.
        interrogative: Which interrogative the query opens with, if any —
            see `Interrogative`. First-match-wins over
            `MarkerLexicon.interrogative_groups`'s priority order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolved_symbols: tuple[NodeRef, ...]
    anchor_count: int
    has_relational_verb: bool
    has_causal_marker: bool
    has_aggregation_marker: bool
    has_code_literal: bool
    token_count: int
    interrogative: Interrogative


def _has_code_literal(query: str) -> bool:
    """Whether `query` contains a backtick span, snake_case, CamelCase, or
    dotted path — evaluated on the raw, case-preserved query text."""
    return bool(
        _BACKTICK_RE.search(query)
        or _SNAKE_CASE_RE.search(query)
        or _CAMEL_CASE_RE.search(query)
        or _DOTTED_PATH_RE.search(query)
    )


def _candidate_symbol_tokens(query: str) -> tuple[str, ...]:
    """Extract code-literal-looking tokens worth a symbol-index lookup."""
    tokens: list[str] = []
    for match in _CANDIDATE_TOKEN_RE.finditer(query):
        token = next(group for group in match.groups() if group is not None)
        tokens.append(token)
    return tuple(dict.fromkeys(tokens))  # de-duplicate, preserve order


def extract_features(query: str, symbols: DerivedSymbolIndex) -> QueryFeatures:
    """Extract `QueryFeatures` from `query` (INV-3: pure — no I/O, no clock).

    Args:
        query: The natural-language query text.
        symbols: The `DerivedSymbolIndex` to resolve code-literal tokens
            against (in-process lookup only — no I/O).

    Returns:
        The extracted, deterministic `QueryFeatures`.
    """
    normalized = normalize_text(query)
    compiled = DEFAULT_COMPILED_LEXICON

    has_relational_verb = bool(compiled.relational_re.search(normalized))
    has_causal_marker = bool(compiled.causal_re.search(normalized))
    has_aggregation_marker = bool(compiled.aggregation_re.search(normalized)) or bool(
        compiled.aggregation_template_re.search(normalized)
    )

    interrogative = Interrogative.NONE
    for candidate, pattern in compiled.interrogative_patterns:
        if pattern.search(normalized):
            interrogative = candidate
            break

    resolved: dict[NodeRef, None] = {}
    for token in _candidate_symbol_tokens(query):
        for ref in symbols.resolve(token):
            resolved[ref] = None

    return QueryFeatures(
        resolved_symbols=tuple(resolved.keys()),
        anchor_count=len(resolved),
        has_relational_verb=has_relational_verb,
        has_causal_marker=has_causal_marker,
        has_aggregation_marker=has_aggregation_marker,
        has_code_literal=_has_code_literal(query),
        token_count=len(query.split()),
        interrogative=interrogative,
    )
