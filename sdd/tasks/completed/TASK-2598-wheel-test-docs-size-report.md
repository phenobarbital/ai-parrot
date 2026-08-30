# TASK-2598: Wheel-content assertion, Admin UI docs, bundle size report

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: done-with-issues
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2597
**Assigned-to**: sdd-worker

---

## Context

Spec §3 Module 8, §5 last criteria. Closes the feature: the wheel
guarantee covers the chat chunk, and adopters/developers can read how
the flags, the lean build, the bundle sizes and the navigator-divergence
policy work.

---

## Scope

- `packages/ai-parrot-server/tests/test_wheel_layout.py`: add
  `test_agentchat_chunk_present` (`@pytest.mark.wheel_build`) asserting
  at least one `parrot/server/ui/dist/assets/*` entry whose name
  contains `AgentChat` (Vite names lazy chunks after the module).
- `docs/admin-ui.md`: new section "Agent Chat" after "Wheel-content
  guarantee…" (line 142) covering: routes, the eight
  `PUBLIC_AGENTCHAT_*` flags with defaults, the lean-build recipe
  (`PUBLIC_AGENTCHAT_MAPS=false pnpm build`), measured `dist/` size
  all-on vs all-off (run both builds and record numbers), the
  offline-icons note, the `wsService` stub, and the divergence policy
  (vendored tree mirrors navigator paths; `// ai-parrot:` header
  comments; how to back-port with `diff -r`).
- `packages/ai-parrot-server/ui/README.md` (if present): pointer to the
  docs section.
- Confirm `Makefile build-server-ui` and `.github/workflows/release.yml`
  need no change (defaults = all on); note in docs that env overrides
  are honoured by both.

**NOT in scope**: code changes in `ui/src`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | MODIFY | new test |
| `docs/admin-ui.md` | MODIFY | "Agent Chat" section |
| `packages/ai-parrot-server/ui/README.md` | MODIFY (if exists) | pointer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-server/tests/test_wheel_layout.py — existing fixture `satellite_wheel_namelist` (used at :72, :83); marker `wheel_build` (pyproject.toml [tool.pytest.ini_options] markers)
```

### Existing Signatures to Use
```python
# test_wheel_layout.py:72  def test_dist_index_present(self, satellite_wheel_namelist): assert "parrot/server/ui/dist/index.html" in satellite_wheel_namelist
# test_wheel_layout.py:83  def test_dist_assets_present(self, satellite_wheel_namelist): assets = [n for n in … if n.startswith("parrot/server/ui/dist/assets/")]; assert assets
# pyproject.toml:104-111   [tool.setuptools.package-data] "parrot.server.ui" = ["dist/*", "dist/assets/*"]
# Makefile:346             release: lint test clean check-registry build-rust build-server-ui
# docs/admin-ui.md headings: What it is (8), Auth model (23), Adopter view (42), Developer view (87), Codegen (107), Where the build output lands (122), Tests (135), Wheel-content guarantee and release pipeline (142)
```

### Does NOT Exist
- ~~a size-report step in `release.yml`~~ — decided not to add one (spec §8); numbers live in docs.
- ~~`pnpm size` script~~ — measure with `du -sh dist/assets` after each build.

---

## Implementation Notes

### Key Constraints
- The wheel test must not assume a specific hash: match `AgentChat` substring + `.js` suffix.
- Document flag names exactly as in `ui/vite.config.ts` (TASK-2591).

---

## Acceptance Criteria

- [x] `pytest -m wheel_build packages/ai-parrot-server/tests/test_wheel_layout.py -v` passes, including the new test (11/11)
- [x] `docs/admin-ui.md` has the "Agent Chat" section with all eight flags, both size measurements, and the divergence policy
- [ ] Spec §5 checklist fully satisfied — **NOT fully satisfied as literally worded**: walked the full checklist in the Completion Note below; one item (§5 line 450, "building with a flag false produces a dist/ without the corresponding chunk") is FALSE as measured (byte-for-byte identical `dist/assets` with all flags on vs. all off) — this is not something TASK-2598 can "fix" (it's a `$lib/features.ts` architecture question already flagged as a cross-cutting follow-up in TASK-2595/2596's Completion Notes), so it's surfaced here for the human reviewer rather than silently ticked

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_wheel_layout.py (addition inside the FEAT-468 Admin UI test class)
@pytest.mark.wheel_build
def test_agentchat_chunk_present(self, satellite_wheel_namelist):
    """FEAT-476: the vendored AgentChat lazy chunk ships in the wheel."""
    chunks = [
        n for n in satellite_wheel_namelist
        if n.startswith("parrot/server/ui/dist/assets/") and "AgentChat" in n and n.endswith(".js")
    ]
    assert chunks, "wheel is missing the AgentChat chunk — was the UI built with the chat module?"
```

---

## Agent Instructions

1. Read spec §3 Module 8 and §5. 2. Confirm TASK-2597 completed. 3. Verify contract (`test_wheel_layout.py` fixture names). 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-31
**Notes**:
Added `test_agentchat_chunk_present` to `TestWheelContainsAdminUI`
(matches by `AgentChat` substring + `.js` suffix, no fixed hash) —
11/11 `wheel_build`-marked tests pass. Added the "Agent Chat" section to
`docs/admin-ui.md` (flags table, lean-build recipe, offline-icons note,
`wsService` stub note, divergence policy with `diff -r` recipe). No
`ui/README.md` exists, so that file wasn't touched. Confirmed
`Makefile`'s `build-server-ui` target and `.github/workflows/
release.yml`'s `build-server` job need no change (plain `pnpm build`,
all flags default `true`) — documented that explicitly.

**Full spec §5 walk** (this task's own Agent Instructions/Acceptance
Criteria ask for exactly this — "reviewer walks it and ticks every
box"). Everything below was either already verified by an earlier task
(cited) or verified directly in this task's own pass:
- [x] `/admin/agents/<name>/chat` full layout + auth redirect — TASK-2597 (`router.svelte.ts`'s existing `guard()`, `requiresAuth: true` on the new route; unauthenticated behavior is pre-existing, unchanged, infra)
- [x] Chat action on enabled rows / hidden on disabled / Chat tab — TASK-2597, `AgentsList.test.ts`/`AgentDetail.test.ts`
- [x] Non-stream/stream envelope rendering, Stop keeps partial text — TASK-2594, `AgentChat.test.ts`
- [x] No-separator response rendered as chunks, not an error — TASK-2592, `stream.test.ts` (documented deviation from the spec's literal wording in TASK-2592's own Completion Note)
- [x] IndexedDB persistence + reconciliation; private-mode chat — TASK-2592, `chat-db.test.ts`
- [x] `wsService` no-op, no real `WebSocket`, no `ws_channel_id` — TASK-2591/2592, `websocket-service.test.ts`
- [x] No `$app/*`/`$env/*` resolution errors; `pnpm build` succeeds; no `navauth/**` — TASK-2591 (shims), verified again in this task's own `pnpm build` run
- [ ] **§5 line 450 — FALSE AS WORDED**: "building with a flag false produces a `dist/` without the corresponding chunk" — measured in this task: `dist/assets` is byte-for-byte identical (15,306,233 bytes / 77 JS files) with all eight `PUBLIC_AGENTCHAT_*` flags on vs. all eight off. Root cause fully diagnosed and documented in TASK-2595/2596's Completion Notes (an isolated Vite/Rollup repro confirmed dead-code elimination of a guarded dynamic `import()` only fires for a bare `const` guard, not `features.x`'s object-property read) and reiterated in `docs/admin-ui.md`'s new "Known limitation" callout. What IS true and was verified (TASK-2595/2596): each surface still gets its own chunk, and the browser never *fetches* it when the flag is off — the practically-important half of this AC, just not the on-disk-size half.
- [x] Vendored files keep relative paths; `diff -r` shows only shim/import/flag edits — TASK-2594/2595/2596 headers document every deviation; divergence policy + `diff -r` recipe now in `docs/admin-ui.md`
- [x] `dist/` stays flat; `pyproject.toml` package-data unchanged; wheel test passes incl. new chunk assertion — this task, verified directly (`du`/`find` show a flat `assets/` dir; `pyproject.toml` untouched; 11/11 `wheel_build` tests pass)
- [x] `pnpm test` passes: new tests + all existing FEAT-468/475 UI tests — this task, 37 files / 225 tests
- [x] 401 mid-conversation → login redirect; 403/404 → error/not-found, no retry loop — TASK-2594 (`http.ts`'s existing interceptor + `authStore.handle401()`, `AgentChat.test.ts`'s 401 tests), TASK-2597 (`AgentChatPage`'s 404 not-found state)
- [x] Voice/avatar degrade to hidden after first 404/405 — TASK-2596, `voice-gating.test.ts`/`avatar-gating.test.ts`
- [x] `docs/admin-ui.md` documents flags, lean-build recipe, measured sizes, divergence policy — this task (sizes documented honestly per the line-450 finding above, not overstated)
- [x] `AgentChatResponse`/`AgentChatMetadata`/`AgentToolCall` in `chat_models.py`, codegen registered, schemas/types regenerated, `agent.ts` re-exports, `test_chat_models.py` passes — TASK-2590
- [x] `@iconify/svelte` renders offline, no `api.iconify.design` fetch — TASK-2591/2593/2595 (`icons.ts` + `icons.test.ts`, extended with `lucide` in TASK-2595)
- [x] Chat action hidden only on `enabled === false`; registry rows (no `enabled` field) treated as enabled — TASK-2597, `AgentsList.test.ts`
- [x] Python changes limited to `chat_models.py`/`generate_ts_types.py`/tests; `AgentTalk` untouched — TASK-2590 (this task, 2591-2598, made zero Python changes)

**Deviations from spec**:
1. §5 line 450 cannot be honestly ticked as literally worded — see the
   full explanation above. Recommending the human reviewer either (a)
   accept the documented, verified alternative property (per-surface
   code-splitting + no runtime fetch when off) as satisfying the AC's
   *intent*, or (b) open a dedicated follow-up spec to reshape
   `$lib/features.ts` into flat `const` exports (a cross-cutting change
   touching every `features.x` call site across TASK-2594/2595/2596's
   vendored tree — deliberately not attempted inside any single task of
   this feature).
2. `docs/admin-ui.md`'s bundle-size numbers reflect an all-on vs. all-off
   build measured on this machine/toolchain
   (vite@5.4.21/rollup@4.63.0/pnpm 9); re-measure if the pinned versions
   change materially.
