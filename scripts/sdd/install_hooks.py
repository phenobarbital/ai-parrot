"""``install_hooks.py`` — install the daily /sdd-spec intake prune git hook (FEAT-577).

Adds a marker-delimited block to post-checkout / post-merge / post-commit in the
effective hooks directory (``git rev-parse --git-path hooks``). The block runs
``python -m scripts.sdd.prune_intake --daily --apply`` from the primary checkout;
the ``--daily`` stamp limits it to once per 24 h. Idempotent; ``--uninstall``
removes only this block. Refuses (exit 2) when the hooks directory is missing.
"""

from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from pathlib import Path

MARKER_BEGIN: str = "# >>> sdd-intake-prune >>>"
MARKER_END: str = "# <<< sdd-intake-prune <<<"
HOOK_EVENTS: tuple[str, ...] = ("post-checkout", "post-merge", "post-commit")
SHEBANG: str = "#!/bin/sh\n"


def hooks_dir(repo_root: Path) -> Path:
    """Resolve ``git rev-parse --git-path hooks`` against ``repo_root`` (honours core.hooksPath)."""
    out = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    path = Path(out)
    return path if path.is_absolute() else (repo_root / path).resolve()


def render_block(python: str, repo_root: Path) -> str:
    """The marker-delimited shell block: primary checkout only; prune --daily --apply; never fails."""
    return (
        f"{MARKER_BEGIN}\n"
        "# Prune /sdd-spec intake staging older than 10 days, at most once a day (FEAT-577).\n"
        "# Installed by `python -m scripts.sdd.install_hooks`; remove with `--uninstall`.\n"
        "if [ -d .git ]; then\n"
        f'    ( cd "{repo_root}" && "{python}" -m scripts.sdd.prune_intake --daily --apply ) >/dev/null 2>&1 || true\n'
        "fi\n"
        f"{MARKER_END}\n"
    )


def _strip_block(text: str) -> str:
    """Remove an existing sdd-intake-prune block (markers inclusive); return the rest unchanged."""
    lines = text.splitlines(keepends=True)
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == MARKER_BEGIN:
            start_idx = i
        elif line.strip() == MARKER_END:
            end_idx = i
            break

    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        new_lines = lines[:start_idx] + lines[end_idx + 1 :]
        return "".join(new_lines)
    return text


def install(hooks: Path, block: str, events: tuple[str, ...] = HOOK_EVENTS) -> list[Path]:
    """Add or replace the block in each hook; create + chmod +x missing hooks. Raises FileNotFoundError when ``hooks`` is missing."""
    if not hooks.is_dir():
        raise FileNotFoundError(hooks)

    modified_paths: list[Path] = []
    for event in events:
        hook_path = hooks / event
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8")
        else:
            content = SHEBANG

        stripped = _strip_block(content)
        if not stripped.endswith("\n") and stripped != "":
            stripped += "\n"

        new_content = stripped + block
        hook_path.write_text(new_content, encoding="utf-8")

        # Add execute permissions
        current_mode = hook_path.stat().st_mode
        hook_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        modified_paths.append(hook_path)

    return modified_paths


def uninstall(hooks: Path, events: tuple[str, ...] = HOOK_EVENTS) -> list[Path]:
    """Remove only the sdd-intake-prune block from each hook; leave everything else byte-identical."""
    modified_paths: list[Path] = []
    if not hooks.is_dir():
        return modified_paths

    for event in events:
        hook_path = hooks / event
        if not hook_path.exists():
            continue

        content = hook_path.read_text(encoding="utf-8")
        if MARKER_BEGIN not in content:
            continue

        stripped = _strip_block(content)
        hook_path.write_text(stripped, encoding="utf-8")
        modified_paths.append(hook_path)

    return modified_paths


def main(argv: list[str] | None = None) -> int:
    """CLI: [--uninstall] [--repo-root]. Exit 0; 2 when the hooks dir is missing (message names core.hooksPath)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    try:
        hooks = hooks_dir(repo_root)
    except Exception:
        # Fallback if git command fails or we are not in a git repo
        hooks = repo_root / ".git" / "hooks"

    if not hooks.is_dir():
        print(
            f"hooks directory {hooks} does not exist — check `git config core.hooksPath`; nothing installed",
            file=sys.stderr,
        )
        return 2

    if args.uninstall:
        uninstalled = uninstall(hooks)
        for p in uninstalled:
            print(f"Uninstalled prune hook from {p}")
    else:
        block = render_block(sys.executable, repo_root)
        installed = install(hooks, block)
        for p in installed:
            print(f"Installed prune hook to {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
