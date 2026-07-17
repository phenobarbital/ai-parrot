# TASK-1812: Migrate test suites to NovaClient + close coverage gaps

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1811
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7 — the closing task. Five existing suites pin the
old module path / provider key and must be migrated; the spec's §4 test table
lists the target coverage. The existing Bedrock suite is the regression gate
for the TASK-1806 base extraction and must pass UNMODIFIED.

---

## Scope

- Migrate (rename + repoint imports/keys, PRESERVE the protocol assertions):
  - `packages/ai-parrot/tests/clients/test_nova_sonic.py` →
    `packages/ai-parrot/tests/clients/test_nova.py` — voice protocol tests now
    target `NovaClient(model="nova-2-sonic", ...)` / the `NovaAudio` methods;
    reuse the existing bidirectional-stream stub fixture.
  - `packages/ai-parrot/tests/bots/test_voicebot_nova_sonic_wiring.py` →
    `test_voicebot_nova_wiring.py` — provider `'nova'` wiring.
  - `packages/ai-parrot/tests/models/test_voice_config.py` — provider literal
    updates (`'nova_sonic'` → `'nova'`).
  - `packages/ai-parrot/tests/models/test_bedrock_models.py` — keep; verify
    TASK-1810 additions are covered (add if missing).
  - `packages/ai-parrot-integrations/tests/voice/test_nova_sonic_provider.py`
    → `test_nova_provider.py` — `VoiceProvider.NOVA` + new import path.
- Verify §4 unit-test coverage is complete across TASK-1806..1811 test files;
  add any missing tests (e.g. `test_no_nova_sonic_module`,
  `test_voice_provider_renamed`).
- Add the optional live-integration test `test_nova_ask_live` marked
  `@pytest.mark.integration` (skipped by default in CI).
- Final sweep: `grep -rn "nova_sonic" packages/ --include="*.py"` returns
  NOTHING.
- Run the FULL affected test set and record results.

**NOT in scope**: any production-code change (if migration reveals a bug,
report it in the Completion Note; trivial fixes allowed only in files owned
by earlier FEAT-315 tasks with a note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/clients/test_nova.py` | CREATE (from test_nova_sonic.py) | voice protocol suite |
| `packages/ai-parrot/tests/clients/test_nova_sonic.py` | DELETE | superseded |
| `packages/ai-parrot/tests/bots/test_voicebot_nova_wiring.py` | CREATE (from ..._nova_sonic_wiring.py) | provider wiring |
| `packages/ai-parrot/tests/bots/test_voicebot_nova_sonic_wiring.py` | DELETE | superseded |
| `packages/ai-parrot/tests/models/test_voice_config.py` | MODIFY | provider literals |
| `packages/ai-parrot/tests/models/test_bedrock_models.py` | MODIFY | ensure new-entry coverage |
| `packages/ai-parrot-integrations/tests/voice/test_nova_provider.py` | CREATE (from test_nova_sonic_provider.py) | integrations provider |
| `packages/ai-parrot-integrations/tests/voice/test_nova_sonic_provider.py` | DELETE | superseded |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.nova import NovaClient                # TASK-1809
from parrot.clients.nova.audio import NovaAudio           # TASK-1807
from parrot.clients.nova.generation import NovaGeneration # TASK-1808
from parrot.clients.bedrock import BedrockConverseBase, BedrockConverseClient  # TASK-1806
from parrot.voice.models import VoiceProvider             # integrations; NOVA = "nova" post TASK-1811
```

### Existing Signatures to Use
```python
# Migration sources — READ EACH IN FULL before porting:
# packages/ai-parrot/tests/clients/test_nova_sonic.py            (voice protocol + stream stub fixture)
# packages/ai-parrot/tests/bots/test_voicebot_nova_sonic_wiring.py
# packages/ai-parrot/tests/models/test_voice_config.py
# packages/ai-parrot-integrations/tests/voice/test_nova_sonic_provider.py

# Voice protocol invariants the migrated tests MUST keep asserting
# (spec §5 acceptance criteria; behavior ported in TASK-1807):
#   - event frame order: sessionStart → promptStart → contentStart(AUDIO) → audioInput*
#   - audioInput content is base64 TEXT; audioOutput content is base64-decoded to bytes
#   - 8-minute limit yields metadata {"reconnect_required": True}
#   - LiveVoiceResponse shape (clients/live.py:156)

# Regression gate (run UNMODIFIED):
#   pytest packages/ai-parrot/tests/clients/test_bedrock_advanced.py \
#          .../test_bedrock_converse.py .../test_bedrock_errors.py \
#          .../test_bedrock_integration.py .../test_factory_bedrock.py -v
```

### Does NOT Exist
- ~~`parrot.clients.nova_sonic`~~ / ~~`NovaSonicClient`~~ — deleted in
  TASK-1811; tests asserting its absence are part of THIS task.
- ~~`VoiceProvider.NOVA_SONIC`~~ — renamed to `NOVA` in TASK-1811.
- ~~provider string `'nova_sonic'`~~ — must not appear anywhere post-migration.

---

## Implementation Notes

### Key Constraints
- Migrations preserve assertions — do not weaken protocol tests to make them
  pass; if one fails, the port (TASK-1807) has a bug: report it.
- The live test needs real AWS credentials — mark
  `@pytest.mark.integration` and `skipif` on missing env, consistent with
  `tests/integration/` conventions in this repo.
- Record the full pytest output as evidence (CLAUDE.md: save to `artifacts/logs/`).

### References in Codebase
- `sdd/specs/novaclient-amazon-aws.spec.md` §4 — the target coverage table
- `packages/ai-parrot/tests/clients/test_bedrock_*.py` — regression gate

---

## Acceptance Criteria

- [ ] All migrated suites pass: `pytest packages/ai-parrot/tests/clients/test_nova*.py packages/ai-parrot/tests/bots/test_voicebot_nova_wiring.py packages/ai-parrot/tests/models/ packages/ai-parrot-integrations/tests/voice/ -v`
- [ ] Bedrock regression gate passes UNMODIFIED: `pytest packages/ai-parrot/tests/clients/test_bedrock_*.py -v`
- [ ] `grep -rn "nova_sonic" packages/ --include="*.py"` → empty
- [ ] Spec §4 unit-test table fully covered (map each row to a test function in the Completion Note)
- [ ] `test_nova_ask_live` exists, integration-marked, skipped without credentials
- [ ] Evidence saved to `artifacts/logs/feat-315-tests.log`

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova.py (excerpt — ported protocol test)
async def test_stream_voice_event_protocol(fake_bidi_stream):
    """Frames: sessionStart → promptStart → contentStart(AUDIO); audio base64."""
    ...

def test_no_nova_sonic_module():
    import importlib, pytest
    with pytest.raises(ImportError):
        importlib.import_module("parrot.clients.nova_sonic")


# packages/ai-parrot-integrations/tests/voice/test_nova_provider.py (excerpt)
def test_voice_provider_renamed():
    from parrot.voice.models import VoiceProvider
    assert VoiceProvider.NOVA.value == "nova"
    assert not any(m.value == "nova_sonic" for m in VoiceProvider)
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§4, §5)
2. **Check dependencies** — TASK-1811 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read every migration-source test file in full
4. **Update status** in `sdd/tasks/index/novaclient-amazon-aws.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
