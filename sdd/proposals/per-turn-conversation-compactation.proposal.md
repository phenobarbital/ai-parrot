# Per-Turn Compaction — Deterministic Stages (Design Concept)

**Status:** Accepted — open questions resolved (2026-09-03), ready to implement
**Scope:** Stages 0 (normalization), 0.5 (token accounting & budgeting), 1 (deterministic pruning + omission store).
**Out of scope:** Stage 2 (LLM summary-turn). This doc only defines the hook points Stage 2 will need.
**Reference:** [aerovato/magic-compact](https://github.com/aerovato/magic-compact) (`packages/opencode-plugin/src/compact/`) — per-turn compaction plugin for OpenCode. We borrow its two-layer split (deterministic pruning vs. LLM summaries), its omission-cache idea, and its "keep user messages verbatim, prune tool I/O by rule" decision. We deliberately do **not** borrow its sequential omission IDs, its regex XML parsing, or its mutate-in-place message editing.

## 1. Context and goals

`parrot.memory` is already turn-centric: `ConversationTurn` (user_message, assistant_response, context_used, tools_used) inside `ConversationHistory`, persisted by `InMemoryConversation` / `RedisConversation`. Today the history grows unbounded and `get_messages_for_api()` renders every turn verbatim; the only relief valve is `get_recent_turns(count)`, which is lossy truncation.

Goals of the deterministic plane:

1. **Canonical storage** — every turn is stored already normalized (whitespace, JSON, control chars). Normalization happens once, at write time, and is idempotent.
2. **Token-aware budgeting** — every turn carries a BPE token estimate computed at write time, so "does this conversation fit the window?" is an O(n) sum over integers, not a re-tokenization of the transcript.
3. **Lossless, rule-based pruning** — old turns shrink by per-tool rules with fixed thresholds; omitted content goes to an omission store and is retrievable on demand via a tool. No LLM involved; every transformation is a pure function, testable with fixtures.
4. **Errors are first-class** — tool failures and turn-level errors are captured in the turn model and survive pruning in condensed form (an agent that forgets its own failures repeats them).

Everything in this doc is deterministic: same history + same config ⇒ same bytes rendered.

## 2. Data model changes

### 2.1 `ToolInvocation` (new)

`tools_used: List[str]` only records tool *names*, which gives Stage 1 nothing to prune and loses failure information. Replace-by-augmentation: keep `tools_used` (derived, for backward compat) and add structured invocations.

```python
class ToolStatus(str, Enum):
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]                  # stored normalized (§3)
    output: Optional[str] = None           # stored normalized
    status: ToolStatus = ToolStatus.COMPLETED
    error: Optional[str] = None            # error message / condensed traceback
    elapsed_ms: Optional[int] = None
    omitted: Dict[str, str] = field(default_factory=dict)
    # field name ("output", "input.content", ...) -> omission content_id (§5)
```

### 2.2 `ConversationTurn` (extended)

```python
class TurnState(str, Enum):
    RAW = "raw"            # normalized, full fidelity
    PRUNED = "pruned"      # Stage 1 applied
    SUMMARIZED = "summarized"  # reserved for Stage 2

@dataclass
class ConversationTurn:
    # existing fields unchanged ...
    tool_invocations: List[ToolInvocation] = field(default_factory=list)
    error: Optional[str] = None            # turn-level failure (client error, retry exhaustion)
    token_count: Optional[TokenCount] = None   # §4
    state: TurnState = TurnState.RAW
    schema_version: int = 2
    norm_version: int = 1                  # normalization ruleset applied (§3)
```

`tools_used` becomes a property: `[ti.tool_name for ti in self.tool_invocations]`, still serialized for old readers. `from_dict` accepts v1 payloads (missing fields default), so existing Redis histories deserialize unchanged; they are upgraded lazily on the next `update_history`.

### 2.3 `ConversationHistory` (extended metadata, no new fields)

Reserved keys in `metadata`:

- `compaction`: `{ "last_pruned_turn_id": str | None, "tokenizer": "o200k_base", "calibration": float }` (§4.3).

## 3. Stage 0 — Normalization at write time

Applied inside `add_turn()` (in the abstract layer, so every backend inherits it), before serialization. A pure function `normalize_turn(turn, ruleset=1) -> turn`.

Rules (v1), applied to `user_message`, `assistant_response`, `context_used`, `ToolInvocation.output`/`error`, and string leaves of `ToolInvocation.input`:

1. **Unicode NFC** normalization.
2. **Strip control/ANSI**: remove ANSI escape sequences (CSI/OSC) and C0 controls except `\n` and `\t`. Tool output from CLIs (rich, pytest, git) is the main win here.
3. **Line-level whitespace**: strip trailing whitespace per line; collapse runs of ≥3 blank lines to 2. Do **not** collapse intra-line spaces or touch tabs — that corrupts code, diffs, and aligned tables. (Cheap, safe subset; aggressive collapsing is where "deterministic" quietly becomes "lossy".)
4. **JSON compaction**: if a string field parses as JSON (or the field is already a dict, as `ToolInvocation.input` is), re-serialize canonical: `orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)` — no indent, sorted keys, UTF-8. This also removes a class of Redis round-trip inconsistencies: one canonical form regardless of which encoder produced it.
5. **Traceback condensation** (errors only): a Python traceback longer than 30 lines keeps the first 5 lines + last 10 (the raising frames and the exception) with a `… N frames elided …` marker. The exception type+message is always intact.

Properties: idempotent (`normalize(normalize(x)) == normalize(x)` — enforced by a property test), versioned via `norm_version` so a future ruleset v2 can re-normalize old turns explicitly instead of silently mixing rules.

Stage 0 runs before the turn is ever sent to a model, so it can never invalidate a provider prompt cache.

## 4. Stage 0.5 — Token accounting & budgeting

### 4.1 Counting

```python
@dataclass
class TokenCount:
    user: int
    assistant: int
    tools: int          # sum over invocations (input + output + error)
    total: int
    tokenizer: str      # e.g. "o200k_base"

class TokenCounter(Protocol):
    name: str
    def count(self, text: str) -> int: ...
```

Default implementation: `tiktoken` with `o200k_base` (fast Rust core, no model download). Optional: HF `tokenizers` for teams that want a specific local tokenizer. The counter is a constructor argument of the memory backend; the name is recorded in both `TokenCount.tokenizer` and history metadata, so mixed-tokenizer histories are detectable.

Computed once in `add_turn()` after normalization, stored with the turn. Recount only if `token_count is None` or `token_count.tokenizer` differs from the configured counter.

### 4.2 Honesty about the estimate

BPE-with-o200k is an *estimator*: Claude and Gemini tokenizers differ (typically within ±10–15% on English/code, worse on non-Latin text). Budgeting therefore never aims at the hard window limit; it aims at watermarks with margin (§4.4).

### 4.3 Calibration

Every provider response reports real usage (`input_tokens` on Anthropic, `usageMetadata` on GenAI). **Decision: the handshake is a callback on the memory backend.** `ConversationMemory` exposes:

```python
async def report_usage(
    self,
    user_id: str,
    session_id: str,
    estimated_prompt_tokens: int,
    provider_prompt_tokens: int,
    chatbot_id: Optional[str] = None,
) -> None: ...
```

`AbstractClient` calls it fire-and-forget after each successful completion (missing usage in the response → no call, calibration simply doesn't move). The backend keeps an EWMA ratio in `metadata.compaction.calibration` (default 1.0, α = 0.2, clamped to [0.5, 2.0] against degenerate reports). Effective estimate = `raw_estimate × calibration`. The client stays provider-specific only in *extracting* usage; the memory layer owns the math. This is the same trick magic-compact uses (provider tokens as ground truth, GPT-BPE as the uniform ruler), made continuous.

### 4.4 Budget model

Config (per agent/bot):

```python
@dataclass(frozen=True)
class ContextBudget:
    window: int                 # model context window, tokens
    reserve_output: int = 8192  # completion headroom
    reserve_fixed: int = 4096   # system prompt + tool schemas estimate
    high_watermark: float = 0.80
    low_watermark: float = 0.60
    keep_turns: int = 4         # recent turns never pruned
```

Definitions: `available = window - reserve_output - reserve_fixed`; `used = calibration × Σ turn.token_count.total`.

Deterministic policy, oldest-first:

- If `used > high_watermark × available`: prune turns from the oldest un-pruned turn forward (skipping the last `keep_turns`) until `used ≤ low_watermark × available` or no prunable turns remain.
- If prunable turns are exhausted and still above the high watermark: this is the Stage 2 trigger (out of scope here; the condition is the hook).

Since pruning savings are computable per turn (§5 stores `tokens_saved`), the selection is a simple prefix scan — no search, no heuristics.

## 5. Stage 1 — Deterministic pruning

### 5.1 What pruning does to a turn

A pure function `prune_turn(turn, policies, store) -> turn` producing `state = PRUNED`:

- `user_message`: **never touched** (verbatim — it is the skeleton of the conversation and it is cheap).
- `assistant_response`: kept as-is in Stage 1. (Stage 2 will replace it with a summary; deterministically truncating prose responses loses meaning for little gain, since tool I/O dominates token mass in agentic sessions.)
- `context_used`: RAG context is re-retrievable by construction → replaced with an omission notice unconditionally (analogous to magic-compact's "stale read" rule).
- `tool_invocations`: per-tool policies (§5.2).
- `error` fields: **never omitted**, already condensed by Stage 0 rule 5. Failures must stay visible.

### 5.2 Per-tool policy registry

```python
@dataclass(frozen=True)
class Limit:
    words: int
    chars: int

    def exceeded(self, text: str) -> bool:
        return len(text) > self.chars or len(text.split()) > self.words

DEFAULT_LIMIT = Limit(words=128, chars=1024)      # magic-compact's defaults
SUBAGENT_LIMIT = Limit(words=512, chars=4096)

class PrunePolicy(Protocol):
    def prune(self, inv: ToolInvocation, store: OmissionStore) -> ToolInvocation: ...
```

Registry: `dict[str, PrunePolicy]` with a `DefaultPolicy` fallback; agents/toolkits can register policies next to their tools (natural fit with the ToolManager — a tool class can declare its own `prune_policy`). Built-in policies, mirroring what worked in magic-compact:

| Tool class | Input | Output |
|---|---|---|
| file write / patch | content → omit (file is on disk; re-reading is cheaper) | keep short ack |
| file read | keep path | omit always ("stale copy"; re-read for current state) |
| shell / bash | truncate command at 512 chars, ref to full | omit if over limit |
| sub-agent / crew task | keep prompt | omit if over `SUBAGENT_LIMIT` |
| HTTP / search / DB query | keep query | omit if over limit |
| default | omit string leaves over limit | omit if over limit |

Failed invocations (`status == ERROR`): output/error kept (condensed), input pruned by the same rules — knowing *what failed and why* matters more than the payload that failed.

### 5.3 Omission store — content-addressed

Backend-agnostic ABC alongside `ConversationMemory`:

```python
class OmissionStore(ABC):
    async def put(self, session_key: str, content: str) -> str: ...   # -> content_id
    async def get(self, session_key: str, content_id: str) -> Optional[str]: ...
    async def clear(self, session_key: str) -> None: ...
```

`content_id = "om_" + blake2b(content, digest_size=8).hexdigest()`. Content addressing (vs. magic-compact's `omitted-001` counter) makes `put` idempotent — pruning the same turn twice, or re-running after a crash, allocates nothing new — and deduplicates identical payloads (repeated reads of the same file cost one entry).

Implementations: `RedisOmissionStore` — hash at `{key_prefix}_omitted:{chatbot_id}:{user_id}:{session_id}`; `InMemoryOmissionStore` — dict per session. **Decision: the omission store may use a shorter TTL than the history key** (config `omission_ttl`, default = history TTL, allowed to be lower) — omitted payloads are recoverable by re-running tools, and the notice text already steers the model to that fallback when an ID has expired. Omitted content is cold storage: never rendered, only fetched by explicit tool call.

The omission notice rendered in place of content:

```
<tool-output-omitted tool="read_file" chars="18234" id="om_a3f19c2e77b01d44">
File contents omitted by compaction. Re-read the file for current state,
or call read_omitted_content("om_a3f19c2e77b01d44") for the exact historical bytes.
</tool-output-omitted>
```

### 5.4 `read_omitted_content` tool

A small built-in tool registered through the ToolManager for any agent whose memory has an omission store: `read_omitted_content(content_id: str) -> str`. Scoped to the current session key; unknown ID returns a clear "expired or unknown" message (content may have aged out with the history TTL — the notice text already tells the model the preferred fallback is a fresh tool call).

### 5.5 Where pruning runs (timing, and the prompt-cache trade-off)

Two options considered:

- **Mutate at write/watermark time** (magic-compact): history stores the pruned form. Simple reads, but destructive-ish (raw only in omission store) and every prune rewrites persisted state.
- **Pure render-time function** (chosen): history always stores the normalized raw turn; `get_messages_for_api(budget=...)` computes which turns render pruned (deterministic: all but the last `keep_turns` once past the high watermark, per §4.4) and applies `prune_turn` on the fly. Omission-store `put` is idempotent, so lazy allocation during render is safe.

Chosen because it keeps storage canonical and non-destructive, makes the render a pure function of `(history, budget, policies)`, and leaves `state`/`tokens_saved` as cache fields rather than sources of truth. Cost: pruning work on each render — bounded by memoizing the pruned form per `(turn_id, norm_version, policy_version)` in the turn's serialized record (that is what `state = PRUNED` caches).

Prompt-cache honesty: when the turn at position `len - keep_turns` crosses into pruned territory, the rendered prefix changes at that point and the provider cache is invalidated from there. This is inherent to any scheme that rewrites history and is bounded (invalidation point is always ≥ `keep_turns` back). Renders are monotonic — a turn that once rendered pruned always renders pruned (guaranteed by the prefix rule + persisted `state`) — so the prefix never flaps between forms.

## 6. Rendering

`get_messages_for_api()` gains an optional `budget: ContextBudget | None` (None = current behavior, unchanged). Tool invocations render as **uniform text** in all cases — one rendering path for every provider, no provider-native tool-call blocks (resolved, §8.2). With a budget:

- RAW turn → user + assistant verbatim, plus (new, optional flag) a compact rendering of `tool_invocations` so tool activity is visible in history at all — today it is dropped entirely.
- PRUNED turn → user verbatim; assistant verbatim; tool invocations rendered with omission notices; turn/tool errors rendered as short `[error: …]` lines.
- SUMMARIZED (future) → user verbatim + Stage 2 summary.

## 7. Testing

All pure functions with fixtures: normalization idempotence (property test, incl. ANSI-heavy and CJK samples); JSON canonicalization stability across orjson/std-json inputs; per-policy prune fixtures (input → expected turn + expected store entries); content-id determinism/dedup; watermark selection on synthetic histories (assert exact set of pruned turn IDs); v1→v2 deserialization round-trip; render monotonicity (growing history never un-prunes a turn).

## 8. Resolved questions (2026-09-03)

1. **Calibration handshake** → a callback on the memory backend (`report_usage`, §4.3); the client only extracts provider usage and reports it.
2. **Tool invocation rendering** → uniform **text rendering** across all LLMs (§6), not provider-native `tool_use`/`tool_result` blocks. One rendering path, no provider-native block IDs stored in `ConversationTurn`. Can be revisited later behind the same render function without touching storage.
3. **TTL coupling** → a shorter TTL for the omission store is acceptable (`omission_ttl` config, §5.3); omitted payloads are recoverable by re-running tools.
4. **Stage 2 (LLM summary-turn)** → deferred to a follow-up design. Hooks reserved here: `TurnState.SUMMARIZED`, the exhausted-prunables trigger (§4.4), and `metadata.compaction.last_pruned_turn_id` as the boundary marker.
