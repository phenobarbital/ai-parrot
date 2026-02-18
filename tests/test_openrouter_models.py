"""Unit tests for OpenRouter data models."""
import pytest
from parrot.models.openrouter import (
    OpenRouterModel,
    ProviderPreferences,
    OpenRouterUsage
)


class TestOpenRouterModel:
    def test_model_values(self):
        """Model enum contains expected identifiers."""
        assert OpenRouterModel.DEEPSEEK_R1 == "deepseek/deepseek-r1"
        assert OpenRouterModel.LLAMA_3_3_70B == "meta-llama/llama-3.3-70b-instruct"

    def test_model_is_string(self):
        """Model enum values are usable as strings."""
        model = OpenRouterModel.DEEPSEEK_R1
        assert isinstance(model, str)
        assert "deepseek" in model

    def test_all_models_are_strings(self):
        """All model enum values are valid strings with slash separator."""
        for model in OpenRouterModel:
            assert isinstance(model.value, str)
            assert "/" in model.value


class TestProviderPreferences:
    def test_defaults(self):
        """Default preferences are sensible."""
        prefs = ProviderPreferences()
        assert prefs.allow_fallbacks is True
        assert prefs.require_parameters is False
        assert prefs.order is None

    def test_serialization_excludes_none(self):
        """model_dump(exclude_none=True) produces clean dict."""
        prefs = ProviderPreferences(
            allow_fallbacks=True,
            order=["DeepInfra", "Together"]
        )
        dumped = prefs.model_dump(exclude_none=True)
        assert "order" in dumped
        assert "ignore" not in dumped
        assert "data_collection" not in dumped

    def test_full_config(self):
        """All fields serialize correctly."""
        prefs = ProviderPreferences(
            allow_fallbacks=False,
            require_parameters=True,
            data_collection="deny",
            order=["DeepInfra"],
            ignore=["Azure"],
            quantizations=["bf16", "fp8"]
        )
        dumped = prefs.model_dump()
        assert dumped["quantizations"] == ["bf16", "fp8"]
        assert dumped["allow_fallbacks"] is False
        assert dumped["data_collection"] == "deny"
        assert dumped["require_parameters"] is True

    def test_empty_serialization(self):
        """Default-only instance serializes with only default fields."""
        prefs = ProviderPreferences()
        dumped = prefs.model_dump(exclude_none=True)
        assert dumped == {
            "allow_fallbacks": True,
            "require_parameters": False
        }


class TestOpenRouterUsage:
    def test_all_optional(self):
        """All fields are optional — empty construction works."""
        usage = OpenRouterUsage()
        assert usage.generation_id is None
        assert usage.total_cost is None

    def test_from_dict(self):
        """Parses from a dict (simulating API response)."""
        data = {
            "generation_id": "gen-abc123",
            "model": "deepseek/deepseek-r1",
            "total_cost": 0.0042,
            "prompt_tokens": 150,
            "completion_tokens": 300,
            "provider_name": "DeepInfra"
        }
        usage = OpenRouterUsage(**data)
        assert usage.total_cost == 0.0042
        assert usage.provider_name == "DeepInfra"
        assert usage.prompt_tokens == 150

    def test_partial_data(self):
        """Handles partial data gracefully."""
        usage = OpenRouterUsage(generation_id="gen-xyz", total_cost=0.001)
        assert usage.generation_id == "gen-xyz"
        assert usage.model is None
        assert usage.provider_name is None
