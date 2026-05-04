"""Unit tests for parrot_loaders.jsonld_extractors.

Tests cover:
- strip_html_text utility
- Each individual extractor function
- EXTRACTOR_REGISTRY completeness and alias correctness
"""

import pytest
from parrot_loaders.jsonld_extractors import (
    EXTRACTOR_REGISTRY,
    JsonLdItem,
    article_extractor,
    breadcrumb_extractor,
    event_extractor,
    faq_extractor,
    howto_extractor,
    organization_extractor,
    person_extractor,
    place_extractor,
    product_extractor,
    recipe_extractor,
    strip_html_text,
)


# ---------------------------------------------------------------------------
# strip_html_text
# ---------------------------------------------------------------------------


class TestStripHtmlText:
    """Tests for the strip_html_text utility function."""

    def test_strips_tags(self) -> None:
        assert strip_html_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_decodes_entities(self) -> None:
        assert strip_html_text("AT&amp;T &amp; Verizon") == "AT&T & Verizon"

    def test_collapses_whitespace(self) -> None:
        assert strip_html_text("  lots   of   space  ") == "lots of space"

    def test_handles_none(self) -> None:
        assert strip_html_text(None) == ""

    def test_handles_non_string(self) -> None:
        assert strip_html_text(42) == "42"

    def test_handles_nested_html(self) -> None:
        result = strip_html_text("<p>A <a href='x'>link</a> here</p>")
        assert result == "A link here"

    def test_nbsp_collapses(self) -> None:
        result = strip_html_text("hello&nbsp;world")
        assert result == "hello world"


# ---------------------------------------------------------------------------
# faq_extractor
# ---------------------------------------------------------------------------


class TestFaqExtractor:
    """Tests for faq_extractor."""

    def test_basic_faq(self) -> None:
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "What is X?",
                    "acceptedAnswer": {"@type": "Answer", "text": "X is great."},
                }
            ],
        }
        items = faq_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "faq"
        assert items[0].source_type == "faq-jsonld"
        assert items[0].selector_name == "faq"
        assert "Q: What is X?" in items[0].page_content
        assert "A: X is great." in items[0].page_content

    def test_multiple_questions(self) -> None:
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "Q1?",
                    "acceptedAnswer": {"@type": "Answer", "text": "A1."},
                },
                {
                    "@type": "Question",
                    "name": "Q2?",
                    "acceptedAnswer": {"@type": "Answer", "text": "A2."},
                },
            ],
        }
        items = faq_extractor(node)
        assert len(items) == 2

    def test_empty_main_entity(self) -> None:
        assert faq_extractor({"@type": "FAQPage", "mainEntity": []}) == []

    def test_missing_main_entity(self) -> None:
        assert faq_extractor({"@type": "FAQPage"}) == []

    def test_html_in_answer_stripped(self) -> None:
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "Who?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": "<p>It is <b>Bob</b></p>",
                    },
                }
            ],
        }
        items = faq_extractor(node)
        assert len(items) == 1
        assert "It is Bob" in items[0].page_content

    def test_row_data_keys(self) -> None:
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "Q?",
                    "acceptedAnswer": {"@type": "Answer", "text": "A."},
                }
            ],
        }
        item = faq_extractor(node)[0]
        assert "question" in item.row_data
        assert "answer" in item.row_data

    def test_skips_missing_answer(self) -> None:
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": "Q?", "acceptedAnswer": {}},
            ],
        }
        assert faq_extractor(node) == []

    def test_page_content_format(self) -> None:
        node = {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "What is Y?",
                    "acceptedAnswer": {"@type": "Answer", "text": "Y is fine."},
                }
            ],
        }
        item = faq_extractor(node)[0]
        assert item.page_content == "Q: What is Y?\n\nA: Y is fine."


# ---------------------------------------------------------------------------
# product_extractor
# ---------------------------------------------------------------------------


class TestProductExtractor:
    """Tests for product_extractor."""

    def test_basic_product(self) -> None:
        node = {
            "@type": "Product",
            "name": "Widget Pro",
            "description": "A great widget.",
            "offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"},
        }
        items = product_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-product"
        assert items[0].source_type == "product-jsonld"
        assert "Widget Pro" in items[0].page_content
        assert items[0].row_data["name"] == "Widget Pro"

    def test_missing_name_returns_empty(self) -> None:
        assert product_extractor({"@type": "Product"}) == []

    def test_includes_price(self) -> None:
        node = {
            "@type": "Product",
            "name": "Gadget",
            "offers": {"price": "9.99", "priceCurrency": "EUR"},
        }
        item = product_extractor(node)[0]
        assert "9.99" in item.page_content

    def test_includes_brand(self) -> None:
        node = {
            "@type": "Product",
            "name": "Phone",
            "brand": {"@type": "Brand", "name": "Acme"},
        }
        item = product_extractor(node)[0]
        assert "Acme" in item.page_content

    def test_offers_list(self) -> None:
        node = {
            "@type": "Product",
            "name": "Item",
            "offers": [
                {"price": "5.00", "priceCurrency": "USD"},
                {"price": "6.00", "priceCurrency": "USD"},
            ],
        }
        item = product_extractor(node)[0]
        assert "5.00" in item.page_content

    def test_selector_name(self) -> None:
        node = {"@type": "Product", "name": "X"}
        assert product_extractor(node)[0].selector_name == "product"


# ---------------------------------------------------------------------------
# event_extractor
# ---------------------------------------------------------------------------


class TestEventExtractor:
    """Tests for event_extractor."""

    def test_basic_event(self) -> None:
        node = {
            "@type": "Event",
            "name": "Tech Conf",
            "startDate": "2026-09-15",
            "location": {"@type": "Place", "name": "Convention Center"},
        }
        items = event_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-event"
        assert "Tech Conf" in items[0].page_content

    def test_missing_name_returns_empty(self) -> None:
        assert event_extractor({"@type": "Event"}) == []

    def test_includes_dates(self) -> None:
        node = {
            "@type": "Event",
            "name": "Conf",
            "startDate": "2026-01-01",
            "endDate": "2026-01-03",
        }
        item = event_extractor(node)[0]
        assert "2026-01-01" in item.page_content
        assert "2026-01-03" in item.page_content

    def test_performer_list(self) -> None:
        node = {
            "@type": "Event",
            "name": "Festival",
            "performer": [
                {"@type": "Person", "name": "Alice"},
                {"@type": "Person", "name": "Bob"},
            ],
        }
        item = event_extractor(node)[0]
        assert "Alice" in item.page_content
        assert "Bob" in item.page_content


# ---------------------------------------------------------------------------
# person_extractor
# ---------------------------------------------------------------------------


class TestPersonExtractor:
    """Tests for person_extractor."""

    def test_basic_person(self) -> None:
        node = {"@type": "Person", "name": "Jane Doe", "jobTitle": "Engineer"}
        items = person_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-person"

    def test_missing_name_returns_empty(self) -> None:
        assert person_extractor({"@type": "Person"}) == []

    def test_includes_job_title(self) -> None:
        node = {"@type": "Person", "name": "Alice", "jobTitle": "CEO"}
        item = person_extractor(node)[0]
        assert "CEO" in item.page_content

    def test_includes_affiliation(self) -> None:
        node = {
            "@type": "Person",
            "name": "Bob",
            "affiliation": {"@type": "Organization", "name": "Acme Corp"},
        }
        item = person_extractor(node)[0]
        assert "Acme Corp" in item.page_content


# ---------------------------------------------------------------------------
# place_extractor
# ---------------------------------------------------------------------------


class TestPlaceExtractor:
    """Tests for place_extractor."""

    def test_local_business(self) -> None:
        node = {
            "@type": "LocalBusiness",
            "name": "Joe's Pizza",
            "address": "123 Main St",
        }
        items = place_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-place"

    def test_missing_name_returns_empty(self) -> None:
        assert place_extractor({"@type": "Place"}) == []

    def test_structured_address(self) -> None:
        node = {
            "@type": "LocalBusiness",
            "name": "Cafe",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "1 Main St",
                "addressLocality": "Springfield",
                "addressCountry": "US",
            },
        }
        item = place_extractor(node)[0]
        assert "1 Main St" in item.page_content
        assert "Springfield" in item.page_content

    def test_geo_coordinates(self) -> None:
        node = {
            "@type": "Place",
            "name": "HQ",
            "geo": {"@type": "GeoCoordinates", "latitude": "37.77", "longitude": "-122.41"},
        }
        item = place_extractor(node)[0]
        assert "37.77" in item.page_content


# ---------------------------------------------------------------------------
# recipe_extractor
# ---------------------------------------------------------------------------


class TestRecipeExtractor:
    """Tests for recipe_extractor."""

    def test_basic_recipe(self) -> None:
        node = {
            "@type": "Recipe",
            "name": "Chocolate Cake",
            "recipeIngredient": ["flour", "sugar", "cocoa"],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Mix dry ingredients."}
            ],
        }
        items = recipe_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-recipe"

    def test_missing_name_returns_empty(self) -> None:
        assert recipe_extractor({"@type": "Recipe"}) == []

    def test_includes_ingredients(self) -> None:
        node = {
            "@type": "Recipe",
            "name": "Cake",
            "recipeIngredient": ["flour", "eggs"],
        }
        item = recipe_extractor(node)[0]
        assert "flour" in item.page_content
        assert "eggs" in item.page_content

    def test_row_data_has_lists(self) -> None:
        node = {
            "@type": "Recipe",
            "name": "Soup",
            "recipeIngredient": ["water", "salt"],
            "recipeInstructions": [{"@type": "HowToStep", "text": "Boil."}],
        }
        item = recipe_extractor(node)[0]
        assert isinstance(item.row_data["ingredients"], list)
        assert isinstance(item.row_data["instructions"], list)

    def test_string_instruction(self) -> None:
        node = {
            "@type": "Recipe",
            "name": "Tea",
            "recipeInstructions": "Boil water.",
        }
        item = recipe_extractor(node)[0]
        assert "Boil water." in item.page_content


# ---------------------------------------------------------------------------
# article_extractor
# ---------------------------------------------------------------------------


class TestArticleExtractor:
    """Tests for article_extractor."""

    def test_basic_article(self) -> None:
        node = {
            "@type": "Article",
            "headline": "Breaking News",
            "author": {"@type": "Person", "name": "Reporter"},
            "datePublished": "2026-01-15",
        }
        items = article_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-article"

    def test_uses_name_fallback(self) -> None:
        node = {"@type": "NewsArticle", "name": "Big Story"}
        items = article_extractor(node)
        assert len(items) == 1
        assert "Big Story" in items[0].page_content

    def test_missing_headline_and_name_returns_empty(self) -> None:
        assert article_extractor({"@type": "Article"}) == []

    def test_author_list(self) -> None:
        node = {
            "@type": "Article",
            "headline": "Story",
            "author": [
                {"@type": "Person", "name": "Alice"},
                {"@type": "Person", "name": "Bob"},
            ],
        }
        item = article_extractor(node)[0]
        assert "Alice" in item.page_content
        assert "Bob" in item.page_content

    def test_includes_date(self) -> None:
        node = {
            "@type": "BlogPosting",
            "headline": "Post",
            "datePublished": "2026-03-01",
        }
        item = article_extractor(node)[0]
        assert "2026-03-01" in item.page_content


# ---------------------------------------------------------------------------
# organization_extractor
# ---------------------------------------------------------------------------


class TestOrganizationExtractor:
    """Tests for organization_extractor."""

    def test_basic_org(self) -> None:
        node = {"@type": "Organization", "name": "Acme Corp", "url": "https://acme.com"}
        items = organization_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-organization"

    def test_missing_name_returns_empty(self) -> None:
        assert organization_extractor({"@type": "Organization"}) == []

    def test_includes_url(self) -> None:
        node = {"@type": "Organization", "name": "Corp", "url": "https://corp.com"}
        item = organization_extractor(node)[0]
        assert "https://corp.com" in item.page_content

    def test_includes_contact(self) -> None:
        node = {
            "@type": "Organization",
            "name": "Corp",
            "telephone": "+1-800-555-0100",
            "email": "info@corp.com",
        }
        item = organization_extractor(node)[0]
        assert "+1-800-555-0100" in item.page_content
        assert "info@corp.com" in item.page_content


# ---------------------------------------------------------------------------
# howto_extractor
# ---------------------------------------------------------------------------


class TestHowToExtractor:
    """Tests for howto_extractor."""

    def test_basic_howto(self) -> None:
        node = {
            "@type": "HowTo",
            "name": "Change a Tire",
            "step": [
                {"@type": "HowToStep", "text": "Loosen the nuts."},
                {"@type": "HowToStep", "text": "Jack up the car."},
            ],
        }
        items = howto_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-howto"

    def test_missing_name_returns_empty(self) -> None:
        assert howto_extractor({"@type": "HowTo"}) == []

    def test_includes_steps(self) -> None:
        node = {
            "@type": "HowTo",
            "name": "Bake bread",
            "step": [
                {"@type": "HowToStep", "text": "Mix flour."},
                {"@type": "HowToStep", "text": "Bake 30 min."},
            ],
        }
        item = howto_extractor(node)[0]
        assert "Mix flour." in item.page_content
        assert "Bake 30 min." in item.page_content

    def test_row_data_has_steps(self) -> None:
        node = {
            "@type": "HowTo",
            "name": "Task",
            "step": [{"@type": "HowToStep", "text": "Do it."}],
        }
        item = howto_extractor(node)[0]
        assert isinstance(item.row_data["steps"], list)
        assert len(item.row_data["steps"]) == 1


# ---------------------------------------------------------------------------
# breadcrumb_extractor
# ---------------------------------------------------------------------------


class TestBreadcrumbExtractor:
    """Tests for breadcrumb_extractor."""

    def test_basic_breadcrumb(self) -> None:
        node = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home"},
                {"@type": "ListItem", "position": 2, "name": "Products"},
                {"@type": "ListItem", "position": 3, "name": "Widget"},
            ],
        }
        items = breadcrumb_extractor(node)
        assert len(items) == 1
        assert items[0].content_kind == "jsonld-breadcrumb"
        assert "Home" in items[0].page_content

    def test_path_separator(self) -> None:
        node = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home"},
                {"@type": "ListItem", "position": 2, "name": "About"},
            ],
        }
        item = breadcrumb_extractor(node)[0]
        assert "Home > About" in item.page_content

    def test_empty_list_returns_empty(self) -> None:
        assert breadcrumb_extractor({"@type": "BreadcrumbList", "itemListElement": []}) == []

    def test_missing_items_returns_empty(self) -> None:
        assert breadcrumb_extractor({"@type": "BreadcrumbList"}) == []

    def test_sorted_by_position(self) -> None:
        node = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 3, "name": "C"},
                {"@type": "ListItem", "position": 1, "name": "A"},
                {"@type": "ListItem", "position": 2, "name": "B"},
            ],
        }
        item = breadcrumb_extractor(node)[0]
        assert item.page_content == "A > B > C"

    def test_row_data_crumbs(self) -> None:
        node = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home"},
                {"@type": "ListItem", "position": 2, "name": "Blog"},
            ],
        }
        item = breadcrumb_extractor(node)[0]
        assert item.row_data["path"] == "Home > Blog"
        assert item.row_data["crumbs"] == ["Home", "Blog"]


# ---------------------------------------------------------------------------
# EXTRACTOR_REGISTRY
# ---------------------------------------------------------------------------


class TestExtractorRegistry:
    """Tests for the EXTRACTOR_REGISTRY completeness and alias correctness."""

    def test_all_types_registered(self) -> None:
        expected = {
            "FAQPage",
            "Product",
            "IndividualProduct",
            "Event",
            "Person",
            "Place",
            "LocalBusiness",
            "Restaurant",
            "Recipe",
            "Article",
            "NewsArticle",
            "BlogPosting",
            "Organization",
            "HowTo",
            "BreadcrumbList",
        }
        assert expected.issubset(set(EXTRACTOR_REGISTRY.keys()))

    def test_aliases_point_to_same_function(self) -> None:
        assert EXTRACTOR_REGISTRY["LocalBusiness"] is EXTRACTOR_REGISTRY["Place"]
        assert EXTRACTOR_REGISTRY["Restaurant"] is EXTRACTOR_REGISTRY["Place"]
        assert EXTRACTOR_REGISTRY["NewsArticle"] is EXTRACTOR_REGISTRY["Article"]
        assert EXTRACTOR_REGISTRY["BlogPosting"] is EXTRACTOR_REGISTRY["Article"]
        assert EXTRACTOR_REGISTRY["IndividualProduct"] is EXTRACTOR_REGISTRY["Product"]

    def test_handles_missing_fields(self) -> None:
        """Every extractor should return [] or a list for an empty/minimal node."""
        for name, extractor in EXTRACTOR_REGISTRY.items():
            if name == "FAQPage":
                result = extractor({"@type": "FAQPage", "mainEntity": []})
            else:
                result = extractor({"@type": name})
            assert isinstance(result, list), f"{name} extractor should return a list"

    def test_registry_values_are_callable(self) -> None:
        for name, fn in EXTRACTOR_REGISTRY.items():
            assert callable(fn), f"EXTRACTOR_REGISTRY['{name}'] is not callable"

    def test_jsonld_item_fields(self) -> None:
        """JsonLdItem must have the required fields."""
        item = JsonLdItem(
            content_kind="faq",
            source_type="faq-jsonld",
            page_content="Q: X\n\nA: Y",
            row_data={"question": "X", "answer": "Y"},
            selector_name="faq",
        )
        assert item.content_kind == "faq"
        assert item.source_type == "faq-jsonld"
        assert item.page_content == "Q: X\n\nA: Y"
        assert item.row_data == {"question": "X", "answer": "Y"}
        assert item.selector_name == "faq"
