"""Deterministic receipt and desktop-hook tests without a desktop or Claude."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid
from types import ModuleType

import pytest

HELPER = Path(__file__).resolve().parents[2] / "src/parrot/sdd/scripts/worker_notification.py"


@pytest.fixture
def notification_module() -> ModuleType:
    """Load this checkout's helper by path, rather than importing parrot."""
    spec = importlib.util.spec_from_file_location("worker_notification", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(command: list[str], cwd: Path) -> str:
    """Run a successful Git fixture command and return stdout."""
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True).stdout


@pytest.fixture
def state(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Create a current completed feature worktree and an existing session cache."""
    worktree = tmp_path / "work tree & <literal>"
    worktree.mkdir()
    _git(["git", "init"], worktree)
    _git(["git", "config", "user.email", "test@example.invalid"], worktree)
    _git(["git", "config", "user.name", "Test"], worktree)
    (worktree / "README").write_text("fixture\n", encoding="utf-8")
    _git(["git", "add", "README"], worktree)
    _git(["git", "commit", "-m", "fixture"], worktree)
    slug = "test & <slug>"
    index = worktree / "sdd/tasks/index"
    index.mkdir(parents=True)
    (index / f"{slug}.json").write_text(json.dumps({"feature_id": "FEAT-793", "tasks": [{"status": "done"}]}))
    cache = tmp_path / str(uuid.uuid4())
    cache.mkdir(mode=0o700)
    environment = {
        "PARROT_SDD_CACHE_DIR": str(cache),
        "PARROT_SDD_NOTIFY_FEATURE": "FEAT-793",
        "PARROT_SDD_NOTIFY_SLUG": slug,
        "PARROT_SDD_NOTIFY_DESKTOP": json.dumps({"PATH": ""}),
    }
    return worktree, cache, environment


def _notifier(tmp_path: Path) -> Path:
    """Create a fake notifier that serializes its argv and exact environment."""
    result = tmp_path / "call.json"
    executable = tmp_path / "notify-send"
    executable.write_text(
        "#!" + sys.executable + "\nimport json, os, sys\n"
        f"open({str(result)!r}, 'w').write(json.dumps([sys.argv[1:], dict(os.environ)]))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return result


def test_completion_and_stop_keep_cli_alive(state: tuple[Path, Path, dict[str, str]], notification_module: ModuleType, tmp_path: Path) -> None:
    """A current explicit receipt sends once under python -S without ending another CLI."""
    worktree, cache, environment = state
    environment["PARROT_SDD_NOTIFY_DESKTOP"] = json.dumps({"PATH": str(tmp_path), "DISPLAY": ":99"})
    command = notification_module.configure_notification(cache, worktree=worktree, env=environment)
    assert command is not None and " -S " in command and str(cache) in command
    assert (cache / "notify-context.json").stat().st_mode & 0o777 == 0o600
    complete = subprocess.run([sys.executable, "-S", str(HELPER), "--complete"], env=environment, text=True, capture_output=True)
    assert complete.returncode == 0 and complete.stdout == ""
    record = _notifier(tmp_path)
    cli = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        hook = subprocess.run(
            [sys.executable, "-S", str(HELPER), "--hook", "--cache", str(cache)],
            input=json.dumps({"hook_event_name": "Stop"}), env={"PATH": "/poisoned", "HOME": "/secret"}, text=True, capture_output=True,
        )
        assert hook.returncode == 0 and hook.stdout == "" and cli.poll() is None, hook.stderr
    finally:
        cli.terminate()
        cli.wait(timeout=2)
    argv, received_environment = json.loads(record.read_text(encoding="utf-8"))
    escaped_worktree = str(worktree).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    assert argv == ["--urgency=normal", "--app-name=AI-Parrot SDD", "SDD work completed: FEAT-793", f"test &amp; &lt;slug&gt;\n{escaped_worktree}\nClaude Code remains open."]
    assert received_environment["DISPLAY"] == ":99"
    assert received_environment["PATH"] == str(tmp_path)
    assert "HOME" not in received_environment
    assert (cache / "notify-complete.json").stat().st_mode & 0o777 == 0o600


def test_overlapping_stop_claims_once(state: tuple[Path, Path, dict[str, str]], notification_module: ModuleType, tmp_path: Path) -> None:
    """Real concurrent hook processes claim delivery once and repeated complete preserves it."""
    worktree, cache, environment = state
    environment["PARROT_SDD_NOTIFY_DESKTOP"] = json.dumps({"PATH": str(tmp_path)})
    assert notification_module.configure_notification(cache, worktree=worktree, env=environment)
    assert notification_module.record_completion(environment)
    record = _notifier(tmp_path)
    command = [sys.executable, "-S", str(HELPER), "--hook", "--cache", str(cache)]
    hooks = [subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) for _ in range(3)]
    for hook in hooks:
        output, _ = hook.communicate(json.dumps({"hook_event_name": "Stop"}), timeout=5)
        assert hook.returncode == 0 and output == ""
    assert record.exists()
    assert notification_module.record_completion(environment)
    assert notification_module._claim_attempt(cache) is False
    assert (cache / "notify-attempted").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("case", ["symlink", "escape", "stale", "oversize", "bad-mode"])
def test_invalid_state_is_nonblocking(state: tuple[Path, Path, dict[str, str]], notification_module: ModuleType, case: str) -> None:
    """Symlinked, escaping, stale, oversized, and invalid-mode state never claims delivery."""
    worktree, cache, environment = state
    assert notification_module.configure_notification(cache, worktree=worktree, env=environment)
    assert notification_module.record_completion(environment)
    if case == "symlink":
        original = cache / "saved-context"
        (cache / "notify-context.json").replace(original)
        (cache / "notify-context.json").symlink_to(original.name)
    elif case == "escape":
        context = json.loads((cache / "notify-context.json").read_text())
        context["index"] = "../../outside.json"
        (cache / "notify-context.json").write_text(json.dumps(context))
        (cache / "notify-context.json").chmod(0o600)
    elif case == "stale":
        _git(["git", "commit", "--allow-empty", "-m", "new head"], worktree)
    elif case == "bad-mode":
        cache.chmod(0o755)
    if case == "oversize":
        result = subprocess.run([sys.executable, "-S", str(HELPER), "--hook", "--cache", str(cache)], input="x" * (64 * 1024 + 1), text=True, capture_output=True)
        assert result.returncode == 0 and result.stdout == ""
    else:
        notification_module.handle_stop({"hook_event_name": "Stop"}, cache=cache)
    assert not (cache / "notify-attempted").exists()
