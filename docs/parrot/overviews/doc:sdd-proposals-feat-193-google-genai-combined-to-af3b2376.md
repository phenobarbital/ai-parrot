---
type: Wiki Overview
title: 'FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
  for newer Gemini models'
id: doc:sdd-proposals-feat-193-google-genai-combined-tools-and-schema-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. The full source is at `sdd/state/FEAT-193/source.md`.
---

---
id: FEAT-193
title: Enable simultaneous tool-calling + structured output in GoogleGenAIClient for newer Gemini models
slug: google-genai-combined-tools-and-schema
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-27
  summary_oneline: Allow ask()/ask_stream() to send tools+response_schema in a single GenerateContentConfig for whitelisted Gemini 3.x models, preserving the two-phase fallback for older ones.
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-193/
created: 2026-05-27
updated: 2026-05-27
---

# FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output for newer Gemini models

> **Mode**: enrichment
> **Confidence**: high
> **Source**: inline — *user analysis from `examples/google/test_tool_structured_output.py`*
> **Audit**: [`sdd/state/FEAT-193/`](../state/FEAT-193/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-193/source.md`.

> *De acuerdo a una última evaluación `examples/google/test_structured_output.py` hemos encontrado un partial acceptance de que los `gemini-3.1-flash-lite`, `gemini-3.5-flash` y `gemini-3.1-pro-preview` ahora aceptan Tool-Calling y Structured Output al mismo tiempo … modificar los métodos `ask()` y `ask_stream()` de `GoogleGenAIClient` para que: si el modelo es inferior a los definidos, mantener el flujo como está; pero si el modelo es de los definidos, realizar tool-calling y structured-output en una sola llamada combinada.*

**Initial signals** (extracted, not interpreted):
- Verbs: *"modificar"*, *"mantener"*, *"realizar … al mismo tiempo"* — direct enhancement request, not a bug.
- Named entities: `GoogleGenAIClient`, `ask()`, `ask_stream()`, `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`, `gemini-3.5-flash`, `gemini-2.5-pro`, `response_mime_type`, `response_schema`, `tools`, `structured_with_tools.py`.
- Components / labels: clients/google (provider), models/google (enum), examples/google (sample).
- Acceptance criteria provided: implicit via the user's task list (modify ask/ask_stream with a model gate + update the example).

---

## 1. Synthesis Summary

The Google GenAI client currently runs a deliberate **two-phase** flow whenever the caller asks for both tools and a structured output: a tool-calling chat first, then a separate `generate_content` call with `response_schema` to reformat the answer (documented at `clients/google/client.py:109-115` and gated at `:2036-2048`). Recent Gemini 3.x models (`gemini-3.1-pro-preview`, `gemini-3.5-flash`, and — with documented instability — `gemini-3.1-flash-lite-preview`) now accept `tools` + `response_mime_type` + `response_schema` in the same `GenerateContentConfig`. This proposal adds a configurable capability gate (`_supports_combined_tools_and_schema`) that, for whitelisted model prefixes, applies the schema in the single chat call and skips the deferred-reformat block at `clients/google/client.py:2337-2474` (and the streaming analogue at `:3020-3084`). Older or non-whitelisted models keep the existing two-phase behaviour untouched. The example `examples/google/structured_with_tools.py` will be parametrized to exercise the new path against each whitelisted model.

---

## 2. Codebase Findings

> All entries here are grounded in `sdd/state/FEAT-193/findings/`. Each cites the finding ID(s) that justify its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `GoogleGenAIClient.ask` | 1797-2547 | Primary surface — contains the two-phase gate (2036-2048) and the deferred-reformat call (2337-2474) | F001 |
| 2 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `GoogleGenAIClient.ask_stream` | 2649-3131 | Streaming surface — gate at 2847-2854, post-loop reformat at 3020-3084 | F002 |
| 3 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `_apply_structured_output_schema` | 750-771 | Schema-application helper (reusable as-is in combined mode) | F001 |
| 4 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `_is_gemini3_model` / `_requires_thinking` / `_as_model_str` | 156-204 | Existing static capability helpers — pattern to follow | F003 |
| 5 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `_default_reformat_model` (`_reformat_model`) | 109-152 | The fast model used for the second reformat call — bypassed in combined mode | F001 |
| 6 | `packages/ai-parrot/src/parrot/models/google.py` | `GoogleModel` | 9-39 | Model enum — has `gemini-3.1-pro-preview` and `gemini-3.1-flash-lite-preview`; **missing `gemini-3.5-flash`** (resolved in §5 / U1) | F005 |
| 7 | `examples/google/structured_with_tools.py` | `main` | 1-99 | Existing sample — hardcoded `gemini-2.0-flash`; needs model parametrization | F004 |
| 8 | `examples/google/test_tool_structured_output.py` | `main` / `test_model` | 1-85 | SDK-only evaluation that produced the user's analysis (single combined `GenerateContentConfig` against four model strings) | F004 |
| 9 | `packages/ai-parrot/tests/test_google_client.py` | `test_google_ask` / `test_google_ask_stream` | 8-101 | Pattern to follow for new combined-mode tests; no existing test covers tools + structured_output | F007 |

### 2.2 Constraints Discovered

- **Existing constraint comment is now stale for newer models.** `clients/google/client.py:109-110` reads: *"Gemini cannot combine tools + response_schema in one call."* This is true for `gemini-2.5-pro` (400 error per the user's SDK evaluation) but **false** for the 3.x whitelist. The comment must be revised, not deleted, since the two-phase fallback remains correct for the older models. *Evidence*: F001, F004.
- **Capability gating must remain prefix-based.** Existing helpers use `@staticmethod` + `.startswith()` (e.g. `_is_gemini3_model`, `_requires_thinking`). The new check should follow the same shape for readability and to keep Vertex-AI / Developer-API parity. *Evidence*: F003.
- **Cache, lifecycle events, conversation memory must survive the new branch.** The combined-mode branch must preserve `_pending_cache_segs` integration (client.py:2120-2157, FEAT-181), `_emit_after_call` lifecycle events (FEAT-176), and `_update_conversation_memory` so observability and prompt caching keep working. *Evidence*: F006.
- **Fallback flow is non-negotiable.** Older models must keep the two-phase reformat path; the user's directive ("si el modelo es inferior … mantener el flujo como está") is explicit. *Evidence*: F001 (gate at :2036-2048).
- **Reformat shortcut is dead in combined mode.** The fast-path JSON parse + `_reformat_model` second call (client.py:2337-2474 and :3020-3084) must be **skipped** when the capability check passes — running it would double-bill and add latency for no benefit, since the schema-compliant JSON arrives in the first call's text. *Evidence*: F001, F002.
- **`gemini-3.1-flash-lite` is documented as unstable in combined mode.** Upstream evaluation flags SDK warnings (`non-text parts in the response: ['function_call']`) and AFC infinite-loop risk. User accepts this trade-off (U2) but a debug log on first use of the model in combined mode should document the risk. *Evidence*: F004, F005.

### 2.3 Recent History (Relevant)

`git log --since="3 months ago" -- packages/ai-parrot/src/parrot/clients/google/` (last 9 entries):

| Commit | Message | Touched area |
|--------|---------|--------------|
| `c6333cb5` | fix(agnostic-prompt-caching-abstraction): address code-review issues | caching translator |
| `1428411a` | feat(agnostic-prompt-caching-abstraction): TASK-1224 — Google/Gemini client cache translator | caching |
| `47c68d22` | feat(lifecycle-events-system): TASK-1194 — Integrate EventEmitterMixin into AbstractClient | lifecycle events |
| `32d8221d` | adding more lazy-imports for heavy imports in components | imports |
| `e7b9850c` | fix(clients): apply context filtering to request-scoped tools | request-scoped tools |
| `8bea2542` | more fixes in google client | misc |
| `4b87acf3` | wip: fix multi-turn on stateless calls | stateless mode |
| `315585ad` | fix when google pro models are echoing thoughts | thinking_config for pro models |
| `12eb573b` | lazy-import of LLM clients | imports |

> **No commit in the last 3 months touches the two-phase reformat path itself** — the flow has been stable. FEAT-193 is the first reopening of that gate.

*Evidence*: F006.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`_supports_combined_tools_and_schema(model: str) -> bool`** — a new instance method (or `@staticmethod` with explicit prefix tuple) on `GoogleGenAIClient` that returns True when the model matches any prefix in the configurable whitelist.
- **`_combined_call_prefixes: tuple`** — a class-level default tuple (`("gemini-3.1-pro", "gemini-3.1-flash-lite", "gemini-3.5-flash")`) plus a constructor kwarg `combined_call_prefixes` that overrides it per-instance (per **U3 — configurable**).
- **`GoogleModel.GEMINI_3_5_FLASH = "gemini-3.5-flash"`** — new enum entry in `packages/ai-parrot/src/parrot/models/google.py`, plus any sensible alias (e.g. `GEMINI_FLASH_LATEST_STABLE`) so callers can reference the model symbolically (per **U1 — real model from Google's deprecations page**).

### What Changes

- **`packages/ai-parrot/src/parrot/clients/google/client.py::ask`** — the gate at lines **2033-2048** branches on `_supports_combined_tools_and_schema(model)`. When True: call `self._apply_structured_output_schema(generation_config, output_config)` immediately (do **not** set `structured_output_for_later = output_config`), so `tools=` and `response_schema=` both land in the SAME `GenerateContentConfig`. When False: keep the current deferral. *Evidence*: F001.
- **`packages/ai-parrot/src/parrot/clients/google/client.py::ask`** — the deferred-reformat block at **2337-2474** wraps its current behaviour in `if structured_output_for_later and use_tools and assistant_response_text:`. When combined mode is in effect, `structured_output_for_later` is `None`, so this block is naturally skipped — but the parsing of `assistant_response_text` into `final_output` must still happen (the model's text IS JSON that needs `_parse_structured_output` to validate against the schema). Add a new branch: combined-mode → call `_parse_structured_output(assistant_response_text, output_config)` directly, no second `generate_content`. *Evidence*: F001.
- **`packages/ai-parrot/src/parrot/clients/google/client.py::ask_stream`** — the gate at **2847-2854** changes from `if structured_output and not _use_tools` to `if structured_output and (not _use_tools or self._supports_combined_tools_and_schema(model))`. Symmetric to `ask()`. *Evidence*: F002.
- **`packages/ai-parrot/src/parrot/clients/google/client.py::ask_stream`** — the post-loop reformat block at **3020-3084** skips the reformat `generate_content` when combined mode is in effect, falling through to `_parse_structured_output(final_text, structured_output)`. *Evidence*: F002.
- **`packages/ai-parrot/src/parrot/clients/google/client.py:109-115`** — update the stale comment to reflect the new bifurcation (older models still go two-phase; whitelisted models go combined). *Evidence*: F001.
- **`packages/ai-parrot/src/parrot/models/google.py::GoogleModel`** — add `GEMINI_3_5_FLASH = "gemini-3.5-flash"` (and the equivalent on `VertexAIModel` if Vertex supports it). *Evidence*: F005.
- **`examples/google/structured_with_tools.py`** — accept `--model <id>` from CLI (default: iterate the whitelist), printing a clear pass/fail and the `len(response.tool_calls)` / `response.structured_output` outcome per model so the user can validate empirically. *Evidence*: F004.

### What's Untouched (Non-Goals)

- The existing two-phase fallback for older / non-whitelisted models — stays bit-for-bit identical.
- `_reformat_model` / `_default_reformat_model` — combined mode bypasses it; no need to change the default.
- `packages/ai-parrot/src/parrot/clients/google/analysis.py` — its specialized methods (sentiment, product review, image understanding) already use single-call structured output because they do not combine with tools. No change needed.
- `tool_config` / `FunctionCallingConfigMode` selection (client.py:2103-2114) — keep AUTO behaviour.
- `_build_tools` (client.py:773-851) — tool serialization is unchanged.
- Streaming behaviour on the wire — combined mode still streams the chat; only the post-stream reformat call is bypassed.

### Patterns to Follow

- **Capability helper signature.** Mirror `_is_gemini3_model` / `_requires_thinking` (`@staticmethod`, `_as_model_str` normalization, `.startswith()` prefix matching). *Evidence*: F003.
- **Configurable defaults pattern.** Mirror `_default_reformat_model` (class attribute) + constructor kwarg + per-instance store (e.g. `self._combined_call_prefixes`). This matches how `reformat_model` is resolved at client.py:149-152. *Evidence*: F001.
- **Logging style.** When combined mode kicks in for `gemini-3.1-flash-lite`, emit `self.logger.warning(...)` once per call documenting the upstream stability flag (per U2). When falling back for an unsupported model, emit the existing `self.logger.info("Google Gemini doesn't support tools + structured output simultaneously …")` message. *Evidence*: F001.

### Integration Risks

- **Cache / lifecycle / memory parity.** Combined mode runs the SAME chat send_message loop as today — it only changes WHICH config keys live on it. All cache, event, and memory plumbing already happens around that loop, so risk is low, but tests must explicitly assert that lifecycle events fire and conversation memory is updated in combined mode. *Mitigation*: include lifecycle-event assertions in the new test cases. *Evidence*: F006.
- **`_parse_structured_output` failure in combined mode.** If the model produces malformed JSON despite `response_schema`, today's fallback is the reformat call. In combined mode there is no second chance. *Mitigation*: on `_parse_structured_output` failure in combined mode, fall back to the two-phase reformat call — same code path, just invoked as the recovery branch. This avoids regressing reliability for the rare malformed case. *Evidence*: F001.
- **`gemini-3.1-flash-lite` AFC infinite-loop risk.** Upstream evaluation observed this. *Mitigation*: keep `max_iterations` and existing AFC safeguards in the chat loop; document in the proposal that users should constrain tool definitions narrowly when targeting this model. *Evidence*: F004, F005.
- **Vertex AI parity.** `_is_gemini3_model` notes that Gemini 3.x models on Vertex require `location='global'` and preview variants need `api_version='v1beta1'`. The combined-mode whitelist is API-shape-orthogonal to that, but spec-level tests must cover both Developer API and Vertex AI code paths if both are supported in production. *Evidence*: F003. *Status*: deferred to the spec — flagged here so it isn't missed.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Two-phase tool+schema gate is at client.py:2033-2048 in `ask()` | F001 | high | Direct read of the block. |
| C2 | Deferred reformat call is at client.py:2337-2474 (ask) and 3020-3084 (stream) | F001, F002 | high | Direct read of both blocks. |
| C3 | `ask_stream`'s analogous gate is at client.py:2847-2854 | F002 | high | Direct read. |
| C4 | Existing capability helpers follow `@staticmethod` + `.startswith()` pattern | F003 | high | Direct read of 4 helpers (lines 156-204). |
| C5 | `GoogleModel` has `gemini-3.1-pro-preview` and `gemini-3.1-flash-lite-preview`; `gemini-3.5-flash` was missing — must be added (per U1) | F005 | high | Full file read; U1 user-confirmed. |
| C6 | Existing example is hardcoded to `gemini-2.0-flash` | F004 | high | Direct read of all 99 lines. |
| C7 | No existing combined-mode test | F007 | high | grep of `test_google_client.py` and search across `tests/`. |
| C8 | `gemini-3.1-flash-lite` is unstable in combined mode but user accepts inclusion (U2) | F004 | medium | Source from user analysis; not independently re-verified by this proposal. |
| C9 | Combined-mode branch must preserve cache hints, lifecycle events, conversation memory | F006 | high | Direct inspection of surrounding code paths. |
| C10 | Whitelist should be configurable (per U3) | — | high | User-confirmed in Q&A. |
| C11 | Combined-mode SDK acceptance is "partial — not 100% probado" by the user's own admission | — | medium | Source signal: user explicitly hedged this. |

Distribution: **8 high**, **3 medium**, **0 low**.

> The two `medium` items (C8 and C11) are why the spec MUST include integration tests that re-verify combined-mode behaviour against each whitelisted model end-to-end through the parrot client — not just at the SDK level.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Is `gemini-3.5-flash` a real Google model identifier?** — *Resolved*: yes, it's a real Google model per https://ai.google.dev/gemini-api/docs/deprecations. *Action*: add `GEMINI_3_5_FLASH = "gemini-3.5-flash"` to the `GoogleModel` enum and include it in the whitelist. *Resolves claims*: C5.
- [x] **U2 — Should `gemini-3.1-flash-lite` be whitelisted despite upstream instability flag?** — *Resolved*: yes, include it; document the risk with a logger warning when combined mode triggers on this model. *Resolves claims*: C8.
- [x] **U3 — Should the whitelist be configurable?** — *Resolved*: yes, configurable preferred. Implement with hardcoded sensible defaults plus an override mechanism (class attribute `_combined_call_prefixes` + constructor kwarg `combined_call_prefixes`). *Resolves claims*: C10.

### Unresolved (defer to spec / implementation)

- [ ] **Should combined-mode failure (malformed JSON despite `response_schema`) fall back to the two-phase reformat call, or surface the error?** *Owner*: tbd. *Blocks claims*: — *Plausible answers*: a) silent fallback to two-phase (preserves reliability at the cost of latency on failure), b) raise + let caller retry (clearer semantics, possibly worse UX). *Recommendation in §3*: option (a).
- [ ] **Vertex AI vs Developer API parity for combined-mode tests.** *Owner*: tbd. *Blocks claims*: — *Plausible answers*: a) mock-only unit tests (fast, covers logic), b) optional live tests against both endpoints gated behind credentials (slow, covers SDK quirks). *Recommendation*: start with (a); add (b) opportunistically.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-193`** — *Rationale*: localization is high-confidence (C1, C2, C3, C4), scope is well-bounded (one helper, two gates, one enum addition, one example update, ~5 unit tests), and the architectural choices were resolved during Q&A (C5, C8, C10). No architectural fork remains to explore.

### Alternatives

- **`/sdd-brainstorm FEAT-193`** — only if you want to debate the configurable-whitelist API surface (e.g. instance-level vs. class-level, env-var vs. kwarg). U3 already settled the high-level answer, so this is unlikely to add value.
- **`/sdd-task FEAT-193`** — if you accept this scope as-is and want a single task in the queue. Not recommended — the change spans both `ask()` and `ask_stream()` plus tests and example, which benefits from explicit task decomposition.
- **Manual review** — not warranted; research was not truncated and confidence is high.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-193/state.json` |
| Source (raw) | `sdd/state/FEAT-193/source.md` |
| Research plan | `sdd/state/FEAT-193/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-193/findings/F001-…F007-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-193/synthesis.json` |

**Budget consumed**:
- Files read: 7 / 40
- Grep calls: 6 / 25
- Git calls: 1 / 10
- Wall time: well within 300s
- Truncated: **no**

**Mode determination**: `enrichment` (chosen — codebase exists, change is well-localized, source has rich analysis from the user, not an open-ended bug investigation).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Jesus Lara |
| Date | 2026-05-27 |
