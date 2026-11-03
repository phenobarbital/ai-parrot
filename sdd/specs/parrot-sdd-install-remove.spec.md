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
**Status**: approved
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
- G7: Ship `/remove-worktree` to all three hosts. Today it is an ai-parrot-only command that calls
  `scripts/remove_worktree.py`, a script that exists only where it was copied by hand (it is missing in flowtask,
  so the command is broken there). Shipped assets (`sdd-fix`, `sdd-status`, the `worktree-management` rule) already
  send users to `/remove-worktree`. The script moves into the package as `parrot sdd worktree list|remove`, and the
  hand-copied `scripts/remove_worktree.py` becomes a `retired` stale file.
- G8: `--stalled` also removes stale MCP toolkit entries (`parrot-<name>` entries that run `parrot mcp-local
  <name>`) from `.mcp.json`, `.codex/config.toml`, `.agents/plugins/parrot/mcp_config.json` and the user-global
  `~/.gemini/config/mcp_config.json`, for the selected hosts.

### Non-Goals (explicitly out of scope)
- Removing current manifest assets: that is plain `parrot sdd uninstall` (unchanged).
- Seeds and SDD state: `sdd/config.json`, `sdd/CONVENTIONS.md`, `sdd/specs/`, `sdd/tasks/`, `sdd/proposals/`,
  `sdd/ledger/`, `sdd/state/`, and the receipt itself are never stale.
- Non-SDD integrations: `.codex/config.toml`, `.codex/skills/parrot-wiki/`, `.codex/rules/parrot-wiki.rules`,
  `.claude/rules/{python,cython,rust}-development.md` and any other file not matched by G3 belong to other
  installers or to the team. They are never touched.
- MCP entries that are not parrot toolkit entries: `wikitoolkit`, `bookstore`, any key not starting with
  `parrot-`, and any `parrot-<name>` whose command is not `parrot mcp-local <name>` (a genuinely foreign server
  with a colliding name). The rest of each config file is never touched.
- Re-registering toolkits after cleanup: `--stalled` only removes; `parrot toolkits install <name>` re-adds an
  enabled toolkit (the run ends with that note when it removed an entry for an enabled toolkit).
- Editing `.parrot/mcp-toolkits.yaml`: a section for a toolkit that no longer has a template is **reported**, not
  removed (it may carry operator settings).
- User-global SDD folders (`~/.claude`, `~/.codex`, `~/.gemini`): verified empty of SDD copies on 2026-11-03.
- Deleting `.github/workflows` references to `scripts/sdd/*`: the user chose "remove everything" for
  `scripts/sdd/`, so references are not checked (see §7).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:87b9fdeed8b7718c4f9740444ce334411bd9598dbc1e87981deaa5f494904c06 evaluation_digest=sha256:0310208dd202aac166dc7179d26c5077e8b3fa8a23bbbc44aa49f36f70a0a08f rules_version=0 status=incomplete -->

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
   - `scripts/remove_worktree.py` (all hosts): hand-copied helper, replaced by `parrot sdd worktree list|remove`
     (M5). `.claude/commands/remove-worktree.md` is **not** retired: it ships from now on (G7), so an old copy is
     simply overwritten by `parrot sdd install` (PR #1940 default).
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
The guard covers **files only**. MCP entries (below) are not sources, so their cleanup runs in every repository,
ai-parrot included.

**Stale MCP toolkit entries (G8, M6)** — a new read/write module `parrot/mcp/toolkit_stale.py`. An entry is a
*parrot toolkit entry* when its key is `parrot-<name>`, its `command` basename is `parrot` and its `args` start
with `["mcp-local", <name>]` (the shape test the host installers already use, minus their containment check).
Only such entries are ever candidates. Reasons:

| Reason | Applies to | Rule |
|---|---|---|
| `retired-toolkit` | every file, global included | `<name>` is not in `available_templates()`: the toolkit no longer exists anywhere |
| `undeclared` | repo-scoped files only | `<name>` is not an **enabled** section of this repo's `.parrot/mcp-toolkits.yaml` (e.g. flowtask's `parrot-memory`) |
| `foreign-repo` | repo-scoped files only | `--config` is an absolute path outside `root`: copied from another repository (today classified "foreign" and kept forever) |
| `missing-repo` | the user-global Gemini file only | `--config` is an absolute path whose repository folder no longer exists |

Files per host: `claude` → `<root>/.mcp.json`; `codex` → `<root>/.codex/config.toml`, every `[mcp_servers.parrot-<name>]`
table **inside or outside** the managed marker block; `google` → `<root>/.agents/plugins/parrot/mcp_config.json`
(repo-scoped) and `~/.gemini/config/mcp_config.json` (global; a portable entry there is never `undeclared`
because other repositories share it). After removing Claude entries, their names are dropped from
`enabledMcpjsonServers` with the existing `uninstall_toolkit_approvals()`. A config file that does not parse is
skipped with a warning and never rewritten. `--keep` globs also match MCP entries, written as
`<file>#<key>` (`.mcp.json#parrot-memory`, `~/.gemini/config/mcp_config.json#parrot-lsp`).

**`/remove-worktree` ships (G7, M5)** — `scripts/remove_worktree.py` moves to
`parrot/sdd/scripts/remove_worktree.py` with a `main(argv)` and is mounted in `cli.VERBS["worktree"]` as `list` and
`remove`. The repo root is the **primary** checkout (`git rev-parse --path-format=absolute --git-common-dir`,
parent), so it behaves the same when run from inside a worktree, as the old `Path(__file__)` root did. ai-parrot
keeps `scripts/remove_worktree.py` as a compatibility shim (same pattern as `scripts/sdd/ensure_worktree.py`).
The command body is rewritten to call `parrot sdd worktree list|remove` (no `source .venv`, no `scripts/` path —
the C16 gate forbids both in shipped files) and gets its codex/google twins; `check_asset_sync.py` ships all three.

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
        │  (cli.py, after the file part)
        ▼
toolkit_stale.remove_stale_mcp_entries(root, hosts, keep, dry_run)
        │── find_stale_mcp_entries ──► [StaleMcpEntry]  (.mcp.json · .codex/config.toml · plugin + global Gemini)
        └── apply per file: delete keys / TOML tables → write once → uninstall_toolkit_approvals (claude)
install_sdd_integration ──► note: N stale SDD file(s), M stale MCP entr(y/ies) … (report only)
sdd_status              ──► "stale": [{"path", "reason", "detail"}], "stale_mcp": [{"file", "key", "reason"}]

parrot sdd worktree list | remove …  ──► parrot.sdd.scripts.remove_worktree.main([verb, …])
/remove-worktree (claude command · codex/google skill · google workflow) ──► parrot sdd worktree list|remove
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
| `cli.status` | modifies | prints `stale: N` + one line per entry, then `stale mcp: M` + one line per entry |
| `mcp.toolkit_seed.available_templates()` | uses | the set of toolkits that still exist |
| `mcp.toolkit_config.load_toolkits_config()` | uses | enabled sections → `undeclared` |
| `knowledge.wiki.claude_code.installer.uninstall_toolkit_approvals()` | uses | drop approvals of removed Claude entries |
| `knowledge.wiki.codex.installer._remove_toml_table()` / `_validate_toml()` | uses | delete one TOML table, validate before write |
| `knowledge.wiki.google.assets.default_mcp_config_path()` | uses | the global Gemini file (overridable for tests) |
| `cli.VERBS["worktree"]` | extends | + `list`, `remove` → `remove_worktree` |
| `scripts/sdd/check_asset_sync.py::ASSET_SOURCES` | extends | ships the `/remove-worktree` command and twins |

### Data Models
```python
StaleReason = Literal["receipt-orphan", "retired", "sdd-orphan"]

class StaleEntry(BaseModel):
    path: str          # repo-relative posix path of one file
    reason: StaleReason
    detail: str        # human "why", e.g. "replaced by `parrot sdd <noun> <verb>` (FEAT-633)"
    symlink: bool = False

StaleMcpReason = Literal["retired-toolkit", "undeclared", "foreign-repo", "missing-repo"]

class StaleMcpEntry(BaseModel):
    host: Literal["claude", "codex", "google"]
    file: str          # display path: repo-relative, or "~/…" for the global Gemini file
    key: str           # "parrot-<name>"
    reason: StaleMcpReason
    detail: str
```

### New Public Interfaces
```python
def find_stale(root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS) -> list[StaleEntry]: ...
def is_source_checkout(root: Path) -> bool: ...
def remove_stale_sdd_files(
    root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS, *, keep: Sequence[str] = (), dry_run: bool = False
) -> list[str]: ...
def find_stale_mcp_entries(
    root: Path, hosts: Sequence[str], *, gemini_config: Path | None = None
) -> list[StaleMcpEntry]: ...
def remove_stale_mcp_entries(
    root: Path, hosts: Sequence[str], *, keep: Sequence[str] = (), dry_run: bool = False,
    gemini_config: Path | None = None,
) -> list[str]: ...
# parrot sdd worktree list [--check-pr]
# parrot sdd worktree remove [TARGET] [--stale] [--delete-branch] [--force] [--dry-run]
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
| M5: ship `/remove-worktree` | yes | port is behavior-preserving; verbs, root rule, shim, asset rows fixed in §2/§3 | — |
| M6: stale MCP entries | yes | four reasons, files per host, shape test, `<file>#<key>` keep form fixed in §2 | — |

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
- **Responsibility**: plan + apply stale removal; report-only note in install; `"stale"` and `"stale_mcp"` in status.
- **Depends on**: Module 1, Module 6 (`find_stale_mcp_entries` for the note and the status key).
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
  #   (installer.py:1163): N = len(find_stale(root, SUPPORTED_HOSTS)) (0 in a source checkout),
  #   M = len(find_stale_mcp_entries(root, hosts)) for the hosts being installed; when N or M > 0 append
  #   "note: N stale SDD file(s), M stale MCP entr(y/ies) — review with `parrot sdd uninstall --stalled --dry-run`"
  # modifies sdd_status (verified: installer.py:1422) — add "stale": [e.model_dump() for e in find_stale(root)]
  #   ([] in a source checkout) and "stale_mcp": [e.model_dump() for e in find_stale_mcp_entries(root,
  #   SUPPORTED_HOSTS)] next to "receipt_version" (installer.py:1464)
  ```

### Module 3: CLI flags
- **Path**: `packages/ai-parrot/src/parrot/sdd/cli.py` (modify)
- **Responsibility**: expose `--stalled` / `--keep` on `uninstall`; print stale entries in `status`.
- **Depends on**: Module 2 (`remove_stale_sdd_files`), Module 6 (`remove_stale_mcp_entries`).
- **Interface Skeleton**:
  ```python
  # modifies cli.py:137  def uninstall(...)  — new options:
  #   --stalled runs remove_stale_sdd_files then remove_stale_mcp_entries with the same hosts/keep/dry_run and
  #   echoes both action lists. In a source checkout the file part's RuntimeError is reported, the MCP part still
  #   runs, and the command exits non-zero (files refused).
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
  #   "stale: N" then "  stale: <path> (<reason>)" per entry;
  #   "stale mcp: M" then "  stale mcp: <file>#<key> (<reason>)" per entry
  # modifies cli.py:176 VERBS["worktree"] — add:
  #   "list":   ("remove_worktree", ("list",),   "List worktrees and orphan dirs: dirty, unpushed, PR, live processes."),
  #   "remove": ("remove_worktree", ("remove",), "Remove a worktree safely (refuses a live sdd-worker, dirty, unpushed)."),
  ```

### Module 4: Documentation
- **Path**: `docs/install/global-runtime.md` (modify)
- **Responsibility**: document `--stalled` / `--keep`, the three file reasons and four MCP reasons, the
  `<file>#<key>` keep form, the source-checkout refusal (files only), the `install` note, and
  `parrot sdd worktree list|remove`; add `<!-- verify: flag=sdd uninstall:--stalled -->` and
  `<!-- verify: flag=sdd uninstall:--keep -->` after the `--dry-run` marker (line 215) and a
  `parrot sdd uninstall --stalled --dry-run` line in the example.
- **Depends on**: none (flag names are fixed here), so it can run in parallel with M1–M3.

### Module 5: Ship `/remove-worktree`
- **Paths**:
  - `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (new — port of `scripts/remove_worktree.py`)
  - `scripts/remove_worktree.py` (modify → compatibility shim)
  - `packages/ai-parrot/src/parrot/sdd/cli.py` (modify — `VERBS["worktree"]`; see M3 skeleton; M5 owns this edit)
  - `.claude/commands/remove-worktree.md` (modify — call `parrot sdd worktree list|remove`)
  - `.agents/skills/remove-worktree/SKILL.md` (new — codex/google skill twin, frontmatter `name`/`description`)
  - `.agent/workflows/remove-worktree.md` (new — google workflow twin, frontmatter `description`)
  - `scripts/sdd/check_asset_sync.py` (modify — three `ASSET_SOURCES` rows), then `--write` regenerates
    `parrot/sdd/_assets/` + `manifest.json`
  - `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (modify — `_SHIPPED_GLOBS` gains the three paths)
- **Responsibility**: make `/remove-worktree` work in every repository that ran `parrot sdd install`.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py  (new)
  PROTECTED_BRANCHES = {"main", "dev", "staging", "master"}       # verified: scripts/remove_worktree.py:48

  def repo_root() -> Path:
      """Primary checkout root: parent of ``git rev-parse --path-format=absolute --git-common-dir``.
      Exit 1 with "error: not a git repository" outside git."""

  # Behavior-preserving port of: Worktree (verified: scripts/remove_worktree.py:59), live_processes_in (:140),
  # discover (:168), cmd_list (:209), _match (:243), _remove_one (:272), cmd_remove (:354);
  # REPO_ROOT / WORKTREE_DIR module constants become values derived from repo_root() at call time.

  def main(argv: Sequence[str] | None = None) -> int:
      """argparse CLI, same sub-commands and flags as scripts/remove_worktree.py:393
      (list [--check-pr]; remove [target] [--stale] [--delete-branch] [--force] [--dry-run])."""

  # scripts/remove_worktree.py → shim, same shape as scripts/sdd/ensure_worktree.py:1-8:
  #   from parrot.sdd.scripts import remove_worktree as _impl; main → _impl.main(); sys.modules alias

  # scripts/sdd/check_asset_sync.py ASSET_SOURCES (verified: :30-43) — add after the matching sdd-* rows:
  #   (".claude/commands/remove-worktree.md", HOST_ORDER),
  #   (".agents/skills/remove-worktree/SKILL.md", ("codex", "google")),
  #   (".agent/workflows/remove-worktree.md", ("google",)),
  ```

### Module 6: Stale MCP toolkit entries
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` (new)
- **Responsibility**: find and remove stale `parrot-<name>` toolkit entries per §2; never touch anything else in a
  config file.
- **Depends on**: none (only existing `parrot.mcp` / `parrot.knowledge.wiki.*` helpers).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/mcp/toolkit_stale.py  (new)
  StaleMcpReason = Literal["retired-toolkit", "undeclared", "foreign-repo", "missing-repo"]

  class StaleMcpEntry(BaseModel):
      """One stale toolkit entry: ``host``, display ``file``, ``key`` ("parrot-<name>"), ``reason``, ``detail``."""

  def is_parrot_toolkit_entry(key: str, entry: Any) -> bool:
      """``key`` is "parrot-<name>", ``command`` basename is "parrot" and ``args[:2] == ["mcp-local", name]``.
      No containment check (that is what separates it from the installers' ``_is_managed_toolkit_entry``)."""

  def find_stale_mcp_entries(
      root: Path, hosts: Sequence[str], *, gemini_config: Path | None = None
  ) -> list[StaleMcpEntry]:
      """Read-only. Files per host and reasons per §2. ``gemini_config`` overrides
      ``google.assets.default_mcp_config_path()`` (tests never touch the real home). An unparsable file is
      skipped. Sorted by (file, key). Raises ValueError for an unknown host."""

  def remove_stale_mcp_entries(
      root: Path, hosts: Sequence[str], *, keep: Sequence[str] = (), dry_run: bool = False,
      gemini_config: Path | None = None,
  ) -> list[str]:
      """dry_run → "plan: stale-mcp-remove <file>#<key> (<reason>)" lines. Real run: per file, drop the
      non-kept keys (JSON: ``mcpServers`` key; TOML: ``_remove_toml_table`` + ``_validate_toml``, and an emptied
      managed marker block is removed), write the file once, then ``uninstall_toolkit_approvals(root, removed)``
      for Claude. Lines: "<file>#<key> — removed (<reason>)", "<file>#<key> — kept (--keep)", and one
      "note: re-register with `parrot toolkits install <names>`" when a removed entry's toolkit is enabled here.
      Empty → ["no stale MCP entries"]."""
  ```

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
| `test_status_reports_stale` | M2 | `sdd_status(root)["stale"]` lists entries; `"stale_mcp"` present |
| `test_retired_remove_worktree_script` | M1 | `scripts/remove_worktree.py` → `retired`; an installed `.claude/commands/remove-worktree.md` is not stale |

### Unit Tests (`packages/ai-parrot/tests/mcp/test_toolkit_stale.py`, new)
| Test | Module | Description |
|---|---|---|
| `test_undeclared_entry_in_mcp_json` | M6 | `parrot-memory` in `.mcp.json`, `memory` not enabled → `undeclared` |
| `test_retired_toolkit_any_file` | M6 | `parrot-oldkit` (no template) → `retired-toolkit` in `.mcp.json` and in the global Gemini file |
| `test_foreign_repo_pinned_config` | M6 | `--config /other/repo/.parrot/mcp-toolkits.yaml` in `.mcp.json` → `foreign-repo` |
| `test_global_portable_entry_not_undeclared` | M6 | portable `parrot-browsing` in the global file, `browsing` not enabled here → not stale |
| `test_global_missing_repo` | M6 | global entry pinned to a deleted folder → `missing-repo` |
| `test_non_parrot_entries_untouched` | M6 | `wikitoolkit`, `bookstore`, `parrot-x` with a non-`mcp-local` command → never reported; bytes of other keys kept |
| `test_codex_tables_inside_and_outside_block` | M6 | stale tables removed from both places; `wikitoolkit` table and foreign tables byte-identical; TOML still valid |
| `test_claude_approvals_dropped` | M6 | removed keys leave `enabledMcpjsonServers`; others stay |
| `test_keep_matches_file_key` | M6 | `--keep '.mcp.json#parrot-memory'` keeps it |
| `test_unparsable_file_skipped` | M6 | invalid JSON → warning, file byte-identical |
| `test_reregister_note` | M6 | removing a `foreign-repo` entry of an enabled toolkit → one `parrot toolkits install` note |
| `test_dry_run_mcp_writes_nothing` | M6 | all files byte-identical |

### Unit Tests (`packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`, extend)
| Test | Module | Description |
|---|---|---|
| `test_remove_worktree_root_is_primary_checkout` | M5 | run from inside a linked worktree → root is the primary checkout |
| `test_remove_worktree_list_and_dry_run` | M5 | `main(["list"])` exits 0 in a temp repo; `remove <name> --dry-run` removes nothing |
| `test_remove_worktree_refuses_dirty` | M5 | a dirty worktree is refused without `--force` |

### Integration Tests (`packages/ai-parrot/tests/sdd/test_sdd_cli.py`, extend)
| Test | Description |
|---|---|
| `test_cli_uninstall_stalled_all_hosts_by_default` | Codex + Google + Claude orphans removed in one run without `--host` |
| `test_cli_uninstall_stalled_rejects_keep_edits` | `--stalled --keep-edits` → exit 2 |
| `test_cli_keep_requires_stalled` | `--keep X` alone → exit 2 |
| `test_cli_stale_alias` | `--stale` behaves as `--stalled` |
| `test_cli_stalled_cleans_mcp_entries` | one run removes stale files and stale MCP entries (global Gemini path overridden) |
| `test_cli_worktree_verbs_mounted` | `parrot sdd worktree list --help` and `remove --help` exit 0 |

Existing gates that must keep passing: `test_no_repo_script_refs.py` (the shipped `/remove-worktree` files carry
no `scripts/`, `.venv` or `parrot sdd run` text) and `check_asset_sync.py --check`.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_installer_stale.py
- packages/ai-parrot/tests/mcp/test_toolkit_stale.py
- packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
- packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/sdd/test_installer_toolkits.py
- packages/ai-parrot/tests/docs/test_getting_started_claims.py
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
- [ ] In the ai-parrot source checkout a real `--stalled` run refuses the file part and exits non-zero with a clear
      message (the MCP part still runs); `--dry-run` lists both.
- [ ] `parrot sdd install` prints one `note:` when stale files or stale MCP entries exist and deletes none;
      `parrot sdd status [--json]` reports both (`stale`, `stale_mcp`).
- [ ] `--stalled` removes every `retired-toolkit`, `undeclared`, `foreign-repo` and `missing-repo` entry of the
      selected hosts' MCP files; `wikitoolkit`, `bookstore`, non-`parrot-` keys and foreign-shaped `parrot-*` entries
      stay byte-identical; Claude approvals of removed entries are dropped; `.codex/config.toml` stays valid TOML.
- [ ] A portable entry in the global Gemini file is never removed for being disabled in one repository.
- [ ] `parrot sdd worktree list` and `parrot sdd worktree remove` behave like `scripts/remove_worktree.py`
      (same flags and safety gates) and resolve the primary checkout from inside a worktree.
- [ ] `parrot sdd install --host <h>` installs `/remove-worktree` for all three hosts (claude command, codex/google
      skill, google workflow); the shipped files call only `parrot sdd worktree …`; `check_asset_sync.py --check`
      and `test_no_repo_script_refs.py` pass.
- [ ] `scripts/remove_worktree.py` in ai-parrot still works (shim); in consumer repos `--stalled` reports it as
      `retired`.
- [ ] `--stalled --keep-edits` and `--keep` without `--stalled` are usage errors.
- [ ] Plain `parrot sdd uninstall` (no `--stalled`) behaves exactly as after PR #1940.
- [ ] `docs/install/global-runtime.md` documents the flags; its `verify:` markers pass.
- [ ] All Validation Contract tests pass; `ruff check` is clean on changed files.

---

## 6. Codebase Contract

First verified against `be6e31d092` (PR #1940 branch); **re-verified on `origin/dev` `6b216935ff` after PR #1940
merged (2026-11-03)** — every installer/cli line number below is unchanged. `keep_edits` and the overwrite
defaults come from that PR.

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
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]]   # line 175; "worktree": { line 176
#   "ensure"/"status"/"guard" exist; mounted via _mount → parrot.sdd.scripts.<module>.main([*prefix, *args]) (line 242)
def mounted_modules() -> set[str]                                                    # line 238 (drives _MOVED in the gate test)
# scripts/sdd/check_asset_sync.py (asset generator, stdlib only)
ASSET_SOURCES  # lines 30-43; (".claude/commands/sdd-*.md", HOST_ORDER) line 31, (".agents/skills/sdd-*/SKILL.md",
               # ("codex","google")) line 36, (".agent/workflows/sdd-*.md", ("google",)) line 38
EXCLUDED_TARGETS  # sdd-insight on all hosts (does not ship)
# scripts/remove_worktree.py (ai-parrot only, 423 lines)
REPO_ROOT = Path(__file__).resolve().parent.parent                                    # line 46
PROTECTED_BRANCHES = {"main", "dev", "staging", "master"}                             # line 48
class Worktree  # line 59;  live_processes_in line 140; discover line 168; cmd_list line 209;
                # _match line 243; _remove_one line 272; cmd_remove line 354; main() line 393 (argparse)
# .claude/commands/remove-worktree.md — 3 lines run `python scripts/remove_worktree.py …` (lines 36, 75, 83)
# scripts/sdd/ensure_worktree.py lines 1-8 — the compatibility-shim pattern for M5
# packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py
_SHIPPED_GLOBS  # line 38; ".agents/skills/sdd-*/SKILL.md", ".codex/agents/sdd-worker.toml", ".agent/workflows/sdd-*.md" line 41

# packages/ai-parrot/src/parrot/mcp/
toolkit_seed.available_templates() -> tuple[str, ...]                                 # toolkit_seed.py:53
toolkit_config.load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig  # toolkit_config.py:90
hosts.HostKind / get_adapter / GoogleAdapter(mcp_path=None)                           # hosts.py:18, :228, :176
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def uninstall_toolkit_approvals(root: Path, removed_toolkit_names: Sequence[str]) -> Optional[str]  # line 577
def _is_managed_toolkit_entry(entry, root, name) -> bool   # line 661 — shape + containment (foreign if outside root)
def reconcile_toolkit_entries(root, *, portable=None)      # line 705 — removes only managed, non-enabled entries
def _script_basename(command: str) -> str                  # line 91
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _remove_marker_block(text, begin, end) -> str          # line 37
def _validate_toml(path: Path, text: str) -> None          # line 50
def _remove_toml_table(text: str, table: str) -> str       # line 60
def _existing_table_names(text: str) -> set[str]           # line 106
def reconcile_toolkit_tables(root, *, portable=None)       # line 263 — tables outside the marker block are "foreign"
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"; MCP_END = "# <<< parrot-wiki Codex MCP <<<"   # lines 19-20
# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _load_mcp_config(path: Path) -> dict[str, Any]         # line 46
def _is_managed_toolkit_entry(entry, root, name) -> bool   # line 101
def _is_parrot_toolkit_shape(entry, name) -> bool          # line 137 — shape only (used for the global file)
def toolkit_config_paths(root, mcp_path=None) -> tuple[Path, ...]   # line 206 — (global, repo plugin file)
def reconcile_toolkit_entries(root, mcp_path=None, *, portable=None)  # line 219 — global entries portable since PR #1940
# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
def default_mcp_config_path() -> Path                      # line 65
PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"      # line 23 (same constant in claude_code/assets.py:94, codex/assets.py:27)
```

Observed state that motivates M6 (2026-11-03): flowtask has `parrot-memory` in `.mcp.json` and in the codex
marker block while `memory` is not declared in its `.parrot/mcp-toolkits.yaml`; querysource entries run ai-parrot's
`parrot` binary; the global Gemini file holds six entries pinned to ai-parrot's config (pre-PR #1940 shape).

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `stale.find_stale` | `load_manifest()` / `load_receipt()` | function-local import | `installer.py:136`, `:209` |
| `toolkit_stale.find_stale_mcp_entries` | `available_templates()`, `load_toolkits_config()`, `default_mcp_config_path()` | import | `toolkit_seed.py:53`, `toolkit_config.py:90`, `google/assets.py:65` |
| `toolkit_stale.remove_stale_mcp_entries` | `_remove_toml_table`, `_validate_toml`, `uninstall_toolkit_approvals` | import | `codex/installer.py:60`, `:50`; `claude_code/installer.py:577` |
| `worktree list/remove` | `remove_worktree.main` | `VERBS` row → `_mount` | `cli.py:176`, `:242` |
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
- ~~SDD copies under `~/.claude`, `~/.codex`, `~/.gemini`~~: none found; not scanned. (The global Gemini **MCP
  config** is scanned by M6 — that is a config file, not an SDD copy.)
- ~~`parrot.mcp.toolkit_stale`~~, ~~`parrot.sdd.scripts.remove_worktree`~~: created by M6 / M5.
- ~~`parrot sdd worktree list` / `remove`~~: today `worktree` has only `ensure`, `status`, `guard` (`cli.py:177-179`).
- ~~`.agents/skills/remove-worktree/`~~, ~~`.agent/workflows/remove-worktree.md`~~: do not exist; M5 creates them.
- ~~a public "is parrot toolkit shape" helper for every host~~: only google's private `_is_parrot_toolkit_shape`
  exists; M6 defines its own `is_parrot_toolkit_entry` instead of importing a private name across hosts.
- ~~a `parrot toolkits` verb that removes stale entries~~: none; reconcile only removes *managed*, non-enabled
  entries, so `foreign-repo` and `retired-toolkit` entries survive it today.

### Edit Sites (Blueprint Anchors)

Verified against: `6b216935ff` (origin/dev, PR #1940 merged)

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
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY (M5) | `    "worktree": {` | `cli.py:176` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | CREATE | — | — | — |
| `scripts/remove_worktree.py` | MODIFY | `REPO_ROOT = Path(__file__).resolve().parent.parent` (whole file → shim) | `remove_worktree.py:46` | 1 |
| `.claude/commands/remove-worktree.md` | MODIFY | `python scripts/remove_worktree.py` | lines 36, 75, 83 | 3 |
| `.agents/skills/remove-worktree/SKILL.md` | CREATE | — | — | — |
| `.agent/workflows/remove-worktree.md` | CREATE | — | — | — |
| `scripts/sdd/check_asset_sync.py` | MODIFY | `    (".claude/commands/sdd-*.md", HOST_ORDER),` | `check_asset_sync.py:31` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/` + `manifest.json` | REGENERATE | `python scripts/sdd/check_asset_sync.py --write` | — | — |
| `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` | MODIFY | `    ".agents/skills/sdd-*/SKILL.md", ".codex/agents/sdd-worker.toml", ".agent/workflows/sdd-*.md",` | `test_no_repo_script_refs.py:41` | 1 |
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | MODIFY | append new tests at end of file | — | — |
| `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` | CREATE | — | — | — |

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
- **The global Gemini file is shared by every repository.** Only `retired-toolkit` and `missing-repo` apply there;
  never `undeclared` (another repo may use the toolkit) and never `foreign-repo` (every entry there points at
  *some* repo). Tests must pass `gemini_config=` and never touch `~/.gemini`.
- **Removing a `foreign-repo` entry of an enabled toolkit leaves that toolkit unregistered** until
  `parrot toolkits install <name>` runs; the closing note says so. `--stalled` deliberately does not re-register
  (removal only, Non-Goals).
- **Codex TOML**: a `parrot-<name>` table outside the managed block is a hand copy; `--stalled` removes it only when
  one of the four reasons applies. Validate with `_validate_toml` before writing; never write a file that fails.
- **`remove_worktree` port**: the old root was `Path(__file__).parent.parent`, i.e. always the primary checkout.
  `git rev-parse --show-toplevel` would return the *worktree* when run inside one and break orphan-dir discovery —
  use `--git-common-dir`. The `/proc/<pid>/cwd` liveness check is Linux-only, as before.
- **Asset sync**: edit the repo-side command/twins, then `check_asset_sync.py --write`; never hand-edit
  `_assets/` (the `--check` gate fails on divergence).

### External Dependencies
None (stdlib `fnmatch`, `os`, `pathlib`; `pydantic` already used).

---

## Worktree Strategy

- Isolation: one feature worktree `feat-FEAT-795-parrot-sdd-install-remove`; the `sdd-coder` engine gives each
  task its own sub-worktree inside it.
- Module dependency graph: M2 → M1 (imports `find_stale`, `is_source_checkout`, `StaleEntry`); M2 → M6 (imports
  `find_stale_mcp_entries`); M3 → M2 (imports `remove_stale_sdd_files`); M3 → M6 (imports
  `remove_stale_mcp_entries`). M1, M5 and M6 have no incoming edge and start concurrently; M4 has no code edge.
- Shared files: `cli.py` (M3 and M5 — `uninstall`/`status` vs. the `VERBS` table; serialize M5 before M3 or
  merge carefully), `test_sdd_cli.py` (M3 only), `installer.py` (M2 only).
- Exclusive resources: `check_asset_sync.py --write` regenerates `_assets/` + `manifest.json` (M5 only;
  `parallel: false` for that task).
- Cross-feature dependency: PR #1940 — **merged into `dev` on 2026-11-03**; no blocker remains.

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
  - id: stale-mcp-only-parrot-toolkit-shape
    statement: "`--stalled` removes an MCP entry only when its key is `parrot-<name>` and it runs `parrot mcp-local <name>`, and only for the reasons retired-toolkit, undeclared, foreign-repo or missing-repo; a portable entry in the shared global Gemini file is never removed as undeclared."
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/mcp/hosts.py]
    contradicts: []
    supersedes: []
    rationale: Config files mix parrot entries with wikitoolkit, bookstore and third-party servers; the user wants a clean install without risking entries parrot did not write.
    rejected_alternatives: [follow-up ledger issue only, drop the MCP cleanup]
  - id: remove-worktree-ships
    statement: "`/remove-worktree` ships to all three hosts and calls `parrot sdd worktree list|remove`; the hand-copied `scripts/remove_worktree.py` is a retired stale file in consumer repositories."
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/cli.py]
    contradicts: []
    supersedes: []
    rationale: Shipped assets already point users at /remove-worktree, which was broken wherever the script was not copied by hand (flowtask).
    rejected_alternatives: [retire remove-worktree in consumer repos, separate feature]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:87b9fdeed8b7718c4f9740444ce334411bd9598dbc1e87981deaa5f494904c06 evaluation_digest=sha256:0310208dd202aac166dc7179d26c5077e8b3fa8a23bbbc44aa49f36f70a0a08f rules_version=0 status=incomplete -->

Audit status: `incomplete` (exit 3)

Findings:
- none

Diagnostics:
- `SNAPSHOT_UNSTABLE`; path: /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/spec-oq-tmp/sdd/specs/parrot-sdd-install-remove.spec.md; message: decision inventory changed while reading

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: cleanup, cli, installer, sdd-tooling
- Targets resolved: 3/3
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
    "targets_resolved": 3,
    "targets_total": 3,
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
      "path": "/home/jesuslara/proyectos/ai-parrot/.claude/worktrees/spec-oq-tmp/sdd/specs/parrot-sdd-install-remove.spec.md"
    }
  ],
  "evaluation_digest": "sha256:0310208dd202aac166dc7179d26c5077e8b3fa8a23bbbc44aa49f36f70a0a08f",
  "exit_code": 3,
  "findings": [],
  "input_digest": "sha256:87b9fdeed8b7718c4f9740444ce334411bd9598dbc1e87981deaa5f494904c06",
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
- [x] Should `remove-worktree` ship in the manifest instead of being retired in consumer repos? — *Resolved with
      the user (2026-11-03)*: ship it. The script is ported to `parrot sdd worktree list|remove`, the command and
      its codex/google twins ship to all three hosts, and `scripts/remove_worktree.py` becomes `retired` (G7, M5).
- [x] Stale MCP server entries in `.mcp.json` / `.codex/config.toml` / `~/.gemini/config/mcp_config.json` —
      *Resolved with the user (2026-11-03)*: include them in this feature, not a follow-up. `--stalled` removes
      `retired-toolkit`, `undeclared`, `foreign-repo` and `missing-repo` parrot toolkit entries (G8, M6).

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
| 0.2 | 2026-11-03 | Jesus Lara | Resolved §8: ship `/remove-worktree` (M5), stale MCP entries in scope (M6); re-verified on origin/dev after PR #1940 merged |
