"""Unit tests for the /create_agent CLI argument parser."""
from parrot.cli.commands import _parse_create_agent_args


def test_pure_description():
    parsed = _parse_create_agent_args("Build a RAG bot for product docs")
    assert parsed["description"] == "Build a RAG bot for product docs"
    assert parsed["clone_from"] is None
    assert parsed["category"] == "general"


def test_clone_from_flag():
    parsed = _parse_create_agent_args(
        "Clone the AT&T bot for Hisense --clone-from ATTBot"
    )
    assert parsed["clone_from"] == "ATTBot"
    assert "ATTBot" not in parsed["description"]
    assert parsed["description"].startswith("Clone the AT&T bot")


def test_category_flag():
    parsed = _parse_create_agent_args(
        "A finance assistant --category finance"
    )
    assert parsed["category"] == "finance"
    assert "finance" not in parsed["description"].split()[-1:]


def test_combined_flags():
    parsed = _parse_create_agent_args(
        "Variant agent --clone-from BaseBot --category support"
    )
    assert parsed["clone_from"] == "BaseBot"
    assert parsed["category"] == "support"
    assert parsed["description"] == "Variant agent"


def test_empty_description():
    parsed = _parse_create_agent_args("")
    assert parsed["description"] == ""


def test_flag_without_value_keeps_token_in_description():
    parsed = _parse_create_agent_args("Build a bot --clone-from")
    # The flag without a value should be ignored gracefully.
    assert parsed["clone_from"] is None
    assert "--clone-from" in parsed["description"]
