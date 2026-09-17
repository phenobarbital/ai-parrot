---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: `parrot toolkits` — on-demand local-MCP toolkit installation

**Date**: 2026-09-18
**Author**: Jesus Lara / Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

FEAT-485 built the generic local-MCP machinery (`parrot mcp-local <name>`,
`.parrot/mcp-toolkits.yaml`, managed `.mcp.json` / `.codex/config.toml` /
`mcp_config.json` reconciliation) and FEAT-556 added packaged **templates**
so a section can be seeded without hand-editing YAML. Three templates ship
today: `bounded-source`, `targeted-writer`, `sdd-coder`.

Two problems remain.

**1. The two database toolkits are invisible.** `QuerysourceToolkit`
(FEAT-558, `parrot_tools.querysource.toolkit`) and `DatabaseQueryToolkit`
(FEAT-105/136, `parrot.tools.databasequery.toolkit`) are exactly the kind of
tool a coding or analysis session wants as a first-class MCP tool — schema
discovery, validated read-only query execution, tenant-scoped query slugs and
MultiQuery pipelines. Neither ships a template, so exposing them means
hand-writing a YAML section from the class signature.

**2. Toolkit selection is a flag buried inside the wrong command.** Today the
only way to choose toolkits is `parrot claude install --toolkits=a,b` or
`--all-toolkits` — a flag on the *wiki* installer. The operator must already
know the template names; `--help` only lists them in a fallback hint after a
no-op run. There is no way to **list** what is available with descriptions,
no way to **disable** one without hand-editing YAML and re-running the host
installer, and no way to **uninstall** one at all.

Compounding this: `scraping`, `browsing` and `memory` are hardcoded as
`BUILTIN_TOOLKITS` (`toolkit_config.py:89`) and resolve implicitly whether or
not the operator wants them. A repo that never asked for browser automation
still has `browsing` resolvable, and `parrot claude install` will happily
write a `parrot-browsing` entry. The owner's decision is that **nothing
except wikitoolkit should be implicit** — every local MCP server becomes
opt-in and individually toggleable.

**Who is affected**: every operator wiring an ai-parrot repo into Claude
Code, Codex, or Google Antigravity — plus the ai-parrot repo itself, whose
`.mcp.json` currently carries `parrot-browsing`, `parrot-memory` and
`parrot-scraping` entries that resolve through the builtins.

## Constraints & Requirements

- **Full replacement.** `parrot toolkits` becomes the *only* toolkit
  selection surface. `--toolkits=` / `--all-toolkits` are removed from
  `parrot claude|codex|google install` (hard cut — no external consumers, per
  project policy).
- **All three hosts.** Claude Code (`.mcp.json`), Codex
  (`.codex/config.toml`), Google Antigravity (`mcp_config.json`) must all be
  installable/uninstallable targets.
- **No secrets on disk.** The installer must never prompt for, capture, or
  write a DSN or credential. `ToolkitSection.env` values are copied
  **verbatim** into the host entry (`google/assets.py:99`), and `.mcp.json`
  is git-tracked in this repo — so a baked secret would be committed.
- **`BUILTIN_TOOLKITS` is deleted.** `scraping`, `browsing` and `memory`
  become packaged templates like any other; `load_toolkits_config` returns
  only sections actually declared in the file.
- **Hard cut on migration.** No auto-migration of existing installs. Repos
  re-run `parrot toolkits install` and pick what they want.
- **wikitoolkit stays invisible** to this command — it remains owned by
  `parrot claude install` and its siblings.
- Every subcommand needs a non-interactive form (`--yes`, explicit names,
  `--host`) so CI and scripts never block on a picker.
- Lean startup preserved: listing templates must not import any toolkit
  class (the existing `--list` contract, `local_cli.py:35`).

---

## Options Explored

### Option A: `parrot toolkits` group over the existing seed + reconcile machinery

A new top-level lazy Click group `toolkits` with five subcommands
(`list`, `install`, `uninstall`, `enable`, `disable`) that orchestrates
machinery which **already exists and is already tested**:

- selection → `toolkit_seed.available_templates()` / `load_template()` for
  names and `# parrot:summary:` descriptions;
- seeding → `toolkit_seed.seed_toolkit_sections()`;
- host wiring → the three hosts' existing `_install_mcp*` reconcilers, which
  already derive their entry set from `load_toolkits_config(root)` filtered
  on `section.enabled`.

The decisive insight: **enable/disable already works end-to-end today.** All
three host installers compute desired entries from enabled sections and
remove entries for sections that are disabled or deleted
(`claude_code/installer.py:528-532`, `google/installer.py:187-191`,
`codex/installer.py:134`). `parrot toolkits disable X` is therefore a YAML
flag flip plus a re-run of the host reconciler — no new reconciliation logic.

Five new templates ship: `querysource`, `database-query`, plus `scraping`,
`browsing`, `memory` migrated out of `BUILTIN_TOOLKITS`. `BUILTIN_TOOLKITS`
is deleted, which also removes the awkward workaround block in
`toolkit_seed.py:193-205` that exists solely to filter builtins back out of
`load_toolkits_config`'s result.

Interactive picker uses `questionary.checkbox` — already a **core**
dependency (`pyproject.toml:165`), already used this way in
`knowledge/wiki/cli.py:4591-4606`.

✅ **Pros:**
- Smallest new surface for the largest capability gain — most of the work is
  wiring and five YAML templates, not new subsystems.
- Reuses three independently-tested reconcilers; foreign-entry protection,
  marker blocks and managed-shape detection all come for free.
- Deleting `BUILTIN_TOOLKITS` *simplifies* two modules rather than
  complicating them.
- `list` gives the operator something they have never had: available
  toolkits with descriptions and per-host installed state.
- Non-interactive forms fall out naturally (names as arguments, `--yes`).

❌ **Cons:**
- Touches all three host installers to remove the `toolkits` parameter
  (hard cut) — a wide, if shallow, diff.
- Breaks existing installs in this repo and any other that relies on the
  builtins; deliberate, but it is real churn.
- A fourth host added later means touching `parrot toolkits` too, not just
  that host's installer.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `questionary>=2.1.1` | Interactive checkbox/select picker | Already a **core** dependency (`pyproject.toml:165`); precedent at `wiki/cli.py:4602`. Blocking — must never be called from async code. |
| `click>=8.1.7` | CLI group, options, `--yes` confirmation | Core dep; `LazyGroup` pattern already in `parrot/cli/__init__.py`. |
| `rich>=13.0` | Tabular `list` output | Core dep (`pyproject.toml:131`). |
| `PyYAML` | Read/write `enabled:` in the config | Already used by `toolkit_config.py` / `toolkit_seed.py`. |

🔗 **Existing Code to Reuse:**
- `parrot/mcp/toolkit_seed.py` — `available_templates()`, `load_template()`,
  `seed_toolkit_sections()`, `template_drift()`, `SeedResult`.
- `parrot/mcp/toolkit_config.py` — `ToolkitSection`, `load_toolkits_config()`.
- `parrot/knowledge/wiki/claude_code/installer.py:462` `_install_mcp_json`,
  `:340` `_install_mcp_approval`, `:420` `_is_managed_toolkit_entry`.
- `parrot/knowledge/wiki/codex/installer.py:110` `_install_mcp`.
- `parrot/knowledge/wiki/google/installer.py:139` `_install_mcp`.
- `parrot/cli/__init__.py` — `LazyGroup` + `_lazy_commands` registration.
- `parrot/mcp/_toolkit_templates/bounded-source.yaml` — template format with
  `# parrot:summary:` / `# parrot:requires_llm:` headers.

---

### Option B: Interactive flags on the existing host installers

No new command group. Add `--pick` / `--interactive` to
`parrot claude|codex|google install`, which opens the same checkbox picker
and feeds the result into the existing `toolkits=` parameter. Add
`parrot claude toolkits-list` style subcommands per host for visibility.

✅ **Pros:**
- Zero new top-level command; the operator stays in the one command they
  already run to set up a repo.
- No hard cut — `--toolkits=` keeps working, so nothing breaks.
- Smallest possible diff.

❌ **Cons:**
- Triples the surface: the same picker, list and toggle logic must be
  attached to three sibling command groups, or factored into a shared module
  that is then *almost* Option A anyway but without a home.
- Conceptually wrong: toolkit selection is host-agnostic, but this binds it
  to whichever host command the operator happened to run. Installing a
  toolkit for Codex and Claude means running two commands with two pickers.
- Does not satisfy the owner's "full replacement" decision, and leaves
  `BUILTIN_TOOLKITS` in place or removes it with no natural command to
  re-add the toolkits from.
- No obvious place for `enable` / `disable` / `uninstall`.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `questionary>=2.1.1` | Picker | Same as Option A. |
| `click>=8.1.7` | Flags on existing commands | Core dep. |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/{claude_code,codex,google}/cli.py` — the three
  `install` commands and their `--toolkits` / `--all-toolkits` options.

---

### Option C: Declarative MCP profile with `parrot toolkits apply`

Treat the set of exposed toolkits as **desired state**. A single
`.parrot/mcp-profile.yaml` declares which toolkits are wanted and which hosts
should carry them; `parrot toolkits apply` reconciles every host to that
declaration (Terraform-style plan/apply, with `--dry-run` showing the diff).
`install` / `enable` / `disable` become thin sugar that edit the profile and
call `apply`.

✅ **Pros:**
- One idempotent code path for every mutation — install, uninstall, enable
  and disable are all just "edit desired state, reconcile".
- The profile is committable, so a team shares one MCP setup and a new
  clone runs a single `parrot toolkits apply`.
- `--dry-run` makes a wide, multi-host change auditable before it lands —
  genuinely valuable when three config files are being rewritten.
- Drift detection generalizes: `template_drift()` becomes one input to a
  broader plan rather than a special case.

❌ **Cons:**
- Introduces a **second** config file whose relationship to
  `.parrot/mcp-toolkits.yaml` (which already has an `enabled:` flag, i.e.
  already is partial desired state) is genuinely confusing. Two sources of
  truth for "is this toolkit on?" is worse than one.
- Significantly more design and code than the gap justifies — the gap is
  "there is no picker and no template for two toolkits".
- The per-host targeting the profile would model is speculative; no evidence
  operators want different toolkit sets per host.
- Ships a mental model (plan/apply) the rest of the parrot CLI does not use.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | Profile schema | Core. |
| `PyYAML` | Profile I/O | Core. |
| `rich>=13.0` | Plan diff rendering | Core dep. |

🔗 **Existing Code to Reuse:**
- `parrot/mcp/toolkit_config.py` — `enabled:` is the seed of desired state.
- The three `_install_mcp*` reconcilers as the apply backends.
- `toolkit_seed.template_drift()` as a plan input.

---

### Option D: Entry-point auto-discovery (FEAT-485's deferred door)

FEAT-485 explicitly deferred "entry-point auto-discovery (Option D — possible
follow-up, not precluded)". Each distribution advertises its exposable
toolkits via `[project.entry-points."parrot.mcp_toolkits"]`, so
`ai-parrot-tools` ships `querysource`, core ships `database-query` and
`memory`, and `parrot toolkits list` enumerates whatever is *installed* in
the environment rather than whatever templates core happens to bundle.

✅ **Pros:**
- Genuinely extensible: a third-party or private distribution exposes a
  toolkit with no change to core, no release of core, no PR.
- The list is honest by construction — it can only offer toolkits whose code
  is actually importable, so `parrot mcp-local X` cannot fail with
  `ModuleNotFoundError` after a successful install.
- Removes the smell of core bundling a template for
  `parrot_tools.querysource...`, a class core does not own and cannot import.

❌ **Cons:**
- Entry-point scanning at list time pulls distribution metadata for every
  installed package — slower than reading a directory, and the "never import
  a toolkit class" guarantee needs care to preserve.
- Templates carry more than a class path (kwargs, comments, safety defaults,
  `{{repo_root}}`); an entry point gives a dotted path, so the template
  bodies still have to live *somewhere* — likely back in each distribution,
  which is a packaging change across four distributions.
- Solves an extensibility problem nobody has hit yet, while the immediate
  ask is two templates and a picker.
- Does not by itself deliver `list` / `enable` / `disable`.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | `entry_points(group=...)` | Stdlib. |
| `importlib.resources` | Template bodies per distribution | Stdlib; already used at `toolkit_seed.py:63`. |

🔗 **Existing Code to Reuse:**
- `parrot/mcp/toolkit_seed.py` — `ToolkitTemplate` model and the
  `# parrot:` header parser survive unchanged; only the *source* of
  templates changes.
- Every `packages/*/pyproject.toml` — where entry points would be declared.

---

## Recommendation

**Option A** is recommended.

The honest framing of this feature is that **~85% of it already exists**.
FEAT-485 built the runner and the three host reconcilers; FEAT-556 built
packaged templates, seeding, and drift reporting. What is missing is a
front door (a picker and a `list`), two templates, and the removal of an
implicit-defaults mechanism that predates the template system and now
contradicts it. Option A is the option scoped to exactly that.

The tradeoff against **Option C** is deliberate: C's plan/apply model is
genuinely better *if* toolkit management grows per-host targeting, staged
rollouts, or team-shared profiles. None of that is asked for, and buying it
now costs a second config file whose overlap with `mcp-toolkits.yaml`'s
existing `enabled:` flag would be a standing source of confusion. If the
need appears, A's subcommands are the natural sugar to put on top of C
later — A does not preclude C.

The tradeoff against **Option D** is about sequencing, not merit. D is the
right long-run answer to "who owns a template", and core bundling a template
whose `class:` points into `parrot_tools` is a real wart that D would fix.
But D is a packaging change across four distributions that delivers none of
the `list`/`enable`/`disable` capability the owner actually asked for. A
ships the capability; D remains open as a follow-up that can change the
template *source* without changing the command surface A establishes.

**Option B** is rejected outright: it distributes host-agnostic logic across
three host-specific commands and has no home for `enable`/`disable`/
`uninstall`.

What Option A trades away: it accepts a wide (if shallow) diff across the
three host installers to remove `--toolkits=`, and it accepts breaking
existing installs. Both are owner decisions, and the hard cut is consistent
with this project's no-deprecation-shims policy.

---

## Feature Description

### User-Facing Behavior

A new top-level command group:

```
parrot toolkits list
parrot toolkits install [NAMES...] [--host claude|codex|google]... [--yes]
parrot toolkits uninstall [NAMES...] [--host ...] [--yes]
parrot toolkits enable NAMES... [--host ...]
parrot toolkits disable NAMES... [--host ...]
```

**`list`** prints every packaged template with its `# parrot:summary:`
description and its current state — `not installed`, `enabled`, or
`disabled` — plus which hosts carry an entry, and a drift marker when the
on-disk section lacks keys the template has gained. It imports no toolkit
class. wikitoolkit never appears.

**`install`** with no NAMES opens a `questionary.checkbox` picker listing
available templates (already-installed ones pre-checked), then a host
selection if `--host` was not given. On confirmation it seeds the chosen
sections into `.parrot/mcp-toolkits.yaml` and runs each selected host's
reconciler, reporting each action. With NAMES given it skips the picker;
with `--yes` it skips the confirmation. For Claude Code it also authorizes
the new servers in `.claude/settings.local.json` via the existing
`_install_mcp_approval` path, and reminds the operator that a new session is
required for the servers to appear.

**`uninstall`** removes both the YAML section and the managed host entries.
**`disable`** sets `enabled: false` and drops the host entries while keeping
the section and all its configured kwargs, so `enable` restores it for free.

Two new templates become available immediately:

- **`querysource`** → `parrot_tools.querysource.toolkit.QuerysourceToolkit`,
  tools prefixed `qs_` (`qs_list_slugs`, `qs_describe_slug`,
  `qs_execute_slug`, `qs_run_multiquery`, `qs_validate_pipeline`,
  `qs_get_dialect_reference`, `qs_list_components`, and `qs_save_multiquery`
  when `allow_write`).
- **`database-query`** → `parrot.tools.databasequery.toolkit.DatabaseQueryToolkit`,
  tools prefixed `dq_` (`dq_get_database_metadata`, `dq_get_table_metadata`,
  `dq_validate_query`, `dq_execute_database_query`, `dq_fetch_database_row`,
  `dq_test_connection`, and `dq_save_result` when `output_dir` is set).

Three existing behaviors move: `scraping`, `browsing` and `memory` are no
longer implicit. `parrot toolkits list` offers them; until installed,
`parrot mcp-local browsing` fails.

`parrot claude|codex|google install` lose `--toolkits` and `--all-toolkits`
and no longer seed anything. They continue to reconcile host entries from
whatever `.parrot/mcp-toolkits.yaml` declares, so running them after a
`parrot toolkits` change remains valid and idempotent.

### Internal Behavior

A new module — `parrot/mcp/toolkit_install.py` — holds the host-agnostic
orchestration, and `parrot/cli/toolkits.py` holds the Click group (lazy-
registered in `parrot/cli/__init__.py::_lazy_commands`). The orchestration
layer exposes three responsibilities:

1. **Inventory.** Join `available_templates()` (what can be installed)
   against `load_toolkits_config(root)` (what is declared, and whether
   enabled) against each host's config file (which entries exist and are
   ours, via that host's `_is_managed_toolkit_entry`). Produces one row per
   template. No toolkit class is imported.
2. **Mutation.** Seed via `seed_toolkit_sections()`; toggle by rewriting the
   `enabled:` key of a section; remove by deleting the section. The YAML
   rewrite must preserve operator comments and hand-edited kwargs — a
   round-trip-safe edit, not a `yaml.safe_dump` of the parsed model.
3. **Host reconcile.** Dispatch to the selected hosts' existing reconcilers,
   which recompute their entry set from the now-current config. Because they
   are already reconcilers rather than appenders, a disable propagates as a
   removal with no new code.

`BUILTIN_TOOLKITS` is deleted from `toolkit_config.py`; `load_toolkits_config`
returns only file-declared sections, and the builtin-filtering workaround in
`seed_toolkit_sections` is deleted with it. Five templates are added to
`parrot/mcp/_toolkit_templates/`.

The picker is invoked synchronously from the Click callback, before any
async work — `questionary` is blocking and must never run inside an event
loop (the constraint is already documented at `wiki/cli.py:4588-4590`).

### Edge Cases & Error Handling

- **No TTY** (CI, piped stdin): the picker cannot run. `install`/`uninstall`
  with no NAMES must fail with a message naming the non-interactive form
  rather than hanging or raising from questionary.
- **Unknown name**: `seed_toolkit_sections` already returns it in
  `SeedResult.unknown` — surface it as a non-zero exit with the available
  names listed, and seed nothing.
- **Section already present**: never rewritten (existing contract). Report
  it as skipped, and report any `template_drift()` keys so the operator can
  copy them in by hand.
- **Foreign host entry** at a colliding `parrot-<name>` key: the existing
  reconcilers already detect and preserve it. Surface the warning rather
  than swallowing it.
- **Toolkit not importable** — `querysource` needs the optional
  `querysource` distribution, `scraping`/`browsing` need `ai-parrot-tools`.
  Install succeeds (templates are inert config); the failure surfaces at
  server start. `list` should flag the likely-missing distribution without
  importing the class, and install should print the install hint.
- **Disable of a section that is not installed**: no-op with a clear
  message, not an error.
- **Malformed `.parrot/mcp-toolkits.yaml`**: `load_toolkits_config` raises
  `ValueError` naming the file and section; surface verbatim and mutate
  nothing.
- **Partial host failure** (e.g. `.codex/config.toml` unwritable while
  `.mcp.json` succeeds): report per-host outcomes and exit non-zero; do not
  roll back the YAML, since re-running is idempotent.
- **Post-cut breakage**: `parrot mcp-local browsing` on a repo that relied on
  the builtins now fails. The error must name `parrot toolkits install
  browsing` explicitly — this is the sole migration aid the hard cut gets.

---

## Capabilities

### New Capabilities
- `toolkit-install-cli`: `parrot toolkits` group — list/install/uninstall/
  enable/disable local MCP toolkits across Claude Code, Codex and Antigravity,
  interactively or non-interactively.
- `database-toolkit-templates`: packaged `querysource` and `database-query`
  templates exposing both DB toolkits as local stdio MCP servers.

### Modified Capabilities
- `expose-toolkits-as-local-mcp` (FEAT-485,
  `sdd/specs/expose-toolkits-as-local-mcp.spec.md`) — `BUILTIN_TOOLKITS` is
  removed; implicit toolkit resolution is no longer part of the contract.
- The FEAT-556 seeding capability — `--toolkits` / `--all-toolkits` move off
  the three host `install` commands onto `parrot toolkits`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/cli/__init__.py` | modifies | Register `"toolkits": "parrot.cli.toolkits"` in `_lazy_commands`. |
| `parrot/cli/toolkits.py` | creates | New Click group: list/install/uninstall/enable/disable + questionary picker. |
| `parrot/mcp/toolkit_install.py` | creates | Host-agnostic inventory + mutation + host dispatch. |
| `parrot/mcp/toolkit_config.py` | modifies | **Delete `BUILTIN_TOOLKITS`** (line 89); `load_toolkits_config` returns file sections only. |
| `parrot/mcp/toolkit_seed.py` | modifies | Drop the `BUILTIN_TOOLKITS` import and the builtin-filtering block (193-205). Add a comment-preserving `enabled:` rewrite + section removal. |
| `parrot/mcp/_toolkit_templates/` | creates | `querysource.yaml`, `database-query.yaml`, `scraping.yaml`, `browsing.yaml`, `memory.yaml`. |
| `parrot/knowledge/wiki/claude_code/{cli,installer}.py` | modifies | Remove `--toolkits`/`--all-toolkits` and the `toolkits` parameter of `install_claude_integration` (770). Reconciliation unchanged. |
| `parrot/knowledge/wiki/codex/{cli,installer}.py` | modifies | Same removal on `install_codex_integration` (202). |
| `parrot/knowledge/wiki/google/{cli,installer}.py` | modifies | Same removal on `install_google_integration` (239). |
| `parrot/mcp/local_cli.py` | modifies | Unknown-name error must name `parrot toolkits install <name>`. |
| `.mcp.json` (this repo) | modifies | `parrot-browsing`/`parrot-memory`/`parrot-scraping` must be re-established via the new command, or removed. |
| `docs/mcp-local-toolkits.md` | modifies | Document the new command; remove the builtins section. |
| `examples/mcp-toolkits.yaml`, `examples/dev_loop/mcp-toolkits.example.yaml` | modifies | Must declare scraping/browsing/memory explicitly now. |
| `tests/mcp/test_toolkit_config.py`, `tests/mcp/test_local_cli.py` | modifies | Builtin-resolution assertions are now wrong. |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py`, `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` | modifies | `--toolkits` flag coverage moves. |

**Breaking changes**: yes, deliberately. Implicit `scraping`/`browsing`/
`memory` resolution is removed, and `--toolkits`/`--all-toolkits` are removed
from three commands. No new runtime dependencies — `questionary` and `rich`
are already core.

---

## Code Context

### User-Provided Code

No code snippets were provided during discovery. The request was given as
prose; the decisions captured in Open Questions below are the user-provided
content.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/mcp/toolkit_config.py:19
class ToolkitSection(BaseModel):
    class_path: str = Field(..., alias="class")       # line 49
    enabled: bool = True                               # line 50
    kwargs: dict[str, Any] = Field(default_factory=dict)
    include: list[str] | None = None
    exclude: list[str] | None = None
    llm: str | None = None
    llm_kwargs: dict[str, Any] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)  # line 56
    model_config = ConfigDict(populate_by_name=True)

# From packages/ai-parrot/src/parrot/mcp/toolkit_config.py:79
class MCPToolkitsConfig(BaseModel):
    toolkits: dict[str, ToolkitSection] = Field(default_factory=dict)

# From packages/ai-parrot/src/parrot/mcp/toolkit_config.py:89
BUILTIN_TOOLKITS: dict[str, ToolkitSection] = {
    "scraping": ToolkitSection(
        class_path="parrot_tools.scraping.toolkit.WebScrapingToolkit",      # line 91
        kwargs={"headless": True, "plans_dir": ".parrot/scraping_plans"},
    ),
    "browsing": ToolkitSection(
        class_path="parrot_tools.browsing.toolkit.WebBrowsingToolkit",      # line 95
        kwargs={"catalog_dir": ".parrot/browsing_catalog", "headless": True},
    ),
    "memory": ToolkitSection(
        class_path="parrot.tools.working_memory.tool.WorkingMemoryToolkit", # line 99
        kwargs={},
    ),
}

# From packages/ai-parrot/src/parrot/mcp/toolkit_config.py:105
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig: ...
# line 143: merged = {name: section.model_copy() for name, section in BUILTIN_TOOLKITS.items()}

# From packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:26
class ToolkitTemplate(BaseModel):
    name: str
    body: str
    requires_llm: bool = False
    summary: str = ""

# From packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:35
class SeedResult(BaseModel):
    created_file: bool = False
    added: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    drift: dict[str, list[str]] = Field(default_factory=dict)

# From packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
def available_templates() -> tuple[str, ...]: ...                       # line 47
def load_template(name: str) -> ToolkitTemplate: ...                    # line 61 (raises KeyError)
def template_drift(root: Path, name: str) -> list[str]: ...             # line 127
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult: ...  # line 154

# From packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:770
def install_claude_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    git_hook: bool = True,
    gitignore: bool = True,
    bookstore: bool = True,
    toolkits: Sequence[str] = (),      # <- removed by this feature
    approve_mcp: bool = True,
) -> list[str]: ...
def uninstall_claude_integration(root: Path) -> list[str]: ...          # line 862
def integration_status(root: Path) -> dict[str, Any]: ...               # line 992
def _managed_server_names(root: Path) -> list[str]: ...                 # line 304
def _install_mcp_approval(root: Path) -> str: ...                       # line 340
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: ...  # line 420
def _install_mcp_json(root: Path) -> str: ...                           # line 462

# From packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _install_mcp(root: Path) -> str: ...                                # line 110
def install_codex_integration(...) -> list[str]: ...                    # line 202 (toolkits param at 207)
def uninstall_codex_integration(root: Path) -> list[str]: ...           # line 265
def integration_status(root: Path) -> dict[str, Any]: ...               # line 312

# From packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: ...  # line 73
def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]: ... # line 139
def install_google_integration(...) -> list[str]: ...                   # line 239
def uninstall_google_integration(...) -> list[str]: ...                 # line 304
def integration_status(...) -> dict[str, Any]: ...                      # line 379

# From packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py:60
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str: ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:81
def toolkit_mcp_entries(root: Path, sections: dict[str, ToolkitSection]) -> dict[str, dict[str, Any]]:
    # line 95: "args": ["mcp-local", name, "--config", config_path]
    # line 99: entry["env"] = dict(section.env)   # <- env copied VERBATIM into host config

# From packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py:56
class QuerysourceToolkit(AbstractToolkit):
    tool_prefix: str | None = "qs"                                      # line 59
    exclude_tools: tuple[str, ...] = ("open", "close")                  # line 60
    confirming_tools: frozenset[str] = frozenset({"save_multiquery"})   # line 61
    auto_open: bool = True                                              # line 62
    def __init__(                                                       # line 64
        self,
        programs: list[str] | None = None,
        allow_write: bool = False,
        allow_raw_sql: bool = False,
        allow_external_sources: bool = True,
        include_sql: bool = True,
        max_rows: int = 200,
        forced_conditions: dict[str, Any] | None = None,
        dsn: str | None = None,
        multiquery_timeout: float = 600.0,
        **kwargs: Any,
    ) -> None: ...

# From packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:115
class DatabaseQueryToolkit(AbstractToolkit):
    tool_prefix: Optional[str] = "dq"                                   # line 147
    def __init__(self, **kwargs: Any) -> None: ...                      # line 154
        # ONLY supported kwargs: output_dir, static_dir (lines 166-167);
        # everything else forwards to AbstractToolkit.
    async def execute_database_query(                                   # line 355
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,   # per-CALL, not constructor
        params: Optional[dict[str, Any]] = None,
        max_rows: int = 10000,
    ) -> Union[QueryResult, ValidationResult]: ...

# From packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py
def default_dsn() -> str:
    """Return ``querysource.conf.asyncpg_url`` (conf.py:44)."""
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot.mcp.toolkit_config import BUILTIN_TOOLKITS, MCPToolkitsConfig, ToolkitSection, load_toolkits_config
from parrot.mcp.toolkit_seed import SeedResult, ToolkitTemplate, available_templates, load_template, seed_toolkit_sections, template_drift
from parrot.tools.databasequery import DatabaseQueryToolkit          # parrot/tools/databasequery/__init__.py:31
from parrot_tools.querysource import QuerysourceToolkit              # parrot_tools/querysource/__init__.py:22
from parrot.knowledge.wiki.claude_code.installer import install_claude_integration, integration_status, uninstall_claude_integration
import questionary   # core dependency, pyproject.toml:165
```

#### Key Attributes & Constants

- `toolkit_seed.TEMPLATE_PACKAGE` → `"parrot.mcp"` (toolkit_seed.py:17)
- `toolkit_seed.TEMPLATE_DIR` → `"_toolkit_templates"` (toolkit_seed.py:18)
- `toolkit_seed.REPO_ROOT_PLACEHOLDER` → `"{{repo_root}}"` (toolkit_seed.py:19)
- `toolkit_seed._META_PREFIX` → `"# parrot:"` (toolkit_seed.py:20) — header
  keys parsed today are `summary:` and `requires_llm:` only.
- `toolkit_seed._DRIFT_IGNORED_KEYS` → `frozenset({"enabled"})` (toolkit_seed.py:22)
- Existing templates on disk: `bounded-source.yaml`, `targeted-writer.yaml`,
  `sdd-coder.yaml` (`parrot/mcp/_toolkit_templates/`)
- Host entry key format: `f"parrot-{name}"` (claude_code/installer.py:334, 512)
- Managed-shape test: `args[:2] == ["mcp-local", name]` (claude_code/installer.py:440)
- `parrot/cli/__init__.py` — `cli._lazy_commands` dict; `"mcp-local"` →
  `"parrot.mcp.local_cli"` is the registration precedent.
- questionary-in-Click precedent: `knowledge/wiki/cli.py:4591` (import),
  `:4602` (`questionary.select`), with the "never call inside async code"
  constraint documented at `:4588-4590`.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot toolkits`~~ — no such command group; `parrot/cli/toolkits.py`
  does not exist. `_lazy_commands` has no `"toolkits"` key.
- ~~`parrot/mcp/toolkit_install.py`~~ — does not exist.
- ~~`parrot/mcp/_toolkit_templates/querysource.yaml`~~,
  ~~`database-query.yaml`~~, ~~`scraping.yaml`~~, ~~`browsing.yaml`~~,
  ~~`memory.yaml`~~ — none exist. Only `bounded-source`, `targeted-writer`,
  `sdd-coder` ship.
- ~~`QuerysourceToolkit.allow_ddl`~~ — not a parameter. The gates are
  `allow_write`, `allow_raw_sql`, `allow_external_sources`.
- ~~`DatabaseQueryToolkit(dsn=...)`~~ / ~~`DatabaseQueryToolkit(credentials=...)`~~
  / ~~`DatabaseQueryToolkit(allow_write=...)`~~ — **none are constructor
  parameters.** `__init__` accepts only `output_dir` and `static_dir`
  (toolkit.py:166-167). Credentials are a **per-call tool argument**, and the
  DDL/DML guard is unconditional — there is no switch to make it permissive.
- ~~`ToolkitSection.host`~~ / ~~`.hosts`~~ — no per-host field exists; a
  section is host-agnostic and every enabled section goes to every host the
  operator installs.
- ~~`ToolkitSection` env-var interpolation~~ — `env` values are copied
  verbatim (`google/assets.py:99`); there is no `${VAR}` expansion performed
  by parrot.
- ~~`toolkit_seed.remove_toolkit_section()`~~ / ~~`set_enabled()`~~ — no
  removal or toggle helper exists; seeding is append-only and an existing
  section is never rewritten (toolkit_seed.py:154 docstring).
- ~~a `# parrot:requires_db:` template header~~ — the parser recognises only
  `summary:` and `requires_llm:` (toolkit_seed.py:83-89).
- ~~`parrot claude install --pick`~~ / ~~`--interactive`~~ — the only
  selection flags today are `--toolkits` and `--all-toolkits`.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Three groups are genuinely
  independent once the template format is fixed (it already is): (a) the five
  new template YAML files, (b) the `toolkit_install.py` inventory/mutation
  core plus the `parrot toolkits` Click group, (c) the `--toolkits` removal
  across the three host installers and their tests. But (b) and (c) both
  depend on the `BUILTIN_TOOLKITS` deletion in `toolkit_config.py`, which
  must land first and which every test module in the area reacts to.
- **Cross-feature independence**: low risk but non-zero. FEAT-569
  (`wikitoolkit-http-mcp`, spec v0.2 drafted 2026-09-18) touches wikitoolkit's
  MCP transport and the coding-agent install path — adjacent to, but not
  overlapping, `.parrot/mcp-toolkits.yaml` and the toolkit reconcilers.
  Shared files to watch: `parrot/knowledge/wiki/{claude_code,codex,google}/
  {cli,installer}.py`. FEAT-558 (QuerysourceToolkit) is already merged on
  `dev`, so its toolkit surface is stable to template against.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the feature is one coherent hard cut. `BUILTIN_TOOLKITS`
  removal ripples into the config loader, the seeder, both example YAML
  files, the local CLI's error text and at least four test modules — splitting
  that across worktrees would mean several branches simultaneously red on the
  same shared modules. Sequential tasks in one worktree, ordered
  config-loader → templates → install core → CLI → host-installer cut →
  docs/examples, keeps the tree green at every commit.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus*: `type: feature`,
  `base_branch: dev`.
- [x] Relationship to `parrot claude install --toolkits=` — *Owner: Jesus*:
  **full replacement**. `--toolkits` and `--all-toolkits` are removed from
  all three host `install` commands; `parrot toolkits` is the only selection
  surface.
- [x] Which hosts can `parrot toolkits install` target — *Owner: Jesus*: all
  three — Claude Code (`.mcp.json`), Codex (`.codex/config.toml`), Google
  Antigravity (`mcp_config.json`).
- [x] How the DB toolkits receive connection info — *Owner: Jesus*: an
  `env:`-based posture with **no secrets on disk**. The installer never
  prompts for or writes a DSN.
- [x] Safety posture of the seeded DB templates — *Owner: Jesus*:
  permissive; the operator narrows it. The host's own per-tool permission
  prompt is the human gate.
- [x] Fate of `scraping` / `browsing` / `memory` — *Owner: Jesus*: converted
  to packaged templates; `BUILTIN_TOOLKITS` is deleted and
  `load_toolkits_config` returns only file-declared sections.
- [x] Migration for existing installs — *Owner: Jesus*: hard cut, reinstall
  required. No auto-migration.
- [x] Subcommand set — *Owner: Jesus*: `install` / `uninstall`, `enable` /
  `disable`, `list` / `status`, each with non-interactive flags.
- [x] wikitoolkit's place in `parrot toolkits list` — *Owner: Jesus*:
  completely invisible; it stays owned by `parrot claude install`.

- [ ] **`env:` cannot hold a secret — confirm the intended resolution path.**
  `ToolkitSection.env` values are written *verbatim* into the host config
  (`google/assets.py:99`), and `.mcp.json` is git-tracked in this repo, so a
  DSN placed there would be committed. parrot performs no `${VAR}`
  expansion. The workable path is an **empty `env:`** plus reliance on the
  environment the MCP host passes to the spawned `parrot mcp-local` process —
  which is how `querysource.conf.asyncpg_url` (`_qs.py:63`) already resolves
  its DSN. Is "empty `env:`, inherit the host process environment, document
  the relevant variable names in the template comments" the intended
  reading of the no-secrets-on-disk decision? — *Owner: Jesus*
- [ ] **"Permissive" is not expressible for `DatabaseQueryToolkit`.** It has
  no `allow_write`/`allow_raw_sql` kwargs and its `QueryValidator` DDL/DML
  guard is unconditional (toolkit.py:365-367) — `__init__` accepts only
  `output_dir` and `static_dir`. So the only permissive knob available is
  setting `output_dir` to expose `dq_save_result`. For `querysource`,
  permissive means `allow_write=true` (exposes `qs_save_multiquery`, which is
  in `confirming_tools` and therefore gets an injected `confirm` flag) and
  `allow_raw_sql=true`. Confirm both readings — and note `max_rows` defaults
  to 200 in querysource vs 10000 in databasequery. — *Owner: Jesus*
- [ ] Should `list` and `status` be **one** subcommand or two? The decision
  selected "list / status" as a pair, but the described output (templates ×
  state × per-host entries × drift) is a single table. Proposal: `list` is
  the table and `status` is an alias, or `status` adds per-host config file
  paths and health. — *Owner: Jesus*
- [ ] Core ships a template whose `class:` points at
  `parrot_tools.querysource...`, which core cannot import and does not own.
  Accept the wart for now (Option D is the eventual fix), or place the
  `querysource`/`scraping`/`browsing` templates in `ai-parrot-tools` and
  teach `available_templates()` to scan more than one package? — *Owner: Jesus*
- [ ] Does `parrot toolkits install` with no `--host` default to **all
  detected hosts** (config file present in the repo) or prompt for host
  selection every time? — *Owner: Jesus*
- [ ] After the cut, should `parrot claude|codex|google install` *warn* when
  `.parrot/mcp-toolkits.yaml` is absent or empty (pointing at
  `parrot toolkits install`), so the removal of `--toolkits` is discoverable
  rather than silent? — *Owner: Jesus*
