"""Real temporary Git integration tests for worktree sync."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.scripts import native_claude_sandbox, worktree_sync


def _run(path: Path, *args: str) -> str:
    """Run Git in a disposable repository and return stdout."""
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=True).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a primary clone, its bare origin, and a linked feature worktree."""
    origin = tmp_path / "origin.git"
    primary = tmp_path / "primary"
    feature = tmp_path / "feature"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(origin), str(primary)], check=True, capture_output=True, text=True)
    _run(primary, "config", "user.email", "test@example.invalid")
    _run(primary, "config", "user.name", "Sync Test")
    (primary / "shared.txt").write_text("base\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "initial")
    _run(primary, "branch", "-M", "dev")
    _run(primary, "push", "-u", "origin", "dev")
    _run(primary, "worktree", "add", "-b", "feat-FEAT-999-sync", str(feature), "dev")
    return origin, primary, feature


def _configure_sandbox(feature: Path) -> None:
    """Install the host-owned read-only sandbox prerequisite in a disposable worktree."""
    _run(feature, "remote", "set-url", "origin", "git@github.com:example/sync.git")
    _run(feature, "config", "extensions.worktreeConfig", "true")
    _run(feature, "config", "--worktree", "remote.origin.pushurl", "no_push")


def _install_gh_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, responses: dict[str, tuple[dict[str, object], str]]
) -> None:
    """Provide deterministic metadata and patch responses through a PATH-local gh stub."""
    fixtures = tmp_path / "gh-fixtures"
    fixtures.mkdir()
    for sha, (metadata, patch) in responses.items():
        (fixtures / f"{sha}.json").write_text(json.dumps(metadata), encoding="utf-8")
        (fixtures / f"{sha}.patch").write_text(patch, encoding="utf-8")
    executable = tmp_path / "gh"
    executable.write_text(
        "#!/bin/sh\n"
        'for argument in "$@"; do case "$argument" in repos/*) endpoint=$argument ;; esac; done\n'
        "sha=${endpoint##*/}\n"
        'case "$*" in\n'
        "  *'Accept: application/vnd.github.patch'*) cat \"$GH_FIXTURES/$sha.patch\" ;;\n"
        '  *) cat "$GH_FIXTURES/$sha.json" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("GH_FIXTURES", str(fixtures))
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")


def _patch_response(primary: Path, sha: str) -> tuple[dict[str, object], str]:
    """Build the two gh API representations of a real local commit."""
    subject = _run(primary, "show", "-s", "--format=%s", sha)
    parent = _run(primary, "rev-parse", f"{sha}^")
    patch = _run(primary, "format-patch", "--stdout", "-1", sha)
    return {"sha": sha, "parents": [{"sha": parent}], "commit": {"message": subject}}, patch


def _native_cli() -> Path:
    """Return the real Claude CLI or mark the required qualification unvalidated."""
    if os.environ.get("PARROT_TEST_REAL_LLM") != "1":
        pytest.skip("UNVALIDATED REQUIRED GATE: set PARROT_TEST_REAL_LLM=1 to exercise the real native boundary")
    available, reason = native_claude_sandbox.native_sandbox_available()
    if not available:
        pytest.skip(f"UNVALIDATED REQUIRED GATE: native sandbox unavailable: {reason}")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        executable = Path(directory) / "claude"
        if executable.is_file() and os.access(executable, os.X_OK):
            return executable
    pytest.skip("UNVALIDATED REQUIRED GATE: Claude CLI is unavailable")


def _native_session(feature: Path, command: str) -> subprocess.CompletedProcess[str]:
    """Run one bounded Bash command through Claude's generated native policy."""
    executable = _native_cli()
    settings = native_claude_sandbox.native_sandbox_settings(feature)
    source = Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"
    environment = {
        **os.environ,
        **native_claude_sandbox.native_root_env(feature),
        native_claude_sandbox.BACKEND_ENV: native_claude_sandbox.BACKEND_NATIVE,
        "PYTHONPATH": str(source),
    }
    prompt = f"Use Bash once to run exactly this command, then stop and report its output verbatim:\n{command}"
    return subprocess.run(
        [
            str(executable),
            "-p",
            prompt,
            "--model",
            "haiku",
            "--max-turns",
            "2",
            "--max-budget-usd",
            "0.20",
            "--permission-mode",
            "bypassPermissions",
            "--tools",
            "Bash",
            "--setting-sources",
            "project,local",
            "--settings",
            json.dumps(settings),
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        cwd=feature,
        env=environment,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def _install_sync_runner(feature: Path, sha: str) -> None:
    """Commit a fixture runner so the sandbox starts from a clean worktree."""
    runner = feature / "native_sync_runner.py"
    runner.write_text(
        "from pathlib import Path\n"
        "from parrot.sdd.scripts import worktree_sync\n"
        "try:\n"
        f"    result = worktree_sync.sync(Path({str(feature)!r}), 'dev', cherry_picks=[{sha!r}])\n"
        "except worktree_sync.SyncError as exc:\n"
        "    raise SystemExit(exc.exit_code) from None\n"
        "raise SystemExit(result.exit_code)\n",
        encoding="utf-8",
    )
    _run(feature, "add", runner.name)
    _run(feature, "commit", "-m", "native qualification runner")


def _git_control_paths(feature: Path) -> tuple[Path, Path]:
    """Return the disposable repository's protected common and worktree configs."""
    common = Path(_run(feature, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "config"
    worktree = Path(_run(feature, "rev-parse", "--path-format=absolute", "--git-path", "config.worktree"))
    return common, worktree


def _refs(path: Path) -> str:
    """Snapshot every reference in a disposable repository."""
    return _run(path, "for-each-ref", "--format=%(refname) %(objectname)")


def test_host_merge_from_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new base commit is integrated into a registered feature worktree."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")

    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    result = worktree_sync.sync(feature, "dev")

    assert result.exit_code == worktree_sync.EXIT_OK
    assert result.status == "synced"
    assert (feature / "base.txt").read_text(encoding="utf-8") == "from base\n"
    assert _run(feature, "status", "--porcelain") == ""


def test_conflict_aborts_and_restores_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Conflicting merge restores HEAD, index and tree and reports paths."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (feature / "shared.txt").write_text("feature\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")

    result = worktree_sync.sync(feature, "dev")

    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert result.status == "conflict"
    assert result.before == result.after == before
    assert result.conflicts == ["shared.txt"]
    assert _run(feature, "status", "--porcelain") == ""
    assert (feature / "shared.txt").read_text(encoding="utf-8") == "feature\n"


def test_stale_base_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advisory covers ahead, current, and sandbox cases without changing the tree."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    before = _run(feature, "rev-parse", "HEAD")

    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    summary = worktree_sync.stale_base_summary(feature, "dev")
    assert "1 commit(s) ahead" in summary
    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""

    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    assert worktree_sync.stale_base_summary(feature, "dev").startswith("stale-base check skipped:")


def test_sandbox_cherry_pick_via_gh_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host-configured sandbox applies a gh mailbox patch with its source-SHA trailer."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("from gh\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "gh patch")
    sha = _run(primary, "rev-parse", "HEAD")
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert result.status == "synced"
    assert (feature / "patch.txt").read_text(encoding="utf-8") == "from gh\n"
    assert f"(cherry picked from commit {sha})" in _run(feature, "log", "-1", "--format=%B")
    assert _run(feature, "config", "--get-all", "remote.origin.pushurl") == "no_push"


def test_native_policy_sync_with_protected_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real native sandbox applies patches without writing protected config."""
    origin, primary, feature = _repository(tmp_path)
    sibling = tmp_path / "sibling"
    _run(primary, "worktree", "add", "-b", "sibling", str(sibling), "dev")
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("from native gh\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "native gh patch")
    sha = _run(primary, "rev-parse", "HEAD")
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    _install_sync_runner(feature, sha)

    common_config, worktree_config = _git_control_paths(feature)
    common_before = common_config.read_bytes()
    worktree_before = worktree_config.read_bytes()
    primary_before = (_run(primary, "rev-parse", "HEAD"), _run(primary, "status", "--porcelain"), _refs(primary))
    sibling_before = (_run(sibling, "rev-parse", "HEAD"), _run(sibling, "status", "--porcelain"))
    remote_before = _refs(origin)
    source = Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"
    command = (
        f"printf BAD > {json.dumps(str(common_config))}; echo COMMON_WRITE=$?; "
        f"printf BAD > {json.dumps(str(worktree_config))}; echo WORKTREE_WRITE=$?; "
        f"PYTHONPATH={json.dumps(str(source))} python native_sync_runner.py; echo SYNC_EXIT=$?"
    )

    session = _native_session(feature, command)
    evidence = f"{session.stdout}\n{session.stderr}"

    assert session.returncode == 0, evidence[-2000:]
    assert "COMMON_WRITE=" in evidence and "COMMON_WRITE=0" not in evidence
    assert "WORKTREE_WRITE=" in evidence and "WORKTREE_WRITE=0" not in evidence
    assert "SYNC_EXIT=0" in evidence
    assert (feature / "patch.txt").read_text(encoding="utf-8") == "from native gh\n"
    assert common_config.read_bytes() == common_before
    assert worktree_config.read_bytes() == worktree_before
    assert (
        _run(primary, "rev-parse", "HEAD"),
        _run(primary, "status", "--porcelain"),
        _refs(primary),
    ) == primary_before
    assert (_run(sibling, "rev-parse", "HEAD"), _run(sibling, "status", "--porcelain")) == sibling_before
    assert _refs(origin) == remote_before
    assert _run(feature, "status", "--porcelain") == ""


def test_native_policy_missing_protection_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing host protection is refused without attempted config repair."""
    origin, primary, feature = _repository(tmp_path)
    sibling = tmp_path / "sibling"
    _run(primary, "worktree", "add", "-b", "sibling", str(sibling), "dev")
    (primary / "patch.txt").write_text("must not apply\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "refused native patch")
    sha = _run(primary, "rev-parse", "HEAD")
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    gh_called = feature / "gh-was-called"
    gh_stub = tmp_path / "gh"
    gh_stub.write_text(
        gh_stub.read_text(encoding="utf-8").replace("#!/bin/sh\n", '#!/bin/sh\n: > "$GH_CALLED"\n', 1),
        encoding="utf-8",
    )
    monkeypatch.setenv("GH_CALLED", str(gh_called))
    _install_sync_runner(feature, sha)

    common_config, worktree_config = _git_control_paths(feature)
    assert not worktree_config.exists()
    common_before = common_config.read_bytes()
    feature_before = (_run(feature, "rev-parse", "HEAD"), _run(feature, "status", "--porcelain"), _refs(feature))
    primary_before = (_run(primary, "rev-parse", "HEAD"), _run(primary, "status", "--porcelain"))
    sibling_before = (_run(sibling, "rev-parse", "HEAD"), _run(sibling, "status", "--porcelain"))
    remote_before = _refs(origin)
    source = Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"
    command = f"PYTHONPATH={json.dumps(str(source))} python native_sync_runner.py; echo SYNC_EXIT=$?"

    session = _native_session(feature, command)
    evidence = f"{session.stdout}\n{session.stderr}"

    assert session.returncode == 0, evidence[-2000:]
    assert "SYNC_EXIT=5" in evidence
    assert not gh_called.exists()
    assert not (feature / "patch.txt").exists()
    assert common_config.read_bytes() == common_before
    assert not worktree_config.exists()
    assert (
        _run(feature, "rev-parse", "HEAD"),
        _run(feature, "status", "--porcelain"),
        _refs(feature),
    ) == feature_before
    assert (_run(primary, "rev-parse", "HEAD"), _run(primary, "status", "--porcelain")) == primary_before
    assert (_run(sibling, "rev-parse", "HEAD"), _run(sibling, "status", "--porcelain")) == sibling_before
    assert _refs(origin) == remote_before


def test_sandbox_second_patch_conflict_restores_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A later git-am conflict aborts the single sandbox batch back to its original tree."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "first.txt").write_text("first\n", encoding="utf-8")
    _run(primary, "add", "first.txt")
    _run(primary, "commit", "-m", "first patch")
    first = _run(primary, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "conflicting patch")
    second = _run(primary, "rev-parse", "HEAD")
    (feature / "shared.txt").write_text("feature change\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    _install_gh_stub(
        tmp_path,
        monkeypatch,
        {first: _patch_response(primary, first), second: _patch_response(primary, second)},
    )
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[first, second])

    assert result.status == "conflict"
    assert result.before == result.after == before
    assert not (feature / "first.txt").exists()
    assert _run(feature, "status", "--porcelain") == ""
    assert not (feature / ".git" / "rebase-apply").exists()


def test_sandbox_push_protection_refuses_before_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing host protection refuses sandbox sync before any remote-transport invocation."""
    _origin, _primary, feature = _repository(tmp_path)
    sha = "a" * 40
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha], dry_run=True)

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "host-provisioned" in str(raised.value)


def test_sandbox_late_validation_failure_leaves_tree_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad second response prevents the already downloaded first patch from being applied."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "first.txt").write_text("first\n", encoding="utf-8")
    _run(primary, "add", "first.txt")
    _run(primary, "commit", "-m", "first patch")
    first = _run(primary, "rev-parse", "HEAD")
    second = "b" * 40
    before = _run(feature, "rev-parse", "HEAD")
    first_response = _patch_response(primary, first)
    _install_gh_stub(
        tmp_path,
        monkeypatch,
        {
            first: first_response,
            second: ({"sha": second, "parents": [{}, {}], "commit": {"message": "merge"}}, "bad patch"),
        },
    )
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[first, second])

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert _run(feature, "rev-parse", "HEAD") == before
    assert not (feature / "first.txt").exists()
    assert _run(feature, "status", "--porcelain") == ""


def test_hotfix_slug_candidates_handle_hyphenated_keys(tmp_path: Path) -> None:
    """A hyphenated Jira key must not hide the slug; an unresolved hotfix base is refused, not defaulted to dev."""
    _origin, primary, _feature = _repository(tmp_path)
    hotfix = tmp_path / "hotfix"
    _run(primary, "worktree", "add", "-b", "hotfix-NAV-123-fix-thing", str(hotfix), "dev")

    assert "fix-thing" in worktree_sync._slug_candidates(hotfix)
    with pytest.raises(worktree_sync.SyncError):
        worktree_sync.resolve_base_branch(hotfix, None)
    assert worktree_sync.resolve_base_branch(hotfix, "main") == "main"


def test_ff_only_diverged_is_clean_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-fast-forwardable --ff-only leaves the tree untouched and is not an unverified rollback."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (feature / "local.txt").write_text("local\n", encoding="utf-8")
    _run(feature, "add", "local.txt")
    _run(feature, "commit", "-m", "local")
    (primary / "shared.txt").write_text("changed\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")
    before = _run(feature, "rev-parse", "HEAD")

    result = worktree_sync.sync(feature, "dev", ff_only=True)

    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""
    assert "unchanged" in result.message
    assert "not verified" not in result.message
