"""Tests for the ExtractJsonLd BrowserAction model — FEAT-154 / TASK-1049."""

import pytest
from pydantic import TypeAdapter

from parrot.tools.scraping.models import (
    ACTION_MAP,
    ActionList,
    ExtractJsonLd,
    ScrapingStep,
)


class TestExtractJsonLdModel:

    def test_extract_jsonld_model_defaults(self) -> None:
        """ExtractJsonLd carries the documented default field values."""
        a = ExtractJsonLd()
        assert a.action == "extract_jsonld"
        assert a.name == "extract_jsonld"
        assert a.extract_name == "jsonld"
        assert a.types is None
        assert a.description.lower().startswith("extract json-ld")

    def test_extract_jsonld_in_action_map(self) -> None:
        """ACTION_MAP routes the discriminator string to the new class."""
        assert ACTION_MAP["extract_jsonld"] is ExtractJsonLd

    def test_action_list_accepts_extract_jsonld(self) -> None:
        """The discriminated ActionList parses an extract_jsonld payload."""
        adapter = TypeAdapter(ActionList)
        payload = {"action": "extract_jsonld", "types": ["Product", "Recipe"]}
        parsed = adapter.validate_python(payload)
        assert isinstance(parsed, ExtractJsonLd)
        assert parsed.types == ["Product", "Recipe"]

    def test_scrapingstep_from_dict_extract_jsonld(self) -> None:
        """ScrapingStep round-trips an extract_jsonld step via ACTION_MAP."""
        data = {
            "action": "extract_jsonld",
            "extract_name": "products",
            "types": ["Product"],
        }
        step = ScrapingStep.from_dict(data)
        assert isinstance(step.action, ExtractJsonLd)
        assert step.action.extract_name == "products"
        assert step.action.types == ["Product"]
