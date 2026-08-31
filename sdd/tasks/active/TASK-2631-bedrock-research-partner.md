# TASK-2631: BedrockResearchPartner — gpt-5.6-sol and nova-2-lite on one implementation

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2629, TASK-2630, **FEAT-484** (`readonly-repo-toolkit`)
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 2** — the actual second researcher.

The key insight this task depends on: `BedrockMantleClient` (`nova/mantle.py:32`)
extends `OpenAIBaseClient` (`openai_base.py:53`), and `NovaClient`
(`nova/client.py:31`) extends `BedrockConverseBase` (`bedrock.py:114`) — **both are
`AbstractClient` subclasses** sharing one tool registry (`base.py:355`) and one
execution path (`_execute_tool`, `base.py:1454` / `openai_base.py:421`).

So a single implementation serves both transports through one call:

```python
client.ask(prompt, use_tools=True, structured_output=ResearchFindings, ...)
```

**No per-transport tool adapter is needed, and none should be written.**

⚠️ **Blocked on FEAT-484.** This task registers `ReadOnlyRepoToolkit`. Do not start
until `sdd/specs/readonly-repo-toolkit.spec.md` has merged.

---

## Scope

- Implement `BedrockResearchPartner(AbstractResearchPartner)` in the module created
  by TASK-2629.
- Resolve the backend and build the matching client:
  - `gpt` → `BedrockMantleClient`, model from `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL`
    (default `gpt-5.6-sol`), reasoning via the OpenAI-shaped effort knob
    (`DEV_FLOW_RESEARCH_PARTNER_EFFORT`)
  - `nova` → `NovaClient`, model from `DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL`
    (default `us.amazon.nova-2-lite-v1:0`), reasoning via `thinking_budget`
- Register FEAT-484's `ReadOnlyRepoToolkit` on the client, bound to the run's `cwd`,
  with `enable_web_search` from `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` (default true).
- Issue exactly one `ask(...)` with `use_tools=True`,
  `structured_output=ResearchFindings`, `max_tokens` from config, and the
  backend-appropriate reasoning knob.
- Build the **neutral prompt**: the brief, the repo root, and the research question —
  and **never** the primary seat's framing, hypotheses, or preferred conclusion.
- Register with `ResearchPartnerFactory` under both `"gpt"` and `"nova"`.
- Unit tests including the neutrality guard and the shared-call-shape test.

**NOT in scope**: the coordinator's timeout/degradation/`.research.md` handling
(TASK-2632) — this class may raise; the coordinator is the soft-degradation
boundary. No node wiring. No `OPENAI_API_KEY` and no Codex CLI path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py` | MODIFY | Add `BedrockResearchPartner` + registrations |
| `packages/ai-parrot/tests/flows/dev_flow/test_research_partner.py` | MODIFY | Backend/transport/prompt tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.nova.client import NovaClient           # nova/client.py:31
from parrot.clients.nova.mantle import BedrockMantleClient  # nova/mantle.py:32
from parrot.models.openai import OpenAIModel                # models/openai.py:22 (GPT5_6_SOL)
from parrot import conf
# From FEAT-484 — CONFIRM the final import path before use:
from parrot.tools.repo import ReadOnlyRepoToolkit
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):    # line 31
    _default_model: str = "nova-2-lite"                              # line 65

# packages/ai-parrot/src/parrot/clients/bedrock.py
class BedrockConverseBase(AbstractClient):                           # line 114
    async def ask(..., thinking_budget: Optional[int] = None, ...)   # line 699 / 715
    # Multi-round Converse toolUse loop: :930-990
    # reasoningContent signatures preserved across rounds: :986-988
    # FEAT-404 ClientRoundEvent per round: :971-981

# packages/ai-parrot/src/parrot/clients/nova/mantle.py
class BedrockMantleClient(OpenAIBaseClient):                         # line 32
    # Endpoint: explicit base_url -> BEDROCK_MANTLE_BASE_URL ->
    #   https://bedrock-mantle.{region}.api.aws/v1                   # :40-44
    # Auth: the SAME AWS_NOVA_API_KEY bearer token the Converse seats
    #   use — NOT a duplicate secret (conf.py:1030-1034).

# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                              # line 53
    async def ask(..., structured_output=None, use_tools=None, ...)  # line 507
    tool_result = await self._execute_tool(tool_name, tool_args)     # line 421
    if self.tools:                                                   # line 960

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    self.tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}  # line 355
    async def _execute_tool(...)                                     # line 1454

# packages/ai-parrot/src/parrot/clients/gpt.py
STRUCTURED_OUTPUT_COMPATIBLE_MODELS = { ... OpenAIModel.GPT5_6_SOL.value ... }  # line 52-60
#   -> structured_output=ResearchFindings is supported on gpt-5.6-sol.

# From TASK-2629 (same module):
class AbstractResearchPartner(ABC):
    partner_name: str
    advisory: bool = True
    async def research(*, brief, question, cwd, run_id, node_id, session_host=None) -> ResearchFindings
```

### Does NOT Exist

- ~~a per-transport tool adapter~~ — **not needed and must not be written.** Both
  clients share `AbstractClient.tools` + `_execute_tool`.
- ~~`gpt-5.5-sol`~~ — the string is **`gpt-5.6-sol`** (`models/openai.py:22`).
- ~~`OPENAI_API_KEY` usage~~ — the mantle path uses the existing `AWS_NOVA_API_KEY`.
  Introducing an OpenAI key is an explicit spec violation.
- ~~a Codex CLI path for the GPT partner~~ — explicitly rejected; `catalog.py:149`'s
  `codex` backend is NOT this seat.
- ~~`thinking_budget` on the mantle path~~ — Converse-only. Passing it to
  `BedrockMantleClient` is wrong; use the OpenAI-shaped effort knob.
- ~~`LLMCodeDispatcher` / `NovaCodeDispatcher`~~ — do NOT route through these.
  They drive `client._chat_completion(...)` in their own loop and bypass `ask()`
  (see FEAT-405 spec §1). This task uses `ask()` for both backends.
- ~~an Anthropic partner model~~ — rejected by TASK-2629's family guard.

---

## Implementation Notes

### Pattern to Follow

```python
# One implementation, two client constructions, ONE call shape:
client = self._build_client()          # BedrockMantleClient | NovaClient
for tool in ReadOnlyRepoToolkit(repo_root=Path(cwd), ...).get_tools():
    ...  # register on client per AbstractClient's tool registry
ai_message = await client.ask(
    prompt,
    use_tools=True,
    structured_output=ResearchFindings,
    max_tokens=...,
    **self._reasoning_kwargs(),        # thinking_budget=N | effort="high"
)
```

### Key Constraints

- **Neutral prompt is a correctness property, not a style note.** `CLAUDE.md`:
  "Never feed the reviewer your reasoning, justification, or preferred conclusion.
  Supplying your conclusions produces ratification, not review." The same applies
  here — a partner primed with Claude's framing produces confirmation, which is the
  exact failure this feature exists to prevent. There is a test for it.
- Read-only: register FEAT-484's toolkit only; never add a write tool.
- Async throughout; Pydantic contracts; `self.logger`.
- This class MAY raise — TASK-2632's coordinator owns degradation.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py:240` —
  `NovaAdversarialReviewDispatcher`: the read-only-by-construction Bedrock seat.
- `packages/ai-parrot/src/parrot/clients/nova/mantle.py:32-60` — mantle construction.

---

## Acceptance Criteria

- [ ] `gpt` backend builds `BedrockMantleClient`; `nova` builds `NovaClient`
- [ ] Both call `ask(use_tools=True, structured_output=ResearchFindings)` — one shared shape
- [ ] The FEAT-484 toolkit is registered on both clients; no write tool is registered
- [ ] Reasoning knob is backend-appropriate: `thinking_budget` Converse-only, effort mantle-only
- [ ] Prompt contains the brief, repo root and question — and **no** primary-seat reasoning
- [ ] No `OPENAI_API_KEY` is read anywhere; no Codex CLI invoked
- [ ] Returns a validated `ResearchFindings`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_research_partner.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py`

---

## Test Specification

```python
class TestBedrockResearchPartner:
    async def test_gpt_partner_uses_mantle_client(self):
        """Default backend builds BedrockMantleClient; no OPENAI_API_KEY read."""

    async def test_nova_partner_uses_converse_client(self):
        """nova backend builds NovaClient and passes thinking_budget."""

    async def test_both_backends_share_one_call_shape(self):
        """Both invoke ask(use_tools=True, structured_output=ResearchFindings)
        with the toolkit registered — no per-transport branching in the call."""

    async def test_reasoning_knob_is_backend_appropriate(self):
        """thinking_budget only on Converse; effort only on mantle."""

    async def test_prompt_excludes_primary_reasoning(self):
        """NEUTRALITY GUARD: prompt carries brief/root/question and none of the
        primary seat's framing, hypotheses, or preferred conclusion."""

    async def test_no_write_tool_registered(self):
        """Registered toolkit exposes no write-shaped tool."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Overview two-backend table, §3 Module 2).
2. **Check dependencies** — TASK-2629 and TASK-2630 must be in `sdd/tasks/completed/`,
   **and FEAT-484 must be merged**. If FEAT-484 has not merged, STOP and report.
3. **Verify the Codebase Contract** — confirm `ReadOnlyRepoToolkit`'s final import
   path and constructor signature from FEAT-484's merged code, not from this file.
4. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
5. **Implement** following the scope and contract.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2631-bedrock-research-partner.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
