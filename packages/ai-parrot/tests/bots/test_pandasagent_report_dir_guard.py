"""Path-traversal guard on ``PandasAgent._get_default_tools``.

``agent_id`` reaches the framework from an HTTP payload (see
``DataAnalystHandler.post``) and is used to build ``STATIC_DIR/<agent_id>/
documents``. These tests pin the guard on that call site.

The method is invoked unbound against a minimal stub: the guard is its first
statement, so the rejection path never reaches the attributes a real agent
would carry.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.bots.data import PandasAgent


@pytest.mark.parametrize(
    "agent_id",
    [
        "../../../etc",
        "/etc/passwd",
        "..",
        "sub/dir",
        "sub\\dir",
        ".hidden",
        "agent\n",
        "",
    ],
)
def test_unsafe_agent_id_is_rejected(agent_id, tmp_path: Path, monkeypatch):
    """An unsafe agent_id raises before anything is written to disk."""
    monkeypatch.setattr("parrot.bots.data.STATIC_DIR", tmp_path)
    stub = SimpleNamespace(agent_id=agent_id)

    with pytest.raises(ValueError, match="Unsafe agent_id"):
        PandasAgent._get_default_tools(stub)

    assert list(tmp_path.iterdir()) == []


def test_safe_agent_id_creates_report_dir_under_static(tmp_path: Path, monkeypatch):
    """A safe agent_id passes the guard and lands under STATIC_DIR."""
    monkeypatch.setattr("parrot.bots.data.STATIC_DIR", tmp_path)
    stub = SimpleNamespace(agent_id="9f1c-agent_1.v2")

    # The stub has no LLM/tool attributes, so the method fails *after* the
    # guard — which is exactly what proves the guard let it through.
    with pytest.raises(AttributeError):
        PandasAgent._get_default_tools(stub)

    assert (tmp_path / "9f1c-agent_1.v2" / "documents").is_dir()
