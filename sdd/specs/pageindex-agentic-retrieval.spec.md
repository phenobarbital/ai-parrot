---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/pageindex-tree-optimizer.brainstorm.md; only core files are touched
tags: [pageindex, agentic-retrieval, citations, tree-optimizer, segments, evidence]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-agentic-retrieval.md]
  api_modules: [parrot.knowledge.pageindex.citations, parrot.knowledge.pageindex.read_ledger, parrot.knowledge.pageindex.agentic]
---

# Feature Specification: PageIndex Agentic Retrieval and Citations

**Feature ID**: FEAT-843
**Date**: 2026-11-08
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.2.0

> Fourth slice of `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` (revision 4). It
> consumes what FEAT-831 (`pageindex-generation-publication`) and FEAT-840
> (`pageindex-segment-store`, PR #2028) landed — pinned generations, immutable document
> revisions, `read_pages` / `read_segments` / `outline` with exact `start`/`end` offsets, and
> `frame_segments` — and adds the bounded stage-2 loop, the request-local read ledger, the
> citation model with its exact-range validator, and the evidence bundle. FEAT-842
> (`pageindex-local-mcp-toolkit`, in progress) owns the two hand-offs this spec fills in:
> the `llm_dependent_tools` set and the template's `exclude:` opt-in slot. Source paths
> below are relative to `packages/ai-parrot/src/parrot/` unless stated; line numbers were
> verified at `dev` @ `9ffbe619f0`.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Stage 1 ranks nodes; nothing reads below them on the agent's behalf and nothing is cited.
`retrieve` (`knowledge/pageindex/toolkit.py:1087`) concatenates the top-k node bodies and
returns prose with no provenance. FEAT-840 gave every imported document an immutable
revision of addressable segments and three read tools that return verbatim text with exact
half-open offsets, but:

- No call drives those tools. A host model in Claude Code can navigate with them (that is
  why the MCP template serves them), but an in-process `Agent`, a Bookstore caller or a
  `multistoresearch` origin has no bounded loop that reads pages and paragraphs and comes
  back with evidence.
- There is no citation below node level. `OKFToolkit.cite` (`knowledge/pageindex/okf/
  tools.py:255`) returns per-node provenance for a `concept_id`. There is no model for
  `{document, revision, page, paragraph, start, end, excerpt}`, no renderer for
  `[Report.pdf, p. 12 ¶3]` and no check that an excerpt is really in the text the model
  was shown.
- Read cursors (`<doc_id>@<revision>#<seq>+<offset>`) are per request budget only — the
  FEAT-840 page says so explicitly: "they are not a read ledger". Nothing records which
  character ranges of which revision a request actually received, so an excerpt from an
  unread suffix, an unread gap, or another revision cannot be told apart from a real one.
- The brainstorm fixed the mechanism — the client's own tool loop
  (`AbstractClient.ask(tools=..., use_tools=True)`, `clients/base.py:1944`) on a dedicated
  client with only the read tools — and left one fact to verify here: whether every
  provider client runs that loop to completion. Verified in §4: **they do not** (seven
  client packages have no tool execution at all), and the ones that do register per-call
  `tools=` permanently on the client's `ToolManager` and expose no caller-settable turn cap
  in `ask()`. Both facts shape the design below.

Decided in the brainstorm (all `[x]`): stage 2 lives both as read tools and as a bounded
internal loop; a citation is a reference plus a verbatim excerpt, validated; the loop runs
on the client-level tool loop with no dependency on `parrot.bots`; `start`/`end` are
computed by the validator, never requested from the model; when every citation fails the
bundle is returned with an explicit ungrounded flag; the loop is opt-in over MCP.

### Goals

1. A `ReadLedger` per request that records, for each `(doc_id, revision, seq)`, the merged
   half-open character ranges actually returned by the read tools — measured in the stored
   segment text before any whitespace normalisation. Markers, cursors and unread remainders
   never enter it. Continuations keep the same revision.
2. A `Citation` model with `doc_id, revision, seq, page, ordinal, section, start, end,
   excerpt, label, document` and a renderer producing `[Report.pdf, p. 12 ¶3]` or
   `[Notes.md, Setup > Install ¶2]`.
3. `validate_citations(ledger, revisions, proposed)` that keeps a citation only if its
   revision and segment are in the ledger, its excerpt equals a stored slice after
   whitespace normalisation, and that slice lies entirely inside the covered ranges
   (adjacent reads may jointly cover it; an unread gap may not; a match elsewhere in the
   segment does not count). The validator fills `start`/`end` from the first full match
   inside covered ranges. A missing or mismatched revision fails.
4. An `AgenticRetriever` that runs stage 1 (`search`), then the client-level tool loop on a
   dedicated client holding only the read tools, bounded by a read budget (chars and read
   count) enforced inside the tools, a maximum number of tool calls, and a wall-clock
   timeout; it returns an `EvidenceBundle`: candidates, ledger entries, kept and rejected
   citations, usage, counts, `grounded`, and optionally a drafted answer.
5. A `pageindex_agentic_retrieve` tool on `PageIndexToolkit` exposing the retriever;
   LLM-dependent; absent from the MCP template by default via the FEAT-842 `exclude:` slot.
6. Every prompt that carries document text uses `frame_segments` output and
   `DATA_FRAMING_INSTRUCTION` in the system prompt; the model is told to cite by `address`
   key (`doc@rev#seq`), which carries the revision.
7. Tests for the brainstorm's required scenarios: prefix-only read of an oversized segment
   rejects an excerpt from its suffix; adjacent continuation reads jointly cover; an unread
   gap fails; repeated excerpts resolve to the first covered occurrence; whitespace
   normalisation; a citation or continuation naming another revision fails; all-fail →
   `grounded=False`.
8. Documentation: `wiki/knowledge/pageindex-agentic-retrieval.md`, linked from
   `wiki/knowledge/pageindex.md` and `pageindex-segment-store.md`.

### Non-Goals (explicitly out of scope)

- No change to the read tools, cursors or `_read` (FEAT-840) beyond consuming their
  `ReadResult`; the ledger is filled by wrappers around them, not inside them.
- No Bookstore `agentic_retrieve` and no `multistoresearch` citations in this slice. The
  brainstorm says both "inherit the read tools and citations": they inherit the model and
  validator (importable, revision-keyed); wiring them is a follow-up recorded in §8.
- No change to `parrot.bots` and no `Agent` inside the loop (rejected in brainstorm:
  "a small `Agent` from `parrot.bots`").
- No change to any client package. Providers without a tool loop are reported, not fixed.
- No persistence of bundles or citations; they are request results.
- No MCP, template or installer change beyond adding one tool name to the FEAT-842
  `exclude:` list and `llm_dependent_tools` set.
- No answer-quality evaluation corpus (that is the optimizer slice's evaluation task).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:02a8bfdafa65b01ffb95da845b15f734a4619c39ebbd03750c2d1b83205dc130 evaluation_digest=sha256:57294153270118cbb5d0be1a36b94f6974aafdc04ea3d539cbc1fc64c3d8c665 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

```
agentic_retrieve(tree, query, …)
   │
   ├─ stage 1: self.search(tree, query, top_k)                 ← existing hybrid search
   ├─ pin: tree = self._load_tree(tree) ; generation_of(tree)   ← reader keeps this dict for the request
   ├─ ledger = ReadLedger(budget_chars, max_reads)
   ├─ tools  = ledger-wrapped read tools  (outline, read_pages, read_segments, list_documents)
   ├─ client = dedicated clone of adapter.client with a fresh ToolManager holding only `tools`
   ├─ client.ask(prompt=<task + framed candidates>, system_prompt=<DATA_FRAMING_INSTRUCTION + citing rules>,
   │             tools=tools, use_tools=True, model=…)         ← provider's own loop runs the reads
   ├─ parse AgenticAnswer from the final text (JSON block; one structured repair call on failure)
   ├─ kept, rejected = validate_citations(ledger, revisions, answer.citations)
   └─ EvidenceBundle(candidates, reads=ledger.entries(), citations=kept, rejected, answer, usage,
                     tool_calls, grounded = bool(kept) or no citation was proposed and answer=None …)
```

**Dedicated client (M3).** Verified: `AbstractClient.ask(tools=…)` registers the passed
tools on the client's own `ToolManager` for good (Anthropic `client.py:588-590` calls
`self.register_tool(tool)` per call and never removes them; `base.register_tools`
`:1484` also flips `enable_tools`). Running the loop on `self._adapter.client` would leak
the read tools into whatever else shares that client (an `Agent`'s manager, Bookstore).
The retriever therefore builds a dedicated client: `agentic_client` constructor kwarg when
given; otherwise `clone_for_tools(client)` = `copy.copy(client)` with
`_tool_manager = ToolManager(logger=…, debug=…)` (`tools/manager.py:302`), `tools = {}`
and `enable_tools = True`. The shallow copy shares credentials, the SDK client cache and
the aiohttp session; only the tool registry is new. The clone is built once per toolkit
and reused; its manager is cleared and re-registered per request (`clear_tools`
`base.py:1533` / `register_tools` `:1483`), under an `asyncio.Lock` so concurrent
`agentic_retrieve` calls on one toolkit serialize on the clone.

**Bounds (M3).** `ask()` exposes no turn cap on the non-streaming path (Anthropic loops
`while True` at `client.py:613`; the `_max_tool_rounds = 25` caps exist only on streaming
paths). So the bounds live where every provider must pass: inside the tools and around the
call. The ledger-wrapped tools refuse once `max_reads` calls or `budget_chars` returned
characters are reached, returning a short `"read budget exhausted — answer from what you
have read"` message instead of text; `asyncio.wait_for(client.ask(...), timeout_s)` bounds
the wall clock; `max_tool_calls` is enforced by the wrapper counter (a refusal still counts
as a call). A timeout yields a bundle with `stopped="timeout"` and whatever the ledger
holds, never an exception to the caller.

**Provider support (M3).** Verified table in §6: Anthropic, Google, OpenAI (via
`openai_base`), Bedrock, Gemma4, Groq, Grok and ZAI execute tools inside `ask()`; HF,
Meta, Local, vLLM, Moonshot, NVIDIA and JEV do not. The retriever cannot detect this
statically; it records `tool_calls == 0` with tools offered as `stopped="no_tool_calls"`
and `grounded=False`, and the wiki page lists the supported providers. §8 escalates
whether a capability flag should be added to `AbstractClient` (out of scope here).

**Prompting (M3).** System prompt: `DATA_FRAMING_INSTRUCTION` + the citing contract (cite
by the `address` key shown in `<segment address=…>`, excerpt verbatim, no paraphrase, JSON
answer shape). User prompt: the query, the stage-1 candidates (title, node_id, summary,
owned-segment counts from `outline`) as a framed block, and the instruction to read before
answering. The final answer is a fenced JSON object `{"answer": str | null,
"citations": [{"address": "doc@rev#seq", "excerpt": str}]}` parsed into `AgenticAnswer`;
if parsing fails, one repair call `client.ask(prompt=<the text>, structured_output=
AgenticAnswer, use_tools=False)` with no document text. `draft_answer=False` asks for
citations only (`answer` stays `None`).

**Ledger (M1).** `ReadLedger.record(result: ReadResult)` merges each `SegmentRead`'s
`[start, end)` into the entry for `(doc_id, revision, seq)`; ranges are merged when they
touch or overlap, so a prefix read and its continuation cover one interval. It also
records the first `generation` seen and the set of revisions, and exposes
`covered(key) -> list[Range]` and `entries() -> list[LedgerEntry]`. A `ReadResult` from
another revision of the same `doc_id` is recorded under its own key; it never merges.

**Validation (M2).** For a proposed `(address, excerpt)`: parse the key with the regex
behind `format_cursor` / `parse_cursor` (`segments.py:19`, without the `+offset` part) →
`(doc_id, revision, seq)`; reject `revision_unread` if the ledger has no entry; load the
revision through the store (`SegmentStore.load_revision`, `segment_store.py:64`); reject
`revision_unavailable` if gone; take `segment.text`; build a whitespace-tolerant pattern
from the normalised excerpt (`" ".join(excerpt.split())`, tokens joined by `\s+`,
`re.escape`d) and iterate matches in `segment.text`; the first match whose `[m.start(),
m.end())` is inside one covered interval is accepted and gives `start`/`end`; otherwise
reject `outside_covered_ranges` (if a match exists but is uncovered) or `excerpt_not_found`.
Empty excerpts are `empty_excerpt`. `label` comes from `SegmentAddress.label`
(`segments.py:82`), `document` from `revision.source.name`.

**Rendering (M2).** `render_citation(c) -> str` = `[<document>, <label>]`, e.g.
`[Report.pdf, p. 12 ¶3]`; `render_citations(list)` joins with `; `.

### Component Diagram

```
toolkit.agentic_retrieve ──► agentic.AgenticRetriever
                                 │  uses
         ┌───────────────────────┼─────────────────────────────┐
         ▼                       ▼                             ▼
 read_ledger.ReadLedger   citations.validate_citations   clone_for_tools(adapter.client)
   ▲ record(ReadResult)      │ needs                           │ ask(tools=…, use_tools=True)
   │                         ▼                                 ▼
 ledger-wrapped tools ◄── SegmentStore.load_revision     provider tool loop ──► wrapped tools
 (outline / read_pages / read_segments / list_documents, FEAT-840)
```

### Integration Points

| Component | How it is touched |
|---|---|
| `knowledge/pageindex/read_ledger.py` | new: `Range`, `LedgerEntry`, `ReadLedger`, `BudgetExhausted` |
| `knowledge/pageindex/citations.py` | new: `Citation`, `ProposedCitation`, `RejectedCitation`, `validate_citations`, `render_citation(s)`, `parse_address_key` |
| `knowledge/pageindex/agentic.py` | new: `AgenticAnswer`, `EvidenceBundle`, `AgenticRetriever`, `clone_for_tools`, prompt constants |
| `knowledge/pageindex/toolkit.py` | `agentic_retrieve` tool; `agentic_client`, `agentic_budget_chars`, `agentic_max_reads`, `agentic_timeout_s` kwargs; `pageindex_agentic_retrieve` added to `llm_dependent_tools` (FEAT-842) |
| `knowledge/pageindex/__init__.py` | export `Citation`, `EvidenceBundle`, `ReadLedger`, `validate_citations` |
| `mcp/_toolkit_templates/pageindex.yaml` (FEAT-842) | `exclude: [pageindex_agentic_retrieve]` |
| `wiki/knowledge/pageindex-agentic-retrieval.md`, `pageindex.md`, `pageindex-segment-store.md` | new page / links |

### Data Models

```python
Range = tuple[int, int]                                    # half-open [start, end) over stored segment text

class LedgerEntry(BaseModel):
    doc_id: str; revision: str; seq: int
    ranges: list[Range]                                    # merged, sorted
    chars: int                                             # sum of range lengths

class ProposedCitation(BaseModel):
    address: str                                           # "<doc_id>@<revision>#<seq>"
    excerpt: str

class Citation(BaseModel):
    doc_id: str; revision: str; seq: int
    page: Optional[int] = None; ordinal: int; section: Optional[list[str]] = None
    start: int; end: int                                   # validator-computed, half-open
    excerpt: str                                           # stored slice, verbatim
    label: str                                             # SegmentAddress.label
    document: str                                          # revision.source.name

class RejectedCitation(BaseModel):
    proposed: ProposedCitation
    reason: Literal["bad_address", "revision_unread", "revision_unavailable", "segment_unread",
                    "empty_excerpt", "excerpt_not_found", "outside_covered_ranges"]

class AgenticAnswer(BaseModel):
    answer: Optional[str] = None
    citations: list[ProposedCitation] = []

class EvidenceBundle(BaseModel):
    tree_name: str; query: str
    generation: Optional[int]
    candidates: list[dict[str, Any]]                       # stage-1 rows as returned by search()
    reads: list[LedgerEntry]
    citations: list[Citation]
    rejected: list[RejectedCitation]
    answer: Optional[str]
    grounded: bool                                         # at least one kept citation
    tool_calls: int; chars_read: int
    stopped: Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]
    usage: dict[str, int]                                  # from AIMessage.usage when available
    rendered_citations: str                                # "[Report.pdf, p. 12 ¶3]; [...]"
```

### New Public Interfaces

```python
await toolkit.agentic_retrieve(tree_name, query, top_k=5, draft_answer=True,
                               budget_chars=None, max_reads=None, timeout_s=None) -> dict   # EvidenceBundle.model_dump()
validate_citations(ledger, load_revision, proposed) -> tuple[list[Citation], list[RejectedCitation]]
render_citation(c) -> str ; render_citations(cs) -> str
ReadLedger(budget_chars, max_reads).record(result) / covered(doc_id, revision, seq) / entries()
clone_for_tools(client) -> AbstractClient
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: read ledger | yes | models and merge rule fixed in §2; pure Python | — |
| M2: citations + validator | yes | reasons enum, match rule, renderer fixed in §2 | — |
| M3: agentic retriever | no | — | prompt wording, parse/repair flow and clone details need judgement |
| M4: toolkit tool + hand-offs | yes | tool signature and kwargs fixed; two one-line edits in FEAT-842 files | — |
| M5: tests | no | — | fake-client tool-loop harness design |
| M6: documentation | no | — | prose |

### Module 1: Read ledger

**Files**: `knowledge/pageindex/read_ledger.py` (create)
**Interface Skeleton**:

```python
from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead   # verified: segments.py:110, :97

Range = tuple[int, int]

class BudgetExhausted(RuntimeError):
    """Raised by a ledger-wrapped read tool once the request's read budget is spent."""

class LedgerEntry(BaseModel): ...

class ReadLedger:
    def __init__(self, *, budget_chars: int, max_reads: int) -> None: ...
    def record(self, result: ReadResult) -> None:
        """Merge every ``SegmentRead.start/end`` of ``result`` into the entry of its ``(doc_id, revision, seq)``.

        Touching or overlapping ranges merge; a read from another revision is a separate entry.
        Records ``result.generation`` on first use and counts ``chars`` and ``reads``."""
    def charge(self, requested_chars: int) -> int:
        """Return the chars the next read may use; raise ``BudgetExhausted`` when ``reads >= max_reads`` or nothing is left."""
    def covered(self, doc_id: str, revision: str, seq: int) -> list[Range]: ...
    def entries(self) -> list[LedgerEntry]: ...
    @property
    def chars_read(self) -> int: ...
    @property
    def reads(self) -> int: ...
    @property
    def generation(self) -> Optional[int]: ...
```

### Module 2: Citations and the exact-range validator

**Files**: `knowledge/pageindex/citations.py` (create)
**Interface Skeleton**:

```python
from parrot.knowledge.pageindex.segments import DocumentRevision, SegmentAddress   # verified: segments.py:59, :71
from parrot.knowledge.pageindex.read_ledger import ReadLedger, Range

_ADDRESS_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)$")   # same alphabet as _CURSOR_RE, segments.py:19

def parse_address_key(key: str) -> tuple[str, str, int]:
    """``doc@rev#seq`` → ``(doc_id, revision, seq)``; ``ValueError`` on any other shape."""

def normalize_ws(text: str) -> str:
    """``" ".join(text.split())`` — the only normalisation the validator applies."""

def find_covered_match(segment_text: str, excerpt: str, covered: list[Range]) -> Optional[Range]:
    """First ``[start, end)`` in ``segment_text`` whose text equals ``excerpt`` after whitespace
    normalisation and lies inside ONE covered range (ranges are already merged, so adjacent
    reads count as one). ``None`` when no occurrence lies inside; callers distinguish
    not-found from uncovered with ``find_any_match``."""

def find_any_match(segment_text: str, excerpt: str) -> bool: ...

def validate_citations(
    ledger: ReadLedger,
    load_revision: Callable[[str, str], Optional[DocumentRevision]],
    proposed: Sequence[ProposedCitation],
) -> tuple[list[Citation], list[RejectedCitation]]:
    """Keep a citation only if its revision+segment were read and its excerpt is a covered slice.

    Order preserved; duplicates (same address+excerpt) collapse to the first. ``start``/``end`` are
    computed here, never taken from the model."""

def render_citation(c: Citation) -> str:            # "[Report.pdf, p. 12 ¶3]"
def render_citations(cs: Sequence[Citation]) -> str  # joined by "; "
```

### Module 3: Agentic retriever

**Files**: `knowledge/pageindex/agentic.py` (create)
**Interface Skeleton**:

```python
from parrot.clients.base import AbstractClient                 # verified: clients/base.py (class), ask at :1944
from parrot.tools.manager import ToolManager                   # verified: tools/manager.py:292, __init__ :302 (logger, debug)
from parrot.tools.toolkit import AbstractTool                  # verified: tools/toolkit.py (tools returned by get_tools)
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_text   # verified: framing.py:10, :39
from parrot.knowledge.pageindex.read_ledger import ReadLedger, BudgetExhausted
from parrot.knowledge.pageindex.citations import AgenticAnswer? (defined here), validate_citations, render_citations

SYSTEM_PROMPT: str      # DATA_FRAMING_INSTRUCTION + citing contract + JSON answer shape
BUDGET_MESSAGE = "read budget exhausted — answer from what you have read"

def clone_for_tools(client: AbstractClient) -> AbstractClient:
    """Shallow copy of ``client`` with a fresh ``ToolManager``, empty legacy ``tools`` and ``enable_tools=True``.

    Shares credentials, the per-loop SDK client cache and the session; isolates the tool registry."""

class AgenticRetriever:
    def __init__(self, *, client: AbstractClient, model: Optional[str], read_tools: Sequence[AbstractTool],
                 load_revision: Callable[[str, str], Optional[DocumentRevision]]) -> None: ...
    async def run(self, *, tree_name: str, query: str, candidates: list[dict[str, Any]],
                  outline: dict[str, Any], generation: Optional[int], budget_chars: int, max_reads: int,
                  max_tool_calls: int, timeout_s: float, draft_answer: bool) -> EvidenceBundle:
        """Stage 2: wrap ``read_tools`` with a fresh ``ReadLedger``, register them on the dedicated client,
        run ``client.ask(..., tools=wrapped, use_tools=True)`` under ``asyncio.wait_for``, parse the answer,
        validate citations, build the bundle. Never raises for budget, timeout or parse failures."""
    def _wrap(self, tool: AbstractTool, ledger: ReadLedger, counter: list[int], max_tool_calls: int) -> AbstractTool:
        """Return a tool with the same name/schema whose execution charges the ledger, records the
        ``ReadResult`` (read_pages / read_segments) and returns ``BUDGET_MESSAGE`` once exhausted."""
    @staticmethod
    def parse_answer(text: str) -> Optional[AgenticAnswer]:
        """First fenced or bare JSON object in ``text`` as ``AgenticAnswer``; ``None`` when absent/invalid."""
```

Prompt budget: the candidates block is `frame_text(...)`-wrapped; the `outline` of the
top candidate's subtree (`toolkit.outline`, `toolkit.py:796`) is included so the model
knows which pages/segments exist before its first read.

### Module 4: Toolkit tool and FEAT-842 hand-offs

**Files**: `knowledge/pageindex/toolkit.py`, `knowledge/pageindex/__init__.py`,
`mcp/_toolkit_templates/pageindex.yaml` (FEAT-842 file)
**Interface Skeleton**:

```python
class PageIndexToolkit(AbstractToolkit):                                  # verified: toolkit.py:63
    # FEAT-842 attribute; this spec adds one name:
    llm_dependent_tools = frozenset({..., "pageindex_agentic_retrieve"})

    def __init__(..., read_max_chars: int = 12000,                        # verified: toolkit.py:146
                 agentic_client: Optional[AbstractClient] = None,
                 agentic_budget_chars: int = 40000,
                 agentic_max_reads: int = 12,
                 agentic_max_tool_calls: int = 20,
                 agentic_timeout_s: float = 120.0, **kwargs): ...

    async def agentic_retrieve(
        self, tree_name: str, query: str, top_k: int = 5, draft_answer: bool = True,
        budget_chars: Optional[int] = None, max_reads: Optional[int] = None, timeout_s: Optional[float] = None,
    ) -> dict[str, Any]:
        """Stage-1 search, then a bounded reading loop that returns cited evidence.

        Returns an evidence bundle: candidates, the exact ranges read, validated citations
        (``[Report.pdf, p. 12 ¶3]``), rejected ones with reasons, and optionally a drafted
        answer. ``grounded`` is false when no citation survived validation. Requires an LLM."""
    def _agentic_read_tools(self) -> list[AbstractTool]:
        """The four read tools (list_documents, outline, read_pages, read_segments) from ``self.get_tools()``."""
    def _agentic_client(self) -> AbstractClient:
        """``agentic_client`` if given, else a cached ``clone_for_tools(self._adapter.client)``; ValueError with no adapter."""
```

Template hand-off (FEAT-842 `pageindex.yaml`, after it merges): `exclude:
[pageindex_agentic_retrieve]` replacing the empty slot, keeping the comment that explains
how to opt in.

### Module 5: Tests

**Files**: `tests/knowledge/pageindex/test_read_ledger.py`, `test_citations.py`,
`test_agentic_retrieval.py` (create)

The agentic tests use a fake `AbstractClient` subclass whose `ask()` imitates a provider
loop: it executes scripted tool calls through its own `tool_manager.execute_tool`
(`tools/manager.py:1799`) and returns an `AIMessage` with a scripted final text — so the
loop, budget refusals, ledger recording and validation run without a model. One test
asserts the clone's tool registry is isolated from the adapter client's.

### Module 6: Documentation

**Files**: `wiki/knowledge/pageindex-agentic-retrieval.md` (create), `wiki/knowledge/
pageindex.md` (link after the Segment Store entry, `:25`), `wiki/knowledge/pageindex-segment-store.md`
(Related link), `tests/knowledge/pageindex/test_agentic_docs.py` (create, pattern
`test_generation_docs.py`).

---

## 4. Test Specification

### Unit Tests

| Test file | Covers |
|---|---|
| `tests/knowledge/pageindex/test_read_ledger.py` | merge of touching/overlapping ranges, separate entries per revision, `charge` raising `BudgetExhausted` on reads and chars, `generation` pinned on first record, `entries()` sorted |
| `tests/knowledge/pageindex/test_citations.py` | `parse_address_key` shapes; prefix-only read rejects suffix excerpt (`outside_covered_ranges`); adjacent continuation reads jointly cover; unread gap fails; repeated excerpt → first covered occurrence; whitespace normalisation; other revision → `revision_unread`; swept revision → `revision_unavailable`; empty excerpt; duplicates collapse; renderer for paged and section-path labels |
| `tests/knowledge/pageindex/test_agentic_retrieval.py` | `clone_for_tools` isolation; wrapped tools record reads and refuse after budget; `max_tool_calls`; timeout → `stopped="timeout"`; parse failure → repair call → or `stopped="parse_error"`; all citations fail → `grounded=False`; `draft_answer=False`; no tool calls → `stopped="no_tool_calls"`; `agentic_retrieve` without adapter raises `ValueError`; name in `llm_dependent_tools` and in `list_tool_names()` |
| `tests/knowledge/pageindex/test_agentic_docs.py` | page exists, names the API and reasons, is linked |

### Integration Tests

| Scenario | Test |
|---|---|
| import a fake two-page PDF (FEAT-840 `paged_toolkit` fixture pattern, `test_read_tools.py:67`), run `agentic_retrieve` with the scripted client reading p.1 then continuing p.2, cite from both, verify kept/rejected and rendered labels | `test_agentic_retrieval.py::test_end_to_end_cited_evidence` |
| re-import changes the revision mid-request: the loop pinned the old generation; citations against the old revision are still valid within the grace period | `test_agentic_retrieval.py::test_citations_survive_reimport_within_grace` |
| existing read-tool and segment tests unchanged | `test_read_tools.py`, `test_segments.py`, `test_segment_store.py`, `test_framing.py` |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_read_ledger.py
- packages/ai-parrot/tests/knowledge/pageindex/test_citations.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py
- packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segments.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py
- packages/ai-parrot/tests/knowledge/pageindex/test_framing.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py
markers: []

### Test Data / Fixtures

- `_adapter()` and `_fake_build(pages)` / `paged_toolkit` from `tests/knowledge/pageindex/test_read_tools.py:20-75`; the `_stub_tiktoken` autouse fixture (`:33`).
- A `ScriptedToolLoopClient(AbstractClient)` fixture: `ask()` runs a list of `(tool_name, kwargs)` through `self.tool_manager.execute_tool`, then returns `AIMessage(output=<scripted text>, usage=…, tool_calls=[…])`.
- Pages with a segment longer than the test `budget_chars` to force a prefix read + cursor continuation.

---

## 5. Acceptance Criteria

- [ ] AC-1 `ReadLedger.record` merges `[0,500)` + `[500,900)` into `[0,900)`, keeps `[0,500)` + `[600,900)` separate, and files a read from another revision under its own key.
- [ ] AC-2 `charge` raises `BudgetExhausted` at `max_reads` or when `chars_read >= budget_chars`; a wrapped tool then returns `BUDGET_MESSAGE` and the bundle says `stopped="budget"`.
- [ ] AC-3 A segment of 1,200 chars read as prefix `[0,500)`: an excerpt from `[700,760)` is rejected `outside_covered_ranges`; after the continuation `[500,1200)` the same excerpt is kept with `start=700, end=760`.
- [ ] AC-4 Reads `[0,500)` and `[600,900)`: an excerpt spanning `[480,620)` is rejected; an excerpt repeated at `[100,140)` and `[550,590)` resolves to `start=100`.
- [ ] AC-5 Excerpt `"two  words\nhere"` matches stored `"two words here"`; `start`/`end` index the stored text.
- [ ] AC-6 A citation whose key names a revision not in the ledger → `revision_unread`; one whose revision file was swept → `revision_unavailable`; a malformed key → `bad_address`.
- [ ] AC-7 `render_citation` yields `[doc.pdf, p. 2 ¶1]` for paged and `[Notes.md, Setup > Install ¶2]` for section-path addresses.
- [ ] AC-8 `clone_for_tools(c)` returns an object with `tool_manager is not c.tool_manager`, `tools == {}`, `enable_tools is True`, same `model`/class; registering tools on it leaves `c.tool_manager.list_tools()` unchanged.
- [ ] AC-9 With the scripted client, `agentic_retrieve` returns a bundle whose `reads` equal the ledger, `citations` are kept/rejected per AC-3..6, `rendered_citations` is non-empty, `grounded is True`, `tool_calls` equals the scripted count and `usage` is populated.
- [ ] AC-10 All proposed citations invalid → `citations == []`, `grounded is False`, `answer` still returned, `rejected` lists every reason.
- [ ] AC-11 `timeout_s=0.01` with a slow scripted client → `stopped="timeout"`, partial `reads`, no exception; scripted client making no tool calls → `stopped="no_tool_calls"`, `grounded is False`.
- [ ] AC-12 `agentic_retrieve` on a toolkit with no adapter raises `ValueError`; `"pageindex_agentic_retrieve" in PageIndexToolkit.llm_dependent_tools` and in `list_tool_names()`.
- [ ] AC-13 The FEAT-842 template lists `pageindex_agentic_retrieve` under `exclude:`; `create_toolkit_mcp_server("pageindex", root)` from the seeded section does not serve it; removing it from `exclude:` and setting `llm:` serves it.
- [ ] AC-14 No file under `clients/`, `bots/`, `mcp/` (other than the template line) is modified.
- [ ] AC-15 Wiki page per §10 exists and is linked; `parrot sdd techwiki check --spec sdd/specs/pageindex-agentic-retrieval.spec.md --root .` passes.

---

## 6. Codebase Contract

> Verified at `dev` @ `9ffbe619f0`. Paths relative to `packages/ai-parrot/src/parrot/` unless they start with `packages/`, `tests/` or `wiki/`.

### Verified Imports

```python
from parrot.knowledge.pageindex.segments import (                     # segments.py
    Segment, SegmentAddress, SegmentRead, ReadResult, DocumentRevision,  # :33, :71, :97, :110, :59
    RevisionMismatchError, RevisionUnavailableError,                     # :123, :127
    format_cursor, parse_cursor,                                         # :282, :287 (cursor regex _CURSOR_RE :19)
)
from parrot.knowledge.pageindex.segment_store import SegmentStore     # segment_store.py:25; load_revision :64 -> Optional[DocumentRevision]
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text   # framing.py:10, :28, :39
from parrot.knowledge.pageindex.generation import generation_of       # used by toolkit._read at toolkit.py:762
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit       # toolkit.py:63
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # llm_adapter.py:43; .client/.model at :56-57
from parrot.clients.base import AbstractClient                        # clients/base.py; ask :1944; register_tools :1483; clear_tools (via tool_manager) :1533; tool_manager property :1002-1009
from parrot.tools.manager import ToolManager                          # tools/manager.py:292; __init__(logger=None, debug=False, ...) :302; register_tools :1072; execute_tool :1799; clear_tools :1444; get_tool_schemas :1316
from parrot.tools.toolkit import AbstractToolkit, AbstractTool        # tools/toolkit.py; llm_dependent_tools default :313
from parrot.models.responses import AIMessage                         # models/responses.py:94; usage :144 (CompletionUsage), tool_calls :158, stop_reason :155
from parrot.knowledge.pageindex import SegmentStore, DocumentRevision, ReadResult, Segment, SegmentAddress  # __init__.py:25-26
```

### Existing Class Signatures

```python
# knowledge/pageindex/segments.py
class SegmentAddress(BaseModel): doc_id, revision, seq, page=None, ordinal, section=None   # :71-79
    @property label -> str   # "p. 12 ¶3" | "Setup > Install ¶2"                            # :82-89
    @property key -> str     # "<doc_id>@<revision>#<seq>"                                   # :92-94
class SegmentRead(BaseModel): address, seq, kind, text, start, end, truncated=False, flags   # :97-107
class ReadResult(BaseModel): tree_name, doc_id, revision, generation=None, segments, truncated, next_cursor, framed  # :110-120
class DocumentRevision(BaseModel): doc_id, revision, source: SourceInfo, segmenter, scored_by, created_at, segments: list[Segment]  # :59-68
class SourceInfo(BaseModel): name, kind, path=None, pages=None                                # :49-56
_CURSOR_RE = r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)\+(\d+)$"                           # :19

# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                                                       # :63
    name = "pageindex"; tool_prefix = "pageindex"                                              # :124-125
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir, ..., scan_injection=True,
                 injection_probability_threshold=0.98, read_max_chars=12000, **kwargs)         # :127-148
        self._read_max_chars = max(500, int(read_max_chars))                                   # :156
        self._segment_store = SegmentStore(storage_dir)                                        # :162
    def _documents_of(self, tree) -> dict[str, dict]                                           # :679
    def _revision_for(self, tree_name, tree, doc_id, revision=None) -> DocumentRevision       # :688 (KeyError / RevisionUnavailableError)
    def _read(self, tree_name, tree, revision, seqs, *, max_chars, cursor) -> ReadResult       # :703-770 (budget clamp :714; ranges :745-748; framed :769)
    async def list_documents(self, tree_name) -> list[dict]                                    # :773
    async def outline(self, tree_name, node_id=None, max_depth=3, max_chars=6000) -> dict      # :796
    async def read_pages(self, tree_name, doc_id, pages, max_chars=12000, cursor=None) -> dict  # :855 (ReadResult.model_dump())
    async def read_segments(self, tree_name, doc_id=None, start=None, end=None, node_id=None, max_chars=12000, cursor=None) -> dict  # :874
    async def index_segments(self, tree_name, node_id=None) -> dict                            # :914
    async def search(self, tree_name, query, top_k=10, use_bm25=True, use_llm_walk=True, rerank=False, categories=None, metadata_filter=None) -> list[dict]  # :1020
    async def retrieve(self, tree_name, query, top_k=5) -> str                                 # :1087
    def _load_tree(self, tree_name) -> dict                                                    # (signature-checked cache; reader keeps the dict)

# clients/base.py
class AbstractClient:
    def __init__(self, preset=None, tools=None, use_tools=False, debug=True, tool_manager: Optional[ToolManager]=None, **kwargs)  # :455-461
        self._tool_manager = tool_manager or ToolManager(logger=self.logger, debug=self._debug)  # :531-534
    tool_manager (property + setter)                                                           # :1002-1009
    def set_tools(self, tools) / get_tool / register_tool / register_tools(tools) -> None      # :1453-1485 (register_tools sets enable_tools=True)
    async def ask(self, prompt, model=None, ..., system_prompt=None, history=None, structured_output=None,
                  tools: Optional[List[Dict]]=None, use_tools: Optional[bool]=None, ...) -> AIMessage   # :1944-1982 (abstract; providers implement)
    async def _execute_tool(self, tool_name, parameters, tool_context=None) -> Any            # :1695

# provider loops (verified by grep for tool execution inside ask(); packages/ai-parrot-client-*/src/parrot/clients/<p>/client.py)
#   run tools to completion inside ask(): anthropic (while True at :613; per-call tools registered permanently :588-590),
#     google, openai (+ openai_base.py), amazon/bedrock, gemma4, groq, grok, zai
#   NO tool execution in ask(): hf, meta, local, vllm, moonshot, nvidia, jev
#   caller-settable turn cap in ask(): none; `_max_tool_rounds = 25` exists only on streaming paths (openai_base.py:1350, bedrock.py:1627, anthropic client.py:997)

# tools/manager.py
class ToolManager(MCPToolManagerMixin): __init__(self, logger=None, debug=False, ...)        # :292, :302
    def register_tools(self, tools: List[Union[ToolDefinition, AbstractTool]]) -> None        # :1072
    def get_tool_schemas(self, provider_format=ToolFormat.GENERIC) -> List[Dict]              # :1316
    def clear_tools(self) -> None                                                              # :1444
    async def execute_tool(self, tool_name, parameters, permission_context=None, *, return_tool_result=False) -> Any  # :1799

# knowledge/pageindex/okf/tools.py
class OKFToolkit: def cite(self, concept_id: str) -> dict                                     # :255 (node-level provenance; untouched)
```

### Integration Points

- `tests/knowledge/pageindex/test_read_tools.py:20-75` — `_adapter()`, `toolkit`, `_fake_build`, `paged_toolkit`, `_stub_tiktoken` (`:33`).
- `tests/knowledge/pageindex/test_generation_docs.py` — docs-test pattern (`parents[5]`).
- `tests/knowledge/pageindex/test_toolkit.py:74-98` — tool-discovery test asserts `expected <= names` (adding a tool does not break it).
- `wiki/knowledge/pageindex.md:14` `## Table of Contents`; `:25` `- [Segment Store](pageindex-segment-store.md)`.
- `wiki/knowledge/pageindex-segment-store.md` `## Related` section (append link).
- FEAT-842 spec `sdd/specs/pageindex-local-mcp-toolkit.spec.md` §2: `llm_dependent_tools` frozenset and `exclude: []` slot in `mcp/_toolkit_templates/pageindex.yaml` (file exists only after FEAT-842 merges).

### Does NOT Exist (Anti-Hallucination)

- `knowledge/pageindex/read_ledger.py`, `citations.py`, `agentic.py` — none exists; no `ReadLedger`, `Citation`, `EvidenceBundle`, `AgenticRetriever`, `validate_citations`, `clone_for_tools` anywhere in `parrot.*`.
- `PageIndexToolkit` has no `agentic_retrieve`, `_agentic_client`, `agentic_*` kwargs; `llm_dependent_tools` is not yet declared on it (FEAT-842 adds it; on `dev` today it inherits the empty default).
- `AbstractClient` has no `clone()`, `copy_with()`, `with_tools()` or per-call tool scoping: per-call `tools=` are registered permanently (anthropic `client.py:588-590`).
- `AbstractClient.ask()` has no `max_tool_iterations` / `max_tool_rounds` parameter; the 25-round caps are local constants on streaming paths only.
- There is no capability flag telling whether a client executes tools inside `ask()`.
- `ReadResult` carries no ledger and cursors are not a ledger (FEAT-840 wiki page).
- `knowledge/contracts/carding.py:503 validate_obligation_clauses` is a node-body verbatim check; it is not reused (different normalisation and no ranges).
- `mcp/_toolkit_templates/pageindex.yaml` does not exist on `dev` yet (FEAT-842).
- `wiki/knowledge/pageindex-agentic-retrieval.md` and the three test files do not exist.

### Edit Sites (Blueprint Anchors)

Base commit: `dev` @ `9ffbe619f0`. Counts from `grep -cF '<anchor>' <path>`.

| File | Anchor (verbatim) | path:NN | count | Change |
|---|---|---|---|---|
| `knowledge/pageindex/read_ledger.py` | — | create | — | M1 |
| `knowledge/pageindex/citations.py` | — | create | — | M2 |
| `knowledge/pageindex/agentic.py` | — | create | — | M3 |
| `knowledge/pageindex/toolkit.py` | `    tool_prefix = "pageindex"` | :125 | 1 | after (FEAT-842 attribute lands here): add `"pageindex_agentic_retrieve"` to `llm_dependent_tools` |
| `knowledge/pageindex/toolkit.py` | `        read_max_chars: int = 12000,` | :146 | 1 | after: `agentic_client`, `agentic_budget_chars`, `agentic_max_reads`, `agentic_max_tool_calls`, `agentic_timeout_s` |
| `knowledge/pageindex/toolkit.py` | `        self._read_max_chars = max(500, int(read_max_chars))` | :156 | 1 | after: store the agentic settings; `self._agentic_clone = None`, `self._agentic_lock = asyncio.Lock()` |
| `knowledge/pageindex/toolkit.py` | `    async def index_segments(self, tree_name: str, node_id: Optional[str] = None) -> dict[str, Any]:` | :914 | 1 | before: `agentic_retrieve`, `_agentic_read_tools`, `_agentic_client` |
| `knowledge/pageindex/__init__.py` | `from .segment_store import SegmentStore` | :26 | 1 | after: imports from `citations`, `read_ledger`, `agentic`; extend `__all__` |
| `mcp/_toolkit_templates/pageindex.yaml` (FEAT-842) | `    exclude: []` | — | — | replace: `    exclude: [pageindex_agentic_retrieve]` (verify after FEAT-842 merges) |
| `wiki/knowledge/pageindex.md` | `- [Segment Store](pageindex-segment-store.md)` | :25 | 1 | after: link to the new page |
| `wiki/knowledge/pageindex-agentic-retrieval.md` | — | create | — | §10 |

FEAT-842 edits `toolkit.py:127-170` (constructor) and `:1020-1125` (`search`/`retrieve`);
the anchors above sit outside its hunks except `:146`/`:156`, which it keeps verbatim
(it adds parameters after `lock_timeout_s` / `self._use_embedding_walk`). Re-verify
counts after it merges.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Offsets are over the **stored** `segment.text`; `SegmentRead.start/end` already are
  (`toolkit.py:745-748`). Normalise only for comparison, never for indexing.
- Merge ledger ranges on record, not on query, so `covered()` is a sorted disjoint list and
  "adjacent reads jointly cover" is a containment test against one interval.
- The ledger is filled by tool wrappers, which see the `ReadResult` dict the tool returns
  (`result.model_dump()`); re-validate it with `ReadResult.model_validate` before recording.
- Register the wrapped tools on the **clone** only; never call `register_tools` on
  `self._adapter.client`.
- Everything the model sees from documents goes through `frame_segments`/`frame_text`
  (`framing.py`), and `DATA_FRAMING_INSTRUCTION` leads the system prompt.
- `AIMessage.usage` is a `CompletionUsage` (`responses.py:144`); copy its dict into the
  bundle, default `{}` when the fake client omits it.
- Tests reuse `_stub_tiktoken` (`test_read_tools.py:33`) — `thin_tree` gates on tokens.
- Docs tests follow `test_generation_docs.py` (`parents[5]` = repo root).

### Known Risks / Gotchas

- **Providers without a tool loop** (hf, meta, local, vllm, moonshot, nvidia, jev): the
  bundle comes back `stopped="no_tool_calls"`, `grounded=False`. Documented; capability
  flag escalated in §8.
- **No turn cap in `ask()`**: a provider loop that keeps calling tools after the budget is
  spent gets `BUDGET_MESSAGE` every time; `max_tool_calls` makes the wrapper raise
  `BudgetExhausted` past that point so the client's own error handling ends the loop, and
  `timeout_s` is the last resort.
- **Shallow clone shares `_clients_by_loop`**: intended (same SDK client), but a provider
  that stores per-instance request state outside the tool manager could interleave; the
  per-toolkit lock serializes agentic calls on one clone.
- **Segment larger than a read budget**: returned truncated with a cursor (FEAT-840);
  only the returned prefix enters the ledger — the brainstorm's "markers and unread
  remainders are not citable evidence".
- **Re-import during a request**: the reader keeps its tree dict and its revision; a
  citation to the old revision validates until the grace sweep removes the file, then
  `revision_unavailable`.
- **Models mis-copy addresses**: `bad_address` is a rejection reason, not an exception; the
  system prompt shows the exact key format and tells the model to copy it from the
  `<segment address=…>` tag.
- **Parse/repair**: the repair call carries only the model's own text, never document text,
  so it cannot be used to launder an injection; if it also fails → `stopped="parse_error"`.
- **FEAT-842 ordering**: the `llm_dependent_tools` and template edits assume FEAT-842 has
  merged; until then the attribute does not exist and the template file is absent. The
  tasks touching them must verify and stop if not.

### External Dependencies

None added.

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-agentic-retrieval
entries:
  - id: citations-are-ledger-validated-exact-ranges
    statement: A citation is kept only when its revision and segment appear in the request's read ledger and its excerpt equals, after whitespace normalisation, a stored slice that lies entirely inside the character ranges the read tools actually returned; start and end are computed by the validator from that match, never supplied by the model.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py"]
    contradicts: []
    supersedes: []
    rationale: Models do not count characters reliably and will quote text they were never shown; the only evidence that survives is text a reader can re-check against an immutable revision at a known offset.
    rejected_alternatives: ["Trust model-supplied offsets", "Accept any occurrence in the segment", "Node-level citations only (OKFToolkit.cite)"]
  - id: stage2-runs-on-client-tool-loop-with-isolated-registry
    statement: The agentic stage runs through AbstractClient.ask(tools=..., use_tools=True) on a dedicated client clone with its own ToolManager holding only the ledger-wrapped read tools, with no dependency on parrot.bots; bounds (read budget, max tool calls, wall clock) are enforced inside the tools and around the call because the clients expose no turn cap and register per-call tools permanently.
    relation: constrains
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "file:packages/ai-parrot/src/parrot/clients/base.py"]
    contradicts: []
    supersedes: []
    rationale: Reuses each provider's native tool handling without a second agent runtime, while keeping the host toolkit's client registry untouched and the loop bounded regardless of provider.
    rejected_alternatives: ["A small Agent from parrot.bots", "Running the loop on the adapter's shared client", "A hand-rolled per-provider tool loop"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:02a8bfdafa65b01ffb95da845b15f734a4619c39ebbd03750c2d1b83205dc130 evaluation_digest=sha256:57294153270118cbb5d0be1a36b94f6974aafdc04ea3d539cbc1fc64c3d8c665 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: agentic-retrieval, citations, evidence, segments, tree-optimizer
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "agentic-retrieval",
      "citations",
      "evidence",
      "segments",
      "tree-optimizer"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:57294153270118cbb5d0be1a36b94f6974aafdc04ea3d539cbc1fc64c3d8c665",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:02a8bfdafa65b01ffb95da845b15f734a4619c39ebbd03750c2d1b83205dc130",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:84f706a633472d197129a4ef3871dc023a4f74296eaa3b9ba3ad7d07dedef051",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Where stage 2 lives — *Resolved in brainstorm*: both read tools on the toolkit and a bounded internal loop.
- [x] Citation guarantee — *Resolved in brainstorm*: reference plus verbatim excerpt, validated.
- [x] How the internal loop runs tools — *Resolved in brainstorm*: the client-level tool loop. Checked: `ask` accepts `tools`/`use_tools` and each client owns a `ToolManager`. Still to verify in the spec: that every provider client runs the loop to completion. → **Verified here: not every provider does** (see §6 provider table); the design keeps the client-level loop and reports unsupported providers in the bundle.
- [x] Is the internal agentic loop exposed over MCP — *Resolved in brainstorm*: not by default; it is opt-in (FEAT-842 `exclude:` slot).
- [x] Old revisions after a re-import — *Resolved in brainstorm*: only the latest; the previous one is kept for the grace period, then removed; a citation to it is reported as "revision unavailable".
- [x] How the dedicated client is obtained — *Resolved in this spec*: `agentic_client` kwarg, else a shallow clone with a fresh `ToolManager`.
- [x] How bounds are enforced without a client turn cap — *Resolved in this spec*: ledger-side refusals (`max_reads`, `budget_chars`, `max_tool_calls`) plus `asyncio.wait_for`.
- [ ] Should `AbstractClient` gain a capability flag (e.g. `supports_tool_loop`) so callers can fail fast on hf/meta/local/vllm/moonshot/nvidia/jev instead of reading `stopped="no_tool_calls"`? — *Owner: Jesus Lara*; touches `clients/base.py`, out of this slice.
- [ ] Bookstore `agentic_retrieve` and `multistoresearch` citations (brainstorm: "inherit the read tools and citations") — follow-up slice or FEAT-840-style Bookstore task? — *Owner: Jesus Lara*.
- [ ] Default budgets (`agentic_budget_chars=40000`, `agentic_max_reads=12`, `agentic_max_tool_calls=20`, `agentic_timeout_s=120`) are provisional; tune with the optimizer's evaluation task over Bookstore books. — *Owner: Jesus Lara*.
- [ ] Should the final answer use `structured_output=` on the tool-loop call itself where the provider supports both at once, instead of JSON-in-text plus a repair call? — *Owner: implementer*; decide per provider evidence during M3.

---

## 9. Design Research Cross-Check

Status: skipped (exploration doc `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` is `**Status**: exploration`, not `accepted`; `codex` is installed)

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/pageindex-agentic-retrieval.md` — create: what stage 2 does, the ledger and why cursors are not one, the citation contract and every rejection reason, the bundle fields and `stopped` values, budgets, the dedicated client and the provider support table, opt-in over MCP, examples.
  - `wiki/knowledge/pageindex.md` — update: link after the Segment Store entry.
  - `wiki/knowledge/pageindex-segment-store.md` — update: Related link.
- **API modules**:
  - `parrot.knowledge.pageindex.citations`, `parrot.knowledge.pageindex.read_ledger`, `parrot.knowledge.pageindex.agentic`; `PageIndexToolkit.agentic_retrieve` docstring.

---

## Revision History

| Rev | Date | Summary |
|---|---|---|
| 0.1 | 2026-11-08 | Initial spec from brainstorm revision 4 (slice 4). Provider tool-loop support verified; anchors at `dev` @ `9ffbe619f0`. |
