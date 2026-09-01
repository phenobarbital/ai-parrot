# Expose Toolkits as Local MCP (`parrot mcp-local`)

> **Feature**: FEAT-485 — Expose Toolkits as Local MCP
> **Spec**: [sdd/specs/expose-toolkits-as-local-mcp.spec.md](../sdd/specs/expose-toolkits-as-local-mcp.spec.md)
> **Package**: `ai-parrot` (core) — `parrot.mcp.local_cli`, `parrot.mcp.toolkit_server`, `parrot.mcp.toolkit_config`

`parrot mcp-local <name>` serves any `AbstractToolkit` subclass — one of
the three zero-config built-ins (`scraping`, `browsing`, `memory`) or a
toolkit of your own — as a **per-toolkit local stdio MCP server**. Each
name becomes its own process, its own tool namespace, and its own
`.mcp.json` / `.codex/config.toml` server entry, so an MCP host (Claude
Code, Codex) sees the toolkit's tools as first-class, equal-standing tools
at tool-selection time — no Bash competition, no hook nudging. This is the
same pattern FEAT-403 proved for `wikitoolkit mcp`, generalized to any
toolkit.

---

## Quickstart

```bash
# See what's resolvable (built-ins + your .parrot/mcp-toolkits.yaml
# sections), with enabled state — fast, does not import any toolkit class:
parrot mcp-local --list

# Serve a toolkit directly (mostly for manual testing — an MCP host
# normally spawns this for you via the installed .mcp.json entry):
parrot mcp-local memory

# Wire it into Claude Code's .mcp.json:
parrot claude install

# Or into Codex's .codex/config.toml:
parrot codex install
```

`parrot claude install` / `parrot codex install` write one managed server
entry per **enabled** toolkit section automatically — you do not hand-edit
`.mcp.json` or `.codex/config.toml`. Re-running either command reconciles:
sections you disable or delete disappear from the managed entries; foreign
entries (anything the installer did not write) are never touched.

---

## Configuration: `.parrot/mcp-toolkits.yaml`

Read relative to the **project root** — the directory the MCP host starts
`parrot mcp-local <name>` in (normally your repo root). The file is
optional: the three built-ins (`scraping`, `browsing`, `memory`) work with
**no config file at all**. When present, its `toolkits:` sections are
deep-merged **over** the built-in defaults — a section with a built-in's
name **replaces** that built-in wholesale (its `kwargs` are not merged
with the built-in's kwargs, they are overwritten); new names are simply
added.

See [`examples/mcp-toolkits.yaml`](../examples/mcp-toolkits.yaml) for a
fully annotated copy-paste starting point.

### Schema

```yaml
toolkits:
  <name>:
    class: <dotted.path.to.AbstractToolkitSubclass>   # required (YAML key: "class")
    enabled: true                                     # default: true
    kwargs: {}                                        # constructor kwargs (replaces, not merges)
    include: null                                      # optional whitelist of tool names
    exclude: null                                      # optional blacklist of tool names
    llm: null                                          # optional "provider:model" string
    env: {}                                            # env vars written into installer entries
```

| Field | Type | Meaning |
|---|---|---|
| `class` | `str` (required) | Dotted path to an `AbstractToolkit` subclass, e.g. `parrot_tools.scraping.toolkit.WebScrapingToolkit`. Resolved via `importlib` — see the trust note below. |
| `enabled` | `bool` (default `true`) | Whether the installers (`parrot claude install` / `parrot codex install`) include this section in their managed entries and whether `--list` shows it as `enabled`/`disabled`. **Does not** block a direct `parrot mcp-local <name>` invocation — a disabled section can still be served manually. |
| `kwargs` | `dict` | Keyword arguments passed to the toolkit's constructor. A file section's `kwargs` **replaces** a built-in's `kwargs` entirely, it is not deep-merged. |
| `include` | `list[str] \| null` | Whitelist of tool names to expose. When set, only these are exposed. |
| `exclude` | `list[str] \| null` | Blacklist of tool names to exclude. Only consulted when `include` is unset. |
| `llm` | `str \| null` | A `"provider:model"` string (e.g. `"openai:gpt-4o-mini"`, `"anthropic:claude-3-5-haiku-latest"`). When set, `LLMFactory.create()` builds a client passed to the toolkit's constructor as `llm_client`. |
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

### Built-ins

| Name | Class | Notes |
|---|---|---|
| `scraping` | `parrot_tools.scraping.toolkit.WebScrapingToolkit` | Requires `ai-parrot-tools[scraping]` (or `[browsing]` for shared browser drivers). Structured scraping/crawling with plan caching. |
| `browsing` | `parrot_tools.browsing.toolkit.WebBrowsingToolkit` | Requires `ai-parrot-tools[browsing]`. Catalogued, deterministic site automation. |
| `memory` | `parrot.tools.working_memory.tool.WorkingMemoryToolkit` | Ships with bare `ai-parrot` — no extra install. Ephemeral, **per-process** DataFrame/result scratchpad; state never persists across restarts and is never shared between two server processes. |

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
5. Wire it into your MCP host: `parrot claude install` and/or
   `parrot codex install`. Re-run either after editing the config to
   reconcile the managed entries (add/update/remove) — installs are
   idempotent.

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
The name isn't a built-in and isn't a key under `toolkits:` in your
config. The error message on stderr lists every resolvable name — compare
against `parrot mcp-local --list`.

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

**A tool call rejects with a missing/invalid `confirm` argument.**
The tool is in the toolkit's `confirming_tools`. This is expected — the
MCP host's caller (the model) must pass `confirm: true` explicitly.

---

## Related

- [FEAT-403 — `wikitoolkit mcp`](../sdd/specs/) — the pattern this feature
  generalizes; `StdioMCPServer`/`LocalServerConfig`/`MCPToolAdapter` are
  shared, unmodified core machinery.
- `parrot mcp serve` (`ai-parrot-server`) — the full aiohttp-backed,
  multi-agent MCP server. Unrelated and unaffected by this feature; if you
  need the full server's capabilities (auth, multi-agent routing), use
  that instead of `mcp-local`.
