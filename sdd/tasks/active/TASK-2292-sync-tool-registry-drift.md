# TASK-2292: Sync `TOOL_REGISTRY` / `LOADER_REGISTRY` drift revealed by the AnnAssign fix

**Feature**: FEAT-436 — Sync `TOOL_REGISTRY` / `LOADER_REGISTRY` Drift Revealed by the AnnAssign Fix
**Spec**: `sdd/specs/sync-tool-registry-drift.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-427 (`TASK-2245`) fixed `scripts/generate_tool_registry.py` to
correctly parse `ast.AnnAssign`-style registry declarations. Now that
`--check` can actually read existing registry contents, it reveals real,
pre-existing drift that had been silently accumulating (the write mode
had the same bug, so it never actually applied a change either) — see
FEAT-427's Completion Note recommendation and spec §1 for the full
history. This task closes that drift by hand-adding the genuinely
missing entries to both `__init__.py` files. Implements spec §2, §3
Module 1 + Module 2.

---

## Scope

- In `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
  - Change the `"odoo"` entry's value from
    `"parrot_tools.odoo.OdooToolkit"` to
    `"parrot_tools.odoo.toolkit.OdooToolkit"` (same key, corrected value
    — the class's actual defining module; both paths currently resolve,
    this is a safe canonicalization).
  - Add the 49 genuinely-missing entries listed in spec §6 Appendix A
    ("TRUE NEW") to `TOOL_REGISTRY`, in a new trailing comment section
    `# --- Synced from drift audit (FEAT-436) ---`, alphabetized by key.
- In `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py`:
  - Add `"WebScrapingLoader": "parrot_loaders.webscraping.WebScrapingLoader"`
    to `LOADER_REGISTRY`, in a new trailing comment section
    `# --- Synced from drift audit (FEAT-436) ---`.
- Verify via `python scripts/generate_tool_registry.py --check
  --tools-only` / `--loaders-only` (read-only; do NOT run the plain
  write mode).

**NOT in scope** (spec §1 Non-Goals / §8 Open Questions):
- Do **NOT** add any of the 42 "alias duplicate" keys listed in spec §6
  Appendix B (e.g. `best_buy`, `duck_duck_go`, `ms_teams`, `zipcode_api`,
  `zoom_us`, …) — each of these classes is **already registered** under
  a different, hand-curated key. Adding a second key for an
  already-registered class is a naming-policy decision explicitly
  deferred to spec §8 Open Questions, not a mechanical drift-sync.
- Do NOT run `python scripts/generate_tool_registry.py` in plain write
  mode against either file — it deletes every `# --- ... ---` section
  comment and reorders every existing entry (verified in spec §1
  Non-Goals). Use `Edit` directly instead.
- Do NOT modify `scripts/generate_tool_registry.py` itself (already
  fixed by FEAT-427).
- Do NOT reorder or re-group any pre-existing entry in either file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Fix `"odoo"` value; append 49 new entries in a new trailing section |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | MODIFY | Append 1 new entry (`WebScrapingLoader`) in a new trailing section |

No test files are created or modified by this task (pure data-sync; see
spec §4 Test Specification — existing suites already cover this via
import + drift-check, no new test file is warranted for a dict-literal
data change).

---

## Implementation Notes

- Use `Edit`, not the generator script, for both files — see spec §1
  Non-Goals for why the generator's plain write mode is destructive to
  the existing hand-curated section comments.
- Match existing formatting exactly: `    "<key>": "<dotted.path.ClassName>",`
  (4-space indent, trailing comma, double quotes).
- The full list of 49 `TOOL_REGISTRY` entries + 1 `LOADER_REGISTRY` entry
  to add, and the full list of 42 alias-duplicate keys to leave unadded,
  are both given verbatim in spec §6 Appendix A / Appendix B — copy from
  there, do not re-derive by re-running the generator and guessing which
  "changes" are real gaps vs. alias duplicates (that classification is
  the whole point of this spec and is easy to get wrong from the raw
  `--check` diff alone).
- Re-verify Appendix B's list is still accurate at implementation time
  (`python scripts/generate_tool_registry.py --check --tools-only`
  should report 92 changes broken down as exactly 49 additions + 1
  rename that this task will apply, plus 42 additions this task must
  leave alone) in case unrelated commits shifted the registry since the
  spec was written (2026-08-20, `dev` HEAD `0dfa99db9`).

## Reference Code

- `scripts/generate_tool_registry.py` (read-only reference for
  understanding `--check`'s output — not modified).
- `sdd/specs/sync-tool-registry-drift.spec.md` §6 Codebase Contract
  Appendix A/B — the definitive source of truth for exactly what to add
  and what to leave alone.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/src/parrot_tools/__init__.py`: `"odoo"`
      value is `"parrot_tools.odoo.toolkit.OdooToolkit"`.
- [ ] `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
      `TOOL_REGISTRY` contains all 49 keys from spec §6 Appendix A with
      exactly the dotted paths shown there.
- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py`:
      `LOADER_REGISTRY` contains
      `"WebScrapingLoader": "parrot_loaders.webscraping.WebScrapingLoader"`.
- [ ] None of the 42 alias-duplicate keys from spec §6 Appendix B were
      added.
- [ ] `git diff` on both files shows only additive changes plus the
      single `odoo` value-line change — every pre-existing line
      (including every `# --- ... ---` comment) is untouched.
- [ ] `python scripts/generate_tool_registry.py --check --tools-only`
      reports exactly the 42 deferred alias-duplicates as remaining
      changes (not 92, not 0).
- [ ] `python scripts/generate_tool_registry.py --check --loaders-only`
      exits `0`.
- [ ] All 50 newly-added dotted paths import successfully (spot-check
      via `importlib.import_module` + `getattr`, or a small ad-hoc
      script — no new test file required).
- [ ] `python -m pytest packages/ai-parrot-tools/tests/ -q` passes.
- [ ] `python -m pytest packages/ai-parrot-loaders/tests/ -q` passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/__init__.py
      packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` clean.

## Test Specification

No new automated test file (see Scope / spec §4). Verification is the
manual commands above plus the existing test suites for both packages.

---

## Output

When complete:
1. Move this file to `sdd/tasks/completed/`.
2. Update `sdd/tasks/index/sync-tool-registry-drift.json` status to `"done"`.
3. Add a completion note below, including the actual `--check` output
   before/after and confirmation of the 42-remaining-changes assertion.

### Completion Note
(Agent fills this in when done)
