"""Unit tests for the ``bedrock-converse`` factory registration
(FEAT-302, TASK-1747).
"""
import tomllib
from pathlib import Path

from parrot.clients.factory import SUPPORTED_CLIENTS


class TestFactoryBedrockConverse:
    def test_bedrock_converse_registered(self):
        assert "bedrock-converse" in SUPPORTED_CLIENTS

    def test_bedrock_legacy_preserved(self):
        from parrot.clients.claude import AnthropicClient
        client_cls = SUPPORTED_CLIENTS["bedrock"]
        if callable(client_cls) and not isinstance(client_cls, type):
            client_cls = client_cls()
        assert client_cls is AnthropicClient or issubclass(client_cls, AnthropicClient)

    def test_lazy_import(self):
        resolver = SUPPORTED_CLIENTS["bedrock-converse"]
        if callable(resolver) and not isinstance(resolver, type):
            cls = resolver()
        else:
            cls = resolver
        assert cls.__name__ == "BedrockConverseClient"

    def test_create_via_llm_factory(self):
        """LLMFactory.create() end-to-end resolution — resolves the lazy
        loader and constructs a real BedrockConverseClient instance."""
        from parrot.clients.factory import LLMFactory
        from parrot.clients.bedrock import BedrockConverseClient

        client = LLMFactory.create("bedrock-converse:claude-sonnet-4-5")
        assert isinstance(client, BedrockConverseClient)
        assert client.model == "claude-sonnet-4-5"

    def test_pyproject_extra_named_bedrock_native(self):
        """Code-review follow-up: the spec (Module 6 / Acceptance Criteria)
        names the optional pip extra ``bedrock-native``. It must not be
        confused with the (correct, unrelated) ``bedrock-converse`` factory
        key / client_type — the extra was briefly misnamed
        ``bedrock-converse`` before this fix."""
        pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        extras = data["project"]["optional-dependencies"]
        assert "bedrock-native" in extras
        assert any("aioboto3" in dep for dep in extras["bedrock-native"])
        assert "bedrock-converse" not in extras
