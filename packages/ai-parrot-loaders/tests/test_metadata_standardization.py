"""
Comprehensive parametrized tests for canonical metadata standardization.

FEAT-125 — AI-Parrot Loaders Metadata Standardization (TASK-861)

Verifies that every loader in LOADER_REGISTRY:
1. Produces a ``document_meta`` sub-dict with exactly the 5 canonical keys.
2. Places all non-canonical extras at the top level, never inside
   ``document_meta``.
3. Respects the ``language`` default from the loader instance.
"""
from __future__ import annotations

import importlib
from typing import Any

import pytest

from parrot_loaders import LOADER_REGISTRY
from .conftest import CANONICAL_DOC_META_KEYS, CANONICAL_TOP_LEVEL_KEYS

# ── Loader filtering helpers ──────────────────────────────────────────────────

# Entries in LOADER_REGISTRY that are NOT loader classes.
_NON_CLASS_ENTRIES: frozenset[str] = frozenset({"get_loader_class", "LOADER_MAPPING"})

# Abstract base classes that cannot be instantiated directly.
_ABSTRACT_BASES: frozenset[str] = frozenset({"BasePDF", "BaseVideoLoader"})

# All entries to skip entirely.
SKIP_NAMES: frozenset[str] = _NON_CLASS_ENTRIES | _ABSTRACT_BASES

# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_loader_class(dotted_path: str) -> type:
    """Import and return a loader class from its dotted import path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _try_instantiate(loader_name: str, loader_path: str) -> Any:
    """Try to get the loader class and instantiate it; skip on failure."""
    try:
        cls = _get_loader_class(loader_path)
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"Optional dependency missing for {loader_name}: {exc}")
    try:
        return cls()
    except Exception as exc:
        pytest.skip(f"Could not instantiate {loader_name}: {exc}")


# ── Parametrized tests ────────────────────────────────────────────────────────


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_create_metadata_canonical_shape(loader_name: str, loader_path: str) -> None:
    """Every loader's create_metadata() must produce the canonical top-level
    key set and a closed document_meta sub-dict.
    """
    if loader_name in SKIP_NAMES:
        pytest.skip(f"Skipping {loader_name}: abstract base or non-class entry")

    loader = _try_instantiate(loader_name, loader_path)
    meta = loader.create_metadata("test_source", doctype="test", source_type="test")

    missing_top = CANONICAL_TOP_LEVEL_KEYS - set(meta.keys())
    assert not missing_top, (
        f"{loader_name}: missing canonical top-level keys: {missing_top}"
    )
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS, (
        f"{loader_name}: document_meta keys mismatch — "
        f"got {set(meta['document_meta'].keys())}"
    )


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_document_meta_no_extra_keys(loader_name: str, loader_path: str) -> None:
    """Non-canonical kwargs must land at top level, never inside document_meta."""
    if loader_name in SKIP_NAMES:
        pytest.skip(f"Skipping {loader_name}: abstract base or non-class entry")

    loader = _try_instantiate(loader_name, loader_path)
    meta = loader.create_metadata(
        "test_source",
        doctype="test",
        source_type="test",
        extra_field="should_be_top_level",
        another_extra=42,
    )

    assert "extra_field" in meta, f"{loader_name}: extra_field not at top level"
    assert "another_extra" in meta, f"{loader_name}: another_extra not at top level"
    assert "extra_field" not in meta["document_meta"], (
        f"{loader_name}: extra_field leaked into document_meta"
    )
    assert "another_extra" not in meta["document_meta"], (
        f"{loader_name}: another_extra leaked into document_meta"
    )
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS, (
        f"{loader_name}: document_meta no longer closed-shape after extras"
    )


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_language_defaults_from_loader(loader_name: str, loader_path: str) -> None:
    """document_meta['language'] must default to the loader's language attribute."""
    if loader_name in SKIP_NAMES:
        pytest.skip(f"Skipping {loader_name}: abstract base or non-class entry")

    loader = _try_instantiate(loader_name, loader_path)
    meta = loader.create_metadata("test_source")
    assert meta["document_meta"]["language"] == loader.language, (
        f"{loader_name}: language in document_meta does not match loader.language"
    )


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_explicit_language_propagates(loader_name: str, loader_path: str) -> None:
    """Explicit language= argument must propagate to document_meta['language']."""
    if loader_name in SKIP_NAMES:
        pytest.skip(f"Skipping {loader_name}: abstract base or non-class entry")

    loader = _try_instantiate(loader_name, loader_path)
    meta = loader.create_metadata(
        "test_source", doctype="test", source_type="test", language="fr"
    )
    assert meta["document_meta"]["language"] == "fr", (
        f"{loader_name}: explicit language='fr' not reflected in document_meta"
    )


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_explicit_title_propagates(loader_name: str, loader_path: str) -> None:
    """Explicit title= argument must propagate to document_meta['title']."""
    if loader_name in SKIP_NAMES:
        pytest.skip(f"Skipping {loader_name}: abstract base or non-class entry")

    loader = _try_instantiate(loader_name, loader_path)
    meta = loader.create_metadata(
        "test_source", doctype="test", source_type="test", title="My Test Title"
    )
    assert meta["document_meta"]["title"] == "My Test Title", (
        f"{loader_name}: explicit title not reflected in document_meta"
    )


# ── Validate _validate_metadata ───────────────────────────────────────────────


def test_validate_metadata_auto_fills_missing_document_meta() -> None:
    """_validate_metadata must fill a missing document_meta and return the dict."""
    from parrot_loaders.txt import TextLoader
    loader = TextLoader()
    incomplete = {"url": "x", "source": "x"}
    result = loader._validate_metadata(incomplete)
    assert "document_meta" in result
    assert set(result["document_meta"].keys()) == CANONICAL_DOC_META_KEYS


def test_validate_metadata_does_not_raise_on_valid() -> None:
    """_validate_metadata must not raise on a fully-canonical metadata dict."""
    from parrot_loaders.txt import TextLoader
    loader = TextLoader()
    meta = loader.create_metadata(
        "test.txt", doctype="text", source_type="file"
    )
    result = loader._validate_metadata(meta)
    assert set(result["document_meta"].keys()) == CANONICAL_DOC_META_KEYS


# ── Extras preservation spot-checks ──────────────────────────────────────────


def test_file_loader_extras_preserved() -> None:
    """File loader extras (origin, table, schema, row_index) go to top level."""
    from parrot_loaders.csv import CSVLoader
    loader = CSVLoader()
    meta = loader.create_metadata(
        "data.csv",
        doctype="csv_row",
        source_type="file",
        row_index=5,
        row_count=100,
        schema={"col": "str"},
        table="my_table",
    )
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
    assert meta["row_index"] == 5
    assert meta["row_count"] == 100
    assert meta["schema"] == {"col": "str"}
    assert meta["table"] == "my_table"
    assert "row_index" not in meta["document_meta"]
    assert "table" not in meta["document_meta"]


def test_web_extras_preserved() -> None:
    """Web loader extras (content_kind, content_extraction) go to top level."""
    from parrot_loaders.webscraping import WebScrapingLoader
    loader = WebScrapingLoader()
    meta = loader.create_metadata(
        "https://example.com",
        doctype="webpage",
        source_type="url",
        content_kind="fragment",
        content_extraction="trafilatura",
        author="Test Author",
    )
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
    assert meta["content_kind"] == "fragment"
    assert meta["content_extraction"] == "trafilatura"
    assert meta["author"] == "Test Author"
    assert "content_kind" not in meta["document_meta"]
    assert "author" not in meta["document_meta"]


def test_video_extras_preserved() -> None:
    """Video loader extras (topic_tags, start, chunk_id) go to top level."""
    from parrot_loaders.youtube import YoutubeLoader
    loader = YoutubeLoader(language="en")
    meta = loader.create_metadata(
        "https://youtube.com/watch?v=abc",
        doctype="video_dialog",
        source_type="video",
        title="My Video",
        topic_tags=["AI", "ML"],
        start="00:01:00",
        end="00:01:30",
        chunk_id="10",
    )
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
    assert meta["topic_tags"] == ["AI", "ML"]
    assert meta["start"] == "00:01:00"
    assert meta["chunk_id"] == "10"
    assert "topic_tags" not in meta["document_meta"]
    assert "start" not in meta["document_meta"]
