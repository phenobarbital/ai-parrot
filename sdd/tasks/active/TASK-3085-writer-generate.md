# TASK-3085: TargetedWriterToolkit — constructor no-fallback guard and writer_generate via AbstractClient

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3083, TASK-3084
**Assigned-to**: unassigned

---

## Context

Spec §2 "Delegation Packet and Writer Contract" (`writer_generate` items
1–7), "Client Configuration and Lifecycle", §3 Module M5 (`writer.py`),
AC7, AC8 (client half), AC9 (generation half), AC11. The writer calls a
configured `AbstractClient` (initially Bedrock + Qwen3-Coder) with **no
tools, no history, no research**, asks for a unified diff, validates it
with TASK-3084, and stores a manifest. It never modifies target files.
`writer_apply` is TASK-3086.

**Decisions fixed here:**

1. Constructor signature:
   `TargetedWriterToolkit(*, repo_root, llm_client: AbstractClient | None = None, limits: WriterLimits | None = None, expected_model_ids: Sequence[str] = (), **policy/toolkit kwargs)`.
   `llm_dependent_tools = frozenset({"writer_generate"})` so a config
   without `llm:` exposes only `writer_apply` (`toolkit_server.py:104-106`).
2. **No silent model switching**: at construction, if `llm_client` is not
   `None` and `getattr(llm_client, "_fallback_model", None)` is truthy →
   `ValueError("writer client permits fallback model ...; set llm_kwargs.fallback_model: null")`.
   Verified mechanics: `AbstractClient.__init__` only creates the
   instance attribute when `fallback_model` is passed (`base.py:426-428`);
   `BedrockConverseBase.__init__` does `kwargs.setdefault("fallback_model", self._fallback_model)`
   (`bedrock.py:282`) so an explicit `fallback_model=None` survives and
   the class default `"claude-haiku-4-5"` (`bedrock.py:1669`) is NOT used.
3. Model identity check after each call: `used_fallback = bool(ai.metadata.get("used_fallback_model"))`
   (`bedrock.py:1063` sets it) → reject `model_substituted`. `actual_model = ai.model`
   (`responses.py:111`). `configured_model = str(getattr(llm_client, "model", ""))`.
   If `expected_model_ids` is non-empty, `actual_model` must be in
   `{configured_model, *expected_model_ids}`; if empty, only the fallback
   flag is checked (Bedrock reports the translated id
   `qwen.qwen3-coder-480b-a35b-v1:0` for alias `qwen3-coder-480b-a35b`,
   `amazon/models.py:130`, so operators list it in config).
4. The call: `await client.ask(prompt=user_text, system_prompt=SYSTEM_PROMPT, max_tokens=limits.max_output_tokens, temperature=0.0, use_tools=False, history=None)`
   — keyword arguments only, all present on both the abstract signature
   (`base.py:1662-1676`) and Bedrock's (`bedrock.py:723-744`). Never pass
   `tools`, `files`, `structured_output`, `deep_research`, `background`,
   `lazy_loading`, `thinking_budget`.
5. Usage: `ai.usage.prompt_tokens/completion_tokens/total_tokens`
   (`basic.py:76-82`). When all three are `0`, record `None` for each
   ("unknown, not zero", spec Measurement Protocol).
6. Client lifecycle: each `writer_generate` runs
   `async with self._client_lock:` (an `asyncio.Lock`; shared clients are
   serialized) and, if the client was constructed by this toolkit from
   MCP config, it is entered once via `await client.__aenter__()` in
   `_open()` (`auto_open = True`, FEAT-391 hooks `toolkit.py:390-436`) and
   closed in `_close()` via `await client.__aexit__(None, None, None)`
   + `await client.close()` (`base.py:1140`). MCP shutdown is not assumed
   to close anything.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/writer.py`:
  - `SYSTEM_PROMPT` constant: instructs the model that it is
    implementing already-decided code; must output ONLY a unified diff
    (`--- a/<path>` / `+++ b/<path>`, `--- /dev/null` for new files), no
    prose, no fences, no renames/deletes/mode changes, only the listed
    target paths, use the provided implementation blocks verbatim where
    they are complete file contents, never invent APIs, never touch other
    files, never include commands.
  - `def build_prompt(contract: ValidatedContract) -> str` using
    `render_prompt_sections` (TASK-3083); the prompt contains ONLY packet
    fields, reference slices and implementation blocks (item 2). Assert
    `len(prompt.encode()) <= limits.max_context_bytes` else
    `context_budget_exceeded` (defensive; contracts already checks).
  - `def build_repair_prompt(contract, previous_patch: str, error: PatchError) -> str`:
    same approved context + the bounded diagnostic (`error.code`,
    `details`, first 2,000 bytes of the previous patch around the failing
    hunk) — item 6.
  - `class TargetedWriterToolkit(OptimizationToolkitBase)`:
    `arg_models = {"writer_generate": WriterGenerateArgs, "writer_apply": WriterApplyArgs}`;
    `llm_dependent_tools = frozenset({"writer_generate"})`;
    `confirming_tools = frozenset({"writer_apply"})` (apply mutates the
    worktree — TASK-3086 implements it; declare the set now so the MCP
    schema is stable); `auto_open = True`.
    - `_open`/`_close` per Decision 6; `_owns_client: bool` is True when
      the client came via the `llm_client` kwarg from MCP config (that is
      the only path; a caller passing a shared client sets
      `owns_client=False` explicitly via kwarg).
    - `async writer_generate(self, task_path: str) -> OperationResult` (`@tool_schema(WriterGenerateArgs)`):
      1. `WriterGenerateArgs(task_path=task_path)`; if `self._client is None` → `error/no_client`.
      2. `contract = await validate_contract(self.policy, task_path, limits_override=self._limits)`;
         `ContractError` → `OperationResult(status="error", error=OperationError(code=exc.code, details=exc.details))`
         — **no model call happened** (AC7); `steps` empty.
      3. `async with self._client_lock, asyncio.timeout(limits.generation_deadline_seconds):`
         attempt loop: `attempts = 0`; call model; `patch_text =
         ai.response or (ai.output if isinstance(ai.output, str) else "")`;
         record usage (sum across attempts) and identity checks
         (Decision 3) — a substituted model aborts immediately with
         `model_substituted`, no repair.
         `normalize_patch` → `parse_patch(max_bytes=limits.max_patch_bytes)`
         → `check_scope(allowed = {t.path: t.action for t in packet.targets})`
         → `apply_in_memory(sources = current bytes for modify targets read
         via `read_line_range`? NO — read raw bytes with a bounded
         `open(...).read(size+1)` guarded by the already-verified size from
         `stat_regular`; `None` for creates)`.
         On `PatchError` with `attempts < limits.max_repairs + 1` → one
         repair call with `build_repair_prompt`; else → `error/<code>`
         with `details` and `repairs=attempts-1`.
         Any tool-call/ structured artefact in the response
         (`ai.output` not a `str`, or `ai.metadata.get("tool_calls")`) →
         `unexpected_tool_call`, no repair.
      4. `TimeoutError` (deadline) → `error/deadline_exceeded`; on
         `asyncio.CancelledError` re-raise after ensuring no artifact dir
         was published (store writes are atomic, TASK-3084).
      5. Build `PatchManifest` (`validation_state="validated"`,
         `before_hashes` = `targets_state`, `after_hashes` = sha256 of the
         in-memory results, `allowed_paths`, `configured_model`,
         `actual_model`, `used_fallback=False`, `usage`, `repairs`,
         `elapsed_ms`, `created_at`); `store.write_generation(...)`.
      6. Return `OperationResult(status="ok", operation="writer_generate", data={"artifact_id", "patch_path": "artifacts/tool-optimizations/<id>/patch.diff", "patch_sha256", "targets": [...], "usage", "repairs", "configured_model", "actual_model"})`.
         The thinking model then reads `patch_path` with the bounded
         reader (item 7) — the toolkit never returns the full patch inline.
    - `async writer_apply(...)`: stub returning `error/not_implemented`
      (TASK-3086 replaces it) — keep the signature and `@tool_schema(WriterApplyArgs)`.
  - Secrets: never log `llm_client` config; `self.logger.info` only
    artifact id, model ids, usage, elapsed.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py`
  with a **recording fake client** (`FakeClient(AbstractClient)` is
  heavy to subclass — instead build a duck-typed fake exposing `model`,
  `_fallback_model`, `async ask(**kw)`, `__aenter__/__aexit__`, `close`,
  and recording every kwarg; the writer only uses these names, and a
  test asserts the toolkit never touches any other attribute via a
  `__getattr__` that fails).

**NOT in scope**: applying patches to the worktree (TASK-3086), MCP
`llm_kwargs` (TASK-3087), benchmarks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/writer.py` | CREATE | Toolkit, prompts, generate |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py` | CREATE | Fake-client tests |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY (only if registry check demands) | `TOOL_REGISTRY` entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.base import OptimizationToolkitBase
from parrot_tools.tool_optimizations.models import OperationResult, OperationError, PatchManifest, WriterLimits, WriterGenerateArgs, WriterApplyArgs
from parrot_tools.tool_optimizations.contracts import ValidatedContract, ContractError, validate_contract, render_prompt_sections   # TASK-3083
from parrot_tools.tool_optimizations.patches import ArtifactStore, PatchError, normalize_patch, parse_patch, check_scope, apply_in_memory   # TASK-3084
from parrot_tools.tool_optimizations.reader import stat_regular                                          # TASK-3082
from parrot.tools.decorators import tool_schema                                                          # decorators.py:39
# TYPE_CHECKING only (keep provider satellites lazy — spec §7):
from parrot.clients.base import AbstractClient                                                           # base.py — class defined there; import under TYPE_CHECKING
from parrot.models.responses import AIMessage                                                            # responses.py (fields verified below)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    max_retries: int = 1                                  # :134 (class), ctor param max_retries: int = 3 at :188 → self.max_retries :198
    _fallback_model: Optional[str] = None                 # :298
    # :426-428  if "fallback_model" in kwargs: self._fallback_model = kwargs.pop("fallback_model")
    def _should_use_fallback(self, model, error) -> bool  # :1002  False when not self._fallback_model
    async def __aenter__(self)                            # :1021  → creates aiohttp session (use_session) + _ensure_client()
    async def __aexit__(self, exc_type, exc_val, exc_tb)  # :1033
    async def close(self) -> None                         # :1140  → close_all()
    async def ask(self, prompt: str, model: str, max_tokens=None, temperature: float = 0.7, files=None, system_prompt=None,
                  history=None, structured_output=None, tools=None, use_tools=None, deep_research=False, background=False, lazy_loading=False)  # :1662-1676 (abstract)
    def __repr__(self): ... self.model ...                # :1165 — `model` attribute exists on instances

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py
class BedrockConverseBase:
    # :282  kwargs.setdefault("fallback_model", self._fallback_model); super().__init__(**kwargs)
    async def ask(self, prompt, model=None, max_tokens=None, temperature=None, files=None, system_prompt=None, history=None,
                  structured_output=None, tools=None, use_tools=None, deep_research=False, background=False, lazy_loading=False,
                  thinking_budget=None, output_schema=None, prompt_cache=False, guardrail_id=None, guardrail_version=None) -> AIMessage  # :723-744
    # :1054 model=payload["modelId"] if used_fallback else resolved_model ; :1062-1065 metadata["used_fallback_model"]=True, metadata["fallback_model"]=...
class BedrockConverseClient(BedrockConverseBase):        # :1650
    client_type = "bedrock-converse"; provider_keys = ("bedrock-converse",)   # :1662, :1666
    _fallback_model: str = "claude-haiku-4-5"            # :1669  ← the default the writer must neutralise
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/models.py:130  "qwen3-coder-480b-a35b": "qwen.qwen3-coder-480b-a35b-v1:0"

# packages/ai-parrot/src/parrot/models/responses.py — AIMessage
output: Any            # :79
response: Optional[str]# :82
model: str             # :111
provider: str          # :114
usage: CompletionUsage # :118
metadata: Dict[str, Any]  # :212
# packages/ai-parrot/src/parrot/models/basic.py — CompletionUsage.prompt_tokens :76, completion_tokens :79, total_tokens :82 (default 0)

# packages/ai-parrot/src/parrot/tools/toolkit.py
llm_dependent_tools: frozenset = frozenset()   # :294  — toolkit_server.py:104-106 drops these names when no `llm:` configured
auto_open: bool = False                        # :319 ; _open :390 ; _close :~407 ; _ensure_open :419 (called from ToolkitTool._execute :171-172)
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py:108-110  kwargs["llm_client"] = llm_client  → constructor kwarg name is exactly `llm_client`
```

### Does NOT Exist
- ~~`client.ask(..., tools=[])` meaning "no tools"~~ — pass `use_tools=False` and omit `tools`; some clients treat `tools=[]` as "prepare tools".
- ~~`AIMessage.text`~~ / ~~`.content`~~ — use `.response` (str) then `.output`.
- ~~`CompletionUsage.input_tokens` attribute~~ — that is only a validation alias; read `prompt_tokens`.
- ~~`LLMFactory` inside writer.py~~ — the client is injected; the factory is only used by MCP config (TASK-3087).
- ~~Automatic retry on `model_substituted` / `unexpected_tool_call` / `ContractError`~~ — none; only one patch repair.
- ~~`client.fallback_model` public attribute~~ — the attribute is `_fallback_model`.
- ~~Passing `model=` to `ask`~~ — use the client's configured model; a per-call override would be a model-settable substitution channel.
- ~~`writer_generate` returning patch text~~ — returns a path + hash only.

---

## Implementation Notes

### Pattern to Follow
```python
class TargetedWriterToolkit(OptimizationToolkitBase):
    arg_models = {"writer_generate": WriterGenerateArgs, "writer_apply": WriterApplyArgs}
    llm_dependent_tools = frozenset({"writer_generate"})
    confirming_tools = frozenset({"writer_apply"})
    auto_open = True

    def __init__(self, *, repo_root, llm_client=None, limits=None, expected_model_ids=(), owns_client=True, **kwargs):
        super().__init__(repo_root=repo_root, **kwargs)
        if llm_client is not None and getattr(llm_client, "_fallback_model", None):
            raise ValueError("TargetedWriterToolkit requires a client with fallback disabled "
                             "(llm_kwargs: {fallback_model: null}); got fallback_model=%r" % (llm_client._fallback_model,))
        self._client = llm_client; self._owns_client = owns_client and llm_client is not None
        self._limits = limits or WriterLimits(); self._expected_models = tuple(expected_model_ids)
        self._client_lock = asyncio.Lock(); self._store = ArtifactStore(self.policy.repo_root)

    async def _open(self) -> None:
        if self._owns_client: await self._client.__aenter__()
    async def _close(self) -> None:
        if self._owns_client:
            await self._client.__aexit__(None, None, None); await self._client.close()
```

```python
# the single model call
ai = await self._client.ask(prompt=prompt, system_prompt=SYSTEM_PROMPT, max_tokens=self._limits.max_output_tokens,
                            temperature=0.0, use_tools=False, history=None)
if ai.metadata and ai.metadata.get("used_fallback_model"):
    return self._error("writer_generate", "model_substituted", ..., details={"configured": configured, "actual": ai.model})
```

### Key Constraints
- Contract failure ⇒ zero client calls (assert with the recording fake).
- Exactly one repair maximum; transport retries inside the client
  (`max_retries`) are a separate budget but the deadline wraps both.
- The deadline uses `asyncio.timeout`; on expiry no artifact is written.
- `temperature=0.0` — spec says "appropriate to the configured client";
  Bedrock accepts `Optional[float]`, base accepts `float`.
- `writer_generate` never writes to any target path (test: snapshot the
  tree hash before/after).
- Keep `parrot.clients.*` imports under `TYPE_CHECKING`; importing
  `writer.py` must not import boto/aioboto3.

### References in Codebase
- `tests/mcp/test_toolkit_server.py:114-140` — how `llm_client` injection is tested with a mock `LLMFactory.create`.
- `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` — the contrastive/fallback mixin (context for why explicit disabling matters; not used here).

---

## Acceptance Criteria

- [ ] Constructor rejects a fake client with `_fallback_model="claude-haiku-4-5"`; accepts `_fallback_model=None`.
- [ ] `get_tools()` without `llm_client` still lists `writer_generate` (filtering is the MCP server's job) — and `create_toolkit_mcp_server` without `llm:` drops it (integration test in TASK-3091; here assert `llm_dependent_tools == {"writer_generate"}`).
- [ ] Invalid/stale contract → error result, `fake.calls == []`.
- [ ] Valid contract + fake returning a correct diff → `ok`, artifact dir exists with `manifest.json`/`patch.diff`/`packet.json`, targets untouched, `fake.calls[0]` kwargs == `{prompt, system_prompt, max_tokens=8192, temperature=0.0, use_tools=False, history=None}` and nothing else.
- [ ] Fake returning fenced prose first then a valid diff → `ok` with `repairs == 1`, two calls, second prompt contains the diagnostic code.
- [ ] Fake returning two bad patches → `error` with the second `PatchError` code, `repairs == 1`, exactly two calls, no artifact.
- [ ] Fake with `metadata={"used_fallback_model": True}` → `model_substituted`, one call, no repair.
- [ ] Fake with non-string `output` → `unexpected_tool_call`.
- [ ] Fake that sleeps beyond `generation_deadline_seconds=0.2` → `deadline_exceeded`; cancellation of the task mid-call leaves no `artifacts/tool-optimizations/*` dir and calls `fake.__aexit__`.
- [ ] Usage recorded; all-zero usage → `{"prompt_tokens": None, ...}`.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py -v`; lint clean; log in `artifacts/logs/TASK-3085-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py
import asyncio, hashlib
from types import SimpleNamespace
import pytest
from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit
from parrot_tools.tool_optimizations.models import WriterLimits
from .fixtures import make_repo_with_target, make_valid_task, GOOD_PATCH   # GOOD_PATCH built from the fixture repo

class FakeClient:
    def __init__(self, responses, *, fallback=None, delay=0.0, metadata=None, usage=(10, 20, 30)):
        self.model = "qwen3-coder-480b-a35b"; self._fallback_model = fallback
        self._responses = list(responses); self.calls = []; self.entered = self.exited = 0; self._delay = delay
        self._metadata = metadata or {}; self._usage = usage
    async def __aenter__(self): self.entered += 1; return self
    async def __aexit__(self, *a): self.exited += 1; return False
    async def close(self): pass
    async def ask(self, **kw):
        self.calls.append(kw); await asyncio.sleep(self._delay)
        text = self._responses.pop(0)
        usage = SimpleNamespace(prompt_tokens=self._usage[0], completion_tokens=self._usage[1], total_tokens=self._usage[2])
        return SimpleNamespace(response=text if isinstance(text, str) else None, output=text, model=self.model,
                               provider="bedrock-converse", usage=usage, metadata=dict(self._metadata))

def test_constructor_rejects_fallback(tmp_path):
    with pytest.raises(ValueError):
        TargetedWriterToolkit(repo_root=tmp_path, llm_client=FakeClient([], fallback="claude-haiku-4-5"))
    TargetedWriterToolkit(repo_root=tmp_path, llm_client=FakeClient([], fallback=None))

async def test_invalid_contract_makes_no_call(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    task.write_text(task.read_text().replace('"design_complete": true', '"design_complete": false'))
    fake = FakeClient([GOOD_PATCH])
    res = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task.relative_to(repo).as_posix())
    assert res.status == "error" and fake.calls == []

async def test_generate_ok_and_no_target_mutation(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    before = (repo / "pkg" / "__init__.py").read_bytes()
    fake = FakeClient([GOOD_PATCH])
    res = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task.relative_to(repo).as_posix())
    assert res.status == "ok" and (repo / res.data["patch_path"]).exists() and not (repo / "pkg" / "greeter.py").exists()
    assert (repo / "pkg" / "__init__.py").read_bytes() == before
    assert set(fake.calls[0]) == {"prompt", "system_prompt", "max_tokens", "temperature", "use_tools", "history"}
    assert fake.calls[0]["use_tools"] is False and fake.calls[0]["history"] is None

async def test_one_repair_then_success(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    fake = FakeClient(["```diff\nnope\n```", GOOD_PATCH])
    res = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task.relative_to(repo).as_posix())
    assert res.status == "ok" and res.data["repairs"] == 1 and len(fake.calls) == 2 and "not_a_patch" in fake.calls[1]["prompt"]

async def test_two_failures_stop(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    fake = FakeClient(["prose", "more prose", GOOD_PATCH])
    res = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task.relative_to(repo).as_posix())
    assert res.status == "error" and len(fake.calls) == 2 and not list((repo / "artifacts").glob("tool-optimizations/*"))

async def test_model_substitution_rejected(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    fake = FakeClient([GOOD_PATCH, GOOD_PATCH], metadata={"used_fallback_model": True})
    res = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task.relative_to(repo).as_posix())
    assert res.error.code == "model_substituted" and len(fake.calls) == 1

async def test_deadline(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    fake = FakeClient([GOOD_PATCH], delay=1.0)
    tk = TargetedWriterToolkit(repo_root=repo, llm_client=fake, limits=WriterLimits(generation_deadline_seconds=1))
    tk._limits = WriterLimits(generation_deadline_seconds=1)  # WriterLimits gt=0 int; use monkeypatch to 0.2 if float needed
    res = await tk.writer_generate(task.relative_to(repo).as_posix())
    assert res.error.code == "deadline_exceeded"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3083 and TASK-3084 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3085-writer-generate.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
