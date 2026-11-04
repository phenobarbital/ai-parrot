---
id: FW-001
query_id: Q001
type: wiki_page
intent: "Precedent: read the approved FEAT-688 gemini-upgrade spec to learn what already landed (Argon member, routing gates, SDK floor) and what it explicitly left for later (2.5 retirement?)."
executed_at: 2026-11-04T01:38:22Z
duration_ms: 4000
parent_id: null
depth: 0
---

# FW-001 — FEAT-688 (merged PR #1685) already added Argon and raised the floor; it did NOT touch gemini-2.5 or any default

## Summary

Wiki page `file:sdd/specs/gemini-upgrade.spec.md` (score 0.72 in orientation; page truncated, remainder read from the file). FEAT-688 (2026-10-15, status approved, merged as PR #1685) added `GoogleModel.GEMINI_4_ARGON = "gemini-4-argon"`, deleted four dead 3.7/deep-research ids, whitelisted Argon in `_default_combined_call_prefixes`, renamed `_is_gemini3_model` → `_is_modern_gemini_model` (gemini-3 | gemini-4), and aligned both google-genai floors. Its Non-Goals explicitly keep every client default on 3.x (U4: `_default_model`, `_fallback_model`, `_lightweight_model`, `_default_reformat_model` unchanged; "Argon is opt-in"), reject a `deprecated_models` registry (U2: retirement is pure deletion), leave `VertexAIModel` untouched (U5), and defer ~28 other live ids (Q2) — including `gemini-2.5-flash-native-audio-*`. Nothing in the spec retires or even mentions retiring `gemini-2.5-pro`/`gemini-2.5-flash`; the only 2.5 mention is a test expectation that `_is_modern_gemini_model("gemini-2.5-pro")` is False.

## Citations

- path: `sdd/specs/gemini-upgrade.spec.md`
  lines: 14, 50-62
  symbol: Target version / Goals
  excerpt: |
    **Target version**: `google-genai>=2.31.0` *(candidate — declared only after the introspection gate in M3)*
    - Add `GoogleModel.GEMINI_4_ARGON = "gemini-4-argon"`.
    - Retire, **by deletion**, the four identifiers that no longer exist upstream
    - Whitelist `"gemini-4-argon"` in `_default_combined_call_prefixes` ... and drop `"gemini-3.7-pro"`
    - Generalize `_is_gemini3_model` to `_is_modern_gemini_model`

- path: `sdd/specs/gemini-upgrade.spec.md`
  lines: 63-80
  symbol: Non-Goals
  excerpt: |
    - **No `GoogleGenAIClient.deprecated_models` registry.** Operator decision (proposal §5 U2): retirement is pure deletion.
    - **No change to the client defaults.** `_default_model`, `_fallback_model`, `_lightweight_model` and
      `_default_reformat_model` stay on 3.x (U4). Argon is opt-in.
    - **`VertexAIModel` is untouched** (U5)
    - No catalogue expansion beyond Argon — roughly 28 further live identifiers are missing ... deferred (§8 Q2).
    - No refactor of the prefix gates into capability metadata on the enum.

- path: `sdd/specs/gemini-upgrade.spec.md`
  lines: 131-158
  symbol: Verified properties of gemini-4-argon (live models.get 2026-10-15)
  excerpt: |
    inputTokenLimit 1048576 · outputTokenLimit 32768 · thinking: true (available, not mandatory)
    supportedGenerationMethods: generateContent, countTokens, batchGenerateContent — **no createCachedContent**

- path: `sdd/specs/gemini-upgrade.spec.md`
  lines: 488-519
  symbol: Known Risks / Rejected alternatives
  excerpt: |
    - **Silent alias collapse.** `GoogleModel` is a plain `Enum` ... `test_google_model_alias_count` is the guard.
    - **Load-bearing names.** Twelve members are referenced by name across the live `src/` trees; deleting one is an `AttributeError` at import
    - **A dead prefix is worse than a dead member.** (`client.py:151`, `client.py:281`)
    - **Argon has no context caching.** ... `_maybe_apply_gemini_cache` (line 518) is already fail-open
    **`deprecated_models` registry** — rejected: no code path resolves or redirects a model through that mapping
    (`factory.py:253` lists its keys, `studio/catalog.py:244` republishes them; nothing consults it at call time).

- path: `sdd/specs/gemini-upgrade.spec.md`
  lines: 534-567
  symbol: §8 Open Questions Q1-Q5
  excerpt: |
    Q1 floor number (resolved by TASK-4371 → 2.31.0, see FW-007) · Q2 ~28 live ids deferred incl.
    `gemini-2.5-flash-native-audio-*`, `gemini-3.8-flash-tts`, `gemini-3.8-live`, `gemini-embedding-2`
    Q3 `VertexAIModel.GEMINI_3_7_PRO` unknown on Vertex · Q4 IMAGEN_* inconclusive
    Q5 `test_google_model_alias_count` pins 49/31 and fails on every catalogue edit

## Notes

- FEAT-688 established the pattern for this feature: enum edit + prefix gates + the two catalogue test modules in one stroke, with live `models.list` verification before deciding what is dead.
- The thinking gate `_requires_thinking` matched `2.5-pro` at the time (per memory [[googlemodel-enum-aliasing-and-prefix-gates]]); retiring 2.5-pro must remove it from that predicate too ("a dead prefix is worse than a dead member").
- [cross-lane: type=grep, intent=confirm whether _requires_thinking / _rejects_zero_thinking_budget still name "gemini-2.5-pro" in client.py after FEAT-688/FEAT-781]
- [cross-lane: type=git_log, intent=confirm PR #1685 merge commit and whether FEAT-781 (#1890) changed client defaults after FEAT-688]
