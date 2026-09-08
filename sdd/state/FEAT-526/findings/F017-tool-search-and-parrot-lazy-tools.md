# F017 — Meta tool search vs. parrot's existing lazy-tool mechanism

**Meta (server-side)** — `docs/tool-search.md`:
- Add `{"type": "tool_search"}` to `tools`, and set `defer_loading: true` on the
  individual functions to defer.
- A deferred tool's **name and description stay visible**; only its parameter
  schema is withheld until loaded. Loaded definitions are appended at the **end**
  of context to preserve the cache prefix.
- Two modes: **hosted** (API searches and loads in the same response) and
  **client** (`execution: "client"` — model emits `tool_search_call` and stops).
- Response adds `tool_search_call` and `tool_search_output` output items.
- **Live probe**: `tools:[{"type":"tool_search"}]` alone → **HTTP 400**
  `"tools.tool_search requires at least one deferred tool."` — the hosted mode
  is inert without `defer_loading: true` tools.

**parrot (client-side)** — `clients/base.py`:
- `_prepare_lazy_tools()` (:1322) exposes only a `search_tools` tool;
  `_check_new_tools()` (:1298) parses its result to discover tool names.
- This is parrot's own **client-side** lazy-loading protocol — functionally the
  same idea as Meta's, implemented one layer up.

**Implication — a real design decision for the spec**: two overlapping
mechanisms. Options: (a) map parrot's `search_tools` onto Meta's native hosted
`tool_search`; (b) keep parrot's client-side path and ignore the native one;
(c) expose the native one as an opt-in `MetaClient` flag. Not a blocker, but it
should be decided deliberately rather than by accident.

*Aside*: `_prepare_lazy_tools` carries a candid in-code note (*"I will hack
specific getting for now"*) — pre-existing debt, out of scope here.
