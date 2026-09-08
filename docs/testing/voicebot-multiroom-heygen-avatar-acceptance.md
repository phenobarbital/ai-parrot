# FEAT-537 — Nova VoiceBot avatar broadcast: operational acceptance

**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md` §5 (AC1–AC15)
**Task**: TASK-2969
**Branch**: `feat-FEAT-537-voicebot-multiroom-heygen-avatar`
**Date (UTC)**: 2026-09-08
**Environment**: sandboxed autonomous `sdd-worker` CLI session — local Redis 8.4.0
and headless Chromium available; **no** LiveAvatar account, **no** LiveKit
deployment, **no** Nova Sonic SDK, **no** human observer.

---

## Result: **NOT ACCEPTED — 9 of 15 criteria PASS, 5 partial, 1 NOT RUN**

> ## ⚠️ NOT VERIFIED
>
> **No acceptance criterion involving a real vendor has been executed.** AC1 and
> AC10 are **NOT RUN** outright; AC5, AC6, AC13 and AC15 are only partially
> satisfied because their vendor half cannot run here. Mock-only results
> explicitly cannot complete this feature (AC10: *"Mock-only results cannot
> complete this feature"*).
>
> The blocking product defect found during acceptance (§4) — and every finding
> from the two adversarial reviews (§4c) — has since been **fixed and covered by
> tests**. The **live vendor gate has now been executed** (§7): 8 of 12 scenarios
> ran against real LiveAvatar + LiveKit, verifying the Module 1 media contract and
> the 1 s interruption budget on real media. What remains is the **Nova half** —
> `aws_sdk_bedrock_runtime` is not installed, so no real Bedrock turn has run — and
> **lip-sync**, which needs a human observer.

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
| `ai-parrot-client-google` / `-amazon` satellites | ✅ **Installed** (corrected) | Were absent from the venv, causing 27 collection errors **and 13 failures** in `tests/voice/`. Not a code defect and not FEAT-537's — the client split left the venv stale. `uv pip install --no-deps -e packages/ai-parrot-client-{amazon,google}` clears all of them (`--no-deps` matters: the manifests pin `ai-parrot>=1.0.0`, and resolving that would pull 1.0.0 from PyPI over the editable 0.28.1 workspace install). |
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
| — | `pytest packages/ai-parrot/tests/clients/ -k nova` | ⚠️ **PARTIAL** — `parrot.clients.amazon` now resolves; collection still stops on `parrot.clients.anthropic`, i.e. the remaining uninstalled `ai-parrot-client-*` satellites. Same environmental cause, unrelated to FEAT-537. |

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
| **AC6** — interruption clears native + software queues, stale speech stops within 1 s in both modes; delayed avatar events cannot become audible | automated (mechanism) + live (timing) | `test_voice_broadcast_media.py` (`interrupt` clears deque + `avatar.interrupt()` + `publisher.flush()`→`clear_queue`), `test_room_audio_publisher.py`, scenario 6 late-avatar rejection; **live gate**: `agent.interrupt`→silence **0.399 s**, `clear_queue`→silence **0.103 s** | **PASS** — mechanism PASS and the **1 s** target is now **MEASURED on real media**, both modes, well inside budget |
| **AC7** — cross-worker stop, owner fencing, rollback and shutdown; ≤ 30 s process-death cleanup; fatal failures not mislabelled as fallback | automated | suite 5 (`stop` on worker A ends the producer owned by B; owner death fenced, room emptied, `failed`/`owner_lost`, simulated ≤ 30 s) · `test_voice_broadcast_media.py` (LiveKit prerequisite failure → `failed`, never `audio_only`) | **PASS** (simulated clock) |
| **AC8** — HTML roles, Raise Hand/Cancel, Grant/Revoke/Reclaim, Finish Speaking, real resampling, existing-track attachment, autoplay recovery; ungranted participants never capture | automated | suite 7 scenarios 2, 3, 8 · `test_voice_demo_broadcast_browser.py` (stateful 44.1 kHz→16 kHz resampler, `getUserMedia` spy = 0 calls) · scenario 1 late-join attachment | **PASS** — except **autoplay-blocked recovery**, which the harness forces off (`--autoplay-policy=no-user-gesture-required`) and is therefore **NOT VERIFIED** |
| **AC9** — scoped pytest, real Redis and browser suites pass; existing voice/avatar regressions green; logs identify versions and skipped live cases | automated | suites 1–8; **`tests/voice/` now 542 passed / 7 skipped / 0 failed / 0 errors** once the client satellites were installed (`dev` is 189/0 on the same env); versions in §1 | **PASS** — the only remaining caveat is `pnpm test` (vitest), whose runner is not installed |
| **AC10** — Module 1 and the 3-/10-browser real-vendor gates recorded, incl. media playback and lip-sync assessment | live | [`voicebot-multiroom-live-gate.md`](voicebot-multiroom-live-gate.md) — **8 of 12 executed** (7 PASS, 1 REJECTED-with-finding); real LiveAvatar + LiveKit, two subscribers, 858 audio / 195 video frames each | **PARTIAL** — Module 1 media contract is now **verified live**. Still NOT RUN: the four Nova/Bedrock rows (SDK not installed) and lip-sync, which needs a human observer |
| **AC11** — setup/authentication/environment/limits/failure-injection docs complete with exact tested commands; FULL/custom-LLM and non-broadcast interfaces still compatible | automated + review | `examples/clients/voice/README.md` §Broadcast mode, [`docs/voice/voicebot-multiroom-heygen-avatar.md`](../voice/voicebot-multiroom-heygen-avatar.md); env names grep-verified, links checked, commands executed; suites 2 & 4 prove the legacy avatar/voice paths unchanged | **PASS** |
| **AC12** — concurrent first joins select exactly one moderator; a raised hand grants no microphone; only the moderator grants/revokes/reclaims; the moderator cannot transmit while another holds the floor | automated | suite 1 (`test_first_admission_elects_single_moderator_under_race`), suite 5, suite 7 scenarios 2 & 3 | **PASS** |
| **AC13** — two different participants complete sequential voice turns through the same conversation; unauthorized, stale-epoch and duplicate-socket audio rejected, incl. concurrent handoffs and across workers; a failed handoff stays silent with a visible error | automated (rejection) + live (turns) | Rejection: suites 1, 5, 6, 7 (`floor_not_granted`, `stale_floor_epoch`, `speaker_connection_exists`, cross-worker binding, barrier-timeout → floor idle + retryable error). Turns: — | **PARTIAL** — the rejection half is PASS; **actual sequential voice turns are NOT RUN** (no vendor access). The §4 defect that previously blocked them is fixed, and the handoff is exercised end-to-end against faked vendors |
| **AC14** — speaker departure returns the floor to the moderator; moderator departure elects the earliest remaining participant; rejoining restores nothing; all browsers show the new roles; the last departure cleans up | automated | suites 1, 5, 7 scenario 3 (both remaining pages converge on the same successor); `test_last_departure_ends_the_broadcast` | **PASS** |
| **AC15** — FEAT-536 integrated **and verified** before FEAT-537 implementation; extends the existing HTML/server/viewer/SDK route; no second HTML/backend; ordinary Gemini/Nova tests green | review + automated | Integrated: `dev` `f8a56c48b`. Verified: **no** (0/8). No second example: `dual_provider.html`, `server.py` and `avatar-viewer.js` were extended in place; `broadcast-ui.js` is an additional **asset**, not a second page. Ordinary tests: suites 2 & 4 green | **PARTIAL** — "integrated" ✅, "verified" ❌ |

**Tally: 9 PASS · 5 PARTIAL · 1 NOT RUN · 0 FAIL.**  
_(AC6 PARTIAL→PASS and AC10 NOT RUN→PARTIAL after the live vendor gate was executed — see §7.)_

---

## 4. Blocking defect found during acceptance — ✅ FIXED

**`BroadcastRegistry.confirm_viewer()` had no production caller, so no floor
grant could succeed.**

- Found by TASK-2968 scenario 2 against the real service: the moderator's Grant
  returned `403 floor_not_granted`. Independently reproduced by the
  post-implementation adversarial review.
- Root cause: nothing transitioned a lease from `pending` to `active`, but
  `grant_floor` requires the target to be `active`. Every unit and contract
  test passed because each one confirmed the lease itself.
- **Fixed** by wiring confirmation to server-observed LiveKit presence, which
  is what spec §2 asks for ("participant events or periodic reconciliation")
  and keeps `confirmed` meaning *the LiveKit server says this browser is in the
  room* — never a client asserting readiness, since that flag is exactly what
  gates holding the floor:
  - `RoomAudioPublisher` observes `participant_connected` / `_disconnected` on
    the producer's own room connection.
  - `BroadcastSession` forwards presence to `BroadcastService`, which resolves
    the identity to its lease and confirms it.
  - `BroadcastService.confirm_present_participants()` re-checks the room roster
    on every reconciler pass, as the backstop for missed events.
- The multi-browser scenarios now reach the floor through this production path
  instead of poking the registry; only LiveKit's roster is faked.

### 4b. Second-order consequence — moderator succession — ✅ FIXED

`_eligible_moderators()` requires `lease.confirmed`, so with nothing confirming
leases the candidate list was always empty, `_elect_locked()` always returned
`None`, and `release_viewer()` ended the broadcast with reason
`audience_empty` — **for an audience that was still watching**. Spec §105 is
explicit to the contrary: *"If the moderator leaves, elect the earliest
remaining admitted participant and publish the role change; do not stop the
broadcast while others remain."*

Fixed in both backends: the broadcast ends only when every remaining seat is
already departing; otherwise the role goes vacant and is filled by the next
confirmation. This also stops a broken-succession failure being reported as a
normal wind-down during triage.

### 4c. Adversarial review findings — all fixed

Two independent adversarial reviews were run with neutral briefs (no
conclusions supplied): the external `codex` CLI and the Claude `code-reviewer`
subagent. Every confirmed finding has been fixed on the branch.

| Finding | Resolution |
|---|---|
| Relayed cross-worker turns installed no speaker context, so a remote speaker inherited the previous speaker's `user_id` and tool permissions. | Fixed — the relay installs the frame's own lease context and fails closed if it cannot. |
| A departing socket's `aclose()` cleared the shared speaker context unconditionally, muting the next speaker after an A→B handoff. | Fixed — release is fenced on the turn generation. |
| WebSocket error frames forwarded `str(exc)` verbatim, against `BroadcastError`'s own contract. | Fixed — only the sanitized reason code crosses the boundary, matching HTTP. |
| `WorkerRelayServer` was never mounted and worker addresses never registered, so cross-worker speaking always failed `owner_lost`. | Fixed — both entry points serve the relay on its own internal listener (never the public app) and advertise the address. Opt-in; single-worker deployments grow no extra port. |
| A cross-worker grant skipped the producer barrier entirely, committing a handoff the producer never fenced. | Fixed — the barrier is relayed over the authenticated transport; an unreachable or stalled producer aborts the grant and leaves the floor idle and retryable. |
| Reconciliation scanned only process-local `_known`, so a dead owner was invisible to every worker that had not served it. | Fixed — store-wide via the new `BroadcastRegistry.list_broadcasts()`. |
| A transient LiveKit removal failure stranded a seat forever (eviction was reported once). | Fixed — `leaving` leases are re-reported until actually released, in both backends. |
| Publisher identities were not visible cross-worker, so other workers projected `selected_identity=None`. | Fixed — new `set_media_state()` persists the producer's media facts; it only ever fills in, never erases. |
| A viewer token could outlive its identity tombstone. | Fixed — tombstones now cover departure plus a full credential TTL. |
| `?token=` query-string credentials accepted on the broadcast socket. | Fixed — subprotocol only; the shipped client already used it. |
| `_RateLimiter._hits` grew one deque per principal forever. | Fixed — quiet principals swept, amortised to once per window. |
| The demo bound anywhere when authentication was disabled (the weaker of the two configurations was the unguarded one). | Fixed — non-loopback binding refused in both configurations. |

Checked and **rejected with evidence**: *"the same-worker audio path never
re-validates against the live floor."* `BroadcastVoiceSession.push_audio` calls
both `_require_speaker()` and `_require_current_floor()`, the latter comparing
the speaker's floor epoch against the live broadcast's. The review sampled the
branch before that fix landed.

Not changed: the demo's `#demo_token` URL **fragment**. Fragments are never
sent in HTTP requests and it is stripped from the address bar immediately; the
credential-in-logs risk was the `?token=` query form, which is gone.

---

## 5. What is still required to accept this feature

1. ~~Fix the `confirm_viewer` gap~~ — done (§4/§4b); suites 1, 5 and 7 re-run
   and passing against the production confirmation path.
2. A LiveAvatar account (`LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`) and a
   reachable LiveKit deployment.
3. ~~AWS Bedrock Nova 2 Sonic SDK~~ — **installed**: `aws_sdk_bedrock_runtime[awscrt]==0.11.0` on
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

---

## 7. Live vendor gate — executed 2026-09-08

The gate was re-run with real LiveAvatar (sandbox tier) and LiveKit credentials.
**8 of 12 scenarios executed: 7 PASS, 1 REJECTED-with-finding.** Full record and
measurements: [`voicebot-multiroom-live-gate.md`](voicebot-multiroom-live-gate.md).

**Correction.** The earlier report said the vendor credentials were absent from
`env/.env`. They were not — that was an incorrect inference on my part: the probe runs in
a git worktree, `env/` is gitignored so it is absent *there*, and I never checked the main
checkout. The gate's actual blocker was that its opt-in switch,
`PARROT_LIVE_BROADCAST_GATE=1`, was never set; its skip message reads "credentials
missing", which made the wrong diagnosis look confirmed. Everything previously reported as
NOT RUN "for lack of credentials" was in fact runnable.

Executing it found three defects — one product, two in the probe itself:

1. **Product:** the account caps `max_session_duration` at 60 s and rejects the spec
   default of 600 s outright (`400`). Because avatar startup degrades instead of raising,
   every broadcast on such an account silently fell back to audio-only, with the real
   cause visible only in a warning log. Fixed: configurable via
   `PARROT_LIVEAVATAR_MAX_SESSION_DURATION_S` (default unchanged at the spec's 600 s).
2. **Probe:** track-kind detection compared `str(track.kind).endswith("AUDIO")`, but
   livekit's `TrackKind` is an int-backed enum stringifying to `"1"`/`"2"`, so no media
   pump was ever started — the probe reported zero audio *and* zero video while the vendor
   was publishing both. This is the failure mode a harness written without ever running
   against the vendor is most prone to, and it would have made a green gate meaningless.
3. **Probe:** first-audio latency was measured to the first frame of any kind, including
   pre-utterance silent comfort audio, producing a **negative** figure (−0.54 s). It now
   measures to the first *audible* frame: 0.686 s.

**What this does and does not establish.** The Module 1 media contract is now verified on
real infrastructure: LITE accepts our `livekit_config`, 24 kHz PCM16 through `agent.speak`
reaches **two distinct** subscribers as non-zero audio (858 frames, 301 audible, peak
13 417 each, plus 195 H264 video frames), interrupt stops speech in 0.399 s and
`clear_queue` in 0.103 s — both inside the 1 s budget. It does **not** establish the Nova
half: the PCM in these scenarios is a synthesized tone, and no real Bedrock turn has run.

**SDK update.** `aws_sdk_bedrock_runtime` is now installed (0.11.0) and a real
`VoiceBot(NOVA, aws_id="nova_sonic")` constructs. It had in fact been present all along
but unusable, because the package installs without `awscrt` and the resulting
`ModuleNotFoundError` is indistinguishable from the package being absent — the repo's own
install instruction (`==0.7.0`, no extra) reproduced that trap, and is now corrected to
`aws_sdk_bedrock_runtime[awscrt]==0.11.0`.

So the remaining gap has changed in kind rather than merely in size: what blocks rows 1–3
is no longer tooling but a **human observer** — "the reply is audible" and "the video is
lip-synced" are perceptual judgements no assertion substitutes for. Row 4 (avatar failure
→ voice-only) was in fact observed incidentally: the 600 s rejection produced a genuine
LiveAvatar startup failure and the broadcast degraded to `audio_only` as designed.

**Follow-up: those two Nova tests were not defects either.** Installing the SDK un-skipped
`test_nova_audio_end_releases_browser_for_two_turns` and
`test_nova_denial_reaches_browser_and_closes_stream`, which then failed — but on
`ModuleNotFoundError: No module named 'parrot.clients.amazon'`, not on any assertion. The
`ai-parrot-client-*` satellites were simply never installed into the venv after the client
split. Installing the two that voice needs makes them pass and, with them, **the entire
`tests/voice/` suite: 542 passed, 7 skipped, 0 failed, 0 errors.**

This retires the "11 failed / 27 errors, identical on clean `dev`" baseline that earlier
revisions of this report leaned on to argue "no regressions". That baseline was an
artifact of an incomplete environment, not a property of the code, and treating it as
immovable meant a genuinely green suite was being reported as partly broken for the whole
feature. The comparison now reads: `dev` **189 passed / 0 failed**, this branch **542
passed / 0 failed**, on the same environment.

---
