---
type: feature
base_branch: dev
---

# Feature Specification: `parrot claude install` seeds and authorizes the Parrot MCP servers

**Feature ID**: FEAT-556
**Date**: 2026-09-12
**Author**: Jesus Lara (with Claude Opus 5)
**Status**: draft
**Target version**: 1.0.1

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot claude install` leaves a repository *almost* wired for the Parrot MCP
servers, and the remaining gap is closed by hand-editing two operator-local
files. Three concrete failures, all observed on 2026-09-12 while migrating the
`sdd-worker` / `sdd-coder` lane into the sibling `flowtask` repository:

1. **The installer never creates `.parrot/mcp-toolkits.yaml`.** It persists
   `.parrot/wiki.json` (`installer.py:625`) and nothing else under `.parrot/`.
   `_install_mcp_json` then derives `.mcp.json` entries from
   `load_toolkits_config(root)` (`installer.py:361-363`), which — with no file
   present — returns only the three built-ins `scraping`, `browsing`, `memory`
   (`toolkit_config.py:89-102`). Every other toolkit (`sdd-coder`,
   `bounded-source`, `targeted-writer`) is invisible to the installer, so the
   operator must hand-append its YAML section. `examples/sdd-coder-mcp.yaml:6-17`
   documents that manual two-step procedure verbatim — including a `sed`
   append and a warning not to `cp` over the file. A feature whose install
   instructions are a `sed` pipeline is not installed.

2. **The installer never authorizes the servers it registers.** Claude Code
   treats project-scope `.mcp.json` servers as untrusted until they are
   enabled. Verified experimentally in `../flowtask`: with a correct `.mcp.json`
   and a correct YAML, `claude mcp list` reported `parrot-sdd-coder … ⏸ Pending
   approval (run claude to approve)`, and the `sdd-worker` agent — whose
   frontmatter whitelists `mcp__parrot-sdd-coder__*` — found no tools and fell
   back to its sequential loop. Adding the server names to
   `enabledMcpjsonServers` in `.claude/settings.local.json` flipped all of them
   to `✔ Connected`. The installer already owns that exact file for permission
   rules (`_install_permissions`, `installer.py:251-302`), so the write has a
   home; it simply does not happen.

3. **A managed entry breaks inside a git worktree.** `assets.toolkit_mcp_json_entry`
   emits `args = ["mcp-local", <name>]` with no `--config` and no `cwd`
   (`assets.py:140-160`), while `parrot mcp-local` resolves the project root as
   `Path.cwd()` (`local_cli.py:105`) and therefore reads
   `<cwd>/.parrot/mcp-toolkits.yaml` (`toolkit_config.py:138`). In a worktree —
   where `sdd-worker` runs — that path does not exist, so the server exits.
   Reproduced in `.claude/worktrees/feat-496-dev-loop-dispatch-event-legibility`:

   ```
   $ claude mcp list
   parrot-bounded-source: … mcp-local bounded-source - ✘ Failed to connect — CONNECTION_CLOSED
   parrot-targeted-writer: … mcp-local targeted-writer - ✘ Failed to connect — CONNECTION_CLOSED
   parrot-sdd-coder: … mcp-local sdd-coder --config /…/ai-parrot/.parrot/mcp-toolkits.yaml - ✔ Connected
   $ parrot mcp-local bounded-source
   Error: Unknown toolkit name: 'bounded-source'. Resolvable: ['scraping', 'browsing', 'memory']
   ```

   Only the hand-written entry carrying an absolute `--config` survives. The
   managed shape is the one that fails.

### Goals

- `parrot claude install` leaves a repo where the Parrot MCP servers are
  **usable and authorized** with no manual file editing: the YAML exists, the
  `.mcp.json` entries exist, the servers are approved.
- `.parrot/mcp-toolkits.yaml` is **created and seeded by the installer** from
  templates that ship inside the wheel, because `.parrot/` is git-ignored by
  the installer itself (`_install_gitignore`, `installer.py:568-582`) and can
  never arrive via `git clone`.
- A managed `.mcp.json` toolkit entry works from **any** cwd, worktrees
  included.
- Authorization is **narrow**: only the servers the installer manages, by name.
- Every step stays **idempotent and ownership-aware**, matching FEAT-485's
  existing contract: never overwrite a foreign entry, never clobber operator
  edits, remove on uninstall exactly what was written.

### Non-Goals (explicitly out of scope)

- `enableAllProjectMcpServers`. Verified unnecessary — per-name
  `enabledMcpjsonServers` alone connects exactly the listed servers and leaves
  unlisted ones pending — and it silently authorizes any future third-party
  entry in `.mcp.json`. It must not be written.
- Wiring the seeding into `parrot codex install` / `parrot google install`.
  Their installers read the same `load_toolkits_config` (`codex/installer.py:122,130`;
  `google/installer.py:114,136`), so M1 is written tool-agnostic for them, but
  their CLI surface is a follow-up.
- Provisioning credentials. Seats whose keys are absent are dropped by the
  `sdd-coder` roster probe at `coder_plan` time; that stays runtime behavior.
- Restarting the Claude Code session. MCP config is read at startup, so a
  freshly installed repo still needs a new session — documented, not automated.

---

## 2. Architectural Design

### Overview

Three additions, in a fixed order inside `install_claude_integration`:

1. **Seed** (new, tool-agnostic): `parrot/mcp/toolkit_seed.py` renders
   requested toolkit sections from packaged templates
   (`parrot/mcp/_toolkit_templates/*.yaml`) into
   `<root>/.parrot/mcp-toolkits.yaml`, creating the file when absent and
   appending only the sections it does not already contain. Templates are
   credential-free; the only substitution is `{{repo_root}}` → the resolved
   install root. A template that needs an operator-chosen model is seeded
   `enabled: false` with an instructional comment, so install never produces
   a server that cannot start.
2. **Pin** (change): a managed toolkit entry gains an absolute
   `--config <root>/.parrot/mcp-toolkits.yaml` and `cwd: <root>`, making
   resolution independent of the host's cwd. `_is_managed_toolkit_entry`
   accepts the legacy two-arg shape as well, so existing hand-written entries
   are *adopted* into management instead of being warned about and skipped.
3. **Approve** (new): after `.mcp.json` reconciliation has settled the final
   managed-name set, those names — `wikitoolkit` plus one `parrot-<name>` per
   enabled section — are merged into `enabledMcpjsonServers` in
   `.claude/settings.local.json`, alongside the permission rules already
   written there. Uninstall removes exactly those names; `integration_status`
   reports both the approval state and the seeded YAML.

Order matters and is part of the contract: seeding must precede reconciliation
(so the new sections produce entries), and approval must follow it (so the name
set is final).

### Component Diagram

```
parrot claude install
      │
      ├─(1)─→ parrot/mcp/toolkit_seed.py ──→ .parrot/mcp-toolkits.yaml
      │            │  reads packaged templates          ▲
      │            └── parrot/mcp/_toolkit_templates/*.yaml
      │                                                 │
      ├─(2)─→ _install_mcp_json ──→ load_toolkits_config ┘
      │            └── assets.toolkit_mcp_json_entry ──→ .mcp.json
      │                  (+ --config <abs>, cwd <root>)
      │
      └─(3)─→ _install_mcp_approval ──→ .claude/settings.local.json
                                         enabledMcpjsonServers: [...]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `install_claude_integration` (`installer.py:589`) | extends | two new kwargs (`toolkits`, `approve_mcp`); two new steps in the action list, ordered seed → mcp_json → approval |
| `_install_mcp_json` (`installer.py:321`) | unchanged logic, new input | sees the seeded sections; its add/update/remove reconciliation is reused as-is |
| `assets.toolkit_mcp_json_entry` (`assets.py:140`) | modifies | entry gains `--config` + `cwd` |
| `_is_managed_toolkit_entry` (`installer.py:304`) | modifies | accepts legacy and pinned shapes |
| `_install_permissions` (`installer.py:251`) | sibling | same file, same `_load_settings`/`_write_settings` helpers (`installer.py:159,183`) |
| `uninstall_claude_integration` (`installer.py:643`) | extends | removes managed names from `enabledMcpjsonServers`; leaves the seeded YAML in place (operator data) |
| `integration_status` (`installer.py:769`) | extends | two new keys |
| `load_toolkits_config` (`toolkit_config.py:105`) | uses | used to validate the seeded file by re-loading it |
| `parrot claude install` CLI (`claude_code/cli.py:54-86`) | extends | new options, same `--flag/--no-flag` style as `--bookstore` / `--tool-guards` |

### Data Models

```python
# parrot/mcp/toolkit_seed.py
class ToolkitTemplate(BaseModel):
    """One packaged `.parrot/mcp-toolkits.yaml` section, ready to render."""

    name: str                     # section key, e.g. "sdd-coder"
    body: str                      # YAML fragment, two-space indented under `toolkits:`
    requires_llm: bool = False     # seeded `enabled: false` + instructional comment when True
    summary: str = ""              # one line, echoed in the install action string


class SeedResult(BaseModel):
    """Outcome of one seeding run."""

    created_file: bool             # the YAML did not exist and was created
    added: list[str]               # sections written
    skipped: list[str]             # sections already present, left untouched
    unknown: list[str]             # requested names with no packaged template
```

### New Public Interfaces

```python
# parrot/mcp/toolkit_seed.py
def available_templates() -> tuple[str, ...]: ...
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: packaged templates + seeder | yes | `ToolkitTemplate`/`SeedResult` fields fixed above; read via `importlib.resources.files("parrot.mcp") / "_toolkit_templates"` exactly as `conventions._package_rule` does (`conventions.py:48-50`); append-only merge; validate by re-loading with `load_toolkits_config`; package-data entry mirrors `"parrot.flows" = ["_rules_data/*.md"]` (`packages/ai-parrot/pyproject.toml:907`) | — |
| M2: pinned managed entry shape | yes | entry dict and both accepted arg shapes fixed in the skeleton below | — |
| M3: approval writer | yes | key name, merge semantics and removal semantics fixed below; `enableAllProjectMcpServers` forbidden | — |
| M4: CLI + orchestration | no | default for `--toolkits` is §8 Q1 — an operator-facing policy call |

### Module 1: Packaged toolkit templates + seeder
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (new),
  `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/{sdd-coder,bounded-source,targeted-writer}.yaml` (new),
  `packages/ai-parrot/pyproject.toml` (modifies: package-data)
- **Responsibility**: own `.parrot/mcp-toolkits.yaml` creation and append-only
  section seeding from wheel-shipped, credential-free templates. Tool-agnostic:
  no Claude-Code import.
- **Depends on**: `load_toolkits_config` (`toolkit_config.py:105`) for validation
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/mcp/toolkit_seed.py  (new)
  TEMPLATE_DIR: str = "_toolkit_templates"
  REPO_ROOT_PLACEHOLDER: str = "{{repo_root}}"

  def available_templates() -> tuple[str, ...]:
      """Return the packaged template names, sorted (stem of each shipped .yaml)."""

  def load_template(name: str) -> ToolkitTemplate:
      """Read one packaged template.

      Raises:
          KeyError: no template named `name` ships with this wheel.
      """

  def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:
      """Create/extend `<root>/.parrot/mcp-toolkits.yaml` with the named sections.

      Creates the file with a `toolkits:` root when absent; appends only
      sections whose key is not already present (an existing section is NEVER
      rewritten — it is operator data); renders `{{repo_root}}` as `root`;
      writes a `requires_llm` template with `enabled: false` plus the comment
      telling the operator to set `llm` and flip it. Re-loads the result with
      `load_toolkits_config(root)` before returning and raises if the file it
      just wrote does not parse.

      Returns:
          SeedResult naming what was created, added, skipped and unknown.

      Raises:
          ValueError: the file exists but is malformed, or the rendered result
              fails to re-load.
      """
  ```

### Module 2: Managed entry pinned to an absolute config path
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`
  (modifies `assets.py:140`),
  `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
  (modifies `installer.py:304`)
- **Responsibility**: make a managed toolkit server start from any cwd, and
  adopt the legacy/hand-written shape instead of treating it as foreign.
- **Depends on**: Module 1 (the file the entry points at)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py  (modifies assets.py:140)
  def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:
      """Build the `.mcp.json` entry for one exposed toolkit (FEAT-485, pinned by FEAT-556).

      Returns `{"command": <abs parrot bin>, "args": ["mcp-local", name,
      "--config", str(root / ".parrot" / "mcp-toolkits.yaml")], "cwd": str(root),
      "env": dict(section.env)}` — `parrot mcp-local` resolves its root from
      `Path.cwd()` (verified: parrot/mcp/local_cli.py:105), so an unpinned entry
      resolves nothing in a worktree.
      """

  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py  (modifies installer.py:304)
  def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:
      """Whether a `parrot-<name>` entry was written by us.

      Accepts the pinned shape `["mcp-local", name, "--config", <any path>]`
      and the pre-FEAT-556 shape `["mcp-local", name]`; the `command` check is
      unchanged (ends with the resolved `parrot` binary name). Accepting the
      legacy shape is what lets reconciliation upgrade an operator's
      hand-written entry in place instead of skipping it with a warning
      (installer.py:374-382).
      """
  ```

### Module 3: MCP approval in `settings.local.json`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
  (new `_install_mcp_approval`; modifies `uninstall_claude_integration`
  `installer.py:643` and `integration_status` `installer.py:769`)
- **Responsibility**: authorize exactly the managed servers, by name, and undo
  exactly that on uninstall.
- **Depends on**: Module 2 (the managed-name set), `_load_settings` /
  `_write_settings` (`installer.py:159,183`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py  (new)
  def _managed_server_names(root: Path) -> list[str]:
      """`["wikitoolkit", "parrot-<name>", ...]` for every enabled toolkit section.

      Same source of truth as reconciliation: `load_toolkits_config(root)`
      filtered on `section.enabled` (verified: installer.py:361-364).
      """

  def _install_mcp_approval(root: Path) -> str:
      """Merge the managed server names into `.claude/settings.local.json`.

      Appends missing names to `enabledMcpjsonServers` (creating the key as a
      list), preserving order and any name the operator added. NEVER writes
      `enableAllProjectMcpServers`: per-name approval is sufficient (verified
      2026-09-12) and the global switch would also authorize unrelated
      third-party entries.

      Returns:
          One human-readable action string, the same style as
          `_install_permissions` (installer.py:294-301).

      Raises:
          RuntimeError: `enabledMcpjsonServers` exists but is not a JSON list.
      """

  def _uninstall_mcp_approval(root: Path) -> str | None:
      """Remove only the managed names from `enabledMcpjsonServers`.

      Drops the key when it becomes empty; leaves foreign names untouched;
      returns None when there was nothing to remove.
      """
  ```

### Module 4: CLI surface and install orchestration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py`
  (modifies `cli.py:54-86`),
  `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
  (modifies `install_claude_integration` `installer.py:589`)
- **Responsibility**: expose the two capabilities and fix the step order.
- **Depends on**: Modules 1-3
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py  (modifies installer.py:589)
  def install_claude_integration(
      root: Path,
      config: Optional[WikiProjectConfig] = None,
      git_hook: bool = True,
      gitignore: bool = True,
      bookstore: bool = True,
      toolkits: Sequence[str] = (),      # names to seed; () seeds nothing
      approve_mcp: bool = True,          # write enabledMcpjsonServers
  ) -> list[str]:
      """Install the wiki ↔ Claude Code integration into a repository.

      Step order is part of the contract: seeding (`toolkits`) runs BEFORE
      `_install_mcp_json` so the new sections produce entries, and approval
      runs AFTER it so the managed-name set is final.
      """

  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py  (modifies cli.py:54-86)
  @click.option("--toolkits", "toolkits_", default="", help="Comma-separated toolkit sections to seed into .parrot/mcp-toolkits.yaml.")
  @click.option("--all-toolkits", is_flag=True, default=False, help="Seed every toolkit template shipped with this release.")
  @click.option("--approve-mcp/--no-approve-mcp", default=True, show_default=True, help="Authorize the managed MCP servers in .claude/settings.local.json.")
  def install(...) -> None:
      """..."""
  ```

---

## 4. Test Specification

Wiki/installer tests live in the repo-root `tests/knowledge/wiki/` tree (see
§7 Known Risks), next to `test_installer_toolkit_entries.py` and
`test_claude_code.py`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_available_templates_lists_packaged_names` | M1 | `sdd-coder`, `bounded-source`, `targeted-writer` resolve from package data (importlib.resources, not a repo path) |
| `test_seed_creates_yaml_when_absent` | M1 | no `.parrot/mcp-toolkits.yaml` → file created with a `toolkits:` root and the requested section; `created_file is True` |
| `test_seed_appends_without_touching_existing_sections` | M1 | pre-existing operator section survives byte-identical; new section appended; `skipped` names the untouched one |
| `test_seed_renders_repo_root_placeholder` | M1 | no `{{repo_root}}` remains; rendered value equals the resolved root |
| `test_seed_requires_llm_section_disabled` | M1 | a `requires_llm` template is written `enabled: false`, so `_install_mcp_json` emits no entry for it |
| `test_seed_result_reloads_via_load_toolkits_config` | M1 | the written file parses and the seeded names appear in `load_toolkits_config(root).toolkits` |
| `test_seed_unknown_name_reported_not_raised` | M1 | unknown name lands in `SeedResult.unknown`; the known ones are still seeded |
| `test_toolkit_entry_pins_config_and_cwd` | M2 | entry carries `--config <root>/.parrot/mcp-toolkits.yaml` and `cwd == str(root)` |
| `test_legacy_entry_is_adopted_and_upgraded` | M2 | a two-arg `["mcp-local", name]` entry is recognized as managed and rewritten to the pinned shape — no stderr warning |
| `test_foreign_entry_still_untouched` | M2 | an entry with a different `command` is left alone and warned about (FEAT-485 behavior preserved) |
| `test_approval_adds_managed_names` | M3 | `enabledMcpjsonServers` contains `wikitoolkit` + one `parrot-<name>` per enabled section |
| `test_approval_preserves_foreign_names` | M3 | an operator-added name survives; order stable |
| `test_approval_never_writes_enable_all` | M3 | `enableAllProjectMcpServers` absent from the written settings |
| `test_approval_idempotent` | M3 | second run reports "already authorized" and leaves the file byte-identical |
| `test_approval_rejects_non_list_key` | M3 | a string value raises `RuntimeError` naming the file |
| `test_uninstall_removes_only_managed_names` | M3 | managed names gone, foreign name kept, key dropped when empty |
| `test_status_reports_approval_and_seeded_yaml` | M3 | `integration_status` exposes both new keys |
| `test_install_seeds_before_reconciliation` | M4 | `install_claude_integration(root, toolkits=["sdd-coder"])` yields a `parrot-sdd-coder` entry in one pass |
| `test_install_no_approve_flag_skips_approval` | M4 | `approve_mcp=False` writes no `enabledMcpjsonServers` |

### Integration Tests
| Test | Description |
|---|---|
| `test_install_then_mcp_local_resolves_from_foreign_cwd` | after `install_claude_integration(root, toolkits=["bounded-source"])`, invoking the entry's `command`+`args` with `cwd` set elsewhere resolves the toolkit (the worktree failure mode, asserted without a live MCP host) |
| `test_fresh_repo_roundtrip` | install → status reports seeded+approved → uninstall → approval names removed, seeded YAML retained |

### Test Data / Fixtures
```python
@pytest.fixture
def repo_root(tmp_path):
    """Bare repo root with .claude/ and a wiki config, as in
    tests/knowledge/wiki/test_installer_toolkit_entries.py:tmp_root_with_config."""
```

---

## 5. Acceptance Criteria

- [ ] On a repo with no `.parrot/`, `parrot claude install --toolkits sdd-coder`
      creates `.parrot/mcp-toolkits.yaml` containing a `sdd-coder:` section and
      a `parrot-sdd-coder` entry in `.mcp.json`, in a single run.
- [ ] That same run adds `wikitoolkit` and every managed `parrot-<name>` to
      `enabledMcpjsonServers` in `.claude/settings.local.json`.
- [ ] `enableAllProjectMcpServers` is never written by any code path.
- [ ] A managed `.mcp.json` toolkit entry carries an absolute `--config` and
      `cwd`, and its toolkit resolves when the process is started from an
      unrelated cwd (worktree case).
- [ ] A pre-existing hand-written `parrot-<name>` entry with `["mcp-local", name]`
      or with `--config`/`cwd` is adopted and upgraded in place — no "already
      exists and was not written by parrot claude install" warning for it.
- [ ] Re-running install is a no-op: no duplicated YAML section, no duplicated
      name in `enabledMcpjsonServers`, existing operator sections byte-identical.
- [ ] `parrot claude uninstall` removes exactly the managed names from
      `enabledMcpjsonServers` (foreign names kept) and leaves the seeded YAML.
- [ ] `parrot claude status` reports the approval state and whether the YAML is
      seeded.
- [ ] Templates contain no credentials and no operator-specific absolute path
      other than the rendered `{{repo_root}}`.
- [ ] A `requires_llm` template is seeded disabled, so install never produces a
      server that cannot start.
- [ ] Templates resolve from the installed wheel
      (`importlib.resources.files("parrot.mcp")`), verified by a test that does
      not read from the repository tree.
- [ ] All tests pass: `pytest tests/knowledge/wiki/ -v` and
      `pytest packages/ai-parrot/tests/knowledge/wiki/ -v`.
- [ ] `ruff check` and `black --check` clean on the touched files.
- [ ] No breaking change to the public `install_claude_integration` signature
      (new parameters are keyword-defaulted).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets  # verified: installer.py:33
from parrot.knowledge.wiki.claude_code.installer import (  # verified: packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py:4-8
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: installer.py:361
from parrot.mcp.toolkit_config import BUILTIN_TOOLKITS, MCPToolkitsConfig, ToolkitSection  # verified: toolkit_config.py:89,79,19
from importlib.resources import files  # verified: parrot/flows/conventions.py:11 (packaged-data read pattern)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):                       # line 19
    class_path: str = Field(..., alias="class")        # line 49
    enabled: bool = True                               # line 50
    kwargs: dict[str, Any]                             # line 51
    include: list[str] | None                          # line 52
    exclude: list[str] | None                          # line 53
    llm: str | None                                    # line 54
    llm_kwargs: dict[str, Any]                         # line 55
    env: dict[str, str]                                # line 56
    model_config = ConfigDict(populate_by_name=True)   # line 58

class MCPToolkitsConfig(BaseModel):                    # line 79
    toolkits: dict[str, ToolkitSection]                # line 86

BUILTIN_TOOLKITS: dict[str, ToolkitSection]            # line 89 — only scraping, browsing, memory
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig:  # line 105
    # default path: root / ".parrot" / "mcp-toolkits.yaml"  # line 138
    # missing default path → builtins only (no raise)       # lines 147-150
    # explicit missing path → ValueError                    # line 149

# packages/ai-parrot/src/parrot/mcp/local_cli.py
root = Path.cwd()                                      # line 105 — the worktree failure's root cause

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _load_settings(path: Path) -> Optional[dict[str, Any]]: ...   # line 159
def _write_settings(path: Path, settings: dict[str, Any]) -> None: ...  # line 183
def _install_permissions(root: Path) -> list[str]: ...            # line 251 (writes .claude/settings.local.json)
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: ...  # line 304
def _install_mcp_json(root: Path) -> str: ...                     # line 321
def _uninstall_mcp_json(root: Path) -> str | None: ...            # line 411
def _install_gitignore(root: Path) -> str: ...                    # line 568 (.parrot/ is git-ignored)
def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True) -> list[str]: ...  # line 589
def uninstall_claude_integration(root: Path) -> list[str]: ...    # line 643
def integration_status(root: Path) -> dict[str, Any]: ...         # line 769

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
PERMISSION_RULES: tuple[str, ...]                                 # line 53
MCP_JSON_ENTRY: dict                                              # line 71
def mcp_json_entry(root: Path) -> dict: ...                       # line 109
def resolve_parrot_bin(root: Path) -> str: ...                    # line 118
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict: ...  # line 140
def permission_rules(root: Path) -> tuple[str, ...]: ...          # line 179

# packages/ai-parrot/src/parrot/flows/conventions.py — packaged-data read pattern to copy
def _package_rule(name: str) -> str:                              # line 48
    return (files("parrot.flows") / "_rules_data" / f"{name}.md").read_text(encoding="utf-8")  # line 50
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `seed_toolkit_sections` | `load_toolkits_config()` | post-write validation | `packages/ai-parrot/src/parrot/mcp/toolkit_config.py:105` |
| `install_claude_integration` | `seed_toolkit_sections()` | call before `_install_mcp_json` | `installer.py:630` (current `_install_mcp_json` call site) |
| `_install_mcp_approval` | `_write_settings()` | settings write | `installer.py:183` |
| `_managed_server_names` | `load_toolkits_config(root)` + `section.enabled` | same filter as reconciliation | `installer.py:363-364` |
| `toolkit_mcp_json_entry` | `resolve_parrot_bin()` | absolute binary path | `assets.py:118` |
| packaged templates | `[tool.setuptools.package-data]` | `"parrot.mcp" = ["_toolkit_templates/*.yaml"]` | `packages/ai-parrot/pyproject.toml:894-907` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.mcp.toolkit_seed`~~ — new in this feature; nothing seeds
  `.parrot/mcp-toolkits.yaml` today (only `.parrot/wiki.json` is written, via
  `save_project_config`, `installer.py:625`).
- ~~`parrot/mcp/_toolkit_templates/`~~ — does not exist; the only templates are
  repo-root `examples/{mcp-toolkits,sdd-coder-mcp,tool-optimizations-mcp}.yaml`,
  which are NOT package data (`packages/ai-parrot/pyproject.toml:894-907` lists
  no `examples` entry) and therefore unavailable from an installed wheel.
- ~~`sdd-coder` / `bounded-source` / `targeted-writer` in `BUILTIN_TOOLKITS`~~ —
  only `scraping`, `browsing`, `memory` are built in (`toolkit_config.py:89-102`).
- ~~`enabledMcpjsonServers` handling anywhere in the installer~~ — the string
  does not occur in `parrot/knowledge/wiki/`; approval has never been written.
- ~~`cwd` or `--config` in a managed `.mcp.json` toolkit entry~~ —
  `toolkit_mcp_json_entry` returns only `command`/`args`/`env` (`assets.py:154-158`).
- ~~a `--toolkits` / `--approve-mcp` option on `parrot claude install`~~ — the
  command's options are `--path`, `--git-hook`, `--gitignore`, `--build`,
  `--bookstore`, `--tool-guards` (`cli.py:54-86`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Every install step returns a human-readable action string (or list) and is
  appended to `actions` in `install_claude_integration` — match
  `_install_permissions`' phrasing, including the "already …" no-op variant
  (`installer.py:294-301`).
- Ownership detection before mutation: the FEAT-485 rule (never overwrite what
  we did not write, warn and skip instead) governs M2 and M3 equally.
- Read packaged data through `importlib.resources.files(...)`, never via
  `Path(__file__).parent` — `conventions.py:48-50` is the reference.
- Pydantic v2 models, Google-style docstrings, strict type hints, 120 columns.
- `.parrot/mcp-toolkits.yaml` is operator data: append, never rewrite, and
  never delete on uninstall.

### Known Risks / Gotchas
- **Wiki/installer tests live in the repo-root `tests/` tree**, not in
  `packages/ai-parrot/tests/`, despite the "tests live next to their
  distribution" convention: `tests/knowledge/wiki/` holds `test_claude_code.py`
  and `test_installer_toolkit_entries.py`, while `packages/ai-parrot/tests/knowledge/wiki/`
  holds `test_installer_mcp.py`. Extend both where behavior changes; do not
  migrate either file in this feature.
- A YAML append must not corrupt an operator file that lacks a trailing
  newline or whose `toolkits:` key is absent — handle both, and fail loudly
  (`ValueError` naming the path) rather than writing a half-valid file.
- `_install_mcp_json` skips disabled sections, which is exactly why a
  `requires_llm` template is seeded disabled: a `targeted-writer` section
  needs an operator-chosen `llm` (the live config uses
  `bedrock-converse:qwen3-coder-480b-a35b` with `fallback_model: null`), and
  seeding it enabled would register a server that cannot start.
- Changing the managed entry shape rewrites existing `.mcp.json` entries on the
  next install in every repo that already has them — intended (it fixes the
  worktree failure), but it is a visible diff in an operator-local file and
  must be stated in the action string.
- Claude Code reads MCP config at session start: a fresh install still needs a
  new session before the tools appear. Say so in the CLI output.
- `settings.local.json` is ignored by the user's global gitignore
  (`~/.config/git/ignore: **/.claude/settings.local.json`), so approval is
  per-machine by construction — that is the correct scope, not a defect.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none; `pyyaml`, `pydantic` and `click` are already direct dependencies |

---

## 8. Open Questions

- [ ] **Q1 — What does `--toolkits` default to?** Options: (a) empty, opt-in per
      repo, `--all-toolkits` to seed everything; (b) seed every shipped
      template by default. (a) keeps `parrot claude install` from silently
      registering a model-seat orchestrator (`sdd-coder`) in an unrelated repo;
      (b) is what "no manual copying" literally asks for. Recommendation: (a)
      plus a one-line hint naming `--all-toolkits` in the install output —
      *Owner: Jesus Lara*
- [ ] **Q2 — Should seeding also be wired into `parrot codex install` and
      `parrot google install` in this feature, or as a follow-up?** M1 is
      tool-agnostic either way; only the CLI wiring and their managed-entry
      shapes would change. Recommendation: follow-up, to keep this spec small —
      *Owner: Jesus Lara*
- [ ] **Q3 — Does `uninstall` deserve a `--purge-toolkits` flag** that also
      removes the sections it seeded (currently: never touch the YAML)?
      Recommendation: no flag in v1 — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `—` · Status: skipped (no exploration
> document — `/sdd-spec` was invoked directly with free-form notes, so there is
> no accepted brainstorm/proposal to brief a reviewer with) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- Default isolation unit: **per-spec** — all four modules touch the same two
  files (`installer.py`, `assets.py`) plus one new module; sequential tasks in
  one worktree avoid self-inflicted merge conflicts.
- M1 (new module + templates + package-data) is the only task that could run in
  parallel, but it is also the dependency of M2-M4, so the graph is effectively
  linear: M1 → M2 → M3 → M4.
- Cross-feature dependencies: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-12 | Jesus Lara (with Claude Opus 5) | Initial draft — FEAT-556 |
