---
type: feature
base_branch: dev
---

# Feature Specification: PII Detection & Redaction for Tool Outputs and Agent Responses

**Feature ID**: FEAT-319
**Date**: 2026-07-20
**Author**: Jesús Lara (spec drafted with Claude Code)
**Status**: draft
**Target version**: 0.26.0

> Source brainstorm: `sdd/proposals/pii-detection-redaction.brainstorm.md`
> (Recommended Option A). Note: the brainstorm tentatively cited FEAT-316;
> that id was taken by the eventbus migration — this feature is **FEAT-319**.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot agents surface text produced by tools (databases, CRMs, scrapers,
file readers) and by the LLM itself. That text can contain personally
identifiable information — emails, phone numbers, payment cards, national
IDs, IP addresses — which today flows unfiltered into (a) the LLM context,
(b) conversation memory, (c) observability backends, and (d) the end user's
channel. The framework redacts **secrets** on tool egress (`OutputScrubber`,
FEAT-252) but has **no personal-data detection at all**. Teams in regulated
contexts (GDPR, PCI-DSS) need a low-latency, per-agent-configurable PII
guardrail: some agents legitimately must return PII (an HR agent returning
an employee email is not a leak), so "what counts as PII" must be an open
catalog with per-entity and per-agent toggles.

### Goals

- Detect PII in tool outputs before they reach the LLM, and in the final
  agent response before it reaches the user — including streaming.
- Sub-millisecond scan for typical payloads (1–10 KB) via a native Rust
  engine; a pure-Python fallback keeps `pip install ai-parrot` fully
  functional with no native wheel.
- Open catalog: entity definitions (regex + validator + scoring heuristics)
  live in data, not code; per-entity enable/disable; per-agent `PIIPolicy`
  with an `allow_entities` allowlist and `off`/`detect_only`/`enforce` modes.
- Two actions: irreversible **redaction/masking** and **reversible
  pseudonymization** (`<PII_EMAIL_1>` tokens; the LLM never sees the value,
  the end user gets it restored).
- Streaming support via a sliding-window filter with a bounded holdback.
- When a policy is in `enforce` mode, conversation memory and observability
  store **scrubbed text on both paths** (`ask()` and `ask_stream()`) —
  PII-at-rest reduction is a goal, not a side effect.
- Opt-in initially: `enable_pii_protection` defaults to `False`.

### Non-Goals (explicitly out of scope)

- NER-class entities (person names, postal addresses) — not regex-detectable;
  the `PIIEngine` protocol is the extension point for a future
  `SpacyNerEngine`.
- PII split across formatting (a card number spanning table cells / JSON
  keys) — span matching operates on contiguous text values; documented
  limitation.
- Adopting a third-party PII engine (argus-redact / worka-pii /
  redact_core) — rejected as brainstorm Option B (adapter + supply-chain
  cost at a security boundary; see the brainstorm for the full analysis).
- Modifying the FEAT-252 secrets scrubber semantics — secrets stay
  unconditional; `parrot/security/redaction.py` is not touched.

---

## 2. Architectural Design

### Overview

A new `parrot/security/pii/` subpackage provides a `PIIEngine` protocol
(`scan(text) -> list[PIISpan]`) with two interchangeable implementations: a
pure-Python engine (stdlib `re`, always installed) and a Rust engine
(`pii-rs` crate, PyO3/maturin, packaged exactly like the existing `yaml-rs`
crate and selected automatically when importable via the optional extra
`ai-parrot[pii-native]`). The engine is *stateless per request* and holds the
compiled catalog; instances are cached by catalog fingerprint.

Everything cold stays in Python: catalog loading/merging (bundled
`default_catalog.yaml` + user overlays merged by entity `id`), per-agent
policy resolution, action application (mask strategies, token substitution),
pseudonym token assignment, orchestration, and audit. The Rust crate owns
only the hot path: `RegexSet` multi-pattern matching (one DFA pass — clean
text exits in microseconds), checksum validators (Luhn, IBAN mod-97),
context-word scoring (aho-corasick), and span overlap merging.

`PIIScrubber` is a **sibling policy** to the FEAT-252 secrets scrubber,
chained *after* the secrets pass inside the existing single tool-egress hook
in `AbstractTool.execute()` — the "single seam" invariant is preserved, and
the PII pass skips text already inside `***REDACTED***` markers. Per-agent
policy is resolved through the `current_agent_name` ContextVar (FEAT-228)
against a registry populated in `AbstractBot.__init__`. The final response
is redacted or token-restored in `AbstractBot.get_response()`
(non-streaming) and through a `StreamingPIIFilter` sliding window in
`BaseBot.ask_stream()` (streaming).

Resolved design decisions (carried from brainstorm + spec round):
- Catalog regexes are validated at load time against the **Rust `regex`
  syntax subset** (no lookaround/backreferences) so Python↔Rust parity is
  permanent and testable.
- Default posture is **opt-in** (`enable_pii_protection=False`);
  `detect_only` mode (audit without rewriting) is the documented first step
  of any rollout.
- In `enforce` mode, memory and observability persist **scrubbed** text on
  both `ask()` and `ask_stream()` paths.
- `PseudonymStore` ships with an abstract interface and **two backends in
  this feature**: in-memory (TTL/LRU) and encrypted Redis (AES-GCM via the
  existing `credentials_utils` helpers over `navigator_session.vault.crypto`,
  connection pattern per `RedisConversation`).

### Component Diagram

```
                       ┌──────────────────────────────────────────────┐
Tool.execute() ──────► │ FEAT-252 hook (tools/abstract.py:695-724)    │
                       │  1. OutputScrubber (secrets, unconditional)  │
                       │  2. PIIScrubber (policy-driven, NEW)         │──► ToolResult (clean)
                       └───────────────┬──────────────────────────────┘        │
                                       │ resolves policy via                    ▼
                                       │ current_agent_name ContextVar     LLM context
                                       ▼
                       ┌──────────────────────────────┐
                       │ PIIPolicy registry (per agent)│
                       └───────────────┬──────────────┘
                                       ▼
      ┌──────────────┐   fingerprint   ┌─────────────────────────────┐
      │ PIICatalog   │───────────────► │ get_engine() cache          │
      │ (YAML merge) │                 │  ├─ RustPIIEngine (pii_rs)  │
      └──────────────┘                 │  └─ PythonPIIEngine (re)    │
                                       └─────────────────────────────┘

LLM answer ──► get_response()  ──► PIIScrubber.redact / TokenMap.restore ──► user
LLM stream ──► ask_stream()    ──► StreamingPIIFilter.feed()/flush()     ──► user
                                       │
                                       ▼
                       ┌───────────────────────────────────┐
                       │ AbstractPseudonymStore            │
                       │  ├─ InMemoryPseudonymStore (TTL)  │
                       │  └─ RedisPseudonymStore (AES-GCM) │
                       └───────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool.execute()` egress hook (`tools/abstract.py:695-724`) | extends | PII pass chained after the secrets scrub; same non-fatal try/except contract |
| `parrot/security/` package | extends | new `pii/` subpackage; `redaction.py` reused read-only (`_already_scrubbed` guard pattern), never modified |
| `AbstractBot.__init__` (`bots/abstract.py`) | extends | new kwargs `enable_pii_protection` / `pii_policy`; registers policy in the per-agent registry |
| `AbstractBot.get_response()` (`bots/abstract.py:3390`) | extends | redact (enforce+redact) or `TokenMap.restore()` (pseudonymize) on outgoing text |
| `BaseBot.ask_stream()` (`bots/base.py:1772-1846`) | modifies | chunk yields wrapped through `StreamingPIIFilter`; final `AIMessage` carries filtered text |
| Conversation memory / observability | modifies (behavioral) | in `enforce` mode both `ask()` and `ask_stream()` persist scrubbed text |
| `parrot/memory/redis.py` (`RedisConversation`) | reuses pattern | `RedisPseudonymStore` follows its `redis.asyncio` + `REDIS_HISTORY_URL` + key-prefix conventions |
| `parrot/security/credentials_utils.py` | uses | AES-GCM encrypt/decrypt for the Redis pseudonym payloads |
| `packages/ai-parrot/pyproject.toml` | extends | optional extra `pii-native = ["parrot-pii-rs>=0.1"]` |
| CI (cibuildwheel/maturin) | extends | wheel job for `pii-rs`, copying the `yaml-rs` matrix (cp311–314 manylinux x86_64) |
| Lifecycle events (FEAT-176) | uses (observer) | detection counts attached to existing `AfterToolCallEvent`/`AfterInvokeEvent` observers; no new event types |

No breaking changes: everything defaults off.

### Data Models

```python
# parrot/security/pii/types.py — design signatures (not implementation)
class PIIAction(str, Enum):
    ALLOW = "allow"
    REDACT = "redact"
    PSEUDONYMIZE = "pseudonymize"

class PIISpan(BaseModel):
    entity_id: str        # catalog entity id, e.g. "credit_card"
    start: int            # char offset (not bytes — UTF-8 safety)
    end: int
    score: float          # after validator/context boosts

# parrot/security/pii/catalog.py
class PIIPattern(BaseModel):
    regex: str            # validated at load against the Rust `regex` subset
    score: float          # base confidence

class PIIMask(BaseModel):
    strategy: Literal["fixed", "partial", "last4"] = "fixed"
    placeholder: str      # e.g. "<CREDIT_CARD>"

class PIIEntityDef(BaseModel):
    id: str               # stable snake_case; used in tokens/policy/audit
    name: str
    locales: list[str] = ["any"]
    severity: Literal["low", "medium", "high"]
    enabled: bool = True
    default_action: PIIAction = PIIAction.REDACT
    max_len: int          # streaming holdback contribution
    patterns: list[PIIPattern]
    validator: Literal["none", "luhn", "mod97", "ip", "date"] = "none"
    validator_boost: float = 0.0
    context_words: list[str] = []
    context_window: int = 40
    context_boost: float = 0.0
    mask: PIIMask

class PIICatalog(BaseModel):
    version: int
    entities: list[PIIEntityDef]
    # methods: load()/merge overlays by entity id, fingerprint() -> sha256,
    #          set_enabled(entity_id, enabled) -> re-fingerprint

# parrot/security/pii/policy.py
class PIIPolicy(BaseModel):
    mode: Literal["off", "detect_only", "enforce"] = "off"
    allow_entities: set[str] = set()          # ids this agent may emit
    entity_actions: dict[str, PIIAction] = {} # per-entity override
    min_score: float = 0.5
    locales: Optional[list[str]] = None
    catalog_paths: list[Path] = []            # overlays; also PARROT_PII_CATALOG env
    scrub_tool_outputs: bool = True
    scrub_final_response: bool = True
    scrub_streaming: bool = True
    pseudonymize_default: bool = False
```

### New Public Interfaces

```python
# parrot/security/pii/engine.py
class PIIEngine(Protocol):
    """Scans text for PII spans. Holds the compiled catalog; sync (pure CPU)."""
    def scan(self, text: str) -> list[PIISpan]: ...

def get_engine(catalog: PIICatalog, prefer_native: bool = True) -> PIIEngine:
    """Cached by catalog.fingerprint(); RustPIIEngine when pii_rs is
    importable, else PythonPIIEngine (single INFO log on fallback)."""

# parrot/security/pii/scrubber.py — mirrors OutputScrubber's call shape
class PIIScrubber:
    def scrub(self, value: Any, tool_name: str | None = None) -> Any: ...
    def transform(
        self, text: str, policy: PIIPolicy, token_map: "TokenMap | None"
    ) -> "TransformResult": ...

# parrot/security/pii/pseudonym.py
class AbstractPseudonymStore(ABC):
    """Per-conversation token maps, keyed (user_id, session_id).
    The map IS PII: never logged; Redis backend stores AES-GCM ciphertext."""
    async def get_map(self, user_id: str, session_id: str) -> "TokenMap": ...
    async def save_map(self, user_id: str, session_id: str, m: "TokenMap") -> None: ...

class InMemoryPseudonymStore(AbstractPseudonymStore): ...   # TTL + LRU
class RedisPseudonymStore(AbstractPseudonymStore): ...      # encrypted payloads

class TokenMap:
    """(entity_id, normalized_value) -> '<PII_EMAIL_1>'; stable within a
    conversation. restore(text) is best-effort (unknown tokens left literal,
    WARNING logged)."""

# parrot/security/pii/streaming.py
class StreamingPIIFilter:
    def feed(self, chunk: str) -> str: ...   # "" while withholding
    def flush(self) -> str: ...

# pii_rs (Rust crate, PyO3) — Python-visible surface
# Engine(catalog_json: str); Engine.scan(text) -> list[Span]; Engine.fingerprint()
```

New bot kwargs (following the `enable_tools` convention):
`enable_pii_protection: bool = False`, `pii_policy: dict | PIIPolicy | None`.

---

## 3. Module Breakdown

> These map 1:1 to the brainstorm's capabilities and directly to Task
> Artifacts.

### Module 1: pii-catalog-engine
- **Path**: `parrot/security/pii/` (`types.py`, `catalog.py`, `policy.py`,
  `engine.py`, `python_engine.py`, `validators.py`, `scrubber.py`,
  `data/default_catalog.yaml`, `__init__.py`) + seam integration in
  `parrot/tools/abstract.py` and `parrot/bots/abstract.py`
- **Responsibility**: catalog schema + loader/merger/fingerprint; `PIIPolicy`
  + per-agent registry (resolved via `current_agent_name`); pure-Python
  engine with enum validators; `PIIScrubber` chained after the secrets pass
  at the tool seam; redact in `get_response()`; bot kwargs; starter entities
  (`email`, `phone_us`, `credit_card` w/ Luhn, `ipv4`, `us_ssn`);
  scrubbed-at-rest on both paths in `enforce`; `detect_only` mode; audit
  logging (entity id + tool, never the value).
- **Depends on**: nothing new (existing seams only).

### Module 2: pii-rust-engine
- **Path**: `parrot/pii-rs/` (Cargo.toml, own maturin `pyproject.toml`,
  `src/lib.rs`, `src/engine.rs`, `src/validators.rs`, `src/merge.rs`) +
  `parrot/security/pii/native_engine.py` + `pii-native` extra + CI wheels
- **Responsibility**: `RegexSet` scan → per-match `find_iter` → validators +
  context scoring (aho-corasick) → span merge; `Engine` pyclass compiled
  once from catalog JSON, GIL released during matching; behavior-identical
  drop-in behind `get_engine()`.
- **Depends on**: Module 1 (protocol + corpus). Parallel with Module 3.

### Module 3: pii-pseudonymization
- **Path**: `parrot/security/pii/pseudonym.py` + restore wiring in
  `bots/abstract.py` (`get_response()`)
- **Responsibility**: `TokenMap` (stable `<PII_{ENTITY}_{n}>` tokens,
  referential consistency), `AbstractPseudonymStore`, `InMemoryPseudonymStore`
  (TTL/LRU, per-key `asyncio.Lock`), `RedisPseudonymStore` (AES-GCM payloads
  via `credentials_utils`, `RedisConversation`-style keys/connection);
  transform at the tool seam, restore at the response; best-effort restore.
- **Depends on**: Module 1. Parallel with Module 2.

### Module 4: pii-streaming-filter
- **Path**: `parrot/security/pii/streaming.py` + hook in `bots/base.py`
  (`ask_stream`)
- **Responsibility**: sliding-window filter — holdback
  `max(entity.max_len) + slack` capped at 128 chars, whitespace-preferring
  cuts (markers/tokens never split), amortized rescan (≥32 new chars or
  50 ms); `flush()` before the final `AIMessage`, which carries the filtered
  full text; works with either engine, with or without Module 3.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_catalog_schema_validation` | M1 | Valid/invalid entity defs; regex rejected if outside the Rust subset |
| `test_catalog_overlay_merge` | M1 | Overlay by `id` disables/re-scores/replaces builtin entities; env var path |
| `test_catalog_fingerprint_toggle` | M1 | `set_enabled` changes fingerprint → engine cache miss |
| `test_python_engine_entities` | M1 | Positive/negative corpus per starter entity (Luhn-valid vs invalid cards, context boosts, `min_score`) |
| `test_pii_scrubber_recursive` | M1 | dict/list/tuple/str traversal; idempotency `scrub(scrub(x)) == scrub(x)`; skips inside `***REDACTED***` |
| `test_pii_policy_allow_entities` | M1 | Allowed entities pass through; `detect_only` audits without rewriting |
| `test_tool_seam_integration` | M1 | Stub tool returning PII → scrubbed `ToolResult`; secrets pass runs first; scrub failure non-fatal |
| `test_agent_policy_resolution` | M1 | Policy resolved via `current_agent_name`; unregistered agent → no PII pass |
| `test_engine_parity` | M2 | Shared corpus through both engines → identical `(entity_id, start, end)` sets; `skipif` without `pii_rs` |
| `test_token_map_roundtrip` | M3 | `restore(transform(x)) == x`; same value → same token; hallucinated token left literal + WARNING |
| `test_pseudonym_stores` | M3 | TTL/LRU eviction; Redis backend stores only ciphertext; map never in logs (`caplog`) |
| `test_streaming_boundaries` | M4 | Seeded random chunk splits → concatenated output == non-streaming scrub output; markers never split |

### Integration Tests

| Test | Description |
|---|---|
| `test_ask_end_to_end_redaction` | Bot with `enforce` policy + PII-emitting stub tool → response and memory contain no raw PII |
| `test_ask_stream_end_to_end` | Streaming path: filtered chunks, filtered final `AIMessage`, scrubbed memory |
| `test_pseudonymize_llm_blind` | LLM context receives tokens only; user response has restored values |
| `test_scrubbed_at_rest_both_paths` | `enforce` mode: memory/observability text scrubbed on `ask()` AND `ask_stream()` |

### Performance Benchmarks (`tests/benchmarks/`)

| Benchmark | Gate |
|---|---|
| Native scan, 1 KB clean text | p99 < 100 µs |
| Native scan, 10 KB mixed | p99 < 1 ms |
| Python fallback, same corpora | informational (target: < 10× native) |
| 100 KB pathological (many near-misses) | no quadratic blowup (documented ceiling) |

### Test Data / Fixtures

```python
# tests/fixtures/pii_corpus/ — labeled YAML: text -> expected spans
# Shared by unit, parity, streaming-fuzz, and benchmark suites.
@pytest.fixture
def pii_corpus() -> list[CorpusCase]: ...

@pytest.fixture
def pii_bot(policy: PIIPolicy):  # bot wired with a stub PII-emitting tool
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests pass (`pytest tests/ -v`).
- [ ] `pip install ai-parrot` alone (no native wheel) provides functional
      PII redaction via the Python engine; fallback logs one INFO line.
- [ ] With `ai-parrot[pii-native]` installed, `get_engine()` selects the
      Rust engine automatically with zero behavior difference (parity suite
      green on the shared corpus).
- [ ] Native benchmark gates met: p99 < 100 µs @ 1 KB clean, < 1 ms @ 10 KB.
- [ ] Default off: `enable_pii_protection=False`; no behavior change for
      existing bots (full test suite passes untouched).
- [ ] `detect_only` mode audits (entity id + tool name, never the value)
      without rewriting any text.
- [ ] Per-agent `allow_entities` lets a designated agent emit listed PII
      while other agents' outputs are scrubbed.
- [ ] Catalog overlays can disable, re-score, or replace builtin entities
      and add new ones without code changes; invalid regex (outside the
      Rust subset) is rejected at load time.
- [ ] Secrets scrub (FEAT-252) still runs first and unconditionally;
      `parrot/security/redaction.py` is unmodified.
- [ ] Pseudonymization round-trip holds: LLM context contains only tokens;
      user-facing response has restored values; unknown tokens degrade to
      literals with a WARNING.
- [ ] `RedisPseudonymStore` persists only AES-GCM ciphertext; token maps
      never appear in logs.
- [ ] Streaming invariant: concatenated streamed output equals the
      non-streaming scrub of the same text; redaction markers/tokens are
      never split across chunks; holdback ≤ 128 chars.
- [ ] In `enforce` mode, memory and observability store scrubbed text on
      both `ask()` and `ask_stream()` paths.
- [ ] Documentation updated in `docs/` (enable/rollout guide:
      off → detect_only → enforce).
- [ ] No breaking changes to the existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below were re-verified on 2026-07-20 on branch
> `claude/pii-detection-ai-parrot-a48mat` (based on `origin/dev`).

### Verified Imports

```python
from parrot.security.redaction import OutputScrubber, ScrubPolicy  # verified: tools/abstract.py:53 imports it this way (relative)
from parrot.observability.context import current_agent_name  # verified: bots/base.py:56
from parrot.memory.redis import RedisConversation  # verified: memory/redis.py:10
from parrot.security.credentials_utils import encrypt_credential  # verified: security/credentials_utils.py:19
from redis.asyncio import Redis  # verified: memory/redis.py:4
```

(Paths below are relative to `packages/ai-parrot/src/parrot/`.)

### Existing Class Signatures

```python
# tools/abstract.py
class ToolResult(BaseModel):  # line 88 — fields .result / .error / .metadata are what gets scrubbed
def _default_scrubber():      # lines 59-65 — module-level OutputScrubber singleton, lazy init
# FEAT-252 egress hook: lines 695-724 inside AbstractTool.execute();
#   in-code comment: "This is the ONLY place scrubbing happens on the way out".
#   Non-fatal try/except wraps the scrub (lines 700-724) — the PII pass MUST
#   live inside this same block, after the secrets scrub.
# AfterToolCallEvent emitted at line 728.

# security/redaction.py
@dataclass(frozen=True)
class ScrubPolicy:            # lines 127-146: reason_tags, audit_log, allowlist, max_output_bytes=1 MiB
def _already_scrubbed(text: str) -> bool:  # lines 122-124 — idempotency guard pattern to mirror
class OutputScrubber:         # line 149 — scrub() recursive over str/dict/list/tuple; _audit logs tag+tool only

# bots/abstract.py
class AbstractBot:            # __init__ kwargs convention around lines 283-400 (e.g. self.enable_tools at ~383-400)
    def get_response(         # line 3390 — sync; every non-streaming path funnels the AIMessage here

# bots/base.py
async def ask_stream(         # line 1566; chunks yielded at 1772-1773; final AIMessage at 1846
# current_agent_name ContextVar set/reset at lines 196/220, 605/772, 964/1564, 1589 (FEAT-228)

# memory/redis.py
class RedisConversation(ConversationMemory):  # line 10
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True)
    # Redis.from_url(REDIS_HISTORY_URL, decode_responses=True, timeouts=5s, retry_on_timeout=True)
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str  # "prefix:chatbot:user:session"

# security/credentials_utils.py
def encrypt_credential(...)   # line 19 — AES-GCM via navigator_session.vault.crypto.encrypt_for_db
# payload layout: [key_id 2B uint16 BE][nonce 12B][encrypted_payload + tag], base64-encoded
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PIIScrubber` | FEAT-252 egress hook | chained call after `_scrubber.scrub(...)` inside the same try/except | `tools/abstract.py:695-724` |
| PIIPolicy registry | `current_agent_name` ContextVar | lookup at scrub time | `bots/base.py:56,1589` |
| response redact/restore | `AbstractBot.get_response()` | text rewrite before return | `bots/abstract.py:3390` |
| `StreamingPIIFilter` | `ask_stream` chunk loop | wrap `yield chunk` + flush before final `AIMessage` | `bots/base.py:1772-1773,1846` |
| `RedisPseudonymStore` | Redis infra conventions | `redis.asyncio`, `REDIS_HISTORY_URL`, key-prefix scheme | `memory/redis.py:10-42` |
| `RedisPseudonymStore` payloads | AES-GCM helpers | `encrypt_credential`/`decrypt_credential` | `security/credentials_utils.py:19+` |
| `pii-rs` packaging | maturin/cibuildwheel wiring | copy `yaml-rs` model (own pyproject, dist, import-fallback) | `parrot/yaml-rs/`, core `pyproject.toml:608-622`, fallback pattern `outputs/formats/yaml.py:5-9` |
| detection counters | lifecycle observers | attach to existing events, no new types | `tools/abstract.py:728`, `bots/base.py:1505,1838` |

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
- ~~`cryptography`/`Fernet` direct dependency~~ — encryption goes through
  `navigator_session.vault.crypto` helpers wrapped by
  `security/credentials_utils.py`.
- ~~FEAT-316 as this feature's id~~ — FEAT-316/317/318 belong to the
  eventbus migration specs; this feature is FEAT-319.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first throughout; `PIIEngine.scan` is deliberately sync (pure CPU,
  sub-ms budget; `get_response()` is sync) — the Rust engine releases the
  GIL internally for large inputs.
- Pydantic models for catalog/policy/spans; Google-style docstrings; strict
  type hints; `self.logger`, never print.
- Mirror `OutputScrubber` exactly: recursive traversal, idempotency guard,
  audit logs carry entity id + tool name and **never the value**, non-fatal
  failure contract at the seam.
- Bot config via the kwargs convention (`enable_tools` precedent); policy
  shape modeled on `ObservabilityConfig` (`observability/config.py:18`).
- Rust: pyo3 0.29 `Bound` API, `crate-type = ["cdylib"]`, release profile
  `opt-level=3, lto=true` — copy `yaml-rs` verbatim as packaging template.
- Validators are a **fixed enum implemented twice** (Python + Rust); a
  catalog can never inject code.

### Known Risks / Gotchas

- **Regex parity**: Rust `regex` lacks lookaround/backrefs — enforced at
  catalog load; the parity suite makes the constraint self-enforcing.
- **False positives** (phones vs order numbers, SSN vs timestamps):
  mitigated by context scoring + `min_score` + documented
  `detect_only`-first rollout; residual risk accepted, revisit with
  telemetry.
- **Pseudonym map is itself PII**: in-memory backend evicts on TTL; Redis
  backend stores ciphertext only; after eviction/restart, restore degrades
  to literal tokens (logged) — documented limitation.
- **Wheel coverage**: initial matrix manylinux x86_64 only (macOS/ARM get
  the Python fallback, logged once); extending the matrix is a follow-up.
- **Oversized payloads**: follow the `max_output_bytes` wholesale-action
  precedent from `ScrubPolicy`.
- **Streaming UX**: holdback delays at most the last ≤128 chars; confirm
  acceptable for voice consumers (open question #9).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pyo3` (Rust) | 0.29 | crate bindings (same as `yaml-rs`) |
| `regex` (Rust) | latest 1.x | `RegexSet` multi-pattern DFA |
| `aho-corasick` (Rust) | transitive | context-word scanning |
| `serde` / `serde_json` (Rust) | 1.x | catalog JSON → compiled engine |
| `maturin` | ==1.9.6 (already in dev deps) | crate build backend |
| — (Python core) | — | **no new Python runtime dependencies** |

---

## Worktree Strategy

- **Default isolation unit**: mixed.
- **Sequencing**: Module 1 first, sequentially, in one worktree — it freezes
  the `PIIEngine` protocol, catalog schema, and seam integration everything
  else builds on. After M1 merges: Module 2 (`pii-rust-engine`) and
  Module 3 (`pii-pseudonymization`) are **parallelizable in separate
  worktrees** (disjoint files: `pii-rs/` crate + `native_engine.py` vs
  `pseudonym.py` + `get_response()` wiring). Module 4 follows M1 (touches
  `bots/base.py` `ask_stream`; serialize with M3 only if M3's restore-wiring
  lands in the same region).
- **Cross-feature dependencies**: none blocking. Before cutting worktrees,
  check in-flight specs touching `tools/abstract.py` / `bots/base.py`
  (the eventbus migration FEAT-316/317/318 touches broker/event modules,
  not these seams).

---

## 8. Open Questions

> Carried forward from the brainstorm with their resolution state.
> Resolved answers are reflected in the spec body (§1, §2, §3, §7).

- [x] Regex-syntax parity: enforce the Rust `regex` subset from day 1 —
  *Resolved in spec round*: yes; catalog validation rejects
  lookaround/backrefs at load time (§2 Overview, §7 Risks).
- [ ] False positives: are context scoring + `min_score` + `detect_only`
  sufficient, or is a per-tool suppression list needed? — *Owner: Jesús*
  (defer to implementation telemetry)
- [x] Default posture — *Resolved in brainstorm/plan round*: opt-in
  (`enable_pii_protection=False`); revisit default-on only after
  `detect_only` telemetry (§1 Goals, §5).
- [x] PII at rest — *Resolved in spec round*: in `enforce` mode, memory and
  observability store scrubbed text on **both** `ask()` and `ask_stream()`
  paths (§1 Goals, §5, integration table).
- [x] Pseudonym store backend — *Resolved in spec round*: ship
  `AbstractPseudonymStore` with in-memory (TTL/LRU) **and** encrypted-Redis
  (AES-GCM via `credentials_utils`) backends in this feature (§3 Module 3).
- [ ] Wheel matrix: manylinux x86_64 first; when to add macOS/ARM? —
  *Owner: Jesús* (follow-up, fallback covers the gap)
- [ ] PII split across formatting (table cells / JSON keys): document as
  limitation only, or add a normalization pre-pass later? — *Owner: Jesús*
- [x] NER-class entities — *Resolved in spec round*: out of scope for
  FEAT-319; `PIIEngine` protocol is the extension point for a future
  `SpacyNerEngine` (§1 Non-Goals).
- [ ] Streaming UX for voice consumers (holdback ≤128 chars acceptable?) —
  *Owner: Jesús*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-20 | Jesús Lara / Claude Code | Initial draft from `pii-detection-redaction.brainstorm.md`; FEAT id corrected 316→319 |
