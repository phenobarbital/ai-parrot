"""Backward-compat re-export. Canonical home is parrot.utils.jsonld_extractors."""
from parrot.utils.jsonld_extractors import (  # noqa: F401
    EXTRACTOR_REGISTRY,
    JsonLdItem,
    strip_html_text,
    faq_extractor,
    product_extractor,
    event_extractor,
    person_extractor,
    place_extractor,
    recipe_extractor,
    article_extractor,
    organization_extractor,
    howto_extractor,
    breadcrumb_extractor,
    question_extractor,
)

__all__ = (
    "EXTRACTOR_REGISTRY", "JsonLdItem", "strip_html_text",
    "faq_extractor", "product_extractor", "event_extractor",
    "person_extractor", "place_extractor", "recipe_extractor",
    "article_extractor", "organization_extractor", "howto_extractor",
    "breadcrumb_extractor", "question_extractor",
)
