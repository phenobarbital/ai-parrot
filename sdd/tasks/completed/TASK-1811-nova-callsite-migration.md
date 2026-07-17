# TASK-1811: Migrate all call sites to NovaClient and delete nova_sonic.py

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1809, TASK-1810
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. Resolved in proposal/spec Q&A: **migrate
everything now, no shim** — `parrot.clients.nova_sonic` is deleted and the
config-facing voice provider key is **renamed `'nova_sonic'` → `'nova'`**
(`VoiceProvider.NOVA = "nova"`). This is an INTENTIONAL breaking change and
must ship with a migration note. `ai-parrot-integrations` is a separate
distribution touched in the same branch (lockstep release — spec §7).

---

## Scope

- `packages/ai-parrot/src/parrot/bots/voice.py`: replace both `'nova_sonic'`
  dispatch sites (lines 164-177 and 211-225) with provider `'nova'` importing
  `NovaClient` from `parrot.clients.nova`; forward voice params (`voice_id`,
  region, etc.) as today; docstrings updated.
- `packages/ai-parrot/src/parrot/models/voice.py`: update any
  `nova_sonic` references (provider literals/config validation) to `'nova'`.
- `packages/ai-parrot-integrations/src/parrot/voice/models.py`: rename enum
  member `NOVA_SONIC = "nova_sonic"` (line 34) → `NOVA = "nova"`; update the
  FEAT-302 comment block (lines 29-33) to reference `parrot.clients.nova`.
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py`: update the
  lazy imports and docstrings (lines 77, 98, 332) to
  `from parrot.clients.nova import NovaClient`.
- DELETE `packages/ai-parrot/src/parrot/clients/nova_sonic.py`.
- Add a migration note documenting the breaking key rename (changelog or
  `docs/migration/feat-315-novaclient.md`).
- Repo-wide sweep: `grep -rn "nova_sonic" packages/` must return only test
  files (migrated in TASK-1812) and historical sdd/docs artifacts.

**NOT in scope**: test-file migration (TASK-1812) — but this task MUST leave
the production packages import-clean (tests may be temporarily red between
1811 and 1812 ONLY for module-path reasons; prefer landing 1811+1812 in
adjacent commits).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | provider `'nova'` → NovaClient (2 dispatch sites) |
| `packages/ai-parrot/src/parrot/models/voice.py` | MODIFY | provider literal updates |
| `packages/ai-parrot-integrations/src/parrot/voice/models.py` | MODIFY | `VoiceProvider.NOVA = "nova"` |
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | import path + docstrings |
| `packages/ai-parrot/src/parrot/clients/nova_sonic.py` | DELETE | superseded by `parrot/clients/nova/` |
| `docs/migration/feat-315-novaclient.md` | CREATE | breaking-change migration note |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.nova import NovaClient   # created by TASK-1809 (verify before use)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/voice.py — CURRENT dispatch (to replace):
#   lines 164-165: docstring — "'nova_sonic' (experimental) resolves to NovaSonicClient"
#   line 173: if provider == 'nova_sonic':
#   line 174:     from ..clients.nova_sonic import NovaSonicClient
#   line 176-177:     provider='nova_sonic', client_class=NovaSonicClient,
#   line 223: if config.provider == 'nova_sonic':
#   line 224:     from ..clients.nova_sonic import NovaSonicClient
#   line 225:     return NovaSonicClient(...)
# READ lines 150-240 in full before editing — the kwargs forwarded at line 225
# (voice params) must be forwarded identically to NovaClient.

# packages/ai-parrot-integrations/src/parrot/voice/models.py:
class VoiceProvider(Enum):                    # line 24
    NOVA_SONIC = "nova_sonic"                 # line 34 → becomes NOVA = "nova"
# NOTE comment block at lines 29-33 explains PCM 16k/24k AudioFormat compat — keep it,
# update the class reference to parrot.clients.nova.NovaClient.

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:
#   line 77: docstring reference to parrot.clients.nova_sonic.NovaSonicClient
#   line 98: from parrot.clients.nova_sonic import NovaSonicClient   (lazy import)
#   line 332: docstring reference

# packages/ai-parrot/src/parrot/models/voice.py — grep "nova" (references exist;
# verify exact lines before editing).

# NovaClient constructor (TASK-1809):
NovaClient(aws_id=None, region=None, profile=None, region_prefix="us",
    guardrail_id=None, guardrail_version=None, voice_id="matthew",
    aws_access_key=None, aws_secret_key=None, aws_session_token=None, **kwargs)
# Voice model note: NovaClient._default_model is "nova-2-lite" (TEXT).
# The voice dispatch MUST pass model="nova-2-sonic" (or the configured voice
# model) when constructing NovaClient for voice sessions — stream_voice
# resolves the model from self.model.
```

### Does NOT Exist
- ~~`parrot.clients.nova_sonic`~~ — after this task, the module is GONE;
  nothing in production packages may import it.
- ~~`VoiceProvider.NOVA_SONIC`~~ — renamed; no alias enum member is kept
  (resolved at spec time: no alias).
- ~~a deprecation shim / re-export~~ — explicitly rejected in Q&A.
- ~~`NovaSonicClient`~~ — class ceases to exist; the voice model is selected
  via `NovaClient(model="nova-2-sonic", ...)`.

---

## Implementation Notes

### Key Constraints
- Voice dispatch must set `model="nova-2-sonic"` explicitly (NovaClient's
  default is the TEXT model `nova-2-lite`) unless the voice config already
  carries a model value — inspect `bots/voice.py:150-240` and
  `models/voice.py` config fields before wiring.
- Keep lazy imports (inside the dispatch branch) — same as today.
- The migration note must show the before/after config snippet
  (`provider: nova_sonic` → `provider: nova`) and mention the lockstep
  release requirement for `ai-parrot-integrations`.
- After the delete, run the sweep:
  `grep -rn "nova_sonic" packages/ --include="*.py"` — only test files
  (owned by TASK-1812) may remain.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/voice.py:150-240` — dispatch to edit
- `sdd/specs/novaclient-amazon-aws.spec.md` §6 Integration Points

---

## Acceptance Criteria

- [ ] `bots/voice.py` provider `'nova'` builds a `NovaClient` with `model="nova-2-sonic"` (or config-provided model) and forwards voice params
- [ ] `VoiceProvider.NOVA == "nova"`; `"nova_sonic"` value removed
- [ ] `packages/ai-parrot/src/parrot/clients/nova_sonic.py` deleted
- [ ] `grep -rn "nova_sonic" packages/ --include="*.py"` → only `tests/` paths (until TASK-1812)
- [ ] `python -c "import parrot.bots.voice"` and integrations voice modules import cleanly
- [ ] Migration note exists documenting the breaking rename
- [ ] `ruff check` clean on all modified files

---

## Test Specification

> Full test migration happens in TASK-1812. This task only guarantees
> import-cleanliness of production code:

```bash
source .venv/bin/activate
python -c "from parrot.bots.voice import *"
python -c "from parrot.voice.models import VoiceProvider; assert VoiceProvider.NOVA.value == 'nova'"
python - <<'EOF'
try:
    import parrot.clients.nova_sonic
    raise SystemExit("FAIL: nova_sonic still importable")
except ImportError:
    print("OK: nova_sonic removed")
EOF
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§3 Module 6, §7 Known Risks)
2. **Check dependencies** — TASK-1809, TASK-1810 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `bots/voice.py:150-240` and both integrations files in full first
4. **Update status** in `sdd/tasks/index/novaclient-amazon-aws.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-17
**Notes**: `bots/voice.py`: both dispatch sites (`_resolve_llm_config`,
`_create_llm_client`) now branch on `provider == 'nova'`, import
`NovaClient` from `parrot.clients.nova`, and forward voice params
identically; `_resolve_llm_config` defaults the voice model to
`"nova-2-sonic"` when the caller didn't configure one (NovaClient's own
default is the TEXT model `nova-2-lite`). `models/voice.py`: comment
updated to document the `'nova_sonic'` → `'nova'` breaking rename.
`ai-parrot-integrations/voice/models.py`: `VoiceProvider.NOVA_SONIC =
"nova_sonic"` renamed to `NOVA = "nova"` (no alias). `voice/handler.py`:
`resolve_voice_client_class`/`resolve_provider_client` + docstrings updated
to `VoiceProvider.NOVA` → `parrot.clients.nova.NovaClient`. Deleted
`parrot/clients/nova_sonic.py`. Created
`docs/migration/feat-315-novaclient.md` (breaking-change note with
before/after snippets and the lockstep-release requirement). Verified
against the worktree's own source tree (not the editable-installed main-repo
copy — required copying two gitignored compiled `.so` build artifacts,
`utils/types` and `utils/parsers/toml`, into the worktree so raw `python -c`
imports resolve correctly; not committed): `from parrot.bots.voice import
VoiceBot`, `VoiceProvider.NOVA.value == 'nova'`, `resolve_voice_client_class
(NOVA) is NovaClient`, and `import parrot.clients.nova_sonic` → ImportError,
all pass. Sweep: `grep -rn "nova_sonic" packages/ --include="*.py"` outside
`tests/` only matches historical/migration-note comments in
`voice/models.py` (both packages) and `nova/audio.py`'s port-provenance
docstring — no functional imports/references remain. Two pre-existing test
files (`test_voicebot_nova_sonic_wiring.py`,
`test_nova_sonic_provider.py`) now fail as expected (assert on the old
`"nova_sonic"` string) — this is the documented TASK-1812 handoff, not a
regression. `ruff check` clean on all touched files except 4 pre-existing,
unrelated lint findings in `bots/voice.py` (unused imports/var, confirmed
present identically on `dev` before this work).

**Deviations from spec**: Also corrected a stale docstring reference in
`clients/bedrock.py` (`apply_guardrail_text`, pointed at the never-real
`parrot.integrations.bedrock.nova_sonic.NovaSonicClient` path) to point at
`NovaAudio._apply_pii_guardrail` — not in the task's file list, but
required to satisfy this task's own sweep acceptance criterion (a
production, non-test file still contained a `nova_sonic` reference).
