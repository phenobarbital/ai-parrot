"""Unit tests for MetaClient (Chat Completions path, credential chain).

No live Meta API calls are made.
"""

from pathlib import Path

import pytest

from parrot.clients.meta import CONTRIBUTOR_MODELS, MetaClient, MetaModel
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.gpt import OpenAIClient
from parrot.clients.openai_base import OpenAIBaseClient


class TestMetaClient:
    def test_subclasses_openai_base_not_openai_client(self):
        assert issubclass(MetaClient, OpenAIBaseClient)
        assert not issubclass(MetaClient, OpenAIClient)

    def test_client_type_and_name(self):
        assert MetaClient.client_type == "meta"
        assert MetaClient.client_name == "meta"

    def test_default_model_is_standard_tier(self):
        assert MetaClient._default_model == "muse-spark-1.3"
        assert MetaClient._default_model not in CONTRIBUTOR_MODELS

    def test_default_timeout_is_raised(self):
        assert MetaClient._default_timeout == 120.0

    def test_no_gpt_leak_in_model_attrs(self):
        for attr in ("_default_model", "_fallback_model", "_lightweight_model"):
            val = getattr(MetaClient, attr, None)
            assert val is None or not str(val).startswith("gpt-")

    def test_feat523_discovery_attrs(self):
        assert MetaClient.provider_keys == ("meta", "muse", "meta-muse")
        assert MetaClient.models is MetaModel

    def test_package_layout_is_exactly_three_files(self):
        import parrot.clients.meta as pkg

        names = {p.name for p in Path(pkg.__file__).parent.glob("*.py")}
        assert names == {"__init__.py", "client.py", "models.py"}

    def test_base_url(self):
        assert MetaClient(api_key="k").base_url == "https://api.meta.ai/v1"

    def test_explicit_key_wins(self):
        assert MetaClient(api_key="explicit").api_key == "explicit"

    def test_prefers_meta_api_key(self, monkeypatch):
        monkeypatch.setattr(
            "parrot.clients.meta.config.get",
            lambda k, *a: {
                "META_API_KEY": "meta-key",
                "MODEL_API_KEY": "model-key",
            }.get(k),
        )
        assert MetaClient().api_key == "meta-key"

    def test_falls_back_to_model_api_key(self, monkeypatch):
        monkeypatch.setattr(
            "parrot.clients.meta.config.get",
            lambda k, *a: {"MODEL_API_KEY": "model-key"}.get(k),
        )
        assert MetaClient().api_key == "model-key"

    def test_never_falls_back_to_openai_api_key(self, monkeypatch):
        """Regression: an sk-... key must never be shipped to Meta."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-be-used")
        monkeypatch.setattr("parrot.clients.meta.config.get", lambda k, *a: None)
        assert MetaClient().api_key != "sk-should-never-be-used"

    def test_not_exported_from_clients_init(self):
        import parrot.clients as clients_pkg

        assert not hasattr(clients_pkg, "MetaClient")

    @pytest.mark.asyncio
    async def test_get_client_returns_async_openai(self, monkeypatch):
        monkeypatch.setattr("parrot.clients.meta.config.get", lambda k, *a: None)
        client = MetaClient(api_key="k")
        sdk_client = await client.get_client()
        from openai import AsyncOpenAI

        assert isinstance(sdk_client, AsyncOpenAI)
        assert str(sdk_client.base_url) == "https://api.meta.ai/v1/"

    @pytest.mark.asyncio
    async def test_list_models_hits_v1_models_endpoint(self, monkeypatch):
        captured = {}

        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def raise_for_status(self):
                pass

            async def json(self):
                return {"data": [{"id": "muse-spark-1.3"}]}

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def get(self, url, headers=None):
                captured["url"] = url
                captured["headers"] = headers
                return FakeResponse()

        import parrot.clients.meta.client as client_mod

        monkeypatch.setattr(client_mod.aiohttp, "ClientSession", FakeSession)

        client = MetaClient(api_key="k")
        result = await client.list_models()

        assert result == [{"id": "muse-spark-1.3"}]
        assert captured["url"] == "https://api.meta.ai/v1/models"
        assert captured["headers"]["Authorization"] == "Bearer k"


class TestMetaFactoryRegistration:
    @pytest.mark.parametrize("alias", ["meta", "muse", "meta-muse"])
    def test_aliases_resolve(self, alias):
        assert SUPPORTED_CLIENTS[alias] is MetaClient

    def test_create_with_explicit_model(self):
        client = LLMFactory.create("meta:muse-spark-1.3")
        assert isinstance(client, MetaClient)
        assert client.model == "muse-spark-1.3"

    def test_create_with_default_model(self):
        client = LLMFactory.create("meta")
        assert isinstance(client, MetaClient)
        # No explicit model was passed; the client falls back to its class
        # default at resolution time (see AbstractClient.default_model /
        # OpenAIBaseClient._resolve_model) rather than stamping `.model` at
        # construction — same convention as MoonshotClient's factory tests.
        assert client.default_model == "muse-spark-1.3"

    def test_registered_keys_match_provider_keys(self):
        keys = {k for k, v in SUPPORTED_CLIENTS.items() if v is MetaClient}
        assert keys == set(MetaClient.provider_keys)

    def test_in_both_wire_rosters(self):
        from tests.clients.test_openai_compatible_defaults import WIRE_SUBCLASSES as A
        from tests.clients.test_openai_base_parity import WIRE_SUBCLASSES as B

        assert MetaClient in A and MetaClient in B
