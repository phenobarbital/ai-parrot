"""Keep ``parrot/sdd/_assets/`` byte-identical to its repo sources (FEAT-633 M6).

Modes: ``--write`` regenerate _assets/ + manifest.json; ``--check`` (default) exit 1 on divergence;
``--wheel <whl>`` verify a built wheel carries every manifest entry. ``--check`` and ``--wheel`` also
report any shipped line naming a monorepo source path (C16) or other monorepo-specific text (C22).
Stdlib only — never import parrot.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ASSETS_DIR = Path("packages/ai-parrot/src/parrot/sdd/_assets")
MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = 1
WHEEL_PREFIX = "parrot/sdd/_assets/"
HOST_ORDER: tuple[str, ...] = ("claude", "codex", "google")

#: (git pathspec glob relative to the repo root, hosts) — see the task's mapping table.
#: NEVER list `codebase-conventions.md` here (C10: ai-parrot's rulebook does not ship).
ASSET_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".claude/commands/sdd-*.md", ("claude",)),
    (".claude/agents/sdd-*.md", ("claude",)),
    (".claude/hooks/sdd-worker-format.sh", ("claude",)),
    (".claude/rules/worktree-management.md", ("claude",)),
    (".claude/skills/second-opinion/SKILL.md", ("claude",)),          # C9 — claude only; no codex/google twin
    (".agents/skills/sdd-*/SKILL.md", ("codex", "google")),
    (".codex/agents/sdd-worker.toml", ("codex",)),
    (".agent/workflows/sdd-*.md", ("google",)),
    (".agents/agents/sdd-*/agent.md", ("google",)),
    ("sdd/templates/*", HOST_ORDER),
    ("sdd/WORKFLOW.md", HOST_ORDER),
    ("sdd/CONVENTIONS.md", HOST_ORDER),                               # C10 — seed, see SEED_TARGETS
)
#: rev 0.5 C22 — `/sdd-insight` does not ship on any host (it depends on unshipped `reference/sdd-insight/`
#: and `.claude/workflows/sdd-insight.js`); these targets match the globs above and are dropped.
EXCLUDED_TARGETS: frozenset[str] = frozenset({
    ".claude/commands/sdd-insight.md", ".agents/skills/sdd-insight/SKILL.md", ".agent/workflows/sdd-insight.md",
})
#: Targets written once by the installer and never overwritten/removed (manifest `"seed": true`).
SEED_TARGETS: frozenset[str] = frozenset({"sdd/CONVENTIONS.md"})
#: Wheel paths (relative to WHEEL_PREFIX) that must never ship — C11d. fnmatch on the posix path.
DENY_PATTERNS: tuple[str, ...] = (
    "sdd/references/*", "sdd/state/*", "sdd/ledger/*", ".parrot/*", "*/.parrot/*",
    "*.jsonl", "*.db", "*.id_ledger*", "sdd/tasks/*",
)
#: C16 — a monorepo source path in shipped content (`packages/…`, `scripts/…`, `$CLAUDE_PROJECT_DIR/…`);
#: the same pattern as TASK-4089's `test_no_repo_script_refs._MONOREPO_PATH`.
MONOREPO_PATH_RE = re.compile(r"(?<![\w./-])(?:packages|scripts)/|\$\{?CLAUDE_PROJECT_DIR\b[^/\s]*/")
#: rev 0.5 C22 — the second pattern both C16 gates add (same as TASK-4089's `_MONOREPO_TEXT`); [rev 0.5 D3] it is what
#: makes the four `tests/sdd_scripts/…` references count as monorepo paths.
MONOREPO_TEXT_RE = re.compile(r"tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/")
#: (target, stripped line) pairs exempted from both patterns — C22 category D (= D3 (d)): the ONLY entry, the same single
#: entry as TASK-4089's `_C16_ALLOWLIST` (`${CLAUDE_PROJECT_DIR:-}/.venv/bin` is the target repo's own venv, the
#: PATH-first fallback). Add nothing else; D3 (c) prose is rewritten by TASK-4089, never allowlisted.
MONOREPO_PATH_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    (".claude/hooks/sdd-worker-format.sh", 'for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \\'),
})
#: target prefix -> asset prefix. No dot-dirs (nested .claude/ discovery) and no `templates/` (.gitignore:273).
PREFIX_MAP: tuple[tuple[str, str], ...] = (
    (".claude/", "claude/"),
    (".agents/", "agents/"),
    (".agent/", "agent/"),
    (".codex/", "codex/"),
    ("sdd/templates/", "sdd/sdd_templates/"),
    ("sdd/", "sdd/"),
)


@dataclass(frozen=True)
class AssetEntry:
    """One packaged asset: where it lives under ``_assets/`` and where it installs."""

    source: str
    target: str
    hosts: tuple[str, ...]
    seed: bool = False

    def as_json(self) -> dict[str, object]:
        """Manifest form (key order fixed: source, target, hosts[, seed]); ``seed`` only when true."""
        payload: dict[str, object] = {"source": self.source, "target": self.target, "hosts": list(self.hosts)}
        if self.seed:
            payload["seed"] = True
        return payload


def asset_source_for(target: str) -> str:
    """Map a repo-relative install target to its path under ``_assets/``.

    Raises:
        ValueError: ``target`` matches no prefix in ``PREFIX_MAP``.
    """
    for prefix, replacement in PREFIX_MAP:
        if target.startswith(prefix):
            return replacement + target[len(prefix):]
    raise ValueError(f"no _assets/ prefix mapping for {target!r}")


def expected_entries(root: Path) -> list[AssetEntry]:
    """Resolve ``ASSET_SOURCES`` against the git-tracked files of ``root``, sorted by target."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode("utf-8")
    tracked = sorted(p for p in out.split("\0") if p)
    entries: dict[str, set[str]] = {}
    for path in tracked:
        if path in EXCLUDED_TARGETS:
            continue
        for pattern, hosts in ASSET_SOURCES:
            if fnmatch.fnmatchcase(path, pattern):
                entries.setdefault(path, set()).update(hosts)
                break
    return [
        AssetEntry(
            source=asset_source_for(target),
            target=target,
            hosts=tuple(h for h in HOST_ORDER if h in entries[target]),
            seed=target in SEED_TARGETS,
        )
        for target in sorted(entries)
    ]


def build_manifest(entries: list[AssetEntry]) -> str:
    """Serialize the manifest exactly as committed (sorted, indent=2, trailing newline)."""
    payload = {"schema_version": SCHEMA_VERSION, "assets": [e.as_json() for e in entries]}
    return json.dumps(payload, indent=2) + "\n"


def monorepo_path_problems(target: str, data: bytes) -> list[str]:
    """C16 + C22: one ``monorepo-path: <target>:<line>: <text>`` per shipped line matching ``MONOREPO_PATH_RE``
    or ``MONOREPO_TEXT_RE``."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if (target, line.strip()) in MONOREPO_PATH_ALLOWLIST:
            continue
        if MONOREPO_PATH_RE.search(line) or MONOREPO_TEXT_RE.search(line):
            problems.append(f"monorepo-path: {target}:{number}: {line}")
    return problems


def find_problems(root: Path, assets_dir: Path) -> list[str]:
    """Compare ``assets_dir`` with the repo sources; return human-readable problems (empty = in sync).

    Problem kinds: ``missing`` (expected asset absent), ``diverged`` (bytes differ from the repo
    source), ``extra`` (file under ``assets_dir`` not in the expected set), ``manifest`` (committed
    ``manifest.json`` differs from ``build_manifest``), ``monorepo-path`` (C16/C22, a shipped source line
    names a monorepo source path or other monorepo-specific text).
    """
    problems: list[str] = []
    entries = expected_entries(root)
    expected: set[Path] = set()
    for entry in entries:
        asset = assets_dir / entry.source
        expected.add(asset)
        source_bytes = (root / entry.target).read_bytes()
        if not asset.is_file():
            problems.append(f"missing: {entry.source} (source {entry.target})")
        elif asset.read_bytes() != source_bytes:
            problems.append(f"diverged: {entry.source} differs from {entry.target}")
        problems.extend(monorepo_path_problems(entry.target, source_bytes))
    if assets_dir.is_dir():
        for path in sorted(assets_dir.rglob("*")):
            if path.is_file() and path not in expected and path.name != MANIFEST_NAME:
                problems.append(f"extra: {path.relative_to(assets_dir).as_posix()}")
    manifest = assets_dir / MANIFEST_NAME
    if not manifest.is_file() or manifest.read_text(encoding="utf-8") != build_manifest(entries):
        problems.append(f"manifest: {MANIFEST_NAME} is missing or stale")
    return problems


def write_assets(root: Path, assets_dir: Path) -> list[AssetEntry]:
    """Regenerate ``assets_dir`` from scratch (copy bytes + mode) and write ``manifest.json``."""
    entries = expected_entries(root)
    expected = {assets_dir / e.source for e in entries}
    if assets_dir.is_dir():
        for path in sorted(assets_dir.rglob("*"), reverse=True):
            if path.is_file() and path not in expected:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    for entry in entries:
        dest = assets_dir / entry.source
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / entry.target, dest)
        shutil.copymode(root / entry.target, dest)
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / MANIFEST_NAME).write_text(build_manifest(entries), encoding="utf-8")
    return entries


def check_wheel(wheel: Path) -> list[str]:
    """Verify ``wheel`` contains ``parrot/sdd/_assets/manifest.json`` and every entry it lists,
    nothing under ``WHEEL_PREFIX`` that matches ``DENY_PATTERNS`` (C11d), and no monorepo source path
    in any entry it ships (C16)."""
    problems: list[str] = []
    manifest_name = WHEEL_PREFIX + MANIFEST_NAME
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        if manifest_name not in names:
            return [f"missing in wheel: {manifest_name}"]
        assets = json.loads(zf.read(manifest_name).decode("utf-8")).get("assets", [])
        if not assets:
            problems.append("manifest lists no assets")
        for entry in assets:
            name = WHEEL_PREFIX + entry["source"]
            if name not in names:
                problems.append(f"missing in wheel: {name}")
        for name in sorted(names):
            if not name.startswith(WHEEL_PREFIX) or name.endswith("/"):
                continue
            rel = name[len(WHEEL_PREFIX):]
            if any(fnmatch.fnmatchcase(rel, pat) for pat in DENY_PATTERNS):
                problems.append(f"forbidden in wheel: {name}")
        for entry in assets:
            name = WHEEL_PREFIX + entry["source"]
            if name in names:
                problems.extend(monorepo_path_problems(entry["target"], zf.read(name)))
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code (0 ok, 1 problems found)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate _assets/ and manifest.json")
    mode.add_argument("--check", action="store_true", help="exit 1 on divergence (default)")
    mode.add_argument("--wheel", type=Path, help="verify a built wheel carries every manifest entry")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root (default: cwd)")
    parser.add_argument("--assets-dir", type=Path, default=None, help="override (tests); default <root>/" + str(ASSETS_DIR))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    assets_dir = args.assets_dir or root / ASSETS_DIR
    if args.wheel:
        problems = check_wheel(args.wheel)
    elif args.write:
        entries = write_assets(root, assets_dir)
        sys.stdout.write(f"wrote {len(entries)} assets + {MANIFEST_NAME} to {assets_dir}\n")
        return 0
    else:
        problems = find_problems(root, assets_dir)
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    if problems:
        sys.stderr.write("SDD assets out of sync — run: python scripts/sdd/check_asset_sync.py --write\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
