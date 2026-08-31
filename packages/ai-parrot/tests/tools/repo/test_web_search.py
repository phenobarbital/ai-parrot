"""Unit tests for the opt-in `web_search` tool (FEAT-484)."""

from __future__ import annotations

import builtins
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit


class TestWebSearchExposure:
    def test_absent_when_disabled(self, temp_repo: Path):
        """Spec §3 Module 5: absent, not merely erroring."""
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo)
        assert "web_search" not in {t.name for t in tk.get_tools()}

    def test_present_when_enabled(self, temp_repo: Path):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, enable_web_search=True)
        assert "web_search" in {t.name for t in tk.get_tools()}

    async def test_degrades_on_import_error(self, temp_repo, monkeypatch):
        real = builtins.__import__

        def _fail(name, *a, **k):
            if "ddgsearch" in name:
                raise ImportError("no ddgs")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _fail)

        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, enable_web_search=True)
        out = await tk.web_search("anything")
        assert out["error"] == "web_search_unavailable"
        assert out["results"] == []
