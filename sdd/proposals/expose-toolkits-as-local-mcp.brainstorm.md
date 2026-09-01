---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Expose Toolkits as Local MCP — per-toolkit stdio servers for Claude Code / Codex

**Date**: 2026-08-31
**Author**: Jesus (with Claude Fable 5)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

FEAT-403 proved the pattern: `wikitoolkit mcp` runs a lean, core-only
`StdioMCPServer` and registers itself in the project's `.mcp.json`, so the
wiki tools appear as **first-class MCP tools** at Claude Code's
tool-selection time — equal standing with Grep/Read, no Bash competition, no
hook nudging. It works: Claude Code and Codex sessions actually use them.

But the machinery is welded to the wiki. Every other toolkit in the
ecosystem — `WebScrapingToolkit`, `WebBrowsingToolkit`,
`WorkingMemoryToolkit`, and the ~80 toolkits in `parrot_tools` — is invisible
to Claude Code unless the user hand-rolls a server. The three named toolkits
are exactly the ones a development/research session wants:

- **WebScrapingToolkit** — structured scraping/crawling with plan caching,
  where Claude Code's own WebFetch is too shallow (JS rendering, sessions).
- **WebBrowsingToolkit** — catalogued, deterministic site automation
  (recorded actions/sequences against real sites, persistent profiles).
- **WorkingMemoryToolkit** — a DataFrame/result scratchpad, letting a Claude
  Code session park large intermediate results outside its context window.

Who is affected: developers using Claude Code/Codex in this repo (and any
repo with ai-parrot installed) who currently cannot reach parrot's tool
surface from their coding agent. Why now: FEAT-403's core server hierarchy
(`MCPServerBase` → `LocalMCPServerBase` → `StdioMCPServer`, plus
`MCPToolAdapter` in core) landed precisely so "any ai-parrot package can
expose `AbstractTool` instances as a local stdio MCP server" — this feature
is the generalization that spec explicitly deferred ("Building a generic
parrot MCP server framework" was a FEAT-403 non-goal).

## Constraints & Requirements

Decided in discovery (Rounds 0–3):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Topology: one MCP server per toolkit.** Separate `.mcp.json` entries
  (e.g. `parrot-scraping`, `parrot-browsing`, `parrot-memory`) — independent
  enable/disable and crash isolation. NOT one aggregated server.
- **Launch: one generic core CLI subcommand**, one binary for all toolkits —
  each `.mcp.json` entry passes a different toolkit name. Naming caveat: the
  user chose `parrot mcp local <name>`, but the `parrot mcp` Click group is
  owned by **ai-parrot-server** (`cli/__init__.py` lazy registry maps
  `"mcp" → "parrot.mcp.cli"`, which exists only in the server package). A
  core-owned spelling is required — see Open Questions; recommended:
  top-level lazy command `parrot mcp-local <name>` (precedent: agentd's
  `mcp-serve`), with the server's `mcp` group optionally attaching it as
  `parrot mcp local` when installed.
- **Config: project config file + CLI args.** `.parrot/mcp-toolkits.yaml`,
  one section per toolkit: dotted class path, constructor kwargs, optional
  `include:`/`exclude:` tool lists, env passthrough. CLI args override.
- **Installer: extend `parrot claude install`** to write/remove one
  `.mcp.json` entry per enabled toolkit (same pattern as the wikitoolkit
  entry, FEAT-403 Module 7).
- **Confirmation: keep the stdio confirm-flag behavior.**
  `MCPToolAdapter.to_mcp_tool_definition()` already injects a required
  `confirm: boolean` for tools with `routing_meta["requires_confirmation"]`
  (e.g. `WebBrowsingToolkit.confirming_tools = {delete_site_action,
  run_site_action, run_site_sequence, execute_web_task}`). Claude Code's own
  permission prompt is the human gate. No new HITL machinery.
- **Tool subsetting: optional per-toolkit `include`/`exclude`** lists in
  config; default = all tools.
- **WorkingMemory scope: per-process ephemeral.** Fresh memory per MCP
  server process (≈ per Claude Code session). No persistence work in v1.
- **LLM-dependent tools: optional via config.** If a toolkit section
  configures an LLM (`provider:model` string), wire it as `llm_client`;
  otherwise auto-exclude the LLM-dependent tools and expose the rest —
  Claude Code itself is usually the intelligence.
- **Lean startup is non-negotiable.** stdout is the JSON-RPC channel. The
  FEAT-403 pattern (deferred imports inside
  `contextlib.redirect_stdout(sys.stderr)`, stderr-only logging) must be
  followed; the command must work with a bare `ai-parrot` install for
  toolkits whose deps are present, and fail with a clear stderr message
  otherwise.
- **No new hard dependencies.** Heavy toolkit deps (selenium/playwright,
  pandas) are imported only when that toolkit is served.
- **Backward compatible.** No change to `wikitoolkit mcp`, no change to the
  server-side `parrot mcp serve`, no change to any toolkit's public API.

---

## Options Explored

### Option A: Core generic local-MCP runner — `parrot mcp-local <toolkit>` + `.parrot/mcp-toolkits.yaml`

A new small core module (e.g. `parrot/mcp/local_cli.py` + a
`parrot/mcp/toolkit_server.py` factory) that:

1. Reads `.parrot/mcp-toolkits.yaml`, finds the named section.
2. Lazy-imports the toolkit's dotted class path (inside a
   stdout→stderr redirect), instantiates it with the section's kwargs.
3. Collects tools via `AbstractToolkit.get_tools()`, applies
   `include`/`exclude`, drops LLM-dependent tools when no LLM is configured.
4. Registers them on a core `StdioMCPServer` and serves.

Built-in aliases (`scraping`, `browsing`, `memory`) map to the three target
toolkits so they work with zero config; any other toolkit is added by
writing a config section with a dotted path — the "open door". The
`parrot claude install` installer iterates enabled sections and writes one
`.mcp.json` entry per toolkit.

✅ **Pros:**
- Exactly generalizes the proven FEAT-403 pattern; reuses `StdioMCPServer`,
  `MCPToolAdapter`, `LocalServerConfig` untouched.
- Zero per-toolkit code: a new toolkit is one YAML section. Nothing to
  maintain per exposure.
- Works with bare `ai-parrot` (+ `ai-parrot-tools` for scraping/browsing);
  never drags in ai-parrot-server/aiohttp/navconfig.
- Per-toolkit processes give crash isolation (a hung browser can't take
  down working memory) and per-entry enable/disable in `.mcp.json`.
- `AbstractToolkit` auto-discovery + lifecycle (`auto_open`/`_ensure_open`,
  FEAT-391) come for free through `tool.execute()`.

❌ **Cons:**
- New config file format to document and validate (schema, error messages).
- Dotted-path instantiation is arbitrary code execution by config — needs a
  clear "project config is trusted" stance (same trust level as `.mcp.json`
  itself, which already executes arbitrary commands).
- Constructor kwargs are YAML-typed only; complex kwargs (e.g. an
  `llm_client` object) need special-cased handling (the `provider:model`
  string convention).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `PyYAML` | parse `.parrot/mcp-toolkits.yaml` | already a core dep (used across repo) |
| `click` | CLI subcommand | already a core dep (`parrot.cli` LazyGroup) |
| — | no new dependencies | heavy toolkit deps stay lazy |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/mcp/local_server.py` — `StdioMCPServer` (serve loop, JSON-RPC dispatch)
- `packages/ai-parrot/src/parrot/mcp/server_base.py` — `MCPServerBase.register_tools()`, `LocalServerConfig`
- `packages/ai-parrot/src/parrot/mcp/adapter.py` — `MCPToolAdapter` (schema + confirm-flag + result conversion)
- `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` — the deferred-import / stdout-redirect / `main()` pattern to copy
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` — `_install_mcp_json()` / `_uninstall_mcp_json()` merge logic to generalize
- `packages/ai-parrot/src/parrot/cli/__init__.py` — `LazyGroup` registry to add the new command
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — `AbstractToolkit.get_tools()` (line 484), `confirming_tools` wiring

---

### Option B: Extend the existing server-side `parrot mcp serve`

`parrot mcp serve <config>` already exists in **ai-parrot-server**
(`packages/ai-parrot-server/src/parrot/mcp/cli.py:51`): it loads a YAML/
Python config, instantiates toolkits via `ParrotMCPServer.
_load_configured_tools()`, and can serve stdio. Extend it with a
toolkit-name mode, constructor kwargs in YAML (today it only supports
`{class, module}` pairs), and include/exclude.

✅ **Pros:**
- The command and YAML loader already exist; smallest diff on paper.
- One CLI surface for local and remote serving.

❌ **Cons:**
- Requires `ai-parrot-server` (aiohttp, navconfig, oauth machinery) in every
  Claude Code session just to run a local scraper — the exact coupling
  FEAT-403 was cut to remove.
- `from navconfig.logging import logging` and friends are the known
  stdout-pollution import chain; stdio safety would need re-hardening there.
- `ParrotMCPServer` is built for multi-transport server deployment; local
  stdio is a degenerate case bolted on (`_run_standalone_server`).
- Existing `serve` signature takes a config *file path* argument — adding a
  name-based mode overloads its contract for current users.

📊 **Effort:** Medium (code) but High (risk of destabilizing server CLI)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot-server` | hosts the CLI | becomes a hard requirement for local exposure — undesirable |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/mcp/cli.py` — `mcp serve`, `_load_from_yaml()`
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py` — `_load_configured_tools()` (line 280)

---

### Option C: Per-toolkit console scripts (the literal wikitoolkit pattern)

Each exposed toolkit ships its own `[project.scripts]` entry point
(`parrot-scraping-mcp`, `parrot-browsing-mcp`, `parrot-memory-mcp`), each a
thin `main()` that builds a `StdioMCPServer` with that toolkit — a
copy of `wiki/mcp_server.py` per toolkit.

✅ **Pros:**
- Dead simple mental model; `.mcp.json` entries are self-describing binaries.
- Per-toolkit tailoring is trivial (custom flags per script).

❌ **Cons:**
- N scripts to write, test, and maintain; the "door" for new toolkits is
  *writing code and a packaging entry point*, not editing config — fails the
  stated extensibility goal.
- Scripts for `parrot_tools` toolkits would have to live in
  `ai-parrot-tools`'s pyproject, splitting the machinery across packages.
- Console-script proliferation in the venv.

📊 **Effort:** Low per toolkit, but scales linearly and poorly.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none new | |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` — template to copy N times

---

### Option D (unconventional): Registry-driven auto-exposure via entry points

Toolkits self-declare MCP exposability through a Python entry-point group
(e.g. `parrot.mcp_toolkits`), the way pytest plugins register. `parrot
mcp-local --list` enumerates installed exposable toolkits;
`parrot claude install` offers them all. No config file — discovery is
packaging metadata; kwargs come from env vars following a naming convention
(`PARROT_MCP_SCRAPING_HEADLESS=1`).

✅ **Pros:**
- Zero-config discovery across all installed distributions (satellites and
  third-party plugins included).
- The "door" is open to *external* packages, not just this repo.

❌ **Cons:**
- Constructor kwargs via env-var conventions are stringly-typed and awkward
  for nested settings (include/exclude lists, LLM config).
- Entry-point changes require re-releasing the package that owns the
  toolkit; a config file iterates instantly.
- Harder to see at a glance what a project exposes (metadata scattered
  across installed dists vs one file in the repo).

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | entry-point discovery | stdlib |

🔗 **Existing Code to Reuse:**
- Same server/adapter core as Option A.

---

## Recommendation

**Option A** is recommended.

The deciding factor is where the *extensibility door* actually is. The
user's goal is "easily sharing other toolkits as internal MCP tools" — in
Option A that is one YAML section (dotted path + kwargs), editable per
project, no code, no release. Option C makes the door a code-and-packaging
exercise per toolkit; Option D makes it a release cycle and pushes kwargs
into env-var conventions that can't express `include:` lists cleanly.

Option B is rejected on dependency direction: local exposure to Claude Code
must not require `ai-parrot-server`. FEAT-403 extracted
`StdioMCPServer`/`MCPToolAdapter` to core precisely to break that coupling,
and its known stdout-pollution import chain is a live hazard for stdio
transport. Building on the core hierarchy keeps `wikitoolkit mcp` and this
feature on one code path.

What we trade off, honestly:

- **A new config format to own.** Schema validation and good error messages
  are real work; mitigated by keeping v1 minimal (name → dotted path,
  kwargs, include/exclude, llm).
- **Config-driven instantiation executes code named by config.** Same trust
  boundary as `.mcp.json` itself (which names arbitrary commands), so this
  adds no new class of exposure — but the doc must say so explicitly.
- **Per-toolkit processes** mean N Python interpreters when N toolkits are
  enabled. Accepted by design (crash isolation was chosen over aggregation);
  toolkits are lazy-imported so each process stays as small as its toolkit
  allows.
- Option D's cross-package discovery remains attractive **later**: nothing
  in Option A precludes adding an entry-point *fallback* for toolkit-name
  resolution in a follow-up feature.

---

## Feature Description

### User-Facing Behavior

A developer enables parrot toolkits for Claude Code in two steps:

1. (Optional) Create/edit `.parrot/mcp-toolkits.yaml`:

```yaml
# .parrot/mcp-toolkits.yaml
toolkits:
  scraping:
    class: parrot_tools.scraping.toolkit.WebScrapingToolkit
    enabled: true
    kwargs:
      headless: true
      plans_dir: .parrot/scraping_plans
    exclude: [plan_infer]        # optional
    llm: null                    # no LLM → LLM-dependent tools auto-excluded
  browsing:
    class: parrot_tools.browsing.toolkit.WebBrowsingToolkit
    enabled: true
    kwargs:
      catalog_dir: .parrot/browsing_catalog
      headless: true
  memory:
    class: parrot.tools.working_memory.WorkingMemoryToolkit
    enabled: true
```

The three built-in names (`scraping`, `browsing`, `memory`) work with **no
config file at all** — sensible defaults are baked in; the file only
overrides or adds.

2. Run `parrot claude install` (already the standard step). It now writes
one `.mcp.json` entry per enabled toolkit alongside the existing
wikitoolkit entry:

```json
{
  "mcpServers": {
    "wikitoolkit":     {"command": ".../.venv/bin/wikitoolkit", "args": ["mcp"]},
    "parrot-scraping": {"command": ".../.venv/bin/parrot", "args": ["mcp-local", "scraping"], "env": {}},
    "parrot-browsing": {"command": ".../.venv/bin/parrot", "args": ["mcp-local", "browsing"], "env": {}},
    "parrot-memory":   {"command": ".../.venv/bin/parrot", "args": ["mcp-local", "memory"], "env": {}}
  }
}
```

On the next Claude Code session, tools appear natively:
`mcp__parrot-scraping__scrape`, `mcp__parrot-browsing__run_site_action`,
`mcp__parrot-memory__store`, … Destructive browsing tools carry the
adapter's required `confirm: boolean` parameter, and Claude Code's own
permission prompt gates each call. `parrot claude uninstall` removes
exactly the entries it wrote. Codex gets the same servers through its own
MCP registration (`parrot codex install` counterpart, if in scope — see
Open Questions).

`parrot mcp-local --list` prints the resolvable toolkit names (built-ins +
config sections) and whether their imports resolve, for troubleshooting.

### Internal Behavior

1. **Resolution.** `parrot mcp-local <name>` loads the config file if
   present, merges over built-in defaults for the three known names, and
   resolves `class` as a dotted path via `importlib` — inside a
   `contextlib.redirect_stdout(sys.stderr)` block, mirroring
   `wiki/mcp_server.py`, so import-time prints can't corrupt JSON-RPC.
2. **Instantiation.** The toolkit is constructed with the section's
   `kwargs`. If `llm:` is set (a `provider:model` string), a client is
   created through the existing client factory and passed as `llm_client`;
   if unset, tools known to require the LLM are dropped from exposure.
3. **Tool collection.** `toolkit.get_tools()` yields the auto-discovered
   `AbstractTool`s (public async methods); `include`/`exclude` filters by
   tool name; `confirming_tools` metadata flows through untouched.
4. **Serving.** Tools are registered on a `StdioMCPServer` with a
   `LocalServerConfig(name=f"parrot-{name}")`; `asyncio.run(server.start())`
   with stderr-only logging. `MCPToolAdapter` handles schema generation
   (from `args_schema`), the confirm-flag injection, execution through
   `tool.execute()` (which honors FEAT-391 `auto_open` lifecycle), and
   `ToolResult` → MCP content conversion.
5. **Shutdown.** EOF on stdin ends the serve loop; the toolkit's `_close()`
   runs via the lifecycle hooks so browser drivers/sessions are released.
   WorkingMemory state dies with the process (ephemeral by decision).
6. **Installer.** `_install_mcp_json()` is generalized from "the wikitoolkit
   entry" to "a set of managed entries": it computes the enabled-toolkit
   entry list and reconciles `.mcp.json` (add/update/remove managed entries,
   never touching foreign ones).

### Edge Cases & Error Handling

- **Unknown toolkit name** → exit non-zero with a stderr message listing
  resolvable names (built-ins + config sections).
- **Import fails** (toolkit extra not installed, e.g. selenium missing) →
  clear stderr message naming the missing dependency and the pip extra;
  non-zero exit. Claude Code shows the server as failed rather than
  hanging.
- **Bad kwargs** (constructor `TypeError`) → stderr message naming the
  offending section and key; non-zero exit.
- **Config file malformed** → named YAML error with path; built-ins remain
  usable without the file.
- **Tool raises during a call** → `MCPToolAdapter.execute()` already maps
  failures to MCP error content; the server keeps serving.
- **Confirming tool called without `confirm: true`** → adapter rejects with
  instructive error (existing behavior), the model retries with the flag
  after the human approves via Claude Code's prompt.
- **Blocking tool work** (selenium is sync under the hood) → runs through
  the toolkit's existing executor/thread offload patterns; the per-toolkit
  process means a stuck browser blocks only its own server, not the others
  (topology decision pays off here).
- **`include` and `exclude` both present** → `include` wins (whitelist
  semantics), documented in the config reference.
- **Name collision with a foreign `.mcp.json` entry** → installer refuses to
  overwrite an entry it does not manage; warns and skips.
- **stdout pollution from toolkit imports** → all imports happen inside the
  redirect block; the serve loop is the only stdout writer.

---

## Capabilities

### New Capabilities
- `toolkit-local-mcp-runner`: generic core CLI (`parrot mcp-local <name>`)
  that serves any configured `AbstractToolkit` as a per-toolkit local stdio
  MCP server, with built-in defaults for `scraping`, `browsing`, `memory`.
- `mcp-toolkits-config`: `.parrot/mcp-toolkits.yaml` project config —
  dotted class path, kwargs, include/exclude, optional LLM wiring, enabled
  flag.
- `claude-install-toolkit-entries`: `parrot claude install`/`uninstall`
  manage per-toolkit `.mcp.json` entries reconciled from the config.

### Modified Capabilities
- `mcp-local-server-wikitoolkit` (`sdd/specs/mcp-local-server-wikitoolkit.spec.md`,
  FEAT-403) — the installer's `.mcp.json` handling generalizes from a single
  wikitoolkit entry to a managed-entry set (wikitoolkit entry unchanged in
  content).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/mcp/local_server.py`, `server_base.py`, `adapter.py` (core) | depends on | consumed as-is; no changes expected |
| `parrot/mcp/` (core) | extends | new `toolkit_server.py` (factory + config loading) and `local_cli.py` (click command) — names must NOT collide with server-package modules (`cli.py`, `server.py`, `config.py`, `wrapper.py` exist there) |
| `parrot/cli/__init__.py` | modifies | add `"mcp-local": "parrot.mcp.local_cli"` to `cli._lazy_commands` |
| `parrot/knowledge/wiki/claude_code/installer.py` | modifies | `_install_mcp_json`/`_uninstall_mcp_json` generalized to managed-entry reconciliation |
| `parrot/knowledge/wiki/claude_code/assets.py` | extends | entry builders for `parrot mcp-local <name>` servers |
| `parrot_tools.scraping.toolkit.WebScrapingToolkit` | depends on | instantiated by config; no changes |
| `parrot_tools.browsing.toolkit.WebBrowsingToolkit` | depends on | instantiated by config; `confirming_tools` flows into confirm-flag |
| `parrot/tools/working_memory/tool.py` `WorkingMemoryToolkit` | depends on | ephemeral per process; no changes |
| `packages/ai-parrot-server/src/parrot/mcp/cli.py` | none | untouched; `parrot mcp serve` keeps its contract |
| `.mcp.json` (this repo) | extends | gains parrot-scraping / parrot-browsing / parrot-memory entries when enabled |
| `docs/` | extends | config reference + "expose your toolkit to Claude Code" guide |
| `pyproject.toml` (core) | none | no new dependencies, no new console scripts |

No breaking changes. New config file is additive; absence of it preserves
today's behavior plus three built-in names that only activate when invoked.

---

## Code Context

### User-Provided Code

None — the user provided the feature intent in prose only.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/mcp/server_base.py
class LocalServerConfig:  # line 48 (dataclass: name, version, description, log_level)
class MCPServerBase(ABC):  # line 57
    def register_tool(self, tool: AbstractTool):  # line 68
    def register_tools(self, tools: list[AbstractTool]):  # line 75
    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:  # line 80
    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:  # line 100
    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:  # line 111

# From packages/ai-parrot/src/parrot/mcp/local_server.py
class LocalMCPServerBase(MCPServerBase):  # line 18 — stderr logging, no stdout handler
class StdioMCPServer(LocalMCPServerBase):  # line 36
    def __init__(self, config: LocalServerConfig):  # line 39
    async def start(self):  # line 44 — blocking stdin readline via run_in_executor
    async def stop(self):  # line 80
    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:  # line 84

# From packages/ai-parrot/src/parrot/mcp/adapter.py  (CORE adapter, FEAT-403)
class MCPToolAdapter:  # line 8
    def __init__(self, tool: AbstractTool):  # line 19
    def _requires_confirmation(self) -> bool:  # line 23 — reads routing_meta["requires_confirmation"]
    def to_mcp_tool_definition(self) -> dict[str, Any]:  # line 27 — injects required `confirm: boolean` for confirming tools
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:  # line 59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]:  # line 108

# From packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py  (pattern to copy)
def create_wiki_mcp_server(root: Path) -> StdioMCPServer:  # line 90
#   line 105: with contextlib.redirect_stdout(sys.stderr):  ← deferred-import guard
def main() -> None:  # line 192 — the `wikitoolkit mcp` entry

# From packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):  # line ~19 — lazy subcommand registry
cli._lazy_commands = { "mcp": "parrot.mcp.cli",  # SERVER package module
                       "claude": "parrot.knowledge.wiki.claude_code.cli",
                       "mcp-serve": "parrot.integrations.agentd.cli", ... }  # line 109

# From packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _install_mcp_json(root: Path) -> str:  # line 258 — wikitoolkit entry merge into .mcp.json
def _uninstall_mcp_json(root: Path) -> str | None:  # line 293
def install_claude_integration(...):  # line 454 — calls _install_mcp_json at line 492

# From packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
def mcp_json_entry(root: Path) -> dict:  # line 95 — {"command": <abs bin>, "args": ["mcp"], "env": {}}

# From packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):  # line 274
    def __init__(self, driver_type: Literal["selenium","playwright"]="selenium",
                 browser=..., headless: bool = True, session_based: bool = False,
                 ..., plans_dir=None, llm_client=None, **kwargs):  # line 300
# 9 public async tool methods (auto-discovered by AbstractToolkit)

# From packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
class WebBrowsingToolkit(WebScrapingToolkit):  # line 64
    confirming_tools: frozenset = frozenset({"delete_site_action",
        "run_site_action", "run_site_sequence", "execute_web_task"})  # line 115
    def __init__(self, catalog_dir="browsing_catalog", user_data_dir=None,
                 profile_directory=None, browser_channel=None,
                 max_loop_iterations=..., credential_resolver=None,
                 human_channel=None, session_based=True, headless=False,
                 confirm_runs=True, **kwargs):  # line 124
# 10 public async tool methods on top of inherited scraping tools

# From packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):  # line 44
    def __init__(self, session_id=None, max_rows=10, max_cols=30,
                 tool_locals_registry=None, answer_memory=None,
                 thread_offload_cells=None, **kwargs):  # line 103
# tool methods incl.: store(194), store_result(208), drop_stored(242),
# get_stored(248), get_result(259), search_stored(291), list_stored(362),
# compute_and_store(384), merge_stored(448), summarize_stored(489),
# import_from_tool(545), list_tool_dataframes(650), save_interaction(670),
# recall_interaction(687)

# From packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    def get_tools(self, ...):  # line 484 — auto-discovers public async methods as tools

# From packages/ai-parrot-server/src/parrot/mcp/cli.py  (existing, DO NOT break)
@click.group(...) def mcp(ctx, config):  # line 16-19 — owns `parrot mcp`
@mcp.command() def serve(config_file, transport, socket, port, log_level):  # line 37-53
# YAML tools format is {class: module} pairs, NO constructor kwargs (line 122-126)

# From packages/ai-parrot-server/src/parrot/mcp/parrot_server.py
async def _load_configured_tools(self) -> List[AbstractTool]:  # line 280
```

#### Verified Imports

```python
# Confirmed to resolve (2026-08-31, this venv):
from parrot.mcp.local_server import StdioMCPServer          # local_server.py:36
from parrot.mcp.server_base import LocalServerConfig, MCPServerBase  # server_base.py:48,57
from parrot.mcp.adapter import MCPToolAdapter               # adapter.py:8 (core)
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot_tools.scraping.toolkit import WebScrapingToolkit    # scraping/toolkit.py:274
from parrot_tools.browsing.toolkit import WebBrowsingToolkit    # browsing/toolkit.py:64
from parrot.tools.working_memory.tool import WorkingMemoryToolkit  # tool.py:44
```

#### Key Attributes & Constants

- `cli._lazy_commands["mcp"]` → `"parrot.mcp.cli"` — **the `parrot mcp`
  group lives in ai-parrot-server** (parrot/cli/__init__.py:109-128)
- `[project.scripts] parrot = "parrot.cli:cli"` (packages/ai-parrot/pyproject.toml:163)
- `wikitoolkit = "parrot.knowledge.wiki.cli:main"` (pyproject.toml:167)
- `.mcp.json` lives at project root, NOT `.claude/` (installer.py:261)
- `AbstractTool.routing_meta["requires_confirmation"]` — set by toolkit from
  `confirming_tools` (parrot/tools/toolkit.py:~681)
- `parrot.tools.<x>` → `parrot_tools.<x>` redirect via `_ParrotToolsRedirector`
  meta_path finder (parrot/tools/__init__.py:44,135) — dotted paths in config
  should prefer explicit `parrot_tools.*`
- `parrot.mcp` is a PEP 420-merged namespace across core and server: core has
  `local_server.py`/`server_base.py`/`adapter.py`; server has `cli.py`/
  `server.py`/`config.py`/`wrapper.py`/`parrot_server.py`/`simple_server.py`/
  `chrome.py`/`oauth_server.py`/`transports/`

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/mcp/cli.py` in **core**~~ — the module exists only in
  ai-parrot-server; core adding a same-named file would collide in the
  merged namespace. New core CLI module must use a different filename
  (e.g. `local_cli.py`).
- ~~`parrot mcp local` subcommand~~ — does not exist; and it cannot be added
  to the `mcp` group from core (group owned by server package).
- ~~`.parrot/mcp-toolkits.yaml`~~ — does not exist yet; this feature creates
  the format and loader.
- ~~kwargs support in server YAML `tools:` format~~ — `_load_from_yaml`
  supports only `{class: module}` pairs (server cli.py:122-126).
- ~~`create_toolkit_mcp_server()` / `parrot/mcp/toolkit_server.py`~~ — to be
  created by this feature.
- ~~generic managed-entry reconciliation in `_install_mcp_json`~~ — current
  code handles exactly one hardcoded `wikitoolkit` entry.
- ~~`WorkingMemoryToolkit` persistence to disk~~ — memory is in-process;
  the per-process-ephemeral decision requires no new persistence code.
- ~~`WebScrapingToolkit`/`WebBrowsingToolkit` in core~~ — they ship in
  `ai-parrot-tools` (`parrot_tools.*`); a bare core install cannot serve
  them (import error path must handle this).

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The runner/factory + config loader
  (core `parrot/mcp/`) is the trunk; the installer generalization and the
  docs/config-reference are separable but both depend on the entry format
  the trunk defines. Per-toolkit smoke tests are independent leaves.
- **Cross-feature independence**: Touches
  `parrot/knowledge/wiki/claude_code/installer.py` and `assets.py` — shared
  with any in-flight wiki/claude-integration work; no such feature is
  currently active. No overlap with dev-flow/devloop features.
- **Recommended isolation**: per-spec (sequential tasks, one worktree).
- **Rationale**: The task chain is short (config loader → runner CLI →
  installer → docs/tests) with real data-format dependencies between steps;
  parallel worktrees would conflict on `parrot/mcp/__init__.py` and the
  installer.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: feature → dev.
- [x] Topology — *Owner: Jesus*: one MCP server per toolkit (separate
  `.mcp.json` entries), not aggregated.
- [x] Config source — *Owner: Jesus*: project config file
  (`.parrot/mcp-toolkits.yaml`) + CLI args; env for secrets via `.mcp.json`
  `env` blocks.
- [x] WorkingMemory semantics over MCP — *Owner: Jesus*: per-process
  ephemeral (per Claude Code session); no persistence in v1.
- [x] Launch mechanism — *Owner: Jesus*: one generic core CLI subcommand,
  toolkit name as argument (not per-toolkit console scripts).
- [x] Installer — *Owner: Jesus*: extend `parrot claude install`/`uninstall`
  to manage per-toolkit entries.
- [x] Confirmation over stdio — *Owner: Jesus*: keep `MCPToolAdapter`'s
  confirm-flag behavior; Claude Code's permission prompt is the human gate.
- [x] Tool subsetting — *Owner: Jesus*: optional per-toolkit
  `include`/`exclude` lists; default all.
- [x] Command home — *Owner: Jesus*: core package (not ai-parrot-server's
  `parrot mcp serve`), FEAT-403 lean-startup pattern.
- [x] LLM-dependent tools — *Owner: Jesus*: optional `llm:` per section;
  when unset, LLM-dependent tools are auto-excluded.
- [ ] Exact command spelling: `parrot mcp local <name>` was chosen, but the
  `mcp` group is owned by ai-parrot-server. Recommended resolution: core
  top-level lazy command `parrot mcp-local <name>` (precedent: `mcp-serve`),
  optionally attached as `parrot mcp local` by the server package when
  installed. — *Owner: Jesus (confirm at /sdd-spec)*
- [ ] Codex parity: should `parrot codex install`
  (`parrot.knowledge.wiki.codex.cli`) get the same per-toolkit entries in
  this feature, or as a follow-up? — *Owner: Jesus*
- [ ] How are "LLM-dependent tools" identified for auto-exclusion — a static
  per-toolkit list in the built-in defaults, or a toolkit-level metadata
  attribute (e.g. `llm_dependent_tools: frozenset`)? — *Owner: spec author*
- [ ] Should `parrot mcp-local --list` also probe imports (slow but
  diagnostic) or just list names? — *Owner: implementer*
