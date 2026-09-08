# TASK-2969: Real-vendor operational acceptance gate and AC evidence report

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: done-with-issues
**Priority**: high
**Estimated effort**: L (4-8h of live time; requires credentials and a human observer)
**Depends-on**: TASK-2950, TASK-2966, TASK-2967, TASK-2968
**Parallel**: false
**Parallelism notes**: Final combined gate (spec §3 Module 7 "final combined gate last"). Docs/evidence only; no production code. If the environment lacks credentials/human, record NOT RUN per row and finish `done-with-issues` — never claim acceptance from mocks (AC10).

---

## Context

Spec AC10: "Module 1 and the full three-/ten-browser real-vendor gates have recorded evidence, including media playback and lip-sync assessment. Mock-only results cannot complete this feature." AC9: logs identify exact dependency versions and any skipped live cases. AC15: FEAT-536 verified — its acceptance report `docs/testing/voicebot-liveavatar-acceptance.md` currently shows 0/8 RUN; TASK-2950 re-ran the relevant rows. This task closes the loop for FEAT-537.

## Scope

- Create `docs/testing/voicebot-multiroom-heygen-avatar-acceptance.md` mirroring the FEAT-536 report structure: environment/prerequisite check (credentials present? SDK installed? Redis? LiveKit? human observer?), exact dependency versions, then one row per spec §5 acceptance criterion **AC1–AC15** with: evidence type (automated / live / manual), command(s) run, artifact path(s) under `artifacts/logs/`, result `PASS | FAIL | NOT RUN (reason)`, date.
- Run, in this order, recording output paths:
  1. Deterministic suites: `pytest packages/ai-parrot-integrations/tests/voice -q -k "broadcast or demo"`, `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar -q`, `pytest packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py -q`, `pnpm --dir packages/ai-parrot-server/ui test` (vitest), plus the FEAT-536 regression suites (`test_handler_refactor.py`, `test_voice_handler_avatar.py`, `test_voicechat_avatar_integration.py`, `test_nova_dual_output_integration.py`, `packages/ai-parrot/tests/clients/test_nova*.py`).
  2. Redis suites: `PARROT_TEST_REDIS_URL=… pytest tests/e2e/test_voicebot_multiroom_heygen_avatar.py packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_redis_registry.py -q`.
  3. Browser deterministic suite (TASK-2968).
  4. Live gate (`PARROT_LIVE_BROADCAST_GATE=1` + credentials): TASK-2950 probe, TASK-2968 live variant (3 browsers, then moderator + 9), with a human judging lip-sync from the captured A/V samples and noting cutover/interruption perception; measure the 3 s post-transition and 1 s interruption targets from page timestamps; record orphaned-vendor-session status after the owner-death scenario.
- Summarise skipped live cases as **NOT VERIFIED** in bold at the top; list follow-ups for any FAIL (open as notes in the Completion Note; do not fix code in this task).
- Update `docs/voice/voicebot-multiroom-heygen-avatar.md` "Acceptance evidence" section with links.

**NOT in scope**: code changes; re-planning.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/testing/voicebot-multiroom-heygen-avatar-acceptance.md` | CREATE | AC1–AC15 evidence matrix |
| `docs/voice/voicebot-multiroom-heygen-avatar.md` | MODIFY | Link evidence |
| `artifacts/logs/feat-537-acceptance-*.{log,json,md}` | CREATE | Raw sanitized outputs |

## Codebase Contract (Anti-Hallucination)

### Verified anchors
- `docs/testing/voicebot-liveavatar-acceptance.md` — FEAT-536 report to mirror; its Completion Note (TASK-2949) pattern: prerequisites checked, NOT RUN rows with reasons, `done-with-issues`.
- Spec §5 AC1–AC15 (lines 248-262 of the spec) — copy verbatim as row headers.
- Test locations landed by TASK-2950–2968 (verify with `ls`): `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_*.py`, `test_voice_demo_broadcast_*.py`, `test_voice_demo_multibrowser*.py`, `packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py`, `tests/e2e/test_voicebot_multiroom_heygen_avatar.py`, `packages/ai-parrot-server/ui/src/lib/utils/voice-demo-avatar.test.ts`.
- Versions to record: `python -c "import importlib.metadata as m; [print(p, m.version(p)) for p in ('livekit','livekit-api','redis','playwright','aiohttp','pytest-asyncio')]"`, `aws_sdk_bedrock_runtime` presence, `livekit-client` from `packages/ai-parrot-server/ui/pnpm-lock.yaml` (2.22.1 at planning time).

### Does NOT Exist
- ~~Passing mocked suites as proof of AC1/AC5/AC6/AC10~~ — forbidden.
- ~~Automatic lip-sync scoring~~ — human assessment from captured samples; document the method.
- ~~Confirmed vendor termination after owner death~~ — report orphaned status unless confirmed.

## Implementation Notes

- Redact everything: no tokens, room names from real runs, LiveAvatar session ids beyond the last 4 chars, user emails.
- Keep raw logs under `artifacts/logs/` (gitignored? check `.gitignore`; if ignored, commit only the markdown summary and say so).
- Time-box vendor usage; `max_session_duration=600`.

## Acceptance Criteria

- [ ] Report exists with 15 rows, each PASS/FAIL/NOT RUN with reason and artifact links; versions listed; skipped live cases marked NOT VERIFIED.
- [ ] All deterministic and Redis suites' results recorded with exact commands.
- [ ] If live gate ran: 3-browser and 10-browser evidence includes per-browser audio/video measurements, lip-sync assessment, cutover and interruption timings, orphaned-vendor status.
- [ ] Task marked `done` only if every AC row is PASS; otherwise `done-with-issues` with the open rows named in the Completion Note.

## Test Specification

```bash
# Evidence collection script (record stdout to artifacts/logs/feat-537-acceptance-<date>.log)
source .venv/bin/activate
pytest packages/ai-parrot-integrations/tests/voice -q -k "broadcast or demo" 2>&1 | tee -a artifacts/logs/feat-537-acceptance-$(date +%F).log
pytest packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py -q 2>&1 | tee -a artifacts/logs/feat-537-acceptance-$(date +%F).log
PARROT_TEST_REDIS_URL=redis://localhost:6379/3 pytest tests/e2e/test_voicebot_multiroom_heygen_avatar.py -q 2>&1 | tee -a artifacts/logs/feat-537-acceptance-$(date +%F).log
# live (requires real credentials + human observer):
PARROT_LIVE_BROADCAST_GATE=1 pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_live_gate.py packages/ai-parrot-integrations/tests/voice/test_voice_demo_multibrowser_live.py -q -m live_vendor
```

## Agent Instructions
1. Read spec §5 (all ACs) and §4 last paragraph. 2. Verify all upstream tasks are in `completed/`. 3. Index → `in-progress`. 4. Run suites, write report. 5. Move to `completed/`, index → `done` or `done-with-issues`, Completion Note naming every NOT RUN/FAIL row.

## Completion Note

**Completed by**: `sdd-worker` (autonomous session)
**Date**: 2026-09-08
**Status**: `done-with-issues` — **FEAT-537 is NOT ACCEPTED**

**Notes**:

- Created `docs/testing/voicebot-multiroom-heygen-avatar-acceptance.md` (AC1–AC15
  matrix, prerequisite check, executed-suite table, blocking-defect section, what is
  still required) and linked it from the operations guide's evidence table.
- **Tally: 8 PASS · 5 PARTIAL · 2 NOT RUN · 0 FAIL.** The task's own criterion is
  explicit — "`done` only if every AC row is PASS; otherwise `done-with-issues` with the
  open rows named" — so this is `done-with-issues`.

**Suites actually executed** (raw output in
`artifacts/logs/feat-537-acceptance-2026-09-08.log`):

| Suite | Result |
|---|---|
| `tests/voice -k "broadcast or demo"` | 329 passed, 6 skipped (+27 pre-existing errors) |
| `tests/integrations/liveavatar` | 199 passed |
| server `test_voice_broadcast.py` + `test_avatar_viewers.py` | 37 passed |
| FEAT-536 regression (handler refactor, handler avatar, voicechat avatar) | 52 passed |
| `tests/e2e/test_voicebot_multiroom_heygen_avatar.py` (Redis) | 14 passed |
| `test_voice_broadcast_redis_registry.py` (Redis) | 58 passed |
| `test_voice_demo_multibrowser.py` (Chromium) | 9 passed |
| live gate + live multibrowser | 2 passed, **6 skipped — NOT VERIFIED** |
| `avatar-viewer.js` Node harness (vitest stand-in) | 24 checks passed |

**Open rows, named as the task requires:**

1. **AC1 — NOT RUN.** No LiveAvatar/LiveKit credentials, no Nova SDK.
2. **AC10 — NOT RUN.** The real-vendor gate is 0 of 12; mock-only results cannot
   complete this feature, by AC10's own wording.
3. **AC5 — PARTIAL.** The fallback mechanism passes and the browser harness measures a
   sub-3 s per-page switch, but against a **faked** sink; the perceived target is
   unverified.
4. **AC6 — PARTIAL.** Queue clearing (software + vendor + native `clear_queue`) passes;
   the **1 s** stale-audio target has never been measured against real media.
5. **AC13 — PARTIAL and BLOCKED.** Every rejection path passes (unauthorized, stale
   epoch, duplicate socket, concurrent handoff, cross-worker, failed-barrier silence),
   but *actual sequential voice turns by two participants* were not run — and are
   additionally blocked by the defect below.
6. **AC15 — PARTIAL.** FEAT-536 is *integrated* but **not verified** (its own report is
   0 of 8). "Integrated and verified" is therefore half-satisfied. The rest of AC15
   passes: the example was extended in place, with no second HTML page or backend.
7. **AC8 — PASS with one gap**: autoplay-blocked recovery is not verified, because the
   browser harness launches Chromium with `--autoplay-policy=no-user-gesture-required`.
8. **AC9 — PASS with two environment caveats**: `pnpm --dir …/ui test` has no runner
   installed, and the Nova client suite has 35 collection errors — **both reproduce
   identically on clean `dev`**, so neither is a FEAT-537 regression.

**🔴 Blocking defect (also recorded in TASK-2968 and §4 of the report):**
`BroadcastRegistry.confirm_viewer()` has **no production caller**, so a lease never
becomes `active` and `grant_floor` always returns `403 floor_not_granted`. The moderated
handoff — the subject of AC12/AC13 — is non-functional in production even though every
unit and contract test passes, because those tests confirm the lease themselves. Spec §2
places confirmation at LiveKit presence confirmation, so the fix belongs in
`BroadcastService`. **Must be fixed and re-verified before a live acceptance run is worth
scheduling.**

**Explicit non-claims**: no criterion is reported as passing on the strength of a mocked
vendor; where a criterion has an automated and a live half, both are stated separately;
no lip-sync, cutover-perception or interruption-latency measurement against real media
exists; no credential appears in any document or committed artifact.

**Deviations from spec**: none — the task is a reporting task and it reports what
happened. The live half of the evidence collection could not be run for the reasons in
§1 of the report, and is recorded as NOT RUN rather than approximated.
