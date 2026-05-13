"""Verify the JSON-LD extractor module promotion (FEAT-154 / TASK-1048)."""


def test_jsonld_extractors_promoted_import() -> None:
    """The canonical module import resolves and exposes the registry + dataclass."""
    from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem

    assert isinstance(EXTRACTOR_REGISTRY, dict)
    assert "Product" in EXTRACTOR_REGISTRY
    assert "FAQPage" in EXTRACTOR_REGISTRY
    # JsonLdItem is a dataclass with the documented field set
    item = JsonLdItem(
        content_kind="test", source_type="test", page_content="x",
    )
    assert item.row_data == {}
    assert item.selector_name is None


def test_jsonld_extractors_backcompat_shim() -> None:
    """The old loader-side import path still works and refers to the same objects."""
    from parrot.utils.jsonld_extractors import (
        EXTRACTOR_REGISTRY as core_registry,
        JsonLdItem as CoreItem,
    )
    from parrot_loaders.jsonld_extractors import (
        EXTRACTOR_REGISTRY as shim_registry,
        JsonLdItem as ShimItem,
    )

    assert core_registry is shim_registry, (
        "Registry must be the same object — duplicate dicts cause silent drift"
    )
    assert CoreItem is ShimItem, (
        "JsonLdItem class must be identical between paths"
    )
