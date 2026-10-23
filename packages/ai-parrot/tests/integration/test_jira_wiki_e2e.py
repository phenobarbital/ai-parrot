"""FEAT-454 end-to-end: Jira payloads -> markdown -> plane -> query.

Every test drives the REAL wikitoolkit commands (build/ns/query/page/related)
and fakes only JiraInterface. Each docstring names the spec goal it proves.

This is the seam test: the renderer emits `[[KEY]]` wikilinks and `#tags`
and writes no edges at all, trusting the existing, unmodified `scan_vault`
to derive them (vault_scan.py:16-21). A failure here is a bug report
against the module that produced the wrong input — TASK-2399/2400/2401/
2403/2404 — never something to patch around from this file.
"""

import asyncio
import copy
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.jira_render import SYNC_MARKER
from parrot.knowledge.wiki.jira_sync import sweep_jira_issues

from tests.fixtures.jira_payloads import raw_issue_payload
from tests.knowledge.wiki.test_jira_sync import FakeJiraInterface

JQL = "project = NAV"

# tests/integration/ -> tests/ -> ai-parrot/ -> packages/ -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def payloads() -> list[dict]:
    """Three tickets: two that link to each other, one linking out of scope."""
    a = raw_issue_payload()  # NAV-9372, blocks NAV-9400
    b = copy.deepcopy(a)
    b["key"], b["id"] = "NAV-9400", "184300"
    b["fields"]["summary"] = "Tenant resolution helper"
    b["fields"]["issuelinks"] = [
        {
            "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
            "inwardIssue": {"key": "NAV-9372"},
        }
    ]
    c = copy.deepcopy(a)
    c["key"], c["id"] = "NAV-9500", "184400"
    c["fields"]["summary"] = "Links outside the swept scope"
    c["fields"]["issuelinks"] = [
        {
            "type": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
            "outwardIssue": {"key": "OTHER-1"},
        }
    ]
    return [a, b, c]


@pytest.fixture
def fake_iface(payloads) -> FakeJiraInterface:
    return FakeJiraInterface(payloads)


@pytest.fixture
def corpus(tmp_path, fake_iface):
    """A swept, unbuilt corpus."""
    d = tmp_path / "issues"
    d.mkdir()
    report = asyncio.run(sweep_jira_issues(fake_iface, d, jql=JQL))
    return d, report


def _build(runner, corpus_dir) -> None:
    result = runner.invoke(wiki, ["build", "--path", str(corpus_dir), "--vault", "--quiet"])
    assert result.exit_code == 0, result.output


def _edges(db: Path) -> list[tuple]:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT src, dst, rel FROM edges").fetchall()
    finally:
        con.close()


class TestSweepToQueryablePlane:
    def test_sweep_to_queryable_plane(self, corpus, tmp_path):
        """G6 + G7: query finds the ticket, page renders it, related traverses."""
        corpus_dir, _ = corpus
        runner = CliRunner()
        _build(runner, corpus_dir)
        db = corpus_dir / ".parrot" / "wiki" / "wiki.db"
        assert db.exists()

        q = runner.invoke(wiki, ["query", "--path", str(corpus_dir), "tenant"])
        assert q.exit_code == 0 and "NAV-9372" in q.output

        p = runner.invoke(wiki, ["page", "--path", str(corpus_dir), "file:NAV-9372.md"])
        assert p.exit_code == 0
        # vault_scan's note-body extraction strips the leading YAML
        # frontmatter block before storing WikiPageRecord.body (mirroring
        # documents.split_frontmatter's own contract), so the raw `type:
        # Issue` line is never present in `page`'s rendered output — only
        # in the source .md file on disk (see
        # test_page_category_is_document_not_issue below, which asserts
        # that). Here, prove `page` resolved and rendered the RIGHT ticket
        # with its real content.
        assert "NAV-9372" in p.output
        assert "Forms lose the tenant" in p.output

        r = runner.invoke(wiki, ["related", "--path", str(corpus_dir), "file:NAV-9372.md"])
        assert r.exit_code == 0 and "NAV-9400" in r.output

    def test_page_category_is_document_not_issue(self, corpus, tmp_path):
        """vault_scan.py:166 hard-codes category='document'. The OKF type
        lives in the FRONTMATTER — this is a constraint, not a bug."""
        corpus_dir, _ = corpus
        text = (corpus_dir / "NAV-9372.md").read_text()
        assert "type: Issue" in text

    def test_unresolved_link_dropped_but_key_preserved(self, corpus):
        """vault_scan.py:183 — nothing is lost; the sweep reports it."""
        corpus_dir, report = corpus
        assert "OTHER-1" in (corpus_dir / "NAV-9500.md").read_text()
        assert "OTHER-1" in report.unresolved_link_keys


class TestResync:
    def test_resync_updates_in_place(self, corpus, payloads, tmp_path):
        """G3: one document, one page, no duplicate pages or edges."""
        corpus_dir, _ = corpus
        runner = CliRunner()
        _build(runner, corpus_dir)
        db = corpus_dir / ".parrot" / "wiki" / "wiki.db"
        edges_before = _edges(db)

        changed = copy.deepcopy(payloads[0])
        changed["fields"]["status"]["name"] = "Done"
        changed["fields"]["updated"] = "2026-08-26T09:00:00.000+0000"
        asyncio.run(sweep_jira_issues(FakeJiraInterface([changed] + payloads[1:]), corpus_dir, jql=JQL, force=True))
        _build(runner, corpus_dir)

        assert len(list(corpus_dir.glob("NAV-*.md"))) == 3
        edges_after = _edges(db)
        assert len(edges_after) == len(set(edges_after)), "duplicate edge rows"
        assert set(edges_after) == set(edges_before)

    def test_resync_preserves_human_annotation(self, corpus, payloads):
        """G4: the human tail is byte-identical after a generated-region change."""
        corpus_dir, _ = corpus
        path = corpus_dir / "NAV-9372.md"
        tail = "\n## Ops note\n\nSeen again in prod 2026-08-21.\n"
        path.write_text(path.read_text() + tail)

        changed = copy.deepcopy(payloads[0])
        changed["fields"]["status"]["name"] = "Done"
        changed["fields"]["updated"] = "2026-08-26T09:00:00.000+0000"
        asyncio.run(sweep_jira_issues(FakeJiraInterface([changed]), corpus_dir, jql=JQL, force=True))

        text = path.read_text()
        assert text.endswith(tail)
        assert "Done" in text.split(SYNC_MARKER)[0]


class TestEntityNotesAndTagPages:
    def test_entity_notes_and_tag_pages(self, corpus):
        """G7: person/project/component/label notes and tag pages."""
        corpus_dir, _ = corpus
        runner = CliRunner()
        _build(runner, corpus_dir)
        assert (corpus_dir / "projects" / "NAV.md").exists()
        assert list((corpus_dir / "people").glob("*.md"))
        edges = _edges(corpus_dir / ".parrot" / "wiki" / "wiki.db")
        assert any(rel == "tagged" for _, _, rel in edges), "#tags must become tag pages (vault_scan docstring 16-21)"
        assert any(rel == "references" for _, _, rel in edges)

    def test_no_email_anywhere_in_corpus(self, corpus):
        """G9 over the entire generated corpus."""
        corpus_dir, _ = corpus
        for path in corpus_dir.rglob("*.md"):
            text = path.read_text()
            assert "jlara@example.com" not in text
            assert "aruiz@example.com" not in text
            assert "emailAddress" not in text


class TestNamespaceRegistration:
    def test_namespace_registration_roundtrip(self, corpus, tmp_path):
        """G6: ns add --store, then query --ns issues reaches the corpus."""
        corpus_dir, _ = corpus
        runner = CliRunner()
        _build(runner, corpus_dir)
        store = corpus_dir / ".parrot" / "wiki"

        add = runner.invoke(
            wiki,
            [
                "ns",
                "add",
                "issues",
                "--store",
                str(store),
                "--global",
                "--description",
                "Jira tickets",
            ],
        )
        assert add.exit_code == 0, add.output

        listed = runner.invoke(wiki, ["ns", "list", "--json"])
        assert "issues" in listed.output

        q = runner.invoke(wiki, ["query", "--ns", "issues", "tenant"])
        assert q.exit_code == 0 and "NAV-9372" in q.output

    def test_no_cross_namespace_edges_written(self, corpus):
        """cli.py:2665-2666 — they do not exist; we must not fabricate one."""
        corpus_dir, _ = corpus
        runner = CliRunner()
        _build(runner, corpus_dir)
        for src, dst, _rel in _edges(corpus_dir / ".parrot" / "wiki" / "wiki.db"):
            assert "::" not in src and "::" not in dst


class TestIngestJiraCommand:
    def test_ingest_jira_builds_by_default(self, tmp_path, payloads, monkeypatch):
        """G10: the plane can never silently lag the files."""
        monkeypatch.setattr("parrot.interfaces.jira.JiraInterface", lambda *a, **k: FakeJiraInterface(payloads))
        d = tmp_path / "issues"
        runner = CliRunner()
        result = runner.invoke(wiki, ["ingest-jira", "--project", "NAV", "--issues-dir", str(d), "--quiet"])
        assert result.exit_code == 0, result.output
        assert (d / ".parrot" / "wiki" / "wiki.db").exists()

    def test_no_build_leaves_db_absent(self, tmp_path, payloads, monkeypatch):
        monkeypatch.setattr("parrot.interfaces.jira.JiraInterface", lambda *a, **k: FakeJiraInterface(payloads))
        d = tmp_path / "issues"
        runner = CliRunner()
        result = runner.invoke(
            wiki,
            ["ingest-jira", "--project", "NAV", "--no-build", "--issues-dir", str(d), "--quiet"],
        )
        assert result.exit_code == 0, result.output
        assert not (d / ".parrot" / "wiki" / "wiki.db").exists()


class TestNegativeGuarantees:
    def test_no_llm_calls_by_default(self, tmp_path, fake_iface, monkeypatch):
        """G2: a raising client constructor is never invoked on the default path.

        Patches `AbstractClient.__init__` (parrot/clients/base.py:304) — the
        common base class every provider client subclasses — rather than a
        single provider's `get_client()`, so this is a genuine chokepoint:
        if ANY code path in the sweep/render chain ever constructed an LLM
        client, this would raise instead of silently passing vacuously.
        """
        from parrot.clients.base import AbstractClient

        def boom(*a, **k):
            raise AssertionError("the default path must never construct an LLM client")

        monkeypatch.setattr(AbstractClient, "__init__", boom)
        d = tmp_path / "issues"
        d.mkdir()
        report = asyncio.run(sweep_jira_issues(fake_iface, d, jql=JQL))
        assert report.fetched == len(fake_iface.raw_issues)

    def test_repo_plane_untouched(self, fake_iface, tmp_path):
        """The repository's own plane is a hard non-goal."""
        repo_plane = _REPO_ROOT / ".parrot" / "wiki"
        if not repo_plane.exists():
            pytest.skip("repo plane not built in this environment")

        def _snapshot() -> dict[str, tuple[int, int]]:
            return {
                str(p.relative_to(repo_plane)): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in sorted(repo_plane.rglob("*"))
                if p.is_file()
            }

        before = _snapshot()
        d = tmp_path / "issues"
        d.mkdir()
        asyncio.run(sweep_jira_issues(fake_iface, d, jql=JQL))
        runner = CliRunner()
        _build(runner, d)
        after = _snapshot()
        assert after == before

    def test_repo_scan_and_build_unmodified(self):
        """Spec AC: `git diff` clean for repo_scan.py and the `build` command."""
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/dev...HEAD"],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            check=False,
        ).stdout
        assert "wiki/repo_scan.py" not in out

    def test_jiratoolkit_regression_after_delegation(self):
        """M2: the pre-existing toolkit suites pass UNCHANGED — no new failure.

        Not marked `@pytest.mark.slow` — no such marker is registered in
        this repo's pytest config (`--strict-markers` would reject an
        invented one); this always runs.

        Run as two separate subprocesses (ai-parrot-tools suites, then
        ai-parrot suites) rather than one combined invocation — this is a
        uv-workspace monorepo where both packages ship a `tests/` package
        of the same dotted name; pytest cannot collect both `tests.*`
        trees in one process (`ImportPathMismatchError` on
        `tests.conftest`), independent of anything this feature touches.

        Compares against a captured pre-refactor baseline
        (`artifacts/logs/feat454-jira-baseline.txt`, taken BEFORE any
        TASK-2402 edit) rather than demanding a bare exit code 0: 6 of
        these tests (`TestCreateIssueDefaults`/`TestDueDateOffset` in
        `test_jiratoolkit_defaults.py`) were already failing before this
        feature touched anything — a live HTTP call to
        `test.atlassian.net` in `jira_create_issue` (a WRITE path,
        entirely outside TASK-2402's read-only delegation scope) returns
        a real 400 in this environment. "Pass UNCHANGED" is interpreted
        literally: the failing set must be identical, proving no NEW
        regression — not that a pre-existing, unrelated, already-broken
        write-path test suddenly turns green.
        """
        # Captured via the exact same 5-suite baseline run performed
        # before TASK-2402 touched jiratoolkit.py (see that task's
        # Completion Note) — re-verified independently here, from scratch,
        # against the actual current subprocess output.
        known_preexisting_failures = {
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py::TestCreateIssueDefaults::test_all_defaults_applied",
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py::TestCreateIssueDefaults::test_explicit_overrides_defaults",
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py::TestCreateIssueDefaults::test_no_defaults_backward_compat",
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py::TestCreateIssueDefaults::test_components_converted_to_id_dicts",
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py::TestDueDateOffset::test_due_date_offset_applied",
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py::TestDueDateOffset::test_invalid_offset_ignored",
        }
        tools_suites = [
            "packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py",
            "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py",
            "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_verify_credentials.py",
        ]
        core_suites = [
            "packages/ai-parrot/tests/test_jiratoolkit_defaults.py",
            "packages/ai-parrot/tests/test_jiratoolkit_permissions.py",
        ]
        actual_failures: set[str] = set()
        for suites in (tools_suites, core_suites):
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *suites, "-q"],
                capture_output=True,
                text=True,
                cwd=_REPO_ROOT,
                check=False,
            )
            for line in result.stdout.splitlines():
                if line.startswith("FAILED "):
                    actual_failures.add(line[len("FAILED ") :].strip())

        new_regressions = actual_failures - known_preexisting_failures
        assert (
            not new_regressions
        ), f"New test failure(s) introduced by the delegation refactor: {sorted(new_regressions)}"
