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
import shlex
import shutil
import subprocess
import sys
import time
from typing import Literal, Mapping, Sequence

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
    worktree: str | None = None  # set for a brief: its worktree (re-attached from its branch when missing)

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


OFFICIAL_AGY_INSTALL = "curl -fsSL https://antigravity.google/cli/install.sh | bash"

_SNAP_WRAPPER_READ_LIMIT = 4096


def resolve_agy() -> Path:
    """Locate the ``agy`` the launch would exec.

    Returns:
        The path ``shutil.which`` found for ``agy``.

    Raises:
        LaunchError: Exit code 1 when ``agy`` is not on ``PATH``.
    """
    found = shutil.which("agy")
    if found is None:
        raise LaunchError(1, f"missing host prerequisite(s): agy — install the official build: {OFFICIAL_AGY_INSTALL}")
    return Path(found)


def agy_is_snap(agy: Path) -> bool:
    """Tell whether ``agy`` is the community snap.

    True when ``agy`` (as given or after symlink resolution) lives under ``/snap/``, when it resolves to the
    ``snap`` binary itself (the ``snap run`` wrapper, ``/usr/bin/snap``), or when it is a small text wrapper
    script that invokes ``snap run``.

    Args:
        agy: The ``agy`` path found on ``PATH``.

    Returns:
        Whether the launch would exec the community snap.
    """
    if str(agy).startswith("/snap/"):
        return True
    try:
        resolved = agy.resolve()
    except (OSError, RuntimeError):
        resolved = agy
    if str(resolved).startswith("/snap/") or resolved.name == "snap":
        return True
    try:
        with open(resolved, "rb") as handle:
            head = handle.read(_SNAP_WRAPPER_READ_LIMIT)
    except OSError:
        return False
    if b"\0" in head:  # a binary: never a text wrapper
        return False
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return "snap run" in text


def require_official_agy(agy: Path) -> None:
    """Refuse the community snap, naming the official install command.

    Args:
        agy: The ``agy`` path found on ``PATH``.

    Raises:
        LaunchError: Exit code 2 when ``agy`` is the community snap.
    """
    if agy_is_snap(agy):
        raise LaunchError(
            2,
            f"{agy} is the community antigravity-cli snap, which cannot run the SDD flow (no project Python, "
            f"bwrap or ssh inside its confinement). Install the official agy instead: {OFFICIAL_AGY_INSTALL}",
        )


def google_worker_sandbox(sandbox: str | None, allowed_domains: Sequence[str]) -> str:
    """Select the Google worker's sandbox backend, failing closed before ``agy`` starts.

    Args:
        sandbox: The requested sandbox mode; ``None`` means ``required``.
        allowed_domains: Configured network-domain restrictions (unsupported for Google).

    Returns:
        Always :data:`native_claude_sandbox.BACKEND_BUBBLEWRAP`.

    Raises:
        LaunchError: Exit code 2 for ``off``, an invalid mode or domain restrictions; exit code 1 for a
            non-Linux platform, a missing ``bwrap`` or a failed Bubblewrap capability probe.
    """
    mode = (sandbox or "required").strip().lower()
    if mode == "off":
        raise LaunchError(2, "--sandbox off is not allowed for the unattended Google worker")
    if mode not in native_claude_sandbox.SANDBOX_MODES:
        raise LaunchError(2, f"invalid sandbox mode: {sandbox}")
    if allowed_domains:
        raise LaunchError(
            2,
            "network domain restrictions are not supported with --host google (the Bubblewrap wrapper does not "
            "isolate the network); remove --sandbox-allow-domain and the configured domains",
        )
    platform = native_claude_sandbox.sandbox_platform()
    if platform != "linux":
        raise LaunchError(
            1, f"the Google worker requires the Bubblewrap sandbox, which is Linux-only (platform: {platform})"
        )
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise LaunchError(1, "missing host prerequisite(s): bwrap — the Google worker requires Bubblewrap")
    usable, reason = native_claude_sandbox.bwrap_probe(bwrap)
    if not usable:
        raise LaunchError(1, f"Bubblewrap probe failed ({reason}); refusing to launch agy")
    return native_claude_sandbox.BACKEND_BUBBLEWRAP


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
        matches = _resolve_briefs(primary, key) or _reattach_brief_branch(primary, key)
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
    branch), so every worktree of the repository is searched. Each match carries that worktree. When no
    worktree holds it, ``_reattach_brief_branch`` may re-attach its surviving branch.
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


def _reattach_brief_branch(primary: Path, key: str) -> list[FeatureRef]:
    """Re-attach a surviving ``hotfix-<key>-*`` / ``fix-<key>-*`` branch whose worktree is gone.

    Only a branch no worktree has checked out qualifies; it is added under the resolved worktree root and the
    brief is then resolved from it (issue:1b8289182630).

    Args:
        primary: The primary checkout.
        key: The brief key the operator passed (e.g. a Jira key).

    Returns:
        The brief refs resolved from the re-attached worktree, or ``[]`` when no branch qualifies.

    Raises:
        LaunchError: exit 2 for ambiguous candidates or an occupied destination; exit 1 when git fails.
    """
    pattern = re.compile(rf"^(?:hotfix|fix)-{re.escape(key)}-.+$", re.IGNORECASE)
    refs = _run(["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin"], cwd=primary)
    if refs.returncode:
        return []
    local: set[str] = set()
    remote: set[str] = set()
    for line in refs.stdout.splitlines():
        ref = line.strip()
        if ref.startswith("refs/heads/"):
            name, bucket = ref.removeprefix("refs/heads/"), local
        elif ref.startswith("refs/remotes/origin/"):
            name, bucket = ref.removeprefix("refs/remotes/origin/"), remote
        else:
            continue
        if pattern.match(name):
            bucket.add(name)
    listing = _run(["git", "worktree", "list", "--porcelain"], cwd=primary)
    checked_out = {
        line.removeprefix("branch refs/heads/")
        for line in (listing.stdout.splitlines() if not listing.returncode else [])
        if line.startswith("branch refs/heads/")
    }
    candidates = sorted((local | remote) - checked_out)
    if not candidates:
        return []
    if len(candidates) > 1:
        raise LaunchError(2, f"ambiguous brief branches for {key!r}: {', '.join(candidates)}")
    branch = candidates[0]
    root = _require(
        _run([sys.executable, "-m", "parrot.sdd.scripts.worktree_root", "--root", str(primary)], cwd=primary)
    ).stdout.strip()
    destination = Path(root) / branch
    if os.path.lexists(destination):
        raise LaunchError(2, f"cannot re-attach {branch}: {destination} already exists")
    if branch in local:
        argv = ["git", "worktree", "add", str(destination), branch]
    else:
        argv = ["git", "worktree", "add", "--no-track", "-b", branch, str(destination), f"origin/{branch}"]
    _require(_run(argv, cwd=primary))
    print(f"launch-worker: re-attached brief branch {branch} at {destination}", file=sys.stderr)
    return _resolve_briefs(primary, key)


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


def _enable_push_protection(worktree: Path) -> str:
    """Provision the sandbox ``no_push`` guard on the host; a refusal is reported, never fatal.

    ``/sdd-done`` disables it again before pushing the branch.
    """
    # Host-only; imported here because the tmux child runs under python -S.
    from parrot.sdd.scripts import worktree_push_protection

    try:
        return f"launch-worker: {worktree_push_protection.enable(worktree)}"
    except (worktree_push_protection.SyncError, OSError, subprocess.SubprocessError) as exc:
        return f"launch-worker: push protection skipped: {exc}"


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
    host: Literal["claude", "google"] = "claude",
) -> int:
    """Prepare and launch or attach to the worker for one feature.

    ``gh_token=False`` forwards ``--no-gh-token`` so the launcher skips host-side ``GH_TOKEN`` resolution.

    ``base_env`` is the operator's environment captured BEFORE anything imported ``parrot``:
    that import lets navconfig load the project's settings ``.env`` (API keys and other secrets)
    into ``os.environ``. The worker and the tmux client get ``base_env``, never the loaded
    ``os.environ``. ``None`` falls back to ``os.environ`` for callers that never imported parrot.
    """
    if host == "google":
        agy = resolve_agy()
        require_official_agy(agy)

    env = dict(os.environ if base_env is None else base_env)
    for key_to_clear in tuple(env):
        if key_to_clear.startswith("PARROT_SDD_NOTIFY_"):
            env.pop(key_to_clear)
    if sandbox is not None and host == "claude":
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
    if host == "google":
        google_worker_sandbox(sandbox or os.environ.get(native_claude_sandbox.MODE_ENV), effective_domains)
        _require_agy_hooks(worktree)
    else:
        _preflight_sandbox(worktree, effective_domains)
    if not no_upstream:
        print(prepare_upstream(worktree), file=sys.stderr)
        # Host-only advisory; imported here because the tmux child runs under python -S.
        from parrot.sdd.scripts.worktree_sync import stale_base_summary

        print(stale_base_summary(worktree), file=sys.stderr)
    print(_enable_push_protection(worktree), file=sys.stderr)
    domain_args = (
        [] if host == "google" else [item for domain in allowed_domains for item in ("--sandbox-allow-domain", domain)]
    )
    token_args = [] if host == "google" or gh_token else ["--no-gh-token"]
    if not tmux:
        if host == "google":
            return launch_agy_worker(
                list(claude_args), cwd=worktree, initial_prompt=f"run {ref.prompt_id}", base_env=env
            )
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
            *(("--host", "google") if host == "google" else ()),
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


AGY_UNATTENDED_ENV = "PARROT_SDD_AGY_UNATTENDED"
AGY_WORKER_ARGS: tuple[str, ...] = ("--agent", "sdd-worker", "--dangerously-skip-permissions")


def agy_environment(base_env: Mapping[str, str] | None, *, unattended: bool) -> dict[str, str]:
    """Build an AGY environment without Claude-native sandbox markers.

    Args:
        base_env: Operator environment, or ``None`` to copy ``os.environ``.
        unattended: Whether to enable the guarded Bubblewrap worker mode.

    Returns:
        A fresh environment mapping for the AGY process.
    """
    env = dict(os.environ if base_env is None else base_env)
    for name in (
        native_claude_sandbox.CACHE_DIR_ENV,
        native_claude_sandbox.ROOTS_ENV,
        native_claude_sandbox.DEGRADED_ENV,
        native_claude_sandbox.BACKEND_ENV,
        AGY_UNATTENDED_ENV,
    ):
        env.pop(name, None)
    if unattended:
        env[AGY_UNATTENDED_ENV] = "1"
        env[native_claude_sandbox.BACKEND_ENV] = native_claude_sandbox.BACKEND_BUBBLEWRAP
    return env


def launch_agy_worker(
    agy_args: Sequence[str],
    *,
    cwd: Path,
    initial_prompt: str,
    base_env: Mapping[str, str] | None = None,
) -> int:
    """Exec the guarded unattended ``sdd-worker`` AGY process.

    Args:
        agy_args: Additional arguments forwarded verbatim to AGY.
        cwd: Feature worktree in which AGY runs.
        initial_prompt: Prompt passed to AGY's print mode.
        base_env: Operator environment, or ``None`` to copy ``os.environ``.

    Returns:
        A launch error code, or 1 if ``execvpe`` unexpectedly returns.
    """
    try:
        agy = resolve_agy()
        require_official_agy(agy)
    except LaunchError as exc:
        print(f"launch-worker: {exc}", file=sys.stderr)
        return exc.exit_code
    command = [str(agy), *AGY_WORKER_ARGS, *agy_args, "-p", initial_prompt]
    env = agy_environment(base_env, unattended=True)
    os.chdir(cwd)
    os.execvpe(command[0], command, env)
    return 1


def _require_agy_hooks(checkout: Path) -> None:
    """Require a current, runnable managed AGY permission hook in ``checkout``.

    Args:
        checkout: Worktree that will host the AGY session.

    Raises:
        LaunchError: Exit code 2 when the hook is absent, stale, or cannot execute.
    """
    from parrot.sdd.installer import _agy_permissions_report

    report = _agy_permissions_report(checkout)
    hint = "run `parrot sdd install --host google` in this repository"
    if report.get("command") is None:
        raise LaunchError(2, f"the agy permission hook is not installed in {checkout}/.agents/hooks.json; {hint}")
    if report.get("stale"):
        raise LaunchError(2, f"the agy permission hook matcher is stale ({report.get('matcher')!r}); {hint}")

    form = report.get("form")
    command = str(report["command"])
    runnable = False
    if form == "launcher":
        runnable = (checkout / "scripts" / "sdd" / "agy_hook.sh").is_file()
    elif form == "bare":
        runnable = shutil.which("parrot") is not None
    elif form == "baked":
        try:
            executable = Path(shlex.split(command)[0])
        except (IndexError, ValueError):
            executable = Path()
        runnable = executable.is_file() and os.access(executable, os.X_OK)
    if not runnable:
        raise LaunchError(2, f"the agy permission hook command is not runnable ({command!r}); {hint}")


def launch_session(
    initial_prompt: str,
    *,
    cwd: Path,
    claude_args: Sequence[str] = (),
    base_env: Mapping[str, str] | None = None,
    host: Literal["claude", "google"] = "claude",
) -> int:
    """Open an interactive Claude or AGY session in ``cwd`` with an initial prompt.

    Used by ``parrot sdd launch brief|fix``: no agent, no sandbox settings, no tmux — identical to typing the
    slash command by hand, except that the operator environment (``base_env``, captured before ``parrot`` was
    imported) is what the host starts from. AGY never receives ``--dangerously-skip-permissions``. Returns a
    host prerequisite error code, or 1 if ``execvpe`` unexpectedly returns.
    """
    if host == "google":
        try:
            agy = resolve_agy()
            require_official_agy(agy)
            _require_agy_hooks(cwd)
        except LaunchError as exc:
            print(f"launch: {exc}", file=sys.stderr)
            return exc.exit_code
        command = [str(agy), *claude_args, "-i", initial_prompt]
        env = agy_environment(base_env, unattended=False)
        os.chdir(cwd)
        os.execvpe(command[0], command, env)
        return 1
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
    parser.add_argument("--host", choices=("claude", "google"), default="claude")
    parser.add_argument("--sandbox-allow-domain", action="append", default=[])
    parser.add_argument("--no-gh-token", action="store_true", default=False)
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.in_session is None:
        parser.error("--in-session is required")
    forwarded = list(args.claude_args)
    if forwarded[:1] == ["--"]:
        forwarded.pop(0)
    if args.host == "google":
        return launch_agy_worker(forwarded, cwd=args.cwd or _invocation_dir(), initial_prompt=f"run {args.in_session}")
    domain_args = [item for domain in args.sandbox_allow_domain for item in ("--sandbox-allow-domain", domain)]
    token_args = ["--no-gh-token"] if args.no_gh_token else []
    return native_claude_sandbox.launch_worker(
        [*token_args, *domain_args, *forwarded],
        cwd=args.cwd or _invocation_dir(),
        initial_prompt=f"run {args.in_session}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
