"""Unit tests for the techwiki documentation check (FEAT-801 M5)."""

from pathlib import Path

import pytest

from parrot.sdd.scripts import techwiki_check
from parrot.sdd.techwiki.check import DocsDecision, evaluate_docs, resolve_docs_policy


def _spec(tmp_path: Path, frontmatter: str) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text(f"---\n{frontmatter}\n---\n# Spec\n")
    return spec


class TestResolveDocs:
    def test_unset(self, tmp_path):
        """No docs key → unset."""
        assert resolve_docs_policy(_spec(tmp_path, "type: feature"))[0] == "unset"

    def test_required(self, tmp_path):
        """docs.policy: required."""
        spec = _spec(tmp_path, "type: feature\ndocs:\n  policy: required\n  pages:\n    - wiki/a/b.md")
        policy, pages, _ = resolve_docs_policy(spec)
        assert policy == "required"
        assert pages == ["wiki/a/b.md"]

    def test_invalid_non_dict(self, tmp_path):
        """Non-dict docs → invalid."""
        assert resolve_docs_policy(_spec(tmp_path, "docs: true"))[0] == "invalid"

    def test_invalid_policy_never_coerced(self, tmp_path):
        """Unknown policy value → invalid."""
        assert resolve_docs_policy(_spec(tmp_path, "docs:\n  policy: maybe"))[0] == "invalid"


class TestEvaluateDocs:
    def test_none_and_unset_skipped(self, tmp_path):
        """none/unset policies are skipped."""
        assert evaluate_docs("none", [], [], tmp_path).status == "skipped"
        assert evaluate_docs("unset", [], [], tmp_path).reason_codes == ["docs_unset"]

    def test_required_pages_present_ok(self, tmp_path):
        """Present, titled pages → ok."""
        page = tmp_path / "wiki" / "a" / "b.md"
        page.parent.mkdir(parents=True)
        page.write_text("---\ntitle: B\n---\n\nbody\n")
        decision = evaluate_docs("required", ["wiki/a/b.md"], ["parrot.sdd"], tmp_path)
        assert decision.status == "ok"
        assert decision.present == ["wiki/a/b.md"]

    def test_missing_page_warns(self, tmp_path):
        """Missing page → warning."""
        decision = evaluate_docs("required", ["wiki/x.md"], [], tmp_path)
        assert decision.status == "warning"
        assert decision.missing == ["wiki/x.md"]

    def test_check_content_rules(self, tmp_path):
        """Empty page / no title / bad api_modules → warning codes."""
        (tmp_path / "wiki").mkdir()
        (tmp_path / "wiki" / "empty.md").write_text("  \n")
        (tmp_path / "wiki" / "notitle.md").write_text("just text\n")
        decision = evaluate_docs("required", ["wiki/empty.md", "wiki/notitle.md"], ["not a module!"], tmp_path)
        assert decision.status == "warning"
        assert {"docs_page_empty", "docs_page_no_title", "docs_api_module_syntax"} <= set(decision.reason_codes)
        assert decision.empty == ["wiki/empty.md"]

    def test_check_repo_relative_only(self, tmp_path):
        """Path with '..' or absolute → invalid (docs_page_outside_root)."""
        for bad in ("../outside.md", "/etc/passwd"):
            decision = evaluate_docs("required", [bad], [], tmp_path)
            assert decision.status == "invalid"
            assert "docs_page_outside_root" in decision.reason_codes

    def test_check_never_blocking(self, tmp_path, capsys):
        """Every policy/status → exit 0 or 2; the CLI has no --force and no blocking code."""
        for fm, expected in (
            ("type: feature", 0),
            ("docs:\n  policy: none", 0),
            ("docs:\n  policy: required\n  pages:\n    - wiki/missing.md", 0),
            ("docs: true", 2),
        ):
            spec = _spec(tmp_path, fm)
            assert techwiki_check.main(["--spec", str(spec), "--root", str(tmp_path)]) == expected
        with pytest.raises(SystemExit):
            techwiki_check.main(["--spec", str(spec), "--force"])
        assert "--force" not in capsys.readouterr().out
        assert isinstance(evaluate_docs("none", [], [], tmp_path), DocsDecision)

    def test_missing_spec_is_usage_error(self, tmp_path):
        """A missing spec file → exit 2."""
        assert techwiki_check.main(["--spec", str(tmp_path / "nope.md")]) == 2
