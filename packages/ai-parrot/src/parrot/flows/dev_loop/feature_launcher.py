"""Host-side launcher for one prepared SDD feature worktree."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence

from . import native_claude_sandbox, worktree_environment


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


def _run(argv: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a host preparation command through the launcher test seam."""
    try:
        return subprocess.run(argv, cwd=cwd, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise LaunchError(1, str(exc)) from exc


def _require(result: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    """Turn an external-command failure into an operator-facing error."""
    if result.returncode:
        raise LaunchError(1, result.stderr.strip() or result.stdout.strip() or "host command failed")
    return result


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


def _attach_session(name: str) -> int:
    """Attach or switch to the requested tmux session."""
    if os.environ.get("TMUX"):
        _require(_run(["tmux", "switch-client", "-t", name], cwd=Path.cwd()))
        return 0
    os.execvp("tmux", ["tmux", "attach-session", "-t", name])
    return 1


def _tmux_environment() -> list[str]:
    """Build tmux ``-e`` environment assignments for the child server."""
    names = sorted(name for name in os.environ if name.startswith("PARROT_SDD_"))
    for name in ("PATH", "VIRTUAL_ENV"):
        if name in os.environ and name not in names:
            names.append(name)
    return [f"{name}={os.environ[name]}" for name in names]


def launch(
    key: str,
    *,
    tmux: bool,
    detach: bool,
    sandbox: str | None,
    allowed_domains: Sequence[str],
    no_upstream: bool,
    claude_args: Sequence[str],
) -> int:
    """Prepare and launch or attach to the worker for one feature."""
    if sandbox is not None:
        if sandbox not in native_claude_sandbox.SANDBOX_MODES:
            raise LaunchError(2, f"invalid sandbox mode: {sandbox}")
        os.environ[native_claude_sandbox.MODE_ENV] = sandbox
    primary = resolve_primary_checkout(Path.cwd())
    ref = resolve_feature(primary, key)
    name = tmux_session_name(ref.feature_id)
    if tmux_session_exists(name):
        if not tmux:
            raise LaunchError(
                2, f"a worker for {ref.feature_id} already runs in tmux session {name}; use --tmux to attach"
            )
        return _attach_session(name)

    worktree = ensure_feature_worktree(primary, ref)
    if not no_upstream:
        print(prepare_upstream(worktree), file=sys.stderr)
    domain_args = [item for domain in allowed_domains for item in ("--sandbox-allow-domain", domain)]
    if not tmux:
        return native_claude_sandbox.launch_worker(
            [*domain_args, *claude_args], cwd=worktree, initial_prompt=f"run {ref.feature_id}"
        )
    if native_claude_sandbox.sandbox_platform() == "windows":
        raise LaunchError(1, "--tmux is not available on native Windows")
    if shutil.which("tmux") is None:
        raise LaunchError(1, "tmux is not available on PATH")
    command = ["tmux", "new-session", "-d", "-s", name, "-c", str(worktree)]
    for assignment in _tmux_environment():
        command.extend(("-e", assignment))
    command.extend(
        [
            "--",
            sys.executable,
            "-m",
            "parrot.flows.dev_loop.feature_launcher",
            "--in-session",
            ref.feature_id,
            *domain_args,
        ]
    )
    if claude_args:
        command.extend(("--", *claude_args))
    _require(_run(command, cwd=worktree))
    if detach:
        print(f"launch-worker: attach with: tmux attach -t {name}", file=sys.stderr)
        return 0
    return _attach_session(name)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the tmux child mode and launch Claude from its prepared worktree."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-session", metavar="FEAT-ID")
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
        [*domain_args, *forwarded], cwd=Path.cwd(), initial_prompt=f"run {args.in_session}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
