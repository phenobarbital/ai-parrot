"""Unit tests for ``--dev-agent`` flag parsing (FEAT-388, Module 3)."""
from __future__ import annotations

import click
import pytest
from parrot.cli.devloop import _parse_dev_agent_flag
from parrot.flows.dev_loop.models import DevAgentSpec


def test_parse_backend_only():
    """A bare backend id defaults model='' and count=1."""
    spec = _parse_dev_agent_flag("codex")
    assert spec == DevAgentSpec(agent="codex", model="", count=1)


def test_parse_backend_model():
    """backend:model sets the model, count stays 1."""
    spec = _parse_dev_agent_flag("codex:gpt-5.5")
    assert spec == DevAgentSpec(agent="codex", model="gpt-5.5", count=1)


def test_parse_backend_model_count():
    """backend:model:count sets all three fields."""
    spec = _parse_dev_agent_flag("codex:gpt-5.5:2")
    assert spec == DevAgentSpec(agent="codex", model="gpt-5.5", count=2)


def test_parse_google_coding_backend_bare():
    """The google_coding (agy) backend id parses like any other."""
    spec = _parse_dev_agent_flag("google_coding")
    assert spec == DevAgentSpec(agent="google_coding", model="", count=1)


def test_two_flags_combine_into_a_list():
    """AC: --dev-agent codex:gpt-5.5:2 --dev-agent google_coding -> both specs."""
    specs = [
        _parse_dev_agent_flag(v) for v in ("codex:gpt-5.5:2", "google_coding")
    ]
    assert specs == [
        DevAgentSpec(agent="codex", model="gpt-5.5", count=2),
        DevAgentSpec(agent="google_coding", model="", count=1),
    ]


def test_unknown_backend_lists_catalog_ids():
    """An unrecognized backend fails fast, listing every valid catalog id."""
    with pytest.raises(click.BadParameter) as exc_info:
        _parse_dev_agent_flag("not-a-backend")
    message = str(exc_info.value)
    assert "codex" in message
    assert "claude-code" in message
    assert "google_coding" in message


def test_count_must_be_positive_int():
    """A zero, negative, or non-numeric count is rejected."""
    with pytest.raises(click.BadParameter):
        _parse_dev_agent_flag("codex:gpt-5.5:0")

    with pytest.raises(click.BadParameter):
        _parse_dev_agent_flag("codex:gpt-5.5:-1")

    with pytest.raises(click.BadParameter):
        _parse_dev_agent_flag("codex:gpt-5.5:abc")


def test_model_with_colon_free_id_is_not_confused_with_count():
    """Colon-split max 2 keeps a bare model (no ':' in catalog model ids) intact."""
    spec = _parse_dev_agent_flag("gemini:auto")
    assert spec == DevAgentSpec(agent="gemini", model="auto", count=1)
