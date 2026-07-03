"""Tests for the multi-dispatcher code review gate (FEAT-270)."""

import pytest

from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)
from parrot.flows.dev_loop.models import (
    ClaudeCodeReviewProfile,
    CodeReviewFinding,
    CodeReviewVerdict,
    CodexCodeReviewProfile,
    GeminiCodeReviewProfile,
)


class _DummyReviewer(AbstractCodeReviewDispatcher):
    agent_name = "dummy"

    async def review(self, *, brief, run_id, node_id, cwd):
        return None  # placeholder

    def build_review_profile(self):
        return None  # placeholder


class TestCodeReviewDispatcherFactory:
    def test_register_and_create(self):
        CodeReviewDispatcherFactory.register("dummy")(_DummyReviewer)
        instance = CodeReviewDispatcherFactory.create("dummy")
        assert isinstance(instance, _DummyReviewer)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown code review dispatcher"):
            CodeReviewDispatcherFactory.create("nonexistent")

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AbstractCodeReviewDispatcher()


class TestCodeReviewFinding:
    def test_valid_finding(self):
        f = CodeReviewFinding(
            message="Missing guard", severity="critical", file="sync.py", line=88
        )
        assert f.severity == "critical"
        assert f.file == "sync.py"
        assert f.line == 88

    def test_invalid_severity_rejected(self):
        with pytest.raises(Exception):
            CodeReviewFinding(message="x", severity="blocker")

    def test_defaults(self):
        f = CodeReviewFinding(message="x", severity="nit")
        assert f.file == ""
        assert f.line == 0


class TestCodeReviewVerdict:
    def test_default_is_pass(self):
        v = CodeReviewVerdict()
        assert v.passed is True
        assert v.findings == []
        assert v.files_modified == []

    def test_with_findings(self):
        f = CodeReviewFinding(message="issue", severity="major")
        v = CodeReviewVerdict(passed=False, findings=[f], summary="Has issues")
        assert not v.passed
        assert len(v.findings) == 1


class TestReviewProfiles:
    def test_claude_profile_has_write_tools(self):
        p = ClaudeCodeReviewProfile()
        assert "Edit" in p.allowed_tools
        assert "Write" in p.allowed_tools
        assert p.permission_mode == "default"

    def test_codex_profile_write_sandbox(self):
        p = CodexCodeReviewProfile()
        assert p.sandbox == "workspace-write"
        assert p.approval_policy == "auto-edit"

    def test_gemini_profile_no_sandbox(self):
        p = GeminiCodeReviewProfile()
        assert p.sandbox is False
        assert p.approval_mode == "auto_edit"
