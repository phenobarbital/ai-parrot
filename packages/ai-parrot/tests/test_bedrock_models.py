"""Unit tests for parrot.models.bedrock_models.translate (TASK-1514).

Tests cover the three translation branches:
- Map: public ID → Bedrock base ID
- Region prefix: prepend ``<prefix>.`` to mapped base ID
- Pass-through: already-Bedrock IDs / ARNs returned verbatim
- Unknown fallback: unknown public ID returned unchanged + warning logged
"""
import logging

import pytest

from parrot.models.bedrock_models import translate


def test_map_public_to_bedrock():
    """A known public ID maps to a Bedrock base ID."""
    out = translate("claude-sonnet-4-6")
    assert "anthropic." in out and out.endswith(":0")


def test_map_known_dated_variant():
    """A dated public ID also maps to the correct Bedrock base ID."""
    out = translate("claude-sonnet-4-5-20250929")
    assert out == "anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_region_prefix():
    """Region prefix is prepended to the mapped Bedrock base ID."""
    result = translate("claude-sonnet-4-6", region_prefix="us")
    assert result.startswith("us.anthropic.")
    assert result.endswith(":0")


def test_region_prefix_eu():
    """EU region prefix is applied correctly."""
    result = translate("claude-sonnet-4-6", region_prefix="eu")
    assert result.startswith("eu.anthropic.")


def test_passthrough_bedrock_id():
    """An already-translated Bedrock ID is returned verbatim."""
    bid = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert translate(bid) == bid


def test_passthrough_bedrock_id_no_prefix():
    """A Bedrock ID with ``anthropic.`` but no region prefix passes through."""
    bid = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert translate(bid) == bid


def test_passthrough_arn():
    """An ARN is returned verbatim."""
    arn = "arn:aws:bedrock:us-east-1::inference-profile/us.anthropic.claude-x"
    assert translate(arn) == arn


def test_passthrough_eu_prefix():
    """An ID starting with the ``eu.`` region prefix passes through."""
    bid = "eu.anthropic.claude-sonnet-4-6-20260115-v1:0"
    assert translate(bid) == bid


def test_unknown_passthrough(caplog):
    """An unknown public ID is returned unchanged and a warning is logged."""
    with caplog.at_level(logging.WARNING, logger="parrot.models.bedrock_models"):
        result = translate("claude-made-up-99")
    assert result == "claude-made-up-99"
    assert "unknown public model ID" in caplog.text.lower() or "claude-made-up-99" in caplog.text


def test_unknown_with_region_prefix_passthrough(caplog):
    """Unknown ID with a region_prefix requested is still returned unchanged."""
    with caplog.at_level(logging.WARNING, logger="parrot.models.bedrock_models"):
        result = translate("claude-nonexistent-99", region_prefix="us")
    # The unknown ID is not in the map — returned as-is (no prefix applied).
    assert result == "claude-nonexistent-99"


def test_no_region_prefix_means_no_dot_prefix():
    """Without a region_prefix, the raw Bedrock base ID is returned."""
    out = translate("claude-sonnet-4-6")
    assert not out.startswith("us.")
    assert not out.startswith("eu.")
    assert not out.startswith("apac.")
