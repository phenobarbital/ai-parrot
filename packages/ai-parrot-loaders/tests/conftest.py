"""
Shared fixtures and constants for ai-parrot-loaders test suite.

FEAT-125 — AI-Parrot Loaders Metadata Standardization
"""
from __future__ import annotations

import pytest

# ── Canonical metadata shape constants ───────────────────────────────────────

#: The exact set of keys that must appear in every Document.metadata["document_meta"].
CANONICAL_DOC_META_KEYS: frozenset[str] = frozenset(
    {"source_type", "category", "type", "language", "title"}
)

#: Top-level keys that every canonical Document.metadata must contain.
CANONICAL_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"url", "source", "filename", "type", "source_type", "created_at", "category", "document_meta"}
)


@pytest.fixture
def canonical_doc_meta_keys() -> frozenset[str]:
    """Return the canonical document_meta key set."""
    return CANONICAL_DOC_META_KEYS


@pytest.fixture
def canonical_top_level_keys() -> frozenset[str]:
    """Return the canonical top-level metadata key set."""
    return CANONICAL_TOP_LEVEL_KEYS
