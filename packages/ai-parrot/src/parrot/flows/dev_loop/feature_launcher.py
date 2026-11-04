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
import re
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
    worktree: str | None = None  # set for a brief: its already-provisioned worktree (never created here)

    @property
    def is_brief(self) -> bool:
        """Whether this ref is a brief held in an existing worktree rather than a feature index."""
        return self.worktree is not None

    @property
    def prompt_id(self) -> str:
        """The id the worker is started with: ``<slug>`` for a brief, the feature id otherwise."""
        return self.slug if self.is_brief else self.feature_id


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
    if not matches:
        matches = _resolve_briefs(primary, key)
    if len(matches) != 1:
        raise LaunchError(2, f"could not uniquely resolve feature {key!r}")
    return matches[0]


_BRIEF_KEY = re.compile(r"^key:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)


def _worktree_paths(primary: Path) -> list[Path]:
    """Return every worktree path of the repository (the primary checkout included)."""
    try:
        result = _run(["git", "worktree", "list", "--porcelain"], cwd=primary)
    except LaunchError:
        return []
    if result.returncode:
        return []
    return [Path(line[len("worktree ") :]) for line in result.stdout.splitlines() if line.startswith("worktree ")]


def _brief_frontmatter_key(root: Path, spec: str) -> str | None:
    """Return the ``key:`` of a brief's frontmatter, ``None`` when unreadable or absent."""
    try:
        text = (root / spec).read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    block = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    found = _BRIEF_KEY.search(block)
    return found.group(1) if found else None


def _resolve_briefs(primary: Path, key: str) -> list[FeatureRef]:
    """Find briefs whose slug, ``BRIEF-<slug>`` id or frontmatter key matches ``key`` (case-insensitive).

    A brief lives only in its own worktree (``sdd/briefs/<slug>.index.json`` on its ``fix-*``/``hotfix-*``
    branch), so every worktree of the repository is searched. Each match carries that worktree.
    """
    wanted = key.casefold()
    matches: list[FeatureRef] = []
    for root in _worktree_paths(primary):
        for index_path in sorted((root / "sdd" / "briefs").glob("*.index.json")):
            try:
                header = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(header, dict) or header.get("type") != "brief":
                continue
            feature_id = header.get("feature_id")
            slug = header.get("feature")
            spec = header.get("spec")
            if not all(isinstance(value, str) and value for value in (feature_id, slug, spec)):
                continue
            names = {feature_id.casefold(), slug.casefold()}
            frontmatter_key = _brief_frontmatter_key(root, spec)
            if frontmatter_key:
                names.add(frontmatter_key.casefold())
            if wanted in names:
                matches.append(
                    FeatureRef(
                        feature_id=feature_id,
                        slug=slug,
                        spec=spec,
                        index=str(index_path.relative_to(root)),
                        worktree=str(root),
                    )
                )
    return matches


def ensure_feature_worktree(primary: Path, ref: FeatureRef) -> Path:
    """Provision or reuse the feature worktree using the existing host runner."""
    # Packaged runner (FEAT-633): works in consumer repositories that have no `scripts/` tree.
    result = _run(
        [
            sys.executable,
            "-m",
            "parrot.sdd.scripts.ensure_worktree",
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


_TMUX_NAME_MAX = 64
_TMUX_UNSAFE = re.compile(r"[^a-z0-9_-]+")


def tmux_session_name(feature_id: str, slug: str) -> str:
    """Return the deterministic tmux session name for a feature.

    The tmux server is shared by every repository of the user and FEAT ids restart at ``FEAT-1`` in each
    one, so the spec slug is part of the name. It stays deterministic so reattach and the duplicate-worker
    guard keep working.

    Args:
        feature_id: Feature id, e.g. ``FEAT-2``.
        slug: Feature (spec) slug, e.g. ``simple-agent``.

    Returns:
        ``sdd-<feature id>-<slug>`` lower-cased, with characters tmux rejects (``.``, ``:``) replaced by
        ``-`` and the slug truncated to keep the name within 64 characters.
    """
    prefix = "sdd-" + _TMUX_UNSAFE.sub("-", feature_id.lower()).strip("-")
    tail = _TMUX_UNSAFE.sub("-", slug.lower()).strip("-")
    tail = tail[: max(_TMUX_NAME_MAX - len(prefix) - 1, 0)].rstrip("-")
    return f"{prefix}-{tail}" if tail else prefix


def legacy_tmux_session_name(feature_id: str) -> str:
    """Return the pre-TASK-5119 session name ``sdd-<FEAT-ID>``, still honoured for live sessions."""
    return f"sdd-{feature_id}"


def _session_path(name: str) -> Path | None:
    """Return the start directory of a tmux session, ``None`` when unknown."""
    try:
        result = _run(["tmux", "display-message", "-p", "-t", f"={name}:", "#{session_path}"], cwd=Path.cwd())
    except LaunchError:
        return None
    path = result.stdout.strip()
    return Path(path) if result.returncode == 0 and path else None


def _existing_session(primary: Path, ref: FeatureRef) -> str:
    """Return the session name to use for ``ref``: the new name, or a live legacy session of this repo.

    A legacy ``sdd-<FEAT-ID>`` session is reused only when it was started inside ``primary`` (the feature
    worktrees live under it); one from another repository is ignored, so it can never be attached to.
    """
    name = tmux_session_name(ref.feature_id, ref.slug)
    if tmux_session_exists(name):
        return name
    legacy = legacy_tmux_session_name(ref.feature_id)
    if tmux_session_exists(legacy):
        path = _session_path(legacy)
        if path is not None and path.resolve().is_relative_to(primary.resolve()):
            return legacy
    return name


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
    gh_token: bool = True,
) -> int:
    """Prepare and launch or attach to the worker for one feature.

    ``gh_token=False`` forwards ``--no-gh-token`` so the launcher skips host-side ``GH_TOKEN`` resolution.

    ``base_env`` is the operator's environment captured BEFORE anything imported ``parrot``:
    that import lets navconfig load the project's settings ``.env`` (API keys and other secrets)
    into ``os.environ``. The worker and the tmux client get ``base_env``, never the loaded
    ``os.environ``. ``None`` falls back to ``os.environ`` for callers that never imported parrot.
    """
    env = dict(os.environ if base_env is None else base_env)
    for key_to_clear in tuple(env):
        if key_to_clear.startswith("PARROT_SDD_NOTIFY_"):
            env.pop(key_to_clear)
    if sandbox is not None:
        if sandbox not in native_claude_sandbox.SANDBOX_MODES:
            raise LaunchError(2, f"invalid sandbox mode: {sandbox}")
        env[native_claude_sandbox.MODE_ENV] = sandbox
        os.environ[native_claude_sandbox.MODE_ENV] = sandbox  # read by the in-process host preflight
    primary = resolve_primary_checkout(_invocation_dir())
    ref = resolve_feature(primary, key)
    name = _existing_session(primary, ref)
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

    if ref.worktree is not None:
        # A brief: /sdd-brief already provisioned its worktree; never create one here.
        worktree = Path(ref.worktree)
        if not worktree.is_dir():
            raise LaunchError(2, f"brief worktree {worktree} does not exist")
    else:
        worktree = ensure_feature_worktree(primary, ref)
    try:
        # Primary checkout only: the sandboxed session can rewrite its own worktree pyproject.
        config_domains, _config_gh_token = native_claude_sandbox.load_launch_config(primary)
        effective_domains = native_claude_sandbox.merge_domains(
            config_domains, native_claude_sandbox.validate_allowed_domains(allowed_domains)
        )
    except ValueError as exc:
        raise LaunchError(2, str(exc)) from exc
    _preflight_sandbox(worktree, effective_domains)
    if not no_upstream:
        print(prepare_upstream(worktree), file=sys.stderr)
    domain_args = [item for domain in allowed_domains for item in ("--sandbox-allow-domain", domain)]
    token_args = [] if gh_token else ["--no-gh-token"]
    if not tmux:
        return native_claude_sandbox.launch_worker(
            [*token_args, *domain_args, *claude_args],
            cwd=worktree,
            initial_prompt=f"run {ref.prompt_id}",
            base_env=env,
        )
    if native_claude_sandbox.sandbox_platform() == "windows":
        raise LaunchError(1, "--tmux is not available on native Windows")
    if shutil.which("tmux") is None:
        raise LaunchError(1, "tmux is not available on PATH")
    desktop_keys = (
        "PATH",
        "HOME",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR",
    )
    env["PARROT_SDD_NOTIFY_FEATURE"] = ref.feature_id
    env["PARROT_SDD_NOTIFY_SLUG"] = ref.slug
    env["PARROT_SDD_NOTIFY_DESKTOP"] = json.dumps({name: env[name] for name in desktop_keys if name in env})
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
            ref.prompt_id,
            "--cwd",
            str(worktree),
            *domain_args,
            *token_args,
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


def launch_session(
    initial_prompt: str,
    *,
    cwd: Path,
    claude_args: Sequence[str] = (),
    base_env: Mapping[str, str] | None = None,
) -> int:
    """Open an interactive Claude session in ``cwd`` with ``initial_prompt`` as its first message (C30 item 5).

    Used by ``parrot sdd launch brief|fix``: no agent, no sandbox settings, no tmux — identical to typing the
    slash command by hand, except that the operator environment (``base_env``, captured before ``parrot`` was
    imported) is what Claude starts from. Returns 1 when ``claude`` is not on PATH; otherwise never returns.
    """
    claude = shutil.which("claude")
    if claude is None:
        print("launch: missing host prerequisite(s): claude", file=sys.stderr)
        return 1
    command = [
        claude,
        "--setting-sources",
        "project,local",
        "--model",
        native_claude_sandbox._DEFAULT_MODEL,
        *claude_args,
        initial_prompt,
    ]
    env = dict(os.environ if base_env is None else base_env)
    os.chdir(cwd)
    os.execvpe(command[0], command, env)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the tmux child mode and launch Claude from its prepared worktree."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-session", metavar="FEAT-ID")
    # The worktree is passed explicitly rather than trusted from the process cwd.
    parser.add_argument("--cwd", type=Path, default=None)
    parser.add_argument("--sandbox-allow-domain", action="append", default=[])
    parser.add_argument("--no-gh-token", action="store_true", default=False)
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.in_session is None:
        parser.error("--in-session is required")
    forwarded = list(args.claude_args)
    if forwarded[:1] == ["--"]:
        forwarded.pop(0)
    domain_args = [item for domain in args.sandbox_allow_domain for item in ("--sandbox-allow-domain", domain)]
    token_args = ["--no-gh-token"] if args.no_gh_token else []
    return native_claude_sandbox.launch_worker(
        [*token_args, *domain_args, *forwarded],
        cwd=args.cwd or _invocation_dir(),
        initial_prompt=f"run {args.in_session}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
