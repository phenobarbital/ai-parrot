"""Host-side launcher for one prepared SDD feature worktree.

Standard library only: the tmux child runs this file as a script with ``python -S`` so that no
``parrot`` import (and with it navconfig, which loads the project's settings ``.env`` into
``os.environ``) ever happens in the process that execs Claude.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Mapping, Sequence

if __package__:
    from . import native_claude_sandbox, worktree_environment
else:  # run as a script (the tmux child): this file's directory is sys.path[0]
    import native_claude_sandbox
    import worktree_environment


@dataclass(frozen=True)
class FeatureRef:
    """Feature metadata required to prepare a worktree."""

    feature_id: str
    slug: str
    spec: str
    index: str


class LaunchError(Exception):
    """An operator-facing launch failure with its CLI exit code."""

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _run(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a host preparation command through the launcher test seam.

    Args:
        argv: Command and arguments.
        cwd: Working directory.
        env: Explicit environment; ``None`` inherits ``os.environ``.
    """
    try:
        return subprocess.run(
            argv, cwd=cwd, check=False, capture_output=True, text=True, env=None if env is None else dict(env)
        )
    except OSError as exc:
        raise LaunchError(1, str(exc)) from exc


def _require(result: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    """Turn an external-command failure into an operator-facing error."""
    if result.returncode:
        raise LaunchError(1, result.stderr.strip() or result.stdout.strip() or "host command failed")
    return result


def _invocation_dir() -> Path:
    """Return the directory the operator launched from.

    Importing ``parrot`` lets navconfig ``chdir`` into its project root, so ``Path.cwd()``
    is no longer where the command was run by the time this module executes. The shell's
    ``PWD`` survives that ``chdir``; fall back to ``Path.cwd()`` only when it is unusable.
    """
    pwd = os.environ.get("PWD")
    if pwd and Path(pwd).is_dir():
        return Path(pwd)
    return Path.cwd()


def _preflight_sandbox(worktree: Path, allowed_domains: Sequence[str]) -> None:
    """Fail on the host, before any push or tmux session, when the sandbox cannot start."""
    try:
        native_claude_sandbox.plan_native_launch(worktree, allowed_domains=allowed_domains)
    except ValueError as exc:
        raise LaunchError(2, str(exc)) from exc
    except RuntimeError as exc:
        raise LaunchError(1, f"native sandbox unavailable ({exc}); refusing to launch") from exc


def resolve_primary_checkout(cwd: Path) -> Path:
    """Resolve the primary checkout that owns ``cwd``'s Git directory."""
    try:
        _root, git_dir = worktree_environment.repository_paths(cwd)
    except (OSError, ValueError) as exc:
        raise LaunchError(2, "launch-worker must run inside a Git checkout") from exc
    if git_dir is None:
        raise LaunchError(2, "launch-worker must run inside a Git checkout")
    return git_dir.parent


def resolve_feature(primary: Path, key: str) -> FeatureRef:
    """Resolve a feature id or slug from the primary checkout task indexes."""
    matches: list[FeatureRef] = []
    for index_path in (primary / "sdd" / "tasks" / "index").glob("*.json"):
        if index_path.name == "_orphans.json":
            continue
        try:
            header = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        feature_id = header.get("feature_id")
        slug = header.get("feature")
        spec = header.get("spec")
        if not all(isinstance(value, str) and value for value in (feature_id, slug, spec)):
            continue
        if key.casefold() in {feature_id.casefold(), slug.casefold()}:
            matches.append(
                FeatureRef(feature_id=feature_id, slug=slug, spec=spec, index=str(index_path.relative_to(primary)))
            )
    if len(matches) != 1:
        raise LaunchError(2, f"could not uniquely resolve feature {key!r}")
    return matches[0]


def ensure_feature_worktree(primary: Path, ref: FeatureRef) -> Path:
    """Provision or reuse the feature worktree using the existing host runner."""
    # FEAT-633 will repoint this invocation to its packaged runner.
    result = _run(
        [
            sys.executable,
            "-m",
            "scripts.sdd.ensure_worktree",
            "--slug",
            ref.slug,
            "--feature-id",
            ref.feature_id,
            "--spec",
            ref.spec,
            "--index",
            ref.index,
            "--json",
        ],
        cwd=primary,
    )
    _require(result)
    try:
        payload = json.loads(result.stdout)
        return Path(payload["path"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LaunchError(1, "ensure_worktree returned invalid JSON") from exc


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one Git command through the shared subprocess seam."""
    return _run(["git", *args], cwd=worktree)


def _set_upstream(worktree: Path, branch: str) -> None:
    """Set the feature branch tracking ref, surfacing Git failures."""
    _require(_git(worktree, "branch", "--set-upstream-to", f"origin/{branch}", branch))


def _is_ancestor(worktree: Path, older: str, newer: str) -> bool:
    """Return Git's ancestry result while distinguishing command failures."""
    result = _git(worktree, "merge-base", "--is-ancestor", older, newer)
    if result.returncode in (0, 1):
        return result.returncode == 0
    _require(result)
    return False


def prepare_upstream(worktree: Path) -> str:
    """Synchronize a feature branch with origin without resolving divergence."""
    branch = _require(_git(worktree, "rev-parse", "--abbrev-ref", "HEAD")).stdout.strip()
    remote = _require(_git(worktree, "ls-remote", "--heads", "origin", branch)).stdout.strip()
    if not remote:
        _require(_git(worktree, "push", "-u", "origin", branch))
        return f"launch-worker: pushed and tracking origin/{branch}"

    _require(_git(worktree, "fetch", "origin", branch))
    local = _require(_git(worktree, "rev-parse", "HEAD")).stdout.strip()
    remote_ref = f"origin/{branch}"
    remote_sha = _require(_git(worktree, "rev-parse", remote_ref)).stdout.strip()
    if local == remote_sha:
        _set_upstream(worktree, branch)
        return f"launch-worker: tracking origin/{branch} (up to date)"
    if _is_ancestor(worktree, local, remote_sha):
        _require(_git(worktree, "merge", "--ff-only", remote_ref))
        _set_upstream(worktree, branch)
        return f"launch-worker: fast-forwarded and tracking origin/{branch}"
    if _is_ancestor(worktree, remote_sha, local):
        _set_upstream(worktree, branch)
        return f"launch-worker: tracking origin/{branch} (local ahead)"
    raise LaunchError(2, f"branch diverged from origin/{branch}; reconcile it before launching")


def tmux_session_name(feature_id: str) -> str:
    """Return the deterministic tmux session name for a feature."""
    return f"sdd-{feature_id}"


def tmux_session_exists(name: str) -> bool:
    """Return whether a tmux session exists, treating absent tmux as absent session."""
    if shutil.which("tmux") is None:
        return False
    try:
        return _run(["tmux", "has-session", "-t", f"={name}"], cwd=Path.cwd()).returncode == 0
    except LaunchError:
        return False


# A detached launch polls the new pane until the launcher process has exec'ed into claude (the
# worker started) or the pane died. The child imports parrot first, which takes seconds, so a fixed
# short sleep would report success before a failure could happen.
_DETACH_START_TIMEOUT_SECONDS = 30.0
_DETACH_POLL_SECONDS = 0.25


def _dead_worker_status(name: str) -> str | None:
    """Return how a dead worker pane kept by ``remain-on-exit`` ended, or ``None`` when it is not dead.

    Args:
        name: tmux session name.

    Returns:
        ``"status N"`` / ``"signal N"`` for a dead pane, ``None`` for a live pane or a missing session.
    """
    state = _pane_state(name)
    if state is None or not state[0]:
        return None
    return state[1]


def _pane_state(name: str) -> tuple[bool, str, str] | None:
    """Return ``(dead, how_it_ended, current_command)`` for the session's pane, ``None`` when unknown."""
    try:
        result = _run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                f"={name}:",
                "#{pane_dead}|#{pane_dead_status}|#{pane_dead_signal}|#{pane_current_command}",
            ],
            cwd=Path.cwd(),
        )
    except LaunchError:
        return None
    if result.returncode:
        return None
    fields = result.stdout.strip().split("|")
    if len(fields) != 4:
        return None
    dead, status, signal, command = fields
    if dead != "1":
        return False, "", command
    if status:
        return True, f"status {status}", command
    return True, f"signal {signal}" if signal else "unknown status", command


def _await_worker_start(name: str) -> None:
    """Block until a detached worker has exec'ed into claude; raise when it died first."""
    deadline = time.monotonic() + _DETACH_START_TIMEOUT_SECONDS
    while True:
        state = _pane_state(name)
        if state is not None:
            dead, ended, command = state
            if dead:
                raise _dead_worker_error(name, ended)
            if command and not command.startswith("python"):
                return
        if time.monotonic() >= deadline:
            print(
                f"launch-worker: WARNING could not confirm the worker in {name} started within "
                f"{_DETACH_START_TIMEOUT_SECONDS:.0f}s; check it with: tmux attach -t {name}",
                file=sys.stderr,
            )
            return
        time.sleep(_DETACH_POLL_SECONDS)


def _dead_worker_error(name: str, ended: str) -> LaunchError:
    """Build the operator-facing error for a worker that exited inside its tmux session."""
    return LaunchError(
        1,
        f"the worker in tmux session {name} exited ({ended}); inspect it with "
        f"`tmux attach -t {name}`, then remove it with `tmux kill-session -t {name}` before relaunching",
    )


def _attach_session(name: str) -> int:
    """Attach or switch to the requested tmux session."""
    if os.environ.get("TMUX"):
        _require(_run(["tmux", "switch-client", "-t", name], cwd=Path.cwd()))
        return 0
    os.execvp("tmux", ["tmux", "attach-session", "-t", name])
    return 1


def _tmux_environment(env: Mapping[str, str]) -> list[str]:
    """Build tmux ``-e`` environment assignments for the child server from the launch environment."""
    names = sorted(name for name in env if name.startswith("PARROT_SDD_"))
    for name in ("PATH", "VIRTUAL_ENV"):
        if name in env and name not in names:
            names.append(name)
    return [f"{name}={env[name]}" for name in names]


def launch(
    key: str,
    *,
    tmux: bool,
    detach: bool,
    sandbox: str | None,
    allowed_domains: Sequence[str],
    no_upstream: bool,
    claude_args: Sequence[str],
    base_env: Mapping[str, str] | None = None,
) -> int:
    """Prepare and launch or attach to the worker for one feature.

    ``base_env`` is the operator's environment captured BEFORE anything imported ``parrot``:
    that import lets navconfig load the project's settings ``.env`` (API keys and other secrets)
    into ``os.environ``. The worker and the tmux client get ``base_env``, never the loaded
    ``os.environ``. ``None`` falls back to ``os.environ`` for callers that never imported parrot.
    """
    env = dict(os.environ if base_env is None else base_env)
    if sandbox is not None:
        if sandbox not in native_claude_sandbox.SANDBOX_MODES:
            raise LaunchError(2, f"invalid sandbox mode: {sandbox}")
        env[native_claude_sandbox.MODE_ENV] = sandbox
        os.environ[native_claude_sandbox.MODE_ENV] = sandbox  # read by the in-process host preflight
    primary = resolve_primary_checkout(_invocation_dir())
    ref = resolve_feature(primary, key)
    name = tmux_session_name(ref.feature_id)
    if tmux_session_exists(name):
        if not tmux:
            raise LaunchError(
                2, f"a worker for {ref.feature_id} already runs in tmux session {name}; use --tmux to attach"
            )
        if detach:
            status = _dead_worker_status(name)
            if status is not None:
                raise _dead_worker_error(name, status)
            print(f"launch-worker: attach with: tmux attach -t {name}", file=sys.stderr)
            return 0
        return _attach_session(name)

    worktree = ensure_feature_worktree(primary, ref)
    _preflight_sandbox(worktree, allowed_domains)
    if not no_upstream:
        print(prepare_upstream(worktree), file=sys.stderr)
    domain_args = [item for domain in allowed_domains for item in ("--sandbox-allow-domain", domain)]
    if not tmux:
        return native_claude_sandbox.launch_worker(
            [*domain_args, *claude_args], cwd=worktree, initial_prompt=f"run {ref.feature_id}", base_env=env
        )
    if native_claude_sandbox.sandbox_platform() == "windows":
        raise LaunchError(1, "--tmux is not available on native Windows")
    if shutil.which("tmux") is None:
        raise LaunchError(1, "tmux is not available on PATH")
    command = ["tmux", "new-session", "-d", "-s", name, "-c", str(worktree)]
    for assignment in _tmux_environment(env):
        command.extend(("-e", assignment))
    command.extend(
        [
            "--",
            sys.executable,
            "-S",  # no site-packages: parrot (and navconfig's .env loading) cannot be imported by the child
            str(Path(__file__).resolve()),
            "--in-session",
            ref.feature_id,
            "--cwd",
            str(worktree),
            *domain_args,
        ]
    )
    if claude_args:
        command.extend(("--", *claude_args))
    # Same tmux invocation, so the option is set before the child's exit can be processed: a worker
    # that fails keeps its pane (and output) instead of silently taking the session with it.
    command.extend((";", "set-option", "-w", "-t", f"={name}:", "remain-on-exit", "failed"))
    # The tmux client's environment seeds a new server's global environment, which the pane inherits.
    _require(_run(command, cwd=worktree, env=env))
    if detach:
        _await_worker_start(name)
        print(f"launch-worker: attach with: tmux attach -t {name}", file=sys.stderr)
        return 0
    return _attach_session(name)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the tmux child mode and launch Claude from its prepared worktree."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-session", metavar="FEAT-ID")
    # The worktree is passed explicitly rather than trusted from the process cwd.
    parser.add_argument("--cwd", type=Path, default=None)
    parser.add_argument("--sandbox-allow-domain", action="append", default=[])
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.in_session is None:
        parser.error("--in-session is required")
    forwarded = list(args.claude_args)
    if forwarded[:1] == ["--"]:
        forwarded.pop(0)
    domain_args = [item for domain in args.sandbox_allow_domain for item in ("--sandbox-allow-domain", domain)]
    return native_claude_sandbox.launch_worker(
        [*domain_args, *forwarded], cwd=args.cwd or _invocation_dir(), initial_prompt=f"run {args.in_session}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
