# TASK-3519 Research: Audit every Google generation path for enforceable budgets

**Feature**: FEAT-581 — Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md` (Module M6)
**Type**: Research / spike (M6 spike gate). No runtime code is authorized or
produced by this task; see "Not implemented" below.

## 1. Baseline and method

| Artifact | Identity |
|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | SHA-256 `6ee140ced87407e91f5a930223b5836b1923a52b5effad954c83ee054f3f2df5` (matches the task's Codebase Contract — fresh) |
| `packages/ai-parrot/src/parrot/clients/base.py` | SHA-256 `863ea53efa14b2da4446966c3baf2d6a88c11711c8bf6963947e881eac30301b` |
| `packages/ai-parrot-server/src/parrot/e2e/errors.py` | SHA-256 `f63146c6b1472eb42e7218d8668a4041fc4af16a216cff65b39c029bc419f9b6` |
| Worktree HEAD | `daa09cd04` on `feat-FEAT-581-agentic-e2e-testing--TASK-3519-a1-f1ace2e8c26a4a9783ed1239a6c3c1bb` |
| `google-genai` SDK (installed, read-only shared `.venv`) | `2.24.0` (`ai-parrot-client-google` declares floor `>=2.23.0`) |

Method: static source audit of `client.py` (5777 lines) cross-referenced
against the installed `google-genai==2.24.0` SDK internals
(`_api_client.py`, `_extra_utils.py`, `chats.py`, `models.py`, `types.py`),
plus one **counting fake-transport** experiment (`unittest.mock` replacing
`google.genai.Client`, no network I/O, no paid calls) that empirically
verifies request counts and a config-mutation hazard the static trace alone
would not have surfaced. No paid model request was made or is required by
this research, per the task's completion rule.

Commands actually run (worktree-local; `.so` extensions copied in from the
read-only main checkout per the task dispatch note and removed before
commit — see §7):

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src \
  python3 -m pytest packages/ai-parrot/tests/test_google_client.py -q
# -> 61 passed, 8 warnings  (artifacts/logs/task-3519-pytest-baseline.log)

python3 artifacts/task3519_probe.py
# -> counting fake-transport probe (artifacts/logs/task-3519-counting-fake-probe.log)
```

## 2. Send-site inventory — every nonstreaming Google request in `client.py`

All line numbers are against the SHA-256 above. "1 request" means one
`await chat.send_message(...)` or one `await self.client.aio.models.generate_content(...)`
call — see §3 for why each of these is exactly one HTTP call regardless of
AFC/tool configuration.

| # | Site | Method | Lines | Loop / cardinality | In `ask()` call graph? |
|---|---|---|---|---|---|
| 1 | Initial chat send | `chat.send_message` | 3401 | `while retry_count < max_retries` (default `max_retries=2`, `kwargs.pop("max_retries", 2)`) — MAX_TOKENS-with-small-cap and MALFORMED_FUNCTION_CALL retry in place; network-error/capacity-error retry (with optional fallback-model swap) wraps the same call | Yes — `ask()` line 3040 |
| 2 | Tool-continuation send | `chat.send_message` | 2207 | Inside `_handle_multiturn_function_calls`'s `while iteration < max_iterations` (default 15); inner `while retry_count < max_retries` around this one send | Yes — round 2..N of `ask()`/`resume()` |
| 3 | Forced final synthesis send | `chat.send_message` | 2374 | Exactly once, only if the iteration cap is hit while the model still wants tools ("hidden" extra send not named in the Scope's four categories, but real and unconditional on that state) | Yes — `_handle_multiturn_function_calls` tail |
| 4 | Structured-repair (inline, non-combined mode) | `client.aio.models.generate_content` | 3657 | Exactly once, only when `structured_output_for_later and use_tools and assistant_response_text` | Yes — `ask()` two-phase structured-output path |
| 5 | Structured-repair (combined-mode recovery) | `_reformat_to_structured` → `generate_content` | 3706, 3723 → 1137 | Exactly once, only on combined-mode parse failure | Yes — `ask()` combined-mode fallback |
| 6 | `resume()` initial injected-response send | `chat.send_message` | 5537 | `while retry_count < max_retries` (local `max_retries=3`, hardcoded, independent of `ask()`'s) | Yes — `resume()` is a *separate* AbstractClient entry point, not called from `ask()` |
| 7 | `resume()` continuation | `chat.send_message` | 2207 (shared helper) | Same `_handle_multiturn_function_calls` as #2/#3, invoked from `resume()` at line 5546 | Yes — `resume()` |
| 8 | `invoke()` two-call tool phase | `generate_content` | 5650 | Exactly once (`needs_two_call` branch, first call) | **No** — `invoke()` is independent of `ask()`; **no retry loop of its own** |
| 9 | `invoke()` two-call structured phase | `generate_content` | 5672 | Exactly once | Same as #8 |
| 10 | `invoke()` single-call path | `generate_content` | 5702 | Exactly once | Same as #8 |
| 11 | `invoke()` structured-repair fallback | `_reformat_to_structured` → `generate_content` | 5748 → 1137 | Exactly once, only if `isinstance(output, str) and output.strip()` after primary parse | Same as #8 |
| 12 | `ask_stream()` embedded non-streaming repair | `generate_content` | 4338, 4352, 4406 | Exactly once per branch, inside an otherwise-**streaming** call | **Out of v1 budget scope** (spec: "streaming ... disabled for budgeted v1") but is a real hidden nonstreaming HTTP call the budget hook will NOT see if wired only into `ask()` |
| 13 | `question()` stateless RAG call | `generate_content` | 5398 | Exactly once, **no retry loop at all** | **No** — `question()` is a Google-client-only legacy method, not part of `AbstractClient`; unguarded regardless of hook |
| 14 | `_deep_research_ask()` | `self.client.interactions.create(...)` (streaming interactions API, not `generate_content`) | ~5184 | N/A — different SDK surface entirely | **Explicitly out of scope** — spec: "batch/deep-research ... disabled for budgeted v1"; routed from `ask(deep_research=True)` at line 3095, *before* any of the above sites execute |
| 15 | `ask_batch()` | not audited in depth | 4565+ | N/A | **Explicitly out of scope** — spec excludes batch for budgeted v1 |
| 16 | `ask_to_image()` | `generate_content` (multimodal) | ~5000+ | Has its own local retry loop (`_retry_delay` at 5090-5106) | **Explicitly out of scope** — spec excludes multipart/media for budgeted v1 |

**Finding — legacy/unguarded gaps outside the M6 hook's reach even after
implementation**: `question()` (#13) and the embedded `ask_stream()` repair
calls (#12) are real nonstreaming HTTP call sites that a hook placed only
inside `ask()`/`resume()`/`invoke()` will never see. The spec's "Existing
callers without the hook keep current behavior" sentence covers this
correctly for `invoke()`/`question()` (no hook wired there in v1), but it
means these two sites remain **structurally un-budgetable** without
touching `ask_stream()`, which the spec explicitly puts out of v1 scope.
This is not a blocker for M6 (the spec already scopes it out), but the M6
task packet must say so explicitly rather than silently ignore it.

## 3. SDK retry / AFC verification (installed `google-genai==2.24.0`)

### 3.1 HTTP-level automatic retries are OFF by construction, not by an explicit disable

- `GoogleGenAIClient.get_client()` (client.py:631-692) never sets
  `http_options.retry_options`. `HttpOptions.retry_options` (SDK
  `types.py:2685-2687`) defaults to `None`.
- SDK `_api_client.py:562-594` `retry_args(options)`: when `options is None`
  → `{'stop': tenacity.stop_after_attempt(1), 'reraise': True}` — **no
  retry, first failure raises**. A configured `HttpRetryOptions` would
  default to 5 attempts (`_api_client.py` docstring on `HttpRetryOptions`,
  `types.py:2596-2599`), 1.0s initial delay, 60s max delay, exp_base 2.0.
- **Conclusion**: every retry currently observed in `client.py` (MAX_TOKENS,
  MALFORMED_FUNCTION_CALL, network/capacity errors, 429/503) is parrot's own
  `while retry_count < max_retries` application-level loop, not an SDK
  auto-retry. The SDK is already "disabled" for retries by omission. A
  budgeted mode should still set `HttpRetryOptions(attempts=1)` **explicitly**
  on the client used for budgeted calls — not to change behavior (it is
  already effectively `attempts=1`), but so the "disabled" contract does not
  silently depend on an SDK default that could change across a `google-genai`
  upgrade. This is a documentation/robustness recommendation, not a behavior
  change to freeze now.

### 3.2 Automatic Function Calling (AFC) never loops for parrot's tool shape

- SDK `_extra_utils.should_disable_afc()` (line 447-476): "Default to enable
  AFC if not specified" — i.e. AFC is *nominally* on unless
  `automatic_function_calling.disable=True` is set. `client.py` only sets
  `disable=True` explicitly for `tool_type == "computer_use"` (line
  3332-3336); every other tool-bearing call leaves AFC at its SDK default
  (enabled).
- However, SDK `_extra_utils.get_function_map()` (line 172-205) only adds an
  entry when `callable(tool)` — i.e. when the SDK was handed a **Python
  function** as a tool. `GoogleGenAIClient._build_tools()` always returns
  `types.Tool(function_declarations=[...])` objects (raw JSON-schema
  declarations), which are never `callable`. Verified directly:
  `types.Tool` instances are pydantic models, not callables.
- Consequence, verified in three independent SDK call sites:
  - `AsyncModels.generate_content` (`models.py:8445-8478`): the AFC
    `while remaining_remote_calls_afc > 0:` loop calls `_generate_content`
    once, then `if not function_map: break` — **exactly one HTTP call**.
  - `AsyncChat.send_message` (`chats.py:793-814`): identical shape —
    `function_map` computed once before the loop, `if not function_map ...:
    break` after the first `generate_content` — **exactly one HTTP call**.
  - Same pattern in the sync `Models.generate_content_stream` /
    `AsyncModels` paths (not used by `client.py`, checked for completeness).
- **Conclusion**: for parrot's declaration-only tools, AFC's "enabled by
  default" nominal state produces **zero** hidden extra HTTP requests
  today — the observed retry/round multiplication in `client.py` is
  entirely parrot's own loop logic (§2), never SDK-internal AFC looping.
  `should_disable_afc()`'s default max remote calls
  (`_DEFAULT_MAX_REMOTE_CALLS_AFC = 10`, `_extra_utils.py:54`) is therefore
  currently moot for this codebase's tool shape. This is a fact about the
  *current* code, not a permanent guarantee: if a future change ever passes
  a bare Python callable as a `tools=[...]` entry instead of a
  `types.Tool(function_declarations=...)`, AFC would start looping silently
  inside a single `chat.send_message()`/`generate_content()` call, invisible
  to a budget hook wrapping only the call boundary. **Recommendation for the
  M6 implementation task**: the budgeted-mode config should set
  `automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`
  unconditionally (not just for `computer_use`) as defense-in-depth, exactly
  mirroring the existing computer_use precedent at line 3332-3336, so a
  future tool-shape change cannot silently reintroduce hidden AFC requests
  under a live budget.

### 3.3 Byte-serialization seam for the 16384-byte request ceiling

- `types.Content`, `types.Part`, `types.GenerateContentConfig` and
  `types.Tool` are all `google.genai._common.BaseModel` (pydantic v2)
  subclasses — verified directly:
  `types.Content(role="user", parts=[types.Part(text="hello")]).model_dump_json()`
  returns valid JSON, `len(...encode())` gives a byte count.
- **No existing helper in `client.py` composes the full "rendered history +
  system instruction + tool definitions/results + new prompt" payload into
  one byte count.** `_estimate_tokens()` (line 448-457) is a `len(text)//4`
  heuristic over a plain string only — it does not serialize `Content`/`Tool`
  objects and is not wired to any request boundary; it currently backs only
  the Gemini prompt-cache heuristic (`_apply_cache_hints`, line 459-508).
- **Frozen approach for M6**: `GenerationBudget.reserve()` must be called
  with a `request_bytes` value the *caller* (client.py) computes by
  `model_dump_json()`-serializing the `Content` list passed as `history=`,
  the `system_instruction` string, the `tools` list, and the outgoing
  message parts, summing UTF-8 byte lengths. This is new code that belongs
  in `budget.py` or a `client.py` helper — it does not exist today under any
  name.

## 4. Counting fake-transport experiment (empirical, no paid calls)

Script: `artifacts/task3519_probe.py` (gitignored under `artifacts/`, not a
task deliverable — deleted after this doc is written per file-scope rules).
Log: `artifacts/logs/task-3519-counting-fake-probe.log`.

Patches `parrot.clients.google.client.genai.Client` with a `MagicMock`,
replaces `chat.send_message` / `client.aio.models.generate_content` with
`AsyncMock(side_effect=...)` counters that return scripted `MagicMock`
responses shaped like real Gemini `GenerateContentResponse` objects (with
`.candidates[0].finish_reason.name` and `.candidates[0].content.parts`).
Drives real `GoogleGenAIClient.ask()`.

| Scenario | Expected sends | Observed | Result |
|---|---|---|---|
| S1: no-tool `ask()`, single STOP response | 1 | 1 (`send_message` ×1) | PASS |
| S2: initial response returns `MAX_TOKENS` with `max_tokens=100` (`_resolve_max_tokens` cap ≤1024) | 2 (initial + 1 retry) | 2 | PASS |

**S2 config-mutation finding (verified, not assumed)**: the probe recorded
`config.max_output_tokens` **at call time** for both sends (a first attempt
gave a reference-aliasing false positive — the same `GenerateContentConfig`
object is mutated in place by parrot's own retry code between attempts, so
naively storing the object reference and inspecting it after the loop
reports every earlier call as showing the *final* value; the probe was
corrected to snapshot the scalar immediately inside the fake transport call,
consistent with this backend's history of `hasattr`/duck-typing findings
promoted here to "snapshot state at the moment of definitive signal, not
after"). Corrected readings:

```
call[0] config.max_output_tokens (at call time) = 100
call[1] config.max_output_tokens (at call time) = 8192
```

This confirms in running code, not just by reading, the exact line-3410
behavior: **on a MAX_TOKENS retry, `client.py` unconditionally jumps the cap
to a hardcoded `8192`, ignoring the caller's original ceiling.** The
`_handle_multiturn_function_calls` continuation-send retry (line 2207-2215)
has the identical hardcoded-`8192` growth. Per spec §"Live Provider Budget"
("Token growth on MAX_TOKENS is clamped to the budget ceiling"), a budgeted
mode's `reserve()` call must intercept this line and clamp the retried
`max_output_tokens` to `min(8192, budget.output_ceiling)` (spec ceiling:
512) — **today's code does not do this and will violate the 512-token
output ceiling on its very first MAX_TOKENS retry if the hook is not wired
at exactly this mutation point**, not just at the network-dispatch boundary.
This is the single most important frozen-contract implication of this
audit: **the reservation/clamp must happen after finish_reason is known,
not only before `send_message`**, because the retry-cap mutation happens
*between* two sends of the same round.

Continuation sends (§2 row 2) and structured-repair sends (§2 rows 4-5,
8-11) were **not** re-verified via the fake transport (would require
constructing `ToolManager`-registered declarations end-to-end, out of
scope/time for a research spike) — their cardinality is instead frozen by
direct, deterministic static trace: each is a single, unconditional
`await` inside its `if`/`while` block with no nested SDK call, and §3.2
proves the SDK itself cannot multiply any of them via AFC for this
codebase's tool shape. This is recorded as **verified-by-static-trace**,
not verified-by-execution, and should be upgraded to executed coverage by
the M6 implementation task's own test suite
(`test_generation_budget_all_send_paths`, spec line 527).

## 5. Frozen contract for the M6 implementation task

```python
# packages/ai-parrot-client-google/src/parrot/clients/google/budget.py (NEW — not created by this task)

class GenerationBudgetExceeded(Exception):
    """Non-retryable: raised by GenerationBudget.reserve() on exhaustion.

    Lives in ai-parrot-client-google, which does NOT depend on
    ai-parrot-server (verified: no `ai-parrot-server` entry in
    packages/ai-parrot-client-google/pyproject.toml `dependencies`).
    It therefore CANNOT subclass parrot.e2e.errors.E2EBudgetError
    (packages/ai-parrot-server/src/parrot/e2e/errors.py:106-114,
    `E2EBudgetError(E2EError)`, exit_code=1, ctor
    `(message: str, *, reason_code: Optional[str] = None)`) — that
    class lives in the opposite-direction package. The live E2E actor
    in parrot/e2e/live.py (M6, not yet created) must catch
    GenerationBudgetExceeded by type and re-raise/wrap it as
    E2EBudgetError at the harness boundary — a plain except+re-raise
    adapter, not a shared exception hierarchy.
    """

class GenerationBudget:
    """Per-run nonstreaming Google budget; reserves before network attempts."""

    async def reserve(self, *, request_bytes: int, output_tokens: int) -> None:
        """Atomically reserve an attempt or raise GenerationBudgetExceeded.

        Call sites (frozen, from §2 — ALL nonstreaming `ask`/`resume` sends):
          - client.py:3401  initial chat.send_message
          - client.py:2207  tool-continuation chat.send_message (loop body)
          - client.py:2374  forced-synthesis chat.send_message (iteration-cap tail)
          - client.py:3657  inline structured-repair generate_content
          - client.py:1137  _reformat_to_structured generate_content
            (shared by call sites at 3706/3723/4338/4352/5748)
          - client.py:5537  resume() initial chat.send_message
        NOT wired in v1 (existing callers keep current behavior, spec-authorized):
          - invoke() (client.py:5650/5672/5702/5748 via _reformat_to_structured)
          - question() (client.py:5398) — legacy, non-AbstractClient method
          - ask_stream() embedded repair (client.py:4338/4352/4406) — streaming
            is out of v1 budget scope per spec, but this IS a real hidden
            nonstreaming call the hook will not see even after M6 ships.
          - _deep_research_ask() / ask_batch() / ask_to_image() — explicitly
            excluded by spec ("deep-research and streaming are disabled for
            budgeted v1"; "Multipart/media ... disabled for budgeted v1").
        MUST intercept the MAX_TOKENS retry-cap mutation at client.py:3410
        and client.py:2214 (both hardcode `= 8192`), clamping to
        min(8192, configured output ceiling) — verified in §4 that these
        lines execute a second, un-budgeted growth mid-round.
        """
```

`GoogleGenAIClient.__init__` accepts an optional `generation_budget:
Optional[GenerationBudget] = None` constructor kwarg; when `None` (the
default), behavior is provably unchanged since no code path currently
reads such an attribute (grepped: no existing reference to
`generation_budget` anywhere in `client.py`). No change to
`packages/ai-parrot/src/parrot/clients/base.py` is required or authorized
— `GenerationBudget`/`GenerationBudgetExceeded` are new, `ai-parrot-client-google`-local types, not an `AbstractClient` extension point.

### Budgeted-mode SDK settings (frozen)

- `http_options=HttpOptions(retry_options=HttpRetryOptions(attempts=1))` set
  explicitly on the budgeted `genai.Client()` construction (defense against
  a future SDK default change; behaviorally a no-op today per §3.1).
- `automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`
  set unconditionally in budgeted mode on every `GenerateContentConfig`,
  mirroring the existing `computer_use` precedent (client.py:3332-3336) —
  defense against a future tool-shape change reintroducing hidden AFC
  requests (§3.2); behaviorally a no-op today for declaration-only tools.
- Wrapper-level retries (parrot's own `while retry_count < max_retries`
  loops) each consume one additional `reserve()` call — the spec is
  explicit that "wrapper-level retries consume another reservation."

## 6. Unsupported budgeted modes / legacy no-hook behavior (frozen)

Per spec §"Live Provider Budget" and this audit, budgeted v1 explicitly
excludes and MUST reject/bypass (not silently degrade) the following
modes when a `generation_budget` is set:

- `deep_research=True` (routes to `_deep_research_ask`'s
  `interactions.create` streaming API before any budgeted send site runs).
- `ask_stream()` (streaming) — including its embedded nonstreaming repair
  calls at 4338/4352/4406, which remain **unbudgeted even in a world where
  M6 ships**, per §2 finding.
- `ask_batch()`, `ask_to_image()` (batch/multipart/media).
- File-based prompt caching (`_maybe_apply_gemini_cache`,
  `_apply_cache_hints`) — spec: "remote caching ... disabled for budgeted
  v1"; these paths currently execute unconditionally whenever
  `system_prompt` is a `List[CacheableSegment]` (client.py:3343-3346),
  independent of any budget, so a budgeted caller must not pass segment
  lists, or `budget.py` must explicitly refuse them.
- `invoke()` and `question()` remain entirely **unguarded legacy
  behavior** with no `generation_budget` hook in v1 — this is
  spec-authorized ("Existing callers without the hook keep current
  behavior") but should be stated explicitly in the M6 task packet as a
  known, permanent (not just "not yet done") gap, since `invoke()` has
  no `max_retries` loop of its own to attach a budget-aware clamp to in
  the first place (§2 row 8-11).

An unresolved bypass here — i.e., any budgeted-mode call reaching
`_deep_research_ask`, `ask_stream`, `ask_batch`, `ask_to_image`, or the
cache-segment path without an explicit `GenerationBudgetExceeded` or a
documented refusal — blocks the M6 guard implementation per this task's
completion rule ("unresolved bypasses block the guard implementation").
This audit found no code path today that would silently let a budgeted
`ask()` call reach any of these excluded surfaces (they are all gated by
distinct, mutually exclusive `if` branches at the top of `ask()`), so no
bypass is currently open — but the M6 implementation must add an explicit
guard/test for each, since "not currently reachable" is not the same as
"structurally prevented."

## 7. Disposition per Scope question

| Scope question | Disposition |
|---|---|
| Enumerate nonstreaming initial/continuation/repair/retry/fallback/hidden requests with exact anchors | **PASS** — §2, 16 call sites enumerated with line numbers, cardinality and call-graph membership. |
| Verify SDK retry/AFC disabling; how request bytes include system/history/tools/results; wrapper seams and error propagation | **PASS** — §3: SDK retries off-by-omission (verified in SDK source), AFC never loops for parrot's tool shape (verified in SDK source, three call sites), byte-serialization seam identified (`model_dump_json()` on pydantic `BaseModel` SDK types, verified interactively), no existing full-payload byte helper (grepped). |
| Freeze `GenerationBudget` constructor, exception type, optional client hook placement, no `clients/base.py` change, counting local fake transport, no paid calls | **PASS** — §5: contract frozen with exact call-site line numbers, exception-type package-boundary constraint verified against `pyproject.toml`, `client.py:1051` region (`_reformat_to_structured` def line, cited by spec) confirmed as one of the anchors; fake-transport experiment run and logged (§4), zero paid calls. |
| Document unsupported budgeted modes and legacy no-hook behavior; unresolved bypasses block guard implementation | **PASS** — §6: five excluded surfaces documented with line anchors; no open bypass found in current code between `ask()`'s mode-dispatch `if` branches. |

No question required a BLOCKED disposition — no live API key, network
access, or paid model call was needed to complete this audit; everything
was verified by static source reading of the worktree's own `client.py`,
the read-only shared venv's installed `google-genai==2.24.0` internals, and
one no-network counting fake-transport run.

## 8. Rejected assumptions

- **Rejected**: "AFC being nominally enabled by default (`disable=None`)
  means hidden multi-round HTTP calls happen today." Verified false — the
  `function_map` is always empty for `types.Tool(function_declarations=...)`
  tools, so the AFC loop always exits after exactly one call regardless of
  the `disable` flag's value (§3.2).
- **Rejected**: "SDK auto-retries are already explicitly disabled by
  parrot's code." Verified false — no `http_options.retry_options` is ever
  set; the "no retry" behavior is the SDK's *default when unconfigured*
  (`retry_args(None)`), not an explicit `attempts=1` set by `client.py`.
  Freezing budgeted mode to *explicitly* set `attempts=1` is a
  recommendation in §3.1/§5, not a claim about current behavior.
- **Rejected**: "The 4096-input-token brainstorm estimate is what v1
  enforces." Spec explicitly supersedes this with a 16384-byte serialized
  request ceiling, 512 output tokens, 4 attempts, 60s deadline (spec
  §"Live Provider Budget") — confirmed by reading the spec directly, not
  inferred.
- **Rejected (self-correction during this audit)**: an initial reading of
  the S2 fake-transport probe's `config.max_output_tokens` values, taken
  from a stored reference to the shared, mutable `GenerateContentConfig`
  object *after* the retry loop completed, reported `8192` for the
  first call too — this was an artifact of reference aliasing (the object
  is mutated in place by `client.py`'s own retry code between attempts),
  not evidence that the first attempt was already sent at the grown cap.
  Corrected by snapshotting the scalar value at call time (§4).

## 9. Not implemented (explicitly out of this task's scope)

Per the task's Scope/Codebase Contract, this task produced **research
only**. Not created: `packages/ai-parrot-client-google/src/parrot/clients/google/budget.py`,
any `GenerationBudget`/`GenerationBudgetExceeded` runtime code, any change
to `client.py`, `clients/base.py`, or `parrot/e2e/live.py`. The probe script
(`artifacts/task3519_probe.py`) and its log are scratch verification
evidence under the gitignored `artifacts/` directory, not a task
deliverable, and were removed from the working tree before this task's
commit (confirmed via `git status --porcelain`).
