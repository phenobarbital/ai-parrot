---
title: "Portable SDD Flow"
slug: portable-sdd-flow
type: feature
base_branch: dev
projects: []
tags: []
status: draft
created: 2026-09-19
---

# Feature Specification: Portable SDD Flow

**Feature ID**: FEAT-583
**Date**: 2026-09-19
**Author**: Jesus
**Status**: draft
**Target version**: Next release (owner-selected release milestone; version assigned by release tooling)

Source: `sdd/proposals/portable-sdd-flow.brainstorm.md` (accepted).
The source has no projects/tags; these remain empty. Its missing base branch
was resolved with `resolve_flow(type_override="feature")` to `dev`.

---

## 1. Motivation & Business Requirements

### Problem Statement

The SDD scripts live at `scripts/sdd/` rather than in an installable Python
distribution. Reusing the workflow requires manually copying scripts, host
commands, agents, templates and rules, without an installer, ownership record,
or reliable upgrade path. Several scripts also load code through checkout-relative
paths, so relocating their entry points alone does not make them portable.

### Goals

- Ship the whole reusable SDD workflow as `ai-parrot-sdd`, importing as `parrot_sdd`.
- Install shared assets plus one host's assets using `sdd claude install`,
  `sdd codex install`, or `sdd google install`.
- Keep Python implementations in the installed package; consuming repositories
  receive workflow assets, not copied Python implementations.
- Make the package the asset source of truth in ai-parrot; tracked relative
  symlinks preserve host discovery and worktree-local editing.
- Generate one `sdd/CONFIG.md` from user-owned `.parrot/sdd.json`.
- Track installed content hashes; safely repeat installation, upgrade and uninstall.
- Keep all satellite dependencies independent of core. Core integrations import
  the satellite lazily and only when the SDD capability is needed.
- Preserve live workflow behavior and ID allocation safety through the hard cut.

### Non-Goals (explicitly out of scope)

- No general `sdd <script-name>` command facade for the Python utilities.
- No compatibility shims for `scripts.sdd`.
- No changes to historical specs, tasks, proposals, or retained research records.
- No REPL rlimit calibration migration into the satellite; relocate that utility
  to `scripts/calibrate_rlimit_as.py` when removing `scripts/sdd/`.
- No SDD subcommands added to `parrot`; existing wiki/hook commands keep their remit.
- No full-screen interactive terminal application for installation.

---

## 2. Architectural Design

### Overview

Add a regular top-level `parrot_sdd` package under
`packages/ai-parrot-sdd/src/`. It owns metadata, scripts, assets, configuration,
manifest management and the `sdd` binary. Use `importlib.resources` for installed
assets; never infer the consuming repository from the package's `__file__`.
Resolve a target repository from explicit `--path` or Git discovery from CWD.
Explicit script root/worktree arguments retain their meaning.

The owner clarified that the new CLI must not use Click. Argument parsing uses
stdlib `argparse` with Rich output. Declare `rich>=13.0` as the third satellite
runtime dependency alongside Pydantic and PyYAML. Rich formats status tables,
changed-path summaries and diagnostics; disable forced color/animation when
output is redirected. Render paths as literal text, not Rich markup. Existing
core Click usage does not constrain the independent satellite CLI.

The two brainstorm asset layouts describe separate dimensions. Canonical storage
is `assets/{generic,templated,seeds}/{shared,claude,codex,google}/...`.
An explicit packaged `assets/catalog.json` maps each source resource to one tier,
destination path and set of host consumers. Shared content consumed by both
Codex and Google has one source and one destination entry with both consumers.
No hard-coded file-count assumption is allowed; enumerate current assets during
task decomposition. Existing counts in the brainstorm are estimates.

### Component Diagram

```text
sdd CLI ──> config + install engine ──> packaged catalog/resources
                         │
                         └──> target repo assets + CONFIG.md + manifest

core SDD consumers ──lazy──> parrot_sdd.meta / packaged agent resources
portable scripts ────────> portable metadata + portable utility dependencies
ai-parrot host files ────> relative symlinks to package assets
```

### Integration Points

| Existing component | Integration | Required behavior |
|---|---|---|
| Wiki SDD ingestion | Lazy metadata import | Missing satellite skips SDD ingestion with zero stats; unrelated wiki operations remain usable |
| Dev-loop branch policy/parsers | Shared metadata | Remove duplicate logic while retaining missing/invalid frontmatter semantics |
| Dev-loop QA | Installed module invocation | Invoke `parrot_sdd.scripts.lint_new` with existing argument quoting |
| Dev-loop agent loader | Satellite resource lookup | One canonical prompt; absent satellite fails only at SDD prompt loading with an install hint |
| Host commands, skills, agents, workflows | Resources and symlinks | Preserve host-specific syntax and discovery locations |
| Test selector/graph checker | Extract `parrot_sdd.test_scope` | Share one installed kernel; keep repository policy in config |
| Task closure ledger | Core-owned optional adapter | Notify after successful closure; adapter failure never reverses closure |
| Workspace and release tools | New distribution | Include wheel/sdist, tests, package data and version source |

### Data Models

All new structured records use Pydantic v2. Proposed contracts:

| Model | Fields and constraints |
|---|---|
| `SDDConfig` | `schema_version: Literal[1] = 1`; `base_branch: str = "dev"`; `hotfix_base: str = "main"`; `source_roots: list[str] = ["src"]`; `test_command: str = "pytest"`; `issue_tracker: str = "none"` |
| `AssetEntry` | `source: str`; `destination: str`; `tier: Literal["generic", "templated", "seeds"]`; `hosts: list[Literal["claude", "codex", "google"]]` |
| `ManifestEntry` | `path: str`; `sha256: str`; `hosts: list[Host]`; `tier: str`; `package_version: str` |
| `SDDManifest` | `schema_version: Literal[1]`; `package_version: str`; `hosts: list[Host]`; `files: list[ManifestEntry]` |

`Host` is `Literal["claude", "codex", "google"]`. Reject unknown config keys,
empty branch names, `base_branch == "main"`, and `hotfix_base != "main"` in v1,
matching the existing SDD lane rules. Configurable branch names must not imply
support for a non-main hotfix that `FlowMeta` currently rejects. Source roots
must be relative paths without traversal. The test command is descriptive data;
installation never executes it. Escape Markdown table values in CONFIG.md.

### New Public Interfaces

Proposed signatures, not existing APIs:

```python
def load_config(root: Path) -> SDDConfig:
    """Read .parrot/sdd.json; use portable defaults if absent; reject invalid input."""

def render_config(config: SDDConfig) -> str:
    """Return deterministic CONFIG.md, with every effective setting represented."""

def install_sdd(
    root: Path, host: Host, config: SDDConfig, *, dry_run: bool = False, force: bool = False
) -> list[str]:
    """Install shared and host resources; return sorted relative changed/would-change paths."""

def uninstall_sdd(root: Path, *, dry_run: bool = False) -> list[str]:
    """Remove hash-matching owned files; retain and report modified files."""

def read_manifest(root: Path) -> SDDManifest | None:
    """Read validated installation state; return None only if no manifest exists."""

def main(argv: list[str] | None = None) -> int:
    """Dispatch the standalone sdd command and return its process exit status."""
```

`install_sdd` returns asset paths including CONFIG.md; the manifest bookkeeping
path is excluded. No-op installation returns an empty list and does not rewrite
the manifest. Dry-run computes the same plan without creating any directory,
file or manifest. Diagnostics use logging; the CLI owns presentation.

### Ownership, upgrades and failure behavior

- Manifest path: `.parrot/sdd-manifest.json`; hashes are SHA-256 over installed bytes.
- An existing untracked destination is a conflict even if content happens to
  match; never silently claim another tool's file. `--force` explicitly authorizes
  replacement of file conflicts, but never unsafe paths or directory replacement.
- An owned file matching its recorded hash can be upgraded. Locally modified
  owned files cause a preflight conflict unless `--force` is supplied.
- Validate all resources, destinations, hashes and templates before writes.
  Invalid config/manifest, unknown placeholders, duplicate conflicting destinations,
  symlink destinations or parent symlinks, absolute paths and `..` escapes fail closed.
- Write files with atomic replacement; save the manifest last. If an I/O failure
  interrupts application, report the exact affected paths and preserve recoverable
  ownership information. Do not claim a fully successful installation.
- Installing another host merges manifest ownership; never drops previous hosts
  or claims non-SDD host configuration. Shared paths occur once with unioned owners.
- `sdd uninstall` uninstalls all manifest-owned hosts. There is no host-specific
  uninstall in v1. Modified files remain on disk and in the residual manifest;
  report them and return an incomplete-operation exit status.
- Do not delete user-authored config, SDD documents, task indexes, ID ledger,
  collision baseline, or unowned files. Seeds become user-owned after creation;
  upgrades/uninstall do not overwrite/remove them, including with `--force`.
- Generic assets copy verbatim. Scalar-only regex substitution is limited to
  known tokens in templated resources, primarily CONFIG.md. Commands read
  CONFIG.md rather than carrying repository-specific defaults.
- The installer neither commits nor pushes. Seed/bootstrap instructions explain
  how to initialize and commit the ID ledger before using the allocator, without
  resetting an existing ledger or shipping ai-parrot's counters.
- `sdd status [--path PATH]` is read-only and reports hosts/version plus missing,
  unchanged and modified paths. All install variants accept `--path`, `--dry-run`,
  `--force`; uninstall accepts `--path`, `--dry-run`.
- CLI exit codes: `0` success (including no-op), `1` operational conflict/error or
  incomplete uninstall, `2` invalid arguments/configuration. Missing installation
  is a successful empty status/uninstall; a malformed manifest is an error.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 Package + metadata | yes | Regular package; move metadata preserving §6 signatures; lazy ingest boundary | — |
| M2 Scripts + portable dependencies | yes | Extracted kernel, config policy, installed entry points and closure notification contract below | — |
| M3 Core consumers | yes | Lazy kernel/metadata imports; core-owned notification entry point; explicit absent-capability errors | — |
| M4 Asset catalog + symlinks | yes | Two-dimensional layout and host mapping; relative symlinks; resource loader | — |
| M5 Config + installer + CLI | yes | Pydantic config, hash ownership, §2 APIs/exit codes, argparse + Rich | — |
| M6 Release + integration guards | yes | Next release; wheel-only standalone smoke tests and existing release registry pattern | — |

### Module 1: Package and metadata spine

- **Paths**: new `packages/ai-parrot-sdd/pyproject.toml`, `src/parrot_sdd/__init__.py`,
  `version.py`, `py.typed`, `meta.py`; modify core `knowledge/wiki/ledger/sdd_ingest.py`.
- **Responsibility**: move the canonical metadata implementation; preserve exported
  flow/taxonomy/worktree contracts; remove the old metadata module in the hard cut.
- **Depends on**: existing Pydantic/PyYAML and workspace packaging.
- **Interface skeleton**: `parse`, `emit`, `parse_taxonomy`, `resolve_flow`,
  `plan_worktree` retain the §6 signatures. Add
  `read_declared_base_branch(doc_path: Path) -> str | None` to consolidate the
  two permissive core parsers without substituting `parse()`'s default `dev`.
  Missing files, malformed YAML, absent/non-string/empty values return `None`.

### Module 2: Scripts hard cut

- **Paths**: `src/parrot_sdd/scripts/`, `scripts/sh/`; moved
  `packages/ai-parrot-sdd/tests/`; live invocation sites across hosts, CI, docs,
  scripts and packages; `scripts/calibrate_rlimit_as.py`; `sdd/.collision_baseline.json`.
- **Responsibility**: move all SDD utilities including `prune_intake.py` and
  `install_hooks.py`; eliminate old imports/module invocations. Import metadata
  directly from `parrot_sdd.meta`, not a second metadata shim.
- **Depends on**: M1. Kernel extraction and immediate consumer updates land in the same wave.
- **Interface skeleton**: retain moved utility public signatures/CLI flags and
  error codes; `ensure(plan, *, repo_root, sync=True, require_paths=(), dry_run=False)`
  and `reserve_ids(kind, count, base_branch, label, *, ...)` preserve behavior.
- Keep shell resources installed in the package. New internal runner
  `parrot_sdd.scripts.run_shell.main(argv: list[str] | None = None) -> int`
  accepts only `close_task`, `heal_orphans`, resolves packaged
  resources, forwards arguments without interpolation and returns the shell exit
  status. This does not add script verbs to `sdd`.
- Move repository-specific baseline data out of the deleted directory, not into
  the wheel. Retain Bash/jq requirements where existing scripts use them.

#### Extracted test-scope kernel

- Move the complete core `flows/dev_loop/test_scope/` implementation to
  `src/parrot_sdd/test_scope/`, including its existing tests under the satellite's
  `tests/test_scope/`. Keep the existing algorithms and public signatures,
  including `plan_tests(*, worktree, changed_files, tier, declared=(), policy=None)`.
  Remove checkout-relative `sys.path` loaders from the two scripts.
- Preserve existing dataclass carriers during this focused move; new config
  boundaries use Pydantic. Package initialization and kernel imports must not
  eagerly import Rich, Pydantic models, core or tools. CLI/config imports remain
  separate from the dependency-light guard path.
- Add `test_scope` to `SDDConfig`, represented by a new `TestScopeConfig` model:
  `core_paths: list[str] = []`, `xdist_safe: list[str] = []`,
  `impact_cap: int = 150`, `impact_depth: int = 1`,
  `core_fanin_threshold: int = 50`, `marker_expression: str = ""`.
  Require positive cap/threshold and nonnegative depth; validate paths as relative.
  Convert this model to existing `ScopePolicy` through the new
  `load_scope_policy(worktree: Path) -> ScopePolicy` in `test_scope/policy.py`.
  Explicit `policy` wins; otherwise planning loads target-repository config.
  Missing config uses portable defaults; invalid config raises an actionable error.
- Move ai-parrot's measured core paths, xdist allowlist and marker expression
  into its `.parrot/sdd.json`, updating paths affected by extraction. Generate
  their documentation into the same CONFIG.md. Preserve ai-parrot behavior via
  parity tests; never ship these values as portable defaults.
- Retain workspace-layout support. Add `src/<import-package>/...` → `tests/...`
  mirroring for single-distribution projects, using the existing deepest-directory
  fallback and `root` distribution identity; recognize `src/` in `distribution_of`.
  No automatic xdist or marker filtering in an unconfigured repository.
- Update immediate consumers in the same extraction wave: QA, coder engine,
  LLM dispatcher, worktree environment and tools' native scope guard. All imports
  use the installed package; missing support must not silently disable a guard
  in a configured SDD execution environment. Test direct-script hook execution
  with an interpreter that can import the satellite. Do not mutate shared venvs.

#### Shell integration boundary

- Remove embedded core imports from packaged `close_task.sh`. After its successful
  exit, `run_shell` calls the new satellite function
  `notify_task_closed(root: Path, task_id: str, feature_slug: str, verification: str) -> None`
  in `parrot_sdd/events.py`. Never notify after failed closure or orphan healing.
- Discover optional callbacks through stdlib `importlib.metadata.entry_points`
  in group `parrot_sdd.task_closed`, sorted by entry-point name. Each callback
  receives those four keyword arguments; zero callbacks is a no-op. Discovery,
  import and callback exceptions are logged individually and do not change the
  successful closure exit status. No hard-coded core module name exists in the
  satellite. Installing the satellite alone loads no core callback.
- Relocate `scripts/sdd/codex_hook.sh` to repository-owned
  `scripts/codex_hook.sh`; update its live callers. It remains an optional
  ai-parrot-tools integration, excluded from the satellite resource catalog and
  runner allowlist. This is the deliberate exception to the brainstorm's proposed
  move of all three shell helpers, needed to retain the approved dependency boundary.

### Module 3: Core integration and duplicate removal

- **Paths**: core dev-loop `nodes/base.py`, `nodes/research.py`,
  `nodes/feature_handoff.py`, `nodes/qa.py`, `_subagent_defs.py` and affected tests;
  `sdd_coder/engine.py`, `dispatchers/llm.py`, `worktree_environment.py`;
  tools `tool_optimizations/hooks.py`; core optional-dependency metadata;
  new core `knowledge/wiki/ledger/sdd_adapter.py`.
- **Responsibility**: replace duplicate branch constants/parsers with the satellite
  contract; preserve fallback behavior; replace the QA module invocation.
- **Depends on**: M1, M2; prompt resource change lands with M4.
- Core imports remain lazy, including `base.py`: importing ordinary core
  functionality without the satellite must succeed. Missing SDD support is
  explicit at the operation boundary; do not preserve stale duplicate policies
  as a silent fallback.
- `load_subagent_definition(name: str) -> str` retains its valid-name validation,
  frontmatter stripping, and missing-resource error behavior. It reads the
  satellite resource, not a checkout path or copied core prompt.
- Core registers entry point `wiki_ledger` in group `parrot_sdd.task_closed`,
  targeting `parrot.knowledge.wiki.ledger.sdd_adapter:task_closed`. New signature:
  `task_closed(*, root: Path, task_id: str, feature_slug: str, verification: str) -> None`.
  Move the existing ledger append behavior here: resolve the shared root, append
  `task.closed` with subject `task:<id>`, actor `agent:close_task.sh`, and existing
  feature/verification payload. Preserve best-effort notification semantics and
  use no SQLite writer. The callback imports ledger implementation lazily.
- Declare core's satellite dependency in an optional `sdd` extra and include the
  satellite directly in workspace development dependencies. No satellite runtime
  dependency points back to core; the entry point is an optional extension supplied
  by an installed host, not a required reverse dependency.

### Module 4: Assets, portability and relative symlinks

- **Paths**: satellite `assets/`, `.claude/commands/`, `.claude/agents/`,
  `.agent/workflows/`, `.agents/skills/`, `.agents/agents/`,
  `.codex/agents/sdd-worker.toml`, `sdd/templates/`, applicable SDD rules/workflows,
  core `_subagent_data/`, `.gitignore`.
- **Responsibility**: catalog the complete flow and its referenced resources;
  consolidate equivalent twins without flattening host-specific syntax.
- **Depends on**: M1; lands atomically with M3 prompt loading.
- Claude receives shared templates plus Claude commands/agents; Codex receives
  shared templates, `.agents/skills/sdd-*/SKILL.md` and its TOML worker;
  Google receives shared templates/skills, `.agent/workflows/` and `.agents/agents/`.
- Generate relative symlinks per destination depth. Follow each symlink in a
  real linked worktree to prove it reaches that worktree's package source.
- Generic assets contain no ai-parrot-specific checkout paths or mandatory wiki,
  Jira, model-provider, or development-environment assumptions. Keep optional
  integrations conditional; repo-owned conventions remain outside generic assets.
- Track package templates explicitly despite the broad `templates/` ignore.
  Ship real resource bytes in wheel/sdist, not dangling repository symlinks.

### Module 5: Configuration, manifest and CLI

- **Paths**: satellite `config.py`, `install.py`, `cli.py`, asset catalog/config
  template/seeds; ai-parrot `.parrot/sdd.json`, generated `sdd/CONFIG.md`.
- **Responsibility**: implement §2 models, public APIs, ownership and exit codes.
- **Depends on**: M4. Uses argparse for parsing and Rich for user-facing output.
- **Interface skeleton**: the signatures in §2 are authoritative. New exception
  `SDDInstallError(RuntimeError)` represents operational failures; Pydantic
  validation errors map to CLI exit 2. New code uses logging, no `print`.
- Ordinary consuming installs create copies. Ai-parrot symlink authoring is a
  repository migration, not an undocumented installer auto-detection mode.

### Module 6: Release plumbing, docs and regression guards

- **Paths**: root `pyproject.toml`, `uv.lock`, satellite package metadata/tests,
  core optional dependencies, `scripts/release.py`, `scripts/pypi_paced_publish.py`,
  `Makefile`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
  `docs/migration/portable-sdd-flow.md`, `CHANGELOG.md`, `sdd/WORKFLOW.md`.
- **Responsibility**: add workspace dependency/source registration, release version
  source and artifact checks; document standalone install, config, upgrades,
  uninstall, hook dependencies and historical command translation.
- **Depends on**: M1–M5.
- Validate built wheel and sdist in an isolated environment with no ai-parrot,
  repository PYTHONPATH or editable installs. Publish is a later release action.

### Worktree Strategy

**Isolation: per-spec.** Implementation uses
`.claude/worktrees/feat-FEAT-583-portable-sdd-flow`, based on `origin/dev`.
The spec remains on `dev`; `$sdd-task` creates the implementation branch/worktree.
The six waves are ordered M1 → M2 → M3 → M4 → M5 → M6. Changes needed to keep
each wave green land in the same wave: update immediate consumers/tests with
their move; never leave a dangling loader until a later wave. Host asset conversion
may be split only after catalog/layout contracts are fixed. Shared core and
release files are exclusive work; do not create speculative module worktrees.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Required coverage |
|---|---|---|
| `test_metadata_contracts` | M1 | Flow/taxonomy normalization, hotfix validation, worktree names and permissive declared-base parsing |
| `test_no_core_dependency` | M1–M5 | AST and runtime checks; shell-embedded Python and checkout path loaders included |
| `test_asset_tiers` | M4 | Every resource assigned once; destination ownership unambiguous; generic tier free of repository-specific content |
| `test_config_validation` | M5 | Missing defaults; invalid JSON/schema; branch constraints; safe source paths; Markdown escaping |
| `test_install_ownership` | M5 | First install, no-op, upgrade, modified/unowned conflict, force, seed preservation |
| `test_manifest_validation` | M5 | Corruption, unknown version, traversal, absolute paths, symlink parents, duplicate destinations |
| `test_multi_host_install` | M5 | Claude→Codex→Google union; shared paths owned once; no host removal on reinstall |
| `test_dry_run` | M5 | Same path plan as install; byte-for-byte and directory-tree non-mutation |
| `test_partial_failure` | M5 | Failed writes reported; manifest never falsely reports success; recovery retains ownership |
| `test_cli_contract` | M5 | All verbs/options and exit codes; help works without core |
| `test_rich_output` | M5 | Literal paths/markup; stable redirected output without ANSI animation |
| `test_scope_policy_portability` | M2 | Portable defaults, ai-parrot policy parity, explicit override precedence and invalid config |
| `test_task_closed_callbacks` | M2/M3 | No callbacks, successful callback, broken callback/import; no notification after failed closure |

### Integration Tests

| Test | Description |
|---|---|
| `test_install_roundtrip` | Install/uninstall per host in temporary Git repos; modified and unowned files survive |
| `test_symlink_integrity` | Every migrated link resolves inside both main checkout and linked worktree |
| `test_wheel_standalone` | Wheel-only install; CLI, metadata, script help, resources and real graph/test planning from an unrelated repo/subdirectory |
| `test_core_without_sdd` | Core/wiki imports and unrelated operations work; SDD ingest skips and dev-loop capability reports missing dependency |
| `test_core_with_sdd` | Same branch selection, QA lint argv and prompt bodies as before migration |
| `test_no_legacy_callsites` | Scan executable/live documentation surfaces for old imports and paths, excluding immutable historical SDD records and explicit migration examples |
| `test_allocator_regression` | Existing concurrency, rejection, duplicate-slug and local-commit protection tests pass against moved code |
| `test_extracted_scope_consumers` | Script/direct hook, QA and dispatcher use the installed kernel; configured guards cannot disappear silently |
| `test_core_ledger_adapter` | Successful closure appends the existing event payload through the optional adapter; missing core is a no-op |

### Test Data / Fixtures

Temporary repos include a src-layout Python project, a workspace layout,
multiple hosts, locally edited assets, malformed manifests, paths with spaces,
a bare origin for ID reservation, and a real linked worktree. Existing moved
script tests retain their behavioral assertions and use explicit fixture roots
instead of deriving the checkout root from their new file depth.

---

## 5. Acceptance Criteria

- [ ] Standalone wheel installation brings no ai-parrot dependency and all three
  host installs work without source checkout/PYTHONPATH assumptions.
- [ ] `scripts/sdd/` is removed; calibration and baseline remain repository-owned
  at the new paths; all live callers use the installed package.
- [ ] Flow metadata, ID allocation, worktree provisioning and taxonomy regressions pass.
- [ ] No satellite path, including embedded shell code, directly imports core or tools;
  the extracted kernel works standalone and optional ledger callbacks are core-owned.
- [ ] Rich output works in interactive and redirected streams without requiring Click.
- [ ] Existing ai-parrot test selection, escalation policy and guard decisions retain parity.
- [ ] Core SDD imports are lazy; wiki ingest tolerates an absent satellite.
- [ ] Duplicate core parsers/constants and bundled prompt copies are consolidated
  without changing fallback selection or programmatic prompt loading.
- [ ] All assets have catalog ownership, resolve through resources in built artifacts,
  and ai-parrot relative symlinks work inside a linked worktree.
- [ ] One generated CONFIG.md governs repository-specific settings; generic assets
  work without mandatory ai-parrot, Jira or wiki installations.
- [ ] Reinstall, upgrades, multi-host ownership, force, dry-run and uninstall satisfy §2.
- [ ] User config, seeds, existing SDD documents/ledgers and locally modified files
  survive uninstall; invalid paths/manifest input cannot escape the target root.
- [ ] New code passes Black (120 columns), Ruff and the scoped §4 tests.
- [ ] Build/release registration, wheel/sdist data checks, migration docs and changelog are complete.
- [ ] Historical SDD documents remain unchanged; no old-path compatibility shim is added.
- [ ] Each migration wave is independently green, with no broken intermediate resource/import paths.

---

## 6. Codebase Contract

Verified on `dev`, 2026-09-19. Paths below describe existing code; §2–§3 paths
under `packages/ai-parrot-sdd/` are proposed and must not be treated as existing.

### Verified Imports

```python
from pydantic import BaseModel, Field, field_validator, model_validator
import yaml
# Both verified in packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:20

from scripts.sdd.sdd_meta import resolve_flow
# Re-export verified in scripts/sdd/sdd_meta.py:10; invoked successfully during specification.

from parrot.knowledge.wiki.ledger.sdd_meta import DocTaxonomy, parse_taxonomy
# Current integration: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py:20
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
class FlowMeta(BaseModel):  # :99
    type: Literal["feature", "hotfix"]
    base_branch: str

def parse(doc_path: Path) -> FlowMeta:  # :129
    """Absent frontmatter defaults; partial invalid frontmatter raises validation errors."""

def emit(meta: FlowMeta) -> str:  # :156
    """Serialize flow frontmatter."""

def parse_taxonomy(doc_path: Path) -> DocTaxonomy:  # :247
    """Parse projects/tags."""

def resolve_flow(  # :263
    *, kind: str | None = None, doc_path: Path | None = None,
    type_override: str | None = None, base_branch_override: str | None = None,
) -> FlowMeta:
    """Resolve overrides, document, work kind, then feature/dev defaults."""

def plan_worktree(  # :336
    meta: FlowMeta, *, slug: str, feature_id: str | None = None, jira_key: str | None = None,
) -> WorktreePlan:
    """Produce name/path/base_ref using origin/<base_branch>."""

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py:51
class SDDGraphIngest:
    def __init__(self, store: "LedgerStore", shared_root: Path) -> None:
        """Bind store and repository paths."""
    async def ingest_all(self) -> dict[str, int]:  # :66
        """Return specs/tasks/edges counters."""
```

### Integration Points

| New component | Existing contract / observation | Verified at |
|---|---|---|
| Metadata | Branch constants/work kinds, taxonomy, worktree root | `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:30`, `:34`, `:218`, `:322` |
| Core branch reuse | `_LONG_LIVED_BRANCHES` duplicated | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py:44` |
| Research parser | `_parse_flow_frontmatter(Path) -> Optional[str]`; returns None for unresolved input | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:159` |
| Handoff parser | Independent permissive duplicate | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py:69` |
| QA shell-out | Existing replacement string and shlex-quoted file arguments | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:820` |
| Agent resource loading | `load_subagent_definition(name: str) -> str` uses core package data | `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:95` |
| Worktree script | `ensure` accepts explicit `repo_root`, sync/verification/dry-run controls | `scripts/sdd/ensure_worktree.py:48` |
| Test selector | `_KERNEL_PARENT` points into core checkout | `scripts/sdd/select_tests.py:17` |
| Graph checker | `_load_contract()` mutates sys.path to load core kernel | `scripts/sdd/check_task_graph.py:195` |
| Test kernel | Keyword-only `plan_tests(worktree, changed_files, tier, declared=(), policy=None)` | `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:122` |
| Repository policy | `ScopePolicy` uses repository-specific constants | `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py:751` |
| Task-close integration | Embedded Python imports wiki ledger core | `scripts/sdd/close_task.sh:131` |
| Codex hook | Executes `parrot_tools.tool_optimizations.hooks` via main .venv | `scripts/sdd/codex_hook.sh:6` |
| Native guard | `_load_scope_guard(cwd)` currently loads kernel by checkout path | `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py:466` |
| Worktree guard | `_load_guard_bash()` currently handles package and direct-script imports | `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:199` |
| Coder kernel consumer | Imports attempt-context writer and data carrier | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:55` |
| Dispatcher kernel consumer | Imports `GuardOutcome` and `guard_argv` | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:59` |
| Intake hooks | `render_block(python, repo_root)` emits old module invocation | `scripts/sdd/install_hooks.py:33` |
| Allocation | Git-native remote compare-and-swap, no local history destruction | `scripts/sdd/reserve_ids.py:468` |
| Workspace | Glob members `packages/*`; root explicitly lists runtime workspace dependencies | `pyproject.toml:13`, `:57` |
| Release registry | `PACKAGES: list[Package]` | `scripts/release.py:116` |
| First publication | Version-specific `NEW_PROJECTS` queue | `scripts/pypi_paced_publish.py:67` |
| Core CLI | `LazyGroup(click.Group)`; separate from terminal renderer | `packages/ai-parrot/src/parrot/cli/__init__.py:19` |
| Ignore policy | Broad `templates/` ignore; artifacts ignored | `.gitignore:267`, `:279` |

### Does NOT Exist (Anti-Hallucination)

- No `packages/ai-parrot-sdd/`, `parrot_sdd.install` or installed `sdd` entry point
  exists in the current workspace source.
- No Toad dependency was found in workspace package declarations; core uses
  Click with Rich/Textual rendering. The owner's new CLI requirement overrides
  the brainstorm's proposed Click implementation.
- No standalone script implementation is achieved by moving entry points alone:
  two scripts still load the core test-scope kernel by filesystem path.
- `parse()` is not a drop-in replacement for the permissive dev-loop parsers:
  missing frontmatter yields `dev`, whereas those parsers yield `None`.
- The metadata parser does not fill missing keys in existing YAML frontmatter;
  the brainstorm's missing `base_branch` required explicit default resolution.
- The old asset counts and “10th distribution” claim are not authoritative inventories.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Preserve the accepted whole-flow scope and hard-cut migration. No provider SDK,
  network or core package is required to import the satellite.
- Use package resources, explicit target roots, strict typed Pydantic records,
  deterministic JSON/Markdown, and standard logging. CLI filesystem operations
  are synchronous; core async consumers must not add blocking event-loop I/O.
- Seed prose must instruct repository customization without unfinished code or TODO stubs.
- Keep historical record exclusions explicit: the brainstorm itself contains old
  paths, so a repository-wide substring ban would contradict preservation.
- ID reservations still require a committed ledger and configured remote/base
  branch. Installation never publishes or silently initializes remote state.

### Known Risks / Gotchas

1. Relative links must resolve inside linked worktrees, not the primary checkout.
2. The global templates ignore can omit newly moved resources; verify the staged
   tree and built wheel/sdist, adding precise ignore exceptions where needed.
3. A lazy optional dependency can accidentally become eager through an imported
   constant, annotation or package initializer; test actual absence in isolation.
4. Preserve `None` versus `dev` semantics in parser consolidation.
5. Multi-host upgrade/uninstall requires unioned shared ownership and retained
   modified-file records, not a manifest overwritten by the latest host.
6. Existing test-scope defaults encode ai-parrot paths and xdist policy; extraction
   must separate portable algorithms from repository policy, not merely rename imports.
7. First-publication pacing and CI push transport must be checked at release time.
   The brainstorm's PyPI quota/token claims are operational context, not guarantees
   verified by this specification. Do not execute publishing as part of implementation.

### External Dependencies

| Package/tool | Existing bound / policy | Reason |
|---|---|---|
| Pydantic | `==2.12.5` in core | Satellite models; use this verified bound initially |
| PyYAML | `>=6.0.2` in core | YAML metadata |
| Rich | `>=13.0` | Required satellite CLI presentation; owner approved |
| setuptools / wheel | `>=77.0.0` / `>=0.44.0` in satellite precedent | Build dependencies only |
| Python | `>=3.11,<3.14` workspace convention | Runtime floor |
| Git, Bash, jq | Existing external script prerequisites | Repository operations/shell helpers; document and diagnose absence |

No Jinja2, Click or Toad dependency is introduced. No new library installation
is performed while drafting this specification.

---

## 8. Open Questions

### Accepted brainstorm decisions (carried forward verbatim)

- [x] Deliverable scope — Whole SDD flow installable, not just scripts
- [x] Script distribution model — Import from installed package, don't copy Python to consuming repo
- [x] Which distribution owns it — New satellite: `ai-parrot-sdd` (`parrot_sdd`)
- [x] Asset authoring in ai-parrot — Package is source, repo has symlinks in
- [x] Asset adaptation for other repos — Tier the assets + render a config
- [x] Core SDD awareness — `sdd` CLI only — core knows nothing
- [x] Config model — One generated config asset (`sdd/CONFIG.md`) from `.parrot/sdd.json`
- [x] Script name — `sdd` (satellite's own binary)
- [x] Host variants — `sdd claude install`, `sdd codex install`, `sdd google install`

“Core knows nothing” applies to CLI ownership, as explicitly scoped by the
brainstorm; the same source requires optional wiki/dev-loop integrations.

### Specification clarifications

- [x] New CLI does not use Click — owner clarification during specification.
- [x] CLI presentation — “Rich output”: argparse + Rich; Rich is an explicit satellite dependency.
- [x] Target release — “next release”: scheduled for the next release; no guessed numeric version.
- [x] Dependency boundary — “include”: extract the test-scope kernel into `parrot_sdd`
  and retain ledger emission in a core-owned optional adapter, as specified in M2/M3.

All specification clarification questions are resolved. Status remains draft for
normal specification review; task decomposition follows approval.

---

## 9. Design Research Cross-Check

Status: skipped (no independent reviewer was invoked for this specification).
Source research was performed locally against the accepted brainstorm; it is
not represented as an independent model opinion. No transcript is claimed.

| # | Verified finding | Disposition | Reason | Landed in |
|---|---|---|---|---|
| R1 | Test scripts load core kernel by checkout path | CONFIRM | Owner approved kernel extraction; repository policy moves to config | §3 M2 |
| R2 | Handoff has another parser copy | CONFIRM | Consolidate all verified duplicates while preserving fallback semantics | §3 M3 |
| R3 | Prompt loader reads core package data | CONFIRM | Symlinks alone cannot consolidate installed-wheel consumers | §3 M4 |
| R4 | Shell helpers depend on core/tools | CONFIRM | Ledger callback stays core-owned; tools-specific hook stays repository-owned | §3 M2/M3 |
| R5 | Partial metadata frontmatter fails validation | CONFIRM | Resolve source default explicitly; keep current parser semantics visible | §6 |

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-19 | Jesus / Codex | Initial researched draft; pending dependency and release clarifications |
| 0.2 | 2026-09-19 | Jesus / Codex | Resolve owner choices: Rich output, next release, kernel extraction and core-owned ledger adapter |
