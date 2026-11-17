"""Real temporary Git integration tests for worktree sync."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from parrot.sdd.scripts import native_claude_sandbox, remove_worktree, worktree_sync

#: The host PATH captured at import, before any test's gh stub narrows PATH to ``<tmp>:/usr/bin``.
_HOST_PATH = os.environ.get("PATH", "")


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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, tuple[dict[str, object], str]],
    compare: dict[str, str] | None = None,
) -> None:
    """Provide deterministic metadata, patch and compare responses through a PATH-local gh stub.

    Every sha gets a ``behind`` compare response (reachable from the base) unless ``compare``
    overrides its status.
    """
    fixtures = tmp_path / "gh-fixtures"
    fixtures.mkdir()
    statuses = compare or {}
    for sha, (metadata, patch) in responses.items():
        (fixtures / f"{sha}.json").write_text(json.dumps(metadata), encoding="utf-8")
        (fixtures / f"{sha}.patch").write_text(patch, encoding="utf-8")
        status = statuses.get(sha, "behind")
        (fixtures / f"compare-{sha}.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    executable = tmp_path / "gh"
    executable.write_text(
        "#!/bin/sh\n"
        'for argument in "$@"; do case "$argument" in repos/*) endpoint=$argument ;; esac; done\n'
        "sha=${endpoint##*/}\n"
        'case "$endpoint" in\n'
        '  */compare/*) cat "$GH_FIXTURES/compare-${sha##*...}.json"; exit ;;\n'
        "esac\n"
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
    # Resolve against the host PATH: _install_gh_stub has already narrowed os.environ["PATH"].
    found = shutil.which("claude", path=_HOST_PATH)
    if found:
        return Path(found)
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


def _refs_except(path: Path, excluded: str) -> str:
    """Snapshot every reference except ``excluded`` (the branch a sync is expected to move)."""
    return "\n".join(line for line in _refs(path).splitlines() if line.split(" ", 1)[0] != excluded)


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
    # The repository's refs are shared by every worktree; the target branch is the one ref the sync
    # must move, so it is excluded from the "nothing else changed" snapshot and checked on its own.
    target_ref = "refs/heads/feat-FEAT-999-sync"
    target_before = _run(feature, "rev-parse", target_ref)
    primary_before = (
        _run(primary, "rev-parse", "HEAD"),
        _run(primary, "status", "--porcelain"),
        _refs_except(primary, target_ref),
    )
    sibling_before = (_run(sibling, "rev-parse", "HEAD"), _run(sibling, "status", "--porcelain"))
    remote_before = _refs(origin)
    source = Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"
    command = (
        f"printf BAD > {json.dumps(str(common_config))}; echo COMMON_WRITE=$?; "
        f"printf BAD > {json.dumps(str(worktree_config))}; echo WORKTREE_WRITE=$?; "
        f"PYTHONPATH={json.dumps(str(source))} {json.dumps(sys.executable)} native_sync_runner.py; echo SYNC_EXIT=$?"
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
        _refs_except(primary, target_ref),
    ) == primary_before
    assert _run(feature, "rev-parse", f"{target_ref}^") == target_before
    assert f"(cherry picked from commit {sha})" in _run(feature, "log", "-1", "--format=%B", target_ref)
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
    command = f"PYTHONPATH={json.dumps(str(source))} {json.dumps(sys.executable)} native_sync_runner.py; echo SYNC_EXIT=$?"

    session = _native_session(feature, command)
    evidence = f"{session.stdout}\n{session.stderr}"

    assert session.returncode == 0, evidence[-2000:]
    assert "SYNC_EXIT=5" in evidence
    assert not gh_called.exists()
    assert not (feature / "patch.txt").exists()
    assert common_config.read_bytes() == common_before
    # The native runtime mounts over denied paths; for an absent config.worktree it leaves an empty
    # placeholder. An empty config sets nothing — what matters is that no key was written.
    assert not worktree_config.exists() or worktree_config.read_bytes() == b""
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


def _sandbox_commit(tmp_path: Path) -> tuple[Path, Path, str]:
    """Return a sandbox-configured feature worktree plus one new commit on the primary clone."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("from gh\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "gh patch")
    return primary, feature, _run(primary, "rev-parse", "HEAD")


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("status", ["ahead", "diverged"])
def test_sandbox_unreachable_cherry_pick_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, dry_run: bool
) -> None:
    """A commit GitHub does not place on the base branch is refused before any worktree change."""
    primary, feature, sha = _sandbox_commit(tmp_path)
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)}, compare={sha: status})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    before = _run(feature, "rev-parse", "HEAD")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha], dry_run=dry_run)

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "not reachable from origin/dev" in str(raised.value)
    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""
    assert not (feature / "patch.txt").exists()


def test_sandbox_invalid_compare_response_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A compare body without a known status fails closed."""
    primary, feature, sha = _sandbox_commit(tmp_path)
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)}, compare={sha: "unknown"})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert not (feature / "patch.txt").exists()


def test_sandbox_identical_compare_syncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit equal to the base tip is reachable and applies."""
    primary, feature, sha = _sandbox_commit(tmp_path)
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)}, compare={sha: "identical"})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert result.status == "synced"
    assert (feature / "patch.txt").read_text(encoding="utf-8") == "from gh\n"


def test_main_missing_git_is_clean_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing git binary yields a JSON refusal with exit 5, never a traceback."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    code = worktree_sync.main([str(tmp_path / "missing"), "--json"])

    body = json.loads(capsys.readouterr().out)
    assert code == worktree_sync.EXIT_TRANSPORT
    assert body["status"] == "refused"
    assert body["exit_code"] == worktree_sync.EXIT_TRANSPORT
    assert "required tool unavailable" in body["message"]


# --- FEAT-814 / TASK-5220: refusal classification and transport hardening -------------------------


def test_ff_only_divergence_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A diverged --ff-only reports status refused with exit 6, not an error."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (feature / "local.txt").write_text("local\n", encoding="utf-8")
    _run(feature, "add", "local.txt")
    _run(feature, "commit", "-m", "local")
    (primary / "shared.txt").write_text("changed\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")

    result = worktree_sync.sync(feature, "dev", ff_only=True)

    assert result.status == "refused"
    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert result.before == result.after
    assert result.message == "fast-forward not possible; worktree unchanged"


def test_untracked_overwrite_merge_is_refused_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge Git refuses because an untracked file is in the way is a refusal, not an unverified rollback."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (primary / "incoming.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "incoming.txt")
    _run(primary, "commit", "-m", "base adds incoming")
    _run(primary, "push")
    before = _run(feature, "rev-parse", "HEAD")
    real_guards = worktree_sync.check_guards
    calls = {"count": 0}

    def racing_guards(wt: Path) -> None:
        # The file appears after the last guard ran: the race the guards cannot close.
        real_guards(wt)
        calls["count"] += 1
        if calls["count"] == 2:
            (wt / "incoming.txt").write_text("local untracked\n", encoding="utf-8")

    monkeypatch.setattr(worktree_sync, "check_guards", racing_guards)

    result = worktree_sync.sync(feature, "dev")

    assert result.status == "refused"
    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert result.before == result.after == before
    assert result.message.startswith("integration refused before starting; worktree unchanged")
    assert "not verified" not in result.message
    assert (feature / "incoming.txt").read_text(encoding="utf-8") == "local untracked\n"


def test_cherry_pick_merge_commit_is_refused_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host cherry-pick of a merge SHA (no -m) is refused without touching the worktree."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    _run(primary, "checkout", "-q", "-b", "side")
    (primary / "side.txt").write_text("side\n", encoding="utf-8")
    _run(primary, "add", "side.txt")
    _run(primary, "commit", "-m", "side")
    _run(primary, "checkout", "-q", "dev")
    (primary / "main.txt").write_text("main\n", encoding="utf-8")
    _run(primary, "add", "main.txt")
    _run(primary, "commit", "-m", "main")
    _run(primary, "merge", "--no-edit", "side")
    _run(primary, "push")
    merge_sha = _run(primary, "rev-parse", "HEAD")
    before = _run(feature, "rev-parse", "HEAD")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[merge_sha])

    assert result.status == "refused"
    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert result.before == result.after == before
    assert result.message.startswith("integration refused before starting; worktree unchanged")
    assert _run(feature, "status", "--porcelain") == ""


def test_rollback_status_error_is_reported_as_exit_6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_rollback never raises: a status failure after the abort is an unverified rollback."""
    _origin, _primary, feature = _repository(tmp_path)
    before = _run(feature, "rev-parse", "HEAD")

    def broken_status(_wt: Path) -> list[str]:
        raise worktree_sync.SyncError(worktree_sync.EXIT_TARGET, "cannot inspect target worktree: boom")

    monkeypatch.setattr(worktree_sync, "_status", broken_status)

    restored, conflicts, detail = worktree_sync._rollback(feature, before, "merge")

    assert restored is False
    assert conflicts == []
    assert "boom" in detail


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("diff --git a/x b/x\n", True),
        ("Index: x\n", True),
        ("--- a/x\n", True),
        ("---\n", True),
        ("---   \n", True),
        ("------\n", False),
        ("---x\n", False),
        ("---  two-spaces\n", False),
        ("plain body\n", False),
    ],
)
def test_patch_break_matches_mailinfo(line: str, expected: bool) -> None:
    """Patch-break detection follows git mailinfo's patchbreak() rules."""
    assert worktree_sync._is_patch_break(line) is expected


def test_trailer_survives_pasted_diff_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit body containing a pasted diff header keeps its cherry-pick trailer after git am."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("pasted\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    # mailinfo ends the message at "Index: " (a pasted diff header); the old "---"-only heuristic put the
    # trailer after that cut, where git am discarded it.
    message = "pasted diff body\n\nWhy:\nIndex: notes\nmore text\n"
    _run(primary, "commit", "-m", message)
    sha = _run(primary, "rev-parse", "HEAD")
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert result.status == "synced"
    assert f"(cherry picked from commit {sha})" in _run(feature, "log", "-1", "--format=%B")


def test_fetch_timeout_is_transport_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stalled fetch is bounded by PARROT_SDD_SYNC_TIMEOUT and becomes an exit-5 refusal."""
    _origin, _primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    monkeypatch.setenv(worktree_sync.TIMEOUT_ENV, "7")
    real_git = worktree_sync._git
    seen: dict[str, object] = {}

    def stalled_git(wt: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("fetch",):
            seen["timeout"] = timeout
            raise subprocess.TimeoutExpired(["git", *args], timeout or 0)
        return real_git(wt, *args, timeout=timeout)

    monkeypatch.setattr(worktree_sync, "_git", stalled_git)

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", dry_run=True)

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "timed out after 7s" in str(raised.value)
    assert seen["timeout"] == 7
    assert worktree_sync.stale_base_summary(feature, "dev").startswith("stale-base check skipped:")


@pytest.mark.parametrize(("raw", "expected"), [("", 120), ("30", 30), ("0", 120), ("-5", 120), ("soon", 120)])
def test_network_timeout_parsing(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    """Only a positive integer overrides the 120-second default."""
    monkeypatch.setenv(worktree_sync.TIMEOUT_ENV, raw)
    assert worktree_sync.network_timeout() == expected


def test_git_disables_terminal_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Git call runs with GIT_TERMINAL_PROMPT=0 so a credential prompt can never block."""
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(worktree_sync.subprocess, "run", fake_run)

    worktree_sync._git(tmp_path, "status")

    environment = captured["env"]
    assert isinstance(environment, dict) and environment["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["timeout"] is None


def test_detached_head_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutating sync of a detached HEAD is refused with exit 2; a dry run still reports."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    _run(feature, "checkout", "-q", "--detach")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev")

    assert raised.value.exit_code == worktree_sync.EXIT_TARGET
    assert "detached HEAD" in str(raised.value)
    assert not (feature / "base.txt").exists()
    assert worktree_sync.sync(feature, "dev", dry_run=True).commits


def test_cli_refusal_goes_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """In human mode a refusal message is printed on stderr, leaving stdout empty."""
    code = worktree_sync.main([str(tmp_path / "missing")])

    captured = capsys.readouterr()
    assert code == worktree_sync.EXIT_TARGET
    assert captured.out == ""
    assert "target must resolve to one worktree" in captured.err


def test_short_sha_refused_before_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A too-short sandbox --cherry-pick value is refused (exit 2) before gh is invoked."""
    _origin, _primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    gh_called = tmp_path / "gh-was-called"
    gh = tmp_path / "gh"
    gh.write_text(f'#!/bin/sh\n: > "{gh_called}"\n', encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=["abc"])

    assert raised.value.exit_code == worktree_sync.EXIT_TARGET
    assert not gh_called.exists()


# --- FEAT-814 / TASK-5229: sandbox dirty guard counts tracked changes only ---------------------------


def test_sandbox_guard_ignores_untracked_placeholders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native-runtime mount placeholders (untracked) do not block a sandboxed patch sync."""
    primary, feature, sha = _sandbox_commit(tmp_path)
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    (feature / ".bashrc").write_text("", encoding="utf-8")
    (feature / ".claude" / "agents").mkdir(parents=True)
    (feature / ".claude" / "agents" / ".keep").write_text("", encoding="utf-8")

    result = worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert result.status == "synced"
    assert (feature / "patch.txt").read_text(encoding="utf-8") == "from gh\n"


def test_sandbox_guard_still_refuses_tracked_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tracked modification still makes a sandboxed sync refuse with exit 3."""
    primary, feature, sha = _sandbox_commit(tmp_path)
    _install_gh_stub(tmp_path, monkeypatch, {sha: _patch_response(primary, sha)})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    (feature / "shared.txt").write_text("edited\n", encoding="utf-8")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert raised.value.exit_code == worktree_sync.EXIT_DIRTY
    assert not (feature / "patch.txt").exists()


def test_host_guard_still_refuses_untracked_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On the host an untracked file still counts as dirty (exit 3)."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    (feature / "scratch.txt").write_text("operator work\n", encoding="utf-8")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev")

    assert raised.value.exit_code == worktree_sync.EXIT_DIRTY
    assert not (feature / "base.txt").exists()


# --- FEAT-820 / TASK-5235: target and base-branch resolution ---------------------------------------


def _as_primary(monkeypatch: pytest.MonkeyPatch, primary: Path) -> None:
    """Point worktree discovery at a disposable clone instead of the real repository.

    ``discover()`` runs ``git worktree list`` with ``cwd=_root()`` and scans
    ``_root()/.parrot/worktrees`` for orphans, and ``_root()`` memoises into the module
    global ``remove_worktree._ROOT``. Both are redirected so ``resolve_target`` can only
    ever see ``primary``'s own worktrees.
    """
    monkeypatch.setattr(remove_worktree, "_ROOT", primary)
    monkeypatch.chdir(primary)


def test_resolve_target_feat_id_and_ambiguity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One match resolves; an ambiguous substring and the primary checkout both exit 2."""
    _origin, primary, feature = _repository(tmp_path)
    second = tmp_path / "second"
    _run(primary, "worktree", "add", "-b", "feat-FEAT-998-sync-extra", str(second), "dev")
    _as_primary(monkeypatch, primary)

    assert worktree_sync.resolve_target("feat-FEAT-999-sync") == feature.resolve()

    with pytest.raises(worktree_sync.SyncError) as ambiguous:
        worktree_sync.resolve_target("sync")

    assert ambiguous.value.exit_code == worktree_sync.EXIT_TARGET
    assert "target must resolve to one worktree" in str(ambiguous.value)
    assert str(feature) in str(ambiguous.value)
    assert str(second) in str(ambiguous.value)

    with pytest.raises(worktree_sync.SyncError) as primary_refused:
        worktree_sync.resolve_target("dev")

    assert primary_refused.value.exit_code == worktree_sync.EXIT_TARGET
    assert "registered non-primary linked worktree" in str(primary_refused.value)


def test_orphan_and_mismatched_git_root_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An orphan directory and a Git-top-level mismatch exit 2 with the primary untouched."""
    _origin, primary, _feature = _repository(tmp_path)
    orphan = primary / ".parrot" / "worktrees" / "orphan-dir"
    orphan.mkdir(parents=True)
    # A registered worktree that is really a subdirectory of an unrelated repository: its own
    # .git link is gone, so `rev-parse --show-toplevel` resolves to `outer`, not to the
    # registered path.
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q", str(outer)], check=True, capture_output=True, text=True)
    foreign = outer / "foreign"
    _run(primary, "worktree", "add", "-b", "feat-FEAT-997-foreign", str(foreign), "dev")
    (foreign / ".git").unlink()
    _as_primary(monkeypatch, primary)
    before = (
        _run(primary, "rev-parse", "HEAD"),
        _run(primary, "status", "--porcelain"),
        _refs(primary),
        _run(primary, "config", "--list"),
    )

    with pytest.raises(worktree_sync.SyncError) as orphan_refused:
        worktree_sync.resolve_target("orphan-dir")

    assert orphan_refused.value.exit_code == worktree_sync.EXIT_TARGET
    assert "registered non-primary linked worktree" in str(orphan_refused.value)

    with pytest.raises(worktree_sync.SyncError) as mismatched:
        worktree_sync.resolve_target("feat-FEAT-997-foreign")

    assert mismatched.value.exit_code == worktree_sync.EXIT_TARGET
    assert "Git top-level does not match" in str(mismatched.value)

    assert (
        _run(primary, "rev-parse", "HEAD"),
        _run(primary, "status", "--porcelain"),
        _refs(primary),
        _run(primary, "config", "--list"),
    ) == before


def test_base_branch_from_index_and_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-spec index, a brief's frontmatter and the --base override resolve in precedence order."""
    _origin, primary, feature = _repository(tmp_path)
    index = feature / "sdd" / "tasks" / "index"
    index.mkdir(parents=True)
    (index / "sync.json").write_text(
        json.dumps({"feature": "sync", "base_branch": "staging", "tasks": []}), encoding="utf-8"
    )

    assert worktree_sync.resolve_base_branch(feature, None) == "staging"
    assert worktree_sync.resolve_base_branch(feature, "dev") == "dev"

    brief_worktree = tmp_path / "widget"
    _run(primary, "worktree", "add", "-b", "fix-ABC-1-widget", str(brief_worktree), "dev")
    briefs = brief_worktree / "sdd" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "widget.brief.md").write_text("---\ntype: hotfix\nbase_branch: main\n---\n\n# Brief\n", encoding="utf-8")

    assert worktree_sync._slug_candidates(brief_worktree) == ["1-widget", "widget"]
    assert worktree_sync.resolve_base_branch(brief_worktree, None) == "main"


# --- FEAT-820 / TASK-5236: live-process guards, never-pushes, up-to-date advisory ------------------


def _await_cwd(pid: int, expected: Path, timeout: float = 10.0) -> None:
    """Block until ``pid``'s cwd resolves to ``expected``, failing the test on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if Path(f"/proc/{pid}/cwd").resolve() == expected.resolve():
                return
        except OSError:
            pass
        time.sleep(0.02)
    pytest.fail(f"pid {pid} never reported a cwd of {expected}")


def _advance_base(primary: Path, name: str) -> str:
    """Commit a new file on the base branch, publish it and return its sha."""
    (primary / name).write_text(f"{name}\n", encoding="utf-8")
    _run(primary, "add", name)
    _run(primary, "commit", "-m", f"base {name}")
    _run(primary, "push")
    return _run(primary, "rev-parse", "HEAD")


def test_live_process_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A foreign process whose cwd is inside the worktree refuses the sync with exit 4."""
    _origin, primary, feature = _repository(tmp_path)
    _advance_base(primary, "base.txt")
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    before = _run(feature, "rev-parse", "HEAD")

    child = subprocess.Popen(["sleep", "30"], cwd=feature)
    try:
        _await_cwd(child.pid, feature)
        with pytest.raises(worktree_sync.SyncError) as raised:
            worktree_sync.sync(feature, "dev")

        assert raised.value.exit_code == worktree_sync.EXIT_LIVE
        assert f"pid {child.pid}" in str(raised.value)
        assert "live process(es) inside target worktree" in str(raised.value)
    finally:
        child.terminate()
        child.wait(timeout=10)

    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""
    assert not (feature / "base.txt").exists()


def test_own_ancestry_not_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller running inside the worktree is excluded from the live-process guard and syncs."""
    _origin, primary, feature = _repository(tmp_path)
    _advance_base(primary, "base.txt")
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    monkeypatch.chdir(feature)

    assert os.getpid() in worktree_sync.own_ancestry()
    assert remove_worktree.live_processes_in(feature, exclude_pids=worktree_sync.own_ancestry()) == []
    worktree_sync.check_guards(feature)

    result = worktree_sync.sync(feature, "dev")

    assert result.status == "synced"
    assert result.exit_code == worktree_sync.EXIT_OK
    assert (feature / "base.txt").read_text(encoding="utf-8") == "base.txt\n"


def test_never_pushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bare origin's refs are byte-identical after every host mode and after a sandbox patch."""
    origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)

    _advance_base(primary, "merged.txt")
    remote_before = _refs(origin)
    assert worktree_sync.sync(feature, "dev").status == "synced"
    assert _refs(origin) == remote_before

    _advance_base(primary, "forwarded.txt")
    remote_before = _refs(origin)
    assert worktree_sync.sync(feature, "dev", ff_only=True).status == "synced"
    assert _refs(origin) == remote_before

    picked = _advance_base(primary, "picked.txt")
    remote_before = _refs(origin)
    assert worktree_sync.sync(feature, "dev", cherry_picks=[picked]).status == "synced"
    assert _refs(origin) == remote_before

    remote_before = _refs(origin)
    assert worktree_sync.sync(feature, "dev", dry_run=True).dry_run is True
    assert _refs(origin) == remote_before

    # Sandbox leg LAST: _install_gh_stub narrows PATH for the rest of the test, and
    # _configure_sandbox rewrites the shared origin URL.
    patched = _advance_base(primary, "patched.txt")
    remote_before = _refs(origin)
    response = _patch_response(primary, patched)
    _configure_sandbox(feature)
    _install_gh_stub(tmp_path, monkeypatch, {patched: response})
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    assert worktree_sync.sync(feature, "dev", cherry_picks=[patched]).status == "synced"
    assert _refs(origin) == remote_before


def test_stale_base_summary_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no new base commits the advisory reads 'up to date' and changes nothing."""
    _origin, _primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    before = _run(feature, "rev-parse", "HEAD")

    summary = worktree_sync.stale_base_summary(feature, "dev")

    assert summary == "base dev: up to date"
    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""


# --- FEAT-820 / TASK-5237: push-protection truth table and gh failure -----------------------------


def _install_failing_gh_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """Put a gh on PATH that writes ``message`` to stderr and exits 1 for every invocation."""
    executable = tmp_path / "gh"
    executable.write_text(f"#!/bin/sh\necho {message!r} >&2\nexit 1\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}")


def _apply_protection_variant(feature: Path, variant: str) -> None:
    """Configure one incomplete push-protection shape using only git config writes."""
    _run(feature, "remote", "set-url", "origin", "git@github.com:example/sync.git")
    if variant == "missing-extension":
        # Looks protected — a no_push URL is present — but the worktree-config extension is off.
        _run(feature, "config", "remote.origin.pushurl", "no_push")
        return
    _run(feature, "config", "extensions.worktreeConfig", "true")
    if variant == "missing-pushurl":
        return
    _run(feature, "config", "--worktree", "remote.origin.pushurl", "no_push")
    _run(feature, "config", "--worktree", "--add", "remote.origin.pushurl", "git@github.com:example/sync.git")


def test_push_protection_ok_truth_table(tmp_path: Path) -> None:
    """Protection holds only for extensions.worktreeConfig=true plus exactly one no_push URL."""
    _origin, _primary, feature = _repository(tmp_path)

    assert worktree_sync.push_protection_ok(feature) is False

    _run(feature, "config", "remote.origin.pushurl", "no_push")
    assert worktree_sync.push_protection_ok(feature) is False

    _run(feature, "config", "--unset-all", "remote.origin.pushurl")
    _run(feature, "config", "extensions.worktreeConfig", "true")
    assert worktree_sync.push_protection_ok(feature) is False

    _run(feature, "config", "--worktree", "remote.origin.pushurl", "no_push")
    assert worktree_sync.push_protection_ok(feature) is True

    _run(feature, "config", "--worktree", "--add", "remote.origin.pushurl", "git@github.com:example/sync.git")
    assert worktree_sync.push_protection_ok(feature) is False


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("variant", ["missing-extension", "missing-pushurl", "extra-pushurl"])
def test_sandbox_push_protection_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, dry_run: bool
) -> None:
    """Every incomplete protection shape exits 5 before gh, dry-run included, writing no config."""
    _origin, _primary, feature = _repository(tmp_path)
    _apply_protection_variant(feature, variant)
    assert worktree_sync.push_protection_ok(feature) is False

    common, worktree_config = _git_control_paths(feature)
    before = tuple(path.read_bytes() if path.is_file() else None for path in (common, worktree_config))
    _install_failing_gh_stub(tmp_path, monkeypatch, "gh must not be reached")
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=["a" * 40], dry_run=dry_run)

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "host-provisioned" in str(raised.value)
    assert "gh must not be reached" not in str(raised.value)
    assert tuple(path.read_bytes() if path.is_file() else None for path in (common, worktree_config)) == before


def test_sandbox_gh_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gh stub exiting 1 becomes a transport refusal carrying its stderr and the host hint."""
    _origin, primary, feature = _repository(tmp_path)
    _configure_sandbox(feature)
    (primary / "patch.txt").write_text("from gh\n", encoding="utf-8")
    _run(primary, "add", "patch.txt")
    _run(primary, "commit", "-m", "gh patch")
    sha = _run(primary, "rev-parse", "HEAD")
    before = (_run(feature, "rev-parse", "HEAD"), _run(feature, "status", "--porcelain"), _refs(feature))
    _install_failing_gh_stub(tmp_path, monkeypatch, "gh: HTTP 403")
    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")

    with pytest.raises(worktree_sync.SyncError) as raised:
        worktree_sync.sync(feature, "dev", cherry_picks=[sha])

    assert raised.value.exit_code == worktree_sync.EXIT_TRANSPORT
    assert "403" in str(raised.value)
    assert "run 'parrot sdd worktree sync-base <target>' from the host" in str(raised.value)
    assert (_run(feature, "rev-parse", "HEAD"), _run(feature, "status", "--porcelain"), _refs(feature)) == before
    assert not (feature / "patch.txt").exists()


# --- FEAT-820 / TASK-5238: unrecovered abort and CLI exit-code mapping ----------------------------


def _conflicting_base(primary: Path, feature: Path) -> str:
    """Give ``feature`` and the base branch incompatible edits to shared.txt; return feature's HEAD."""
    (feature / "shared.txt").write_text("feature\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")
    return before


def test_abort_failure_is_not_reported_as_restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing merge --abort yields status 'error' with recovery guidance, never 'conflict'."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    before = _conflicting_base(primary, feature)

    original_git = worktree_sync._git
    calls: list[tuple[str, ...]] = []

    def recording_git(wt: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ("merge", "--abort"):
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="abort refused")
        return original_git(wt, *args, timeout=timeout)

    monkeypatch.setattr(worktree_sync, "_git", recording_git)

    result = worktree_sync.sync(feature, "dev")

    assert result.status == "error"
    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert "automatic rollback was not verified" in result.message
    assert "abort refused" in result.message
    assert result.before == before
    assert ("merge", "--abort") in calls
    assert not any(args and args[0] == "reset" for args in calls)


def test_main_exit_code_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() maps synced to 0 and conflict to 6, in human and --json form, honouring --dry-run."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    _as_primary(monkeypatch, primary)
    _advance_base(primary, "base.txt")

    dry = worktree_sync.main(["feat-FEAT-999-sync", "--base", "dev", "--dry-run", "--json"])
    body = json.loads(capsys.readouterr().out)

    assert dry == worktree_sync.EXIT_OK
    assert body["dry_run"] is True
    assert body["commits"]
    assert not (feature / "base.txt").exists()

    code = worktree_sync.main(["feat-FEAT-999-sync", "--base", "dev"])
    captured = capsys.readouterr()

    assert code == worktree_sync.EXIT_OK
    assert "synchronized" in captured.out
    assert captured.err == ""
    assert (feature / "base.txt").read_text(encoding="utf-8") == "base.txt\n"

    _conflicting_base(primary, feature)

    conflicted = worktree_sync.main(["feat-FEAT-999-sync", "--base", "dev", "--json"])
    conflict_body = json.loads(capsys.readouterr().out)

    assert conflicted == worktree_sync.EXIT_CONFLICT
    assert conflict_body["status"] == "conflict"
    assert conflict_body["exit_code"] == worktree_sync.EXIT_CONFLICT
    assert conflict_body["conflicts"] == ["shared.txt"]
