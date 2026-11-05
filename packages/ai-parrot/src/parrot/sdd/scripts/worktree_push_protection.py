"""Provision or remove sandbox push protection on one SDD linked worktree (host only).

Sandbox ``sync-base --cherry-pick`` requires ``extensions.worktreeConfig=true`` and exactly one
effective ``remote.origin.pushurl=no_push`` on the target worktree. The worker launcher enables it
before a sandboxed worker starts; ``/sdd-done`` disables it before the host pushes the branch.
Only the target worktree's ``config.worktree`` is written; the common push URL and sibling
worktrees are never touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel

from parrot.sdd.scripts.worktree_sync import (
    EXIT_OK,
    EXIT_TARGET,
    EXIT_TRANSPORT,
    SyncError,
    _git,
    in_sandbox,
    push_protection_ok,
    resolve_target,
)

NO_PUSH = "no_push"
_PUSHURL = "remote.origin.pushurl"


class PushProtectionResult(BaseModel):
    """Machine-readable push-protection outcome."""

    worktree: str
    action: Literal["enable", "disable", "status"]
    protected: bool
    exit_code: int
    message: str


def _require_host(action: str) -> None:
    """Refuse configuration writes from inside a sandbox."""
    if in_sandbox():
        raise SyncError(EXIT_TRANSPORT, f"push-protection {action} is a host operation; never run it in a sandbox")


def _git_dir(wt: Path, flag: str) -> Path:
    """Return an absolute Git directory for ``wt`` (``--git-dir`` or ``--git-common-dir``)."""
    proc = _git(wt, "rev-parse", flag)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SyncError(EXIT_TARGET, f"not a Git worktree: {wt} ({proc.stderr.strip()})")
    path = Path(proc.stdout.strip())
    return (path if path.is_absolute() else wt / path).resolve()


def _common_config(wt: Path) -> Path:
    """Return the common config file of a linked worktree; refuse the primary checkout."""
    common = _git_dir(wt, "--git-common-dir")
    if _git_dir(wt, "--git-dir") == common:
        raise SyncError(EXIT_TARGET, f"{wt} is the primary checkout; push protection applies to linked worktrees only")
    return common / "config"


def _common_values(wt: Path, config: Path, key: str) -> list[str]:
    """Read every value of ``key`` from the common config file only."""
    proc = _git(wt, "config", "--file", str(config), "--get-all", key)
    return [line for line in proc.stdout.splitlines() if line] if proc.returncode == 0 else []


def _worktree_config_enabled(wt: Path) -> bool:
    """Return whether ``extensions.worktreeConfig`` is effectively true."""
    proc = _git(wt, "config", "--bool", "extensions.worktreeConfig")
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def enable(wt: Path) -> str:
    """Make ``remote.origin.pushurl=no_push`` the sole effective push URL of one linked worktree.

    Args:
        wt: Linked worktree path.

    Returns:
        Operator-facing summary.

    Raises:
        SyncError: In a sandbox (exit 5), or when the repository needs the manual procedure in
            ``docs/sdd/worktree-sync-base.md`` (exit 2). Nothing is written on refusal.
    """
    _require_host("enable")
    config = _common_config(wt)
    if _common_values(wt, config, "core.worktree"):
        raise SyncError(EXIT_TARGET, "common core.worktree is set; migrate it by hand (docs/sdd/worktree-sync-base.md)")
    if any(value.lower() == "true" for value in _common_values(wt, config, "core.bare")):
        raise SyncError(EXIT_TARGET, "common core.bare=true; migrate it by hand (docs/sdd/worktree-sync-base.md)")
    if _common_values(wt, config, _PUSHURL):
        raise SyncError(
            EXIT_TARGET, f"a common {_PUSHURL} is set; remove it by hand first (docs/sdd/worktree-sync-base.md)"
        )
    if push_protection_ok(wt):
        return "push protection already enabled"
    steps = (
        ("config", "extensions.worktreeConfig", "true"),
        ("config", "--worktree", "--replace-all", _PUSHURL, NO_PUSH),
    )
    for step in steps:
        proc = _git(wt, *step)
        if proc.returncode != 0:
            raise SyncError(EXIT_TARGET, f"git {' '.join(step)} failed: {proc.stderr.strip()}")
    if not push_protection_ok(wt):
        raise SyncError(EXIT_TARGET, "push protection did not take effect; inspect the worktree's Git config")
    return "push protection enabled"


def disable(wt: Path) -> str:
    """Remove the worktree-local push URL so the host can push this worktree's branch again.

    Args:
        wt: Linked worktree path.

    Returns:
        Operator-facing summary.

    Raises:
        SyncError: In a sandbox (exit 5), or when Git refuses the removal (exit 2).
    """
    _require_host("disable")
    _common_config(wt)
    if not _worktree_config_enabled(wt):
        return "push protection not enabled"
    proc = _git(wt, "config", "--worktree", "--unset-all", _PUSHURL)
    if proc.returncode == 5:  # git: the key was not set
        return "push protection not enabled"
    if proc.returncode != 0:
        raise SyncError(EXIT_TARGET, f"cannot remove worktree {_PUSHURL}: {proc.stderr.strip()}")
    return "push protection disabled"


def main(argv: Sequence[str] | None = None) -> int:
    """Serve ``parrot sdd worktree push-protection {enable,disable,status} <target>``."""
    parser = argparse.ArgumentParser(
        description="Provision or remove sandbox push protection on one SDD linked worktree."
    )
    parser.add_argument("action", choices=("enable", "disable", "status"))
    parser.add_argument("target", help="FEAT-ID, brief key, worktree name or path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    worktree = args.target
    try:
        wt = resolve_target(args.target)
        worktree = str(wt)
        if args.action == "enable":
            message = enable(wt)
        elif args.action == "disable":
            message = disable(wt)
        else:
            message = "protected" if push_protection_ok(wt) else "not protected"
        result = PushProtectionResult(
            worktree=worktree, action=args.action, protected=push_protection_ok(wt), exit_code=EXIT_OK, message=message
        )
    except SyncError as exc:
        result = PushProtectionResult(
            worktree=worktree, action=args.action, protected=False, exit_code=exc.exit_code, message=str(exc)
        )
    except OSError as exc:
        result = PushProtectionResult(
            worktree=worktree,
            action=args.action,
            protected=False,
            exit_code=EXIT_TRANSPORT,
            message=f"required tool unavailable: {exc}",
        )
    if args.json:
        print(result.model_dump_json())
    else:
        print(result.message, file=sys.stdout if result.exit_code == EXIT_OK else sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
