"""Unit tests for FEAT-375 Codex `exec review` / `resume` command variants.

Covers TASK-1901 (Module 3: Dispatcher command variants).
"""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
from parrot.flows.dev_loop.models import (
    CodexAdversarialReviewProfile,
    CodexCodeDispatchProfile,
)


@pytest.fixture
def dispatcher():
    return CodexCodeDispatcher(max_concurrent=1, redis_url="redis://x", stream_ttl_seconds=60)


def _cmd(dispatcher, profile):
    return dispatcher._build_command(
        profile=profile,
        cwd="/wt",
        schema_path="/s.json",
        output_path="/o.json",
        prompt="P",
    )


def test_legacy_shape_unchanged(dispatcher):
    cmd = _cmd(dispatcher, CodexCodeDispatchProfile())
    assert cmd[:3] == ["codex", "exec", "--json"] and "review" not in cmd
    assert "--ask-for-approval" in cmd
    assert "--sandbox" in cmd


def test_review_uncommitted_default(dispatcher):
    cmd = _cmd(dispatcher, CodexAdversarialReviewProfile())
    assert "--sandbox" in cmd and "read-only" in cmd  # read-only enforced
    assert "review" in cmd
    assert "resume" not in cmd


def test_review_base_and_commit(dispatcher):
    b = _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="base", review_base="dev"))
    assert "--base" in b and "dev" in b
    c = _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="commit", review_commit="abc123"))
    assert "--commit" in c and "abc123" in c


def test_scope_requires_target(dispatcher):
    with pytest.raises(ValueError):
        _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="base"))
    with pytest.raises(ValueError):
        _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="commit"))


def test_resume_no_sandbox_flag(dispatcher):
    cmd = _cmd(dispatcher, CodexAdversarialReviewProfile(resume_last=True))
    assert "resume" in cmd and "--last" in cmd
    assert "--sandbox" not in cmd
    assert any(a.startswith("sandbox_mode=") or 'sandbox_mode="read-only"' in a for a in cmd)


def test_command_shape_options_preserved_for_adversarial_profile(dispatcher):
    cmd = _cmd(dispatcher, CodexAdversarialReviewProfile())
    assert "--cd" in cmd and "/wt" in cmd
    assert "--model" in cmd and "gpt-5.5" in cmd
    assert "--output-schema" in cmd and "/s.json" in cmd
    assert "-o" in cmd and "/o.json" in cmd
    assert "--ignore-user-config" in cmd  # default True on the base profile
    assert cmd[-1] == "P"


def test_adversarial_profile_never_emits_ask_for_approval(dispatcher):
    cmd = _cmd(dispatcher, CodexAdversarialReviewProfile())
    assert "--ask-for-approval" not in cmd
    resume_cmd = _cmd(dispatcher, CodexAdversarialReviewProfile(resume_last=True))
    assert "--ask-for-approval" not in resume_cmd
