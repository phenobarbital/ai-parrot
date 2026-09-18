# Design research triage — FEAT-565 new-planogram-compliance-algo

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-565/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 41 cited paths passed the containment + existence check; the factual claims behind
> S1 (`_encode_file` → `"document"`, `base.py:1392-1401`) and S3 (shelf 1 `position`
> non-monotone, `slot` contiguous) were reproduced before triage.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Resolve the vision-client capability gap first (architecture) | ESCALATE | Claim verified: no parrot method sends an image to a local OpenAI-compatible server. Whether a script-local SDK-handle lane is acceptable, or a core `ask_to_image` must come first, is the owner's call (touches a non-negotiable rule and core scope) | §8 Q7 |
| S2 | Make the deliverable and tests trackable (architecture) | CONFIRM | Reached independently; narrow `.gitignore` re-include block instead of `git add -f` | §3 M0, §7 |
| S3 | Normalize a physical planogram axis before alignment (architecture) | CONFIRM | Verified: `position` is not monotone on shelf 1; order by `slot`, validate contiguity, keep `segment_slot` | §2 stage 4, §3 M1/M2, §4 |
| S4 | Versioned consumer-visible SKU identity bridge (api) | CONFIRM | Catalog already required with family/xl/colors/pack/aliases; added `provenance`; uncovered SKUs reported in `run.catalog_missing_skus`; MPNs never fuzzy-matched | §2 resolution rules, §3 M1/M2 |
| S5 | Represent unseen areas separately from unknown occupancy (architecture) | CONFIRM | Exposed a real gap: a registered-but-uncertain slot had no status. Added `not_assessed` beside `not_visible`; both out of denominators, never `empty` | §2 statuses/metrics, §3 M1, §4, §5 |
| S6 | Separate automatic registration from human-review semantics (api) | CONFIRM | No `reviewed` flag exists in the new models; grade, anchors, margin and runner-up are exposed; `run.registration_method = "auto_alignment"` added. Per-slot candidate-mapping lists not added (runner-up is recorded per image) | §3 M1 |
| S7 | Reference uncertainty as a separate scoring dimension (risk) | CONFIRM | 40/102 reference entries are inferred; added `reference_read_method`, direct-reference strict/lenient metrics and `run.reference_provisional` | §2 metrics, §3 M1, §4, §5 |
| S8 | Structured price evidence instead of raw strings (api) | CONFIRM | `PriceReading` already structured; made explicit that agreement/compliance compare normalised amounts and conflicts keep all raws. OCR confidence score not added (grammar acceptance is the gate) | §2 metrics, §4 |
| S9 | Preserve cross-photo conflicts before deduplication (architecture) | CONFIRM | Every observation stays in `slots[]`, `PositionResult.slot_ids` links them; added identity/price-conflict and per-image injectivity tests | §4 |
| S10 | Expand cache invalidation to all perception inputs (risk) | CONFIRM | Key already hashes full prompt text + rendered images (covers slot JSON, distractors, overlays); added base URL + generation params and atomic writes. OCR is not cached; alignment parameters never reach an LLM call | §2, §3 M6, §4 |
| S11 | Hand-labelled evaluation fixture before claiming accuracy (testing) | ESCALATE | Producing ground truth is the owner's effort/decision; spec already makes no accuracy claim and ships the ablation switches | §8 Q3 |
| S12 | Gate Set-of-Marks and local OCR behind A/B tests (testing) | CONFIRM | Added `--no-marks`, marks-sensitive cache key, graceful absence of `rapidocr`. Default stays marks-on with labels drawn over the tag area only, pending the A/B (§8 Q6) | §2 CLI, §3 M5/M7, §4, §5 |

Summary: **10** confirmed · **0** rejected · **2** escalated.
