---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Fireflies MCP Meeting Filters

**Date**: 2026-08-21
**Author**: Arturo Martinez
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`FirefliesObsidianAgent.sync_fireflies_transcripts()` (`packages/ai-parrot/src/parrot/agents/obsidian.py:141`)
currently calls the Fireflies MCP tool `fireflies_get_transcripts` with only
one parameter it exposes to the caller: `limit`. Every other filter the
Fireflies MCP tool itself supports — date range, keyword/content search,
organizer/participant emails, "mine only", and channel/folder — is silently
unavailable. The agent always pulls the caller's *N* most recent meetings,
full stop.

For a user running this as a scheduled sync (`fireflies_daemon.yaml`, every
8 hours) or a manual run, that means there is no way to scope which meetings
land in the Obsidian vault: no "only my 1:1s", no "only last week's client
calls", no "only meetings in the Sales channel". The user has to sync
everything and prune the vault by hand.

**Who is affected**: the operator running `FirefliesObsidianAgent` (today,
primarily the repo owner via the example script / `agentd` daemon config).

**Why now**: the underlying Fireflies MCP tool (`fireflies_get_transcripts`,
exposed via `npx mcp-remote` per `create_fireflies_mcp_server`,
`packages/ai-parrot/src/parrot/mcp/integration.py:1067`) already supports
this filtering server-side — this is a client-side gap in the agent, not a
capability the MCP server is missing.

## Constraints & Requirements

- Must go through the *existing* Fireflies MCP tool call path
  (`self._call_fireflies_tool("fireflies_get_transcripts", args)` →
  `self.tool_manager.get_tool("mcp_fireflies_fireflies_get_transcripts")` →
  `tool.execute(**args)`, `packages/ai-parrot/src/parrot/agents/obsidian.py:476-500`).
  No new MCP server/transport work.
- Structured data → Pydantic model per `python-development` / `CLAUDE.md`
  conventions, not a bare dict.
- `sync_fireflies_transcripts(limit=10, skip_existing=True)` is a public,
  documented, exposed method (`fireflies_daemon.yaml` `exposed_methods:`,
  the example script, and `test_obsidian.py`) — backward compatibility for
  callers that pass no filters is required (unchanged behavior: most-recent
  `limit` meetings, unfiltered).
- Filter values must map onto exactly the parameters
  `fireflies_get_transcripts` accepts: `fromDate`, `toDate`, `keyword`,
  `scope` (`title|sentences|all`), `organizers` (email array), `participants`
  (email array), `mine` (bool), `channelId`, plus the existing `limit`/`skip`
  pagination pair. (Verified against the live tool schema — see Code Context.)
- `limit` keeps its current meaning for existing callers: total transcripts
  desired, not a page size — pagination beyond the API's per-call cap of 50
  must be transparent to the caller.
- Must remain schedule-friendly: `fireflies_daemon.yaml` should be able to
  declare default filters for unattended runs (e.g. "only my meetings")
  without the caller re-specifying them on every invocation.

---

## Options Explored

### Option A: `FirefliesFilters` Pydantic model + internal auto-pagination

Add a `FirefliesFilters` Pydantic model capturing every filter dimension
`fireflies_get_transcripts` supports, plus a new optional `filters` argument
on `sync_fireflies_transcripts()`. The agent maps the model's snake_case
fields onto the tool's camelCase parameter names, merges them with an
optional agent-level `default_filters` (constructor kwarg, settable from
`fireflies_daemon.yaml`), and internally loops the tool call
(`skip=0,50,100,…`) until the API returns an empty page, accumulating
transcripts until `limit` is reached — with `limit` still meaning "total
transcripts across all pages," matching today's semantics.

✅ **Pros:**
- One clean, typed, reusable filter model — validated once (bad `scope`
  enum, malformed dates) before any network call.
- `limit` keeps its current meaning; zero-filter calls behave exactly as
  today (full backward compatibility for the example script, the daemon
  YAML, and existing tests).
- Auto-pagination means callers never have to know the underlying API caps
  a single call at 50 — they just ask for `limit=200` and get it.
- Agent-level `default_filters` lets the scheduled daemon apply a standing
  scope (e.g. `mine=true`) without every invocation repeating it.

❌ **Cons:**
- Most implementation work of the three options: new model, field-name
  mapping layer, pagination loop, default-filter merge logic.
- Unbounded pagination (per the resolved decision below) means a caller who
  passes very broad/no filters can trigger a long-running sync against a
  large Fireflies account — this is an accepted, explicitly chosen risk (see
  Open Questions).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (==2.12.5, already a core dependency) | `FirefliesFilters` model, field validation | Pinned in `packages/ai-parrot/pyproject.toml:51`; no new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/agents/obsidian.py:476` `_call_fireflies_tool()` — unchanged call path, just richer `args`.
- `packages/ai-parrot/src/parrot/agents/obsidian.py:392` `_parse_fireflies_response()` — unchanged; still parses each page's raw text response the same way.
- `packages/ai-parrot/src/parrot/mcp/integration.py:1067` `create_fireflies_mcp_server()` / `:1451` `add_fireflies_mcp_server()` — unchanged; filters are a sync-time concern, not a connection-time one.
- `examples/agents/fireflies_daemon.yaml` — natural home for a new `default_filters:` block under `agent.kwargs`.

---

### Option B: Raw `dict` passthrough, caller-driven pagination

Accept `filters: Optional[dict] = None` on `sync_fireflies_transcripts()`
and forward its keys almost verbatim into the `fireflies_get_transcripts`
tool call args (after light key-casing normalization). No model, no
validation, no internal pagination — a caller wanting more than one page
calls `sync_fireflies_transcripts()` again with `filters={"skip": 50, ...}`
themselves.

✅ **Pros:**
- Least code to write and test — a handful of lines merging a dict into the
  existing `args` dict.
- Trivially extensible if Fireflies adds a new tool parameter later (no
  model field to add).

❌ **Cons:**
- Violates the project's Pydantic-for-structured-data convention
  (`.claude/rules/python-development.md`, `CLAUDE.md`) — no type safety, no
  validation, typos in filter keys silently produce empty results instead of
  errors.
- Pushes pagination and default-filter merging onto every caller — directly
  contradicts the schedule-friendly requirement (the daemon YAML can't
  declare "always sync more than 50 meetings" without external looping
  logic).
- Weakest fit for the decided requirements (structured model + auto-paginate
  were both explicitly requested) — kept here mainly as the contrasting
  baseline against Option A.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| *(none new)* | plain `dict` merge | no new dependency, but no validation either |

🔗 **Existing Code to Reuse:**
- Same `_call_fireflies_tool()` / `_parse_fireflies_response()` reuse as Option A.

---

### Option C (unconventional): Build a `fireflies_search` mini-grammar query instead

Fireflies MCP also exposes `fireflies_search(query: str)`, which accepts a
mini query grammar (`keyword:"x" scope:sentences from:2026-01-01
organizers:a@x.com,b@x.com mine:true channel:<id> limit:20 skip:10`,
verified against the live tool schema) rather than discrete JSON parameters.
This option would define the *same* `FirefliesFilters` model as Option A but
serialize it into that grammar string and call `fireflies_search` instead of
`fireflies_get_transcripts`, then parse `fireflies_search`'s (differently
shaped) response.

✅ **Pros:**
- `fireflies_search`'s grammar natively supports the same filters plus a
  richer keyword/`scope` combination in one string, and it is the tool
  Fireflies documents as the "advanced" query surface.
- Would future-proof against new grammar tokens Fireflies adds to the search
  DSL without a client-side schema change (new tokens just pass through the
  string).

❌ **Cons:**
- Requires writing and testing a string-grammar serializer (escaping
  quoted keyword terms, comma-joining email lists, formatting dates) —
  strictly more code than mapping to named JSON parameters.
  `fireflies_search`'s response shape has not been verified to match
  `_parse_fireflies_response()`'s expectations (built for
  `fireflies_get_transcripts`'s `[N]: - id: ...` text format) — would very
  likely need a second parser, doubling the parsing surface to maintain.
- Explicitly the option the user steered away from in discovery: structured
  kwargs on `fireflies_get_transcripts` were preferred specifically to avoid
  building/parsing a query string.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (==2.12.5) | Same `FirefliesFilters` model, reused as a serializer source | no new dependency |

🔗 **Existing Code to Reuse:**
- `_call_fireflies_tool()` for the call path (tool name would become
  `fireflies_search` instead of `fireflies_get_transcripts`).
- None of `_parse_fireflies_response()` is reusable as-is — `fireflies_search`
  results were not observed to share `fireflies_get_transcripts`'s exact text
  layout.

---

## Recommendation

**Option A** is recommended.

The problem statement and every discovery round converged on the same
shape: a typed `FirefliesFilters` model over `fireflies_get_transcripts`
(not `fireflies_search`), with internal pagination so `limit` keeps meaning
"how many meetings I want," and an agent-level default so the scheduled
daemon can carry a standing filter.

Trading off against Option B: Option A costs more code (a model, a
field-mapping layer, a pagination loop) but that cost buys exactly the
validation and schedule-friendliness the requirements call for — Option B's
savings would just relocate that work onto every caller, which for a
daemon-scheduled agent means it never gets done consistently.

Trading off against Option C: `fireflies_search`'s grammar is more powerful
in the abstract, but it was explicitly ruled out in discovery, and adopting
it here would mean maintaining two response parsers for one feature with no
concrete requirement driving that cost.

---

## Feature Description

### User-Facing Behavior

- `sync_fireflies_transcripts()` gains a new optional `filters` parameter
  accepting a `FirefliesFilters` instance (or `None`, unchanged today's
  behavior — most-recent `limit` meetings, no scoping).
- A caller can now do things like:
  ```python
  await agent.sync_fireflies_transcripts(
      limit=100,
      filters=FirefliesFilters(
          from_date="2026-08-01",
          mine=True,
          organizers=["boss@company.com"],
      ),
  )
  ```
  and get up to 100 of *their own* meetings organized by that person since
  Aug 1, regardless of how many pages that takes against the underlying
  50-per-call API cap.
- `FirefliesObsidianAgent`'s constructor gains an optional `default_filters:
  FirefliesFilters` kwarg. `fireflies_daemon.yaml` can set this under
  `agent.kwargs.default_filters` so every scheduled run applies a standing
  scope without the caller (e.g. `parrot ask fireflies-sync "sync"`)
  re-specifying it.
- Callers who never touch `filters` see byte-for-byte the same behavior as
  today.

### Internal Behavior

- New `FirefliesFilters` Pydantic model (fields: `from_date`, `to_date`,
  `keyword`, `scope` (`Literal["title","sentences","all"]`, default
  `"all"`), `organizers: list[str]`, `participants: list[str]`, `mine:
  Optional[bool]`, `channel_id: Optional[str]`) — validated at construction
  time, so a bad `scope` value or malformed date fails fast before any tool
  call.
- A small mapping step converts the model's snake_case fields to the tool's
  camelCase parameter names (`from_date`→`fromDate`, `to_date`→`toDate`,
  `channel_id`→`channelId`; `keyword`/`scope`/`organizers`/`participants`/
  `mine` pass through unchanged) and drops unset/`None` fields so the tool
  call only carries filters the caller actually specified.
- If both `default_filters` (agent-level) and a per-call `filters` are
  present, per-call fields take precedence over agent defaults on a
  field-by-field basis (call-level filter wins where both set a value;
  agent default fills in fields the call left unset).
- `sync_fireflies_transcripts()`'s existing single
  `_call_fireflies_tool("fireflies_get_transcripts", {"limit": limit})` call
  becomes a loop: call with the mapped filter args plus `limit=min(50,
  remaining)` and increasing `skip`, accumulate parsed transcripts (still via
  the unchanged `_parse_fireflies_response()`), and keep looping until either
  the running total reaches the caller's `limit` or a page comes back with
  fewer transcripts than requested (i.e., the API is exhausted). No hard
  page/total ceiling is imposed (explicit user decision — see Open
  Questions).
- Everything downstream of "list of transcript dicts" — per-transcript
  fetch, `skip_existing` dedup, Obsidian note creation, OKF frontmatter — is
  unchanged.

### Edge Cases & Error Handling

- **Invalid filter shape** (bad `scope` literal, unparseable date, etc.):
  `FirefliesFilters(...)` raises `pydantic.ValidationError` before any MCP
  call; this surfaces through `sync_fireflies_transcripts()`'s existing
  top-level `try/except` as `report["status"] = "error"`.
- **A page fetch fails mid-pagination** (e.g. page 3 of an unknown-length
  sequence errors): stop requesting further pages, keep the transcripts
  already accumulated from prior successful pages, append the failure to
  `report["errors"]`, and proceed to sync what was fetched — `report["status"]`
  stays `"ok"` with a partial result, consistent with how a single
  transcript's sync failure is handled today (logged into `errors`, loop
  continues).
- **No filters + a broad/no `limit`**: pagination continues until the API
  itself returns an empty/short page — there is no engineered ceiling. This
  is an explicit, accepted risk from discovery (see Open Questions), not an
  oversight.
- **`channel_id` filter with no matching channel / an invalid ID**: passed
  through to the tool as-is; whatever the Fireflies API/tool returns for an
  unknown channel (almost certainly an empty result set) is surfaced
  unchanged — this feature does not add channel-name resolution
  (`fireflies_list_channels`) as a convenience.

---

## Capabilities

### New Capabilities
- `fireflies-mcp-meeting-filters`: structured, validated filtering
  (date range, keyword/scope, organizers/participants, mine-only,
  channel) over `FirefliesObsidianAgent.sync_fireflies_transcripts()`,
  plus transparent multi-page fetching against the Fireflies MCP
  `fireflies_get_transcripts` tool and an agent/daemon-level default-filter
  setting.

### Modified Capabilities
- None. `FirefliesObsidianAgent` and its sync method were introduced without
  a dedicated prior spec (they exist today only as example/agent code plus
  `test_obsidian.py`); the only related prior spec,
  `sdd/specs/integrate-mcp-fireflies.spec.md` (FEAT-237), covers
  `FIREFLIES_API_KEY` env-var resolution in the MCP *connection* layer
  (`parrot/mcp/integration.py`, `parrot/mcp/registry.py`) — a different,
  unaffected layer from this feature's sync-time filtering.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/obsidian.py` (`FirefliesObsidianAgent`) | extends | New `FirefliesFilters` model, constructor `default_filters` kwarg, `sync_fireflies_transcripts(filters=...)` param, internal pagination loop. |
| `packages/ai-parrot/tests/agents/test_obsidian.py` | extends | New tests for filter validation, field-name mapping, pagination, and default-filter merge. |
| `examples/agents/fireflies_daemon.yaml` | extends | Optional new `agent.kwargs.default_filters` documented block; no schema-breaking change since it's additive YAML. |
| `examples/agents/fireflies_obsidian_sync.py` | extends (optional) | Could show a `filters=FirefliesFilters(...)` usage example; not required for the feature to function. |
| `packages/ai-parrot/src/parrot/mcp/integration.py` (`create_fireflies_mcp_server` / `add_fireflies_mcp_server`) | none | Unaffected — this feature is entirely about the sync-time tool *call*, not MCP server connection/auth. |
| `packages/ai-parrot/src/parrot/mcp/registry.py` (`fireflies` descriptor) | none | Unaffected, same reason as above. |

---

## Code Context

### User-Provided Code
_None — the user described the desired behavior in free-form notes; no code was pasted during discovery._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/agents/obsidian.py:28
class FirefliesObsidianAgent(BasicAgent):
    def __init__(  # line 45
        self,
        name: str = "FirefliesObsidianSync",
        vault_path: Optional[str | Path] = None,
        fireflies_token: Optional[str] = None,
        meetings_folder: str = "meetings",
        **kwargs,
    ): ...

    async def sync_fireflies_transcripts(  # line 141
        self,
        limit: int = 10,
        skip_existing: bool = True,
    ) -> Dict[str, Any]: ...
        # currently calls:
        #   await self._call_fireflies_tool(
        #       "fireflies_get_transcripts", {"limit": limit}
        #   )                                             # line 150

    async def _call_fireflies_tool(  # line 476
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Any:
        # full_name = f"mcp_fireflies_{tool_name}"
        # tool = self.tool_manager.get_tool(full_name)
        # result = await tool.execute(**args)
        ...

    @staticmethod
    def _parse_fireflies_response(response_text: str) -> List[Dict[str, Any]]:  # line 392
        # Parses fireflies_get_transcripts' text format:
        #   [10]:
        #     - id: 01KZ...
        #       title: ...
        #       dateString: ...
        #       organizer_email: ...
        #       duration: ...
        #       participants { ... }
        ...

# From packages/ai-parrot/src/parrot/mcp/integration.py:1067
def create_fireflies_mcp_server(
    *,
    api_key: Optional[str] = None,
    api_base: str = "https://api.fireflies.ai/mcp",
    **kwargs,
) -> MCPServerConfig: ...

# From packages/ai-parrot/src/parrot/mcp/integration.py:1451 (inside MCPEnabledMixin)
async def add_fireflies_mcp_server(
    self,
    api_key: Optional[str] = None,
    **kwargs,
) -> List[str]: ...
```

#### Verified Imports
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:22-26 (already present)
from parrot.agents.obsidian import FirefliesObsidianAgent  # parrot/agents/__init__.py
from parrot.bots.agent import BasicAgent
from parrot.tools.obsidian import ObsidianToolkit
from parrot.models.responses import AIMessage
from parrot.interfaces.obsidian.okf import project_okf_block
from parrot.knowledge.okf.ontology import ConceptType, RelationType
```

#### Fireflies MCP Tool Parameters (verified against the live `fireflies_get_transcripts` tool schema)
- `channelId: str` — channel/folder ID (use `fireflies_list_channels()` to resolve names; out of scope here).
- `date: number` — **deprecated**, do not use.
- `fromDate: str` — ISO-8601 date, e.g. `"2023-01-01"`.
- `toDate: str` — ISO-8601 date.
- `keyword: str` (max 255 chars).
- `limit: number` — **max 50 per call** (this is exactly why Option A's pagination loop is required for any `limit > 50`).
- `mine: boolean`.
- `organizers: string[]` — email format.
- `participants: string[]` — email format.
- `scope: "title" | "sentences" | "all"`.
- `skip: number` — pagination offset.
- `format: "toon" | "json" | "text"` — response shape; existing code implicitly relies on the tool's default (`"toon"`), matching `_parse_fireflies_response()`'s expected text layout. **Not** part of `FirefliesFilters` — this is a response-format switch, not a meeting filter, and changing it would break the existing parser.

#### Key Attributes & Constants
- `FirefliesObsidianAgent.tool_manager` → provided by `BasicAgent`/`MCPEnabledMixin`, used via `.get_tool("mcp_fireflies_fireflies_get_transcripts")` (`packages/ai-parrot/src/parrot/agents/obsidian.py:494`).
- `FirefliesObsidianAgent._mcp_fireflies_initialized: bool` (`obsidian.py:65`) — gates `_ensure_fireflies_mcp()`; unaffected by this feature.

### Does NOT Exist (Anti-Hallucination)
- ~~A `fireflies_list_channels`-based name→ID resolver anywhere in `obsidian.py`~~ — does not exist; explicitly out of scope per discovery (caller must pass the raw `channel_id`).
- ~~Any existing `filters` / `FirefliesFilters` parameter on `sync_fireflies_transcripts()`~~ — does not exist yet; today's signature is exactly `(limit: int = 10, skip_existing: bool = True)`.
- ~~Pagination logic of any kind in `sync_fireflies_transcripts()`~~ — does not exist; today's implementation makes exactly one `fireflies_get_transcripts` call and never inspects `skip`.
- ~~A shared response parser between `fireflies_get_transcripts` and `fireflies_search`~~ — `_parse_fireflies_response()` is written against `fireflies_get_transcripts`'s text layout only; `fireflies_search`'s response shape is unverified against it (this is why Option C is rated High effort).
- ~~A `default_filters` constructor kwarg on `FirefliesObsidianAgent` today~~ — does not exist; the constructor currently only accepts `name`, `vault_path`, `fireflies_token`, `meetings_folder`, `**kwargs` (`obsidian.py:33-41`).

---

## Parallelism Assessment

- **Internal parallelism**: Low. This is a single-file, single-method-family
  change (`FirefliesFilters` model + `sync_fireflies_transcripts()` +
  constructor kwarg all live in `obsidian.py`); the model, the field-mapping,
  and the pagination loop are tightly coupled and best implemented as one
  sequential task. The `fireflies_daemon.yaml` doc update is a trivial
  same-file-set follow-on, not independent work.
- **Cross-feature independence**: No conflicts detected with in-flight specs.
  The only related prior spec (FEAT-237, `integrate-mcp-fireflies.spec.md`)
  touches `parrot/mcp/integration.py` and `parrot/mcp/registry.py` — files
  this feature does not touch at all.
- **Recommended isolation**: `per-spec` (single worktree, tasks run
  sequentially).
- **Rationale**: The entire change surface is one class in one file plus its
  test file and one YAML example — there is no natural seam (no separate
  toolkits, no unrelated endpoints) to split across worktrees. Sequential
  tasks in one worktree (model → mapping/pagination → daemon YAML docs →
  tests) is the right-sized approach.

---

## Open Questions

- [x] Which underlying Fireflies MCP tool to filter through —
      `fireflies_get_transcripts` vs `fireflies_search` — *Resolved with user
      (2026-08-21)*: `fireflies_get_transcripts` (structured kwargs), not the
      mini-grammar `fireflies_search`.
- [x] Filter dimensions to support — *Resolved with user (2026-08-21)*: date
      range, keyword/scope, organizer/participant emails, mine-only/channel
      — all four.
- [x] API shape for the filters — *Resolved with user (2026-08-21)*: a new
      `FirefliesFilters` Pydantic model passed as an optional `filters` arg.
- [x] Agent/daemon-level default filters — *Resolved with user
      (2026-08-21)*: yes, add a `default_filters` constructor kwarg,
      settable from `fireflies_daemon.yaml`.
- [x] Client-side validation strictness — *Resolved with user
      (2026-08-21)*: validate obvious shape errors only (Pydantic
      types/enums), leave semantic rejection to the Fireflies API/tool.
- [x] Pagination strategy — *Resolved with user (2026-08-21)*: auto-paginate
      internally; `limit` keeps meaning "total transcripts across all
      pages."
- [x] Pagination safety ceiling — *Resolved with user (2026-08-21)*: **no**
      hard cap — keep paginating until the API returns an exhausted/short
      page, however many that takes. **Flagging as an accepted risk**: an
      unfiltered or very broad-filtered call against a large Fireflies
      account could issue many sequential tool calls in one
      `sync_fireflies_transcripts()` invocation. `/sdd-spec` should decide
      whether this needs at least a documented caller-facing warning (e.g.
      in the method's docstring) even without an enforced ceiling.
- [x] Partial-pagination-failure behavior — *Resolved with user
      (2026-08-21)*: keep transcripts already fetched from prior successful
      pages, record the page error in `report["errors"]`, return
      `status="ok"` with the partial result.
- [x] Channel-name resolution convenience — *Resolved with user
      (2026-08-21)*: out of scope; caller passes the raw `channel_id`
      directly.
- [ ] Exact merge precedence when both `default_filters` and a per-call
      `filters` set the *same* field to different values — this brainstorm
      assumes "per-call field wins, agent default fills in only what the
      call left unset," but that specific tie-break was not put to the user
      explicitly and should be confirmed during `/sdd-spec`. — *Owner:
      Arturo Martinez*
- [ ] Should `FirefliesFilters` (or the daemon YAML's `default_filters`
      block) validate `organizers`/`participants` as well-formed email
      strings client-side, given the underlying tool schema types them as
      `format: email`? — *Owner: Arturo Martinez*
