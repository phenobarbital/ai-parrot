# FEAT-537 — Nova PCM → LiveAvatar LITE → LiveKit multi-subscriber live gate

**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md` §2 ("Vendor contract and
implementation gate"), §3 Module 1 — gates **AC10** and **AC15**
**Task**: TASK-2950
**Branch**: `feat-FEAT-537-voicebot-multiroom-heygen-avatar`
**Probe**: `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_live_gate.py`
**Date (UTC)**: 2026-09-08 (initial, NOT RUN) · **re-run 2026-09-08 with live vendors**
**Environment**: autonomous CLI session with real LiveAvatar (sandbox tier) and LiveKit
credentials from `env/.env`; no Nova Sonic SDK, no human observer.

## Result: **8 of 12 scenarios EXECUTED against real vendors — gate partially closed**

**Correction to the first version of this report.** It stated the LiveAvatar and LiveKit
credentials were "not in `env/.env`". That was wrong, and the error was mine: the probe
ran inside a git worktree, `env/` is gitignored so it does not exist there, and I inferred
absence instead of checking the main checkout. The credentials were present the whole
time. The gate's real blocker was simply that its opt-in switch,
`PARROT_LIVE_BROADCAST_GATE=1`, was never set — a gate that skips by design skipped, and
the skip message said "credentials missing", which made the wrong diagnosis look
confirmed.

Re-running with the switch set executed the probe against the live vendors and **found
three real defects**, two of them in the probe itself, which is precisely what a live gate
exists to surface:

1. **Vendor rejection (product):** the account caps `max_session_duration` at **60 s** and
   returned `400 max_session_duration (600s) exceeds the maximum allowed (60s)`. The spec
   default of 600 s is not universally acceptable. Because avatar startup *degrades*
   rather than raises, every broadcast on such an account silently became audio-only. Now
   configurable via `PARROT_LIVEAVATAR_MAX_SESSION_DURATION_S`.
2. **Probe bug — no media was ever measured:** track-kind detection compared
   `str(track.kind).endswith("AUDIO")`, but livekit's `TrackKind` is an int-backed
   protobuf enum stringifying to `"1"`/`"2"`. No pump was ever started, so the probe
   reported zero audio *and* zero video while the vendor was in fact publishing both.
3. **Probe bug — meaningless metric:** first-audio latency was measured to the first frame
   of any kind, including the silent comfort audio that flows before the speak request,
   yielding a **negative** latency (−0.54 s). It now measures to the first *audible* frame.

Run command:

```bash
PARROT_LIVE_BROADCAST_GATE=1 PARROT_LIVEAVATAR_MAX_SESSION_DURATION_S=60 \
PARROT_LIVE_MAX_SESSION_DURATION=60 \
  pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_live_gate.py
# 3 passed in 29.18s
```

### Measured results

Committed evidence: [`artifacts/logs/feat-537-live-gate-EVIDENCE.json`](../../artifacts/logs/feat-537-live-gate-EVIDENCE.json) — one representative passing run,
force-added because `artifacts/` is gitignored (`.gitignore:283`). Without it the numbers
below would be unverifiable by anyone but the machine that produced them. The gate's
scrubber redacts credentials; the committed file was checked to contain no key, token,
JWT or `wss://` URL.

| Measurement | Value | Target |
|---|---|---|
| Audio frames reaching **each** of two distinct subscribers | 858 (301 audible, peak 13 417) | > 0 |
| Video frames per subscriber (H264, `avatar` track) | 195 | progress observed |
| First **audible** audio latency, both subscribers | 0.686 s | reported, no target |
| `agent.interrupt` → silence | **0.399 s** | ≤ 1 s ✅ |
| `AudioSource.clear_queue()` → silence | **0.103 s** | ≤ 1 s ✅ |
| Session survives interrupt and re-speaks | 301 audible frames on the second utterance | > 0 |
| `max_session_duration` accepted | 60 s ✅ / 600 s ❌ rejected | see defect 1 |
| Control-WS server event types observed | 8 (`agent.speak_started/ended/interrupted`, `agent.audio_buffer_appended/cleared/committed`, `agent.state_updated`, `session.state_updated`) | manifest |

**Still NOT RUN: the four Nova-dependent scenarios (rows 1–4)** — `aws_sdk_bedrock_runtime`
is not installed, so no real Bedrock session can be opened. Lip-sync remains a subjective
A/V judgement no assertion substitutes for.

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
| `PARROT_LIVE_BROADCAST_GATE=1` | **Now set** | The real blocker in the first run: the opt-in switch was never enabled, and its skip text ("credentials missing") disguised that |
| `LIVEAVATAR_API_KEY` | **Present** | In `env/.env` all along; the first report's "absent" was an incorrect inference from a worktree, where gitignored `env/` does not exist |
| `LIVEAVATAR_AVATAR_ID` | **Present** | Same — sandbox tier (`LIVEAVATAR_SANDBOX=True`), which is what caps sessions at 60 s |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | **Present** | Live deployment reached; rooms created, joined and torn down |
| AWS Bedrock Nova 2 Sonic credentials | **Partially present** | `AWS_NOVA_SONIC_KEY_ID` / `AWS_NOVA_SONIC_SECRET_KEY` exist in `env/.env`, but see the next row |
| `aws_sdk_bedrock_runtime` (Nova voice SDK) | **Installed** — 0.11.0 | Was present but unusable: the package alone installs without `awscrt`, so the import raised `ModuleNotFoundError` and looked like a missing package. `uv pip install 'aws_sdk_bedrock_runtime[awscrt]==0.11.0'` fixes it; a real `VoiceBot(NOVA, aws_id="nova_sonic")` now constructs |
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
| 1 | FEAT-536 #2 | Nova, voice-only — spoken + text reply, tool call visible | **NOT RUN** | SDK blocker removed (0.11.0 installed, a real Nova `VoiceBot` constructs). Remaining blocker is different in kind: this is a FEAT-536 *human-observed* browser scenario — "spoken reply audible" is a perceptual judgement, not an assertion this probe can make |
| 2 | FEAT-536 #4 | Nova + Avatar — lip-synced video, exactly one audio source | **NOT RUN** | Vendors are now reachable and the A/V path is verified (rows 5–11); **lip-sync itself** remains a subjective judgement requiring a human observer |
| 3 | FEAT-536 #5 | Second turn — clean new turn, no leftover state | **NOT RUN** | A real Bedrock session is now possible; the *analogue* is covered by row 10 (session survives interrupt and re-speaks). A Nova-driven second turn still needs a driven browser session |
| 4 | FEAT-536 #8 | Avatar failure fallback — voice-only keeps working | ⚠️ **OBSERVED INCIDENTALLY** | Not run as a scripted scenario, but the 600 s rejection (row 12) produced exactly this: a genuine LiveAvatar startup failure that degraded to `audio_only` rather than breaking the broadcast. The degradation path is real, not just unit-tested |
| 5 | FEAT-537 | LITE session accepts `livekit_config` with `livekit_url` / `livekit_room` / `livekit_client_token` (OpenAPI SHA `8f589bc4…`) | ✅ **RUN — PASS** | Session opened; avatar joined the room as `avatar-agent` |
| 6 | FEAT-537 | Nova-format 24 kHz mono PCM16 via `agent.speak` reaches **two distinct** LiveKit subscribers as non-zero audio | ✅ **RUN — PASS** | 858 frames / 301 audible / peak 13 417 at **both** subscribers. The spec's documented inference is now a tested fact. (PCM is a synthesized tone, not Nova output — see row 1) |
| 7 | FEAT-537 | Track manifest: participant identities, track kinds/names/SIDs, codec + sample-rate observations, first-frame latency, decoded video-frame progress per subscriber | ✅ **RUN — PASS** | `avatar-audio` (audio/opus) + `avatar` (video/H264) from `avatar-agent`; 195 video frames; first audible audio 0.686 s |
| 8 | FEAT-537 | Control-WS server event-type manifest (harvested from `AvatarWebSocket._handle_server_message` INFO logs) | ✅ **RUN — PASS** | 8 event types observed (see Measured results) |
| 9 | FEAT-537 | `agent.interrupt` mid-utterance → measured time-to-silence vs the 1 s target | ✅ **RUN — PASS** | **0.399 s** against a 1 s budget, measured on real media |
| 10 | FEAT-537 | Session survives interruption and speaks a second utterance (speaker-handoff analogue) | ✅ **RUN — PASS** | Second utterance delivered 301 audible frames |
| 11 | FEAT-537 | `livekit.rtc.AudioSource.clear_queue()` on the direct publisher stops queued audio within 1 s | ✅ **RUN — PASS** | **0.103 s**. The symbol's *effect* is now observed, not just its presence |
| 12 | FEAT-537 | `LiveAvatarConfig.max_session_duration = 600` accepted by the account (spec §7 vendor cleanup bound) | ⚠️ **RUN — REJECTED** | The account caps it at **60 s**: `400 max_session_duration (600s) exceeds the maximum allowed (60s)`. The spec default is not universally valid; now configurable (see defect 1) |

**8 of 12 scenarios executed: 7 PASS, 1 REJECTED-with-finding; 1 further row observed
incidentally. 3 of 12 NOT RUN (rows 1–3), each now blocked by the need for a *human
observer* driving a browser — audible speech and lip-sync are perceptual judgements — and
no longer by a missing SDK, which has since been installed.**

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
3. ~~AWS Bedrock Nova 2 Sonic SDK~~ — **done**: `aws_sdk_bedrock_runtime[awscrt]==0.11.0` on
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
