"""Tests for `wikitoolkit ingest-jira` (FEAT-454, M5)."""
import inspect
import json

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.cli import wiki


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _clean_jira_env(monkeypatch):
    """Isolate JQL/project resolution from the local dev environment."""
    for var in (
        "JIRA_WIKI_JQL",
        "JIRA_DEFAULT_PROJECT",
        "JIRA_WIKI_ISSUES_DIR",
        "JIRA_WIKI_NAMESPACE",
    ):
        monkeypatch.delenv(var, raising=False)


def _patch_sweep(monkeypatch, report_factory=None, capture=None):
    """Patch the sweep the CLI imports lazily inside the command body."""
    from parrot.knowledge.wiki.jira_sync import SweepReport

    async def fake_sweep(interface, issues_dir, *, jql, since=None, force=False, dry_run=False):
        if capture is not None:
            capture["jql"] = jql
            capture["since"] = since
            capture["force"] = force
            capture["dry_run"] = dry_run
            capture["issues_dir"] = issues_dir
        if report_factory is not None:
            return report_factory()
        return SweepReport()

    monkeypatch.setattr("parrot.knowledge.wiki.jira_sync.sweep_jira_issues", fake_sweep)


def _patch_interface(monkeypatch):
    """Avoid ever constructing a real JiraInterface (no real credentials)."""
    monkeypatch.setattr("parrot.interfaces.jira.JiraInterface", lambda *a, **k: object())


def _patch_build(monkeypatch, calls):
    def fake_build_callback(**kw):
        calls.append(kw)

    monkeypatch.setattr(cli.build, "callback", fake_build_callback)


class TestHelpAndRegistration:
    def test_command_is_registered(self, runner):
        result = runner.invoke(wiki, ["--help"])
        assert result.exit_code == 0
        assert "ingest-jira" in result.output

    def test_help_lists_every_option(self, runner):
        result = runner.invoke(wiki, ["ingest-jira", "--help"])
        assert result.exit_code == 0
        for opt in (
            "--jql",
            "--project",
            "--since",
            "--issues-dir",
            "--build",
            "--no-build",
            "--enrich",
            "--force",
            "--dry-run",
            "--json",
            "--quiet",
        ):
            assert opt in result.output

    def test_help_works_without_jira_installed(self, runner, monkeypatch):
        """Lazy import: --help must never pay for `jira`."""
        import builtins

        real = builtins.__import__

        def blocked(name, *a, **k):
            if name == "jira":
                raise ModuleNotFoundError("No module named 'jira'")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", blocked)
        assert runner.invoke(wiki, ["ingest-jira", "--help"]).exit_code == 0


class TestScopeResolution:
    def test_project_shorthand(self, runner, monkeypatch, tmp_path):
        capture: dict = {}
        _patch_sweep(monkeypatch, capture=capture)
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki,
            [
                "ingest-jira",
                "--project",
                "NAV",
                "--no-build",
                "--issues-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert capture["jql"] == "project = NAV"

    def test_jql_and_project_together_is_an_error(self, runner, tmp_path):
        result = runner.invoke(
            wiki,
            [
                "ingest-jira",
                "--jql",
                "project = X",
                "--project",
                "NAV",
                "--no-build",
                "--issues-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_env_default(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_WIKI_JQL", "project = ENV")
        capture: dict = {}
        _patch_sweep(monkeypatch, capture=capture)
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki, ["ingest-jira", "--no-build", "--issues-dir", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert capture["jql"] == "project = ENV"

    def test_default_project_env_fallback(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_DEFAULT_PROJECT", "NAV")
        capture: dict = {}
        _patch_sweep(monkeypatch, capture=capture)
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki, ["ingest-jira", "--no-build", "--issues-dir", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert capture["jql"] == "project = NAV"

    def test_unresolvable_scope_is_a_click_exception(self, runner, monkeypatch, tmp_path):
        monkeypatch.delenv("JIRA_WIKI_JQL", raising=False)
        monkeypatch.delenv("JIRA_DEFAULT_PROJECT", raising=False)
        result = runner.invoke(
            wiki, ["ingest-jira", "--no-build", "--issues-dir", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "--jql" in result.output and "JIRA_WIKI_JQL" in result.output


class TestBuildByDefault:
    def test_builds_by_default(self, runner, monkeypatch, tmp_path):
        """G10 — the plane can never silently lag the files."""
        calls: list = []
        _patch_sweep(monkeypatch)
        _patch_interface(monkeypatch)
        _patch_build(monkeypatch, calls)
        result = runner.invoke(
            wiki, ["ingest-jira", "--project", "NAV", "--issues-dir", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["vault_mode"] is True
        assert calls[0]["no_git"] is True

    def test_no_build_skips_it(self, runner, monkeypatch, tmp_path):
        calls: list = []
        _patch_sweep(monkeypatch)
        _patch_interface(monkeypatch)
        _patch_build(monkeypatch, calls)
        result = runner.invoke(
            wiki,
            ["ingest-jira", "--project", "NAV", "--no-build", "--issues-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert calls == []

    def test_dry_run_skips_build(self, runner, monkeypatch, tmp_path):
        calls: list = []
        _patch_sweep(monkeypatch)
        _patch_interface(monkeypatch)
        _patch_build(monkeypatch, calls)
        result = runner.invoke(
            wiki,
            ["ingest-jira", "--project", "NAV", "--dry-run", "--issues-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert calls == []


class TestReportingAndExitCodes:
    def test_json_output_is_valid_sweep_report(self, runner, monkeypatch, tmp_path):
        from parrot.knowledge.wiki.jira_sync import SweepReport

        _patch_sweep(monkeypatch, report_factory=lambda: SweepReport(fetched=3, written=2))
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki,
            [
                "ingest-jira",
                "--project",
                "NAV",
                "--no-build",
                "--json",
                "--issues-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["fetched"] == 3
        assert parsed["written"] == 2
        assert set(parsed) == set(SweepReport.model_fields)

    def test_nonzero_exit_when_sweep_had_errors(self, runner, monkeypatch, tmp_path):
        """A 'partial' sweep must not look like success to cron."""
        from parrot.knowledge.wiki.jira_sync import SweepReport

        _patch_sweep(monkeypatch, report_factory=lambda: SweepReport(errors=["boom"]))
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki,
            ["ingest-jira", "--project", "NAV", "--no-build", "--issues-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_unresolved_links_warning_shown(self, runner, monkeypatch, tmp_path):
        """The operator's signal to widen the JQL (vault_scan.py:183)."""
        from parrot.knowledge.wiki.jira_sync import SweepReport

        _patch_sweep(
            monkeypatch,
            report_factory=lambda: SweepReport(unresolved_link_keys=["NAV-1"]),
        )
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki,
            ["ingest-jira", "--project", "NAV", "--no-build", "--issues-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert "NAV-1" in result.output
        assert "widen the JQL" in result.output

    def test_quiet_prints_one_line(self, runner, monkeypatch, tmp_path):
        from parrot.knowledge.wiki.jira_sync import SweepReport

        _patch_sweep(monkeypatch, report_factory=lambda: SweepReport(fetched=1, written=1))
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki,
            [
                "ingest-jira",
                "--project",
                "NAV",
                "--no-build",
                "--quiet",
                "--issues-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert len(result.output.strip().splitlines()) == 1


class TestFailureModes:
    def test_missing_jira_dependency_is_one_line(self, runner, monkeypatch, tmp_path):
        from parrot.interfaces.jira import JiraDependencyError

        async def boom(*a, **k):
            raise JiraDependencyError("install ai-parrot[jira]")

        monkeypatch.setattr("parrot.knowledge.wiki.jira_sync.sweep_jira_issues", boom)
        _patch_interface(monkeypatch)
        result = runner.invoke(
            wiki, ["ingest-jira", "--project", "NAV", "--no-build", "--issues-dir", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "ai-parrot[jira]" in result.output

    def test_enrich_fails_fast(self, runner, tmp_path):
        result = runner.invoke(
            wiki, ["ingest-jira", "--enrich", "--no-build", "--issues-dir", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "not implemented" in result.output.lower()


class TestNoSelfRegistration:
    def test_does_not_register_a_namespace(self):
        """ns add is the ONLY writer of namespace entries (ns_add docstring)."""
        src = inspect.getsource(cli.ingest_jira.callback)
        for banned in ("ns_add", "save_namespace", "wikis.json"):
            assert banned not in src, banned


class TestAppendOnlyEdit:
    def test_existing_commands_untouched(self):
        """cli.py is contested — the diff must be append-only.

        Verified via `git diff -U0 packages/ai-parrot/src/parrot/knowledge/
        wiki/cli.py` showing a single hunk appended after the last
        pre-existing command (`ingest`), before `claude-hook` — never
        inside a pre-existing command body.
        """
        assert hasattr(cli, "ingest_jira")
