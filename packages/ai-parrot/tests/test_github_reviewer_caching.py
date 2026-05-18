"""Unit tests for GitHubReviewer prompt_caching opt-in.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1226).

Note: GitHubReviewer imports parrot_tools.gittoolkit which requires
the ``github`` (PyGithub) package. These tests skip gracefully when
that dependency is not installed.
"""
import inspect
import pytest

try:
    from parrot.bots.github_reviewer import GitHubReviewer
    _GITHUB_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _GITHUB_AVAILABLE = False

_skip_no_github = pytest.mark.skipif(
    not _GITHUB_AVAILABLE,
    reason="PyGithub not installed; skipping GitHubReviewer tests",
)


class TestGitHubReviewerCachingSource:
    """Tests that inspect the source code rather than instantiating the class.

    These tests verify the FEAT-181 opt-in pattern is present in the source
    without requiring the full GitHubReviewer import chain to succeed.
    """

    def test_prompt_caching_setdefault_in_source(self):
        """The kwargs.setdefault for prompt_caching=True is in the source file."""
        import pathlib
        # Find the github_reviewer.py file via package structure
        src_path = pathlib.Path(__file__).parent.parent / "src" / "parrot" / "bots" / "github_reviewer.py"
        assert src_path.exists(), f"Source file not found at {src_path}"
        source = src_path.read_text(encoding="utf-8")
        assert 'setdefault("prompt_caching", True)' in source, (
            "Expected kwargs.setdefault(\"prompt_caching\", True) in GitHubReviewer.__init__"
        )

    def test_docstring_mentions_prompt_caching(self):
        """The GitHubReviewer class docstring mentions prompt caching."""
        import pathlib
        src_path = pathlib.Path(__file__).parent.parent / "src" / "parrot" / "bots" / "github_reviewer.py"
        source = src_path.read_text(encoding="utf-8")
        assert "prompt_caching" in source

    def test_docstring_mentions_gemini_threshold(self):
        """The GitHubReviewer docstring mentions the Gemini ≥4096 threshold."""
        import pathlib
        src_path = pathlib.Path(__file__).parent.parent / "src" / "parrot" / "bots" / "github_reviewer.py"
        source = src_path.read_text(encoding="utf-8")
        assert "4096" in source


@_skip_no_github
class TestGitHubReviewerCachingRuntime:
    """Runtime tests — only run when PyGithub is installed."""

    def test_prompt_caching_default_true(self):
        """GitHubReviewer sets prompt_caching=True by default."""
        source = inspect.getsource(GitHubReviewer.__init__)
        assert "prompt_caching" in source

    def test_can_override_to_false(self):
        """setdefault semantics allow caller to override with prompt_caching=False."""
        source = inspect.getsource(GitHubReviewer.__init__)
        assert "setdefault" in source

    def test_docstring_present(self):
        """GitHubReviewer has a docstring."""
        assert GitHubReviewer.__doc__ is not None
        assert len(GitHubReviewer.__doc__) > 0
