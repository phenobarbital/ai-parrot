# Expose Toolkits as Local MCP (`parrot mcp-local`)

> **Feature**: FEAT-485 — Expose Toolkits as Local MCP
> **Spec**: [sdd/specs/expose-toolkits-as-local-mcp.spec.md](../sdd/specs/expose-toolkits-as-local-mcp.spec.md)
> **Package**: `ai-parrot` (core) — `parrot.mcp.local_cli`, `parrot.mcp.toolkit_server`, `parrot.mcp.toolkit_config`

`parrot mcp-local <name>` serves any `AbstractToolkit` subclass — a
toolkit you've installed with `parrot toolkits install` (`scraping`,
`browsing`, `memory`) or a toolkit of your own — as a **per-toolkit local
stdio MCP server**. Each name becomes its own process, its own tool
namespace, and its own `.mcp.json` / `.codex/config.toml` server entry, so
an MCP host (Claude Code, Codex) sees the toolkit's tools as first-class,
equal-standing tools at tool-selection time — no Bash competition, no hook
nudging. This is the same pattern FEAT-403 proved for `wikitoolkit mcp`,
generalized to any toolkit.

> **Hard cut (FEAT-570)**: `scraping`, `browsing` and `memory` are no
> longer resolvable "for free" — a name resolves **only** if
> `.parrot/mcp-toolkits.yaml` declares a section for it. There is no
> auto-migration. If your `parrot mcp-local <name>` used to work and now
> exits with `Unknown toolkit name`, re-run
> `parrot toolkits install <name>` (see below) — that is the single
> migration aid this feature ships.

---

## Quickstart

```bash
# Install one or more toolkits: seeds .parrot/mcp-toolkits.yaml AND
# registers the managed server entries with every detected MCP host
# (Claude Code's .mcp.json, Codex's .codex/config.toml, Google Antigravity):
parrot toolkits install scraping browsing memory --yes

# See what's resolvable — declared sections only — with enabled state and
# per-host status; fast, does not import any toolkit class:
parrot mcp-local --list
parrot toolkits list

# Serve a toolkit directly (mostly for manual testing — an MCP host
# normally spawns this for you via the installed .mcp.json entry):
parrot mcp-local memory
```

`parrot toolkits install|uninstall|enable|disable [NAMES...] [--host
claude|codex|google] [--yes]` is the primary entry point (FEAT-570):

- **`parrot toolkits list`** — a table of every packaged toolkit template
  with its state (`not_installed`/`enabled`/`disabled`), which hosts have a
  managed entry for it, missing dependencies, and any drift from the
  packaged template.
- **`parrot toolkits status`** — each host's resolved config paths, scope
  (repo vs. user-global) and presence.
- **`parrot toolkits install NAMES...`** — seeds `NAMES` into
  `.parrot/mcp-toolkits.yaml` (if not already declared) and registers a
  managed server entry with every targeted host. Run with no `NAMES` from
  an interactive terminal to get a checkbox picker instead.
- **`parrot toolkits uninstall NAMES...`** — removes `NAMES`' sections and
  deregisters their host entries. **Config only** — a toolkit's own data
  (scraping plans, DB results) is never deleted.
- **`parrot toolkits enable / disable NAMES...`** — flips `enabled:` and
  reconciles the host entries, keeping the section (and its `kwargs`)
  around either way.
- **`--host`** (repeatable) targets specific hosts; default is every host
  whose config already exists. **`--yes`** skips the confirmation prompt
  (required for non-interactive/CI use, alongside explicit `NAMES`).

Re-running `install`/`uninstall`/`enable`/`disable` reconciles: sections
you disable or delete disappear from the managed entries; foreign entries
(anything the installer did not write) are never touched.

---

## Credential posture

The packaged templates (`scraping`, `browsing`, `memory`, …) ship with
`env: {}` — the installer never writes a secret into `.mcp.json` /
`.codex/config.toml`. Any credential a toolkit needs (an API key, a DSN)
is inherited from the **environment the MCP host passes to
`parrot mcp-local`** at spawn time, exactly like any other environment
variable the host process sees — not from anything `parrot toolkits`
generates or stores. If a toolkit of your own needs a secret, add it to
its section's `env:` map as an `"${VAR}"` reference (see
`examples/mcp-toolkits.yaml`), never as a literal value.

---

## Configuration: `.parrot/mcp-toolkits.yaml`

Read relative to the **project root** — the directory the MCP host starts
`parrot mcp-local <name>` in (normally your repo root). A toolkit resolves
**only** if this file declares a section for it (FEAT-570) — nothing is
implicit, and there is no built-in default set. An absent file resolves to
an empty config (`parrot mcp-local --list` prints "No toolkits
resolvable.").

See [`examples/mcp-toolkits.yaml`](../examples/mcp-toolkits.yaml) for a
fully annotated copy-paste starting point.

### Schema

```yaml
toolkits:
  <name>:
    class: <dotted.path.to.AbstractToolkitSubclass>   # required (YAML key: "class")
    enabled: true                                     # default: true
    kwargs: {}                                        # constructor kwargs
    include: null                                      # optional whitelist of tool names
    exclude: null                                      # optional blacklist of tool names
    llm: null                                          # optional "provider:model" string
    llm_kwargs: {}                                     # optional extra kwargs for LLMFactory.create (requires llm)
    env: {}                                            # env vars written into installer entries
```

| Field | Type | Meaning |
|---|---|---|
| `class` | `str` (required) | Dotted path to an `AbstractToolkit` subclass, e.g. `parrot_tools.scraping.toolkit.WebScrapingToolkit`. Resolved via `importlib` — see the trust note below. |
| `enabled` | `bool` (default `true`) | Whether `parrot toolkits install/enable/disable` include this section in their managed host entries and whether `--list` shows it as `enabled`/`disabled`. **Does not** block a direct `parrot mcp-local <name>` invocation — a disabled section can still be served manually. |
| `kwargs` | `dict` | Keyword arguments passed to the toolkit's constructor. |
| `include` | `list[str] \| null` | Whitelist of tool names to expose. When set, only these are exposed. |
| `exclude` | `list[str] \| null` | Blacklist of tool names to exclude. Only consulted when `include` is unset. |
| `llm` | `str \| null` | A `"provider:model"` string (e.g. `"openai:gpt-4o-mini"`, `"anthropic:claude-3-5-haiku-latest"`). When set, `LLMFactory.create()` builds a client passed to the toolkit's constructor as `llm_client`. |
| `llm_kwargs` | `dict` | Extra keyword arguments forwarded verbatim to `LLMFactory.create(llm, **llm_kwargs)`, so they reach the client constructor unchanged — e.g. `fallback_model: null`, `max_retries`, `read_timeout`. This is **trusted server configuration**, never an LLM-callable argument. Requires `llm` to be set, and may not contain an `llm` key (it would collide with the factory's first argument). See `examples/tool-optimizations-mcp.yaml`, where `fallback_model: null` is required so the Bedrock client cannot silently answer with its default fallback model. |
| `env` | `dict[str, str]` | Environment variables written into the generated `.mcp.json` / `.codex/config.toml` server entry (e.g. API keys the toolkit reads from its process env at runtime). **Not** passed as constructor kwargs. |

### The include/exclude/llm-dependent rules

- **`include` wins over `exclude`.** If both are set on a section, `exclude`
  is ignored entirely — only the named tools in `include` are exposed.
- **LLM-dependent tools are dropped automatically when no `llm:` is
  configured.** A toolkit MAY declare `llm_dependent_tools: frozenset[str]`
  (an `AbstractToolkit` class attribute, mirroring `confirming_tools`)
  naming its tools that call an LLM internally. With no `llm:` string in
  the section, those tool names are excluded from exposure — with `llm:`
  set, they are included and the toolkit receives a real `llm_client`.
- **`confirming_tools` behavior is unchanged.** A tool named in the
  toolkit's `confirming_tools` still gets the `MCPToolAdapter`'s required
  `confirm: boolean` schema property over stdio, exactly as it does for
  `wikitoolkit mcp` today. This is model-settable — the real human gate is
  the MCP host's own permission prompt, not anything `parrot`-side.

### Packaged toolkit templates

`parrot toolkits install <name>` seeds one of these packaged templates into
`.parrot/mcp-toolkits.yaml` — none of them resolve until you do:

| Name | Class | Notes |
|---|---|---|
| `scraping` | `parrot_tools.scraping.toolkit.WebScrapingToolkit` | Requires `ai-parrot-tools[scraping]` (or `[browsing]` for shared browser drivers). Structured scraping/crawling with plan caching. |
| `browsing` | `parrot_tools.browsing.toolkit.WebBrowsingToolkit` | Requires `ai-parrot-tools[browsing]`. Catalogued, deterministic site automation. |
| `memory` | `parrot.tools.working_memory.tool.WorkingMemoryToolkit` | Ships with bare `ai-parrot` — no extra install. Ephemeral, **per-process** DataFrame/result scratchpad; state never persists across restarts and is never shared between two server processes. |

`parrot toolkits list` shows every packaged template (this table plus any
others shipped since), each one's state, and whether its distribution is
importable.

---

## Exposing your own toolkit

1. Write (or reuse) an `AbstractToolkit` subclass anywhere importable from
   your project's environment — it does not need to live inside
   `ai-parrot`/`ai-parrot-tools`.
2. Add a section to `.parrot/mcp-toolkits.yaml`:
   ```yaml
   toolkits:
     my-toolkit:
       class: my_package.my_module.MyToolkit
       kwargs:
         some_option: value
   ```
3. Confirm it resolves: `parrot mcp-local --list` should list `my-toolkit`
   with `enabled` state and its class path (this does **not** import the
   class — it is a fast, side-effect-free check).
4. Serve it manually to sanity check: `parrot mcp-local my-toolkit`, then
   send a JSON-RPC `initialize` / `tools/list` on stdin.
5. Wire it into your MCP host(s): `parrot toolkits install my-toolkit`
   (or `--host claude` / `--host codex` / `--host google` to target one).
   Re-run after editing the config to reconcile the managed entries
   (add/update/remove) — installs are idempotent.

### ⚠️ Trust note

**Config-driven instantiation is arbitrary code execution.** `class:`
names a dotted path that `importlib` resolves and instantiates with your
`kwargs` — exactly the same trust boundary as `.mcp.json` /
`.codex/config.toml` themselves already carry (both let you name an
arbitrary command to execute). Only add a `class:` entry for code you
trust, exactly as you would only add a `command:` you trust to
`.mcp.json`. This is a deliberate design decision (see the spec's Known
Risks), not mitigated further in v1.

---

## Troubleshooting

**`parrot mcp-local --list` doesn't show my toolkit.**
Check that `.parrot/mcp-toolkits.yaml` is at the project root (the
directory you run the command from, or the directory the MCP host starts
the process in — NOT necessarily your shell's cwd if the host uses a
different working directory) and that the YAML is valid (`toolkits:` must
be a mapping; each section needs at least `class`).

**`parrot mcp-local <name>` exits immediately with a `ValueError: Unknown
toolkit name`.**
The name isn't a key under `toolkits:` in your config — no name resolves
implicitly (FEAT-570 hard cut). stderr also prints
`No toolkit named '<name>' is configured. Install it with: parrot toolkits
install <name>` — run that command (or add the section by hand) and
re-run. The error also lists every resolvable name — compare against
`parrot mcp-local --list` / `parrot toolkits list`.

**`ImportError: Cannot import toolkit '<dotted.path>' for '<name>'`.**
The `class:` path doesn't resolve in this Python environment. For
`scraping`/`browsing` this usually means the `ai-parrot-tools` extra isn't
installed (`uv pip install "ai-parrot-tools[scraping]"` or
`[browsing]`) — the error message includes this hint. For a custom
toolkit, confirm the module is importable from wherever the MCP host
launches `parrot` (same venv, same `PYTHONPATH`).

**The MCP host reports a broken/garbled tool response, or hangs on
startup.**
stdout is reserved exclusively for the JSON-RPC channel — anything else
written to stdout (an errant `print()`, a library's import-time banner)
corrupts the stream from the host's point of view. All resolution/import
work in `create_toolkit_mcp_server()` runs inside a
`contextlib.redirect_stdout(sys.stderr)` block specifically to prevent
this; if you still see corruption with a custom toolkit, check whether
importing it (or any of its transitive dependencies) prints directly to
`stdout` rather than logging through `self.logger`.

**Every call times out after 30 minutes, even read-only ones.**
That is Claude Code's stdio idle timeout (`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`,
default 1,800,000 ms) firing on calls queued behind one stuck handler.
`StdioMCPServer` runs each `tools/call` as its own asyncio task and honours
the host's `notifications/cancelled`, so a stuck call no longer blocks the
others and is cancelled once the host gives up on it. If a toolkit still
pins the server, look for an unbounded `await` inside the tool — a child
process awaited without a deadline is the usual cause; spawn it through
`parrot.flows.dev_loop.procs.run_bounded` or wrap it in `asyncio.wait_for`.
The client log names the culprit: the first `Calling MCP tool: <name>`
line without a matching `completed` line in
`~/.cache/claude-cli-nodejs/<cwd-slug>/mcp-logs-<server>/`.

**A tool call rejects with a missing/invalid `confirm` argument.**
The tool is in the toolkit's `confirming_tools`. This is expected — the
MCP host's caller (the model) must pass `confirm: true` explicitly.

---

## Related

- [Tool optimizations (FEAT-543)](tool-optimizations.md) — the
  `local-git`, `bounded-source` and `targeted-writer` toolkits configured
  through this machinery, including the `llm_kwargs` example and the
  opt-in host read guards.
- [FEAT-403 — `wikitoolkit mcp`](../sdd/specs/) — the pattern this feature
  generalizes; `StdioMCPServer`/`LocalServerConfig`/`MCPToolAdapter` are
  shared, unmodified core machinery.
- `parrot mcp serve` (`ai-parrot-server`) — the full aiohttp-backed,
  multi-agent MCP server. Unrelated and unaffected by this feature; if you
  need the full server's capabilities (auth, multi-agent routing), use
  that instead of `mcp-local`.

## `sdd-coder` — orchestration kernel for the interactive sdd-worker (FEAT-549)

`SddCoderToolkit` (`parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit`)
exposes the FEAT-323 dev-loop machinery — `TaskScheduler`,
`SubWorktreeManager`, `build_dispatcher` — as seven MCP tools so the
interactive `sdd-worker` agent can dispatch one `sdd-coder` sub-agent per
task, across a roster of heterogeneous model seats, in parallel:
`coder_plan`, `coder_run_chunk`, `coder_prepare_native`, `coder_merge`,
`coder_wait`, `coder_status`, `coder_cleanup`. Every result is a
`CoderResult` envelope (`status: "ok" | "error"`); argument validation
happens in `_pre_execute` before the engine is ever touched.

```bash
# Append the toolkit entry — never `cp` over an existing .parrot/mcp-toolkits.yaml,
# which would drop every other toolkit configured in it.
sed -n '/^toolkits:/,$p' examples/sdd-coder-mcp.yaml | tail -n +2 \
  >> .parrot/mcp-toolkits.yaml
parrot mcp-local --list --config .parrot/mcp-toolkits.yaml   # sdd-coder + your other toolkits
parrot mcp-local sdd-coder --config examples/sdd-coder-mcp.yaml   # serve straight from the example
```

The roster (which models fill which seat, and their fallbacks) lives
entirely in the yaml's `kwargs.roster` — nothing is hardcoded in Python or
in the `sdd-worker`/`sdd-coder` prompts. See
[`docs/dev_loop/sdd-coder-orchestrator.md`](dev_loop/sdd-coder-orchestrator.md)
for the full install steps, roster semantics, the orchestrator loop, and
known gotchas (the Gemini 3 `thought_signature` echo requirement,
`GEMINI_API_KEY` resolution via `navconfig`).
