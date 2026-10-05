# TASK-4090: SDD asset packaging: _assets sync tool, package-data, MANIFEST.in, CI checks

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4072, TASK-4076, TASK-4089
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6: the SDD flow's markdown assets must ship **inside the core wheel** under
`packages/ai-parrot/src/parrot/sdd/_assets/` so `parrot sdd install` (TASK-4091) can deploy
them into any repository without a monorepo checkout. The repo's `.claude/` (+ the codex /
google twins and `sdd/templates/`) stays the **source of truth** (owner decision); the
packaged copies are generated, and `scripts/sdd/check_asset_sync.py` fails CI on any
divergence (FEAT-553 `_rules_data` precedent). Packaging is a **verified build artifact**
(codex S8): `MANIFEST.in` grows the asset tree and CI proves the built wheel contains the
full set.

This task runs after TASK-4089 (the markdown is already rewritten to
`python -m parrot.sdd.scripts.<name>`, so the copies are installable), and is serialized after
TASK-4072 (`pyproject.toml`) and TASK-4076 (`ci.yml`).

---

## Scope

- Create the stdlib-only `scripts/sdd/check_asset_sync.py` (`--write` regenerates `_assets/` +
  `manifest.json`; default / `--check` exits 1 listing diverging, missing and extra files;
  `--wheel <path>` verifies a built wheel contains `manifest.json` and every manifest entry).
- Generate `packages/ai-parrot/src/parrot/sdd/_assets/` (77 files + `manifest.json`) with `--write`.
- Declare the asset tree in `[tool.setuptools.package-data]` and in `MANIFEST.in`.
- Add the sync-check step and a wheel-content job to `.github/workflows/ci.yml`.
- Write `tests/sdd_scripts/test_check_asset_sync.py`.

**NOT in scope**:
- `parrot/sdd/installer.py`, `parrot/sdd/cli.py`, lazy `sdd` registration (TASK-4091).
- Rewriting markdown references (TASK-4089 — already done when this starts).
- `parrot/sdd/__init__.py` (TASK-4070) and `parrot/sdd/scripts/` (TASK-4085..4088).
- Wiring the SDD hook into `.claude/settings.json` of a target repo — this task only packages
  `.claude/hooks/sdd-worker-format.sh`; registration is TASK-4091's concern.
- `release.yml` / `[tool.cibuildwheel]` (the M8 wheel-matrix task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_asset_sync.py` | CREATE | Stdlib sync/check/wheel-verify tool; owns the source→asset mapping |
| `packages/ai-parrot/src/parrot/sdd/_assets/` | CREATE | Generated asset tree (77 files) — produced ONLY by `check_asset_sync.py --write` |
| `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` | CREATE | Generated manifest (`schema_version: 1`, one entry per asset) |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `"parrot.sdd"` package-data with explicit per-subdir patterns |
| `packages/ai-parrot/MANIFEST.in` | MODIFY | `graft src/parrot/sdd/_assets` so the sdist (and wheel-from-sdist) carry the tree |
| `.github/workflows/ci.yml` | MODIFY | Asset-sync check step + `sdd-assets-wheel` job (build sdist→wheel, verify contents) |
| `tests/sdd_scripts/test_check_asset_sync.py` | CREATE | Unit tests for write/check/extra/missing/diverge/wheel + package-data coverage |

The source → `_assets/` → target mapping is decided in Implementation Notes › Asset mapping.


---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# check_asset_sync.py is STDLIB-ONLY (runs in CI with a bare `python`, before/without uv sync):
import argparse, json, shutil, subprocess, sys, zipfile
from dataclasses import dataclass
from pathlib import Path
# tests:
import pytest
import tomllib                                   # stdlib (Python >= 3.11; core requires-python is >=3.11)
from scripts.sdd import check_asset_sync         # pattern verified: tests/sdd_scripts/test_check_task_state.py:6
                                                 # (`from scripts.sdd.check_task_state import ...`; testpaths=["tests"], pyproject.toml:240)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml
[build-system] requires = ["setuptools>=77.0.0", "Cython==3.0.11", "wheel>=0.44.0"]   # lines 1-7 (local setuptools 84.0.0)
[tool.setuptools.packages.find] where = ["src"]; include = ["parrot*"]; namespaces = true   # lines 951-954
[tool.setuptools.package-data]                                                         # line 956
parrot = ["py.typed", "templates/*.tpl", "**/*.pyx", "**/*.pxd"]                       # line 957 (`**` already used)
"parrot.flows" = ["_rules_data/*.md"]                                                  # line 969 — anchor, grep -c == 1
"parrot.flows.dev_loop" = ["_subagent_data/*.md"]                                      # line 970

# packages/ai-parrot/MANIFEST.in (2 lines today)
recursive-include src *.pyx *.pxd      # line 1
include setup.py                       # line 2 — anchor, grep -c == 1

# packages/ai-parrot/setup.py — two Cython extensions (parrot.utils.types C++, parrot.utils.parsers.toml C), lines 13-24

# .github/workflows/ci.yml
#   job `lint-and-registry:` line 10 (ubuntu-latest, Python 3.12, astral-sh/setup-uv@v10.2.0, `uv sync --all-packages`)
#   step "Check stalled SDD task files" lines 104-107; last line:
            --baseline scripts/sdd/.task_state_baseline.json     # line 107 — anchor, grep -c == 1
#   job `install-guide:` line 113 (comment block for it starts line 109)
# .github/workflows/release.yml:100-102 — `uv build --out-dir ../../dist` precedent

# scripts/generate_tool_registry.py — `--check` CI precedent: "CI mode: exit 1 if stale" (line 11, 362, 447-449)
# packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py — FEAT-553 precedent: byte parity via
#   `read_bytes() == read_bytes()` (lines 22-39); there is NO sync script for _rules_data (test-only)
```

### Does NOT Exist
- ~~`scripts/sdd/check_asset_sync.py`, `parrot/sdd/_assets/`~~ — new in this task.
- ~~a sync/regeneration tool for `_rules_data/` or `_subagent_data/`~~ — the FEAT-553 precedent
  is parity tests only; this task introduces the first `--write` generator (mirrors
  `generate_tool_registry.py --check`).
- ~~any wheel-content check in `ci.yml`~~ — `ci.yml` builds no wheel today (`grep -n "uv build" ci.yml` → none).
- ~~`MANIFEST.in` data entries~~ — Cython sources + `setup.py` only.
- ~~`sdd/templates/research_plan.schema.json` in git~~ — on disk but untracked; never package it.
- ~~`_assets/.claude/...` dot-dir layout~~ — rejected (see mapping rationale).

---

## Complexity Contract

> **MANDATORY.** Declares the measurable targets and contract symbols used for
> deterministic complexity routing (FEAT-561) before any coder is dispatched.
> This is a declaration, not a hand-authored score — the evaluator computes
> classification from measured evidence, never from this section's prose.

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/check_asset_sync.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/manifest.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/MANIFEST.in", "action": "MODIFY"},
    {"path": ".github/workflows/ci.yml", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_check_asset_sync.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py#test_claude_rules_twin_is_identical"
  ]
}
```

---

## Implementation Notes

### Asset mapping (DECIDED — read from what each host actually loads)

Evidence: `sdd/WORKFLOW.md:404-405` — *Codex*: "Repository skills in `.agents/skills/sdd-*` …
and agent `.codex/agents/sdd-worker.toml`"; *Antigravity (Google Gemini)*: "Slash command
workflows in `.agent/workflows/sdd-*.md` …, skills in `.agents/skills/sdd-*`, and subagents in
`.agents/agents/`". Both the codex and google wiki installers render project conventions from
`.agent/rules/` (`knowledge/wiki/codex/assets.py:143`, `knowledge/wiki/google/assets.py:139`).

| Host(s) | Repo source = install target (git-tracked only) | Count | `_assets/` source |
|---|---|---|---|
| claude | `.claude/commands/sdd-*.md` | 14 | `claude/commands/` |
| claude | `.claude/agents/sdd-*.md` | 9 | `claude/agents/` |
| claude | `.claude/hooks/sdd-worker-format.sh` | 1 | `claude/hooks/` |
| claude | `.claude/rules/codebase-conventions.md`, `.claude/rules/worktree-management.md` | 2 | `claude/rules/` |
| codex, google | `.agents/skills/sdd-*/SKILL.md` | 14 | `agents/skills/<n>/` |
| codex, google | `.agent/rules/codebase-conventions.md` | 1 | `agent/rules/` |
| codex | `.codex/agents/sdd-worker.toml` | 1 | `codex/agents/` |
| google | `.agent/workflows/sdd-*.md` | 14 | `agent/workflows/` |
| google | `.agents/agents/sdd-*/agent.md` | 8 | `agents/agents/<n>/` |
| claude, codex, google | `sdd/templates/*` (git-tracked: 12 — `research_plan.schema.json` is untracked and excluded) | 12 | `sdd/sdd_templates/` |
| claude, codex, google | `sdd/WORKFLOW.md` | 1 | `sdd/WORKFLOW.md` |

**Total: 77 assets.** Excluded on purpose: `.agent/agents/sdd-*/agent.md` (no host doc names
`.agent/agents/` — Antigravity's subagent dir is `.agents/agents/`), `.agent/skills/worktree-management/`
(not an SDD-named skill on any host list), `.claude/agents/qa-runner.md` (not `sdd-*`).

**Why `_assets/` does NOT mirror dot-dirs** (verified, not assumed): setuptools 84's
`setuptools.glob` *does* match dot-dirs (checked: `_assets/**/*.md` returned
`_assets/.claude/commands/a.md`), so packaging is not the blocker. The blockers are:
(1) a nested `packages/ai-parrot/src/parrot/sdd/_assets/.claude/` would be picked up by Claude
Code's nested-directory discovery when working under `packages/ai-parrot/`, loading every SDD
command/agent/rule twice; (2) `.gitignore:273` (`templates/`) ignores any `templates/` dir
(`git check-ignore` confirms `_assets/sdd/templates/spec.md` is ignored). Hence the explicit
prefix map `.claude/→claude/`, `.agents/→agents/`, `.agent/→agent/`, `.codex/→codex/`,
`sdd/templates/→sdd/sdd_templates/`, `sdd/→sdd/`, and every manifest entry carries its
explicit `target`. Because the target IS the repo source path, the sync check is driven by
the manifest alone.

### Pattern to Follow
- `scripts/generate_tool_registry.py` — a repo script with a write mode and a `--check` CI
  mode that exits 1 when the generated artifact is stale.
- `test_rules_parity.py` — byte comparison (`read_bytes()`), never text normalization.

### Key Constraints
- **Stdlib only** in `check_asset_sync.py` (no pydantic, no parrot import): the wheel job runs
  it with a bare `python` before any sync, and it must never import the package it verifies.
- **Bytes, not text**: copy with `shutil.copyfile` and compare `read_bytes()`; no newline or
  encoding normalization (the installer's "identical → skip" rule depends on exact bytes).
- **Git-tracked sources only** (`git ls-files`): an untracked local file must never leak into
  the wheel, and CI and dev machines must produce the same manifest.
- **Deterministic manifest**: entries sorted by `target`, `hosts` in the fixed order
  `claude, codex, google`, `json.dumps(..., indent=2) + "\n"`.
- Executable bit: `.sh` assets keep `0o755` in the tree (`shutil.copymode`); TASK-4091 must
  still `chmod` on install because wheels do not reliably preserve modes.
- Never hand-edit `_assets/`: it is regenerated wholesale by `--write` (extra files removed).

### References in Codebase
- `sdd/WORKFLOW.md:404-405` — per-host asset locations (mapping evidence).
- `.gitignore:273` — global `templates/` ignore (why `sdd_templates/`).
- `.github/workflows/release.yml:100-102` — `uv build` precedent.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `scripts/sdd/check_asset_sync.py` — *why*: it owns the mapping; the tree is generated from it.
2. Run `python scripts/sdd/check_asset_sync.py --write`, then `--check` (expect exit 0, 77 assets)
   — *why*: `_assets/` and `manifest.json` must never be hand-written.
3. `git add -f` is NOT needed (no ignored path in the tree) — verify with
   `git status --porcelain -uall packages/ai-parrot/src/parrot/sdd/_assets | wc -l` == 78 — *why*: a silently
   ignored asset would ship nowhere.
4. Add the package-data block and the `MANIFEST.in` graft — *why*: wheel and sdist must both carry the tree.
5. Locally: `uv build --package ai-parrot --out-dir /tmp/<scratch>/dist` then
   `python scripts/sdd/check_asset_sync.py --wheel <wheel>` — *why*: proves the CI job before pushing.
6. Add the CI step + job; write the tests; run the Validation Commands.

### `scripts/sdd/check_asset_sync.py` (CREATE)
```python
"""Keep ``parrot/sdd/_assets/`` byte-identical to its repo sources (FEAT-633 M6).

Modes: ``--write`` regenerate _assets/ + manifest.json; ``--check`` (default) exit 1 on divergence;
``--wheel <whl>`` verify a built wheel carries every manifest entry. Stdlib only — never import parrot.
"""

from __future__ import annotations

import argparse
import json
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
ASSET_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".claude/commands/sdd-*.md", ("claude",)),
    (".claude/agents/sdd-*.md", ("claude",)),
    (".claude/hooks/sdd-worker-format.sh", ("claude",)),
    (".claude/rules/codebase-conventions.md", ("claude",)),
    (".claude/rules/worktree-management.md", ("claude",)),
    (".agents/skills/sdd-*/SKILL.md", ("codex", "google")),
    (".agent/rules/codebase-conventions.md", ("codex", "google")),
    (".codex/agents/sdd-worker.toml", ("codex",)),
    (".agent/workflows/sdd-*.md", ("google",)),
    (".agents/agents/sdd-*/agent.md", ("google",)),
    ("sdd/templates/*", HOST_ORDER),
    ("sdd/WORKFLOW.md", HOST_ORDER),
)
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

    def as_json(self) -> dict[str, object]:
        """Manifest form (key order fixed: source, target, hosts)."""
        return {"source": self.source, "target": self.target, "hosts": list(self.hosts)}


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
    # FILL IN: one `git -C root ls-files -z -- <pathspecs>` call, glob-match each tracked path to the
    #          FIRST matching ASSET_SOURCES row (fnmatch on the posix path), merge hosts if a target
    #          matches twice (keep HOST_ORDER) — bounded by "git-tracked only" + deterministic order
    raise NotImplementedError


def build_manifest(entries: list[AssetEntry]) -> str:
    """Serialize the manifest exactly as committed (sorted, indent=2, trailing newline)."""
    payload = {"schema_version": SCHEMA_VERSION, "assets": [e.as_json() for e in entries]}
    return json.dumps(payload, indent=2) + "\n"


def find_problems(root: Path, assets_dir: Path) -> list[str]:
    """Compare ``assets_dir`` with the repo sources; return human-readable problems (empty = in sync).

    Problem kinds: ``missing`` (expected asset absent), ``diverged`` (bytes differ from the repo
    source), ``extra`` (file under ``assets_dir`` not in the expected set), ``manifest`` (committed
    ``manifest.json`` differs from ``build_manifest``).
    """
    # FILL IN: byte comparison per entry (read_bytes), rglob for extras (ignore manifest.json),
    #          manifest text equality — bounded by AC "lists diverging/missing/extra files"
    raise NotImplementedError


def write_assets(root: Path, assets_dir: Path) -> list[AssetEntry]:
    """Regenerate ``assets_dir`` from scratch (copy bytes + mode) and write ``manifest.json``."""
    # FILL IN: remove files under assets_dir not in the expected set (only inside assets_dir!), copy each
    #          source with shutil.copyfile + shutil.copymode, write build_manifest() — bounded by idempotency
    #          (a second --write produces no git diff)
    raise NotImplementedError


def check_wheel(wheel: Path) -> list[str]:
    """Verify ``wheel`` contains ``parrot/sdd/_assets/manifest.json`` and every entry it lists."""
    # FILL IN: zipfile.ZipFile(wheel).namelist(); read the manifest FROM THE WHEEL (not the checkout);
    #          one "missing in wheel: <WHEEL_PREFIX><source>" per absent entry; flag an empty asset list —
    #          bounded by codex S8 (prove the shipped artifact) and test_check_wheel_reports_missing_entry
    raise NotImplementedError


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
```
**Why this shape**: the mapping lives in one place (`ASSET_SOURCES` + `PREFIX_MAP`); `manifest.json`
is a pure function of git-tracked sources, so `--check` is a regeneration diff. `check_wheel`
reads the manifest *from the wheel* so it proves the shipped artifact, not the checkout (codex S8).
`sys.stdout/stderr.write` instead of `print` (stdlib script convention in the brief).

### `packages/ai-parrot/src/parrot/sdd/_assets/` (CREATE) and `_assets/manifest.json` (CREATE)
```text
# GENERATED — never hand-write. Produced by: python scripts/sdd/check_asset_sync.py --write
_assets/
  manifest.json                      {"schema_version": 1, "assets": [{"source": "claude/commands/sdd-spec.md",
                                       "target": ".claude/commands/sdd-spec.md", "hosts": ["claude"]}, ...]}  (77 entries)
  claude/{commands,agents,hooks,rules}/...
  agents/skills/sdd-*/SKILL.md       agents/agents/sdd-*/agent.md
  agent/workflows/sdd-*.md           agent/rules/codebase-conventions.md
  codex/agents/sdd-worker.toml
  sdd/sdd_templates/*                sdd/WORKFLOW.md
```
**Why**: the manifest format is fixed by the FEAT-633 brief; TASK-4091 reads it via `importlib.resources`.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot.flows" = \["_rules_data/\*.md"\]' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `"parrot.flows" = ["_rules_data/*.md"]` (verified: packages/ai-parrot/pyproject.toml:969)
# FEAT-633: packaged SDD flow assets deployed by `parrot sdd install`, read via importlib.resources.
# Explicit per-subdir patterns (one per _assets/ subtree); test_check_asset_sync asserts they cover
# every manifest entry, so a new subtree fails CI instead of silently missing from the wheel.
"parrot.sdd" = [
    "_assets/manifest.json",
    "_assets/claude/commands/*.md",
    "_assets/claude/agents/*.md",
    "_assets/claude/hooks/*.sh",
    "_assets/claude/rules/*.md",
    "_assets/agents/skills/*/SKILL.md",
    "_assets/agents/agents/*/agent.md",
    "_assets/agent/workflows/*.md",
    "_assets/agent/rules/*.md",
    "_assets/codex/agents/*.toml",
    "_assets/sdd/sdd_templates/*",
    "_assets/sdd/WORKFLOW.md",
]
```
**Why**: setuptools here (≥77, local 84) supports `**`, but explicit globs keep the wheel's
content reviewable and the coverage test makes drift loud. Insert after line 969, not after
the `parrot.flows.dev_flow` comment block, so TASK-4072's `[project.scripts]` edit (:199) never collides.

### `packages/ai-parrot/MANIFEST.in` (MODIFY)
```text
# occurrences: 1 (verified: grep -c 'include setup.py' packages/ai-parrot/MANIFEST.in)
# AFTER — insert below `include setup.py` (verified: packages/ai-parrot/MANIFEST.in:2)
graft src/parrot/sdd/_assets
```
**Why**: `uv build` makes the wheel FROM the sdist; without the graft the sdist (and thus the
wheel) could lose the tree (spec §3 M6, codex S8).

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '            --baseline scripts/sdd/.task_state_baseline.json' .github/workflows/ci.yml)
# AFTER — insert below `            --baseline scripts/sdd/.task_state_baseline.json` (verified: .github/workflows/ci.yml:107)

      # FEAT-633: parrot/sdd/_assets/ is a generated copy of the SDD sources (.claude/, .agents/,
      # .agent/, .codex/, sdd/); fail on any byte divergence. Fix: python scripts/sdd/check_asset_sync.py --write
      - name: Check packaged SDD assets are in sync (FEAT-633)
        run: python scripts/sdd/check_asset_sync.py --check

  # FEAT-633 (codex S8): prove the BUILT wheel carries the SDD asset tree. `uv build` builds the
  # sdist first and the wheel from it, so this also proves MANIFEST.in. g++ is preinstalled on
  # ubuntu-latest for the two Cython extensions; no uv sync / test deps needed.
  sdd-assets-wheel:
    name: SDD assets ship in the ai-parrot wheel
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v10.2.0
        with:
          version: "latest"

      - name: Build ai-parrot sdist + wheel
        run: uv build --package ai-parrot --out-dir dist

      - name: Verify wheel contains manifest.json and every manifest entry
        run: python scripts/sdd/check_asset_sync.py --wheel dist/ai_parrot-*.whl
```
**Why**: the sync step is stdlib, so it needs no environment; the wheel job is the cheapest
reliable proof — one build (sdist→wheel, ~2 min incl. Cython) and a zip listing.
Rejected cheaper options: `setup.py build_py` (skips sdist/MANIFEST.in, not the shipped artifact);
reusing `release.yml` (tag-only, codex S8 wants PR-time proof).

### `tests/sdd_scripts/test_check_asset_sync.py` (CREATE)
```python
"""Tests for scripts/sdd/check_asset_sync.py (FEAT-633 M6, spec §4 test_asset_sync_check)."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts.sdd import check_asset_sync as cas

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A git repo with one source per host family, committed (sources must be git-tracked)."""
    for rel in (".claude/commands/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md",
                ".agent/workflows/sdd-spec.md", "sdd/templates/task.md", "sdd/WORKFLOW.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, *flags: str) -> int:
    return cas.main([*flags, "--root", str(repo), "--assets-dir", str(repo / "assets")])


def test_write_then_check_is_clean(mini_repo: Path) -> None:
    assert _run(mini_repo, "--write") == 0
    assert _run(mini_repo, "--check") == 0
    manifest = json.loads((mini_repo / "assets" / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert {"source": "sdd/sdd_templates/task.md", "target": "sdd/templates/task.md",
            "hosts": ["claude", "codex", "google"]} in manifest["assets"]


def test_divergence_missing_and_extra_fail(mini_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(mini_repo, "--write")
    (mini_repo / ".claude/commands/sdd-spec.md").write_text("changed\n")      # diverged
    (mini_repo / "assets/agent/workflows/sdd-spec.md").unlink()                 # missing
    (mini_repo / "assets/claude/stray.md").write_text("x")                       # extra
    assert _run(mini_repo, "--check") == 1
    err = capsys.readouterr().err
    # FILL IN: assert each of the three paths is named with its problem kind — bounded by find_problems' wording


def test_untracked_source_is_not_packaged(mini_repo: Path) -> None:
    (mini_repo / "sdd/templates/untracked.json").write_text("{}")
    _run(mini_repo, "--write")
    assert not (mini_repo / "assets/sdd/sdd_templates/untracked.json").exists()


def test_check_wheel_reports_missing_entry(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "claude/commands/a.md", "target": ".claude/commands/a.md", "hosts": ["claude"]}]}
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
    assert cas.check_wheel(wheel) == [f"missing in wheel: {cas.WHEEL_PREFIX}claude/commands/a.md"]


def test_repo_assets_in_sync() -> None:
    """The committed _assets/ tree matches the monorepo sources (the CI gate, as a test)."""
    assert cas.main(["--check", "--root", str(_REPO_ROOT)]) == 0


def test_package_data_covers_every_manifest_entry() -> None:
    """Every manifest source matches one `"parrot.sdd"` package-data glob in pyproject.toml."""
    pyproject = tomllib.loads((_REPO_ROOT / "packages/ai-parrot/pyproject.toml").read_text())
    patterns = pyproject["tool"]["setuptools"]["package-data"]["parrot.sdd"]
    pkg_dir = _REPO_ROOT / "packages/ai-parrot/src/parrot/sdd"
    covered = {p.relative_to(pkg_dir).as_posix() for pat in patterns for p in pkg_dir.glob(pat) if p.is_file()}
    manifest = json.loads((pkg_dir / "_assets/manifest.json").read_text())
    missing = [e["source"] for e in manifest["assets"] if f"_assets/{e['source']}" not in covered]
    assert not missing, missing
```
**Why**: covers spec §4 `test_asset_sync_check` (divergence fails) plus the two packaging
guarantees this task adds (git-tracked only, package-data coverage).

### FILL IN checklist
- [ ] `check_asset_sync.py::expected_entries` — git ls-files + first-match glob; bounded by "git-tracked only", deterministic order.
- [ ] `check_asset_sync.py::find_problems` — byte compare, extras, manifest text; bounded by AC-2.
- [ ] `check_asset_sync.py::write_assets` — wholesale regeneration, idempotent; bounded by AC-1.
- [ ] `test_divergence_missing_and_extra_fail` — final stderr assertions.

---

## Acceptance Criteria

- [ ] `python scripts/sdd/check_asset_sync.py --write` produces `_assets/` with 77 assets +
      `manifest.json`; a second `--write` leaves `git status` clean (idempotent).
- [ ] `python scripts/sdd/check_asset_sync.py` (default `--check`) exits 0 on the repo and exits 1
      naming every diverging / missing / extra file otherwise (spec §5: "`check_asset_sync.py` gates
      CI on `.claude/` ↔ `_assets/` divergence").
- [ ] `manifest.json` matches the brief's format (`schema_version: 1`, `source`/`target`/`hosts`), sorted by target.
- [ ] `uv build --package ai-parrot` produces a wheel for which `check_asset_sync.py --wheel` exits 0
      (codex S8 — installed runtime never depends on a monorepo checkout).
- [ ] `ci.yml` runs the sync check in `lint-and-registry` and the new `sdd-assets-wheel` job.
- [ ] No new runtime dependency; `check_asset_sync.py` imports stdlib only.
- [ ] `ruff check scripts/sdd/check_asset_sync.py tests/sdd_scripts/test_check_asset_sync.py` passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# tests/sdd_scripts/test_check_asset_sync.py — see the CREATE block above:
#   test_write_then_check_is_clean                 write → check == 0; manifest shape
#   test_divergence_missing_and_extra_fail         spec §4 test_asset_sync_check
#   test_untracked_source_is_not_packaged          git-tracked only
#   test_check_wheel_reports_missing_entry         wheel verifier
#   test_repo_assets_in_sync                       committed tree == sources
#   test_package_data_covers_every_manifest_entry  pyproject globs ⊇ manifest
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4090 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
