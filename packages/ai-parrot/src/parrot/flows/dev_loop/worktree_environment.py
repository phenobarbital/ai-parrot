"""Protect shared Python environments when executing SDD worktree commands.

This file deliberately uses only the standard library and can run directly as
a Claude hook, even when importing the rest of Parrot is unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any, Sequence

POLICY_MESSAGE = (
    "Worktree agents may read and execute the shared environment, but must not mutate it. "
    "Use existing tools directly or uv run --no-sync. For dependency changes, use a real "
    "task-local virtual environment with an explicit --python target, or ask the main-checkout "
    "operator for a controlled installation. Never repair shared .pth files from a task."
)


def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
    """Find the checkout root and common Git directory, including pool worktrees."""
    cwd = cwd.resolve(strict=True)
    for root in (cwd, *cwd.parents):
        marker = root / ".git"
        if marker.is_dir():
            return root, marker.resolve()
        if marker.is_file():
            content = marker.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir: "):
                raise ValueError(f"Invalid Git worktree marker: {marker}")
            git_dir = (root / content.removeprefix("gitdir: ")).resolve(strict=True)
            common = git_dir / "commondir"
            if common.is_file():
                git_dir = (git_dir / common.read_text(encoding="utf-8").strip()).resolve(strict=True)
            return root, git_dir
    return cwd, None


def shared_environments(cwd: Path) -> tuple[Path, ...]:
    """Resolve environment symlinks so aliases receive the same protection."""
    root, git_dir = repository_paths(cwd)
    candidates = [Path(sys.prefix), root / ".venv"]
    if git_dir is not None:
        candidates.append(git_dir.parent / ".venv")
    for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        if value := os.environ.get(name):
            candidates.append(root / value)
    environments = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if not (resolved / "pyvenv.cfg").is_file():
            continue
        # A real environment inside a linked task checkout is task-owned.
        is_task_local = git_dir is not None and git_dir.parent != root and resolved.is_relative_to(root)
        if not is_task_local:
            environments.add(resolved)
    return tuple(sorted(environments))


def validate_write_path(cwd: Path, path: Path) -> None:
    """Reject direct file-tool writes through aliases into shared environments."""
    target = path.resolve()
    if any(target == env or target.is_relative_to(env) for env in shared_environments(cwd)):
        raise ValueError(POLICY_MESSAGE)


def command_policy_error(cwd: Path, argv: Sequence[str]) -> str | None:
    """Give early feedback for package operations; filesystem mounts enforce safety."""
    if not argv:
        return "A command is required."
    command = Path(argv[0]).name
    if command != "uv":
        return None
    args = list(argv[1:])
    if args[:1] in (["--version"], ["version"], ["help"]):
        return None
    if args[:1] == ["run"] and "--no-sync" in args[1:]:
        return None
    if args[:1] in (["add"], ["remove"]) and "--no-sync" in args[1:]:
        return None
    if args[:2] in (["pip", "list"], ["pip", "show"], ["pip", "check"]):
        return None
    if args[:1] == ["venv"]:
        # The filesystem sandbox prevents targeting a shared environment.
        return None
    if args[:2] in (["pip", "install"], ["pip", "uninstall"], ["pip", "sync"]):
        for index, value in enumerate(args):
            target = value.split("=", 1)[1] if value.startswith("--python=") else None
            if value == "--python" and index + 1 < len(args):
                target = args[index + 1]
            if target:
                # Do not resolve the Python symlink itself: venv/bin/python
                # commonly points at the system interpreter.
                interpreter = Path(os.path.abspath(cwd / target))
                environment = interpreter.parent.parent.resolve()
                root, _ = repository_paths(cwd)
                if environment.is_relative_to(root) and (environment / "pyvenv.cfg").is_file():
                    if environment not in shared_environments(cwd):
                        return None
    return POLICY_MESSAGE


def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:
    """Build a fail-closed Linux filesystem sandbox for a command and its children.

    Only the checkout, Git administration directory, and private temporary
    storage are writable. Existing shared environments remain read-only even
    when the checkout is the primary repository. No host chmod or mount changes
    are performed. Network isolation is outside this policy's scope.
    """
    if not argv:
        raise ValueError("A command is required.")
    executable = shutil.which("bwrap")
    if executable is None:
        raise RuntimeError("Bubblewrap (bwrap) is required for SDD commands; refusing unsandboxed execution.")
    root, git_dir = repository_paths(cwd)
    command = [
        executable,
        "--die-with-parent",
        "--unshare-pid",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(root),
        str(root),
    ]
    if git_dir is not None and not git_dir.is_relative_to(root):
        command.extend(["--bind", str(git_dir), str(git_dir)])
    for environment in shared_environments(cwd):
        command.extend(["--ro-bind", str(environment), str(environment)])
    # Caches are disposable and must not write into the shared host cache.
    command.extend(["--setenv", "XDG_CACHE_HOME", "/tmp/cache", "--setenv", "UV_CACHE_DIR", "/tmp/uv-cache"])
    command.extend(["--setenv", "UV_NO_SYNC", "1", "--setenv", "PYTHONDONTWRITEBYTECODE", "1"])
    source_roots = sorted((root / "packages").glob("*/src"))
    if source_roots:
        python_path = os.pathsep.join(map(str, source_roots))
        if inherited := os.environ.get("PYTHONPATH"):
            python_path += os.pathsep + inherited
        command.extend(["--setenv", "PYTHONPATH", python_path])
    command.extend(["--chdir", str(cwd.resolve()), "--", *argv])
    return command


def hook_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap native Bash input and reject shared-environment file-tool writes."""
    cwd = Path(payload["cwd"])
    tool_input = payload["tool_input"]
    output: dict[str, Any] = {"hookEventName": "PreToolUse"}
    try:
        if payload["tool_name"] == "Bash":
            command = tool_input["command"]
            if not isinstance(command, str) or not command:
                raise ValueError("Bash command must be a non-empty string")
            wrapped = protected_argv(cwd, ["/bin/bash", "-c", command])
            # Preserve timeout/background/description without granting approval
            # or overriding decisions from other hooks.
            output["updatedInput"] = {**tool_input, "command": shlex.join(wrapped)}
        else:
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if not isinstance(path, str):
                raise ValueError("File tool requires a path")
            validate_write_path(cwd, cwd / path)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        output.update(permissionDecision="deny", permissionDecisionReason=str(exc))
    return {"hookSpecificOutput": output}


def main() -> None:
    """Serve a native PreToolUse hook without importing application dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true", required=True)
    parser.parse_args()
    try:
        result = hook_response(json.load(sys.stdin))
    except Exception as exc:
        # A nonzero hook failure normally fails open. Emit an explicit denial.
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Shared-environment guard failed: {exc}",
            }
        }
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
