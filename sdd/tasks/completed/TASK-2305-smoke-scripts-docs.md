# TASK-2305: Live smoke scripts + hierarchy documentation

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2303, TASK-2304
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 / Goal G6 (live validation) and the docs acceptance
criterion. Offline suites prove payload shapes; the smoke scripts prove real
endpoints accept them. Credential-gated: each script skips cleanly when its
key is absent, so CI and keyless machines are unaffected. Endpoint list is an
open §8 item — propose the candidate set below and confirm with the user
before finalizing (drop endpoints the user has no credentials for).

---

## Scope

- Create `examples/clients/smoke/` with one script per endpoint (candidate set
  — CONFIRM with user at task start): `smoke_mantle.py`, `smoke_nvidia.py`,
  `smoke_moonshot.py`, `smoke_openrouter.py`, `smoke_groq.py`,
  `smoke_vllm_local.py`, `smoke_zai.py`, plus `smoke_openai.py` as the
  positive control.
- Each script: constructs the client via `LLMFactory.create("provider:model")`,
  runs (1) plain `ask()`, (2) `ask()` with one `@tool` (verifies tool wire
  format end-to-end), (3) `invoke()` (verifies the lightweight-model chain —
  the original 404 repro path), and prints a compact PASS/FAIL summary.
  Skip-if-no-key: check the provider's env var(s) first and exit 0 with
  `SKIPPED (no <ENV_VAR>)`.
- Shared runner helper inside the smoke package (arg parsing, summary
  formatting) — keep scripts thin.
- Write `docs/clients/openai-compatible.md`: the hierarchy diagram (from spec
  §2), what belongs in the base vs a provider subclass, the
  "add a new OpenAI-compatible provider" recipe (subclass, attrs, env vars,
  optional `_chat_completion` override), the funnel contract, and the
  no-`gpt-*`-defaults rule.
- Run whichever smoke scripts the available credentials allow; record results
  in the Completion Note (env per memory: data-querying against real services
  may need `ENV=prod`-style env selection — follow existing examples/
  conventions, see `examples/agents/aws/` scripts for the house style).

**NOT in scope**: CI wiring for live tests (manual by design); fixing endpoint
failures the smokes reveal (file findings; reopen the relevant task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/smoke/*.py` | CREATE | per-endpoint credential-gated smoke scripts + shared helper |
| `docs/clients/openai-compatible.md` | CREATE | hierarchy + add-a-provider recipe |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.factory import LLMFactory   # factory.py:161; create() :193; "provider:model" split :187
from parrot.tools import tool                    # @tool decorator (CLAUDE.md tool pattern)
```

### Existing Signatures to Use
```python
# factory.py SUPPORTED_CLIENTS keys (verified :107-149) — use these provider strings:
#   "openai", "openrouter", "nvidia", "moonshot"/"kimi", "local"/"localllm"/"ollama",
#   "vllm", "groq", "zai"/"z.ai", "bedrock-mantle"/"mantle"
# Env vars per provider (verified in each client __init__):
#   OPENAI_API_KEY (gpt.py:101), OPENROUTER_API_KEY (openrouter.py:71),
#   NVIDIA_API_KEY (nvidia.py:281), MOONSHOT_API_KEY (moonshot.py:141),
#   LOCAL_LLM_BASE_URL/LOCAL_LLM_API_KEY (localllm.py:74-78),
#   VLLM_BASE_URL/VLLM_API_KEY via os.getenv (vllm.py:88-96),
#   GROQ key via GroqClient __init__ (groq.py:65 — verify exact env var name in the body),
#   ZAI_API_KEY (zai.py:40), BEDROCK_MANTLE_API_KEY / AWS_NOVA_API_KEY +
#   BEDROCK_AWS_REGION / AWS_REGION_NAME (mantle.py:91-92)
# House style for runnable example agents: examples/agents/aws/*.py (FEAT-437)
# Doc house style: docs/clients/bedrock-mantle.md exists — follow its structure
```

### Does NOT Exist
- ~~`examples/clients/smoke/`~~ — this task creates it; check whether `examples/clients/` exists first and follow whatever convention is closest (`examples/agents/aws/` is the verified reference).
- ~~pytest markers for live tests~~ — smokes are plain scripts, not pytest (deliberate: no accidental CI network).
- ~~a `GROQ_API_KEY` guarantee~~ — the exact env var name in groq.py:65-78 body was not captured in the spec contract; VERIFY it before writing the gate.

---

## Implementation Notes

### Pattern to Follow
```python
# skip-gate pattern:
import os, sys
KEY = os.getenv("NVIDIA_API_KEY")
if not KEY:
    print("SKIPPED (no NVIDIA_API_KEY)")
    sys.exit(0)
```

### Key Constraints
- Scripts must be safe to run repeatedly (no state, tiny max_tokens, cheap
  models per provider).
- `asyncio.run(main())` entrypoints; async-first inside.
- The `invoke()` leg is mandatory in every script — it is the original
  DeepSeek-404 repro path.

### References in Codebase
- `examples/agents/aws/agent_claude_haiku45.py` — runnable-example house style.
- `sdd/specs/openai-compatible-clients.spec.md` §8 (endpoint list open question).

---

## Acceptance Criteria

- [ ] Endpoint list confirmed with user; scripts exist for the confirmed set
- [ ] Every script skip-gates on missing credentials (exit 0, clear message)
- [ ] Each script exercises ask / ask+tool / invoke and prints PASS/FAIL
- [ ] `docs/clients/openai-compatible.md` written (hierarchy, recipe, funnel contract, no-defaults rule)
- [ ] Smokes run against available credentials; results recorded in Completion Note
- [ ] `ruff check` clean on new files

---

## Test Specification

Live-by-design — no pytest additions. The Completion Note MUST include a
results table: endpoint | model | ask | ask+tool | invoke | notes.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2303 and TASK-2304 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2305-smoke-scripts-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**: (include the live-results table)

**Deviations from spec**: none
