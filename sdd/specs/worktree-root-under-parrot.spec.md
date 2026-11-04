---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop]
tags: [sdd, worktree, installer, doctor, portability]
---

# Feature Specification: Worktree Root Under `.parrot/`

**Feature ID**: FEAT-802
**Date**: 2026-11-04
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.1.0

---

## 1. Motivation & Business Requirements

### Problem Statement

SDD worktrees live under `.claude/worktrees/`, a directory that belongs to one host (Claude Code)
although the SDD flow also runs under codex and gemini. The location is encoded in **three
independent constants** that do not know about each other:

| Source of truth | Kind | Who reads it |
|---|---|---|
| `conf.WORKTREE_BASE_PATH` (`parrot/conf.py:938`) | absolute, env-configurable (`WORKTREE_BASE_PATH`, FEAT-253) | dev-loop dispatchers, nodes, webhook, sdd-coder engine, usage recorders |
| `sdd_meta.WORKTREE_ROOT` (`knowledge/wiki/ledger/sdd_meta.py:379`) | fixed repo-relative string | `plan_worktree`, `plan_brief_worktree`, `worktree_status`, re-exported by `parrot/sdd/scripts/sdd_meta.py` |
| `worktree_environment.WORKTREE_ADMIN_DIR` (`sdd/scripts/worktree_environment.py:139`) | fixed `Path` | native sandbox allow-list |

plus eight more modules that spell `.claude/worktrees` inline (`remove_worktree`, `worktree_baseline`,
ledger `integration` outbox, `audit`, `dangerous_actions`, `doctor`, `installer`, e2e `supervisor`) and
~60 rule/command/agent/doc files. Setting `WORKTREE_BASE_PATH` therefore moves the dev-loop but not the
`parrot sdd` scripts, the sandbox, the doctor or the installer. The same directory also receives Claude
Code's own `--worktree` checkouts, so `/remove-worktree` and `worktree_status` cannot tell SDD worktrees
from host-native ones. The evaluation of the SDD flow on external repositories (fieldsync, 2026-11-04)
listed this as the structural cause behind the "worktree writes to the main checkout" family of
findings; those findings themselves are addressed by follow-up specs (see Non-Goals).

### Goals

- G1 **One root, one resolver.** Every consumer obtains the worktree root from a single function;
  no module spells the directory inline.
- G2 **Host-agnostic location.** The default root is `.parrot/worktrees/` — `.parrot/` is already the
  host-agnostic state directory, fully git-ignored (`.gitignore:392`, managed block `.parrot/`), and the
  sandbox's writable zone (`.parrot/ledger/`).
- G3 **Keep the documented override.** `WORKTREE_BASE_PATH` (absolute, or relative to the repository
  root) keeps working, now for every consumer, not only the dev-loop.
- G4 **Hard cut, no dual-root lookup.** No code path looks in `.claude/worktrees/` for live worktrees.
  `parrot doctor` and `parrot sdd install` detect registered worktrees under the legacy root, refuse to
  continue, and print the exact migration recipe per worktree.
- G5 **Rules, commands, agents and docs agree with the code** on both the Claude (`.claude/`) and
  the codex/gemini (`.agent/`, `.agents/`) sides, and the packaged assets under
  `parrot/sdd/_assets/` ship the same text.

### Non-Goals (explicitly out of scope)

- Fixing the installer portability gaps found in the same evaluation: host installers baking absolute
  paths by default, `parrot sdd install --portable` on a repo with no `.mcp.json`, and
  `find_project_root` resolving the main checkout from inside a worktree. Separate specs.
- Preparing worktrees of non-Python repositories (`[tool.parrot.worktree]` outside `pyproject.toml`).
  Separate spec.
- A `parrot sdd worktree migrate` command, `git worktree move` wrapper, or any automatic relocation.
  The user moves the directory; parrot only tells them how.
- Compatibility lookups in the legacy root (rejected by the user in the brainstorm: "corte limpio").
- Rewriting historical documents (`sdd/specs/*`, `sdd/tasks/completed/*`, `docs/superpowers/*`,
  `.claude/settings.local.json` permission strings) that mention `.claude/worktrees` as history.
- Claude Code's own `--worktree` feature keeps using `.claude/worktrees/`; this spec does not touch it
  (that is precisely why the two must no longer share a directory).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:561a17ec736291a2840a9242a9d4ca5d664f3d6ebb0a35bc982cb45cdd75805b evaluation_digest=sha256:a0c4c6d71d1c520bca8c2adf6ff90b61614d0709fe847812e2bcf0c4b194d07e rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, dev-loop, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools

## 2. Architectural Design

### Overview

A new resolver family lives next to `find_repo_root()` in `parrot/sdd/config.py` (pydantic-only
module, already imported by `sdd_meta`, `brief_meta` and the installer; `parrot/sdd/__init__.py` is
import-free so `parrot/conf.py` can import it without a cycle):

- `DEFAULT_WORKTREE_ROOT = ".parrot/worktrees"`, `LEGACY_WORKTREE_ROOT = ".claude/worktrees"`,
  `WORKTREE_ROOT_ENV = "WORKTREE_BASE_PATH"`.
- `worktree_root_setting(override=None) -> str` — the raw root: `override` if given, else
  `os.environ[WORKTREE_ROOT_ENV]` if set and non-blank, else the default. Relative values are
  repository-relative (POSIX string, no trailing slash); absolute values are returned normalized.
- `worktree_root(repo_root, override=None) -> Path` — the absolute, normalized root for a repository.
- `legacy_worktrees(repo_root) -> list[Path]` — registered worktrees (`git worktree list --porcelain`)
  whose resolved path is under `<repo_root>/.claude/worktrees/`. Empty when git is unavailable.
- `legacy_migration_recipe(repo_root, paths) -> list[str]` — one `mv '<old>' '<new>'` line per
  worktree plus a final `git worktree repair`, where `<new>` is `worktree_root(repo_root) / old.name`.

**Why `mv` is not enough.** `.git/worktrees/<name>/gitdir` stores the absolute path of the worktree's
`.git` file; after a bare `mv`, `git worktree list` reports the entry as prunable and `git -C <new>`
fails. `git worktree repair` (git ≥ 2.30; this checkout runs 2.43) rewrites both directions. The recipe
is the only thing parrot prints; it never runs it.

**Repo-relative plans stay repo-relative.** `WorktreePlan.path` becomes
`f"{worktree_root_setting()}/{name}"`. With the default or a relative override it is repo-relative
exactly as today; with an absolute override it is absolute, and every consumer already joins it as
`repo_root / plan.path` (`ensure_worktree.py:115`), which pathlib resolves to the absolute operand.
No consumer signature changes.

**`conf.py` derives, it does not define.** `WORKTREE_BASE_PATH` becomes
`str(worktree_root(BASE_DIR, override=config.get("WORKTREE_BASE_PATH", fallback=None)))` and
`DEV_LOOP_REPO_BASE_PATH` defaults to `<WORKTREE_BASE_PATH>/repos`. The dev-loop keeps reading
`conf.WORKTREE_BASE_PATH`; nothing under `parrot/flows/` changes.

**Hard cut.** `install_sdd_integration()` calls `legacy_worktrees(root)` before planning anything
(dry-run included) and raises `LegacyWorktreesError(RuntimeError)` whose message is the recipe; the
CLI prints it and exits 1. `parrot doctor` adds the failing check `sdd: legacy worktrees` with the
recipe as its `fix`, and `sdd: worktrees ignored` now probes the resolved root. `worktree_status`
reports a legacy entry with `flow_type="legacy"` (health only, never `ready_for_done`) so
`/sdd-status` shows what still has to move. `ensure_worktree`, `/sdd-done`, `/remove-worktree` only
ever look in the resolved root.

**Documents follow the code.** The in-repo `.claude/`, `.agent/`, `.agents/`, `CLAUDE.md`,
`sdd/WORKFLOW.md` and `docs/` sources are updated by hand; `scripts/sdd/check_asset_sync.py --write`
regenerates `parrot/sdd/_assets/` + `manifest.json` from them, and `--check` (CI) proves they match.
A new guard test fails on any SDD asset, rule, command or agent that still spells `.claude/worktrees`
outside the single sentence that describes the migration.

### Component Diagram
```
parrot/sdd/config.py                      (M1: resolver — the only place that knows the path)
  worktree_root_setting() / worktree_root() / legacy_worktrees() / legacy_migration_recipe()
        │
        ├──→ parrot/conf.py            WORKTREE_BASE_PATH, DEV_LOOP_REPO_BASE_PATH  → flows/dev_loop/* (unchanged)
        ├──→ sdd_meta.plan_worktree, brief_meta.plan_brief_worktree          (M2)  → ensure_worktree
        ├──→ worktree_status, remove_worktree, worktree_baseline,
        │    worktree_environment, native_claude_sandbox, ledger/integration,
        │    audit, dangerous_actions, e2e/supervisor, build_llm_wiki        (M3)
        ├──→ sdd/installer (GITIGNORE_BLOCK + refusal), self_/doctor (checks) (M4)
        └──→ .claude/ .agent/ .agents/ CLAUDE.md docs/ ──check_asset_sync──→ sdd/_assets/  (M5)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.config.find_repo_root` | sibling | resolver functions live in the same module |
| `parrot.conf` | derives | `WORKTREE_BASE_PATH` / `DEV_LOOP_REPO_BASE_PATH` computed through the resolver |
| `sdd_meta.plan_worktree`, `brief_meta.plan_brief_worktree` | uses | `WorktreePlan.path` built from `worktree_root_setting()` |
| `worktree_status.discover_worktree_reports` | uses + extends | scans resolved root; legacy entries → `flow_type="legacy"` |
| `installer.install_sdd_integration` | guards | raises `LegacyWorktreesError` before any write |
| `self_.doctor._check_sdd_git` | extends | new check + resolved-root probe |
| `scripts/sdd/check_asset_sync.py` | regenerates | `_assets/` from repo sources (unchanged tool) |

### Data Models
```python
# parrot/sdd/scripts/worktree_status.py  (modifies :70)
flow_type: Literal["feature", "hotfix", "non-sdd", "legacy"]   # "legacy": registered under .claude/worktrees/
```

### New Public Interfaces
```python
# parrot/sdd/config.py
DEFAULT_WORKTREE_ROOT: str
LEGACY_WORKTREE_ROOT: str
WORKTREE_ROOT_ENV: str
class LegacyWorktreesError(RuntimeError): ...
def worktree_root_setting(override: str | None = None) -> str: ...
def worktree_root(repo_root: Path, override: str | None = None) -> Path: ...
def legacy_worktrees(repo_root: Path) -> list[Path]: ...
def legacy_migration_recipe(repo_root: Path, paths: Sequence[Path]) -> list[str]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: resolver + conf | yes | names, defaults, env precedence, recipe text fixed in §2/§3 | — |
| M2: plan builders | yes | `WorktreePlan.path = f"{worktree_root_setting()}/{name}"`; `WORKTREE_ROOT` deleted everywhere | — |
| M3: script consumers | yes | mechanical replacement per the §6 Edit Sites table | — |
| M4: installer + doctor hard cut | yes | error class, check names, exit code, message shape fixed | — |
| M5: rules/commands/agents/docs + guard test | yes | textual sweep + `check_asset_sync.py --write`; guard test contract fixed | — |

### Module 1: Resolver and `conf.py` derivation
- **Path**: `packages/ai-parrot/src/parrot/sdd/config.py` (modify), `packages/ai-parrot/src/parrot/conf.py` (modify)
- **Responsibility**: the only definition of where worktrees live; legacy detection; recipe text.
- **Depends on**: nothing new (`subprocess`, `os`, `pathlib`).
- **Interface Skeleton**:
  ```python
  # parrot/sdd/config.py  (modifies parrot/sdd/config.py:93 — appended after find_repo_root)
  DEFAULT_WORKTREE_ROOT: str = ".parrot/worktrees"
  LEGACY_WORKTREE_ROOT: str = ".claude/worktrees"
  WORKTREE_ROOT_ENV: str = "WORKTREE_BASE_PATH"


  class LegacyWorktreesError(RuntimeError):
      """Registered git worktrees still live under ``.claude/worktrees/``; the message is the recipe."""


  def worktree_root_setting(override: str | None = None) -> str:
      """Raw worktree root: ``override``, else ``$WORKTREE_BASE_PATH``, else ``DEFAULT_WORKTREE_ROOT``.

      Relative values are repository-relative POSIX strings without a trailing slash; absolute values are
      returned ``os.path.normpath``-ed. Blank values count as unset.
      """


  def worktree_root(repo_root: Path, override: str | None = None) -> Path:
      """Absolute, normalized worktree root for ``repo_root`` (``repo_root / setting`` when relative)."""


  def legacy_worktrees(repo_root: Path) -> list[Path]:
      """Registered worktrees (``git worktree list --porcelain``) under ``repo_root/LEGACY_WORKTREE_ROOT``.

      Resolved paths, sorted. Empty when git is missing, the command fails, or ``repo_root`` is not a repo.
      Never raises.
      """


  def legacy_migration_recipe(repo_root: Path, paths: Sequence[Path]) -> list[str]:
      """Shell lines that move ``paths`` under ``worktree_root(repo_root)`` and repair git's bookkeeping.

      One ``mv '<old>' '<new>'`` per path, then ``git -C '<repo_root>' worktree repair`` (git >= 2.30),
      preceded by ``mkdir -p '<root>'``. Quoted with ``shlex.quote``.
      """
  ```
  ```python
  # parrot/conf.py  (modifies parrot/conf.py:938-939 and :979-985)
  from parrot.sdd.config import worktree_root  # parrot.sdd is import-free; parrot.sdd.config imports pydantic only
  WORKTREE_BASE_PATH: str = str(worktree_root(BASE_DIR, override=config.get("WORKTREE_BASE_PATH", fallback=None)))
  DEV_LOOP_REPO_BASE_PATH: str  # default f"{WORKTREE_BASE_PATH}/repos"; same relative→join / absolute→verbatim rule
  ```

### Module 2: Plan builders
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`, `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py`, `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` (modify)
- **Responsibility**: `WorktreePlan.path` comes from the resolver; `WORKTREE_ROOT` ceases to exist.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/ledger/sdd_meta.py  (modifies :379 — constant deleted; :444 path built from resolver)
  def plan_worktree(meta: FlowMeta, *, slug: str, feature_id: str | None = None, jira_key: str | None = None) -> WorktreePlan:
      """Unchanged signature. ``path`` is ``f"{worktree_root_setting()}/{name}"`` (repo-relative unless
      ``WORKTREE_BASE_PATH`` is absolute)."""  # verified: sdd_meta.py:391-397

  # parrot/sdd/scripts/sdd_meta.py  (modifies :15-30 — ``WORKTREE_ROOT`` removed from the re-export list)
  # parrot/sdd/scripts/brief_meta.py  (modifies :22 import, :199 path)
  def plan_brief_worktree(meta: BriefMeta, *, config: SddConfig | None = None) -> WorktreePlan:
      """Unchanged signature; same path rule as plan_worktree."""  # verified: brief_meta.py:204
  ```

### Module 3: Script and runtime consumers
- **Path**: `parrot/sdd/scripts/worktree_status.py`, `remove_worktree.py`, `worktree_baseline.py`, `worktree_environment.py`, `native_claude_sandbox.py`, `dangerous_actions.py`, `parrot/sdd/audit.py`, `parrot/knowledge/wiki/ledger/integration.py`, `packages/ai-parrot-server/src/parrot/e2e/supervisor.py`, `scripts/build_llm_wiki.py`, `.claude/hooks/dangerous-actions-blocker.sh` (modify)
- **Responsibility**: every inline `.claude/worktrees` becomes a resolver call (code) or the new path (regexes, docstrings, exclusion lists).
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/sdd/scripts/worktree_status.py  (modifies :21 import, :70 flow_type, :304 root)
  worktree_root_path = worktree_root(repo_root)                      # replaces (repo_root / WORKTREE_ROOT).resolve()
  # discover_worktree_reports(): a porcelain entry under repo_root/LEGACY_WORKTREE_ROOT → WorktreeReport(
  #     flow_type="legacy", ready_for_done=False, tasks=[], index_found=False)   # verified: :286

  # parrot/sdd/scripts/worktree_environment.py  (modifies :139 — WORKTREE_ADMIN_DIR deleted; :177 uses worktree_root(primary))
  # parrot/sdd/scripts/remove_worktree.py       (modifies :220 → worktree_root(_root()); :374 message)
  # parrot/sdd/scripts/worktree_baseline.py     (modifies :60 → worktree_root(main_root))
  # parrot/knowledge/wiki/ledger/integration.py (modifies :376 → worktree_root(primary) / f"_ledger-outbox-{uuid}")
  # parrot/sdd/audit.py                          (modifies :70 regex → r"\bpackages/ai-parrot\w*|\.parrot/worktrees/")
  # parrot/sdd/scripts/dangerous_actions.py     (modifies :125-128 regexes protect BOTH roots; :275 text; :316 → worktree_root(root).is_dir())
  # .claude/hooks/dangerous-actions-blocker.sh  (modifies :172-173, :231 — same two-root protection, new dir test)
  # scripts/build_llm_wiki.py                   (modifies :133 exclusion → ".parrot/worktrees")
  # e2e/supervisor.py                           (modifies :858 docstring path)
  ```
  The `rm -rf` guard protects both `.claude/worktrees` and `.parrot/worktrees` on purpose: the cut tells
  people to move, never to delete, the legacy tree.

### Module 4: Installer and doctor hard cut
- **Path**: `packages/ai-parrot/src/parrot/sdd/installer.py`, `packages/ai-parrot/src/parrot/self_/doctor.py` (modify)
- **Responsibility**: the managed `.gitignore` block names the new root; both entry points refuse while legacy worktrees exist and print the recipe.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/sdd/installer.py  (modifies :49-61 GITIGNORE_BLOCK line → "# SDD feature worktrees (parrot sdd worktree ensure)\n.parrot/worktrees/\n")
  def install_sdd_integration(root: Path, hosts=..., *, keep_edits=False, dry_run=False, portable=False, ...) -> list[str]:
      """Unchanged signature. New first step (before load_sdd_config at :1113, dry-run included):
      ``legacy = legacy_worktrees(root)``; non-empty → ``raise LegacyWorktreesError("\n".join(
      ["error: SDD worktrees still live under .claude/worktrees/ — move them first:", *recipe]))``.
      Raises: LegacyWorktreesError (the CLI prints str(exc) to stderr and exits 1)."""  # verified: :1064

  # parrot/self_/doctor.py  (modifies :338 _check_sdd_git, :356-360)
  def _check_sdd_git(root: Path, branch: str) -> list[DoctorCheck]:
      """Adds, in order after 'sdd: id ledger tracked':
      DoctorCheck(name="sdd: worktrees ignored", ok=<check-ignore f"{setting}/x">, detail=f"{setting}/ is|is NOT git-ignored", fix="parrot sdd install (adds the .gitignore block)")
      DoctorCheck(name="sdd: legacy worktrees", ok=not legacy, detail=f"{n} worktree(s) registered under .claude/worktrees/" | "none under .claude/worktrees/", fix="\n".join(recipe))
      where setting = worktree_root_setting() and legacy = legacy_worktrees(root)."""
  ```

### Module 5: Rules, commands, agents, docs, packaged assets, guard test
- **Path**: `.claude/rules/worktree-management.md`, `.claude/commands/{sdd-done,sdd-next,sdd-spec,remove-worktree,release,security-check}.md`, `.claude/agents/{sdd-worker,sdd-coder,sdd-planner,sdd-research,sdd-autopilot}.md`, `.agent/skills/worktree-management/SKILL.md`, `.agent/workflows/{sdd-done,sdd-next,sdd-spec,remove-worktree}.md`, `.agent/agents/*/agent.md`, `.agents/agents/*/agent.md`, `.agents/skills/{sdd-done,sdd-spec,sdd-task}/SKILL.md`, `CLAUDE.md`, `sdd/WORKFLOW.md` (if it names the path), `docs/sdd/{GUIDE,PLATFORM,CODEX,ANTIGRAVITY}.md`, `docs/getting-started.md`, `docs/install/global-runtime.md`, `docs/dev_loop/{claude-native-sandbox,sdd-compaction-capabilities}.md`, `docs/clients/{meta,openai-compatible}.md`, `packages/ai-parrot/src/parrot/sdd/_assets/**` (regenerated), `tests/sdd_scripts/test_command_contracts.py` (new guard test)
- **Responsibility**: every operational mention of the root says `.parrot/worktrees/`; `/sdd-done`'s `WORKTREES_DIR="$MAIN_ROOT/.claude/worktrees"` (`sdd-done.md:81`) becomes `.parrot/worktrees`; the worktree-management rule gains one "Migrating from `.claude/worktrees/`" paragraph with the `mv` + `git worktree repair` recipe (the only allowed mention of the legacy path).
- **Depends on**: M1 (names only; no code).
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_command_contracts.py  (new test next to test_no_legacy_naming_template_remains, :80)
  def test_no_legacy_worktree_root_remains() -> None:
      """No .md/.toml/.sh under .claude/, .agent/, .agents/, parrot/sdd/_assets/ and CLAUDE.md names
      `.claude/worktrees` except lines that also contain `git worktree repair` (the migration recipe).
      Files under a live worktree are skipped exactly as the sibling test does."""
  ```
  Regeneration command (run after the textual sweep, both must pass):
  `python scripts/sdd/check_asset_sync.py --write && python scripts/sdd/check_asset_sync.py --check`.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_worktree_root_default` | M1 | no env → `.parrot/worktrees`; `worktree_root(tmp)` == `tmp/.parrot/worktrees` |
| `test_worktree_root_env_relative` | M1 | `WORKTREE_BASE_PATH=wt/x` → `tmp/wt/x`; setting string is `wt/x` |
| `test_worktree_root_env_absolute` | M1 | absolute env honored verbatim (normalized); blank env ignored |
| `test_worktree_root_override_wins` | M1 | `override=` beats env |
| `test_legacy_worktrees_detects_registered` | M1 | real temp repo + `git worktree add .claude/worktrees/feat-FEAT-1-x` → listed; a plain dir there → not listed |
| `test_legacy_worktrees_no_git` | M1 | non-repo dir → `[]`, no exception |
| `test_legacy_migration_recipe_shape` | M1 | `mkdir -p`, one `mv` per path, final `git -C … worktree repair`, shlex-quoted |
| `test_conf_worktree_base_path_derives` | M1 | `conf.WORKTREE_BASE_PATH` endswith `.parrot/worktrees`; `DEV_LOOP_REPO_BASE_PATH` is `<it>/repos` |
| `test_plan_worktree_path` (updated) | M2 | `plan.path == ".parrot/worktrees/feat-FEAT-552-<slug>"`; absolute env → absolute path |
| `test_plan_brief_worktree_paths` (updated :112,:115) | M2 | `.parrot/worktrees/hotfix-…` / `fix-…` |
| `test_sdd_meta_reexports` (updated :22) | M2 | `WORKTREE_ROOT` no longer exported; `AttributeError` on access |
| `test_worktree_status_scans_resolved_root` (updated :121,:186) | M3 | patch env instead of `WORKTREE_ROOT`; orphans under `.parrot/worktrees` found |
| `test_worktree_status_legacy_entry` | M3 | porcelain entry under `.claude/worktrees` → `flow_type="legacy"`, `ready_for_done=False` |
| `test_worktree_admin_dirs_resolved_root` (updated :344) | M3 | sandbox allow-list contains `<primary>/.parrot/worktrees` |
| `test_audit_monorepo_path` (updated :27) | M3 | `cd .parrot/worktrees/feat-FEAT-1-x` → `monorepo-path`; `.claude/worktrees` no longer flagged |
| `test_dangerous_rm_both_roots` | M3 | `rm -rf .claude/worktrees/x` and `rm -rf .parrot/worktrees/x` both denied |
| `test_gitignore_block_new_root` (updated :497,:552) | M4 | managed block ignores `.parrot/worktrees/feat-x/README.md` |
| `test_install_refuses_legacy_worktrees` | M4 | temp repo with a legacy worktree → `LegacyWorktreesError`, message has the `mv` and `repair` lines, nothing written (dry-run too) |
| `test_install_cli_exit_1_on_legacy` | M4 | CLI returns 1 and prints the recipe to stderr |
| `test_doctor_legacy_worktrees_check` (updated :44) | M4 | failing `sdd: legacy worktrees` with recipe in `fix`; `sdd: worktrees ignored` probes `.parrot/worktrees/x` |
| `test_no_legacy_worktree_root_remains` | M5 | guard over rules/commands/agents/assets |
| `test_wheel_only_foreign_repo` (updated :157-326) | M5 | foreign-repo flow creates and resolves `.parrot/worktrees/feat-…` |

### Integration Tests
| Test | Description |
|---|---|
| `test_ensure_worktree_creates_under_parrot` | `parrot sdd worktree ensure` in a temp repo creates `<repo>/.parrot/worktrees/feat-FEAT-N-slug` and `git worktree list` agrees |
| `test_twins_mention_parrot_root` (extends `tests/sdd/test_ledger_workflow_twins.py`) | `.claude/commands/sdd-done.md` and `.agent/workflows/sdd-done.md` both set `WORKTREES_DIR` to `.parrot/worktrees` |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_config.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/sdd/test_audit.py
- packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
- packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
- packages/ai-parrot/tests/self_/test_doctor_sdd.py
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
- tests/sdd_scripts/test_worktree_plan.py
- tests/sdd_scripts/test_brief_meta.py
- tests/sdd_scripts/test_worktree_status.py
- tests/sdd_scripts/test_command_contracts.py
- tests/sdd/test_ledger_workflow_twins.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def legacy_repo(tmp_path: Path) -> Path:
    """A git repo with one commit, an `origin` pointing at itself, and one registered worktree
    under `.claude/worktrees/feat-FEAT-1-x` (created with `git worktree add`, never by hand)."""
```
Every resolver test clears `WORKTREE_BASE_PATH` with `monkeypatch.delenv(..., raising=False)` first —
the developer's own shell may export it.

---

## 5. Acceptance Criteria

- [ ] AC1 `grep -rn '\.claude/worktrees' packages/*/src scripts .claude .agent .agents CLAUDE.md` (excluding `.claude/worktrees/` itself and `settings.local.json`) returns only: the `LEGACY_WORKTREE_ROOT` constant, the two `rm -rf` guard regexes, the `dangerous-actions-blocker.sh` twin regex, and the migration-recipe sentence/paragraph in the worktree-management rule twins and their `_assets/` copy.
- [ ] AC2 `sdd_meta.WORKTREE_ROOT`, `parrot.sdd.scripts.sdd_meta.WORKTREE_ROOT` and `worktree_environment.WORKTREE_ADMIN_DIR` no longer exist (`AttributeError`).
- [ ] AC3 `conf.WORKTREE_BASE_PATH` equals `str(worktree_root(BASE_DIR, override=<navconfig value>))`; unset → ends with `.parrot/worktrees`; `DEV_LOOP_REPO_BASE_PATH` defaults to `<WORKTREE_BASE_PATH>/repos`.
- [ ] AC4 `parrot sdd worktree ensure --slug x --feature-id FEAT-1` in a fresh repo creates `<repo>/.parrot/worktrees/feat-FEAT-1-x`; with `WORKTREE_BASE_PATH=/abs/dir` it creates `/abs/dir/feat-FEAT-1-x`.
- [ ] AC5 `parrot sdd install` (any host, `--dry-run` included) on a repo with ≥1 registered worktree under `.claude/worktrees/` writes nothing, exits 1, and prints `mkdir -p`, one `mv` per worktree and `git -C <repo> worktree repair`.
- [ ] AC6 `parrot doctor --scope sdd` on the same repo fails with `sdd: legacy worktrees` and the same recipe in `fix`; after the user runs the recipe the check passes and `git worktree list` shows no prunable entry.
- [ ] AC7 The managed `.gitignore` block written by `parrot sdd install` contains `.parrot/worktrees/` and no longer `.claude/worktrees/`; `sdd: worktrees ignored` probes `<setting>/x`.
- [ ] AC8 `parrot sdd worktree status` lists a legacy entry as `flow_type: legacy` with `ready_for_done: false`.
- [ ] AC9 `/sdd-done`, `/sdd-next`, `/remove-worktree` command twins (`.claude/commands`, `.agent/workflows`, `.agents/skills`) and the sdd-worker/planner/research/autopilot agent twins reference `.parrot/worktrees` only; `python scripts/sdd/check_asset_sync.py --check` passes.
- [ ] AC10 `tests/sdd_scripts/test_command_contracts.py::test_no_legacy_worktree_root_remains` exists and passes.
- [ ] AC11 All Validation Contract tests pass with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] AC12 No dual-root lookup: no production code path reads `.claude/worktrees` to *find* a worktree (only to detect legacy ones for the refusal/report).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.sdd.config import SddConfig, find_repo_root, load_sdd_config  # verified: knowledge/wiki/ledger/sdd_meta.py:23
from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT, WorktreePlan      # verified: sdd/scripts/brief_meta.py:22 (WORKTREE_ROOT to be removed)
from parrot.sdd.scripts.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # verified: sdd/scripts/ensure_worktree.py:23
from navconfig import BASE_DIR, config                                   # verified: parrot/conf.py:6
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/config.py
class SddConfigError(ValueError): ...                                   # line 15
class SddConfig(BaseModel): ...                                         # line 19
def find_repo_root(start: Path | None = None) -> Path | None            # line 93 — walks up to first `.git` (dir or file)
def load_sdd_config(root: Path | None = None) -> SddConfig              # line 106

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
WORKTREE_ROOT: str = ".claude/worktrees"                                # line 379 — DELETE
class WorktreePlan(BaseModel): name: str; path: str; base_ref: str      # lines 383-388
def plan_worktree(meta: FlowMeta, *, slug: str, feature_id: str | None = None, jira_key: str | None = None) -> WorktreePlan  # 391-397
    path = f"{WORKTREE_ROOT}/{name}"                                    # line 444

# packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py
def plan_brief_worktree(meta: BriefMeta, *, config: SddConfig | None = None) -> WorktreePlan  # line 204; path at :199

# packages/ai-parrot/src/parrot/conf.py
_wt: str = config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))   # line 938
WORKTREE_BASE_PATH: str = os.path.normpath(_wt) if os.path.isabs(_wt) else ...               # line 939
_repos: str = config.get("DEV_LOOP_REPO_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees/repos"))  # 979-982
DEV_LOOP_REPO_BASE_PATH: str = ...                                                           # 983-985

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
WORKTREE_ADMIN_DIR = Path(".claude") / "worktrees"                      # line 139 — DELETE
def worktree_admin_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]   # line 154; uses WORKTREE_ADMIN_DIR at :177
# module imports stdlib only (lines 9-18); it is always launched as `sys.executable -m parrot.sdd.scripts.worktree_environment --hook` (native_claude_sandbox.py:412), so importing parrot.sdd.config is safe

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py
class WorktreeReport(BaseModel): flow_type: Literal["feature", "hotfix", "non-sdd"]  # line 70
def _is_under_worktree_root(path: Path, worktree_root: Path) -> bool    # line 236
def _parse_porcelain(output: str) -> list[tuple[Path, str | None]]      # line 253
def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]  # line 286; root at :304

# packages/ai-parrot/src/parrot/sdd/installer.py
GITIGNORE_BLOCK = (...)                                                  # lines 49-61; worktrees line at :51
def install_sdd_integration(root: Path, hosts=("claude",), *, keep_edits=False, dry_run=False, portable=False, base_branch=None, push_base=False, hotfix_base=None, dangerous_guard=True, sdd_coder=True) -> list[str]  # 1064-1075
    from parrot.sdd.config import load_sdd_config  # TASK-4299           # line 1111
    config = load_sdd_config(root)                                       # line 1113

# packages/ai-parrot/src/parrot/self_/doctor.py
class DoctorCheck(BaseModel): name: str; ok: bool; detail: str = ""; fix: str = ""; informational: bool = False  # 40-47
def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]    # line 195
def _check_sdd_git(root: Path, branch: str) -> list[DoctorCheck]        # line 338; worktrees check at 356-360
def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]  # line 664

# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
_RM_CRITICAL = re.compile(r"rm\s+...(\.venv|\.git(/|\s|$)|\.claude/worktrees)")   # 125-127
_WIN_CRITICAL = re.compile(r"(\.venv|\.git([\\/]|\s|$)|\.claude[\\/]worktrees)", re.IGNORECASE)  # 128
# merge/pull guard: (root / ".claude" / "worktrees").is_dir()           # line 316

# packages/ai-parrot/src/parrot/sdd/audit.py
MONOREPO_PATH_RE = re.compile(r"\bpackages/ai-parrot\w*|\.claude/worktrees/")   # line 70

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py
tmp = primary / ".claude" / "worktrees" / f"_ledger-outbox-{uuid.uuid4()}"      # line 376

# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
worktree_dir = _root() / ".claude" / "worktrees"                        # line 220; message at :374

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_baseline.py
def _default_scratch(worktree: Path, baseline_mod: ModuleType) -> Path  # line 53; returns main_root / ".claude" / "worktrees" at :60

# packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py
target_path = (repo_root / plan.path).resolve()                          # line 115 — absolute plan.path survives the join
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `worktree_root()` | `conf.WORKTREE_BASE_PATH` | module-level assignment | `parrot/conf.py:938-939` |
| `worktree_root_setting()` | `plan_worktree` / `plan_brief_worktree` | f-string path | `sdd_meta.py:444`, `brief_meta.py:199` |
| `legacy_worktrees()` + `LegacyWorktreesError` | `install_sdd_integration` | first statement, before `load_sdd_config` | `installer.py:1111-1113` |
| `legacy_worktrees()` + recipe | `_check_sdd_git` | new `DoctorCheck` | `doctor.py:356-360` |
| `worktree_root()` | `worktree_admin_dirs` | replaces `WORKTREE_ADMIN_DIR` | `worktree_environment.py:177` |
| `worktree_root()` | `discover_worktree_reports` | replaces `repo_root / WORKTREE_ROOT` | `worktree_status.py:304` |
| repo sources → `_assets/` | `scripts/sdd/check_asset_sync.py --write` | regeneration (existing tool) | `scripts/sdd/check_asset_sync.py:1-7` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.sdd.paths`~~, ~~`parrot.sdd.worktree_root`~~ (module) — the resolver goes into the existing `parrot/sdd/config.py`.
- ~~`parrot.conf.WORKTREE_ROOT`~~ — conf only ever exposed `WORKTREE_BASE_PATH`.
- ~~`WorktreePlan.absolute_path`~~ / ~~`plan_worktree(repo_root=...)`~~ — signature stays; the path string carries the root.
- ~~`parrot sdd worktree migrate`~~ / ~~`git worktree move` wrapper~~ — out of scope by decision.
- ~~`DoctorCheck.severity`~~ — only `ok` / `informational` exist.
- ~~`installer.LEGACY_WORKTREES_NOTE`~~ — the refusal is an exception, not a log line.
- ~~`manifest.json` entries for `.claude/hooks/dangerous-actions-blocker.sh`~~ — the shell hook is repo-local; `_assets/claude/hooks/` holds only `sdd-worker-format.sh`.
- `.agent/skills/worktree-management/SKILL.md` is NOT a manifest target (only `.claude/rules/worktree-management.md` is, `manifest.json:505-506`): update it by hand.

### Edit Sites (Blueprint Anchors)

Verified against: `daa9d7194` (dev, 2026-11-04)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | `def find_repo_root(start: Path \| None = None) -> Path \| None:` | `config.py:93` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `_wt: str = config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))` | `conf.py:938` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `    fallback=str(BASE_DIR / ".claude/worktrees/repos"),` | `conf.py:981` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | `WORKTREE_ROOT: str = ".claude/worktrees"` | `sdd_meta.py:379` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | `    path = f"{WORKTREE_ROOT}/{name}"` | `sdd_meta.py:444` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` | MODIFY | `    WORKTREE_ROOT,` | `scripts/sdd_meta.py:20` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` | MODIFY | `from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT, WorktreePlan` | `brief_meta.py:22` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` | MODIFY | `        path=f"{WORKTREE_ROOT}/{name}",` | `brief_meta.py:199` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | MODIFY | `    worktree_root = (repo_root / WORKTREE_ROOT).resolve()` | `worktree_status.py:304` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | MODIFY | `    flow_type: Literal["feature", "hotfix", "non-sdd"]` | `worktree_status.py:70` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `WORKTREE_ADMIN_DIR = Path(".claude") / "worktrees"` | `worktree_environment.py:139` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `    admin_dir = (primary / WORKTREE_ADMIN_DIR).resolve()` | `worktree_environment.py:177` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | MODIFY | `    worktree_dir = _root() / ".claude" / "worktrees"` | `remove_worktree.py:220` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_baseline.py` | MODIFY | `    return main_root / ".claude" / "worktrees"` | `worktree_baseline.py:60` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | MODIFY | `        tmp = primary / ".claude" / "worktrees" / f"_ledger-outbox-{uuid.uuid4()}"` | `integration.py:376` | 1 |
| `packages/ai-parrot/src/parrot/sdd/audit.py` | MODIFY | `MONOREPO_PATH_RE = re.compile(r"\bpackages/ai-parrot\w*|\.claude/worktrees/")` | `audit.py:70` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | `_WIN_CRITICAL = re.compile(r"(\.venv|\.git([\\/]|\s|$)|\.claude[\\/]worktrees)", re.IGNORECASE)` | `dangerous_actions.py:128` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | `    if re.search(r"git\s+(merge|pull)\b", scan) and root is not None and (root / ".claude" / "worktrees").is_dir():` | `dangerous_actions.py:316` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    "# SDD feature worktrees (parrot sdd worktree ensure)\n.claude/worktrees/\n"` | `installer.py:51` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    config = load_sdd_config(root)` | `installer.py:1113` | 1 |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `    ignored = _git(root, "check-ignore", "-q", ".claude/worktrees/x")` | `doctor.py:356` | 1 |
| `packages/ai-parrot-server/src/parrot/e2e/supervisor.py` | MODIFY | `        (``.claude/worktrees/<feature>--TASK-<id>-<uuid>/``) routinely` | `supervisor.py:858` | 1 |
| `scripts/build_llm_wiki.py` | MODIFY | `    ".claude/worktrees",` | `build_llm_wiki.py:133` | 1 |
| `.claude/hooks/dangerous-actions-blocker.sh` | MODIFY | `    if echo "$SCAN" | grep -qE 'git\s+(merge|pull)\b' && [[ -d .claude/worktrees ]]; then` | `dangerous-actions-blocker.sh:231` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `WORKTREES_DIR="$MAIN_ROOT/.claude/worktrees"` | `sdd-done.md:81` | 1 |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | `def test_no_legacy_naming_template_remains() -> None:` | `test_command_contracts.py:80` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/**` | REGENERATE | — (`check_asset_sync.py --write`) | — | — |

Documentation files in M5 are a textual sweep (`.claude/worktrees` → `.parrot/worktrees`); their anchors
are the literal string, verified by `grep -c` at task time.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `parrot/sdd/__init__.py` must stay import-free (its docstring says so); the resolver goes into
  `parrot/sdd/config.py`, whose only third-party import is pydantic.
- `conf.py` keeps the FEAT-253 G1 rule: relative env values join `BASE_DIR`, absolute ones are honored
  verbatim. The resolver implements that rule once; `conf.py` just calls it.
- Scripts under `parrot/sdd/scripts/` keep working as `python -m parrot.sdd.scripts.<name>` from a
  wheel-only install (`test_wheel_only_foreign_repo.py`); importing `parrot.sdd.config` there is fine,
  importing `parrot.conf` (navconfig) is not.
- The `rm -rf` guard regexes and the `.sh` hook twin are edited together (memory
  `sdd-worker-prompt-two-suites`: edit BOTH twins).
- After the textual sweep run `python scripts/sdd/check_asset_sync.py --write` then `--check`; never
  hand-edit `_assets/` or `manifest.json`.
- Tests that touch the resolver `monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)` first.
- Hard cut, no shims (memory `no-external-consumers-hard-cuts-ok`): `WORKTREE_ROOT` and
  `WORKTREE_ADMIN_DIR` are deleted, not deprecated.

### Known Risks / Gotchas
- **`.env`-only override.** `conf.py` reads `WORKTREE_BASE_PATH` through navconfig (env *and* `.env`
  files); the scripts read `os.environ` only. A value set only in a navconfig `.env` file moves the
  dev-loop but not `parrot sdd worktree ensure`. Mitigation: document "export it in the shell" in the
  worktree-management rule; `parrot doctor` is not extended for this (out of scope).
- **This repository has 44 registered worktrees** under `.claude/worktrees/` (2026-11-04). The first
  `parrot sdd install` / `parrot doctor` after merging will refuse until they are moved — that is the
  intended behaviour; the PR description must carry the recipe.
- **A bare `mv` strands git bookkeeping** (`.git/worktrees/<name>/gitdir`); the recipe always ends
  with `git worktree repair`. Nested pool sub-worktrees (`<feature>--pool/TASK-…`) move with their
  parent directory and are repaired by the same command.
- **Sandbox allow-list.** `worktree_admin_dirs` feeds the native sandbox writable paths
  (`native_claude_sandbox.py:402`); if it resolved the wrong root, `/sdd-done` from inside a worktree
  could no longer add the ledger-snapshot worktree. The `test_worktree_environment.py` fixture
  (`:344`) must model the new root.
- **`test_worktree_status.py` patches `scripts.sdd.worktree_status.WORKTREE_ROOT`** (`:121`, `:186`);
  with the constant gone those tests must set the env var (or pass an override) instead.
- **Long socket paths.** `e2e/supervisor.py:858` documents that worktree paths overflow `sun_path`;
  `.parrot/worktrees` is one character shorter than `.claude/worktrees`, so nothing changes there.
- **`.gitignore` of this repo** already ignores `.parrot/*` (`:392`) and the managed block adds
  `.parrot/`; `.parrot/worktrees/` needs no extra line, but the managed block names it explicitly so
  foreign repos without a `.parrot/` rule still ignore it.
- **Claude Code's native `--worktree`** keeps writing to `.claude/worktrees/`; after this feature such
  checkouts show up as `legacy` in `worktree_status` and block `parrot sdd install`. That is accepted:
  the worktree-management rule already forbids `claude --worktree` for SDD work.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| git | ≥ 2.30 | `git worktree repair` in the printed recipe (checkout has 2.43) |

---

## Decisions

```yaml
schema_version: 1
document_id: worktree-root-under-parrot
entries:
  - id: single-worktree-root-resolver
    statement: The SDD worktree root is obtained only through parrot.sdd.config.worktree_root()/worktree_root_setting(); no module spells the directory inline.
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/config.py, file:packages/ai-parrot/src/parrot/conf.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py]
    contradicts: []
    supersedes: []
    rationale: "Three constants (conf.WORKTREE_BASE_PATH, sdd_meta.WORKTREE_ROOT, worktree_environment.WORKTREE_ADMIN_DIR) drifted; WORKTREE_BASE_PATH only moved the dev-loop."
    rejected_alternatives: ["keep WORKTREE_ROOT and make conf derive from it (conf must honour the env override)", "drop the env override (FEAT-253 dev-loop confinement relies on it)"]
  - id: worktree-root-is-parrot-dir
    statement: The default SDD worktree root is .parrot/worktrees/, never a host-specific directory such as .claude/.
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/config.py]
    contradicts: []
    supersedes: []
    rationale: ".parrot/ is host-agnostic, fully git-ignored and already the sandbox-writable state dir; .claude/worktrees/ is also used by Claude Code's own --worktree feature."
    rejected_alternatives: [".worktrees/ at the repo root (another top-level dir to ignore and sandbox)", "keep .claude/worktrees/ and only unify the constants"]
  - id: legacy-worktrees-hard-cut
    statement: No production code path looks for live worktrees under .claude/worktrees/; parrot sdd install and parrot doctor refuse while registered worktrees exist there and print the mv + git worktree repair recipe.
    relation: forbids
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/installer.py, file:packages/ai-parrot/src/parrot/self_/doctor.py]
    contradicts: []
    supersedes: []
    rationale: "User decision in the 2026-11-04 brainstorm: clean cut, people move the directory themselves; dual-root lookups would keep the drift alive."
    rejected_alternatives: ["dual-root lookup for one release", "parrot sdd worktree migrate command", "doctor warns but install proceeds"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:561a17ec736291a2840a9242a9d4ca5d664f3d6ebb0a35bc982cb45cdd75805b evaluation_digest=sha256:a0c4c6d71d1c520bca8c2adf6ff90b61614d0709fe847812e2bcf0c4b194d07e rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, dev-loop, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: doctor, installer, portability, worktree
- Targets resolved: 5/5
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "dev-loop",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 5,
    "targets_total": 5,
    "unmapped_tags": [
      "doctor",
      "installer",
      "portability",
      "worktree"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:a0c4c6d71d1c520bca8c2adf6ff90b61614d0709fe847812e2bcf0c4b194d07e",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:561a17ec736291a2840a9242a9d4ca5d664f3d6ebb0a35bc982cb45cdd75805b",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:7409d986ece435c577c60a1f007df6fa973b573a0cc6a4fd5636582393c9f656",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Keep the `WORKTREE_BASE_PATH` override? — *Resolved in brainstorm (Claude's call, stated)*: yes, now honoured by every consumer; relative values are repo-relative.
- [x] Migration: dual-root lookup or hard cut? — *Resolved by user*: hard cut; `doctor` and `sdd install` refuse and print `mv` + `git worktree repair`.
- [x] Block or warn in `parrot doctor` / `parrot sdd install`? — *Resolved by user*: block ("sí, correcto" to the refuse-and-print design).
- [ ] Should `ensure_worktree` also refuse while legacy worktrees exist, or only `install`/`doctor`? — *Owner: Jesus* (spec default: only `install`/`doctor`; `ensure` just creates under the new root — can be decided at task time).
- [ ] Target version 2.1.0 vs the next patch: this is a behavioural cut for every installed repo — *Owner: Jesus*.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `—` · Status: skipped (no accepted exploration document — the
> design was settled in an interactive chat brainstorm on 2026-11-04, not in a `sdd/proposals/` file)
> · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-802 (`feat-FEAT-802-worktree-root-under-parrot`); the
  sdd-coder engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `worktree_root_setting` from `parrot.sdd.config`)
  - M3 → M1 (imports `worktree_root`, `LEGACY_WORKTREE_ROOT`)
  - M4 → M1 (imports `legacy_worktrees`, `legacy_migration_recipe`, `LegacyWorktreesError`, `worktree_root_setting`)
  - M5 → M1 (names only; no import) — M2, M3, M4, M5 are mutually independent and may run concurrently once M1 is merged.
- **Shared files**: none between modules. (`worktree_status.py`, `dangerous_actions.py` are M3-only;
  `installer.py`, `doctor.py` are M4-only; `conf.py`, `config.py` are M1-only.)
- **Exclusive resources**: `check_asset_sync.py --write` rewrites `_assets/manifest.json` — the M5 task that runs it is `parallel: false`.
- **Cross-feature dependencies**: none to merge first. The follow-up specs (installer portability gaps,
  `find_project_root` in worktrees, non-Python worktrees) build on this one.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-04 | Jesus Lara / Claude | Initial draft from the 2026-11-04 brainstorm (unify roots, `.parrot/worktrees/`, hard cut) |
