# TASK-2303: Phase 2 — rebase GroqClient onto OpenAIBaseClient (native AsyncGroq retained)

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2301
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 / Goal G4. `GroqClient` (1,424 lines) reimplements the OpenAI
wire protocol on `AbstractClient` because extending `OpenAIClient` was never
safe. Rebase it onto `OpenAIBaseClient`, deleting the duplicated
shaping/tool-loop/structured-output code, while **keeping the native
`groq.AsyncGroq` SDK** behind `get_client()` (spec-time decision — the
`AsyncOpenAI` swap was explicitly rejected). `AsyncGroq` mirrors the OpenAI
SDK's `chat.completions.create` surface, so the base funnel should drive it
directly. **Strict payload parity gates this task: any divergence found blocks
the migration — never silently normalize.**

---

## Scope

- `class GroqClient(AbstractClient)` → `class GroqClient(OpenAIBaseClient)`
  (groq.py:49).
- Keep: `client_type="groq"` (:59 — drives `ToolFormat.GROQ` via the
  base.py:1385 map; do NOT declare `tool_format = ToolFormat.OPENAI` — the
  inherited base attr must be OVERRIDDEN back: declare
  `tool_format: ToolFormat = ToolFormat.GROQ` explicitly on GroqClient,
  otherwise the inherited OPENAI value from `OpenAIBaseClient` would win over
  the client_type map and enable strict tools — THIS IS THE CENTRAL GOTCHA),
  model attrs (:61–63 incl. `_lightweight_model="kimi-k2-instruct"`),
  `__init__` (:65), `get_client() -> AsyncGroq` (:79; NOTE: base_url stored
  :72 but NOT passed to the SDK :88 — preserve this quirk verbatim),
  `_fix_schema_for_groq` (:90) if payload parity requires it.
- Delete in favor of base implementations, gated per-deletion by parity tests:
  `_prepare_groq_tools` (:195; callers :317/:743/:851),
  `_prepare_structured_output_format` (:227), the reimplemented `ask` (:270),
  `ask_stream` (:678), `resume` (:819), `batch_ask` (:958), `invoke` (:1293).
  Keep Groq-specific text helpers (`summarize_text` :962 etc.) only if their
  behavior differs from what base `ask()` provides — read before deciding.
- Extend TASK-2301's suites: add `GroqClient` to `WIRE_SUBCLASSES`;
  payload-parity fixture captures `AsyncGroq.chat.completions.create` kwargs;
  assert `ToolFormat.GROQ` wrapper WITHOUT `"strict"`; assert kimi lightweight
  model reaches invoke.
- Keep existing `packages/ai-parrot/tests/test_groq_client.py` (78 L) and
  `tests/unit/test_groq_invoke.py` green (update only where they pinned
  internals that no longer exist — name each in the Completion Note).

**NOT in scope**: swapping to `AsyncOpenAI` (rejected); ZaiClient (TASK-2304);
touching `tool_format` resolution in base.py.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY | rebase + delete duplicated wire code + explicit `ToolFormat.GROQ` |
| `tests/clients/test_openai_compatible_defaults.py` | MODIFY | add GroqClient to roster |
| `tests/clients/test_openai_base_parity.py` | MODIFY | Groq payload parity (AsyncGroq mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.groq import GroqClient               # groq.py:49
from parrot.clients.openai_base import OpenAIBaseClient  # after TASK-2296
from parrot.tools.manager import ToolFormat              # tools/manager.py:47
from groq import AsyncGroq                               # lazy import pattern groq.py:81
```

### Existing Signatures to Use
```python
# clients/groq.py (verified @ dev ab84ffff0, 1424 L):
class GroqClient(AbstractClient):                              # :49
    client_type: str = "groq"                                  # :59
    model: str = GroqModel.LLAMA_3_3_70B_VERSATILE             # :61
    _default_model: str = 'openai/gpt-oss-120b'                # :62  (NOT a gpt-* leak: no dash-digit; leak predicate is r"^gpt-")
    _lightweight_model: str = "kimi-k2-instruct"               # :63
    def __init__(self, api_key=None, base_url="https://api.groq.com/openai/v1", **kwargs)  # :65
    async def get_client(self) -> "AsyncGroq"                  # :79  (AsyncGroq(api_key=self.api_key) :88 — NO base_url passed)
    def _fix_schema_for_groq(self, schema: dict) -> dict       # :90
    def _prepare_groq_tools(self) -> List[dict]                # :195 → DELETE (callers :317/:743/:851)
    def _prepare_structured_output_format(self, structured_output) -> dict  # :227 → DELETE
    async def ask(...)                                         # :270 → DELETE (base provides)
    async def ask_stream(...)                                  # :678 → DELETE
    async def resume(...)                                      # :819 → DELETE
    async def invoke(...)                                      # :1293 → DELETE (only its invoke uses base _prepare_tools today :1344)

# Strict-tools guard (already correct, relies on tool_format):
# base.py:1411  if provider_format in (ToolFormat.OPENAI, ToolFormat.GROQ): → function wrapper
# base.py:1420  strict applied ONLY for ToolFormat.OPENAI ("Groq rejects it")
# base.py:1378  explicit tool_format attr WINS over client_type map ← why GroqClient MUST declare GROQ explicitly post-rebase
```

### Does NOT Exist
- ~~`AsyncGroq(base_url=...)` in current code~~ — base_url is NOT passed to the SDK (groq.py:88); do not "fix" this.
- ~~`ToolFormat.GROQ` declaration on GroqClient today~~ — it currently falls through the client_type map; post-rebase the explicit declaration becomes REQUIRED (inherited OPENAI would win otherwise).
- ~~`use_code_interpreter` support in the base~~ — Groq's `ask` has this kwarg (:270); if callers rely on it, keep as a thin Groq `ask` override delegating to `super().ask()`; do not add it to the base.
- ~~an `AsyncGroq.chat.completions.parse` guarantee~~ — verify before letting the base funnel call `.parse`; if unsupported, override `_chat_completion` to force `.create` (same pattern as NvidiaClient nvidia.py:407).

---

## Implementation Notes

### Pattern to Follow
- Migration order: (1) rebase + explicit `tool_format=GROQ` + keep ALL
  overrides → suite green; (2) delete overrides one at a time, parity test
  after each; (3) roster addition last.
- Parity divergence protocol (spec §2): a payload difference the tests catch
  BLOCKS the deletion — keep the override, document in Completion Note,
  surface to the user. Never adjust the expected payload to match the base.

### Key Constraints
- `_default_model 'openai/gpt-oss-120b'` and `_lightweight_model` are Groq
  catalogue ids — keep verbatim.
- Full `pytest` run; zero network.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/nvidia.py:407` — `_chat_completion` create-not-parse override pattern.
- `sdd/specs/openai-compatible-clients.spec.md` §2 Phase-2, §7 Risks (Groq base_url quirk).

---

## Acceptance Criteria

- [ ] `GroqClient(OpenAIBaseClient)` with explicit `tool_format = ToolFormat.GROQ`
- [ ] `get_client()` still returns `AsyncGroq` (test asserts NOT `AsyncOpenAI`)
- [ ] Duplicated wire code deleted; line count of groq.py reduced substantially
- [ ] Groq payloads: function wrapper, NO `"strict"` key (test)
- [ ] GroqClient added to `WIRE_SUBCLASSES` roster; no-leak + funnel tests green
- [ ] `pytest packages/ai-parrot/tests/test_groq_client.py tests/unit/test_groq_invoke.py tests/clients/test_openai_compatible_defaults.py tests/clients/test_openai_base_parity.py -v` green
- [ ] Full `pytest` run green; `ruff check` clean

---

## Test Specification

```python
# tests/clients/test_openai_base_parity.py (additions)
async def test_groq_payload_no_strict(mock_asyncgroq):
    """Tools payload uses function wrapper without strict=True."""
    ...

async def test_groq_keeps_native_sdk():
    from groq import AsyncGroq
    c = GroqClient(api_key="k")
    assert isinstance(await c.get_client(), AsyncGroq)

def test_groq_tool_format_explicit():
    from parrot.tools.manager import ToolFormat
    assert GroqClient.tool_format is ToolFormat.GROQ
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2301 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2303-groq-rebase.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
