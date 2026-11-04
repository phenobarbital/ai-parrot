# TASK-5153: Admin UI model lists and the gemini-4-argon pricing row

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (UI + pricing). The admin UI keeps hand-maintained model lists that are not
generated from `/models`. They default to `google:gemini-2.5-flash` and offer an invalid
`google:gemini-3-pro-preview` (codex S8). `CostCalculator` looks prices up by exact key
(`calculator.py:301`), so without a `gemini-4-argon` row every Argon call is unpriced (codex S5, spec AC-8).
The Argon price is an **external input**: take it from Google's pricing page at implementation time and
record the URL and date (spec §8 Q1).

## Scope

- `regeneration-models.ts`: the 2.5-flash entry and `DEFAULT_MODEL` → `google:gemini-3.8-flash`; refresh the :66-67 comment.
- `ChatInput.svelte`: replace the 2.5 Flash / 2.5 Pro options with 3.8 Flash / 4 Argon; replace `gemini-3-pro-preview` with `gemini-3.1-pro-preview`.
- `pricing/google.json`: add a `gemini-4-argon` row and bump `last_updated`.
- `test_cost_calculator.py`: add `test_gemini_4_argon_priced`.

**NOT in scope**: a cross-language UI/backend consistency test (codex S8 part rejected); removing the dated
2.5 *preview* pricing rows (they price history); `GoogleModel` (other tasks).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts` | MODIFY | default + list entry + comment |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatInput.svelte` | MODIFY | Google options |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` | MODIFY | Argon row, `last_updated` |
| `packages/ai-parrot/tests/unit/observability/test_cost_calculator.py` | MODIFY | Argon pricing test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.cost.calculator import CostCalculator, _reset_pricing_cache_for_tests  # verified: test_cost_calculator.py:15-18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/cost/calculator.py
#   file_key = "google" if provider == "gemini" else provider                     # line ~299
#   price_value = provider_pricing.get(model) ...                                 # line 301 — exact key
#   def revision_for(self, provider: str, model: str, at: Optional[date] = None) -> tuple[Optional[str], Optional[str]]  # line 322
#   cost_usd(provider=..., model=..., input_tokens=..., output_tokens=...)        # used at test_cost_calculator.py:190-195
# CostCalculator(today=date(...))                                                 # test_cost_calculator.py:189
```
```text
pricing/google.json:3      "last_updated": "2026-06-10",
pricing/google.json:103    "gemini-3.8-flash": [   ← insert the Argon row before it (same file key, list-or-dict entry)
regeneration-models.ts:21-26  { value: "google:gemini-2.5-flash", label: "Gemini 2.5 Flash", provider: "Google", enabled: true },
regeneration-models.ts:62     export const DEFAULT_MODEL = "google:gemini-2.5-flash";
regeneration-models.ts:66-67  comment examples "gemini-2.5-flash" / "google:gemini-2.5-flash"
ChatInput.svelte:203-206      2.5 Flash, 2.5 Pro, gemini-3-flash-preview, gemini-3-pro-preview
```

### Does NOT Exist
- ~~prefix matching in `CostCalculator`~~ — exact key only.
- ~~a vitest file for `regeneration-models.ts`~~ — none; UI validation is `pnpm build`.
- ~~`gemini-3-pro-preview` as a catalogue value~~ — the 3.x pro id is `gemini-3.1-pro-preview`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/ChatInput.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/google.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_cost_calculator.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/cost/calculator.py#CostCalculator",
    "sym:packages/ai-parrot/src/parrot/observability/cost/calculator.py#CostCalculator.revision_for"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Fetch Argon pricing from `https://ai.google.dev/gemini-api/docs/pricing` — *why*: the repo cannot derive it.
2. Edit `google.json` — *why*: exact-key lookup.
3. Add the pricing test.
4. Edit the two UI files; run `pnpm build` in `packages/ai-parrot-server/ui` — *why*: TypeScript strict check (spec AC-14).

### `pricing/google.json` (MODIFY)
```jsonc
// occurrences: 1 (`"gemini-3.8-flash": [` at :103) — insert BEFORE it:
    "gemini-4-argon": {
      "input_per_1m": 0.0,            // FILL IN: from Google's pricing page
      "output_per_1m": 0.0,           // FILL IN
      "valid_from": "YYYY-MM-DD"      // FILL IN: Argon release / price-effective date
    },
// and :3  "last_updated": "<edit date>",
```
**Why**: same shape as the README format (`pricing/README.md` "File Format"). If Google lists tiered or cached prices, add `cached_input_per_1m` too. JSON has no comments: strip them in the real file.

### `test_cost_calculator.py` (MODIFY — append)
```python
def test_gemini_4_argon_priced() -> None:
    """FEAT-798 (codex S5): gemini-4-argon has an exact pricing row."""
    cc = CostCalculator(today=date.today())
    cost = cc.cost_usd(provider="gemini", model="gemini-4-argon", input_tokens=1000, output_tokens=500)
    # FILL IN: assert cost is a positive number (not the unpriced sentinel the calculator returns for unknown models)
    #          and that cc.revision_for("gemini", "gemini-4-argon") != (None, None) — bounded by spec AC-8
```

### `regeneration-models.ts` (MODIFY)
```ts
// :22-23
    value: "google:gemini-3.8-flash",
    label: "Gemini 3.8 Flash",
// :62
export const DEFAULT_MODEL = "google:gemini-3.8-flash";
// :66-67 comment examples → "gemini-3.8-flash" / "google:gemini-3.8-flash"
```

### `ChatInput.svelte` (MODIFY, :203-206)
```ts
    { value: "google:gemini-3.8-flash", label: "Gemini 3.8 Flash" },
    { value: "google:gemini-4-argon", label: "Gemini 4 Argon" },
    { value: "google:gemini-3-flash-preview", label: "Gemini 3 Flash" },
    { value: "google:gemini-3.1-pro-preview", label: "Gemini 3.1 Pro" },
```

### FILL IN checklist
- [ ] Argon prices, `valid_from`, source URL and date in the Completion Note.
- [ ] Pricing test assertions (check how `cost_usd` signals "unpriced" in `calculator.py` before asserting).
- [ ] `pnpm build` result recorded.

---

## Acceptance Criteria

- [ ] `CostCalculator().cost_usd(provider="gemini", model="gemini-4-argon", ...)` is priced (spec AC-8).
- [ ] No `gemini-2.5` id and no `gemini-3-pro-preview` in the two UI files; `DEFAULT_MODEL == "google:gemini-3.8-flash"` (spec AC-9, AC-15).
- [ ] `pnpm build` succeeds for the UI package (spec AC-14).

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_calculator.py -q`

## Test Specification
See the blueprint.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§3 M7, §8 Q1).
3. Check dependencies: none.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint.
6. Run the Validation Commands and `pnpm build`.
7. Commit only the files listed above.
8. Close with `parrot sdd task close TASK-5153 google-migration verified`, then fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
