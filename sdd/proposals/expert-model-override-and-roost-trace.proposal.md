---
title: "Expert registry per-expert model override (C8) and trace-carrying Roost query"
slug: expert-model-override-and-roost-trace
type: feature
mode: proposal
status: draft
base_branch: dev
projects: [ai-parrot]
tags: [domain-experts, roost, experts-registry, model-config, tracing, audit]
requested_by: parrot-finance-agent FEAT-10 (finance-expert-roster)
created: 2026-11-02
extends: [FEAT-778 domain-experts]
---

# Expert registry model override (C8) and trace-carrying Roost `query()`

> Light proposal (scope, rationale, impact, open questions). Run `/sdd-spec` on it in this
> repository. Every symbol below was read at ai-parrot `29779e8b1f`; re-verify before coding.

## 1. Why

`parrot-finance-agent` FEAT-10 runs seven domain experts (five analysts, CIO, Secretary) over
Roost. Its approved runtime profile fixes the **exact provider/model per seat** (five distinct
analyst providers). Two gaps in ai-parrot block that and are the only things holding the
finance committee back (its readiness check refuses to start without them):

1. **C8: the expert registry cannot take an explicit model.** `ExpertRegistry._build`
   (`packages/ai-parrot/src/parrot/experts/registry.py`, the line
   `model_config = model_config_for(bundle.manifest.tier)`) always uses the tier default.
   `model_config_for(tier, *, overrides=...)` in `experts/policy.py` **already accepts
   overrides**; nothing passes them.
2. **`RoostEndpoint.query()` cannot carry a trace id.** It builds its own envelope with
   `squawk_bridge.new_envelope(correlation_id=..., caller=..., budget_ms=...)` and no `trace`.
   `new_envelope` already accepts `trace: TraceContext`, `RoostAuditEntry` already records
   `trace_id` (from `msg.trace_id()` = `envelope.trace.trace_id`), and `RoostMessage.reply()`
   reuses the opener's `envelope`. So the plumbing exists end to end except the parameter on
   `query()`.

## 2. Scope

### 2.1 Per-expert model override (C8)

- `ExpertRegistry.__init__` gains a keyword-only parameter
  `model_overrides: Mapping[str, Mapping[str, Any]] | None = None`, keyed by **expert name**
  (the bundle slug), value passed as `overrides` to `model_config_for` (allowed keys:
  `provider`, `model`, optionally `temperature`, `max_tokens`).
- `_build` uses `model_config_for(bundle.manifest.tier, overrides=self._model_overrides.get(name))`.
  With no override behavior is **byte-for-byte unchanged**.
- Fail-closed validation at construction/`load()`:
  - an override for a slug that has no admitted bundle is a load error (reported in
    `_report`, not silently ignored);
  - an override must contain both `provider` and `model`, and no unknown keys;
  - the resolved `ModelConfig` is what the built `ExpertAgent` actually uses (the finance side
    asserts it per seat).
- Expose the effective config for readiness: e.g. `ExpertRegistry.effective_model(name) ->
  ModelConfig` (read-only), so a host can print/verify the resolved provider/model without
  reaching into private state.

### 2.2 Trace-carrying `query()`

- `RoostEndpoint.query(question, *, receiver, timeout=None, expected_schema=None, hops=0,
  trace_id: str | None = None)`. When given, build
  `TraceContext(trace_id=trace_id, ...)` and pass `trace=` to `squawk_bridge.new_envelope`.
  Absent: unchanged behavior.
- The trace must be visible in **every** audit entry of the exchange (opener, terminal reply,
  both `served` and `received` directions) because replies reuse the opener envelope. Add tests,
  do not assume.
- Validation: `trace_id` must be a non-empty string without whitespace/control characters;
  otherwise `ValueError` before any message is sent.
- Optional (same change if trivial, else follow-up): the same keyword on `cfp()` and the other
  protocol openers, for consistency.

## 3. Non-goals

- No change to default tier policy, spawn/tool deny rules, or knowledge resolution.
- No change to Squawk wire formats; if the satellite `CallMessage` path cannot carry a trace
  id, document the limitation and keep `LocalEnvelope` support (the finance adapter qualifies
  LocalEnvelope mode and records Squawk parity as a separate gate).
- No finance-specific logic in ai-parrot.

## 4. Tests (ai-parrot)

`packages/ai-parrot/tests/experts/` and `tests/roost/`:

1. Registry without overrides builds identical `ModelConfig` per tier (regression).
2. Override applies provider+model to exactly the named expert; siblings keep tier defaults.
3. Unknown slug / partial override / unknown key fail load with a clear report entry.
4. `effective_model` returns the applied config.
5. `query(..., trace_id="t1")`: every `RoostAuditEntry` of the conversation has
   `trace_id == "t1"`; without it `trace_id is None` (as today).
6. Invalid `trace_id` raises before sending.
7. Cancellation/timeout paths still record the trace id on the terminal failure entry.

## 5. How finance consumes it (so the names match)

- `parrot.finance.roster.registry.supports_model_overrides` checks the factory signature for the
  keyword **`model_overrides`** and passes `{slug: {"provider": ..., "model": ...}}`.
- `parrot.finance.roster.dispatch.TracedDispatcher` switches to native propagation when
  `query` has a `trace_id` parameter, passing `trace_id=run_id`; otherwise it keeps the digest-join
  fallback. No finance change is needed beyond recording the released revision.

Using different names is fine, but then the two finance lookups
(`C8_OVERRIDE_PARAMETER` in `roster/registry.py`, `native_trace_supported` in
`roster/dispatch.py`) must be renamed in the same step.

## 6. Open questions

- [ ] Should overrides be keyed by `manifest.name` only, or also accept tags
      (`expert:<slug>`)? (Finance uses the slug.)
- [ ] Should an override that changes the provider re-run knowledge-resolver token budgeting
      (`resolver.resolve(..., model=model_config.model)` already receives the model name)?
- [ ] Does the Squawk `CallMessage` carry `trace_id` end to end (`new_envelope` passes
      `trace.trace_id` into it)? Needs a satellite-installed test or an explicit
      "LocalEnvelope only" note.
- [ ] Release/tag: finance records the ai-parrot revision in
      `docs/finance/runtime-source-manifest.json` (editable install, no PyPI pin needed locally).

## 7. Acceptance

- [ ] All tests in §4 pass; existing `tests/experts` and `tests/roost` unchanged and green.
- [ ] `model_overrides` and `trace_id` are documented in the experts and Roost docs.
- [ ] After merge, in `parrot-finance-agent`: `RosterRegistry.load()` reports `c8_supported=True`
      and the dispatch adapter reports `mode == "native"`.
