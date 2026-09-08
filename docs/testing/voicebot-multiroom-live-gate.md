# FEAT-537 — Nova PCM → LiveAvatar LITE → LiveKit multi-subscriber live gate

**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md` §2 ("Vendor contract and
implementation gate"), §3 Module 1 — gates **AC10** and **AC15**
**Task**: TASK-2950
**Branch**: `feat-FEAT-537-voicebot-multiroom-heygen-avatar`
**Probe**: `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_live_gate.py`
**Date (UTC)**: 2026-09-08
**Environment**: sandboxed autonomous `sdd-worker` CLI session — no LiveAvatar account,
no LiveKit deployment, no Nova Sonic SDK, no human observer.

## Result: **NOT RUN — the FEAT-537 live vendor gate remains open**

Per this task's own instruction ("If credentials/SDK/human are unavailable: still land the
probe code + report with every scenario NOT RUN and the concrete reason; mark this task
`done-with-issues`"), **zero** of the scenarios below were executed against real vendors.
The probe code exists, lints clean and skips cleanly — that is *not* evidence that the
vendor contract holds. Downstream FEAT-537 tasks therefore treat every media/timing
semantic in the spec as an **unverified default exposed as a configurable knob**
(see "Consequences for downstream tasks").

## Upstream dependency status (spec AC15)

AC15 requires FEAT-536 to be "integrated **and verified**" before FEAT-537 implementation.

| Condition | Status |
|---|---|
| FEAT-536 **integrated** into `dev` | ✅ Yes — merged as PR #1333, `dev` commit `f8a56c48b` |
| FEAT-536 **verified** (real-vendor acceptance) | ❌ No — `docs/testing/voicebot-liveavatar-acceptance.md` records **0 of 8** scenarios run, all NOT RUN for the same missing-credential reason |

**AC15 is therefore only half-satisfied.** This report re-states that gap rather than
inheriting FEAT-536's merge as if it were verification.

## Prerequisite check performed this session

| Prerequisite | Status | Detail |
|---|---|---|
| `PARROT_LIVE_BROADCAST_GATE=1` | **Unset** | The probe's opt-in switch was never enabled — nothing to enable it for |
| `LIVEAVATAR_API_KEY` | **Absent** | Not in the process env and not in `env/.env` |
| `LIVEAVATAR_AVATAR_ID` | **Absent** | Same |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | **Absent** | No LiveKit deployment is reachable or credentialed from this sandbox |
| AWS Bedrock Nova 2 Sonic credentials | **Partially present** | `AWS_NOVA_SONIC_KEY_ID` / `AWS_NOVA_SONIC_SECRET_KEY` exist in `env/.env`, but see the next row |
| `aws_sdk_bedrock_runtime` (Nova voice SDK) | **Not installed** | `import aws_sdk_bedrock_runtime` fails; the Nova route reports itself unavailable at startup |
| Human observer for lip-sync / playback judgement | **Absent** | This is an autonomous CLI session; lip-sync is a subjective A/V judgement no assertion can substitute for |
| `livekit` realtime SDK | **Present** — 1.1.14 | `rtc.AudioSource.clear_queue` / `wait_for_playout` confirmed present on this version |
| `livekit-api` | **Present** — 1.2.0 | Token minting works offline; no room to join |
| `livekit-client` UMD (browser) | **Present** — 2.22.1 | Served by FEAT-536's `/voice-assets/livekit-client.umd.js` route |
| `playwright` | **Present** — 1.52.0 | Irrelevant to this task (browser coverage is TASK-2968) |
| Python | 3.12.3 | Meets the Nova SDK's `>=3.12` requirement |

## Scenario matrix

Mirrors the FEAT-536 acceptance report layout. Rows 1–4 are the FEAT-536 rows this feature
depends on and that TASK-2950 was chartered to re-execute; rows 5–11 are FEAT-537's own
Module 1 probe.

| # | Origin | Scenario | Status | Reason |
|---|---|---|---|---|
| 1 | FEAT-536 #2 | Nova, voice-only — spoken + text reply, tool call visible | **NOT RUN** | `aws_sdk_bedrock_runtime` not installed; no live Bedrock session possible |
| 2 | FEAT-536 #4 | Nova + Avatar — lip-synced video, exactly one audio source | **NOT RUN** | No LiveAvatar account and no LiveKit deployment |
| 3 | FEAT-536 #5 | Second turn — clean new turn, no leftover state | **NOT RUN** | Requires a real provider session to open a first turn |
| 4 | FEAT-536 #8 | Avatar failure fallback — voice-only keeps working | **NOT RUN** | Requires a real (even misconfigured) LiveAvatar endpoint to observe a genuine failure |
| 5 | FEAT-537 | LITE session accepts `livekit_config` with `livekit_url` / `livekit_room` / `livekit_client_token` (OpenAPI SHA `8f589bc4…`) | **NOT RUN** | No LiveAvatar credentials |
| 6 | FEAT-537 | Nova-format 24 kHz mono PCM16 via `agent.speak` reaches **two distinct** LiveKit subscribers as non-zero audio | **NOT RUN** | No LiveAvatar/LiveKit credentials — this is *the* row that converts the spec's documented inference into a tested fact |
| 7 | FEAT-537 | Track manifest: participant identities, track kinds/names/SIDs, codec + sample-rate observations, first-frame latency, decoded video-frame progress per subscriber | **NOT RUN** | Same |
| 8 | FEAT-537 | Control-WS server event-type manifest (harvested from `AvatarWebSocket._handle_server_message` INFO logs) | **NOT RUN** | Same |
| 9 | FEAT-537 | `agent.interrupt` mid-utterance → measured time-to-silence vs the 1 s target | **NOT RUN** | Same |
| 10 | FEAT-537 | Session survives interruption and speaks a second utterance (speaker-handoff analogue) | **NOT RUN** | Same |
| 11 | FEAT-537 | `livekit.rtc.AudioSource.clear_queue()` on the direct publisher stops queued audio within 1 s | **NOT RUN** | Needs a real LiveKit room; the *symbol* is confirmed present in livekit 1.1.14, its *effect* is not |
| 12 | FEAT-537 | `LiveAvatarConfig.max_session_duration = 600` accepted by the account (spec §7 vendor cleanup bound) | **NOT RUN** | No account to accept or reject it |

**0 of 12 scenarios executed. 12 of 12 NOT RUN with reason.**

## What the probe *does* verify today

These are code-level facts, deliberately not presented as vendor evidence:

- The probe module imports and collects with `--strict-markers` and skips with three `s`
  when the gate is off: `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_live_gate.py -q` → `3 skipped`.
- `ruff check` is clean on the probe module.
- No credential is read at import time; every read happens inside a fixture.
- Every value written to `artifacts/` passes through `_sanitize()`, which strips JWTs,
  `ws(s)://` URLs and any literal credential value.
- `rtc.AudioSource.clear_queue` and `rtc.AudioSource.wait_for_playout` exist on the
  installed `livekit` 1.1.14 (symbol presence only).

## Recorded dependency versions

| Dependency | Version |
|---|---|
| `livekit` | 1.1.14 |
| `livekit-api` | 1.2.0 |
| `livekit-client` (browser UMD) | 2.22.1 |
| `playwright` | 1.52.0 |
| `redis` | 5.2.1 |
| `aws_sdk_bedrock_runtime` | **not installed** |
| Python | 3.12.3 |

## Consequences for downstream tasks

Because rows 5–12 are NOT RUN, the following spec values remain **unverified defaults** and
MUST be implemented as configurable knobs rather than hard-coded constants, so a later live
run can correct them without a code change:

| Value | Default | Spec reference |
|---|---|---|
| Avatar startup readiness deadline | 15 s | §2 "Audio routing, failure and interruption" |
| Expected-speech progress watchdog | 10 s | §2 (runtime fallback triggers) |
| Per-send vendor deadline | 2 s | §2 |
| Interrupt time-to-silence target | 1 s | §2 / AC6 |
| Post-fallback audible-audio target | 3 s | §2 / AC5 |
| Max vendor session duration | 600 s | §7 |

Downstream tasks must **not** report AC5/AC6/AC10 as satisfied on the strength of mocked
tests. AC10 explicitly states "Mock-only results cannot complete this feature".

## What would be needed to complete this task

1. A LiveAvatar account with LITE entitlement: `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`
   (plus `LIVEAVATAR_BASE_URL` / `LIVEAVATAR_SANDBOX` if not the defaults).
2. A reachable LiveKit deployment: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
3. AWS Bedrock Nova 2 Sonic model access with `aws_sdk_bedrock_runtime==0.7.0` installed on
   Python ≥ 3.12 (for rows 1–4; rows 5–12 use a deterministic tone and do not need Nova).
4. A human observer for the lip-sync and synchronized-A/V-capture judgement that rows 2 and
   7 call for — no assertion in the probe substitutes for it.
5. Then: `PARROT_LIVE_BROADCAST_GATE=1 pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_live_gate.py -q -s`
   and replace every NOT RUN above with a dated PASS/FAIL plus the generated
   `artifacts/logs/feat-537-live-gate-<stamp>.json` manifest.

## Explicit non-claims

- No production code was changed by this task (the probe is a test module; the only
  non-test edit is the `live_vendor` marker registration).
- No scenario above is reported as passing, and no mocked test elsewhere in FEAT-536/537 is
  offered as a substitute for one.
- No token, credential, room URL or vendor session identifier appears in this document.
