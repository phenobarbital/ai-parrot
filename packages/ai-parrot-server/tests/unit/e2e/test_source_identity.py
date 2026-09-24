"""Unit tests for ``parrot.e2e.evidence.capture_identity`` (TASK-3522, M2).

Every test builds a synthetic Git checkout under ``tmp_path`` (never the real
repository) and drives ``capture_identity`` through *real* ``git`` subprocess
calls — the SUT itself only ever talks to Git via
``asyncio.create_subprocess_exec``, so faking that boundary would not exercise
the async-subprocess contract the spec requires. Only the process-external
inputs a test cares about (environment variables) are faked, via
``monkeypatch``, isolated for every test in this file so a developer's real
shell (``GOOGLE_API_KEY``, opt-in flags) can never leak into an assertion.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from parrot.e2e.errors import E2EConfigError
from parrot.e2e.evidence import capture_identity
from parrot.e2e.models import E2EPlan

_SPEC_RELATIVE = "sdd/specs/agentic-e2e-testing.spec.md"

# ---------------------------------------------------------------------------
# Isolation: never let the invoking shell's own env leak into a fingerprint.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_e2e_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every opt-in/credential variable this module reads, for every test."""
    for name in ("PARROT_TEST_E2E", "PARROT_TEST_REAL_LLM", "E2E_MODEL", "E2E_MAX_LLM_CALLS", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Synthetic Git checkout helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _run(["git", "init"], cwd=root)
    _run(["git", "config", "user.email", "e2e-test@example.com"], cwd=root)
    _run(["git", "config", "user.name", "E2E Test"], cwd=root)


def _commit_all(root: Path, message: str = "commit") -> None:
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-m", message], cwd=root)


def _git_head(root: Path) -> str:
    """Read the checkout's current commit SHA via a synchronous ``git`` call.

    Kept as a plain (non-async) helper so this test-only comparison never
    runs a blocking subprocess from inside an ``async def test_*`` body.
    """
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    """A minimal, real Git checkout with one committed source file and spec."""
    root = tmp_path / "worktree"
    root.mkdir()
    _init_repo(root)
    (root / "sdd" / "specs").mkdir(parents=True)
    (root / "sdd" / "specs" / "agentic-e2e-testing.spec.md").write_text("# Spec\n\nRationale.\n", encoding="utf-8")
    (root / "src_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(root)
    return root


def _plan(**overrides: object) -> E2EPlan:
    data: dict[str, object] = {
        "feature_id": "FEAT-581",
        "spec_path": _SPEC_RELATIVE,
        "policy": "optional",
        "targets": {},
        "scenarios": [],
    }
    data.update(overrides)
    return E2EPlan.model_validate(data)


# ---------------------------------------------------------------------------
# Success and determinism
# ---------------------------------------------------------------------------


async def test_capture_identity_returns_valid_source_identity(git_worktree: Path) -> None:
    plan = _plan()

    identity = await capture_identity(plan, worktree=git_worktree)

    assert identity.commit == _git_head(git_worktree)
    assert identity.worktree == str(git_worktree.resolve())
    for digest in (identity.manifest_sha256, identity.spec_sha256, identity.plan_sha256, identity.environment_sha256):
        assert len(digest) == 64
        int(digest, 16)  # raises ValueError if not hex


async def test_capture_identity_is_deterministic_for_unchanged_source(git_worktree: Path) -> None:
    plan = _plan()

    first = await capture_identity(plan, worktree=git_worktree)
    second = await capture_identity(plan, worktree=git_worktree)

    assert first == second


async def test_capture_identity_accepts_relative_worktree_path(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(git_worktree.parent)
    plan = _plan()

    identity = await capture_identity(plan, worktree=Path(git_worktree.name))

    assert identity.worktree == str(git_worktree.resolve())


# ---------------------------------------------------------------------------
# Source manifest mutation is detected
# ---------------------------------------------------------------------------


async def test_capture_identity_changes_when_tracked_source_content_changes(git_worktree: Path) -> None:
    plan = _plan()
    before = await capture_identity(plan, worktree=git_worktree)

    (git_worktree / "src_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 != after.manifest_sha256
    # Only the manifest moved; spec/plan/environment identity are untouched.
    assert before.spec_sha256 == after.spec_sha256
    assert before.plan_sha256 == after.plan_sha256
    assert before.environment_sha256 == after.environment_sha256


async def test_capture_identity_changes_when_untracked_nonignored_file_is_added(git_worktree: Path) -> None:
    plan = _plan()
    before = await capture_identity(plan, worktree=git_worktree)

    (git_worktree / "new_untracked.py").write_text("NEW = True\n", encoding="utf-8")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 != after.manifest_sha256


async def test_capture_identity_changes_when_tracked_file_mode_changes(git_worktree: Path) -> None:
    plan = _plan()
    target = git_worktree / "src_module.py"
    before = await capture_identity(plan, worktree=git_worktree)

    target.chmod(target.stat().st_mode | 0o111)
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 != after.manifest_sha256


async def test_capture_identity_records_raw_symlink_target_not_dereferenced_content(git_worktree: Path) -> None:
    plan = _plan()
    link = git_worktree / "link.txt"

    link.symlink_to("target-a")
    first = await capture_identity(plan, worktree=git_worktree)

    link.unlink()
    link.symlink_to("target-b")
    second = await capture_identity(plan, worktree=git_worktree)

    # Neither "target-a" nor "target-b" exists on disk: if the manifest
    # dereferenced the symlink, both hashes would fail identically instead
    # of differing on the raw target string.
    assert first.manifest_sha256 != second.manifest_sha256


# ---------------------------------------------------------------------------
# Manifest exclusions (spec §2: only declared generated artifacts/caches and
# SDD task/ledger bookkeeping are excluded)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    [
        "artifacts/logs/e2e/run-1.log",
        "sdd/tasks/active/TASK-9999-bookkeeping.md",
        "sdd/ledger/counter.json",
        "pkg/__pycache__/module.cpython-311.pyc",
        ".pytest_cache/README.md",
        "compiled.pyc",
    ],
)
async def test_capture_identity_excludes_declared_bookkeeping_and_caches(
    git_worktree: Path, relative_path: str
) -> None:
    plan = _plan()
    before = await capture_identity(plan, worktree=git_worktree)

    excluded_path = git_worktree / relative_path
    excluded_path.parent.mkdir(parents=True, exist_ok=True)
    excluded_path.write_text("bookkeeping\n", encoding="utf-8")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 == after.manifest_sha256


async def test_capture_identity_excludes_this_features_run_evidence_directory(git_worktree: Path) -> None:
    plan = _plan(feature_id="FEAT-581")
    before = await capture_identity(plan, worktree=git_worktree)

    evidence_path = git_worktree / "sdd" / "state" / "FEAT-581" / "e2e" / "runs" / "run-1" / "e2e-verdict.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text("{}\n", encoding="utf-8")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 == after.manifest_sha256


async def test_capture_identity_excludes_gitignored_untracked_files(git_worktree: Path) -> None:
    (git_worktree / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    _commit_all(git_worktree, "add gitignore")
    plan = _plan()
    before = await capture_identity(plan, worktree=git_worktree)

    ignored_path = git_worktree / "ignored" / "scratch.txt"
    ignored_path.parent.mkdir(parents=True, exist_ok=True)
    ignored_path.write_text("scratch\n", encoding="utf-8")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 == after.manifest_sha256


async def test_capture_identity_includes_uv_lock_templates_and_config(git_worktree: Path) -> None:
    """Scope: 'include spec, plan, source, templates, uv.lock and relevant config'."""
    (git_worktree / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (git_worktree / "templates").mkdir()
    (git_worktree / "templates" / "example.md").write_text("template\n", encoding="utf-8")
    (git_worktree / "config.toml").write_text("[tool]\n", encoding="utf-8")
    _commit_all(git_worktree, "add non-excluded categories")
    plan = _plan()
    before = await capture_identity(plan, worktree=git_worktree)

    (git_worktree / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    (git_worktree / "templates" / "example.md").write_text("template changed\n", encoding="utf-8")
    (git_worktree / "config.toml").write_text("[tool]\nkey = 1\n", encoding="utf-8")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.manifest_sha256 != after.manifest_sha256
    # uv.lock content is also folded into the environment fingerprint.
    assert before.environment_sha256 != after.environment_sha256


# ---------------------------------------------------------------------------
# Plan and model identity
# ---------------------------------------------------------------------------


async def test_capture_identity_changes_when_plan_content_changes(git_worktree: Path) -> None:
    before = await capture_identity(_plan(policy="optional"), worktree=git_worktree)
    after = await capture_identity(_plan(policy="none"), worktree=git_worktree)

    assert before.plan_sha256 != after.plan_sha256
    assert before.manifest_sha256 == after.manifest_sha256


async def test_capture_identity_changes_when_model_changes(git_worktree: Path) -> None:
    from parrot.e2e.models import LiveBudget

    before_plan = _plan(budget=LiveBudget(model="google:gemini-2.5-flash-lite"))
    after_plan = _plan(budget=LiveBudget(model="google:gemini-2.5-pro"))

    before = await capture_identity(before_plan, worktree=git_worktree)
    after = await capture_identity(after_plan, worktree=git_worktree)

    # The model is folded into both the frozen plan and the environment
    # fingerprint (spec §2: "Environment fingerprint includes ... selected
    # model"), so both change; the source manifest itself does not.
    assert before.plan_sha256 != after.plan_sha256
    assert before.environment_sha256 != after.environment_sha256
    assert before.manifest_sha256 == after.manifest_sha256


async def test_capture_identity_opt_in_env_vars_affect_environment_fingerprint(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    before = await capture_identity(plan, worktree=git_worktree)

    monkeypatch.setenv("PARROT_TEST_E2E", "1")
    monkeypatch.setenv("PARROT_TEST_REAL_LLM", "1")
    after = await capture_identity(plan, worktree=git_worktree)

    assert before.environment_sha256 != after.environment_sha256
    assert before.manifest_sha256 == after.manifest_sha256


async def test_capture_identity_never_persists_credential_value(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The credential's value must never leak into the identity object."""
    monkeypatch.setenv("GOOGLE_API_KEY", "super-secret-value-should-not-leak")
    plan = _plan()

    identity = await capture_identity(plan, worktree=git_worktree)

    dumped = identity.model_dump_json()
    assert "super-secret-value-should-not-leak" not in dumped


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


async def test_capture_identity_raises_config_error_for_missing_worktree(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    plan = _plan()

    with pytest.raises(E2EConfigError) as excinfo:
        await capture_identity(plan, worktree=missing)

    assert excinfo.value.reason_code == "worktree_missing"
    assert excinfo.value.exit_code == 2


async def test_capture_identity_raises_config_error_when_not_a_git_repository(tmp_path: Path) -> None:
    root = tmp_path / "not-a-repo"
    root.mkdir()
    (root / "sdd" / "specs").mkdir(parents=True)
    (root / _SPEC_RELATIVE).write_text("# Spec\n", encoding="utf-8")
    plan = _plan()

    with pytest.raises(E2EConfigError) as excinfo:
        await capture_identity(plan, worktree=root)

    assert excinfo.value.reason_code == "git_command_failed"


async def test_capture_identity_raises_config_error_when_git_binary_missing(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise_missing_binary(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git executable not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_missing_binary)
    plan = _plan()

    with pytest.raises(E2EConfigError) as excinfo:
        await capture_identity(plan, worktree=git_worktree)

    assert excinfo.value.reason_code == "git_unavailable"


async def test_capture_identity_raises_config_error_for_missing_spec_path(git_worktree: Path) -> None:
    plan = _plan(spec_path="sdd/specs/does-not-exist.spec.md")

    with pytest.raises(E2EConfigError) as excinfo:
        await capture_identity(plan, worktree=git_worktree)

    assert excinfo.value.reason_code == "spec_path_missing"


async def test_capture_identity_raises_config_error_for_spec_path_escaping_via_symlink(
    git_worktree: Path, tmp_path: Path
) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    real_spec = outside_dir / "real.spec.md"
    real_spec.write_text("# Outside spec\n", encoding="utf-8")

    link_spec = git_worktree / "sdd" / "specs" / "linked.spec.md"
    link_spec.symlink_to(real_spec)
    _commit_all(git_worktree, "add escaping symlink")

    plan = _plan(spec_path="sdd/specs/linked.spec.md")

    with pytest.raises(E2EConfigError) as excinfo:
        await capture_identity(plan, worktree=git_worktree)

    assert excinfo.value.reason_code == "path_escape"
