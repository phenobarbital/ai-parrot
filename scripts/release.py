#!/usr/bin/env python
"""Monorepo-aware version bumping and release driver for the ai-parrot workspace.

Every distribution under ``packages/`` carries its own independent version.
Most read it from a ``version.py`` (``dynamic = ["version"]`` +
``[tool.setuptools.dynamic] version = {attr = ...}``); ``navrules`` is a
maturin/PyO3 package and repeats the same number in three places
(``__init__.py``, ``pyproject.toml``, ``rust/Cargo.toml``) which must stay
in lockstep or the wheel metadata disagrees with the Python module.

``.github/workflows/release.yml`` fires on ``release: [created]``, builds all
distributions and publishes them to PyPI with ``skip-existing: true`` — so a
package whose version did not move is simply skipped rather than failing the
whole deploy. The git tag is the **core** ``ai-parrot`` version (tags observed
in this repo: ``0.26.1``, ``0.26.0``, ``0.25.35`` …).

Usage::

    source .venv/bin/activate

    python scripts/release.py status                 # read-only table
    python scripts/release.py bump patch --dry-run   # preview every write
    python scripts/release.py bump patch             # bump all + sync pins
    python scripts/release.py bump minor --only ai-parrot ai-parrot-server
    python scripts/release.py bump patch --commit --tag --push
    python scripts/release.py gh-release             # create the GitHub Release

``gh-release`` is deliberately a separate subcommand: creating the release
triggers the PyPI publish, and PyPI refuses a re-upload of an existing
version, so that step is irreversible and must be asked for explicitly.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- version-file styles ----------------------------------------------------
# "python": __version__ = "X.Y.Z"      (packages/*/src/**/version.py)
# "toml":   ^version = "X.Y.Z"         (pyproject.toml / Cargo.toml, 1st match)
_PATTERNS = {
    "python": (re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE),
               '__version__ = "{v}"'),
    "toml": (re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE),
             'version = "{v}"'),
}


@dataclass
class Package:
    """One publishable distribution in the workspace.

    Attributes:
        dist: PyPI distribution name.
        files: ``(path, style)`` pairs holding the version. The FIRST entry is
            the source of truth; the rest are followers kept in lockstep.
        path: Package directory, used to detect changes since the last tag.
    """

    dist: str
    files: list[tuple[str, str]]
    path: str
    aliases: list[str] = field(default_factory=list)

    @property
    def source_file(self) -> Path:
        return REPO_ROOT / self.files[0][0]

    def current(self) -> str:
        """Return the version recorded in the source-of-truth file."""
        rel, style = self.files[0]
        pattern, _ = _PATTERNS[style]
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            sys.exit(f"error: no version found in {rel}")
        return match.group(1)

    def write(self, new_version: str, dry_run: bool = False) -> list[str]:
        """Write ``new_version`` into every file of this package.

        Returns:
            The relative paths actually modified.
        """
        touched: list[str] = []
        for rel, style in self.files:
            path = REPO_ROOT / rel
            pattern, template = _PATTERNS[style]
            text = path.read_text(encoding="utf-8")
            new_text, count = pattern.subn(
                template.format(v=new_version), text, count=1
            )
            if not count:
                sys.exit(f"error: no version line to replace in {rel}")
            if new_text != text:
                if not dry_run:
                    path.write_text(new_text, encoding="utf-8")
                touched.append(rel)
        return touched


# Mirrors the *_VERSION_FILE variables in the Makefile. Keep both in sync when
# a package is added — `status` fails loudly if a path disappears.
PACKAGES: list[Package] = [
    Package("ai-parrot",
            [("packages/ai-parrot/src/parrot/version.py", "python")],
            "packages/ai-parrot", aliases=["core", "parrot"]),
    Package("ai-parrot-tools",
            [("packages/ai-parrot-tools/src/parrot_tools/version.py", "python")],
            "packages/ai-parrot-tools", aliases=["tools"]),
    Package("ai-parrot-loaders",
            [("packages/ai-parrot-loaders/src/parrot_loaders/version.py", "python")],
            "packages/ai-parrot-loaders", aliases=["loaders"]),
    Package("ai-parrot-embeddings",
            [("packages/ai-parrot-embeddings/src/parrot/embeddings/version.py", "python")],
            "packages/ai-parrot-embeddings", aliases=["embeddings"]),
    Package("ai-parrot-pipelines",
            [("packages/ai-parrot-pipelines/src/parrot_pipelines/version.py", "python")],
            "packages/ai-parrot-pipelines", aliases=["pipelines"]),
    Package("ai-parrot-visualizations",
            [("packages/ai-parrot-visualizations/src/parrot/outputs/formats/version.py", "python")],
            "packages/ai-parrot-visualizations", aliases=["visualizations", "viz"]),
    Package("ai-parrot-integrations",
            [("packages/ai-parrot-integrations/src/parrot/integrations/version.py", "python")],
            "packages/ai-parrot-integrations", aliases=["integrations"]),
    Package("ai-parrot-server",
            [("packages/ai-parrot-server/src/parrot/server/version.py", "python")],
            "packages/ai-parrot-server", aliases=["server"]),
    Package("ai-parrot-advisors",
            [("packages/ai-parrot-advisors/src/parrot/advisors/version.py", "python")],
            "packages/ai-parrot-advisors", aliases=["advisors"]),
    Package("parrot-formdesigner",
            [("packages/parrot-formdesigner/src/parrot_formdesigner/version.py", "python")],
            "packages/parrot-formdesigner", aliases=["formdesigner"]),
    # navrules keeps the same number in three files; __init__.py is the truth.
    Package("navrules",
            [("packages/navrules/src/navrules/__init__.py", "python"),
             ("packages/navrules/pyproject.toml", "toml"),
             ("packages/navrules/rust/Cargo.toml", "toml")],
            "packages/navrules", aliases=["rules"]),
    # parrot_codec is a maturin/PyO3 crate: pyproject.toml and Cargo.toml
    # repeat the same number and must move together. NOTE: its Cargo.lock is
    # deliberately NOT listed — the "toml" handler rewrites the FIRST
    # `^version = ` line, which in a lockfile is the lockfile *format*
    # version (`version = 4`), not the crate's. Cargo refreshes the lock at
    # build time anyway (maturin does not pass --locked), the same way
    # navrules' lock harmlessly lags its Cargo.toml.
    #
    # Omitting this package is what stranded parrot_codec at 0.1.0 while
    # every sibling advanced: PyPI refuses new files on a release older than
    # 14 days, so once 0.1.0 aged out, each build matrix leg produced wheels
    # that could never upload and the 400 failed the whole deploy step.
    Package("parrot-codec",
            [("packages/ai-parrot/src/parrot/codec-rs/pyproject.toml", "toml"),
             ("packages/ai-parrot/src/parrot/codec-rs/Cargo.toml", "toml")],
            "packages/ai-parrot/src/parrot/codec-rs", aliases=["codec"]),
]

CORE = PACKAGES[0]
_PART_INDEX = {"major": 0, "minor": 1, "patch": 2}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a git/gh command from the repo root, capturing output."""
    return subprocess.run(
        cmd, cwd=REPO_ROOT, text=True, capture_output=True, **kwargs
    )


def bump(version: str, part: str) -> str:
    """Apply a semver bump, zeroing every component to the right."""
    parts = version.split(".")
    idx = _PART_INDEX[part]
    if len(parts) <= idx:
        sys.exit(f"error: version {version!r} has no {part} component")
    try:
        parts[idx] = str(int(parts[idx]) + 1)
    except ValueError:
        sys.exit(f"error: non-numeric {part} component in {version!r}")
    parts[idx + 1:] = ["0"] * len(parts[idx + 1:])
    return ".".join(parts)


def last_tag() -> str | None:
    """Return the most recent tag by creation date, or None if untagged."""
    proc = run(["git", "tag", "--sort=-creatordate"])
    tags = [t for t in proc.stdout.split() if t]
    return tags[0] if tags else None


def commits_since(tag: str | None, path: str) -> int:
    """Count commits touching ``path`` since ``tag`` (all history if None)."""
    rev = f"{tag}..HEAD" if tag else "HEAD"
    proc = run(["git", "rev-list", "--count", rev, "--", path])
    return int(proc.stdout.strip() or 0)


def sync_core_pins(core_version: str, dry_run: bool = False) -> list[str]:
    """Re-pin ``ai-parrot>=<core>`` across every sibling pyproject.

    The satellite distributions depend on the core package by lower bound;
    a core bump that leaves those pins behind ships wheels that resolve to
    an older core than the one they were built against.
    """
    pattern = re.compile(r"ai-parrot>=[\d.]+")
    touched: list[str] = []
    for pyproject in sorted((REPO_ROOT / "packages").glob("*/pyproject.toml")):
        text = pyproject.read_text(encoding="utf-8")
        new_text = pattern.sub(f"ai-parrot>={core_version}", text)
        if new_text != text:
            if not dry_run:
                pyproject.write_text(new_text, encoding="utf-8")
            touched.append(str(pyproject.relative_to(REPO_ROOT)))
    return touched


def resolve(names: list[str]) -> list[Package]:
    """Map user-supplied names/aliases to Package objects."""
    by_name = {}
    for pkg in PACKAGES:
        by_name[pkg.dist] = pkg
        for alias in pkg.aliases:
            by_name[alias] = pkg
    selected: list[Package] = []
    for name in names:
        pkg = by_name.get(name)
        if pkg is None:
            sys.exit(
                f"error: unknown package {name!r}. Known: "
                + ", ".join(p.dist for p in PACKAGES)
            )
        if pkg not in selected:
            selected.append(pkg)
    return selected


def cmd_status(args: argparse.Namespace) -> int:
    """Print the version table without touching anything."""
    tag = last_tag()
    print(f"Last tag: {tag or '(none)'}\n")
    print(f"{'PACKAGE':<26} {'VERSION':<10} {'COMMITS SINCE TAG':>18}")
    print("-" * 56)
    for pkg in PACKAGES:
        missing = [f for f, _ in pkg.files if not (REPO_ROOT / f).exists()]
        if missing:
            print(f"{pkg.dist:<26} {'MISSING':<10} {missing[0]}")
            continue
        n = commits_since(tag, pkg.path)
        marker = "" if n else "  (unchanged)"
        print(f"{pkg.dist:<26} {pkg.current():<10} {n:>18}{marker}")
    print("\nTag for the next release is the ai-parrot (core) version.")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    """Bump versions, optionally commit / tag / push."""
    targets = resolve(args.only) if args.only else list(PACKAGES)
    dry = args.dry_run
    prefix = "[dry-run] " if dry else ""

    plan: list[tuple[Package, str, str]] = []
    for pkg in targets:
        current = pkg.current()
        plan.append((pkg, current, bump(current, args.part)))

    print(f"{prefix}Bumping {args.part} on {len(plan)} package(s):\n")
    touched: list[str] = []
    for pkg, current, new in plan:
        files = pkg.write(new, dry_run=dry)
        touched.extend(files)
        extra = f"  [{len(files)} files]" if len(files) > 1 else ""
        print(f"  {pkg.dist:<26} {current:>9} -> {new}{extra}")

    core_new = next(
        (new for pkg, _, new in plan if pkg is CORE), CORE.current()
    )
    pins = sync_core_pins(core_new, dry_run=dry)
    if pins:
        print(f"\n{prefix}Synced ai-parrot>={core_new} in:")
        for pin in pins:
            print(f"  {pin}")
        touched.extend(pins)

    if dry:
        print(f"\n[dry-run] {len(set(touched))} file(s) would change. "
              "Nothing was written.")
        return 0

    if not args.commit:
        print(f"\n{len(set(touched))} file(s) updated, not committed.")
        print("Review with: git diff -- packages/")
        return 0

    add = run(["git", "add", "--"] + sorted(set(touched)))
    if add.returncode:
        print(add.stderr, file=sys.stderr)
        return add.returncode
    message = args.message or f"chore: release v{core_new}"
    commit = run(["git", "commit", "-m", message])
    if commit.returncode:
        print(commit.stdout + commit.stderr, file=sys.stderr)
        return commit.returncode
    print(f"\nCommitted: {message}")

    if args.tag:
        existing = run(["git", "rev-parse", "-q", "--verify",
                        f"refs/tags/{core_new}"])
        if existing.returncode == 0:
            print(f"error: tag {core_new} already exists — bump again or "
                  "delete the tag first.", file=sys.stderr)
            return 1
        tagged = run(["git", "tag", core_new])
        if tagged.returncode:
            print(tagged.stderr, file=sys.stderr)
            return tagged.returncode
        print(f"Tagged: {core_new}")

    if args.push:
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        cmd = ["git", "push", "origin", branch]
        if args.tag:
            cmd.append("--tags")
        pushed = run(cmd)
        print(pushed.stdout + pushed.stderr, end="")
        if pushed.returncode:
            return pushed.returncode
        print(f"Pushed {branch}" + (" with tags" if args.tag else ""))

    print(f"\nNext: python scripts/release.py gh-release --tag {core_new}")
    print("      (creates the GitHub Release -> triggers the PyPI publish)")
    return 0


def cmd_gh_release(args: argparse.Namespace) -> int:
    """Create the GitHub Release that triggers .github/workflows/release.yml."""
    tag = args.tag or CORE.current()

    if run(["git", "rev-parse", "-q", "--verify",
            f"refs/tags/{tag}"]).returncode != 0:
        print(f"error: tag {tag} does not exist locally. Run "
              "`release.py bump <part> --commit --tag --push` first.",
              file=sys.stderr)
        return 1

    remote = run(["git", "ls-remote", "--tags", "origin", tag])
    if tag not in remote.stdout:
        print(f"error: tag {tag} is not on origin. Push it first: "
              f"git push origin {tag}", file=sys.stderr)
        return 1

    existing = run(["gh", "release", "view", tag])
    if existing.returncode == 0:
        print(f"error: GitHub Release {tag} already exists.", file=sys.stderr)
        return 1

    cmd = ["gh", "release", "create", tag, "--title", tag, "--verify-tag"]
    if args.notes_file:
        cmd += ["--notes-file", args.notes_file]
    elif args.notes:
        cmd += ["--notes", args.notes]
    else:
        cmd.append("--generate-notes")
    if args.draft:
        cmd.append("--draft")

    if args.dry_run:
        print("[dry-run] would run:\n  " + " ".join(cmd))
        return 0

    created = run(cmd)
    print(created.stdout + created.stderr, end="")
    if created.returncode:
        return created.returncode
    print(f"\nGitHub Release {tag} created — release.yml is now building and "
          "publishing to PyPI.")
    print("Watch it: gh run watch")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show the version table.")
    p_status.set_defaults(func=cmd_status)

    p_bump = sub.add_parser("bump", help="Bump package versions.")
    p_bump.add_argument("part", choices=["patch", "minor", "major"])
    p_bump.add_argument("--only", nargs="+", metavar="PKG",
                        help="Bump only these packages (name or alias). "
                             "Default: all.")
    p_bump.add_argument("--commit", action="store_true",
                        help="git add + commit the version files.")
    p_bump.add_argument("--tag", action="store_true",
                        help="Tag the commit with the new core version.")
    p_bump.add_argument("--push", action="store_true",
                        help="Push the branch (and tags, with --tag).")
    p_bump.add_argument("-m", "--message", help="Override the commit message.")
    p_bump.add_argument("--dry-run", action="store_true",
                        help="Show every write without performing it.")
    p_bump.set_defaults(func=cmd_bump)

    p_gh = sub.add_parser(
        "gh-release",
        help="Create the GitHub Release (triggers the PyPI publish).",
    )
    p_gh.add_argument("--tag", help="Tag to release. Default: core version.")
    p_gh.add_argument("--notes", help="Release notes body.")
    p_gh.add_argument("--notes-file", help="Read release notes from a file.")
    p_gh.add_argument("--draft", action="store_true",
                      help="Create as a draft (does NOT trigger the publish).")
    p_gh.add_argument("--dry-run", action="store_true")
    p_gh.set_defaults(func=cmd_gh_release)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
