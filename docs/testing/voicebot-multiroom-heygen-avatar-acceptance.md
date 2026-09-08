# FEAT-537 — Nova VoiceBot avatar broadcast: operational acceptance

**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md` §5 (AC1–AC15)
**Task**: TASK-2969
**Branch**: `feat-FEAT-537-voicebot-multiroom-heygen-avatar`
**Date (UTC)**: 2026-09-08
**Environment**: sandboxed autonomous `sdd-worker` CLI session — local Redis 8.4.0
and headless Chromium available; **no** LiveAvatar account, **no** LiveKit
deployment, **no** Nova Sonic SDK, **no** human observer.

---

## Result: **NOT ACCEPTED — 8 of 15 criteria PASS, 5 partial, 2 NOT RUN**

> ## ⚠️ NOT VERIFIED
>
> **No acceptance criterion involving a real vendor has been executed.** AC1 and
> AC10 are **NOT RUN** outright; AC5, AC6, AC13 and AC15 are only partially
> satisfied because their vendor half cannot run here. Mock-only results
> explicitly cannot complete this feature (AC10: *"Mock-only results cannot
> complete this feature"*).
>
> There is also **one blocking product defect** (see §4) that must be fixed
> before a live run is even worth scheduling.

Prerequisite gate — **AC15 is half-satisfied**: FEAT-536 is *integrated* (PR
#1333, `dev` `f8a56c48b`) but **not verified** — its own report
[`voicebot-liveavatar-acceptance.md`](voicebot-liveavatar-acceptance.md) records
0 of 8 scenarios run. FEAT-537's own gate
([`voicebot-multiroom-live-gate.md`](voicebot-multiroom-live-gate.md)) records
0 of 12.

---

## 1. Prerequisite check

| Prerequisite | Status | Detail |
|---|---|---|
| Redis | ✅ **Present** | 8.4.0 at `redis://localhost:6379/3` |
| Headless Chromium (Playwright) | ✅ **Present** | 136.0.7103.25, `playwright` 1.52.0 |
| `livekit` / `livekit-api` | ✅ **Present** | 1.1.14 / 1.2.0 (token minting works offline) |
| `livekit-client` UMD | ✅ **Present** | 2.22.1 |
| `LIVEAVATAR_API_KEY` / `LIVEAVATAR_AVATAR_ID` | ❌ **Absent** | Not in env, not in `env/.env` |
| `LIVEKIT_URL` / `_API_KEY` / `_API_SECRET` | ❌ **Absent** | No reachable deployment |
| AWS Bedrock Nova 2 Sonic | ⚠️ **Partial** | `AWS_NOVA_SONIC_*` exist in `env/.env`, but `aws_sdk_bedrock_runtime` is **not installed** |
| Human observer (lip-sync, A/V judgement) | ❌ **Absent** | Autonomous CLI session |
| `ai-parrot-client-google` / `-amazon` satellites | ❌ **Not installed** | Causes 27 pre-existing collection errors in `tests/voice/` and 35 in `tests/clients/` — **identical on clean `dev`** |
| vitest (`ui/node_modules`) | ❌ **Not installed** | `pnpm exec vitest` → "Command not found"; not installed to avoid mutating the shared repo |

### Dependency versions

`livekit` 1.1.14 · `livekit-api` 1.2.0 · `livekit-client` UMD 2.22.1 · Redis
server 8.4.0 · `redis` (python) 5.2.1 · `playwright` 1.52.0 · `aiohttp` 3.14.3 ·
`aws_sdk_bedrock_runtime` **not installed** · Python 3.12.3

---

## 2. Suites executed

All commands run from the repo root with `source .venv/bin/activate`.
Raw output: `artifacts/logs/feat-537-acceptance-2026-09-08.log` (gitignored).

| # | Command | Result |
|---|---|---|
| 1 | `pytest packages/ai-parrot-integrations/tests/voice -q -k "broadcast or demo"` | **329 passed, 6 skipped**, 27 errors (pre-existing, see §1) |
| 2 | `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar -q` | **199 passed** |
| 3 | `pytest packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py -q` | **37 passed** |
| 4 | `pytest .../test_handler_refactor.py .../test_voice_handler_avatar.py .../test_voicechat_avatar_integration.py -q` (FEAT-536 regression) | **52 passed** |
| 5 | `PARROT_TEST_REDIS_URL=… pytest tests/e2e/test_voicebot_multiroom_heygen_avatar.py -q` | **14 passed** |
| 6 | `PARROT_TEST_REDIS_URL=… pytest .../test_voice_broadcast_redis_registry.py -q` | **58 passed** |
| 7 | `pytest .../test_voice_demo_multibrowser.py -q` | **9 passed** (stable over 3 runs) |
| 8 | `pytest .../test_voice_broadcast_live_gate.py .../test_voice_demo_multibrowser_live.py -q` | **2 passed, 6 skipped — NOT VERIFIED** |
| 9 | `node` harness for `avatar-viewer.js` broadcast policy | **24 checks passed** (stand-in for vitest, which is not installed) |
| — | `pnpm --dir packages/ai-parrot-server/ui test` | ❌ **NOT RUN** — vitest not installed |
| — | `pytest packages/ai-parrot/tests/clients/ -k nova` | ❌ **NOT RUN** — 35 collection errors, **identical on clean `dev`** (`parrot.clients.amazon` absent) |

Measurement artifacts produced: 32 × `artifacts/logs/feat-537-browser-*.json`,
`artifacts/logs/feat-537-crossworker-*.json`,
`artifacts/logs/feat-537-live-gate-2026-09-08.{md,json}` (all gitignored).

---

## 3. Acceptance criteria

| AC | Evidence type | Command / artifact | Result |
|---|---|---|---|
| **AC1** — two turns through real Nova → LITE → LiveKit, ≥ 3 browsers | live | — | **NOT RUN** — no LiveAvatar/LiveKit credentials, no Nova SDK |
| **AC2** — 10 concurrent receivers; concurrent 11th rejected across workers without a second provider | automated | suites 1, 5, 7 · `feat-537-crossworker-*.json` (12 attempts → 10 admitted, 2 × `viewer_limit_reached`, 1 producer start) · `feat-537-browser-scenario4-*.json` (10 live pages, 11th refused, 1 avatar session) | **PASS** (vendors faked) |
| **AC3** — unique subscribe-only credentials; tenant/agent/owner authz, floor/socket replay and lease-ownership tests; no vendor/publisher credentials in the browser | automated | suites 1, 3, 5, 6 · JWT grants decoded (`canPublish=false`, `canPublishData=false`, unique `sub`) · Redis scanned for `token|secret|ws_url|api_key` · browser scan of URL/localStorage/console | **PASS** |
| **AC4** — late join, leave and reconnect without starting/stopping the producer; stale credentials cannot bypass admission | automated | suites 1, 5, 7 · tombstone + identity-reuse tests · scenario 1 late joiner | **PASS** |
| **AC5** — startup and runtime avatar failure preserve Nova speech for all healthy viewers, exclusive playback, 3 s post-transition target; no auto-recovery or ambiguous replay | automated (mechanism) + live (perception) | suite 7 scenarios 5 & 6 · per-page switch latency **< 3 s** recorded in `feat-537-browser-scenario6-*.json`; `test_voice_broadcast_media.py` covers ambiguous-frame handling | **PARTIAL** — mechanism PASS; the 3 s figure is against a **faked** sink, so the real perceived target is **NOT VERIFIED** |
| **AC6** — interruption clears native + software queues, stale speech stops within 1 s in both modes; delayed avatar events cannot become audible | automated (mechanism) + live (timing) | `test_voice_broadcast_media.py` (`interrupt` clears deque + `avatar.interrupt()` + `publisher.flush()`→`clear_queue`), `test_room_audio_publisher.py`, scenario 6 late-avatar rejection | **PARTIAL** — mechanism PASS; the **1 s** target is **NOT MEASURED** against real media |
| **AC7** — cross-worker stop, owner fencing, rollback and shutdown; ≤ 30 s process-death cleanup; fatal failures not mislabelled as fallback | automated | suite 5 (`stop` on worker A ends the producer owned by B; owner death fenced, room emptied, `failed`/`owner_lost`, simulated ≤ 30 s) · `test_voice_broadcast_media.py` (LiveKit prerequisite failure → `failed`, never `audio_only`) | **PASS** (simulated clock) |
| **AC8** — HTML roles, Raise Hand/Cancel, Grant/Revoke/Reclaim, Finish Speaking, real resampling, existing-track attachment, autoplay recovery; ungranted participants never capture | automated | suite 7 scenarios 2, 3, 8 · `test_voice_demo_broadcast_browser.py` (stateful 44.1 kHz→16 kHz resampler, `getUserMedia` spy = 0 calls) · scenario 1 late-join attachment | **PASS** — except **autoplay-blocked recovery**, which the harness forces off (`--autoplay-policy=no-user-gesture-required`) and is therefore **NOT VERIFIED** |
| **AC9** — scoped pytest, real Redis and browser suites pass; existing voice/avatar regressions green; logs identify versions and skipped live cases | automated | suites 1–8; FEAT-536 regression **52 passed**; versions in §1; skips reported as NOT VERIFIED | **PASS** — with the caveat that `pnpm test` (vitest) and the Nova client suite could not run in this environment (both **identical on clean `dev`** or tool-absent) |
| **AC10** — Module 1 and the 3-/10-browser real-vendor gates recorded, incl. media playback and lip-sync assessment | live | [`voicebot-multiroom-live-gate.md`](voicebot-multiroom-live-gate.md) — **0 of 12** | **NOT RUN** |
| **AC11** — setup/authentication/environment/limits/failure-injection docs complete with exact tested commands; FULL/custom-LLM and non-broadcast interfaces still compatible | automated + review | `examples/clients/voice/README.md` §Broadcast mode, [`docs/voice/voicebot-multiroom-heygen-avatar.md`](../voice/voicebot-multiroom-heygen-avatar.md); env names grep-verified, links checked, commands executed; suites 2 & 4 prove the legacy avatar/voice paths unchanged | **PASS** |
| **AC12** — concurrent first joins select exactly one moderator; a raised hand grants no microphone; only the moderator grants/revokes/reclaims; the moderator cannot transmit while another holds the floor | automated | suite 1 (`test_first_admission_elects_single_moderator_under_race`), suite 5, suite 7 scenarios 2 & 3 | **PASS** |
| **AC13** — two different participants complete sequential voice turns through the same conversation; unauthorized, stale-epoch and duplicate-socket audio rejected, incl. concurrent handoffs and across workers; a failed handoff stays silent with a visible error | automated (rejection) + live (turns) | Rejection: suites 1, 5, 6, 7 (`floor_not_granted`, `stale_floor_epoch`, `speaker_connection_exists`, cross-worker binding, barrier-timeout → floor idle + retryable error). Turns: — | **PARTIAL / BLOCKED** — the rejection half is PASS; **actual sequential voice turns are NOT RUN**, and are additionally **blocked by the defect in §4** |
| **AC14** — speaker departure returns the floor to the moderator; moderator departure elects the earliest remaining participant; rejoining restores nothing; all browsers show the new roles; the last departure cleans up | automated | suites 1, 5, 7 scenario 3 (both remaining pages converge on the same successor); `test_last_departure_ends_the_broadcast` | **PASS** |
| **AC15** — FEAT-536 integrated **and verified** before FEAT-537 implementation; extends the existing HTML/server/viewer/SDK route; no second HTML/backend; ordinary Gemini/Nova tests green | review + automated | Integrated: `dev` `f8a56c48b`. Verified: **no** (0/8). No second example: `dual_provider.html`, `server.py` and `avatar-viewer.js` were extended in place; `broadcast-ui.js` is an additional **asset**, not a second page. Ordinary tests: suites 2 & 4 green | **PARTIAL** — "integrated" ✅, "verified" ❌ |

**Tally: 8 PASS · 5 PARTIAL · 2 NOT RUN · 0 FAIL.**

---

## 4. 🔴 Blocking defect found during acceptance

**`BroadcastRegistry.confirm_viewer()` has no production caller, so no floor
grant can succeed.**

- Found by TASK-2968 scenario 2 against the real service: the moderator's Grant
  returned `403 floor_not_granted`.
- `BroadcastService`, the HTTP handlers and the control socket never transition
  a lease from `pending` to `active`, but `grant_floor` requires the target to
  be `active`.
- Consequence: the moderated-handoff feature — AC12/AC13's whole subject — is
  non-functional in production despite every unit and contract test passing,
  because each of those tests confirms the lease itself.
- Spec §2 places confirmation at LiveKit presence confirmation (participant
  events or periodic reconciliation), so the fix belongs in `BroadcastService`.
- **Not fixed here**: TASK-2968 and TASK-2969 both scope out code changes. The
  browser suite documents and works around it in `confirm_all_leases()`.

**This must be fixed and re-verified before a live acceptance run is scheduled.**

---

## 5. What is still required to accept this feature

1. Fix the `confirm_viewer` gap above and re-run suites 1, 5 and 7.
2. A LiveAvatar account (`LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`) and a
   reachable LiveKit deployment.
3. AWS Bedrock Nova 2 Sonic access with `aws_sdk_bedrock_runtime==0.7.0` on
   Python ≥ 3.12.
4. `pnpm --dir packages/ai-parrot-server/ui install --frozen-lockfile`, then
   `pnpm --dir packages/ai-parrot-server/ui test` for the vitest suite that
   currently has no runner.
5. The `ai-parrot-client-google` / `-amazon` satellites installed, to clear the
   27 + 35 pre-existing collection errors (these are **not** FEAT-537
   regressions — they reproduce identically on clean `dev`).
6. A human observer to run the live gate: TASK-2950's probe, then the
   three-browser and moderator-plus-nine scenarios, judging lip-sync from the
   captured A/V samples and reporting measured cutover (3 s) and interruption
   (1 s) perception plus orphaned-vendor status after owner death.
7. Replace every **NOT RUN** / **PARTIAL** row above with a dated PASS/FAIL and
   artifact links.

## 6. Explicit non-claims

- No acceptance criterion is reported as passing on the strength of a mocked
  vendor. Where a criterion has an automated half and a live half, both halves
  are stated separately.
- No live scenario was executed. No lip-sync, cutover-perception or
  interruption-latency measurement against real media exists.
- No token, credential, room URL or vendor session identifier appears in this
  document or in any committed artifact.
