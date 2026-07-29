# Tool-Result Compression Pipeline (FEAT-380)

A client-agnostic compression stage applied **once**, inside
`ToolManager.execute_tool()`, before any LLM client sees a tool result.
Every tool call that goes through `AbstractTool`/`ToolkitTool` benefits
from it automatically — no per-client code, no per-tool opt-in required.

> This page documents what **shipped**, verified against the merged
> implementation — not what the design spec originally proposed. A few
> places diverged from the spec's aspiration during implementation; those
> are called out explicitly below rather than glossed over.

## Why

Tool results used to reach the LLM with no semantic reduction. The only
prior defense was the Google client's `MAX_TOOL_RESULT_CHARS` truncation —
positional (keeps the *first N* elements/chars, regardless of which ones
actually matter) and client-specific (Claude/Groq/Grok had nothing at
all). The compression pipeline replaces that as the **primary** defense;
the Google client's truncation is demoted to a last line of defense (see
[Google client truncation](#google-client-truncation-last-line-of-defense)
below).

**Be honest about the numbers.** `MINIMAL` (the zero-config default) can
look like a 40% *byte* reduction, but BPE tokenizers merge whitespace
runs — the real *token* saving is closer to **5–15%**. The real return on
investment is `NORMAL` (columnar splitting + constant/null-column
factoring for row-oriented data), which can be dramatically larger for
the right shape of payload (e.g. `DatabaseQueryToolkit` results: N column
names no longer repeat once per row). Measure, don't assume — see
[Savings report](#savings-report) below.

## The four `FilterLevel`s

| Level | Behavior | Lossy? |
|---|---|---|
| `NONE` | Passthrough — compression never runs. | No |
| `MINIMAL` | **Default when nothing is configured.** Lossless only: JSON separator compaction, null-key elision, exact sibling dedup. | No |
| `NORMAL` | Bounded lossy transformations: columnar splitting (row-oriented data), constant-column factoring, long-field clipping. Arms the [tee](#tee-recovery-flow) when anything is actually dropped. | Possibly |
| `AGGRESSIVE` | Structural summary only — reserved for future codecs; no built-in codec currently emits an `AGGRESSIVE`-specific behavior beyond what `NORMAL` already does for `columnar`/`json_compact`. | Yes |

A codec's `compress()` call is always deterministic and synchronous — no
LLM is ever invoked to compress a result (that would defeat the purpose
and reintroduce a prompt-injection surface).

## Configuration

### The `.parrot/compressors.toml` format

```toml
# .parrot/compressors.toml — validated against CompressorConfig at load time

[compressor."dq_execute_database_query"]
codec = "columnar"
level = "normal"
tee = true

  [compressor."dq_execute_database_query".params]
  min_rows = 20
  heterogeneity_ratio = 1.5

[compressor."*"]
codec = "json_compact"
level = "minimal"
```

- `codec` must be a **registered** codec name (`json_compact` and
  `columnar` ship built in) — an unknown codec fails **at load time**
  (manager construction), never silently on the first tool call.
- `level` is one of the four `FilterLevel` values above; defaults to
  `minimal` when omitted.
- `tee` is currently informational (codecs decide `lossy` themselves;
  every lossy outcome is teed automatically regardless of this flag —
  see [Tee recovery flow](#tee-recovery-flow)).
- `params` is a codec-specific dict. The `columnar` codec recognizes
  `min_rows` (default `20`) and `heterogeneity_ratio` (default `1.5`).

### Resolution precedence (which manifest wins)

1. project `.parrot/compressors.toml` (relative to `ToolManager`'s working
   directory at construction time)
2. third-party package manifests — a `compressors.toml` shipped next to an
   importable package's `__init__.py`, discovered via the same
   source-precedence shape as `parrot/tools/discovery.py` (default probed
   sources: `parrot_tools`, `plugins.tools`)
3. core defaults, shipped inside `parrot/tools/compression/compressors.toml`
   (ships `[compressor."*"] codec = "json_compact" level = "minimal"` plus
   `dq_execute_database_query` → `columnar`/`normal`/`tee=true`)

The **first source** to declare a given tool-name key wins; a project or
third-party entry that shadows a core built-in logs a `warning` naming
both files.

### Match precedence (which entry applies to a given tool call)

For a given `tool_name`, checked in this order:

1. **exact** match on the tool name
2. **glob** match (`fnmatch`), longest pattern first for determinism
3. the **`"*"`** wildcard

### Effective-level precedence (highest wins)

1. a per-call override (an internal `level_override` — no public API
   surfaces this yet; reserved for a future explicit-override feature)
2. `status != "success"` → forces `NONE` — errors are never compressed by
   default
3. an exact/glob `tool_name` entry in the resolved manifest
4. the manifest's `"*"` wildcard entry
5. `MINIMAL` when nothing is configured at all (the zero-config baseline)

**Then**, regardless of which rule produced the level: a resolved
`NORMAL`/`AGGRESSIVE` is **capped down to `MINIMAL`** whenever no
`WorkingMemoryToolkit` is registered on the session — a lossy compression
with no way to recover the original is exactly what "no unrecoverable
loss" forbids. `NONE`/`MINIMAL` are lossless and are never capped.

### The kill switch

```bash
PARROT_COMPRESSION_DISABLED=1
```

When set, the pipeline is skipped entirely for every tool call — the
result returned by `ToolManager.execute_tool()` is byte-identical to what
it would have been before this feature existed.

## Tee recovery flow

Anything **lossy** (a `NORMAL`/`AGGRESSIVE` transformation that actually
dropped or factored data) is automatically persisted to the session's
`WorkingMemoryToolkit` (when one is registered) before the compressed
result is returned, and a pointer is appended to the compressed payload:

```json
{
  "columns": ["store_id", "revenue"],
  "rows": [["S0001", 1000.0]],
  "constants": {"region": "south"},
  "_tee": {
    "key": "__tee__:dq_execute_database_query:3f9a1c2e:1",
    "reason": "lossy",
    "hint": "use wm_get_result for the full payload"
  }
}
```

The agent recovers the full, pre-compression payload — **without
re-running the tool** — by calling the `wm_get_result` tool with
`include_raw=True`:

```python
recovered = await working_memory_toolkit.get_result(
    key="__tee__:dq_execute_database_query:3f9a1c2e:1",
    include_raw=True,
)
recovered["raw_data"]  # the exact original payload
```

The same tee path also captures a tool's **error** payload (status
`"error"`) before the existing `raise ValueError(result.error)` — the
error still raises identically, but the discarded `result.result` is not
lost.

**Degradation**: if no `WorkingMemoryToolkit` is registered, the tee is
unavailable and (per the effective-level precedence above) `NORMAL`/
`AGGRESSIVE` are capped to `MINIMAL` — nothing ever goes lossy without a
recovery path.

## Extending it: third-party codecs and manifests

A package can register a compressor for its own tools with **zero core
edits**: ship a `compressors.toml` next to your package's `__init__.py`
(it's discovered automatically, per the [resolution precedence](#resolution-precedence-which-manifest-wins)
above), and register a codec class via the `register_codec` decorator:

```python
from parrot.tools.compression import (
    CompressionOutcome, FilterLevel, register_codec,
)

@register_codec
class MyCodec:
    codec_name = "my_codec"

    def compress(self, result, *, level, params):
        # synchronous, deterministic, no LLM calls
        ...
        return CompressionOutcome(
            payload=..., lossy=..., bytes_before=..., bytes_after=...,
            est_tokens_saved=..., codec_name="my_codec",
        )
```

An unknown `codec` name in any manifest — yours or the project's — fails
loudly at `ToolManager` construction, never silently on first use.

## Savings report

`parrot.tools.compression.report.CompressionReport` aggregates per-tool
and per-session savings from tool-call outcomes — a functional equivalent
of `rtk gain`, without vendoring `rtk` (it's a Rust *binary*, not a
linkable library, and was never a dependency of this feature).

```python
from parrot.tools.compression.report import CompressionReport

report = CompressionReport()
report.handle(event)  # feed it lifecycle-event-shaped data per call
# ... or report.handle(event, skipped_reason="min_rows") for a skip

print(report.render())
```

`render()` always shows **milliseconds spent alongside tokens saved** — a
saving that can't be checked against its cost isn't evaluable — and
always includes the token-estimate caveat:

> token figures are bytes/4 estimates — percentages reliable, absolutes
> approximate (no tokenizer available to the pipeline)

**Percentages are reliable; absolute token counts are approximate**
(`bytes // 4`, since no tokenizer is available to the pipeline).

> **Known gap, documented rather than silently worked around**:
> `CompressionReport` is not yet wired into `ToolManager` as an automatic
> listener — there is no `ToolManager._compression_report` today. Feed it
> events yourself (e.g. from your own event-bus subscription) until a
> future task wires it in automatically.

## Optional Rust extension

The `columnar` codec has an optional Rust acceleration path
(`parrot_codec`, PyO3) that releases the GIL for the transform via
`py.detach()` (pyo3 0.29's renamed `allow_threads`). It is **entirely
optional** — the pure-Python path is the executable specification the
Rust path must match byte-for-byte, and everything works without it.

### Building it

```bash
cd packages/ai-parrot/src/parrot/codec-rs
maturin develop --release
```

This is a **separate, self-contained** maturin sub-project (own
`pyproject.toml`, own `Cargo.toml`) — mirroring the existing `yaml-rs`
extension's actual structure. It does **not** make the core `ai-parrot`
wheel depend on the Rust toolchain: `pip install ai-parrot` is entirely
unaffected. The Rust toolchain (`cargo`/`rustc`) is only needed if you
want to build this specific optional extension yourself.

### What changes when it's present vs. absent

- **Absent** (the default, nothing extra installed): `import parrot_codec`
  fails, logged **once** at `debug` for the whole process (never per
  call). Every payload — including ones over the size/row threshold —
  runs on the pure-Python path, or **passes through uncompressed** once
  over the budget-router's threshold (256 KB serialized or 1,500 rows,
  whichever is reached first, as of this feature's latency calibration —
  see [Latency budgets](#latency-budgets) below). Sending a fat payload
  beats stalling the event loop.
- **Present**: over-threshold payloads route to an executor thread with
  the GIL released for the actual transform — but **only for `bytes`/`str`
  input** (an already-JSON-serialized row array or `QueryResult`-shaped
  object). A native `list[dict]`/`dict` result — the common case for
  `DatabaseQueryToolkit`-style tools — **never crosses the FFI boundary**;
  per-row extraction under the GIL can be slower than pure Python, so
  materialized Python objects always stay on the Python path regardless
  of whether the extension is installed.

  **Routing granularity note**: `BudgetRouter.route()` decides
  INLINE/EXECUTOR/PASSTHROUGH from `rust_available` (a process-wide flag —
  is `parrot_codec` importable at all?), not from whether THIS SPECIFIC
  payload is `bytes`/`str`-eligible for the FFI path described above. So
  a native `list[dict]` payload, when the extension IS installed and the
  payload is over threshold, still gets routed to `Route.EXECUTOR` — it
  runs in a worker thread (still useful: it frees the event loop even
  though it's a real OS thread context switch, not "for free" like the
  Rust path), but the transform itself stays pure Python under the GIL
  the whole time, same as the `Route.INLINE` case just off the event
  loop. This is a real, if modest, waste of a thread-pool slot — not a
  correctness bug — and is a candidate for a future "isinstance(payload,
  (bytes, str))" refinement to `BudgetRouter.route()`'s EXECUTOR branch.

## Latency budgets

The router decides, from a cheap pre-compression size estimate, whether a
codec call runs inline, offloads to an executor (meaningful only with the
Rust extension), or passes through untouched. Defaults, calibrated
against measured pure-Python codec latency (not the design spec's
original placeholders — see the changelog entry below):

| Setting | Value |
|---|---|
| `size_threshold_bytes` | 256 KB |
| `row_threshold` | 1,500 rows |
| `minimal_budget_ms` (p99 reference) | 5.0 ms |
| `inline_budget_ms` (p99 reference) | 3.0 ms |
| `executor_budget_ms` (p99 reference) | 15.0 ms |

A codec that sustainedly busts its budget (3 consecutive rolling windows
of 100 calls / 60s, whichever is reached first) self-degrades to
passthrough for a 5-minute cooldown, then re-arms via a single probe call.
All values are configurable per `BudgetRouter`/`CircuitBreaker` instance.

## Google client truncation (last line of defense)

`GoogleGenAIClient.MAX_TOOL_RESULT_CHARS` (200,000 chars, a class
attribute — overridable per instance/subclass) is now documented and
logged as exactly what it is: a **last resort**, running on a payload
that has typically already passed through the compression pipeline. It
is still **positional** (keeps the first N elements/chars) — that
imprecision is precisely what the pipeline above exists to avoid — so it
is not "smarter" than before, just demoted. When it does fire, a
`warning` names the tool and the pre/post sizes.

## Known limitations (shipped state, not aspirational)

Documenting what actually shipped, per each behavior verified against the
merged code:

- **`clients/live.py` restores permissions/credential-broker/redaction/
  lifecycle events, but not yet compression itself.** The live voice
  route was rewired (TASK-1956) from a private `tool._execute()` call to
  the standardized `AbstractTool.execute()` — closing every protection
  gap it previously had **except** compression, because routing all the
  way through `ToolManager.execute_tool()` would have discarded
  `voice_text`/`display_data` (that method's success path only returns
  the compressed `.result` payload, not the full `ToolResult`). A tool
  called from the live voice path is therefore not yet compressed;
  restoring that would need `execute_tool()`'s return contract extended
  to expose those fields — a natural, separately-scoped follow-up.
- **`AfterToolCallEvent`'s new `compression_*` fields are not populated on
  the literal event instance a subscriber observes.** The event is
  emitted inside `AbstractTool.execute()`, strictly *before*
  `ToolManager`'s compression stage runs (`ToolManager` has no event
  emitter of its own) — so `compression_codec`, `compression_level`,
  `result_size_bytes_original`, `compression_duration_ms`, and
  `compression_teed` all default to their zero values on that specific
  event object today. The real numbers ARE available — in
  `ToolResult.metadata` (readable via `ToolManager.add_result_hook`) —
  just not yet threaded onto the event instance itself. See the
  changelog entry below for the exact field semantics that DID land.
- **The savings report has no automatic listener** — see
  [Savings report](#savings-report) above.

## See also

- [Tools documentation](../tools.md) — the general tool reference this
  page is cross-linked from (`ToolManager` section).
- `sdd/specs/tool-result-compression.spec.md` — the design spec (FEAT-380),
  authoritative for the decision trail; this page is authoritative for
  what shipped.
