# TASK-2966: README extension, operations guide and dependency extra for broadcast mode

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2965
**Parallel**: false
**Parallelism notes**: Docs-only plus a possible extras tweak; must describe the code as actually landed, so it runs after the UI task.

---

## Context

Spec §2: "`examples/clients/voice/README.md` and new `docs/voice/voicebot-multiroom-heygen-avatar.md`: exact tested installation/start commands, Python/SDK requirements, environment variable names, Redis/LiveKit/auth setup, moderator-plus-nine-participants walkthrough, Raise Hand/Grant/Finish Speaking, failure injection and expected cleanup. Link to FEAT-536's shared setup instead of duplicating." Module 6 docs; AC11.

## Scope

- `examples/clients/voice/README.md`: add a section `### Broadcast mode (FEAT-537)` after `### LiveAvatar viewer (optional, FEAT-536)` (`:63-98`) and extend `## Run it` (`:100`): env vars (`VOICEBOT_BROADCAST_REDIS_URL`, `VOICEBOT_DEMO_PARTICIPANTS`, `VOICEBOT_BROADCAST_WORKER_ID`, `PARROT_BROADCAST_WORKER_TOKEN`, `VOICEBOT_BROADCAST_FAILURE_HOOK`, plus the existing `LIVEAVATAR_*`/`LIVEKIT_*`/AWS ones), exact commands (`source .venv/bin/activate`, `uv pip install -e packages/ai-parrot-integrations[broadcast]` if the extra was added in TASK-2953, `pnpm --dir packages/ai-parrot-server/ui install --frozen-lockfile`, `redis-server`/docker one-liner, `python examples/clients/voice/server.py --host localhost`), the 10-browser walkthrough (first tab = moderator, nine more via the share link; 11th sees `viewer_limit_reached`), Raise Hand → Grant → Talk → Finish Speaking, failure injection with the hook flag and what every browser should show, expected cleanup timings (owner death ≤ 30 s, terminal state visible 5 min). Update `## Files` (`:174`) and `## Related` (`:183`).
- `docs/voice/voicebot-multiroom-heygen-avatar.md` (new; `docs/voice/` does not exist yet): architecture summary (component diagram from spec §2 copied as mermaid), roles/floor state machine, HTTP + WS API reference table (from TASK-2962/2960 as implemented — copy status codes from the tests), Redis key layout (TASK-2953), limits/timeouts table, security model (what never reaches the browser; demo mode is loopback-only), operations: env matrix, worker registry, reconciliation, orphaned vendor session caveat (spec §7), how to run deterministic suites, Redis suites and the live gate (`PARROT_LIVE_BROADCAST_GATE=1`), and the acceptance evidence locations (`docs/testing/voicebot-multiroom-live-gate.md`, `artifacts/logs/`). Link FEAT-536's `docs/testing/voicebot-liveavatar-acceptance.md` and README instead of duplicating setup.
- `packages/ai-parrot-integrations/pyproject.toml`: only if TASK-2953 did not add it, add `broadcast = ["ai-parrot-integrations[liveavatar]", "redis>=5.0"]`; keep `liveavatar` out of `all` (existing comment `:91-93`).
- Verify every command in the docs actually runs (or mark it "requires credentials" explicitly); record the versions you tested (`livekit`, `livekit-api`, `redis`, `playwright`, `livekit-client` UMD).

**NOT in scope**: code changes beyond the extras line; acceptance evidence (TASK-2969).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/README.md` | MODIFY | Broadcast section, run steps, walkthrough |
| `docs/voice/voicebot-multiroom-heygen-avatar.md` | CREATE | Operations/architecture guide |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY (conditional) | `broadcast` extra |

## Codebase Contract (Anti-Hallucination)

### Verified anchors
- `examples/clients/voice/README.md` headings: `# Dual VoiceChatHandler Provider-Switch Demo (FEAT-418)` :1, `## Prerequisites` :39, `### Gemini Live` :41, `### Amazon Nova 2 Sonic` :48, `### LiveAvatar viewer (optional, FEAT-536)` :63, `## Run it` :100, `## What's shared vs. what differs` :118, `## Real-live acceptance runbook (spec §4, AC13)` :151, `## Files` :174, `## Related` :183.
- README already documents: `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`, `LIVEAVATAR_BASE_URL`, `LIVEAVATAR_SANDBOX`, `LiveKitRoomManager` env, `pnpm --dir packages/ai-parrot-server/ui install --frozen-lockfile`, `python examples/clients/voice/server.py [--port 9000]`.
- `docs/testing/voicebot-liveavatar-acceptance.md` exists (FEAT-536 acceptance report, all NOT RUN).
- Integrations extras: `[project.optional-dependencies]` :33; `msteams` includes `redis>=5.0` :56; `liveavatar` :94-97 (`livekit-api>=1.0`, `livekit~=1.1`).
- Installed versions at planning time (re-check): livekit 1.1.14, livekit-api 1.2.0, redis 5.2.1, playwright 1.52.0, aiohttp 3.14.3, livekit-client UMD 2.22.1.
- Env var names must match what TASK-2961/2962/2963 actually implemented — grep `os.environ` in `broadcast/service.py`, `worker_transport.py`, `handlers/voice_broadcast.py`, `examples/clients/voice/server.py` before writing.

### Does NOT Exist
- ~~`docs/voice/`~~ — create it.
- ~~A separate broadcast backend or HTML~~ — document the single shared example only.
- ~~Confirmed vendor stop after owner death~~ — document as "orphaned until vendor expiry bound" (spec §7).

## Implementation Notes

- Every command in a fenced block must be copy-pasteable; annotate credential-requiring ones with `# requires real credentials`.
- Use a table for status codes/reasons and a table for timeouts (60 s pending, 15 s owner lease, 5 s renew/heartbeat, 15 s control expiry, 3 s barrier, 15 s avatar startup, 10 s speech watchdog, 2 s send deadline, 300 s terminal retention, 60 s viewer credential TTL).
- Do not paste tokens, room names from real runs, or LiveAvatar session ids.

## Acceptance Criteria

- [ ] README has the Broadcast section with exact env names and commands matching the code (grep-verified), 10-browser walkthrough and failure-injection steps.
- [ ] `docs/voice/voicebot-multiroom-heygen-avatar.md` covers architecture, roles, API table, Redis keys, limits, security, operations, test commands, evidence locations; links FEAT-536 docs.
- [ ] Extras: `pip install -e packages/ai-parrot-integrations[broadcast]` resolves (or the line already exists from TASK-2953).
- [ ] `markdownlint`-clean if the repo has a config; otherwise no broken relative links (check with a quick script).

## Test Specification

```bash
# Docs sanity (no pytest): every relative link resolves
python - <<'EOF'
import re, pathlib
for p in ["examples/clients/voice/README.md", "docs/voice/voicebot-multiroom-heygen-avatar.md"]:
    t = pathlib.Path(p).read_text()
    for link in re.findall(r"\]\(((?!http)[^)#]+)", t):
        assert (pathlib.Path(p).parent / link).exists(), (p, link)
print("links ok")
EOF
```

## Agent Instructions
1. Read spec §2 docs paragraph + §7 + §4 "Test Data / Fixtures" last paragraph (documentation must publish exact commands). 2. Grep env names in landed code. 3. Index → `in-progress`. 4. Write docs. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
