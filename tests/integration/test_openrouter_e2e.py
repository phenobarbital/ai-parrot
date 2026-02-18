"""Integration tests for OpenRouter client.

These tests require a valid OPENROUTER_API_KEY environment variable.
They are skipped automatically when the key is not set.
"""
import os

import pytest

from parrot.clients.openrouter import OpenRouterClient
from parrot.models.openrouter import ProviderPreferences

SKIP_REASON = "OPENROUTER_API_KEY not set"
skip_no_key = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason=SKIP_REASON,
)

TEST_MODEL = "meta-llama/llama-3.3-70b-instruct"


@pytest.fixture
def live_client():
    """Create a live OpenRouter client for integration testing."""
    return OpenRouterClient(
        model=TEST_MODEL,
        app_name="ai-parrot-integration-test",
    )


@skip_no_key
@pytest.mark.asyncio
class TestOpenRouterE2E:
    """End-to-end tests for OpenRouterClient against the live API."""

    async def test_basic_completion(self, live_client):
        """Basic completion returns a non-empty response."""
        response = await live_client.completion("Say hello in one word.")
        assert response is not None
        assert len(str(response)) > 0

    async def test_list_models(self, live_client):
        """list_models returns a non-empty list of model dicts."""
        models = await live_client.list_models()
        assert isinstance(models, list)
        assert len(models) > 0
        # Each model should have at least an 'id' field
        assert "id" in models[0]

    async def test_completion_with_provider_prefs(self):
        """Completion works with provider preferences."""
        prefs = ProviderPreferences(
            allow_fallbacks=True,
            order=["DeepInfra"],
        )
        client = OpenRouterClient(
            model=TEST_MODEL,
            provider_preferences=prefs,
        )
        response = await client.completion("Say hi.")
        assert response is not None

    async def test_get_generation_stats(self, live_client):
        """get_generation_stats returns usage data for a completed generation."""
        # First, make a completion to get a generation ID
        response = await live_client.completion("Say yes.")
        # OpenRouter returns generation ID in the response metadata
        # The exact location depends on the response format from the parent class
        gen_id = None
        if hasattr(response, "id"):
            gen_id = response.id
        elif isinstance(response, dict) and "id" in response:
            gen_id = response["id"]

        if gen_id is None:
            pytest.skip("Could not extract generation_id from response")

        stats = await live_client.get_generation_stats(gen_id)
        assert stats is not None
        assert stats.generation_id is not None or stats.model is not None
