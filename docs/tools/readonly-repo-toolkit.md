# ReadOnlyRepoToolkit (FEAT-484)

A cwd-confined, write-free `AbstractToolkit` that gives any `AbstractClient`
safe read access to a repository checkout. It exists so a hosted model can
ground itself in a codebase without any custom, per-client, per-transport
plumbing — register it once and every tool dispatches the same way,
regardless of which client is asking.

Location: `parrot/tools/repo/` (`packages/ai-parrot/src/parrot/tools/repo/`).

## The four grounding axes

| Axis | Tools | Backed by |
|---|---|---|
| Structural | `search_code`, `related_code` | `WikiCombinedSearch` over the AST/tree-sitter code graph (lexical FTS5/BM25) |
| Static | `read_file`, `list_files`, `grep_files` | Confined filesystem access + `git grep` (falls back to a bounded walk) |
| Historical | `git_log`, `git_show`, `git_blame` | Local `git`, via `asyncio.create_subprocess_exec` |
| External | `web_search` | `DdgSearchTool`, **opt-in only** |

`search_code` is the preferred entry point for "where does X live / how do
modules relate" questions — it returns ranked, deduplicated results with
summaries and skips build artifacts. `grep_files` is the explicit fallback
for what the graph cannot answer: regexes, config strings, or files outside
the index.

## Read-only by construction

`ReadOnlyRepoToolkit` defines **no mutating method** — there is no
`write_file`, no `apply_patch`, no `run_command`, not behind a flag, not
behind a permission mode. `AbstractToolkit._generate_tools()` only turns
public `async def` methods into LLM-callable tools, so "no write tool is
defined" and "no write tool is reachable" are the same statement here. This
mirrors `NovaAdversarialReviewDispatcher`'s "read-only by construction"
design (`dispatchers/nova.py`).

## The confinement boundary

Every tool that resolves a caller-supplied path funnels through
`resolve_within_root()` (`parrot/tools/repo/confinement.py`):

1. Resolve the candidate to an absolute **real** path (`Path.resolve()`,
   which follows symlinks).
2. Assert the result is inside `repo_root` (itself resolved, so a
   symlinked root doesn't break containment).

Rejection returns a structured `RepoToolError` the model can read and
recover from — **never** an exception that aborts the dispatch loop, and
**never** a silent empty result. This one code path is deliberately reused
by `read_file`, `list_files`, `grep_files`, and every path argument on the
git tools; a second implementation would be a second chance to get it
wrong.

## Secret deny-list (spec §8 Q1)

Path confinement alone leaves `.env`, private keys, and credential files
readable by a hosted model. `is_secret_path()` denies (case-insensitively,
matched on the repo-relative path):

```
.env, .env.*, *.pem, *.key, *.p12, *.pfx,
id_rsa*, id_dsa*, id_ecdsa*, id_ed25519*,
*.local.json, credentials, .netrc, .pgpass,
*.keystore, *.jks
```

A match is **overridden** (the path is readable) when the filename ends in
`.example`, `.sample`, `.template`, or `.dist` — so `.env.example` reads
fine while `.env` does not.

- `read_file` on a deny-listed path returns
  `RepoToolError{error: "secret_file"}`.
- `grep_files` and `list_files` **omit** deny-listed paths from their
  results entirely — a grep must not become a secret-exfiltration side
  channel.
- `search_code` inherits the protection for free: it never returns file
  bodies, only summaries and paths.

Set `deny_secret_files=False` on the constructor to disable the deny-list
specifically — it **never** affects path containment; `escape/secret.txt`
outside the root is still refused either way.

## Bounds (and their defaults)

| Constructor argument | Default | Governs |
|---|---|---|
| `max_result_bytes` | `64_000` | Any single tool result (file content, grep/git output). Truncation sets `truncated=True` and appends a visible marker — never a silent cut. |
| `max_search_hits` | `12` | Max hits from `grep_files`/`search_code`/`related_code`; also caps `list_files` (at `max_search_hits * 10`, hard-capped at 500). |
| `search_budget_tokens` | `4_000` | Token ceiling for `search_code` results, enforced via `pack_results`. `total_tokens` on the result is always `<= search_budget_tokens`. |
| `command_timeout` | `20.0` seconds | Every subprocess (`grep_files`, `git_log`/`show`/`blame`). A timed-out child is killed; cancellation also kills the child — no orphan processes. |

Every subprocess in this package uses `asyncio.create_subprocess_exec` with
an **argv list** — never `shell=True`, never blocking `subprocess.run`.

## The degradation contract

Nothing in this toolkit fails hard when its ideal backend is unavailable —
it degrades, and it says so:

- **`search_code` / `related_code`**: when the wiki plane is missing,
  unbuilt, or errors — or the plane query comes back with nothing usable —
  the tool transparently falls back to `grep_files` and returns
  `degraded=True` with a non-empty `degraded_reason`, plus a
  `self.logger.warning(...)` for the operator. The model always sees the
  degradation in the payload it reads; it is never silent.
- **`mode="vector"`** (see below) with no embedder configured degrades to
  lexical with `degraded_reason="semantic search not configured"` rather
  than returning an empty result.
- **The git tools** (`git_log`/`git_show`/`git_blame`) return a structured
  `RepoToolError` outside a git repository, or when `git` itself is
  unavailable — never an exception.
- **`grep_files`** itself is never "degraded" — `degraded=False` always for
  a direct call. `degraded=True` is exclusively a signal that `search_code`
  fell back to it.

## The `mode` argument (spec §8 Q2)

`search_code(query, top_k=12, mode=None)` exposes `mode` as a tool argument
— a `Literal["lexical", "vector", "combined"]` — so the model itself can
choose a strategy:

- **`lexical`** (the default, via `default_search_mode`) — matches names
  and text. Best for symbols and modules.
- **`combined`** — also considers semantic similarity where available.
- **`vector`** — semantic only.

This installation ships **no embedder** (spec §8 Q4 — lexical only,
conceptual recall is a follow-up). With no embedder, the vector leg of the
plane query is skipped: `combined` silently gets full lexical weight, and a
pure `vector` request would return nothing — so `search_code` explicitly
maps `vector` to `lexical` and marks the result `degraded=True` with a
reason, rather than returning an empty response. An embedder-enabled
deployment gains real semantic search with no signature change.

## Worktree plane behavior — read this before reusing this toolkit elsewhere

The code graph ("wiki plane") backing `search_code`/`related_code` is
rooted at a checkout and can be very large (hundreds of MB), so building
one per git worktree is a non-starter. When `repo_root` is a git worktree,
`resolve_plane_root()` resolves the **main checkout** (via
`git rev-parse --path-format=absolute --git-common-dir`) and queries its
plane instead of rebuilding.

**The tradeoff, explicitly:** from inside a worktree, the partner sees the
codebase at roughly **last-commit state** through `search_code` —
uncommitted or worktree-local edits are not reflected in the graph.
`git_log`/`git_show`/`git_blame` and `read_file`/`list_files`/`grep_files`
all read the live filesystem and cover this gap.

This tradeoff is **correct for research** — investigating how a codebase
works, independent of any one in-flight change — and **wrong for review**
— inspecting a specific diff, where staleness would hide exactly the
change under review. If this toolkit is ever reused by a
review-style consumer, that consumer needs its own freshness story; do not
assume `search_code` reflects the diff being reviewed.

This toolkit is a **pure consumer** of the plane: it never builds or
refreshes it (`wikitoolkit build` and its git-post-commit hook own
indexing). A missing or stale plane simply degrades `search_code` to
`grep_files`.

## `enable_web_search` — absent, not disabled

`web_search` is the only tool with a network egress question, so it is
the only one gated by a constructor flag — and the gate is by
**construction**, not by a runtime check inside the method:

```python
if not enable_web_search:
    self.exclude_tools = (*self.exclude_tools, "web_search")
```

`AbstractToolkit._generate_tools()` reads `self.exclude_tools` before
generating any tool, so with `enable_web_search=False` (the default),
`"web_search"` is **not present** in `get_tools()` at all — a client
cannot call what does not exist. This preserves the read-only-by-construction
property for the egress axis too: no way to accidentally leave it reachable.

When enabled, `web_search` delegates to `DdgSearchTool` (imported lazily,
since it ships from the separate `ai-parrot-tools` distribution) and
degrades to a structured `{"error": ..., "results": []}` dict — never an
exception — on either an import failure or a search failure.

## Registration example — both transports

The whole point of registering `ReadOnlyRepoToolkit` on `AbstractClient` is
that it works unchanged regardless of which transport the client uses.
FEAT-482 registers the **same toolkit class** on both a Bedrock Converse
client and an OpenAI-compatible one:

```python
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.clients.nova.client import NovaClient          # Bedrock Converse
from parrot.clients.nova.mantle import BedrockMantleClient  # OpenAI-compatible

toolkit = ReadOnlyRepoToolkit(
    repo_root=Path("/path/to/checkout"),
    enable_web_search=False,       # default: web_search absent entirely
    default_search_mode="lexical",  # no embedder configured
)

# Converse (Bedrock) — NovaClient/BedrockConverseBase share one registry
# (AbstractClient.tools) and one dispatch path (_execute_tool).
converse_client = NovaClient(model="...")
for tool in toolkit.get_tools():
    converse_client.tools[tool.name] = tool

# OpenAI-compatible (bedrock-mantle) — same toolkit instance, same tools,
# no per-transport branching anywhere in the toolkit.
openai_client = BedrockMantleClient(model="...")
for tool in toolkit.get_tools():
    openai_client.tools[tool.name] = tool
```

Both clients dispatch every tool through their own `_execute_tool`
(`AbstractClient._execute_tool` / `OpenAIBaseClient._execute_tool`) against
the exact same `ToolkitTool` instances — there is no Converse-shaped or
OpenAI-shaped variant of anything in this package, and there should never
be one.

## Non-goals

- **No write capability, ever.** Not behind a flag, not behind a
  permission mode.
- **No plane build/refresh.** `wikitoolkit build` owns indexing; this
  toolkit only ever reads what is already there.
- **No vector/embedding leg shipped.** Lexical FTS5/BM25 only.
- **No dev-flow / dev-loop coupling.** This package imports nothing from
  `parrot.flows.dev_flow` or `parrot.flows.dev_loop`; wiring it into a
  research/review flow is the consumer's job (see FEAT-482).
- **No sandboxing beyond path confinement.** Resource limits (cgroups,
  seccomp) are out of scope; the bounds here are byte-size and timeout
  only.
