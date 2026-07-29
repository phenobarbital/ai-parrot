"""FEAT-375 code-review fix: `examples/dev_loop/server.py`'s
`_build_codex_adversarial_reviewer` must not let a `DEV_LOOP_ADVERSARIAL_SCOPE`
of "base"/"commit" silently degrade to an unreviewed pass when its target
ref isn't (or can't be) configured.

The ``examples/dev_loop/server.py`` module is loaded via
``importlib.util.spec_from_file_location`` (mirrors
``test_server_repo_wiring.py``) so it doesn't need the ``examples``
directory to be a Python package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop.code_review import CodexAdversarialReviewDispatcher


def _load_server_module():
    server_path = Path(__file__).parents[5] / "examples" / "dev_loop" / "server.py"
    if not server_path.exists():
        pytest.skip(f"server.py not found at {server_path}")
    module_name = "_dev_loop_server_under_test_adversarial"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_uncommitted_scope_needs_no_ref(monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_SCOPE", "uncommitted")
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_BASE_REF", "")
    module = _load_server_module()
    reviewer = module._build_codex_adversarial_reviewer(MagicMock())
    assert isinstance(reviewer, CodexAdversarialReviewDispatcher)
    assert reviewer.build_review_profile().review_scope == "uncommitted"


def test_base_scope_without_ref_raises_at_startup(monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_SCOPE", "base")
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_BASE_REF", "")
    module = _load_server_module()
    with pytest.raises(RuntimeError, match="DEV_LOOP_ADVERSARIAL_BASE_REF"):
        module._build_codex_adversarial_reviewer(MagicMock())


def test_base_scope_with_ref_wires_review_base(monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_SCOPE", "base")
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_BASE_REF", "dev")
    module = _load_server_module()
    reviewer = module._build_codex_adversarial_reviewer(MagicMock())
    profile = reviewer.build_review_profile()
    assert profile.review_scope == "base"
    assert profile.review_base == "dev"


def test_commit_scope_always_raises_at_startup(monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_ADVERSARIAL_SCOPE", "commit")
    module = _load_server_module()
    with pytest.raises(RuntimeError, match="not supported"):
        module._build_codex_adversarial_reviewer(MagicMock())
