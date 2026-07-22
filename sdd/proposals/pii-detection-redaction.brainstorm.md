---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Low-Latency PII Detection & Redaction for Tool Outputs and Agent Responses

**Date**: 2026-07-19
**Author**: Jesús Lara (with Claude Code research)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot agents routinely surface text produced by tools (databases, CRMs,
web scrapers, file readers) and by the LLM itself. That text can contain
personally identifiable information — emails, phone numbers, payment cards,
national IDs, IP addresses — which today flows unfiltered into (a) the LLM
context, (b) conversation memory, (c) observability backends, and (d) the end
user's channel (chat, Slack, Teams, voice).

The framework already redacts **secrets/credentials** on tool egress
(`OutputScrubber`, FEAT-252), but has **no personal-data detection at all**.
Teams deploying agents in regulated contexts (GDPR, PCI-DSS, HIPAA-adjacent)
need a guardrail that:

- detects PII in tool outputs *before* they reach the LLM, and in the final
  agent response *before* it reaches the user — including streaming;
- adds near-zero latency (the hot path runs on every tool call and every
  response chunk);
- is **configurable per agent**: some agents legitimately must return PII
  (an HR agent returning an employee's email is not a leak), so "what counts
  as PII" must be an open catalog with per-entity and per-agent toggles —
  not a hardcoded list.

## Constraints & Requirements

- **Latency budget**: sub-millisecond scan for typical payloads (1–10 KB);
  the scan runs inside the single tool-egress seam and the streaming chunk
  loop, so it cannot add perceptible delay.
- **Configurable catalog**: entity definitions (regex + validator + scoring
  heuristics) live in data, not code; per-entity enable/disable; per-agent
  policy with an allowlist of entities the agent may emit.
- **Two actions**, both required: irreversible **redaction/masking**
  (placeholders like `<CREDIT_CARD>`) and **reversible pseudonymization**
  (tokens like `<PII_EMAIL_1>` with a restore map — hide PII from the LLM,
  restore it for the end user).
- **Streaming support** with a light sliding-window buffer.
- **Works out-of-the-box**: `pip install ai-parrot` alone must provide
  functional PII protection (pure-Python fallback); the Rust engine is an
  optional accelerator, never a hard dependency.
- **Opt-in initially**: default off; a `detect_only` mode must exist for
  safe rollout (audit without rewriting).
- Repo conventions: async-first, Pydantic models, Google docstrings,
  `self.logger`, `uv` packaging.

---

## Options Explored

### Option A: Own Rust engine via PyO3 (thin hot-path crate) + pure-Python fallback

Build a small in-repo Rust crate (`pii-rs`) exposing a single compiled
`Engine` pyclass whose only job is the hot path: multi-pattern regex matching
(`RegexSet` — one DFA pass answers "which of N patterns hit", so clean text
exits in microseconds), checksum validators (Luhn, IBAN mod-97), context-word
scoring (aho-corasick), and span merging. Everything cold stays in Python:
catalog loading/merging, policy resolution, action application, pseudonym
token assignment, orchestration, audit. A pure-Python engine implements the
identical `PIIEngine` protocol with stdlib `re`, so the native wheel is a
drop-in accelerator gated by importability — exactly how `yaml_rs` already
works in this repo.

✅ **Pros:**
- Total control of catalog schema, scoring heuristics, and API — no
  impedance mismatch with `PIIPolicy`/per-agent semantics.
- Proven precedent in-repo: `yaml-rs` crate (pyo3 0.29, maturin, cdylib,
  `try: import yaml_rs` fallback) is a copy-paste packaging template.
- `RegexSet` + validators in Rust delivers the sub-ms budget (10–33×
  speedups over Python regex are typical for this workload).
- Fallback keeps macOS/ARM and no-wheel environments fully functional.
- Catalog constrained to the Rust `regex` syntax subset from day one makes
  Rust↔Python parity testable and permanent.

❌ **Cons:**
- We own the crate: CI wheel builds (cibuildwheel/maturin), parity tests,
  and validator implementations in two languages.
- Rust `regex` has no lookaround/backreferences — catalog authors lose some
  regex expressiveness (mitigated by validators + context scoring).

📊 **Effort:** Medium (Python phase is Low; the crate itself is small)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyo3` 0.29 | Rust↔Python bindings | already used by `yaml-rs` |
| `maturin` | build backend for the crate | already in dev deps (1.9.6) |
| `regex` (Rust) | `RegexSet` multi-pattern DFA | no lookaround — catalog subset |
| `aho-corasick` (Rust) | context-word scan | transitive dep of `regex` |
| `serde`/`serde_json` (Rust) | catalog JSON → compiled engine | already used by `yaml-rs` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/yaml-rs/` — full packaging template (own
  maturin `pyproject.toml`, dist name, python-source wrapper, import-fallback).
- `packages/ai-parrot/src/parrot/security/redaction.py` — `OutputScrubber`
  pattern: reason-tagged markers, idempotency guard, allowlist, audit log.
- `packages/ai-parrot/src/parrot/tools/abstract.py:695-724` — the single
  tool-egress scrub seam to chain into.
- `parrot.observability.context.current_agent_name` (FEAT-228 ContextVar) —
  per-agent policy resolution without threading new parameters.

---

### Option B: Adopt an existing Rust-backed library (argus-redact / worka-pii / redact_core)

Integrate a third-party PII engine that already ships Rust cores with Python
bindings: `argus-redact` (PyO3 core, `mode="fast"` regex layer is sub-ms,
reversible pseudonymization built in), `worka-ai/pii` (deterministic
detection, regex + validators + dictionary recognizers, anonymization
operators), or `redact_core` (Presidio-compatible replacement).

✅ **Pros:**
- Least implementation work for the engine itself; pseudonymization and
  span logic already written and battle-tested.
- Someone else maintains the wheels for multiple platforms.

❌ **Cons:**
- Catalog/policy model is theirs, not ours: per-agent `allow_entities`,
  seam toggles, and the `ScrubPolicy`-style audit contract would be an
  adapter layer fighting the library's own config surface.
- New runtime dependency of uncertain maturity/governance for a *security*
  feature; supply-chain exposure on the trust boundary.
- Streaming filter still has to be written by us regardless (none of these
  expose a chunk-feed API), as does the seam integration — so the saved
  effort is smaller than it looks.
- Reversibility semantics (per-message keys in argus-redact) don't map to
  our per-conversation `PseudonymStore` requirement.

📊 **Effort:** Low–Medium (engine) + Medium (adapter + streaming anyway)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `argus-redact` | Rust+PyO3 PII engine | fast mode sub-ms; reversible pseudonyms; CN-centric depth |
| `worka-pii` / `redact_core` | Rust PII engines | crates, Python bindings varying maturity |

🔗 **Existing Code to Reuse:**
- Same seams as Option A (`tools/abstract.py`, `security/redaction.py`) —
  the integration points don't change, only the engine behind them.

---

### Option C: Pure-Python engine first, pluggable interface (Rust later if profiling demands)

Ship only the Python implementation: compiled stdlib `re` patterns combined
per-entity, validators in Python, the same catalog/policy/seam design. Define
`PIIEngine` as a Protocol so a native engine can be slotted in later without
API changes.

✅ **Pros:**
- Fastest to ship; zero build/CI complexity; works identically everywhere.
- For typical payloads (1–10 KB, ~10 entities) compiled `re` is already
  ~1–5 ms — acceptable for many deployments.
- All the *design* work (catalog, policy, seams, streaming) is identical to
  Option A; nothing is thrown away if Rust comes later.

❌ **Cons:**
- Misses the stated sub-ms latency target on the tool hot path; cost is per
  tool call *and* per streaming rescan, so it compounds.
- Python lacks a `RegexSet` equivalent — N entities means N passes (or one
  giant alternation with worse pathology), scaling poorly as the catalog
  grows.
- Defers the Rust work the user explicitly asked for.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `re` | pattern matching | no new deps at all |

🔗 **Existing Code to Reuse:**
- Same as Option A.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that meets all three hard requirements at once —
  sub-ms hot path (Rust `RegexSet`), a catalog/policy model designed around
  *our* per-agent semantics, and out-of-the-box function via the Python
  fallback (which is effectively Option C embedded as Phase 1).
- The repo has already paid the architectural cost: `yaml-rs` proves the
  crate-in-core + maturin + import-fallback pattern end-to-end, including
  cibuildwheel wiring. `pii-rs` copies it mechanically.
- Option B's savings evaporate once the adapter, per-agent policy mapping,
  and streaming filter are counted, while adding a third-party dependency at
  the most security-sensitive point of the pipeline.
- Phasing de-risks it: Phase 1 (pure Python) ships complete functionality;
  Phase 2 (Rust) is a behavior-identical accelerator proven by parity tests.

Trade-off accepted: we maintain validators in two languages and constrain
catalog regexes to the Rust-compatible subset (no lookaround/backrefs). The
parity test suite makes this constraint self-enforcing.

---

## Feature Description

### User-Facing Behavior

- New bot kwargs, following the `enable_tools` convention:
  `enable_pii_protection: bool = False` and `pii_policy: dict | PIIPolicy`.
- `PIIPolicy` fields: `mode` (`off` | `detect_only` | `enforce`),
  `allow_entities` (ids this agent may legitimately emit), `entity_actions`
  (per-entity override: `allow` | `redact` | `pseudonymize`), `min_score`,
  `locales`, `catalog_paths` (overlay files), and per-seam toggles
  (`scrub_tool_outputs`, `scrub_final_response`, `scrub_streaming`).
- Bundled default catalog (`data/default_catalog.yaml`) with starter
  entities: `email`, `phone_us`, `credit_card` (Luhn), `ipv4`, `us_ssn`.
  Users overlay/extend by entity `id` via `catalog_paths` or the
  `PARROT_PII_CATALOG` env var — an overlay can disable, re-score, or
  replace patterns of a builtin entity, or add new ones.
- Redaction produces the entity's mask (`<CREDIT_CARD>`, partial, or last4
  per catalog `mask.strategy`); pseudonymization produces stable tokens
  `<PII_EMAIL_1>` — same value → same token within a conversation — and the
  final response restores real values for the user while the LLM never saw
  them.
- Runtime toggles: mutate `bot.pii_policy` (e.g.
  `allow_entities.add("email")`) or `PIICatalog.set_enabled(entity_id,
  enabled)`; recompilation is cached by catalog fingerprint.
- With native wheels installed (`pip install ai-parrot[pii-native]`) the
  Rust engine is used automatically; otherwise a single INFO log notes the
  Python fallback. No behavior difference.

### Internal Behavior

- **Module**: `parrot/security/pii/` (always installed): `types.py`
  (`PIISpan`, `PIIAction`, results), `catalog.py` (`PIIEntityDef`,
  `PIICatalog` — load/merge/fingerprint), `policy.py` (`PIIPolicy` Pydantic
  model + per-agent registry), `engine.py` (`PIIEngine` Protocol:
  `scan(text) -> list[PIISpan]`; `get_engine()` factory cached by catalog
  fingerprint), `python_engine.py`, `native_engine.py`, `validators.py`
  (enum-dispatched: `luhn`, `mod97`, `ip`, `date` — a catalog can never
  inject code), `pseudonym.py` (`TokenMap`, `PseudonymStore`),
  `scrubber.py` (`PIIScrubber`), `streaming.py` (`StreamingPIIFilter`).
- **Crate**: `parrot/pii-rs/` with its own maturin `pyproject.toml`
  (module `pii_rs`, dist `parrot-pii-rs`), mirroring `yaml-rs`. PyO3 API:
  `Engine::new(catalog_json)`, `Engine::scan(text) -> Vec<PySpan>`
  (`{entity_id, start, end, score}`, char offsets, GIL released during
  matching), `Engine::fingerprint()`. Scan algorithm: `RegexSet` pass →
  `find_iter` only for matched patterns → validator + context-word scoring
  → overlap merge (higher score wins, ties leftmost-longest).
- **Seam composition** — `PIIScrubber` is a **sibling policy** chained after
  the secrets pass inside the existing FEAT-252 hook in
  `AbstractTool.execute()` (the "single seam" invariant is preserved;
  secrets scrub first; PII pass skips text already inside `***REDACTED***`
  markers via the existing idempotency-guard pattern). Per-agent policy is
  resolved through the `current_agent_name` ContextVar against a registry
  populated in `AbstractBot.__init__`. `ScrubPolicy` itself is **not**
  extended — secrets stay unconditional; PII is per-agent and reversible.
- **Final response**: in `AbstractBot.get_response()` — apply redaction
  (enforce+redact) or `TokenMap.restore()` (pseudonymize) to the outgoing
  text. **Streaming**: `StreamingPIIFilter.feed(chunk)` wraps the yield in
  `BaseBot.ask_stream()`'s chunk loop with a holdback window of
  `max(entity.max_len) + slack` (cap 128 chars), cutting on whitespace so
  markers/tokens are never split; `flush()` before the final `AIMessage`,
  which carries the filtered full text (memory stores scrubbed text).
- **Pseudonym map**: per-conversation `PseudonymStore` on the bot instance,
  in-memory with TTL/LRU, keyed `(entity_id, normalized_value)`; never
  persisted, never logged (the map *is* PII).
- **Audit**: mirrors `OutputScrubber._audit` — logs entity id + tool name,
  never the value; detection counts can ride the existing
  `AfterToolCallEvent`/`AfterInvokeEvent` observers (no new event types).

### Edge Cases & Error Handling

- **Scrub failure is non-fatal**: wrapped in the same try/except pattern as
  FEAT-252 — a scrubber exception logs a warning and returns the original
  result rather than breaking tool execution.
- **Idempotency**: re-scrubbing scrubbed text is a no-op; PII patterns never
  scan inside existing redaction markers.
- **Hallucinated tokens**: `restore()` is best-effort — a token the LLM
  invented (unknown index) is left literal and logged at WARNING.
- **Store eviction/restart**: restore degrades gracefully — tokens surface
  as literals (documented limitation of in-memory-only maps).
- **Oversized payloads**: follow `ScrubPolicy.max_output_bytes` precedent
  (wholesale action above a size threshold).
- **Catalog validation at load**: regexes compiled against the Rust-subset
  syntax (rejected early on both engines if incompatible); schema errors
  fail loudly at startup, not at scan time.
- **Chunk-boundary PII**: the sliding window guarantees a span can never be
  emitted partially; the streaming invariant is *concatenated streaming
  output == non-streaming scrub output*.

---

## Capabilities

### New Capabilities
- `pii-catalog-engine`: PII catalog schema, `PIIPolicy`, Python engine,
  `PIIScrubber`, and integration at the tool-egress + final-response seams
  (Phase 1).
- `pii-rust-engine`: `pii-rs` PyO3 crate, `pii-native` extra, CI wheels,
  parity + latency benchmark suites (Phase 2).
- `pii-pseudonymization`: reversible token map, `PseudonymStore`,
  transform-at-seam + restore-at-response (Phase 3).
- `pii-streaming-filter`: sliding-window `StreamingPIIFilter` wired into
  `ask_stream` (Phase 4).

### Modified Capabilities
- (none — the FEAT-252 secrets scrubber is chained-with, not modified; its
  hook site in `tools/abstract.py` gains an additional pass)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/abstract.py` (egress seam) | extends | PII pass chained after secrets scrub inside the FEAT-252 hook |
| `parrot/security/` | extends | new `pii/` subpackage; `redaction.py` untouched |
| `parrot/bots/abstract.py` | extends | new kwargs `enable_pii_protection`/`pii_policy`; redact/restore in `get_response()` |
| `parrot/bots/base.py` (`ask_stream`) | modifies | chunk loop wraps yields through `StreamingPIIFilter` (Phase 4) |
| `packages/ai-parrot/pyproject.toml` | extends | new optional extra `pii-native = ["parrot-pii-rs>=x.y"]` |
| CI (cibuildwheel) | extends | wheel job for `pii-rs` (copy `yaml-rs` matrix: cp311–314 manylinux x86_64) |
| Conversation memory / observability | depends on | streaming path stores scrubbed text; `ask()` path decision open (see Open Questions) |

No breaking changes: default is `enable_pii_protection=False`.

---

## Code Context

### User-Provided Code

(none — requirements were provided as prose)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/abstract.py:88
class ToolResult(BaseModel):  # .result / .error / .metadata are the scrubbed fields
    ...

# From packages/ai-parrot/src/parrot/tools/abstract.py:59-65
def _default_scrubber():  # module-level OutputScrubber singleton, lazy init
    ...
# The FEAT-252 hook lives at tools/abstract.py:695-724 inside AbstractTool.execute();
# in-code comment: "This is the ONLY place scrubbing happens on the way out".
# Non-fatal try/except wraps the scrub (lines 700-724).

# From packages/ai-parrot/src/parrot/security/redaction.py:127-146
@dataclass(frozen=True)
class ScrubPolicy:
    reason_tags: bool = True
    audit_log: bool = True
    allowlist: FrozenSet[str] = field(default_factory=frozenset)
    max_output_bytes: int = 1_048_576

# From packages/ai-parrot/src/parrot/security/redaction.py:122-124
def _already_scrubbed(text: str) -> bool:  # idempotency guard to reuse
    ...

# From packages/ai-parrot/src/parrot/bots/abstract.py:3390
def get_response(  # sync; every non-streaming path funnels the AIMessage here
    ...

# From packages/ai-parrot/src/parrot/bots/base.py:1566
async def ask_stream(  # chunks yielded at :1772-1773; final AIMessage at :1846
    ...
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.security.redaction import OutputScrubber, ScrubPolicy  # via tools/abstract.py:53
from parrot.observability.context import current_agent_name  # bots/base.py:56 (FEAT-228)
```

#### Key Attributes & Constants
- `current_agent_name` ContextVar is set in `ask`/`invoke`/`ask_stream`
  (`bots/base.py:196, 605, 964, 1589`) — per-agent policy resolution point.
- Bot kwarg-toggle convention: `self.enable_tools` (`bots/abstract.py:~383-400`).
- Pydantic config-model template: `ObservabilityConfig`
  (`parrot/observability/config.py:18`) — already carries telemetry
  PII/redaction settings; shape template for `PIIPolicy`.
- Rust packaging template: `packages/ai-parrot/src/parrot/yaml-rs/`
  (own maturin `pyproject.toml`, pyo3 0.29 `Bound` API, cdylib,
  `opt-level=3, lto=true`; consumed via `try: import yaml_rs` fallback in
  `parrot/outputs/formats/yaml.py:5-9`).
- Core `[tool.maturin]` + `[tool.cibuildwheel]` wiring:
  `packages/ai-parrot/pyproject.toml:608-622` (cp311–314 manylinux x86_64).
- Benchmarks directory exists: `tests/benchmarks/`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.security.pii`~~ — does not exist yet (this feature creates it).
- ~~Any runtime personal-PII detection~~ — `redaction.py` covers only
  secrets/credentials/infra (API keys, JWT, DSNs, env dumps, net topology).
- ~~`presidio` / `scrubadub` / `phonenumbers` / `detect-secrets` deps~~ —
  not in any package's `pyproject.toml`.
- ~~An output-side middleware pipeline~~ — `bots/middleware.py`
  (`PromptPipeline`) is input-only; there is no response-transform chain.
- ~~Mutating lifecycle hooks~~ — FEAT-176 events and `_on_post_ask` /
  `_post_response_memory_hook` are observer-only / fire-and-forget; they
  cannot rewrite responses.
- ~~aiohttp response-body middleware~~ — the only server middleware is A2A
  auth; egress is per-handler.

---

## Parallelism Assessment

- **Internal parallelism**: High after Phase 1. Phase 2 (`pii-rust-engine`)
  and Phase 3 (`pii-pseudonymization`) are independent of each other and
  can run in parallel worktrees; Phase 4 (streaming) depends on Phase 1
  only (works with either engine, with or without pseudonymization).
- **Cross-feature independence**: touches `tools/abstract.py` (FEAT-252
  hook site) and `bots/base.py` `ask_stream` — check for in-flight specs
  touching those files before cutting worktrees. `security/redaction.py`
  is read-only reused, not modified.
- **Recommended isolation**: per-spec (one worktree per capability).
- **Rationale**: the four capabilities have clean file boundaries
  (`pii/` subpackage vs `pii-rs/` crate vs `pseudonym.py` vs
  `streaming.py`+`ask_stream`), and the Phase-1 Protocol freezes the
  interface the others build against.

---

## Open Questions

- [ ] Regex-syntax parity: enforce the Rust `regex` subset (no lookaround/
  backrefs) in catalog validation from day 1 — acceptable expressiveness
  loss? — *Owner: Jesús*
- [ ] False positives (phones vs order numbers, SSN vs timestamps): are
  context scoring + `min_score` + `detect_only` rollout sufficient, or do
  we need a per-tool suppression list too? — *Owner: Jesús*
- [ ] Default posture: secrets scrubbing is unconditional; should PII
  protection become default-on after telemetry from `detect_only`? —
  *Owner: Jesús*
- [ ] PII at rest: memory and observability currently store raw text. The
  streaming path will store scrubbed text; should the non-streaming `ask()`
  path store scrubbed text as well? — *Owner: Jesús*
- [ ] Pseudonym map is itself PII (GDPR): in-memory + TTL only, restore
  degrades after restart/eviction — acceptable, or is an encrypted Redis
  option needed later? — *Owner: Jesús*
- [ ] Wheel matrix: start manylinux x86_64 only (macOS/ARM fall back to
  Python, logged once) — when to extend? — *Owner: Jesús*
- [ ] PII split across formatting (card number across table cells / JSON
  keys) is out of scope for span matching — document as limitation? —
  *Owner: Jesús*
- [ ] NER-class entities (person names, postal addresses) are not
  regex-detectable; `PIIEngine` Protocol is the extension point for a
  future `SpacyNerEngine` (spacy already in the `agents` extra) — confirm
  out of scope for FEAT-324. — *Owner: Jesús*
  (Note: this feature was tentatively FEAT-316 when drafted; 316–318 were
  taken by the eventbus migration, so the spec assigned FEAT-324.)
- [ ] Streaming UX: holdback window delays the last ≤128 chars of a
  stream — acceptable for AgentTalk/voice consumers? — *Owner: Jesús*
