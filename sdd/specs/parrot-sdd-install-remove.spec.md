---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, installer, cli, cleanup]
---

# Feature Specification: `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files

**Feature ID**: FEAT-795
**Date**: 2026-11-03
**Author**: Jesus Lara
**Status**: draft
**Target version**: 2.0.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot sdd install` now replaces every file the packaged manifest ships, and `parrot sdd uninstall` removes
them (PR #1940). Both commands only look at the **current** manifest, though. Files that earlier processes put in
a repository and that the manifest no longer ships stay behind forever:

- files copied **by hand** before the installer existed;
- files from an **older layout** that moved;
- files a past `parrot sdd install` recorded in `sdd/.sdd-installed.json` but a newer release dropped.

Evidence from the user's repositories (2026-11-03):

| Repo | Orphans found (not in the current 84-entry manifest) |
|---|---|
| querysource | `scripts/sdd/*.py` + `__pycache__/` (25+ files), `.agent/skills/{using-git-worktrees,worktree-*}/`, `.claude/rules/{using-git-worktrees,worktree-*}.md`, `.claude/commands/{remove-worktree,sdd-insight}.md`, `.agents/skills/sdd-insight/` |
| flowtask | `scripts/sdd/*` (35+ files incl. `.collision_baseline.json`), same worktree skills/commands |
| navigator-auth | `.agent/agents/sdd-*/agent.md` (old Google layout; now `.agents/agents/`), `.agent/workflows/sdd-insight.md`, `.agent/skills/worktree-management/`, `scripts/sdd/*` |

These orphans show stale instructions to all three assistant hosts (Claude Code, Codex, Gemini/Antigravity), for
example an old `.claude/rules/worktree-status.md` next to the current `worktree-management.md`. A clean install is
not possible without deleting them by hand.

### Goals
- G1: `parrot sdd uninstall --stalled` removes **only** stale SDD files and keeps the current installation; running
  `parrot sdd install` afterwards leaves the repository clean.
- G2: Detect stale files for all three hosts (`claude`, `codex`, `google`) in one run. Without `--host` all three
  are scanned; `--host` narrows the scan.
- G3: Three detection sources, each reported with its reason:
  `receipt-orphan` (recorded by an older install, no longer shipped), `retired` (a curated list of known legacy
  paths), `sdd-orphan` (an `sdd-*` entry in a host folder that the manifest does not ship).
- G4: `--dry-run` lists what would be removed; `--keep <glob>` (repeatable) protects exceptions.
- G5: `parrot sdd install` and `parrot sdd status` **report** stale files (never delete them) and point to
  `parrot sdd uninstall --stalled`.
- G6: Refuse to delete in the ai-parrot source checkout, where `sdd-*` files and `scripts/sdd/` are the originals.

### Non-Goals (explicitly out of scope)
- Removing current manifest assets: that is plain `parrot sdd uninstall` (unchanged).
- Seeds and SDD state: `sdd/config.json`, `sdd/CONVENTIONS.md`, `sdd/specs/`, `sdd/tasks/`, `sdd/proposals/`,
  `sdd/ledger/`, `sdd/state/`, and the receipt itself are never stale.
- Non-SDD integrations: `.codex/config.toml`, `.codex/skills/parrot-wiki/`, `.codex/rules/parrot-wiki.rules`,
  `.claude/rules/{python,cython,rust}-development.md` and any other file not matched by G3 belong to other
  installers or to the team. They are never touched.
- Stale MCP server entries in `.mcp.json`, `.codex/config.toml` or `~/.gemini/config/mcp_config.json` (handled by
  the toolkit installer; possible follow-up).
- User-global folders (`~/.claude`, `~/.codex`, `~/.gemini`): verified empty of SDD copies on 2026-11-03.
- Deleting `.github/workflows` references to `scripts/sdd/*`: the user chose "remove everything" for
  `scripts/sdd/`, so references are not checked (see §7).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:1cfe2de29e6baa3b3770d41e19bb27e5f281d433610ffad8ddc64a51a03c7160 evaluation_digest=sha256:ffc5cd6f5cffbd2fc08000bab54acbca04b41ff12a9acbc03dd64b96e520aaf0 rules_version=0 status=incomplete -->

## 2. Architectural Design

### Overview

A new read-only module, `parrot/sdd/stale.py`, computes the stale set:

1. **receipt-orphan**: every key of `receipt["files"]` that is not a target of the current manifest. Parrot
   wrote it, so it is safe to remove. It is host-neutral and always scanned.
2. **retired**: files matched by `RETIRED_PATTERNS`, a hand-maintained tuple of `(glob, hosts, why)` for legacy
   paths that do not start with `sdd-`:
   - `scripts/sdd/**` (all hosts): helper scripts copied by hand, replaced by `parrot sdd <noun> <verb>`
     (FEAT-633). The **whole tree** goes, including `__pycache__/` and dotfiles. This was resolved with the
     user; no reference check.
   - `.claude/rules/{using-git-worktrees,worktree-status,worktree-start-feature,worktree-pr-and-clean}.md`
     (claude): merged into `.claude/rules/worktree-management.md` (FEAT-553).
   - `.agent/skills/{using-git-worktrees,worktree-status,worktree-start-feature,worktree-pr-and-clean,worktree-management}/**`
     (google): retired Google twins of the rule above; none ships.
   - `.agent/agents/sdd-*/**` (google): old Google agent layout, now `.agents/agents/sdd-*/agent.md`.
   - `.claude/commands/remove-worktree.md` (claude): an ai-parrot-only command that does not ship.
3. **sdd-orphan**: in each host folder of `SDD_PREFIX_DIRS`, every direct child whose name starts with `sdd-`
   (a file, or every file below a directory) that is not a current manifest target. Folders and hosts:
   `.claude/commands` (all hosts: Codex and Google skills point at the command bodies), `.claude/agents`
   (claude), `.agents/skills` and `.agents/agents` (codex, google), `.agent/workflows` and `.agent/skills`
   (google), `.codex/agents` (codex). The `sdd-` prefix belongs to parrot: a team-made `sdd-*` command is removed
   unless `--keep` protects it. This was resolved with the user.

These rules apply to every source:
- A current manifest target (any host) is **never** stale, and neither is a seed.
- Paths are de-duplicated, and reasons are ranked `receipt-orphan` > `retired` > `sdd-orphan`.
- Symlinks are never followed. A symlinked file or directory is reported as `skip-symlink` and kept.
- Only files are listed. After removal, empty parent folders are pruned up to (never including) the repo root.

`installer.py` turns that set into a plan (`stale-remove` / `keep-stale` / `skip-symlink` actions) and applies it
in `remove_stale_sdd_files()`:
- it unlinks each file and calls `_prune_empty_parents`;
- it drops the matching `receipt["files"]` keys and saves the receipt only when it changed;
- it never removes the receipt.

`install_sdd_integration` appends one note when the stale set is non-empty, and `sdd_status` gains a `"stale"`
key. The CLI adds `--stalled` (alias `--stale`) and `--keep GLOB` to `uninstall`. `--stalled` replaces the normal
uninstall plan entirely, and combining it with `--keep-edits` is a usage error.

**Source-checkout guard**: when `<root>/packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` exists, the
root is the ai-parrot monorepo, where the matched files are the asset **sources**:
- a real run raises `RuntimeError`, which the CLI turns into a `ClickException`;
- `--dry-run` still lists the stale set, preceded by a `note:` line;
- `sdd_status` and the install note skip the scan (they report `[]`).

### Component Diagram
```
parrot sdd uninstall --stalled [--host H]... [--keep GLOB]... [--dry-run]
        │  (cli.py)
        ▼
installer.remove_stale_sdd_files(root, hosts, keep, dry_run)
        │── stale.is_source_checkout(root) ──► refuse (real run) / note (dry-run)
        │── stale.find_stale(root, hosts, receipt, manifest_targets) ──► [StaleEntry]
        │── plan: stale-remove | keep-stale | skip-symlink
        └── apply: unlink → _prune_empty_parents → receipt["files"].pop → _save_receipt
install_sdd_integration ──► note: N stale SDD file(s) … (report only)
sdd_status              ──► "stale": [{"path", "reason", "detail"}]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `installer.load_manifest()` | uses | set of current targets = never stale |
| `installer.load_receipt()` / `_save_receipt()` | uses | receipt orphans in; pop removed keys out |
| `installer._under()` / `_prune_empty_parents()` | uses | containment (realpath) + empty-folder cleanup |
| `installer.PlanAction` | extends | + `stale-remove`, `keep-stale`, `skip-symlink` |
| `installer.install_sdd_integration()` | modifies | appends one report-only note |
| `installer.sdd_status()` | modifies | additive `"stale"` key (`parrot self doctor` reads this dict lazily; additive is safe) |
| `cli.uninstall` | modifies | `--stalled/--stale`, `--keep` |
| `cli.status` | modifies | prints `stale: N` + one line per entry |

### Data Models
```python
StaleReason = Literal["receipt-orphan", "retired", "sdd-orphan"]

class StaleEntry(BaseModel):
    path: str          # repo-relative posix path of one file
    reason: StaleReason
    detail: str        # human "why", e.g. "replaced by `parrot sdd <noun> <verb>` (FEAT-633)"
    symlink: bool = False
```

### New Public Interfaces
```python
def find_stale(root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS) -> list[StaleEntry]: ...
def is_source_checkout(root: Path) -> bool: ...
def remove_stale_sdd_files(
    root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS, *, keep: Sequence[str] = (), dry_run: bool = False
) -> list[str]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: stale detector | yes | `stale.py` layout, `StaleEntry`, three sources, `RETIRED_PATTERNS` / `SDD_PREFIX_DIRS` contents fixed in §2, guard path fixed | — |
| M2: installer wiring | yes | plan actions + messages fixed below; receipt rules fixed in §2 | — |
| M3: CLI flags | yes | flag names, alias, mutual exclusion, default hosts fixed | — |
| M4: docs | yes | section + `verify:` markers fixed | — |

### Module 1: Stale detector
- **Path**: `packages/ai-parrot/src/parrot/sdd/stale.py` (new)
- **Responsibility**: pure, read-only computation of the stale set and the source-checkout guard. It writes nothing.
- **Depends on**: `parrot.sdd.installer` (`SUPPORTED_HOSTS`, `load_manifest`, `load_receipt`, `_under`), imported
  **inside** the functions so that `installer.py` can import `stale` at module level without an import cycle.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/stale.py  (new)
  StaleReason = Literal["receipt-orphan", "retired", "sdd-orphan"]
  #: (glob relative to the repo root, hosts, why) — legacy paths NOT starting with `sdd-` (§2 item 2).
  RETIRED_PATTERNS: tuple[tuple[str, tuple[str, ...], str], ...]
  #: (host folder, hosts) whose direct `sdd-*` children are parrot-owned (§2 item 3).
  SDD_PREFIX_DIRS: tuple[tuple[str, tuple[str, ...]], ...]
  #: present only in the ai-parrot monorepo (asset sources live there).
  SOURCE_CHECKOUT_MARKER = Path("packages/ai-parrot/src/parrot/sdd/_assets/manifest.json")

  class StaleEntry(BaseModel):
      """One stale file: repo-relative ``path``, ``reason``, human ``detail``, ``symlink`` (never followed)."""

  def is_source_checkout(root: Path) -> bool:
      """True when ``root`` is the ai-parrot monorepo (``SOURCE_CHECKOUT_MARKER`` exists)."""

  def find_stale(root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS) -> list[StaleEntry]:
      """Stale SDD files for ``hosts`` (receipt orphans always), sorted by path, de-duplicated with reason
      precedence receipt-orphan > retired > sdd-orphan. Current manifest targets and seeds are never returned.
      Symlinks are returned with ``symlink=True`` and never descended. Raises ValueError for an unknown host."""
  ```

### Module 2: Installer wiring
- **Path**: `packages/ai-parrot/src/parrot/sdd/installer.py` (modify)
- **Responsibility**: plan + apply stale removal; report-only note in install; `"stale"` in status.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/sdd/installer.py:79  (PlanAction = Literal[ … ])
  #   add "stale-remove", "keep-stale", "skip-symlink" after "receipt-remove"   # verified: installer.py:108

  def plan_stale(root: Path, hosts: Sequence[str], *, keep: Sequence[str] = ()) -> list[PlannedAction]:
      """Pure: ``stale-remove`` per StaleEntry (note = "<reason>: <detail>"), ``keep-stale`` when a ``keep``
      glob (fnmatch on the posix path) matches, ``skip-symlink`` for symlink entries."""

  def remove_stale_sdd_files(
      root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS, *, keep: Sequence[str] = (), dry_run: bool = False
  ) -> list[str]:
      """Remove stale SDD files (current assets, seeds and state untouched).

      dry_run → ``str(step)`` lines (prefixed by a ``note:`` line in a source checkout).
      Real run in a source checkout → RuntimeError("refusing: <root> is the ai-parrot source checkout …").
      Each removal → "<path> — removed (<reason>)"; keep → "<path> — kept (--keep)";
      symlink → "warning: <path> — symlink; kept". Removed receipt keys are popped and the receipt saved
      only if it changed; empty → ["no stale SDD files"]. Ends with a "note: commit the deletions" line
      when anything was removed."""

  # modifies install_sdd_integration (verified: installer.py:1059) — before `return [a for a in actions if a]`
  #   (installer.py:1163): when not a source checkout and find_stale(root, SUPPORTED_HOSTS) is non-empty, append
  #   "note: N stale SDD file(s) the package no longer ships — review with `parrot sdd uninstall --stalled --dry-run`"
  # modifies sdd_status (verified: installer.py:1422) — add "stale": [e.model_dump() for e in find_stale(root)]
  #   ([] in a source checkout) next to "receipt_version" (installer.py:1464)
  ```

### Module 3: CLI flags
- **Path**: `packages/ai-parrot/src/parrot/sdd/cli.py` (modify)
- **Responsibility**: expose `--stalled` / `--keep` on `uninstall`; print stale entries in `status`.
- **Depends on**: Module 2 (`remove_stale_sdd_files`).
- **Interface Skeleton**:
  ```python
  # modifies cli.py:137  def uninstall(...)  — new options:
  @click.option("--stalled", "--stale", "stalled", is_flag=True,
                help="Remove only stale SDD files (hand-copied, retired or no longer shipped) for all hosts "
                     "unless --host narrows it; current assets are kept.")
  @click.option("--keep", "keep", multiple=True, metavar="GLOB",
                help="With --stalled: never remove paths matching GLOB (repeatable).")
  def uninstall(path_, hosts, keep_edits, dry_run, stalled, keep) -> None:
      """--stalled → remove_stale_sdd_files(root, hosts or SUPPORTED_HOSTS, keep=keep, dry_run=dry_run);
      --stalled with --keep-edits → click.UsageError; --keep without --stalled → click.UsageError;
      RuntimeError/ValueError → ClickException (unchanged pattern)."""
  # modifies cli.py:150 def status(...) — before the "receipt version:" line (cli.py:171):
  #   "stale: N" then "  stale: <path> (<reason>)" per entry
  ```

### Module 4: Documentation
- **Path**: `docs/install/global-runtime.md` (modify)
- **Responsibility**: document `--stalled` / `--keep`, the three reasons, the source-checkout refusal, the `install`
  note; add `<!-- verify: flag=sdd uninstall:--stalled -->` and `<!-- verify: flag=sdd uninstall:--keep -->`
  after the `--dry-run` marker (line 215) and a `parrot sdd uninstall --stalled --dry-run` line in the example.
- **Depends on**: none (flag names are fixed here), so it can run in parallel with M1–M3.

---

## 4. Test Specification

### Unit Tests (`packages/ai-parrot/tests/sdd/test_installer_stale.py`, new)
| Test | Module | Description |
|---|---|---|
| `test_receipt_orphan_detected` | M1 | receipt key not in the manifest → `receipt-orphan` |
| `test_retired_scripts_sdd_tree` | M1 | `scripts/sdd/a.py`, `__pycache__/a.pyc`, `.collision_baseline.json` all `retired` |
| `test_legacy_agent_layout_google_only` | M1 | `.agent/agents/sdd-worker/agent.md` stale for `google`, not reported for `--host claude` |
| `test_sdd_prefix_orphan_file_and_dir` | M1 | `.claude/commands/sdd-old.md` and `.claude/commands/sdd-pkg/README.md` → `sdd-orphan` |
| `test_current_targets_and_seeds_never_stale` | M1 | a full install, then `find_stale` == [] |
| `test_non_sdd_files_untouched` | M1 | `.codex/config.toml`, `.codex/skills/parrot-wiki/SKILL.md`, `.claude/rules/python-development.md` not reported |
| `test_reason_precedence` | M1 | a receipt-recorded `scripts/sdd/x.py` → only `receipt-orphan` |
| `test_symlink_not_followed` | M1 | `scripts/sdd` symlinked to a folder outside the repo → reported with `symlink=True`; the outside folder is untouched after removal |
| `test_source_checkout_detected` | M1 | marker file present → `is_source_checkout` True |
| `test_remove_stale_removes_and_prunes` | M2 | files gone, empty `scripts/sdd/` folder gone, current assets intact |
| `test_remove_stale_updates_receipt` | M2 | removed receipt keys popped; receipt kept |
| `test_remove_stale_keep_glob` | M2 | `--keep '.claude/commands/sdd-team-*'` keeps a matching file |
| `test_remove_stale_dry_run_writes_nothing` | M2 | plan lines only; tree byte-identical |
| `test_remove_stale_refuses_source_checkout` | M2 | real run raises RuntimeError; dry-run returns a `note:` + plan |
| `test_install_reports_stale_note` | M2 | install over a repo with orphans → one `note:` line, nothing deleted |
| `test_status_reports_stale` | M2 | `sdd_status(root)["stale"]` lists entries |

### Integration Tests (`packages/ai-parrot/tests/sdd/test_sdd_cli.py`, extend)
| Test | Description |
|---|---|
| `test_cli_uninstall_stalled_all_hosts_by_default` | Codex + Google + Claude orphans removed in one run without `--host` |
| `test_cli_uninstall_stalled_rejects_keep_edits` | `--stalled --keep-edits` → exit 2 |
| `test_cli_keep_requires_stalled` | `--keep X` alone → exit 2 |
| `test_cli_stale_alias` | `--stale` behaves as `--stalled` |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_installer_stale.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_installer.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def stale_repo(tmp_path: Path) -> Path:
    """A git-less repo after `install_sdd_integration(root, SUPPORTED_HOSTS)` plus hand-made orphans:
    scripts/sdd/{reserve_ids.py,__pycache__/x.pyc}, .claude/rules/worktree-status.md,
    .agent/agents/sdd-worker/agent.md, .claude/commands/sdd-insight.md, and a receipt entry for a dropped asset."""
```

---

## 5. Acceptance Criteria

- [ ] `parrot sdd uninstall --stalled` removes every receipt-orphan, retired and sdd-orphan file for all three hosts
      when `--host` is omitted, and only for the given hosts (plus receipt orphans and host-neutral retired paths)
      when `--host` is passed.
- [ ] After `--stalled`, every current manifest target, seed, `sdd/` state file and the receipt are byte-identical
      to before; `parrot sdd status` shows the same per-host states.
- [ ] `scripts/sdd/` is removed whole (including `__pycache__/` and dotfiles) and its empty folder is pruned.
- [ ] Non-SDD files (§1 Non-Goals) are never reported or removed.
- [ ] `--dry-run` writes nothing; `--keep GLOB` keeps matches; symlinks are never followed or removed.
- [ ] In the ai-parrot source checkout a real `--stalled` run exits non-zero with a clear message; `--dry-run` lists.
- [ ] `parrot sdd install` prints one `note:` when stale files exist and deletes none; `parrot sdd status [--json]`
      reports them.
- [ ] `--stalled --keep-edits` and `--keep` without `--stalled` are usage errors.
- [ ] Plain `parrot sdd uninstall` (no `--stalled`) behaves exactly as after PR #1940.
- [ ] `docs/install/global-runtime.md` documents the flags; its `verify:` markers pass.
- [ ] All Validation Contract tests pass; `ruff check` is clean on changed files.

---

## 6. Codebase Contract

Verified against `be6e31d092` (branch `fix/sdd-install-overwrite`, PR #1940, **unmerged on 2026-11-03**). This
feature builds on that PR: `keep_edits` and the overwrite defaults below come from it.

### Verified Imports
```python
from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration  # verified: cli.py:13
from parrot.sdd.installer import load_manifest, load_receipt, PlannedAction, RECEIPT_PATH  # verified: installer.py:136,209,112,44
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "google")                      # line 39
RECEIPT_PATH = Path("sdd/.sdd-installed.json")                                        # line 44
PlanAction = Literal[ …, "receipt-remove", ]                                          # lines 79-108
class PlannedAction(BaseModel): action: PlanAction; target: str; note: str = ""       # line 112; __str__ → "plan: <action> <target> (<note>)"
def load_manifest() -> list[dict[str, Any]]                                           # line 136; entries {"source","target","hosts",["seed"]}
def load_receipt(root: Path) -> dict[str, Any]                                        # line 209; {"files": {target: sha}, "blocks", "ledger_hooks", …}
def _save_receipt(root: Path, receipt: dict[str, Any]) -> None                        # line 256
def _under(path: Path, base: Path) -> bool                                            # line 270 (lexical; callers pass realpaths)
def plan_uninstall(root: Path, hosts: Sequence[str], *, keep_edits: bool = False) -> list[PlannedAction]  # line 644
def install_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False, portable=False,
                            base_branch=None, push_base=False, hotfix_base=None, dangerous_guard=True,
                            sdd_coder=True) -> list[str]                               # line 1059; returns at line 1163
def _prune_empty_parents(root: Path, path: Path) -> None                              # line 1256
def uninstall_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False) -> list[str]  # line 1267
def sdd_status(root: Path) -> dict[str, Any]                                          # line 1422; "receipt_version" key line 1464
# packages/ai-parrot/src/parrot/sdd/cli.py
_keep_edits_option = click.option("--keep-edits", …)                                  # line 17
def uninstall(path_: Path | None, hosts: tuple[str, ...], keep_edits: bool, dry_run: bool) -> None  # line 137
def status(path_: Path | None, as_json: bool) -> None                                 # line 150; "receipt version:" echo line 171
# scripts/sdd/check_asset_sync.py (asset generator, stdlib only)
ASSET_SOURCES  # the globs that define what ships; EXCLUDED_TARGETS = sdd-insight on all hosts (does not ship)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `stale.find_stale` | `load_manifest()` / `load_receipt()` | function-local import | `installer.py:136`, `:209` |
| `remove_stale_sdd_files` | `_prune_empty_parents`, `_save_receipt`, `_under` | call | `installer.py:1256`, `:256`, `:270` |
| install note | `install_sdd_integration` | append before return | `installer.py:1163` |
| status key | `sdd_status` | dict entry | `installer.py:1464` |
| CLI | `remove_stale_sdd_files` | import in `cli.py:13` | `cli.py:13` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.sdd.stale`~~: created by M1.
- ~~`--stalled` / `--stale` / `--keep` on `parrot sdd uninstall`~~: added by M3.
- ~~a `"retired"` / `"stale"` key in `_assets/manifest.json`~~: the retired list lives in `stale.py`, never in
  the generated manifest (`check_asset_sync.py --write` would drop it).
- ~~`--force` semantics~~: `--force` is a hidden no-op since PR #1940; do not wire anything to it.
- ~~an existing source-checkout guard in `installer.py`~~: none; M1 adds `is_source_checkout`.
- ~~SDD copies under `~/.claude`, `~/.codex`, `~/.gemini`~~: none found; not scanned.

### Edit Sites (Blueprint Anchors)

Verified against: `be6e31d092`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/stale.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    "receipt-remove",` | `installer.py:108` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    return [a for a in actions if a]` | `installer.py:1163` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `def uninstall_sdd_integration(` (new functions go right above it) | `installer.py:1267` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `        "receipt_version": receipt.get("version"),` | `installer.py:1464` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration` | `cli.py:13` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `def uninstall(path_: Path \| None, hosts: tuple[str, ...], keep_edits: bool, dry_run: bool) -> None:` | `cli.py:137` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `    click.echo(f"receipt version: {report['receipt_version'] or 'none'}")` | `cli.py:171` | 1 |
| `docs/install/global-runtime.md` | MODIFY | `<!-- verify: flag=sdd uninstall:--dry-run -->` | `global-runtime.md:215` | 1 |
| `packages/ai-parrot/tests/sdd/test_installer_stale.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | MODIFY | `def test_uninstall_removes_unrecorded_assets_unless_keep_edits(tmp_path: Path) -> None:` | `test_sdd_cli.py:50` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror the existing plan/apply split: a pure `plan_*` returning `PlannedAction`s, an apply loop producing
  action-log strings (`"warning:"` / `"note:"` prefixes drive `_echo_actions` in `cli.py`).
- Symlink safety like `_apply_asset`: compare `os.path.realpath` of the candidate against the realpath of the
  root with `_under`; walk with `os.walk(..., followlinks=False)` / `Path.is_symlink()` before descending.
- Retired globs use `fnmatch` on posix relative paths (as `check_asset_sync.py` does); `**` patterns are expanded
  by walking the folder prefix, not by `Path.glob` (which follows symlinks on older Pythons).
- `logger` for warnings, never `print`; Google docstrings; ruff/black at 120 columns.

### Known Risks / Gotchas
- **CI still calling `scripts/sdd/*`**: a consumer repo whose `.github/workflows` runs
  `scripts/sdd/check_id_collisions.py` breaks after `--stalled`. The user chose to remove the whole tree. The
  docs must say to replace such calls with `parrot sdd <noun> <verb>`, and `--keep 'scripts/sdd/<file>'` is the
  escape hatch.
- **Team-made `sdd-*` commands** are removed (`sdd-` prefix is parrot-owned). Mitigation: `--dry-run` first and
  `--keep`; the docs must say so.
- **Source checkout**: ai-parrot's own `sdd-insight` files, `.agent/agents/sdd-*` and `scripts/sdd/` are sources or
  shims; the guard (G6) is mandatory, and tests must cover it.
- **Worktree tests import the main checkout** (shared editable venv): run tests with
  `PYTHONPATH=packages/ai-parrot/src`.
- **`.agent/skills/worktree-management/`** is the Google twin still maintained in ai-parrot. It is retired only in
  consumer repos, which the source guard ensures.
- Deleting tracked files leaves `git status` deletions; the run ends with a `note:` to commit them.

### External Dependencies
None (stdlib `fnmatch`, `os`, `pathlib`; `pydantic` already used).

---

## Worktree Strategy

- Isolation: one feature worktree `feat-FEAT-795-parrot-sdd-install-remove`; the `sdd-coder` engine gives each
  task its own sub-worktree inside it.
- Module dependency graph: M2 → M1 (imports `find_stale`, `is_source_checkout`, `StaleEntry`); M3 → M2 (imports
  `remove_stale_sdd_files`). M4 has no code edge and runs concurrently with M1–M3.
- Shared files: `installer.py` (M2 only), `cli.py` (M3 only), `test_sdd_cli.py` (M3 only); no file is shared
  across modules.
- Exclusive resources: none.
- **Cross-feature dependency**: PR #1940 (`fix/sdd-install-overwrite`) must be merged into `dev` before the
  worktree is created; all anchors above are from that branch.

---

## Decisions

```yaml
schema_version: 1
document_id: parrot-sdd-install-remove
entries:
  - id: sdd-prefix-is-parrot-owned
    statement: Any `sdd-*` entry in an SDD host folder that the current manifest does not ship is stale and removed by `parrot sdd uninstall --stalled` unless protected by `--keep`.
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/installer.py]
    contradicts: []
    supersedes: []
    rationale: Hand-copied and retired SDD files leave outdated instructions for all three assistant hosts; the user chose prefix ownership over a report-only mode.
    rejected_alternatives: [report-only for unknown sdd-* files]
  - id: stalled-never-touches-current-assets
    statement: "`--stalled` removes only stale files; current manifest targets, seeds, SDD state and the receipt are never removed by it."
    relation: forbids
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/installer.py]
    contradicts: []
    supersedes: []
    rationale: The flag exists to make a following install clean, not to uninstall.
    rejected_alternatives: [full uninstall plus stale removal]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:1cfe2de29e6baa3b3770d41e19bb27e5f281d433610ffad8ddc64a51a03c7160 evaluation_digest=sha256:ffc5cd6f5cffbd2fc08000bab54acbca04b41ff12a9acbc03dd64b96e520aaf0 rules_version=0 status=incomplete -->

Audit status: `incomplete` (exit 3)

Findings:
- none

Diagnostics:
- `SNAPSHOT_UNSTABLE`; path: /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/spec-stale-tmp/sdd/specs/parrot-sdd-install-remove.spec.md; message: decision inventory changed while reading

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: cleanup, cli, installer, sdd-tooling
- Targets resolved: 1/1
- Impact complete: true
- Inventory complete: false
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": false,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 1,
    "targets_total": 1,
    "unmapped_tags": [
      "cleanup",
      "cli",
      "installer",
      "sdd-tooling"
    ]
  },
  "diagnostics": [
    {
      "code": "SNAPSHOT_UNSTABLE",
      "decision_id": null,
      "message": "decision inventory changed while reading",
      "path": "/home/jesuslara/proyectos/ai-parrot/.claude/worktrees/spec-stale-tmp/sdd/specs/parrot-sdd-install-remove.spec.md"
    }
  ],
  "evaluation_digest": "sha256:ffc5cd6f5cffbd2fc08000bab54acbca04b41ff12a9acbc03dd64b96e520aaf0",
  "exit_code": 3,
  "findings": [],
  "input_digest": "sha256:1cfe2de29e6baa3b3770d41e19bb27e5f281d433610ffad8ddc64a51a03c7160",
  "snapshot": null,
  "status": "incomplete"
}
```

## 8. Open Questions

- [x] What does `--stalled` remove? — *Resolved with the user (2026-11-03)*: only stale files; the current
      installation is kept.
- [x] Hand-copied `scripts/sdd/*` — *Resolved with the user*: remove the whole tree, no reference check.
- [x] Unknown `sdd-*` files in host folders — *Resolved with the user*: remove them (`sdd-` prefix is
      parrot-owned); `--keep` and `--dry-run` cover exceptions.
- [ ] Should `remove-worktree` (today an ai-parrot-only skill) ship in the manifest instead of being retired in
      consumer repos? — *Owner: Jesus Lara*
- [ ] Follow-up: stale MCP server entries (old toolkit names) in `.mcp.json` / `.codex/config.toml` /
      `~/.gemini/config/mcp_config.json`. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec written from notes) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-03 | Jesus Lara | Initial draft |
