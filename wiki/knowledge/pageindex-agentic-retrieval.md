---
title: PageIndex Agentic Retrieval and Citations
summary: Bounded stage-2 reading loop over pinned PageIndex segments that returns ledger-validated, exact-range citations.
---

# PageIndex Agentic Retrieval and Citations

## Purpose

PageIndex answers a question in two stages. **Stage 1** is the tree search (`search`, `retrieve`): it ranks
nodes and returns their bodies as prose with no provenance. **Stage 2** is `agentic_retrieve`: it runs the same
stage-1 search, then lets a model read the matching document text through the segment read tools, inside hard
budgets, and returns **citations** that name an exact character range of a segment the request actually received.

Use `retrieve` when a host model navigates the tree itself, or when prose context is enough. Use
`agentic_retrieve` when the caller needs evidence it can quote and check: an in-process agent, a Bookstore caller
or a local MCP host that wants `[Report.pdf, p. 12 ¶3]` style references. Every citation is validated against the
ledger of what was read, so an excerpt from an unread suffix, an unread gap, or another revision is rejected
rather than returned.

The loop reuses the client's own tool loop (`AbstractClient.ask(tools=…, use_tools=True)`) on a dedicated client
clone, so no provider SDK is called directly and `parrot.bots` is not involved. It runs only where the provider
executes tools inside `ask()` (see [Provider support](#provider-support)).

## Public API

- [`PageIndexToolkit.agentic_retrieve`](ref:parrot.knowledge.pageindex.toolkit) — stage-1 search plus the bounded reading loop; returns the evidence bundle as a dict
- [`AgenticRetriever`](ref:parrot.knowledge.pageindex.agentic) — runs the supervised loop for one request; `AgenticRetriever.run` owns the deadline, the call cap and the validation step
- [`EvidenceBundle`](ref:parrot.knowledge.pageindex.agentic) — the request result: candidates, ledger entries, kept and rejected citations, answer, counts, `stopped`
- [`AgenticAnswer`](ref:parrot.knowledge.pageindex.agentic) — the structured final answer the model proposes (`answer`, `citations`)
- [`clone_for_tools`](ref:parrot.knowledge.pageindex.agentic) — shallow clone of a client with an isolated tool registry
- [`clip_read_result`](ref:parrot.knowledge.pageindex.agentic) — cuts a `ReadResult` to the granted number of stored-text characters
- [`ReadLedger`](ref:parrot.knowledge.pageindex.read_ledger) — per-request record of the character ranges returned to the model; `charge`, `record`, `covered`, `entries`
- [`LedgerEntry`](ref:parrot.knowledge.pageindex.read_ledger) — merged coverage of one segment of one revision (`doc_id`, `revision`, `seq`, `ranges`, `chars`)
- [`BudgetExhausted`](ref:parrot.knowledge.pageindex.read_ledger) — internal read-budget signal, caught by the read wrapper
- [`Citation`](ref:parrot.knowledge.pageindex.citations) — a validated citation with computed `start`/`end` and the stored `excerpt`
- [`ProposedCitation`](ref:parrot.knowledge.pageindex.citations) — what the model proposes: an `address` and an `excerpt`
- [`RejectedCitation`](ref:parrot.knowledge.pageindex.citations) — a proposal that failed validation, with its `reason`
- [`validate_citations`](ref:parrot.knowledge.pageindex.citations) — the validation ladder over a ledger
- [`render_citation`](ref:parrot.knowledge.pageindex.citations) / [`render_citations`](ref:parrot.knowledge.pageindex.citations) — `[Document, label]` rendering, joined by `; `
- [`parse_address_key`](ref:parrot.knowledge.pageindex.citations) — parses `doc@rev#seq` into its parts

The four read tools the loop uses are private, snapshot-bound copies of the public read tools. They are exposed to
the model under the usual names: `pageindex_list_documents`, `pageindex_outline`, `pageindex_read_pages` and
`pageindex_read_segments`. Only the last two read text; the first two count toward the call cap but not toward the
character budget.

Not available in this release: a Bookstore `agentic_retrieve` and citations for `multistoresearch` origins. Both
are follow-ups; they inherit the model and validator, which are keyed by revision, but nothing wires them yet.

## Configuration & Parameters

The loop is configured on the `PageIndexToolkit` constructor. Per-call overrides are arguments of `agentic_retrieve`.
Requires a model: without `llm_client` or `adapter` there is no client to clone, and `agentic_retrieve` raises
`ValueError` unless `agentic_client` is given.

| Constructor kwarg | Default | Effect | Per-call override |
|---|---:|---|---|
| `agentic_budget_chars` | `40000` | Stored-text characters the reads may deliver to the model per request. | `budget_chars` |
| `agentic_max_reads` | `12` | Read results (`read_pages` / `read_segments` replies) recorded per request. | `max_reads` |
| `agentic_max_tool_calls` | `20` | Tool invocations admitted per request across all four tools, refusals included. | none |
| `agentic_timeout_s` | `120.0` | One wall-clock deadline per request, shared by every phase. | `timeout_s` |
| `agentic_client` | `None` | A dedicated client used as-is for the loop (see below). | none |
| `model` | adapter model | Model id for the loop and for the repair call. | none |

Per-call arguments: `top_k` (stage-1 candidates, default `5`), `draft_answer` (default `True`; when `False` the model
returns citations only and `answer` is `null`). Positive values are required; `ValueError` otherwise.

Budgets are provisional. The defaults above are the starting point chosen in the spec; they are to be tuned against
Bookstore evaluation and may change.

### Snapshot pinning

Each request pins a private deep copy of the tree **before** stage 1. Stage 1 searches that copy, and the four read
tools resolve documents, nodes, outlines and segment selections from it. They load only the revisions the pinned tree
names. A re-import during the request does not switch the request to a new revision; cursors and addresses keep naming
the revision they were issued for. The bundle's `generation` is the pinned generation. A tool call naming a different
tree than the one the request was started for is rejected with `ValueError`.

Old revisions stay readable for the grace period described in [Segment Store](pageindex-segment-store.md). After it,
a revision the request read but can no longer load is rejected as `revision_unavailable`.

### The dedicated client

The loop never registers tools on the toolkit's shared client. Two cases:

- **`agentic_client` given.** That client is used as-is. Its tool registry is cleared and re-registered for every
  request, so pass a client that serves nothing else.
- **Not given.** The first request builds `clone_for_tools(adapter.client)` and caches it on the toolkit. The clone
  is a shallow `copy.copy`: credentials, the SDK client cache and the HTTP session are shared with the original; the
  tool registry (`ToolManager`) is new and empty; `enable_tools` is `True`. Concurrent `agentic_retrieve` calls on
  one toolkit serialize on the toolkit's agentic lock.

### Opt-in over MCP

The `pageindex_agentic_retrieve` tool is LLM-dependent (it is in `PageIndexToolkit.llm_dependent_tools`), so a
section without `llm:` never serves it. The shipped MCP template also lists it in `exclude:`, so a section with
`llm:` does not serve it until you remove it from that list. Opt in with:

```yaml
toolkits:
  pageindex:
    class: parrot.knowledge.pageindex.toolkit.PageIndexToolkit
    kwargs:
      storage_dir: .parrot/pageindex
      max_result_chars: 24000
      agentic_budget_chars: 40000
      agentic_max_reads: 12
      agentic_max_tool_calls: 20
      agentic_timeout_s: 120.0
    llm: anthropic:claude-haiku-5-5
    llm_kwargs: {}
    exclude: []
    env: {}
```

The budget keys are constructor kwargs and may be left out to use the defaults. The section is validated by
`parrot.mcp.toolkit_config.ToolkitSection`, which rejects non-empty `llm_kwargs` when `llm` is not set. See
[PageIndex Local MCP](pageindex-local-mcp.md) for the `exclude:` slot.

### Read budget and clipping

The read tools accept `max_chars`; when the model omits it, the wrapper requests 12000 characters. The grant for a
call is `min(requested, budget remaining)`. A grant below 500 is still honoured: `_read` is asked for 500 characters
and the result is clipped to the grant before anything is recorded or returned. A budget of `100` therefore delivers at
most 100 characters in total. A clipped segment keeps its `start`, its `end` shortens, and its `truncated` flag is set;
the result's `next_cursor` points at the first omitted character. Zero remaining budget refuses the read without
reading. Metadata-only calls do not spend characters.

## Usage Examples

```python
from parrot.clients.factory import LLMFactory
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

client = LLMFactory.create("anthropic:claude-haiku-5-5")
toolkit = PageIndexToolkit(
    storage_dir=".parrot/pageindex",
    llm_client=client,
    agentic_budget_chars=20000,
    agentic_max_reads=8,
    agentic_timeout_s=60,
)

bundle = await toolkit.agentic_retrieve("handbook", "What is the refund window?", top_k=5)

if bundle["grounded"]:
    print(bundle["answer"])
    print(bundle["rendered_citations"])  # e.g. [Handbook.pdf, p. 12 ¶3]; [Handbook.pdf, p. 13 ¶1]
    for citation in bundle["citations"]:
        print(citation["label"], citation["start"], citation["end"], citation["excerpt"])
else:
    print("no citation survived:", bundle["stopped"])
    for rejected in bundle["rejected"]:
        print(rejected["reason"], rejected["proposed"]["address"])
```

`bundle["citations"]` holds validated citations in model order; `rendered_citations` is the same list rendered
with `render_citations`. `bundle["reads"]` lists the ledger entries (what was actually read), which is the first thing
to inspect when a citation is missing.

Read the citation's own `excerpt` field, not the text the model proposed: validation replaces it with the stored
slice, so the returned excerpt is always verbatim.

## Gotchas

### Provider support

The loop needs a client whose text `ask()` executes tool calls. Clients declare it with the class attribute
`AbstractClient.supports_tool_loop` (text `ask()` only — it makes no claim about `ask_stream()` or about inline
`ask(tools=...)` registration).

| Text `ask()` runs the tool loop | Declares `supports_tool_loop = False` |
|---|---|
| every installed provider, except the three on the right; `OpenAICodexClient` and `ClaudeAgentClient` run it through their agent bridges, using tools registered in `client.tool_manager` | `hf` / `transformers` (`TransformersClient`), `jev` / `typesafe` (`JevClient`), `gemini-live` (`GeminiLiveClient`) |

The retriever calls `require_tool_loop(client)` before candidate search. If the client declares
`supports_tool_loop = False`, it raises `ValueError` with the message:
`"agentic retrieval requires a client that executes tool calls inside ask(); <Class> (<client_type>) declares supports_tool_loop=False"`.
When the model runs without making any tool call, `stopped="no_tool_calls"` now means a capable client whose model
simply chose not to call any tools — it is no longer a proxy for "unsupported provider".

### Ledger versus cursors

A cursor (`<doc_id>@<revision>#<seq>+<offset>`) is a promise about where the next read starts. It says nothing about
what the model has seen, and it does not limit what a citation may name. The ledger is the record of what was actually
delivered: after clipping, each read's ranges are merged per `(doc_id, revision, seq)`. Markers, `framed` wrapper
text, cursors and unread remainders never enter it. A citation is valid only inside those ranges, so two adjacent
continuation reads may jointly cover an excerpt, while an unread gap or a suffix that was never returned may not.
Repeated reads count against the character budget again, even when the ranges they cover are already merged.

### The citation contract

The model proposes `{"address": "doc@rev#seq", "excerpt": "..."}`. `address` is the `address` attribute of a
`<segment>` tag shown in the prompt; it carries the revision, so a revision the request never read cannot be cited.
`validate_citations` runs these checks in order. The first failing check sets the reason:

| Reason | Meaning |
|---|---|
| `bad_address` | The address is not `doc@rev#seq` (16 hex characters for the revision, digits for `seq`). |
| `empty_excerpt` | The excerpt is empty after whitespace normalisation. |
| `revision_unread` | No segment of that document revision was returned to the model. |
| `revision_unavailable` | The revision was read earlier but can no longer be loaded (it was swept after the grace period). |
| `segment_unread` | The sequence number is out of range for the revision, or no range of that segment was returned. |
| `excerpt_not_found` | The excerpt does not occur in the stored segment text. |
| `outside_covered_ranges` | The excerpt occurs in the segment, but not entirely inside a range that was returned. |

Excerpts match after whitespace normalisation: any run of whitespace in the stored text matches a single space in the
excerpt. The first match fully inside a covered range is used; a match elsewhere in the segment does not count.
`start` and `end` are half-open offsets into the stored text, computed by the validator. A proposal that repeats an
already-seen address and excerpt is dropped silently and does not appear in `rejected`.

`grounded` is `True` only when at least one citation survived. A bundle can be `stopped="answered"` and still be
ungrounded; treat `grounded` as the signal to show citations, and `answer` as unverified text when it is not.

### `stopped` values and precedence

`stopped` is always set. When several conditions hold, the first one in this list wins:

1. `timeout` — the single request deadline expired in any phase: lock wait, stage-1 search, outline, the tool loop,
   the repair call or citation validation. The answer and citations are cleared; completed reads remain in `reads`.
   Repair does not start after expiry.
2. `max_tool_calls` — the call cap was reached. The provider task is cancelled and awaited, there is no repair call and
   no answer; the reads already recorded remain. Refused calls count toward the cap.
3. `provider_error` — the provider call raised. The exception is logged and **not** re-raised: there is no answer,
   no repair call and no citation validation, while the reads already charged against the budget remain in `reads`
   and `chars_read`. `asyncio.CancelledError` is never converted — an external cancellation still propagates.
4. `parse_error` — the final output, after one repair call, is not an `AgenticAnswer`. No answer, no citations.
5. `budget` — the model answered, but at least one read was refused because the character or read budget ran out. The
   answer is still validated and kept.
6. `no_tool_calls` — the model answered without admitting any tool call. Every citation is then `revision_unread`,
   so `grounded` is `False`. This is also what an unsupported provider produces.
7. `answered` — the normal case.

Some exceptions still propagate: an external cancellation of the caller is re-raised after cleanup rather than
returned as a bundle, and `ValueError` is raised for invalid arguments or a missing LLM. A failure of the provider
call itself does **not** propagate — it comes back as `stopped="provider_error"` (item 3 above).

### Other behaviour to know

- **Ordinary tool errors do not stop the loop.** A provider that catches tool exceptions and keeps asking is cut off by
  the call cap, not by the error. A budget refusal is a normal tool result (a short message), not an exception.
- **The repair call is the only extra model call.** It runs only when the first output does not parse, uses the same
  client without tools, and uses only the remaining deadline.
- **Read tools never serve a different tree.** A tool call naming another tree fails with `ValueError`; the provider
  receives that as a tool error.
- **Metadata calls count.** `list_documents` and `outline` spend a tool call (and so count toward `max_tool_calls`)
  but spend no characters.
- **No persistence.** Bundles and citations are request results; nothing is written to storage.
- **Cap-fill ends the loop immediately.** The controller stops the request as soon as the last admitted tool call
  completes, so a model that uses *exactly* `max_tool_calls` reads returns `stopped="max_tool_calls"` with no answer.
  Size `agentic_max_tool_calls` one above the read count you expect.
- **A provider-done / stop tie resolves to `max_tool_calls`.** When the provider finishes in the same tick the cap is
  reached, `asyncio.wait` reports both and the stop branch wins — a completed answer is discarded. Same remedy: leave
  one call of headroom.
- **One agentic request at a time per toolkit.** A single `_agentic_lock` guards the whole request, so a second
  concurrent caller waits for it and, if its own `timeout_s` expires first, gets a `stopped="timeout"` bundle with no
  candidates. Scale out with separate `PageIndexToolkit` instances, not with concurrent calls on one.
- **A byte-identical re-import is a no-op.** Importing the same source twice into one tree splices nothing and mints
  no generation: the call returns the existing `doc_id` and `revision` with `reused: true` and an empty
  `new_node_ids`. Changed bytes under the same name still get their own suffixed `doc_id`, and an explicit `doc_id=`
  always splices.

## Related

- [PageIndex — Tree-Based RAG for Document Retrieval](pageindex.md) — tree construction and stage-1 retrieval
- [PageIndex Segment Store](pageindex-segment-store.md) — revisions, addresses, the read tools and cursors this builds on
- [PageIndex Local MCP](pageindex-local-mcp.md) — the `exclude:` opt-in slot and the MCP template
- [Bookstore Agentic Retrieval](bookstore-agentic-retrieval.md) — per-book cited retrieval, multi-origin excerpts, safe re-indexing and measured budgets
