"""Tests for the host-prepared ``parrot sdd launch worker`` command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from click.testing import CliRunner

from parrot.cli import cli as devloop
from parrot.flows.dev_loop import feature_launcher as launcher

_REAL_PREFLIGHT = launcher._preflight_sandbox


@pytest.fixture(autouse=True)
def _restore_sandbox_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """``launch(sandbox=...)`` writes ``os.environ`` directly; restore it after each test."""
    # setenv first: monkeypatch.delenv records nothing for an absent variable, so teardown
    # would leave whatever launch() wrote; setenv records the original (possibly unset) state.
    monkeypatch.setenv(launcher.native_claude_sandbox.MODE_ENV, "required")
    monkeypatch.delenv(launcher.native_claude_sandbox.MODE_ENV)


# The package under test, pinned for child interpreters. A subprocess started from a linked worktree
# would otherwise import ``parrot`` from the editable-installed primary checkout (see memory:
# worktree tests run main-checkout code), which lacks this feature.
_SRC = str(Path(__file__).resolve().parents[2] / "src")


def _child_env(**extra: str) -> dict[str, str]:
    """Environment for a child interpreter that must import this worktree's ``parrot``."""
    return {**os.environ, "PYTHONPATH": _SRC, **extra}


def _result(argv: list[str], code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a scripted subprocess result."""
    return subprocess.CompletedProcess(argv, code, stdout, stderr)


def _primary(tmp_path: Path) -> Path:
    """Create a minimal primary checkout with one feature index."""
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    index = primary / "sdd" / "tasks" / "index" / "sandbox.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"feature": "sandbox", "feature_id": "FEAT-768", "spec": "sdd/specs/sandbox.md"}),
        encoding="utf-8",
    )
    return primary


def test_resolve_feature_is_case_insensitive_and_skips_orphans(tmp_path: Path) -> None:
    """Feature ids and slugs are both valid case-insensitive launch keys."""
    primary = _primary(tmp_path)
    (primary / "sdd" / "tasks" / "index" / "_orphans.json").write_text("{}", encoding="utf-8")
    ref = launcher.resolve_feature(primary, "feat-768")
    assert ref.feature_id == "FEAT-768"
    assert ref.slug == "sandbox"
    assert ref.index == "sdd/tasks/index/sandbox.json"


def test_resolve_feature_rejects_missing_or_ambiguous_keys(tmp_path: Path) -> None:
    """A launch key must identify exactly one feature index."""
    primary = _primary(tmp_path)
    with pytest.raises(launcher.LaunchError) as missing:
        launcher.resolve_feature(primary, "FEAT-999")
    assert missing.value.exit_code == 2
    duplicate = primary / "sdd" / "tasks" / "index" / "duplicate.json"
    duplicate.write_text(json.dumps({"feature": "other", "feature_id": "FEAT-768", "spec": "x"}), encoding="utf-8")
    with pytest.raises(launcher.LaunchError) as ambiguous:
        launcher.resolve_feature(primary, "FEAT-768")
    assert ambiguous.value.exit_code == 2


def _brief_worktree(tmp_path: Path, slug: str = "fix-thing", key: str | None = None, name: str = "brief-wt") -> Path:
    """Create a worktree directory holding one brief (index + frontmatter), as /sdd-brief leaves it."""
    root = tmp_path / name
    briefs = root / "sdd" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / f"{slug}.index.json").write_text(
        json.dumps(
            {
                "feature": slug,
                "feature_id": f"BRIEF-{slug}",
                "spec": f"sdd/briefs/{slug}.brief.md",
                "type": "brief",
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    (briefs / f"{slug}.brief.md").write_text(
        f"---\nkind: brief\nslug: {slug}\nkey: {key or slug}\n---\n\n# Brief\n", encoding="utf-8"
    )
    return root


def _list_worktrees(monkeypatch: pytest.MonkeyPatch, *roots: Path) -> None:
    """Script ``git worktree list --porcelain`` to report ``roots`` and leave other commands untouched."""
    real = launcher._run

    def fake_run(argv: list[str], *, cwd: Path, env: object = None) -> subprocess.CompletedProcess[str]:
        if list(argv[:3]) == ["git", "worktree", "list"]:
            return _result(argv, stdout="".join(f"worktree {root}\nHEAD abc\nbranch refs/heads/x\n\n" for root in roots))
        return real(argv, cwd=cwd) if env is None else real(argv, cwd=cwd, env=env)

    monkeypatch.setattr(launcher, "_run", fake_run)


@pytest.mark.parametrize("key", ["fix-thing", "FIX-THING", "BRIEF-fix-thing", "JIRA-77"])
def test_resolve_feature_finds_a_brief_by_slug_id_or_frontmatter_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """A brief resolves to its worktree by slug, ``BRIEF-<slug>`` or frontmatter ``key:``, case-insensitively."""
    primary = _primary(tmp_path)
    brief = _brief_worktree(tmp_path, key="JIRA-77")
    _list_worktrees(monkeypatch, primary, brief)
    ref = launcher.resolve_feature(primary, key)
    assert ref.is_brief
    assert ref.worktree == str(brief)
    assert ref.slug == "fix-thing"
    assert ref.prompt_id == "fix-thing"
    assert ref.index == "sdd/briefs/fix-thing.index.json"


def test_resolve_feature_brief_missing_or_ambiguous_is_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No brief, or the same brief in two worktrees, is a LaunchError(2) like an unresolved feature."""
    primary = _primary(tmp_path)
    first = _brief_worktree(tmp_path, name="wt-a")
    second = _brief_worktree(tmp_path, name="wt-b")
    _list_worktrees(monkeypatch, primary, first)
    with pytest.raises(launcher.LaunchError) as missing:
        launcher.resolve_feature(primary, "nope")
    assert missing.value.exit_code == 2
    _list_worktrees(monkeypatch, primary, first, second)
    with pytest.raises(launcher.LaunchError) as ambiguous:
        launcher.resolve_feature(primary, "fix-thing")
    assert ambiguous.value.exit_code == 2


def test_resolve_feature_prefers_feature_index_over_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Feature resolution is unchanged: a feature index wins and carries no worktree."""
    primary = _primary(tmp_path)
    _list_worktrees(monkeypatch, primary, _brief_worktree(tmp_path, slug="sandbox"))
    ref = launcher.resolve_feature(primary, "sandbox")
    assert ref.feature_id == "FEAT-768"
    assert not ref.is_brief
    assert ref.prompt_id == "FEAT-768"


def test_launch_brief_uses_existing_worktree_and_slug_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A brief launch reuses its worktree (no ensure_feature_worktree) and starts the worker with ``run <slug>``."""
    primary = _primary(tmp_path)
    brief = _brief_worktree(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    _list_worktrees(monkeypatch, primary, brief)

    def forbidden(primary: Path, ref: object) -> Path:
        raise AssertionError("a brief must never get a provisioned worktree")

    monkeypatch.setattr(launcher, "ensure_feature_worktree", forbidden)
    monkeypatch.setattr(launcher, "prepare_upstream", lambda path: "launch-worker: ready")
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(
        launcher.native_claude_sandbox, "launch_worker", lambda argv, **kwargs: captured.update(argv=argv, **kwargs) or 0
    )
    result = launcher.launch(
        "BRIEF-fix-thing",
        tmux=False,
        detach=False,
        sandbox="legacy",
        allowed_domains=(),
        no_upstream=False,
        claude_args=(),
    )
    assert result == 0
    assert captured["cwd"] == brief
    assert captured["initial_prompt"] == "run fix-thing"


def test_prepare_upstream_divergence_never_mutates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Divergence is reported for reconciliation rather than merged or pushed."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        values = {
            ("rev-parse", "--abbrev-ref", "HEAD"): "feature\n",
            ("ls-remote", "--heads", "origin", "feature"): "remote feature\n",
            ("rev-parse", "HEAD"): "local\n",
            ("rev-parse", "origin/feature"): "remote\n",
        }
        tail = tuple(argv[1:])
        if tail[:3] == ("merge-base", "--is-ancestor", "local"):
            return _result(argv, 1)
        if tail[:3] == ("merge-base", "--is-ancestor", "remote"):
            return _result(argv, 1)
        return _result(argv, stdout=values.get(tail, ""))

    monkeypatch.setattr(launcher, "_run", fake_run)
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.prepare_upstream(worktree)
    assert exc.value.exit_code == 2
    assert not any(command[1] in {"merge", "push"} for command in calls)


def test_launch_non_tmux_passes_worktree_and_worker_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal launch performs host prep then delegates in the provisioned worktree."""
    primary = _primary(tmp_path)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "prepare_upstream", lambda path: "launch-worker: ready")
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(
        launcher.native_claude_sandbox,
        "launch_worker",
        lambda argv, **kwargs: captured.update(argv=argv, **kwargs) or 0,
    )
    assert (
        launcher.launch(
            "sandbox",
            tmux=False,
            detach=False,
            sandbox="legacy",
            allowed_domains=("api.example.com",),
            no_upstream=False,
            claude_args=("--", "--verbose"),
        )
        == 0
    )
    assert captured["cwd"] == worktree
    assert captured["initial_prompt"] == "run FEAT-768"
    assert captured["argv"] == ["--sandbox-allow-domain", "api.example.com", "--", "--verbose"]


def test_launch_no_gh_token_reaches_launch_worker_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """gh_token=False forwards the launcher-owned flag on the direct path."""
    primary = _primary(tmp_path)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(
        launcher.native_claude_sandbox, "launch_worker", lambda argv, **kwargs: captured.update(argv=argv) or 0
    )
    kwargs = dict(tmux=False, detach=False, sandbox="legacy", allowed_domains=(), no_upstream=True, claude_args=())
    assert launcher.launch("sandbox", gh_token=False, **kwargs) == 0
    assert captured["argv"] == ["--no-gh-token"]
    assert launcher.launch("sandbox", **kwargs) == 0
    assert captured["argv"] == []


def test_bad_primary_launch_config_fails_before_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed primary-checkout config is a LaunchError(2) raised before tmux/launch starts."""
    primary = _primary(tmp_path)
    (primary / "pyproject.toml").write_text('[tool.parrot.sdd]\nsandbox_allowed_domains = ["https://github.com"]\n')
    worktree = tmp_path / "feature"
    worktree.mkdir()
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.launch(
            "sandbox", tmux=False, detach=False, sandbox="legacy", allowed_domains=(), no_upstream=True, claude_args=()
        )
    assert exc.value.exit_code == 2


def test_tmux_child_receives_no_gh_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The tmux child command line carries --no-gh-token, and main() forwards it to launch_worker."""
    primary = _primary(tmp_path)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    calls: list[list[str]] = []
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr(launcher.native_claude_sandbox, "sandbox_platform", lambda: "linux")
    monkeypatch.setattr(launcher, "_run", _tmux_runner(calls, panes=["0|||claude"]))
    launcher.launch(
        "FEAT-768",
        tmux=True,
        detach=True,
        sandbox="legacy",
        allowed_domains=(),
        no_upstream=True,
        claude_args=(),
        gh_token=False,
    )
    assert "--no-gh-token" in calls[0][calls[0].index("--in-session") :]
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        launcher.native_claude_sandbox, "launch_worker", lambda argv, **kwargs: seen.update(argv=argv) or 0
    )
    assert launcher.main(["--in-session", "FEAT-768", "--cwd", str(worktree), "--no-gh-token"]) == 0
    assert seen["argv"] == ["--no-gh-token"]


def test_tmux_new_session_carries_environment_and_detaches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Detached tmux workers receive the preparation environment explicitly."""
    primary = _primary(tmp_path)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    calls: list[list[str]] = []
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setenv("PARROT_SDD_EXTRA", "yes")
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr(launcher.native_claude_sandbox, "sandbox_platform", lambda: "linux")
    monkeypatch.setattr(launcher, "_run", _tmux_runner(calls, panes=["0|||claude"]))
    assert (
        launcher.launch(
            "FEAT-768", tmux=True, detach=True, sandbox="legacy", allowed_domains=(), no_upstream=True, claude_args=()
        )
        == 0
    )
    command = calls[0]
    assert command[:8] == ["tmux", "new-session", "-d", "-s", "sdd-feat-768-sandbox", "-c", str(worktree), "-e"]
    assert "PARROT_SDD_SANDBOX_MODE=legacy" in command
    assert "PARROT_SDD_EXTRA=yes" in command
    assert command[-7:] == [";", "set-option", "-w", "-t", "=sdd-feat-768-sandbox:", "remain-on-exit", "failed"]
    tail = command[command.index("--") : command.index(";")]
    assert tail == [
        "--",
        launcher.sys.executable,
        "-S",
        str(Path(launcher.__file__).resolve()),
        "--in-session",
        "FEAT-768",
        "--cwd",
        str(worktree),
    ]


@pytest.fixture(autouse=True)
def _no_real_sandbox_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host preflight has dedicated tests; elsewhere it must not probe the real host."""
    monkeypatch.setattr(launcher, "_preflight_sandbox", lambda worktree, domains: None)


@pytest.fixture(autouse=True)
def _no_grace_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The detach start poll sleeps in real time; tests never wait for it."""
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)


def _upstream_runner(
    calls: list[list[str]],
    *,
    remote: str,
    local: str = "local",
    remote_sha: str = "remote",
    ancestors: set = frozenset(),
):
    """Script ``_run`` for ``prepare_upstream``; ``ancestors`` holds the (older, newer) pairs that are ancestry."""

    def fake_run(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        tail = tuple(argv[1:])
        if tail[:2] == ("merge-base", "--is-ancestor"):
            return _result(argv, 0 if (tail[2], tail[3]) in ancestors else 1)
        values = {
            ("rev-parse", "--abbrev-ref", "HEAD"): "feature\n",
            ("ls-remote", "--heads", "origin", "feature"): remote,
            ("rev-parse", "HEAD"): f"{local}\n",
            ("rev-parse", "origin/feature"): f"{remote_sha}\n",
        }
        return _result(argv, stdout=values.get(tail, ""))

    return fake_run


def _git_verbs(calls: list[list[str]]) -> list[str]:
    """Return the git sub-commands that were run, in order."""
    return [command[1] for command in calls if command[0] == "git"]


def test_prepare_upstream_pushes_when_remote_branch_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A branch unknown to origin is pushed with tracking and nothing else."""
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "_run", _upstream_runner(calls, remote=""))
    assert "pushed" in launcher.prepare_upstream(tmp_path)
    assert ["git", "push", "-u", "origin", "feature"] in calls
    assert "fetch" not in _git_verbs(calls) and "merge" not in _git_verbs(calls)


def test_prepare_upstream_fast_forwards_when_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A local branch strictly behind origin is fast-forwarded only, then tracks origin."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        launcher, "_run", _upstream_runner(calls, remote="sha refs/heads/feature\n", ancestors={("local", "remote")})
    )
    assert "fast-forwarded" in launcher.prepare_upstream(tmp_path)
    assert ["git", "merge", "--ff-only", "origin/feature"] in calls
    assert ["git", "branch", "--set-upstream-to", "origin/feature", "feature"] in calls
    assert "push" not in _git_verbs(calls)


@pytest.mark.parametrize(
    ("local", "ancestors", "status"),
    [("remote", set(), "up to date"), ("local", {("remote", "local")}, "local ahead")],
)
def test_prepare_upstream_sets_tracking_when_equal_or_ahead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local: str, ancestors: set, status: str
) -> None:
    """Equal or ahead branches only gain an upstream; the worker pushes its own commits."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        launcher, "_run", _upstream_runner(calls, remote="sha refs/heads/feature\n", local=local, ancestors=ancestors)
    )
    assert status in launcher.prepare_upstream(tmp_path)
    assert ["git", "branch", "--set-upstream-to", "origin/feature", "feature"] in calls
    assert not {"merge", "push"} & set(_git_verbs(calls))


def test_prepare_upstream_git_failure_is_exit_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A network/git failure is a host error, never silently skipped."""
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: _result(argv, 128, stderr="could not resolve host"))
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.prepare_upstream(tmp_path)
    assert exc.value.exit_code == 1 and "could not resolve host" in str(exc.value)


def test_ensure_feature_worktree_uses_json_runner_and_surfaces_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worktree path comes from ``ensure_worktree --json``; its failure is exit 1 with stderr."""
    primary = _primary(tmp_path)
    ref = launcher.resolve_feature(primary, "FEAT-768")
    calls: list[list[str]] = []
    payload = json.dumps({"path": str(tmp_path / "wt")})
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: calls.append(argv) or _result(argv, stdout=payload))
    assert launcher.ensure_feature_worktree(primary, ref) == tmp_path / "wt"
    assert calls[0][1:3] == ["-m", "parrot.sdd.scripts.ensure_worktree"] and calls[0][-1] == "--json"
    assert calls[0][calls[0].index("--index") + 1] == "sdd/tasks/index/sandbox.json"

    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: _result(argv, 1, stderr="spec missing"))
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.ensure_feature_worktree(primary, ref)
    assert exc.value.exit_code == 1 and "spec missing" in str(exc.value)


def _no_host_prep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if any host preparation step runs."""
    boom = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("host prep must not run"))  # noqa: E731
    monkeypatch.setattr(launcher, "ensure_feature_worktree", boom)
    monkeypatch.setattr(launcher, "prepare_upstream", boom)


def test_existing_session_refuses_non_tmux_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second console for a feature already running in tmux is refused before host prep."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    _no_host_prep(monkeypatch)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: name == "sdd-feat-768-sandbox")
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.launch(
            "FEAT-768", tmux=False, detach=False, sandbox=None, allowed_domains=(), no_upstream=False, claude_args=()
        )
    assert exc.value.exit_code == 2 and "sdd-feat-768-sandbox" in str(exc.value)


@pytest.mark.parametrize("inside_tmux", [False, True])
def test_existing_session_attaches_without_host_prep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inside_tmux: bool
) -> None:
    """``--tmux`` on a running session attaches (or switches client inside tmux) with no host prep."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    _no_host_prep(monkeypatch)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: True)
    if inside_tmux:
        monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    else:
        monkeypatch.delenv("TMUX", raising=False)
    calls: list[list[str]] = []
    execs: list[list[str]] = []
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: calls.append(argv) or _result(argv))
    monkeypatch.setattr(launcher.os, "execvp", lambda file, args: execs.append(args))
    launcher.launch(
        "FEAT-768", tmux=True, detach=False, sandbox=None, allowed_domains=(), no_upstream=False, claude_args=()
    )
    if inside_tmux:
        assert calls == [["tmux", "switch-client", "-t", "sdd-feat-768-sandbox"]] and not execs
    else:
        assert execs == [["tmux", "attach-session", "-t", "sdd-feat-768-sandbox"]] and not calls


def test_existing_session_with_detach_only_prints_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--tmux --detach`` on a running session neither preps nor attaches."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    _no_host_prep(monkeypatch)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: True)
    monkeypatch.setattr(launcher, "_attach_session", lambda name: pytest.fail("must not attach with --detach"))
    assert (
        launcher.launch(
            "FEAT-768", tmux=True, detach=True, sandbox=None, allowed_domains=(), no_upstream=True, claude_args=()
        )
        == 0
    )
    assert "tmux attach -t sdd-feat-768-sandbox" in capsys.readouterr().err


# --- issue:a94869a0df2b: tmux session names must not collide across repositories ---------------------------


@pytest.mark.parametrize(
    ("feature_id", "slug", "expected"),
    [
        ("FEAT-2", "simple-agent", "sdd-feat-2-simple-agent"),
        ("FEAT-2", "v1.2:api", "sdd-feat-2-v1-2-api"),
        ("FEAT-7", "", "sdd-feat-7"),
    ],
)
def test_tmux_session_name_includes_slug_and_is_tmux_safe(feature_id: str, slug: str, expected: str) -> None:
    """The name is ``sdd-<feature id>-<slug>``, lower-cased, without ``.`` or ``:``."""
    assert launcher.tmux_session_name(feature_id, slug) == expected


def test_tmux_session_name_truncates_long_slug() -> None:
    """A very long slug is cut so the name stays within 64 characters and never ends in ``-``."""
    name = launcher.tmux_session_name("FEAT-1234", "a-" * 60)
    assert len(name) <= 64 and name.startswith("sdd-feat-1234-a") and not name.endswith("-")
    assert launcher.tmux_session_name("FEAT-1234", "a-" * 60) == name  # deterministic


def _legacy_session(monkeypatch: pytest.MonkeyPatch, session_path: Path) -> list[list[str]]:
    """Only the legacy ``sdd-FEAT-768`` session exists, started in ``session_path``."""
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: name == "sdd-FEAT-768")

    def fake_run(argv: list[str], *, cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[:2] == ["tmux", "display-message"] and argv[-1] == "#{session_path}":
            return _result(argv, stdout=f"{session_path}\n")
        return _result(argv)

    monkeypatch.setattr(launcher, "_run", fake_run)
    return calls


def test_legacy_session_of_this_repo_is_still_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live pre-fix ``sdd-<FEAT-ID>`` session started inside this checkout still blocks a duplicate worker."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    _no_host_prep(monkeypatch)
    worktree = primary / ".claude" / "worktrees" / "feat-FEAT-768-sandbox"
    worktree.mkdir(parents=True)
    _legacy_session(monkeypatch, worktree)
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.launch(
            "FEAT-768", tmux=False, detach=False, sandbox=None, allowed_domains=(), no_upstream=False, claude_args=()
        )
    assert exc.value.exit_code == 2 and "tmux session sdd-FEAT-768;" in str(exc.value)


def test_legacy_session_of_this_repo_is_reattached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--tmux`` reattaches to this repo's live legacy session instead of launching a second worker."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.delenv("TMUX", raising=False)
    _no_host_prep(monkeypatch)
    _legacy_session(monkeypatch, primary)
    execs: list[list[str]] = []
    monkeypatch.setattr(launcher.os, "execvp", lambda file, args: execs.append(args))
    launcher.launch(
        "FEAT-768", tmux=True, detach=False, sandbox=None, allowed_domains=(), no_upstream=False, claude_args=()
    )
    assert execs == [["tmux", "attach-session", "-t", "sdd-FEAT-768"]]


def test_legacy_session_of_another_repo_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Another repository's ``sdd-FEAT-768`` is never attached to: a new, slug-named worker is launched."""
    primary = _primary(tmp_path)
    other_repo = tmp_path / "other-repo" / ".claude" / "worktrees" / "feat-FEAT-768-other"
    other_repo.mkdir(parents=True)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: worktree)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr(launcher.native_claude_sandbox, "sandbox_platform", lambda: "linux")
    monkeypatch.setattr(launcher, "_await_worker_start", lambda name: None)
    calls = _legacy_session(monkeypatch, other_repo)
    assert (
        launcher.launch(
            "FEAT-768", tmux=True, detach=True, sandbox="legacy", allowed_domains=(), no_upstream=True, claude_args=()
        )
        == 0
    )
    new_sessions = [argv for argv in calls if argv[:2] == ["tmux", "new-session"]]
    assert len(new_sessions) == 1 and new_sessions[0][4] == "sdd-feat-768-sandbox"
    assert not any(argv[:2] in (["tmux", "attach-session"], ["tmux", "switch-client"]) for argv in calls)


@pytest.mark.parametrize(
    ("platform", "tmux_path", "match"),
    [("windows", "/usr/bin/tmux", "native Windows"), ("linux", None, "tmux is not available")],
)
def test_tmux_refused_on_windows_or_without_tmux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, tmux_path: str | None, match: str
) -> None:
    """``--tmux`` needs a POSIX host with tmux on PATH; otherwise it is a host error (exit 1)."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: tmp_path)
    monkeypatch.setattr(launcher.native_claude_sandbox, "sandbox_platform", lambda: platform)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: tmux_path)
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: pytest.fail(f"no tmux command may run: {argv}"))
    with pytest.raises(launcher.LaunchError, match=match) as exc:
        launcher.launch(
            "FEAT-768", tmux=True, detach=True, sandbox=None, allowed_domains=(), no_upstream=True, claude_args=()
        )
    assert exc.value.exit_code == 1


def test_invalid_sandbox_mode_is_exit_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown ``--sandbox`` value is caller input, rejected before anything else."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    _no_host_prep(monkeypatch)
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.launch(
            "FEAT-768", tmux=False, detach=False, sandbox="bogus", allowed_domains=(), no_upstream=True, claude_args=()
        )
    assert exc.value.exit_code == 2
    assert launcher.native_claude_sandbox.MODE_ENV not in launcher.os.environ


def test_sandbox_flag_reaches_non_tmux_child_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--sandbox legacy`` is in ``PARROT_SDD_SANDBOX_MODE`` when ``launch_worker`` resolves the mode."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: tmp_path)
    seen: list[str | None] = []
    monkeypatch.setattr(
        launcher.native_claude_sandbox,
        "launch_worker",
        lambda argv, **kwargs: seen.append(launcher.os.environ.get(launcher.native_claude_sandbox.MODE_ENV)) or 0,
    )
    launcher.launch(
        "FEAT-768", tmux=False, detach=False, sandbox="legacy", allowed_domains=(), no_upstream=True, claude_args=()
    )
    assert seen == ["legacy"]


def test_click_command_maps_launch_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy Click surface returns the launcher error code and diagnostic."""
    monkeypatch.setattr(
        launcher, "launch", lambda *args, **kwargs: (_ for _ in ()).throw(launcher.LaunchError(2, "bad key"))
    )
    result = CliRunner().invoke(devloop, ["sdd", "launch", "worker", "missing"])
    assert result.exit_code == 2
    assert "launch-worker: bad key" in result.output


def test_preflight_refusal_happens_before_push_or_tmux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable sandbox fails on the host before the branch is pushed or a session is created."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "_preflight_sandbox", _REAL_PREFLIGHT)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: tmp_path)
    monkeypatch.setattr(launcher, "prepare_upstream", lambda path: pytest.fail("must not push before preflight"))
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: pytest.fail(f"no host command may run: {argv}"))

    def refuse(cwd: Path, *, allowed_domains=()):
        raise RuntimeError("missing prerequisite(s): bwrap")

    monkeypatch.setattr(launcher.native_claude_sandbox, "plan_native_launch", refuse)
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.launch(
            "FEAT-768", tmux=True, detach=True, sandbox=None, allowed_domains=(), no_upstream=False, claude_args=()
        )
    assert exc.value.exit_code == 1 and "bwrap" in str(exc.value)


def test_launch_resolves_from_invocation_dir_not_process_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The primary checkout comes from the shell's PWD, which survives navconfig's chdir on import."""
    primary = _primary(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PWD", str(primary))
    seen: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_primary_checkout", lambda cwd: seen.append(cwd) or primary)
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: True)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(
            "FEAT-768", tmux=False, detach=False, sandbox=None, allowed_domains=(), no_upstream=True, claude_args=()
        )
    assert seen == [primary]


def test_in_session_child_runs_in_the_worktree_after_parrot_import(tmp_path: Path) -> None:
    """Regression: importing parrot chdirs away from tmux's -c directory; --cwd must still win."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    code = (
        "from pathlib import Path; "
        "from parrot.flows.dev_loop import feature_launcher as fl; "
        "seen = {}; "
        "fl.native_claude_sandbox.launch_worker = lambda argv, **kw: seen.update(kw) or 0; "
        f"rc = fl.main(['--in-session', 'FEAT-768', '--cwd', {str(worktree)!r}]); "
        f"assert rc == 0 and seen['cwd'] == Path({str(worktree)!r}), seen; "
        "assert seen['initial_prompt'] == 'run FEAT-768'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=worktree, capture_output=True, text=True, timeout=60, env=_child_env()
    )
    assert result.returncode == 0, result.stderr[-2000:]


def _tmux_runner(calls: list[list[str]], *, panes: list[str]) -> object:
    """Script tmux: ``new-session`` succeeds; successive ``display-message`` calls return ``panes``."""
    states = iter(panes)
    last = {"value": panes[-1]}

    def fake_run(argv: list[str], *, cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[:2] == ["tmux", "display-message"]:
            last["value"] = next(states, last["value"])
            return _result(argv, stdout=f"{last['value']}\n")
        return _result(argv)

    return fake_run


def _tmux_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, exists: bool) -> None:
    """Common tmux-host stubs for detach tests."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: exists)
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr(launcher.native_claude_sandbox, "sandbox_platform", lambda: "linux")


def _launch_detached() -> int:
    return launcher.launch(
        "FEAT-768", tmux=True, detach=True, sandbox=None, allowed_domains=(), no_upstream=True, claude_args=()
    )


def test_detached_launch_reports_a_worker_that_died_while_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launcher keeps polling while the child is still python, and reports it when the pane dies."""
    _tmux_host(tmp_path, monkeypatch, exists=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "_run", _tmux_runner(calls, panes=["0|||python", "0|||python", "1|3||python"]))
    with pytest.raises(launcher.LaunchError) as exc:
        _launch_detached()
    assert exc.value.exit_code == 1
    assert "exited (status 3)" in str(exc.value) and "tmux kill-session -t sdd-feat-768-sandbox" in str(exc.value)
    assert sum(command[:2] == ["tmux", "display-message"] for command in calls) == 3


def test_detached_launch_reports_a_signalled_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker killed by a signal has no exit status; the signal is reported instead."""
    _tmux_host(tmp_path, monkeypatch, exists=False)
    monkeypatch.setattr(launcher, "_run", _tmux_runner([], panes=["1||9|claude"]))
    with pytest.raises(launcher.LaunchError, match=r"exited \(signal 9\)"):
        _launch_detached()


def test_detached_launch_returns_once_the_worker_execs_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Success is the pane leaving the python launcher for claude, then the attach hint and exit 0."""
    _tmux_host(tmp_path, monkeypatch, exists=False)
    slept: list[float] = []
    monkeypatch.setattr(launcher.time, "sleep", slept.append)
    monkeypatch.setattr(launcher, "_run", _tmux_runner([], panes=["0|||python3.12", "0|||claude"]))
    assert _launch_detached() == 0
    assert slept == [launcher._DETACH_POLL_SECONDS]
    err = capsys.readouterr().err
    assert "tmux attach -t sdd-feat-768-sandbox" in err and "WARNING" not in err


def test_detached_launch_warns_when_start_cannot_be_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A child still in python at the deadline is not an error, but the operator is told to check it."""
    _tmux_host(tmp_path, monkeypatch, exists=False)
    clock = iter([0.0, 10.0, launcher._DETACH_START_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(launcher, "_run", _tmux_runner([], panes=["0|||python"]))
    assert _launch_detached() == 0
    assert "WARNING could not confirm the worker in sdd-feat-768-sandbox started" in capsys.readouterr().err


def test_detach_on_existing_dead_session_reports_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-running ``--tmux --detach`` on a session whose worker died says so instead of a success hint."""
    _tmux_host(tmp_path, monkeypatch, exists=True)
    monkeypatch.setattr(launcher, "_run", _tmux_runner([], panes=["1|1||python"]))
    with pytest.raises(launcher.LaunchError, match=r"exited \(status 1\)") as exc:
        _launch_detached()
    assert exc.value.exit_code == 1


@pytest.mark.parametrize(
    ("stdout", "code", "expected"),
    [("1|3||python", 0, "status 3"), ("1||15|claude", 0, "signal 15"), ("0|||claude", 0, None), ("", 1, None)],
)
def test_dead_worker_status_parsing(
    monkeypatch: pytest.MonkeyPatch, stdout: str, code: int, expected: str | None
) -> None:
    """Only a dead pane reports how it ended; a live pane or a missing session is ``None``."""
    monkeypatch.setattr(launcher, "_run", lambda argv, *, cwd: _result(argv, code, stdout=stdout))
    assert launcher._dead_worker_status("sdd-FEAT-768") == expected


# --- issue:82503cfbb76a: navconfig-loaded secrets must never reach the worker -----------------------------


def _tmux_new_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, base_env: dict[str, str]) -> dict:
    """Run a detached tmux launch and return the recorded ``new-session`` argv and env."""
    _tmux_host(tmp_path, monkeypatch, exists=False)
    seen: dict = {}

    def fake_run(argv: list[str], *, cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
        if argv[:2] == ["tmux", "new-session"]:
            seen.update(argv=argv, env=env)
        if argv[:2] == ["tmux", "display-message"]:
            return _result(argv, stdout="0|||claude\n")
        return _result(argv)

    monkeypatch.setattr(launcher, "_run", fake_run)
    launcher.launch(
        "FEAT-768",
        tmux=True,
        detach=True,
        sandbox="preferred",
        allowed_domains=(),
        no_upstream=True,
        claude_args=(),
        base_env=base_env,
    )
    return seen


def test_tmux_client_and_e_pairs_use_the_pre_import_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variables only in the loaded os.environ never reach the tmux client env or its -e pairs."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-dotenv")
    monkeypatch.setenv("PARROT_SDD_FROM_DOTENV", "leak")
    base_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "DISPLAY": ":7",
        "PARROT_SDD_OPERATOR": "kept",
        "PARROT_SDD_NOTIFY_HELPER": "/stale/helper.py",
    }
    seen = _tmux_new_session(tmp_path, monkeypatch, base_env=base_env)
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "PARROT_SDD_FROM_DOTENV" not in seen["env"]
    assert seen["env"]["PARROT_SDD_OPERATOR"] == "kept"
    assert seen["env"]["PARROT_SDD_SANDBOX_MODE"] == "preferred"
    assert "PARROT_SDD_OPERATOR=kept" in seen["argv"] and "PARROT_SDD_SANDBOX_MODE=preferred" in seen["argv"]
    assert not any("FROM_DOTENV" in item or "sk-from-dotenv" in item for item in seen["argv"])
    assignments = dict(item.split("=", 1) for item in seen["argv"] if item.startswith("PARROT_SDD_"))
    assert assignments["PARROT_SDD_NOTIFY_FEATURE"] == "FEAT-768"
    assert assignments["PARROT_SDD_NOTIFY_SLUG"] == "sandbox"
    assert json.loads(assignments["PARROT_SDD_NOTIFY_DESKTOP"]) == {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "DISPLAY": ":7",
    }
    assert "PARROT_SDD_NOTIFY_HELPER" not in assignments


def test_non_tmux_launch_hands_the_pre_import_environment_to_launch_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The direct launch passes the snapshot (plus the sandbox mode) as the worker's base environment."""
    primary = _primary(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.setenv("PWD", str(primary))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-dotenv")
    monkeypatch.setattr(launcher, "tmux_session_exists", lambda name: False)
    monkeypatch.setattr(launcher, "ensure_feature_worktree", lambda primary, ref: tmp_path)
    captured: dict = {}
    monkeypatch.setattr(
        launcher.native_claude_sandbox, "launch_worker", lambda argv, **kwargs: captured.update(kwargs) or 0
    )
    launcher.launch(
        "FEAT-768",
        tmux=False,
        detach=False,
        sandbox="legacy",
        allowed_domains=(),
        no_upstream=True,
        claude_args=(),
        base_env={"PATH": "/usr/bin", "PARROT_SDD_NOTIFY_FEATURE": "stale", "PARROT_SDD_NOTIFY_HELPER": "stale"},
    )
    assert captured["base_env"] == {"PATH": "/usr/bin", "PARROT_SDD_SANDBOX_MODE": "legacy"}


def test_launch_worker_starts_claude_from_base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """native launch_worker builds the claude env from base_env, not from os.environ."""
    native = launcher.native_claude_sandbox
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-dotenv")
    monkeypatch.setattr(native.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(native, "_native_roots", lambda cwd: (tmp_path, tmp_path / ".git", tmp_path))
    monkeypatch.setattr(native, "resolve_sandbox_mode", lambda root: "required")
    monkeypatch.setattr(native, "plan_native_launch", lambda *args, **kwargs: ("required", False, "", {}))
    monkeypatch.setattr(native, "native_root_env", lambda cwd: {})
    monkeypatch.setattr(native, "sandbox_platform", lambda: "linux")
    monkeypatch.setattr(native, "_allocate_session_cache", lambda: tmp_path / "cache")
    monkeypatch.setattr(native.os, "chdir", lambda path: None)
    execs: list[dict] = []
    monkeypatch.setattr(native.os, "execvpe", lambda file, args, env: execs.append(env))
    native.launch_worker([], cwd=tmp_path, base_env={"PATH": "/usr/bin", "HOME": str(tmp_path)})
    assert execs and "ANTHROPIC_API_KEY" not in execs[0]
    assert execs[0]["PATH"] == "/usr/bin"


def test_tmux_child_script_runs_without_site_packages(tmp_path: Path) -> None:
    """The tmux child is stdlib-only under ``python -S``: parrot/navconfig cannot even be imported there."""
    script = str(Path(launcher.__file__).resolve())
    result = subprocess.run(
        [sys.executable, "-S", script, "--in-session", "FEAT-768", "--cwd", str(tmp_path), "--", "--agent", "other"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )
    # It got as far as the launcher's own argument policy, i.e. every import succeeded without site-packages.
    assert result.returncode == 2, result.stderr
    assert "--agent must be sdd-worker" in result.stderr


def test_cli_snapshots_environment_before_importing_parrot_flows(tmp_path: Path) -> None:
    """Regression: the click command snapshots os.environ BEFORE importing parrot.flows.

    The import is simulated by a meta-path loader for ``feature_launcher`` that injects a secret into
    os.environ while it executes — as navconfig does with the settings ``.env`` — so the check does
    not depend on the developer machine having a populated ``.env``.
    """
    code = """
import importlib.abc, importlib.util, os, sys
from click.testing import CliRunner
from parrot.cli import cli as devloop

NAME = "parrot.flows.dev_loop.feature_launcher"
seen = {}

class LaunchError(Exception):
    exit_code = 1

def launch(*args, base_env=None, **kwargs):
    seen["base_env"] = base_env
    return 0

class Loader(importlib.abc.Loader):
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        os.environ["ANTHROPIC_API_KEY"] = "sk-injected-by-import"
        module.LaunchError, module.launch = LaunchError, launch

class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        return importlib.util.spec_from_loader(fullname, Loader()) if fullname == NAME else None

sys.meta_path.insert(0, Finder())
sys.modules.pop(NAME, None)
os.environ.pop("ANTHROPIC_API_KEY", None)
result = CliRunner().invoke(devloop, ["sdd", "launch", "worker", "FEAT-768"])
assert result.exit_code == 0, result.output
assert os.environ.get("ANTHROPIC_API_KEY") == "sk-injected-by-import", "probe import never ran"
assert "ANTHROPIC_API_KEY" not in seen["base_env"], "base_env was taken after the import"
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        env={**{k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}, "PYTHONPATH": _SRC},
    )
    assert result.returncode == 0, result.stderr[-3000:]


def _capture_exec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Mock ``claude`` discovery and exec; point the invocation dir at a primary checkout."""
    primary = _primary(tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(launcher, "_invocation_dir", lambda: primary)
    monkeypatch.setattr(launcher.os, "chdir", lambda path: seen.__setitem__("cwd", Path(path)))

    def _exec(file: str, argv: list[str], env: dict[str, str]) -> None:
        seen.update(argv=list(argv), env=env)
        raise SystemExit(0)  # the real exec never returns

    monkeypatch.setattr(launcher.os, "execvpe", _exec)
    seen["primary"] = primary
    return seen


@pytest.mark.parametrize(
    ("argv", "prompt"),
    [
        (["sdd", "launch", "brief", "NAV-1", "--no-interview"], "/sdd-brief NAV-1 --no-interview"),
        (["sdd", "launch", "fix", "--top", "2"], "/sdd-fix --top 2"),
    ],
)
def test_launch_brief_and_fix_exec_slash_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str], prompt: str
) -> None:
    """brief/fix run a plain Claude session in the primary checkout with the slash command as the last argument."""
    seen = _capture_exec(monkeypatch, tmp_path)
    result = CliRunner().invoke(devloop, argv)
    assert result.exit_code == 0, result.output
    command = seen["argv"]
    assert isinstance(command, list)
    assert seen["cwd"] == seen["primary"]
    assert command[-1] == prompt
    assert command[1:3] == ["--setting-sources", "project,local"]
    assert "--model" in command
    assert "--agent" not in command and "--settings" not in command


def test_launch_help_lists_three_verbs() -> None:
    """The launch noun carries worker, brief and fix; the devloop spelling is gone."""
    result = CliRunner().invoke(devloop, ["sdd", "launch", "--help"])
    assert result.exit_code == 0
    for verb in ("worker", "brief", "fix"):
        assert verb in result.output
    assert "Usage" in CliRunner().invoke(devloop, ["devloop", "launch-worker"]).output
