---
type: feature
base_branch: dev
---

# Feature Specification: `parrot toolkits` — on-demand local-MCP toolkit installation

**Feature ID**: FEAT-570
**Date**: 2026-09-18
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: next minor after 0.29.x (core `ai-parrot` only)
**Brainstorm**: `sdd/proposals/expose-local-mcp-tools.brainstorm.md` (accepted 2026-09-18, Option A)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-485 built the generic local-MCP machinery (`parrot mcp-local <name>`,
`.parrot/mcp-toolkits.yaml`, managed `.mcp.json` / `.codex/config.toml` /
`mcp_config.json` reconciliation) and FEAT-556 added packaged **templates** so a
section can be seeded without hand-editing YAML. Three templates ship today:
`bounded-source`, `targeted-writer`, `sdd-coder`.

Two problems remain.

**1. The two database toolkits are invisible.** `QuerysourceToolkit` (FEAT-558)
and `DatabaseQueryToolkit` (FEAT-105/136) are exactly the kind of tool a coding
or analysis session wants as a first-class MCP tool — schema discovery, validated
read-only query execution, tenant-scoped query slugs and MultiQuery pipelines.
Neither ships a template, so exposing them means hand-writing a YAML section from
the class signature.

**2. Toolkit selection is a flag buried inside the wrong command.** The only way
to choose toolkits is `parrot claude install --toolkits=a,b` / `--all-toolkits` —
a flag on the *wiki* installer. The operator must already know the template
names; there is no way to **list** what is available with descriptions, no way to
**disable** one without hand-editing YAML and re-running the host installer, and
no way to **uninstall** one at all.

Compounding this: `scraping`, `browsing` and `memory` are hardcoded as
`BUILTIN_TOOLKITS` (`toolkit_config.py:89`) and resolve implicitly whether or not
the operator wants them. A repo that never asked for browser automation still has
`browsing` resolvable, and `parrot claude install` will write a `parrot-browsing`
entry. The owner's decision is that **nothing except wikitoolkit is implicit** —
every local MCP server becomes opt-in and individually toggleable.

**Who is affected**: every operator wiring an ai-parrot repo into Claude Code,
Codex or Google Antigravity — plus the ai-parrot repo itself, whose `.mcp.json`
carries `parrot-browsing`, `parrot-memory` and `parrot-scraping` entries that
resolve through the builtins.

### Goals

- A `parrot toolkits` command group — `list`, `status`, `install`, `uninstall`,
  `enable`, `disable` — as the **only** toolkit selection surface.
- Interactive picker when names are omitted; a non-interactive form for every
  subcommand so CI never blocks.
- Two new templates: `querysource` and `database-query`.
- `BUILTIN_TOOLKITS` deleted; `scraping`/`browsing`/`memory` become templates.
- All three hosts installable/uninstallable (Claude Code, Codex, Antigravity).
- **Toolkit-only host reconciliation**: `parrot toolkits` must never add, refresh
  or remove the wikitoolkit entry, which stays owned by `parrot claude install`
  and its siblings (design research S1).
- No secrets written to disk by the installer, ever.
- Listing templates must not import any toolkit class.

### Non-Goals (explicitly out of scope)

- Auto-migration of existing installs — hard cut, reinstall required.
- Bringing wikitoolkit into `parrot toolkits` (it stays invisible to this command).
- Entry-point auto-discovery of templates across distributions — rejected for v1
  in brainstorm Option D; remains a possible follow-up and is not precluded.
- A declarative `mcp-profile.yaml` plan/apply model — rejected in brainstorm
  Option C (two sources of truth for "is this toolkit on?").
- Per-host toolkit sets (a section is host-agnostic).
- Fixing the stale `dq_validate_database_query` assertions in
  `packages/ai-parrot/tests/tools/databasequery/` — a pre-existing defect recorded
  in §7, not this feature's work.

---

## 2. Architectural Design

### Overview

A new top-level lazy Click group `toolkits` orchestrates machinery that already
exists and is already tested: `toolkit_seed` for template inventory and seeding,
`toolkit_config` for what is declared and enabled, and per-host reconcilers for
the actual config-file entries.

The decisive property carried from the brainstorm: **enable/disable already works
end-to-end.** All three host installers derive their desired entry set from
`load_toolkits_config(root)` filtered on `section.enabled`, and remove entries for
sections that are disabled or deleted (`claude_code/installer.py:528-532`,
`google/installer.py:187-191`, `codex/installer.py:134`). A disable is therefore a
YAML flag flip plus a reconcile — no new reconciliation logic.

Design research materially changed two things about *how* that reconcile is
reached:

1. **Toolkit-only reconcilers (S1).** The existing `_install_mcp_json` /
   `_install_mcp` entry points also (re)write the **wikitoolkit** entry — verified
   at `claude_code/installer.py:462`, `google/installer.py:148-160`,
   `codex/installer.py:110`. Calling them from `parrot toolkits` would mutate an
   artifact this command explicitly does not own. Each host therefore grows a
   public **toolkit-only** reconcile function that touches only `parrot-<name>`
   entries; the existing full installers are refactored to call it, so there is
   one reconciliation implementation, not two.
2. **A host adapter contract (S2).** The three hosts are not symmetric: Claude and
   Google each have `_is_managed_toolkit_entry`, **Codex has neither** — it
   detects collisions via `_existing_table_names` plus a managed marker block, and
   regenerates its whole block. Google writes **two** files. So `parrot toolkits`
   talks to a `HostAdapter` protocol (inspect / reconcile / paths / collisions),
   never to private per-host helpers.

Every other brainstorm decision stands: full replacement of `--toolkits`,
`BUILTIN_TOOLKITS` deleted, hard-cut migration, wikitoolkit invisible,
`env:` left empty with credentials inherited from the spawned process's
environment, `questionary` for the picker (already a core dependency).

### Component Diagram

```
parrot toolkits <sub>            parrot/cli/toolkits.py          (M7)
        │  questionary picker (sync, never inside async)
        ▼
  toolkit_install.py             inventory / install / uninstall / set_enabled   (M6)
        │
        ├──► toolkit_seed.py     templates, preflight+atomic seed, toggle, remove (M4,M5)
        │        └─ _toolkit_templates/*.yaml   querysource, database-query,
        │                                        scraping, browsing, memory
        ├──► toolkit_config.py   load_toolkits_config  (NO builtins)              (M3)
        │
        └──► hosts.py  HostAdapter protocol                                       (M1)
                 ├─ ClaudeAdapter  → reconcile_toolkit_entries()  .mcp.json      (M2)
                 ├─ CodexAdapter   → reconcile_toolkit_tables()   .codex/config.toml
                 └─ GoogleAdapter  → reconcile_toolkit_entries()  ~/.gemini/... + .agents/plugins/parrot/
                                      (wikitoolkit entry NEVER touched by any of these)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parrot/cli/toolkits.py` | `parrot.cli.cli` LazyGroup | `_lazy_commands["toolkits"]` | `parrot/cli/__init__.py:110-133` |
| `toolkit_install.inventory()` | `toolkit_seed.available_templates()` | call | `toolkit_seed.py:47` |
| `toolkit_install.inventory()` | `toolkit_config.load_toolkits_config()` | call | `toolkit_config.py:105` |
| `toolkit_install.install_toolkits()` | `toolkit_seed.seed_toolkit_sections()` | call | `toolkit_seed.py:154` |
| `ClaudeAdapter.reconcile()` | `claude_code.installer.reconcile_toolkit_entries()` | new public fn extracted from `_install_mcp_json` | `claude_code/installer.py:462` |
| `ClaudeAdapter.approve()` | `claude_code.installer._install_mcp_approval()` | call, filtered to toolkit names only | `claude_code/installer.py:340` |
| `CodexAdapter.reconcile()` | `codex.installer.reconcile_toolkit_tables()` | new public fn extracted from `_install_mcp` | `codex/installer.py:110` |
| `GoogleAdapter.reconcile()` | `google.installer.reconcile_toolkit_entries()` | new public fn extracted from `_install_mcp` | `google/installer.py:139` |
| `parrot mcp-local <unknown>` | new error text naming `parrot toolkits install` | `create_toolkit_mcp_server` ValueError | `parrot/mcp/local_cli.py:113-117` |

### Data Models

```python
# parrot/mcp/hosts.py
class HostKind(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GOOGLE = "google"

class HostEntryState(BaseModel):
    host: HostKind
    config_paths: tuple[Path, ...]   # Google has TWO; the others exactly one
    config_present: bool             # at least one config file exists
    repo_scoped: bool                # False for Google's user-global file
    managed: bool                    # a parrot-<name> entry we own exists
    foreign: bool                    # the key exists but is not ours

# parrot/mcp/toolkit_install.py
class ToolkitState(str, Enum):
    NOT_INSTALLED = "not_installed"
    ENABLED = "enabled"
    DISABLED = "disabled"

class ToolkitRow(BaseModel):
    name: str
    summary: str
    class_path: str
    state: ToolkitState
    requires_llm: bool
    requires_dist: tuple[str, ...]   # FEAT-570: new template metadata (S6)
    dist_available: bool             # importlib.util.find_spec — NEVER imports
    drift: list[str]
    hosts: list[HostEntryState]

class ActionReport(BaseModel):
    actions: list[str]
    warnings: list[str]
    failed_hosts: dict[HostKind, str]
```

### New Public Interfaces

```python
# parrot/mcp/hosts.py
def get_adapter(kind: HostKind) -> HostAdapter: ...
def detect_hosts(root: Path) -> list[HostKind]: ...

# parrot/mcp/toolkit_install.py
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]: ...
def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport: ...
def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport: ...
def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]) -> ActionReport: ...

# parrot/mcp/toolkit_seed.py  (additions)
def set_section_enabled(root: Path, name: str, enabled: bool) -> bool: ...
def remove_section(root: Path, name: str) -> bool: ...
def preflight_seed(root: Path, names: Sequence[str]) -> None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Host adapter contract | no | Protocol shape is fixed below, but the Codex/Google asymmetry needs judgment while extracting | Host semantics differ; extraction is a design act |
| M2: Toolkit-only reconcilers | no | Must preserve wikitoolkit + foreign-entry warnings exactly | Refactor of tested reconciliation logic |
| M3: Delete `BUILTIN_TOOLKITS` | yes | Delete const + the merge seed at `toolkit_config.py:143`; docstring rewrite | — |
| M4: Seed preflight / toggle / remove | yes | Signatures fixed; lexical editor, atomic replace, all-or-nothing on unknown names | — |
| M5: Five templates | yes | Exact YAML bodies decided in §7 and below | — |
| M6: Install orchestration | yes | Models + signatures fixed above | — |
| M7: CLI group | yes | Subcommands, flags and picker behavior fixed below | — |
| M8: Host flag cut | yes | Remove three `--toolkits`/`--all-toolkits` pairs + `toolkits` params; add warning | — |
| M9: Consumer audit | yes | Exact file list in §5 AC7 | — |
| M10: Tests | yes | Matrix enumerated in §4 | — |

### Module 1: Host adapter contract
- **Path**: `packages/ai-parrot/src/parrot/mcp/hosts.py` (new)
- **Responsibility**: One protocol over three asymmetric hosts. Never exposes a
  private per-host helper to callers.
- **Depends on**: M2 (the toolkit-only reconcilers it wraps)
- **Interface Skeleton**:
  ```python
  # parrot/mcp/hosts.py  (new)
  class HostAdapter(Protocol):
      """One MCP host's toolkit-entry surface. Implementations NEVER touch wikitoolkit."""
      kind: HostKind

      def config_paths(self, root: Path) -> tuple[Path, ...]:
          """Config files this host reads, most significant first.

          Google returns two (user-global ~/.gemini/config/mcp_config.json,
          verified: google/assets.py:59, and repo .agents/plugins/parrot/mcp_config.json,
          verified: google/installer.py:214); the others return exactly one.
          """

      def is_repo_scoped(self) -> bool:
          """False when the primary config is user-global (Google only)."""

      def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
          """Per-toolkit entry state. Reads config files only; imports no toolkit."""

      def reconcile(self, root: Path) -> list[str]:
          """Rewrite ONLY this host's parrot-<name> entries from the current config.

          Returns human-readable actions. Leaves the wikitoolkit entry and every
          foreign key untouched; foreign collisions are returned as warnings.
          """

      def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> str | None:
          """Claude Code only; a no-op returning None elsewhere."""

  def get_adapter(kind: HostKind) -> HostAdapter: ...
  def detect_hosts(root: Path) -> list[HostKind]:
      """Hosts whose config already exists. Google is included only when its
      user-global file exists AND §8 Q1 resolves to auto-detect (default: warn)."""
  ```

### Module 2: Toolkit-only host reconcilers
- **Path**: `parrot/knowledge/wiki/{claude_code,codex,google}/installer.py` (modify)
- **Responsibility**: Extract the `parrot-<name>` half of each host's
  `_install_mcp*` into a public function that does **not** touch wikitoolkit.
  The existing full installers then call it, keeping one implementation.
- **Depends on**: nothing (refactor)
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/claude_code/installer.py  (modifies :462 _install_mcp_json)
  def reconcile_toolkit_entries(root: Path) -> tuple[list[str], list[str]]:
      """Reconcile only `parrot-<name>` keys in .mcp.json from the toolkit config.

      Returns (actions, warnings). Never reads or writes the "wikitoolkit" key.
      Managed-shape detection stays `_is_managed_toolkit_entry` (verified: :420);
      foreign `parrot-<name>` keys are warned about and skipped (verified: :517).
      """

  def toolkit_server_names(root: Path) -> list[str]:
      """The `parrot-<name>` keys confirmed managed — WITHOUT "wikitoolkit".

      Split out of `_managed_server_names` (verified: :304), whose result is
      seeded with ["wikitoolkit"] at :332 and therefore must not be reused by
      `parrot toolkits` approval handling (design research S3).
      """

  # parrot/knowledge/wiki/codex/installer.py  (modifies :110 _install_mcp)
  def reconcile_toolkit_tables(root: Path) -> tuple[list[str], list[str]]:
      """Regenerate only the `[mcp_servers.parrot-<name>]` tables in the managed block.

      Codex has no `_is_managed_toolkit_entry`: collision detection is
      `_existing_table_names` (verified: :100) against the managed marker block.
      The wikitoolkit table inside the same managed block is preserved verbatim.
      """

  # parrot/knowledge/wiki/google/installer.py  (modifies :139 _install_mcp)
  def reconcile_toolkit_entries(root: Path, mcp_path: Path | None = None) -> tuple[list[str], list[str]]:
      """Reconcile `parrot-<name>` entries in BOTH the user-global mcp_config.json
      and the repo plugin file (verified: :214), leaving "wikitoolkit" untouched.
      """
  ```

### Module 3: Delete `BUILTIN_TOOLKITS`
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` (modify)
- **Responsibility**: Remove implicit toolkit resolution. `load_toolkits_config`
  returns only sections declared in the file.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # parrot/mcp/toolkit_config.py  (modifies :89 BUILTIN_TOOLKITS, :143 merge seed)
  # BUILTIN_TOOLKITS is DELETED.
  def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig:
      """Load `.parrot/mcp-toolkits.yaml`; returns ONLY file-declared sections.

      A missing default path now yields an EMPTY config (previously the three
      builtins). An explicitly named missing `config_path` still raises
      ValueError (unchanged, verified: :105 docstring).
      """
  ```

### Module 4: Seed preflight, atomic write, toggle and remove
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (modify)
- **Responsibility**: Make mutation safe (design research S4, S5) and add the
  toggle/remove primitives `parrot toolkits` needs.
- **Depends on**: M3
- **Interface Skeleton**:
  ```python
  # parrot/mcp/toolkit_seed.py  (modifies :154 seed_toolkit_sections)
  def preflight_seed(root: Path, names: Sequence[str]) -> None:
      """Validate the whole request BEFORE any write.

      Raises ValueError when any name is unknown (all-or-nothing — the current
      code seeds the valid ones anyway) or when the existing file is malformed
      (the current code swallows that ValueError and appends regardless).
      """

  def set_section_enabled(root: Path, name: str, enabled: bool) -> bool:
      """Flip `enabled:` for one section, preserving comments and formatting.

      Lexical edit + atomic replace — never `yaml.safe_dump` of a parsed model,
      which would discard operator comments (no round-trip parser is declared:
      `ruamel` is absent from packages/ai-parrot/pyproject.toml).
      Returns False when the section is absent.
      """

  def remove_section(root: Path, name: str) -> bool:
      """Delete one section and its comment block; atomic replace. False if absent."""
  ```

### Module 5: Five packaged templates
- **Path**: `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/*.yaml` (new)
- **Responsibility**: `querysource`, `database-query`, `scraping`, `browsing`,
  `memory`. Adds a `# parrot:requires_dist:` header (S6).
- **Depends on**: M3 (the builtin bodies move here verbatim)
- **Interface Skeleton**:
  ```yaml
  # _toolkit_templates/querysource.yaml
  # parrot:summary: Tenant-scoped QuerySource slugs and MultiQuery pipelines.
  # parrot:requires_llm: false
  # parrot:requires_dist: parrot_tools,querysource
    querysource:
      class: parrot_tools.querysource.toolkit.QuerysourceToolkit   # verified: querysource/toolkit.py:56
      # Credentials are NEVER written here. The DSN resolves from the environment
      # this server inherits, via querysource.conf.asyncpg_url (verified: _qs.py:63).
      # Set `dsn:` only if you must override it, and never commit a secret.
      kwargs:
        allow_write: true        # exposes qs_save_multiquery (confirming_tools, :61)
        allow_raw_sql: true
        # programs: [<tenant>, ...]   # omit = unrestricted
        # max_rows: 200
      env: {}

  # _toolkit_templates/database-query.yaml
  # parrot:summary: Multi-driver schema discovery and validated read-only queries.
  # parrot:requires_llm: false
  # parrot:requires_dist:
    database-query:
      class: parrot.tools.databasequery.toolkit.DatabaseQueryToolkit  # verified: toolkit.py:115
      # No allow_write / allow_raw_sql / dsn exist on this class — __init__ takes
      # ONLY output_dir and static_dir (verified: toolkit.py:166-167). The DDL/DML
      # guard is unconditional. Credentials are a per-CALL tool argument.
      kwargs:
        output_dir: {{repo_root}}/.parrot/db_results   # exposes dq_save_result
      env: {}
  ```

### Module 6: Install orchestration
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` (new)
- **Responsibility**: Host-agnostic inventory and mutation; dispatch to adapters.
- **Depends on**: M1, M4
- **Interface Skeleton**:
  ```python
  # parrot/mcp/toolkit_install.py  (new)
  def dist_available(requires_dist: Sequence[str]) -> bool:
      """True when every named distribution is importable — via importlib.util.find_spec.

      NEVER imports the toolkit class: `--list` must stay side-effect free
      (the existing contract, verified: local_cli.py:35-45).
      """

  def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:
      """One row per packaged template: state, drift, per-host entry state.

      wikitoolkit is never included — it is owned by `parrot claude install`.
      """

  def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:
      """Preflight, seed the sections, then reconcile each host's toolkit entries.

      Raises ValueError before ANY write when a name is unknown. Per-host failures
      are collected in `ActionReport.failed_hosts`, never rolled back (re-running
      is idempotent).
      """

  def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:
      """Snapshot managed entries, remove the sections, reconcile, then drop only
      the removed toolkits' Claude approvals (design research S3)."""

  def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool,
                           hosts: Sequence[HostKind]) -> ActionReport:
      """Flip `enabled:` and reconcile; the section and its kwargs are kept."""
  ```

### Module 7: `parrot toolkits` CLI group
- **Path**: `packages/ai-parrot/src/parrot/cli/toolkits.py` (new);
  `packages/ai-parrot/src/parrot/cli/__init__.py` (modify)
- **Responsibility**: The user-facing surface and the questionary picker.
- **Depends on**: M6
- **Interface Skeleton**:
  ```python
  # parrot/cli/toolkits.py  (new)
  @click.group(name="toolkits")
  def toolkits() -> None:
      """Install and manage local MCP toolkit servers."""

  @toolkits.command("list")
  def list_() -> None:
      """Table: template × state × per-host entry × drift × dependency availability."""

  @toolkits.command()
  def status() -> None:
      """Per-host resolved config paths, scope (repo / user-global) and health."""

  @toolkits.command()
  @click.argument("names", nargs=-1)
  @click.option("--host", "hosts_", multiple=True,
                type=click.Choice([k.value for k in HostKind]))
  @click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
  def install(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
      """Seed NAMES and register them with each selected host.

      With no NAMES, opens a questionary.checkbox picker (already-installed
      entries pre-checked). questionary is blocking and is called synchronously
      from this callback, never inside async code (pattern verified:
      knowledge/wiki/cli.py:4588-4606). With no TTY and no NAMES, exits 2 naming
      the non-interactive form. With no --host, targets every detected host.
      """

  # uninstall / enable / disable mirror install's signature.
  # parrot/cli/__init__.py — add to _lazy_commands (verified: :110-133):
  #     "toolkits": "parrot.cli.toolkits",
  ```

### Module 8: Host installer flag cut
- **Path**: `parrot/knowledge/wiki/{claude_code,codex,google}/{cli,installer}.py` (modify)
- **Responsibility**: Remove `--toolkits` / `--all-toolkits` and the `toolkits`
  parameter; warn when the toolkit config is empty so the removal is discoverable.
- **Depends on**: M7
- **Interface Skeleton**:
  ```python
  # claude_code/installer.py  (modifies :770)
  def install_claude_integration(
      root: Path,
      config: Optional[WikiProjectConfig] = None,
      git_hook: bool = True,
      gitignore: bool = True,
      bookstore: bool = True,
      approve_mcp: bool = True,
  ) -> list[str]:
      """... `toolkits` parameter REMOVED (FEAT-570). Seeding moved to `parrot toolkits`.

      Still reconciles whatever `.parrot/mcp-toolkits.yaml` declares, and appends a
      hint naming `parrot toolkits install` when that config is absent or empty.
      """
  # codex/installer.py:202 install_codex_integration — same removal
  # google/installer.py:239 install_google_integration — same removal
  # The three cli.py `--toolkits` / `--all-toolkits` options are deleted
  # (claude_code/cli.py:89-99, codex/cli.py:70-80, google/cli.py:64-74).
  ```

### Module 9: Builtin-consumer audit
- **Path**: `parrot/mcp/local_cli.py`, `examples/mcp-toolkits.yaml`,
  `examples/dev_loop/mcp-toolkits.example.yaml`, `examples/dev_loop/mcp_wiring.py`,
  `docs/mcp-local-toolkits.md` (modify)
- **Responsibility**: Every place that assumes implicit builtins (design research S9).
- **Depends on**: M7
- **Interface Skeleton**:
  ```python
  # parrot/mcp/local_cli.py  (modifies :113-117)
  #   Unknown NAME now fails with:
  #   "Error: no toolkit named 'browsing' is configured. Install it with:
  #    parrot toolkits install browsing"
  #   Docstring at :35-45 stops calling the three names "built-ins".
  ```

### Module 10: Cross-host test matrix
- **Path**: `packages/ai-parrot/tests/mcp/`, `tests/mcp/`,
  `packages/ai-parrot/tests/knowledge/wiki/` (modify + new)
- **Responsibility**: The matrix in §4 (design research S10).
- **Depends on**: M1–M9

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_load_config_no_file_is_empty` | M3 | No file ⇒ empty config (replaces `test_no_file_returns_builtins`, `tests/mcp/test_toolkit_config.py:17`) |
| `test_explicit_missing_config_still_raises` | M3 | Named `config_path` absent ⇒ ValueError (unchanged) |
| `test_preflight_rejects_unknown_name_before_write` | M4 | Unknown name ⇒ ValueError, file byte-identical afterwards |
| `test_preflight_rejects_malformed_yaml` | M4 | Malformed file ⇒ ValueError, no append |
| `test_set_section_enabled_preserves_comments` | M4 | Comments, quoted keys, nested maps survive a toggle |
| `test_remove_section_preserves_neighbours` | M4 | Removing the middle section leaves the others and their comments intact |
| `test_seed_write_is_atomic` | M4 | Simulated failure mid-write leaves the original file |
| `test_templates_parse_and_declare_class` | M5 | All five templates load and their `class:` is a resolvable dotted string |
| `test_list_does_not_import_toolkits` | M6 | `inventory()` with `sys.modules` assertions — no toolkit class imported |
| `test_dist_available_uses_find_spec` | M6 | Missing distribution ⇒ `dist_available=False`, no ImportError raised |
| `test_inventory_excludes_wikitoolkit` | M6 | wikitoolkit never appears in a row |
| `test_install_unknown_name_is_atomic` | M6 | No section seeded, no host touched |
| `test_reconcile_preserves_wikitoolkit` | M2 | Each host: wikitoolkit entry byte-identical before/after a toolkit reconcile |
| `test_reconcile_preserves_foreign_entry` | M2 | Foreign `parrot-<name>` key untouched + warning returned |
| `test_toolkit_server_names_excludes_wikitoolkit` | M2 | The new split function never returns `"wikitoolkit"` |
| `test_disable_removes_entry_keeps_section` | M6 | `enabled: false`, kwargs intact, host entry gone |
| `test_uninstall_removes_only_its_approvals` | M6 | Claude `enabledMcpjsonServers` keeps wikitoolkit and foreign names |
| `test_google_reports_user_global_scope` | M1 | `is_repo_scoped()` is False; both config paths reported |
| `test_no_tty_without_names_exits_2` | M7 | Non-interactive invocation fails with the non-interactive hint |
| `test_install_flags_removed` | M8 | `--toolkits` / `--all-toolkits` are rejected by all three host CLIs |
| `test_empty_config_warning` | M8 | Host install with no toolkit config names `parrot toolkits install` |
| `test_mcp_local_unknown_name_names_command` | M9 | Error text contains `parrot toolkits install` |

### Integration Tests
| Test | Description |
|---|---|
| `test_install_enable_disable_uninstall_roundtrip` | Full lifecycle against a temp repo with all three host configs |
| `test_mcp_local_e2e_after_install` | `parrot toolkits install memory` then spawn `parrot mcp-local memory` and complete a JSON-RPC handshake (adapts `tests/mcp/test_mcp_local_e2e.py`) |
| `test_no_secret_in_any_written_file` | Seed both DB templates with a DSN in the environment; assert it appears in no written file |

### Test Data / Fixtures
```python
# Temp repo with .mcp.json, .codex/config.toml and a redirected user-global
# mcp_config.json (Google's path is monkeypatched — never the real ~/.gemini).
@pytest.fixture
def repo_with_hosts(tmp_path, monkeypatch) -> Path: ...

@pytest.fixture
def foreign_entries(repo_with_hosts) -> Path:
    """Pre-seed a hand-written parrot-scraping entry that is NOT our shape."""
```

---

## 5. Acceptance Criteria

- [ ] **AC1** `parrot toolkits list` shows all five templates with summary, state,
      per-host entry state, drift and dependency availability — and imports no
      toolkit class (asserted, not assumed).
- [ ] **AC2** `parrot toolkits install/uninstall/enable/disable` work
      interactively (picker) and non-interactively (`NAMES`, `--host`, `--yes`);
      a no-TTY run without NAMES exits 2 with the non-interactive form named.
- [ ] **AC3** `querysource` and `database-query` templates install and produce a
      working `parrot mcp-local <name>` server.
- [ ] **AC4** `BUILTIN_TOOLKITS` no longer exists anywhere in the tree
      (`grep -r BUILTIN_TOOLKITS` returns nothing) and `load_toolkits_config`
      returns an empty config when no file is present.
- [ ] **AC5** No `parrot toolkits` subcommand ever adds, refreshes or removes a
      `wikitoolkit` entry, in any of the three hosts (asserted per host).
- [ ] **AC6** No installer path writes a credential: with a DSN exported in the
      environment, that value appears in no file the command writes.
- [ ] **AC7** Every builtin consumer is updated in the same change:
      `local_cli.py`, `docs/mcp-local-toolkits.md`, `examples/mcp-toolkits.yaml`,
      `examples/dev_loop/mcp-toolkits.example.yaml`, `examples/dev_loop/mcp_wiring.py`,
      and this repo's `.mcp.json`. A repo-wide search for implicit-builtin
      assumptions is part of the check.
- [ ] **AC8** A mutation that fails preflight (unknown name, malformed YAML)
      leaves `.parrot/mcp-toolkits.yaml` byte-identical.
- [ ] **AC9** `--toolkits` / `--all-toolkits` are gone from all three host CLIs,
      and each `install_*_integration` no longer accepts `toolkits`.
- [ ] **AC10** Operator comments and formatting in `.parrot/mcp-toolkits.yaml`
      survive enable, disable and remove.
- [ ] **AC11** All tests pass: `pytest tests/mcp/ packages/ai-parrot/tests/mcp/ packages/ai-parrot/tests/knowledge/wiki/ -v`
- [ ] **AC12** `ruff check` and `black --check` clean on every touched file.
- [ ] **AC13** `docs/mcp-local-toolkits.md` documents the new command and no
      longer claims the three names work without YAML.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified 2026-09-18 against `dev` @ the FEAT-570 reservation commit.

### Verified Imports
```python
from parrot.mcp.toolkit_config import MCPToolkitsConfig, ToolkitSection, load_toolkits_config  # verified: toolkit_config.py:19,79,105
from parrot.mcp.toolkit_config import BUILTIN_TOOLKITS   # verified: toolkit_config.py:89 — DELETED BY THIS FEATURE
from parrot.mcp.toolkit_seed import (                     # verified: toolkit_seed.py:26,35,47,61,127,154
    SeedResult, ToolkitTemplate, available_templates, load_template,
    seed_toolkit_sections, template_drift,
)
from parrot.tools.databasequery import DatabaseQueryToolkit    # verified: databasequery/__init__.py:31
from parrot_tools.querysource import QuerysourceToolkit        # verified: querysource/__init__.py:22
from parrot.tools.toolkit import AbstractToolkit               # verified: tools/toolkit.py:206
import questionary   # verified: core dependency, packages/ai-parrot/pyproject.toml:165
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):          # line 19
    class_path: str = Field(..., alias="class")     # line 49
    enabled: bool = True                            # line 50
    kwargs: dict[str, Any]
    include: list[str] | None
    exclude: list[str] | None
    llm: str | None
    llm_kwargs: dict[str, Any]
    env: dict[str, str]                             # line 56 — copied VERBATIM into host entries
class MCPToolkitsConfig(BaseModel):       # line 79
    toolkits: dict[str, ToolkitSection]
BUILTIN_TOOLKITS: dict[str, ToolkitSection]         # line 89 — scraping/browsing/memory at 91/95/99
def load_toolkits_config(root, config_path=None) -> MCPToolkitsConfig:   # line 105
    # line 143 seeds `merged` from BUILTIN_TOOLKITS — the deletion point

# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
TEMPLATE_PACKAGE = "parrot.mcp"           # line 17
TEMPLATE_DIR = "_toolkit_templates"       # line 18
REPO_ROOT_PLACEHOLDER = "{{repo_root}}"   # line 19
_META_PREFIX = "# parrot:"                # line 20 — parses ONLY summary:/requires_llm: (:83-89)
_DRIFT_IGNORED_KEYS = frozenset({"enabled"})   # line 23
class ToolkitTemplate(BaseModel): name; body; requires_llm; summary   # line 26
class SeedResult(BaseModel): created_file; added; skipped; unknown; drift   # line 35
def available_templates() -> tuple[str, ...]          # line 47
def load_template(name) -> ToolkitTemplate            # line 61 — raises KeyError
def template_drift(root, name) -> list[str]           # line 127
def seed_toolkit_sections(root, names) -> SeedResult  # line 154

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _install_permissions(root) -> list[str]                          # line 251
def _managed_server_names(root) -> list[str]                         # line 304  (seeds ["wikitoolkit"] at :332)
def _install_mcp_approval(root) -> str                               # line 340
def _uninstall_mcp_approval(root, removed_toolkit_names=()) -> str|None   # line 371 — already name-selective
def _is_managed_toolkit_entry(entry, root, name) -> bool             # line 420  (args[:2] == ["mcp-local", name] at :440)
def _install_mcp_json(root) -> str                                   # line 462  (key f"parrot-{name}" at :512; foreign skip :517; cleanup :528-532)
def install_claude_integration(root, config=None, git_hook=True, gitignore=True,
                               bookstore=True, toolkits=(), approve_mcp=True) -> list[str]   # line 770
def uninstall_claude_integration(root) -> list[str]                  # line 862
def integration_status(root) -> dict[str, Any]                       # line 992

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _existing_table_names(text) -> set[str]                          # line 100
def _install_mcp(root) -> str                                        # line 110
def install_codex_integration(...) -> list[str]                      # line 202  (toolkits param at :207)
def uninstall_codex_integration(root) -> list[str]                   # line 265
def integration_status(root) -> dict[str, Any]                       # line 312

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _is_managed_toolkit_entry(entry, root, name) -> bool              # line 73
def _install_mcp(root, mcp_path=None) -> list[str]                    # line 139
#   wikitoolkit entry written at :148-160; toolkit entries :162-186; cleanup :187-191
#   repo plugin file .agents/plugins/parrot/mcp_config.json written at :214
def install_google_integration(...) -> list[str]                      # line 239
def uninstall_google_integration(...) -> list[str]                    # line 304
def integration_status(...) -> dict[str, Any]                         # line 379

# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
PLUGIN_DIR = Path(".agents/plugins/parrot")                           # line 19
def default_mcp_config_path() -> Path                                 # line 59 — ~/.gemini/config/mcp_config.json (USER-GLOBAL)
def resolve_binary(root, name) -> str                                 # line 64
def toolkit_mcp_entries(root, sections) -> dict[str, dict[str, Any]]  # line 81
#   args at :95 == ["mcp-local", name, "--config", config_path]; entry["env"] = dict(section.env) at :99

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
def toolkit_mcp_block(root, sections) -> str                          # line 60

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                            # line 56
    tool_prefix = "qs"                                                # line 59
    exclude_tools = ("open", "close")                                 # line 60
    confirming_tools = frozenset({"save_multiquery"})                 # line 61
    auto_open = True                                                  # line 62
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False,
                 allow_external_sources=True, include_sql=True, max_rows=200,
                 forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)   # line 64

# packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py
def default_dsn() -> str      # line 63 — returns querysource.conf.asyncpg_url (env-driven)

# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
class DatabaseQueryToolkit(AbstractToolkit):                          # line 115
    tool_prefix = "dq"                                                # line 147
    def __init__(self, **kwargs)                                      # line 154 — ONLY output_dir/static_dir (:166-167)
    async def get_database_metadata(...)   # 234
    async def validate_query(...)          # 265   -> dq_validate_query
    async def get_table_metadata(...)      # 298
    async def test_connection(...)         # 325
    async def execute_database_query(self, driver, query, credentials=None,
                                     params=None, max_rows=10000)     # 355 — credentials is PER-CALL
    async def fetch_database_row(...)      # 397
    async def save_result(...)             # 434 — excluded unless output_dir set (:174-176)

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                           # line 206
    exclude_tools: tuple[str, ...] = ()        # 243
    tool_prefix: str | None = None             # 257
    confirming_tools: frozenset = frozenset()  # 275
    llm_dependent_tools: frozenset = frozenset()   # 294
    auto_open: bool = False                    # 319
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_lazy_commands["toolkits"]` | `parrot.cli.cli` | LazyGroup dict entry | `parrot/cli/__init__.py:110-133` |
| `ClaudeAdapter` | `_is_managed_toolkit_entry` | via new `reconcile_toolkit_entries` | `claude_code/installer.py:420` |
| `CodexAdapter` | `_existing_table_names` | via new `reconcile_toolkit_tables` | `codex/installer.py:100` |
| `GoogleAdapter` | `default_mcp_config_path` + `PLUGIN_DIR` | two config paths | `google/assets.py:59,19` |
| picker | `questionary.checkbox` | sync call in Click callback | `knowledge/wiki/cli.py:4591,4602` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot toolkits`~~ — no such command group; `parrot/cli/toolkits.py` does not
  exist and `_lazy_commands` has no `"toolkits"` key.
- ~~`parrot/mcp/toolkit_install.py`~~, ~~`parrot/mcp/hosts.py`~~ — do not exist.
- ~~`querysource.yaml`~~, ~~`database-query.yaml`~~, ~~`scraping.yaml`~~,
  ~~`browsing.yaml`~~, ~~`memory.yaml`~~ — only `bounded-source`,
  `targeted-writer`, `sdd-coder` ship in `_toolkit_templates/`.
- ~~`DatabaseQueryToolkit.validate_database_query()`~~ — **does not exist**. The
  method is `validate_query` (`toolkit.py:265`) ⇒ tool `dq_validate_query`.
- ~~`DatabaseQueryToolkit(dsn=…)`~~ / ~~`(credentials=…)`~~ / ~~`(allow_write=…)`~~
  / ~~`(allow_raw_sql=…)`~~ — none are constructor parameters.
- ~~`QuerysourceToolkit.allow_ddl`~~ — not a parameter (`allow_write`,
  `allow_raw_sql`, `allow_external_sources`).
- ~~`codex.installer._is_managed_toolkit_entry`~~ — **does not exist**; Codex uses
  `_existing_table_names` + marker block instead.
- ~~`ToolkitSection.host`~~ / ~~`.hosts`~~ / ~~`.requires_dist`~~ — no such fields
  (`requires_dist` is new *template header* metadata, not a section field).
- ~~`${VAR}` interpolation in `ToolkitSection.env`~~ — values are copied verbatim
  (`google/assets.py:99`); parrot performs no expansion.
- ~~`toolkit_seed.remove_toolkit_section()`~~ / ~~`set_enabled()`~~ — no toggle or
  removal helper exists; seeding is append-only and never rewrites a section.
- ~~`ruamel.yaml`~~ — not a declared dependency of `packages/ai-parrot`.
- ~~a repo-relative Google MCP config~~ — `default_mcp_config_path()` is
  `~/.gemini/config/mcp_config.json`, user-global.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `LazyGroup` registration for the new command (`parrot/cli/__init__.py`), so
  `parrot --help` stays fast and the group imports nothing until invoked.
- `questionary` is **blocking**: call it synchronously from the Click callback,
  before any async work — the constraint is documented at
  `knowledge/wiki/cli.py:4588-4590`.
- Template bodies keep the `# parrot:` header convention and `{{repo_root}}`
  placeholder (`toolkit_seed.py:19-20`).
- YAML mutation is a **lexical edit + atomic replace** (write temp, `os.replace`),
  never `yaml.safe_dump` of a parsed model — no round-trip parser is declared.
- Google-style docstrings, strict type hints, 120 columns, `self.logger`.

### Known Risks / Gotchas
- **Wikitoolkit contamination (S1, high).** The three existing `_install_mcp*`
  entry points rewrite the wikitoolkit entry as a side effect. Extracting
  toolkit-only reconcilers is mandatory, and AC5 asserts it per host.
- **Host asymmetry (S2, high).** Codex has no `_is_managed_toolkit_entry`; Google
  writes two files, one of them user-global. Code that assumes a symmetric
  private helper will not work.
- **Claude approval scope (S3, high).** `_managed_server_names` seeds
  `["wikitoolkit"]` (`:332`), so it must not be reused for `parrot toolkits`
  approvals; `toolkit_server_names` is split out for that. `_uninstall_mcp_approval`
  is already name-selective — reuse it as-is.
- **Non-atomic seeding today (S4, high).** `seed_toolkit_sections` swallows the
  load-time `ValueError`, appends, and only fails on reload; and it seeds valid
  names even when the request contains an unknown one. `preflight_seed` fixes both.
- **Comment loss (S5, high).** Operator kwargs and comments in
  `.parrot/mcp-toolkits.yaml` must survive toggles — AC10.
- **Dependency vs template availability (S6).** A template installs fine while its
  distribution is missing; `querysource` defers its ImportError to `_open`. Report
  availability via `find_spec` without importing.
- **Stale test suites (pre-existing, out of scope).**
  `packages/ai-parrot/tests/tools/databasequery/test_toolkit.py:32` and
  `test_toolkit_abstracttoolkit_contract.py:32` assert `dq_validate_database_query`,
  a tool name the implementation cannot generate (no such method), and they
  contradict `tests/tools/test_database_toolkit_parity.py:59,63`. Recorded here so
  an implementing agent does not "fix" the template to match a broken test. Also
  note this repo has **two** test trees (`tests/` and `packages/*/tests/`).
- **Local venv caveat.** `packages/ai-parrot/tests/` is currently uncollectable in
  the local venv (navigator-session pin); rely on CI for those suites.
- **This repo breaks itself.** `.mcp.json` here carries `parrot-browsing`,
  `parrot-memory`, `parrot-scraping`. After the cut they stop resolving until
  reinstalled — AC7 covers doing it in the same change.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `questionary` | `>=2.1.1` | Interactive picker — already a core dependency (`pyproject.toml:165`) |
| `rich` | `>=13.0` | `list` / `status` tables — already core (`pyproject.toml:131`) |
| `click` | `>=8.1.7` | Command group — already core |
| `PyYAML` | (existing) | Reading the config; writing is lexical, not dumped |

**No new dependencies.** Adding `ruamel.yaml` for round-trip YAML was considered
and rejected (S5): a narrowly-scoped lexical editor with explicit tests is cheaper
than a new core dependency for two operations.

---

## 8. Open Questions

- [x] Full replacement vs. additive command — *Resolved in brainstorm*: full
  replacement; `--toolkits`/`--all-toolkits` removed from all three host CLIs.
- [x] Which hosts are targetable — *Resolved in brainstorm*: all three.
- [x] Credentials — *Resolved in brainstorm*: templates ship `env: {}`; the DSN is
  inherited from the spawned process's environment. The installer never writes a secret.
- [x] Safety posture — *Resolved in brainstorm*: `querysource` seeds
  `allow_write: true` + `allow_raw_sql: true`; `database-query` seeds `output_dir`
  (its only permissive knob — no write gates exist on that class).
- [x] Fate of scraping/browsing/memory — *Resolved in brainstorm*: packaged
  templates; `BUILTIN_TOOLKITS` deleted.
- [x] Migration — *Resolved in brainstorm*: hard cut, reinstall required.
- [x] Subcommand set — *Resolved in brainstorm*: install/uninstall, enable/disable,
  list/status, all with non-interactive flags.
- [x] wikitoolkit visibility — *Resolved in brainstorm*: invisible to this command.
- [x] `list` vs `status` — *Resolved in brainstorm*: two subcommands; `list` is the
  table, `status` reports per-host config paths and health.
- [x] Template ownership — *Resolved in brainstorm*: accept core-bundled templates
  for v1; entry-point discovery (Option D) remains the follow-up.
- [x] Warn when the toolkit config is empty after the cut — *Resolved in brainstorm*: yes.

- [ ] **Q1. Google's target and scope** (raised by design research S8, independently
  confirmed). Google is not repo-scoped like the other two: `_install_mcp` writes
  the **user-global** `~/.gemini/config/mcp_config.json` (`assets.py:59`) *and* the
  repo-local `.agents/plugins/parrot/mcp_config.json` (`installer.py:214`).
  "Install into all detected hosts" therefore means something different for Google —
  it would mutate a file shared by every project on the machine. Options:
  (a) auto-detect Google only when its user-global file exists, and print an
  explicit "this affects all projects" warning; (b) require an explicit
  `--host google`, never auto-detect; (c) write only the repo plugin file by
  default and touch the user-global one only with `--mcp-config`.
  **Interim default for implementation: (a)** — it honors "all detected hosts"
  while surfacing the blast radius. — *Owner: Jesus*
- [x] **Q2.** Should `parrot toolkits uninstall` also delete a toolkit's on-disk
  artifacts (e.g. `.parrot/scraping_plans`, `.parrot/db_results`)? Interim
  default: **no** — remove config only, never operator data. — *Owner: Jesus*: only remove config

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted brainstorm**.
> Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning_effort=high) · Status: completed
> · Transcript: `sdd/state/FEAT-570/design_research/`
> All 31 `affected_paths` passed containment and existence verification.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Add toolkit-only host reconciliation (architecture) | CONFIRM | Verified: all three `_install_mcp*` also rewrite the wikitoolkit entry (`claude_code:462`, `google:148-160`, `codex:110`) — calling them would mutate an artifact this command does not own | §2 Overview, §3 M2, AC5 |
| S2 | Model host asymmetry explicitly (architecture) | CONFIRM | Verified: Codex has no `_is_managed_toolkit_entry`; it uses `_existing_table_names` (`codex:100`) + marker block. Google has two config files | §3 M1 |
| S3 | Handle Claude approvals selectively (risk) | CONFIRM | Verified: `_managed_server_names` seeds `["wikitoolkit"]` (`:332`). Partial correction — `_uninstall_mcp_approval` (`:371`) is already name-selective | §3 M2, §7 |
| S4 | Preflight mutations before seeding (risk) | CONFIRM | Verified: load-time `ValueError` is swallowed, the file is appended to, and unknown names do not stop valid ones being seeded | §3 M4, AC8 |
| S5 | Choose a real comment-preserving YAML strategy (api) | CONFIRM | Verified: no `ruamel` declared; seeding is append-only text. Decided: lexical editor + atomic replace, no new dependency | §3 M4, §7, AC10 |
| S6 | Make dependency availability metadata explicit (api) | CONFIRM | Verified: the `# parrot:` parser handles only `summary:`/`requires_llm:` (`toolkit_seed.py:83-89`) | §3 M5, §3 M6 |
| S7 | Derive database-toolkit info from the actual contract (api) | REJECT | Premise false: `validate_query` exists (`toolkit.py:265`); `validate_database_query` exists nowhere in `parrot/tools/databasequery/`. The brainstorm's `dq_validate_query` is correct; the two suites cited assert an ungeneratable name and contradict `tests/tools/test_database_toolkit_parity.py:59,63` | §7 (recorded as pre-existing defect) |
| S8 | Define Google's target and state precisely (risk) | ESCALATE | Verified: user-global `~/.gemini/config/mcp_config.json` **and** repo `.agents/plugins/parrot/mcp_config.json`. "All detected hosts" cannot mean the same thing for a user-global file | §8 Q1 |
| S9 | Audit all builtin consumers in the same change (risk) | CONFIRM | Verified: `examples/dev_loop/mcp_wiring.py`, `local_cli.py:35`, `docs/mcp-local-toolkits.md`, `examples/mcp-toolkits.yaml`, `.mcp.json` all assume implicit builtins | §3 M9, AC7 |
| S10 | Add a cross-host command matrix before removing old flags (testing) | CONFIRM | Verified: `test_installer_mcp.py` is the only suite covering the `--toolkits` flags | §4, §3 M10 |

Summary: **8** confirmed · **1** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-570
  (`.claude/worktrees/feat-FEAT-570-expose-local-mcp-tools`, from `origin/dev`).
  The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → (none) — refactor of the three installers
  - M1 → M2 (adapters wrap the functions M2 extracts)
  - M3 → (none)
  - M4 → M3 (drops the `BUILTIN_TOOLKITS` import and its filtering workaround)
  - M5 → M3 (the three builtin bodies move into templates verbatim)
  - M6 → M1, M4
  - M7 → M6
  - M8 → M7 (the new warning names the command M7 creates)
  - M9 → M7 (the `mcp-local` error names it too)
  - M10 → M1–M9
  - M3 and M2 have no edge between them and are expected to run concurrently;
    likewise M4 and M5 once M3 lands.
- **Shared files** (their tasks serialize):
  - `parrot/mcp/toolkit_seed.py` — M4 (helpers) and M5 (the `requires_dist` header parser)
  - `parrot/knowledge/wiki/{claude_code,codex,google}/installer.py` — M2 (extract) and M8 (flag cut)
  - `parrot/cli/__init__.py` — M7 only
- **Exclusive resources**: none — no extension rebuild, lockfile or migration.
  This repo's own `.mcp.json` is rewritten once, in M9, as the last code task.
- **Cross-feature dependencies**: none blocking. FEAT-569 (`wikitoolkit-http-mcp`,
  approved, TASK ids reserved) touches
  `parrot/knowledge/wiki/{claude_code,codex,google}/{cli,installer}.py` — the same
  files as M2/M8. Coordinate merge order with FEAT-569 or expect conflicts there.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-18 | Jesus Lara (with Claude) | Initial draft from accepted brainstorm; design research folded in (8 CONFIRM / 1 REJECT / 1 ESCALATE) |
