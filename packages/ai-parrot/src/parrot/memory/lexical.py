"""Shared Unicode-aware lexical normalization for memory retrieval."""

import re

MIN_TERM_LENGTH = 3


def query_terms(text: str) -> tuple[str, ...]:
    """Return distinct case-folded words of length at least three in first-seen order."""
    terms: list[str] = []
    seen: set[str] = set()
    for term in re.findall(r"\w+", text.casefold()):
        if len(term) < MIN_TERM_LENGTH or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return tuple(terms)
