"""Shared fixtures for prompt layer tests."""
import importlib
import sys
import pytest
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.builder import PromptBuilder

# Force-load the REAL parrot.bots.abstract module ONCE for all test files.
# The root conftest installs a stub that lacks prompt builder methods.
# By loading it here (in the package conftest), all test modules in this
# directory share the same module object, so @patch targets work correctly.
sys.modules.pop("parrot.bots.abstract", None)
_real_abstract = importlib.import_module("parrot.bots.abstract")
sys.modules["parrot.bots.abstract"] = _real_abstract


@pytest.fixture
def full_configure_context():
    """Full context for CONFIGURE phase with all static vars."""
    return {
        "name": "TestBot",
        "role": "helpful assistant",
        "goal": "help users",
        "capabilities": "- Can search\n- Can analyze",
        "backstory": "Expert in AI",
        "pre_instructions_content": "",
        "extra_security_rules": "",
        "has_tools": False,
        "extra_tool_instructions": "",
        "rationale": "",
    }


@pytest.fixture
def full_request_context():
    """Full context for REQUEST phase with all dynamic vars."""
    return {
        "knowledge_content": "Some knowledge facts",
        "user_context": "User prefers JSON",
        "chat_history": "Human: hello\nAssistant: hi",
        "output_instructions": "",
    }


@pytest.fixture
def minimal_configure_context():
    """Minimal context with only required identity vars."""
    return {
        "name": "MinBot",
        "role": "assistant",
    }


@pytest.fixture
def empty_request_context():
    """Request context with all empty strings."""
    return {
        "knowledge_content": "",
        "user_context": "",
        "chat_history": "",
        "output_instructions": "",
    }


@pytest.fixture
def custom_layer():
    """A simple custom layer for testing."""
    return PromptLayer(
        name="custom",
        priority=LayerPriority.CUSTOM,
        template="<custom>$custom_val</custom>",
    )


@pytest.fixture
def conditional_layer():
    """A layer with a condition."""
    return PromptLayer(
        name="conditional",
        priority=LayerPriority.CUSTOM,
        template="<cond>$data</cond>",
        condition=lambda ctx: bool(ctx.get("data", "").strip()),
    )


@pytest.fixture
def default_builder():
    """Fresh default PromptBuilder."""
    return PromptBuilder.default()
