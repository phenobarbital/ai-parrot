---
type: feature
base_branch: dev
projects: [clients, knowledge-pageindex]
tags: [clients, tool-loop, capability, agentic-retrieval, pageindex]
docs:
  policy: required
  pages:
    - wiki/clients/abstract-client.md
    - wiki/knowledge/pageindex-agentic-retrieval.md
  api_modules:
    - parrot.clients.base
---

# Feature Specification: Client tool-loop capability flag

**Feature ID**: FEAT-848
**Date**: 2026-11-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: 2.2.0

---

## 1. Motivation & Business Requirements

> Follow-up escalated by `pageindex-agentic-retrieval` (FEAT-843, §8): "Should `AbstractClient`
> gain a capability flag so callers can fail fast instead of reading `stopped="no_tool_calls"`?"
> No brainstorm exists; the §6 research below replaces it.

### Problem Statement

`AbstractClient.ask()` accepts `tools`/`use_tools`, but nothing on the class says whether the
provider **executes** the model's tool calls and feeds the results back before returning. A caller
that needs a completed tool loop — the stage-2 `AgenticRetriever` (FEAT-843), any future
tool-driven helper — can only find out after the fact: it offers the tools, waits for the model,
and reads `tool_calls == 0`. On a provider without a loop that is a wasted LLM call and an answer
with `grounded=False` that looks like a model failure rather than a configuration error.

The research for this spec (§6, re-verified on `dev @ 8758f61456` with an MRO-resolved audit of
every installed provider) also corrected the record FEAT-843 left behind. FEAT-843 wrote that
seven providers "do not execute tools in `ask()`" (hf, meta, local, vllm, moonshot, nvidia, jev).
That grep looked only at each provider's own `client.py`; `MetaClient`, `LocalLLMClient`,
`vLLMClient`, `MoonshotClient`, `NvidiaClient` and `OpenRouterClient` all resolve `ask()` to
`OpenAIBaseClient.ask()` (or call it through `super()`), which runs `_run_tool_call_loop`
(`openai_base.py:995`). The providers that really have no tool loop are **four classes**:
`TransformersClient` (hf — warns "Tool calling not supported", `hf/client.py:373-374`),
`JevClient` (jev — warns "ignores tools", `jev/client.py:546-547`), `GeminiLiveClient`
(google-live — `ask()` takes no `tools` and yields voice, `live.py:1289`) and `OpenAICodexClient`
(codex — tools are served to the external Codex process over `CodexToolBridge`, not executed in
`ask()` itself; see §2 for how it is classified). The wiki page shipped by FEAT-843 repeats the
wrong table (`wiki/knowledge/pageindex-agentic-retrieval.md:173`).

### Goals

- G1 — One declarative class attribute on `AbstractClient`, `supports_tool_loop: bool`, default
  `True`, with the same shape as the existing declarative attributes `credential_env` and
  `budget_supported_methods` (`base.py:312-322`). `False` means: `ask()` / `ask_stream()` do not
  execute offered tools and feed results back before returning.
- G2 — The providers that do not run a loop declare `False`: `TransformersClient`, `JevClient`,
  `GeminiLiveClient`. `OpenAICodexClient` stays `True` (its tool results are consumed before
  `ask()` returns, through the bridge).
- G3 — `AgenticRetriever` and `PageIndexToolkit.agentic_retrieve` fail fast with a `ValueError`
  that names the client when the selected client declares `False` — before any candidate search
  or LLM call.
- G4 — A guard test keeps the flag honest: for every installed provider it resolves `ask()`
  through the MRO (plus one hop of `self._helper(` calls) and asserts that the presence of a
  tool-execution marker matches the declared flag, with an explicit, documented allowlist for
  clients whose loop runs in an external process (`OpenAICodexClient`).
- G5 — The documentation says the right thing: the provider table in the agentic-retrieval page
  is corrected, and `abstract-client.md` documents the attribute.

### Non-Goals (explicitly out of scope)

- Changing any provider's tool loop, adding a loop to hf/jev/live/codex, or adding a caller-
  settable turn cap to `ask()` (FEAT-843 §7 risk; separate work).
- Making `Agent`/`AbstractBot` consult the flag. They already degrade through their own prompt
  path; wiring is a follow-up (§8).
- A `typing.Protocol` (`ToolLoopCapable`) like `VoiceCapable` (`protocols.py:17`). A boolean
  class attribute is enough for a yes/no fact and matches `budget_supported_methods`.
- Rewriting FEAT-843's spec §6. Specs are historical; the correction lives in this spec, the wiki
  page and a one-line note in FEAT-843's §8 item (see §3 M4).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:837dfed57c0d972b85f85ee295095e79412186c1310c01aef0bc1b388bb71479 evaluation_digest=sha256:591a264b48b845c9db74ef04b19bccd2b57ba3ec701111034130fbfae430fe8a rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

A class attribute, three overrides, two fail-fast checks, one guard test, two doc pages.

```python
class AbstractClient(EventEmitterMixin, ABC):
    ...
    budget_supported_methods: FrozenSet[str] = frozenset()        # base.py:322 (existing)

    # FEAT-848: whether ask()/ask_stream() execute the model's tool calls and feed the
    # results back until a final answer. False = tools are ignored or only forwarded.
    supports_tool_loop: bool = True
```

`TransformersClient`, `JevClient` and `GeminiLiveClient` set `supports_tool_loop = False` next
to their `client_name`. Nothing else in the clients changes: the flag is declarative, read by
callers, never consulted by `ask()` itself (a provider that warns and ignores tools keeps doing
exactly that).

**Classification rule** (what `True` promises): when `ask()` is given `tools`/`use_tools`, the
tool calls the model emits are executed and their results are fed back to the model before
`ask()` returns its final answer — in-process (`_execute_tool`, `_run_tool_call_loop`,
`_handle_multiturn_function_calls`, `_run_tool_loop`) or by an external agent process that the
client drives to completion (`OpenAICodexClient` via `CodexToolBridge`). `False` when tools are
ignored (`TransformersClient`, `JevClient`) or when `ask()` has no tools parameter at all
(`GeminiLiveClient`, a voice iterator).

**Fail fast (FEAT-843 consumer).** `PageIndexToolkit._agentic_client()` (`toolkit.py:1145`)
raises `ValueError` when the resolved client (override or clone) declares `False`; it runs at
`toolkit.py:1191`, before candidate search. `AgenticRetriever.__init__` (`agentic.py:163`) raises
the same error for direct constructions. The message names the class and `client_type`:
`"agentic retrieval requires a client that executes tool calls inside ask(); TransformersClient
(transformers) declares supports_tool_loop=False"`. `EvidenceBundle` and `StopReason` are
unchanged — `no_tool_calls` remains the outcome for a `True` client whose model simply never
called a tool.

**Guard test.** `tests/clients/test_tool_loop_capability.py` enumerates
`LLMFactory.supported_clients()` exactly like `test_credential_env.py::_classes()`
(`test_credential_env.py:12-19`, skipping extras that are not installed). For each class it
collects the source of every `ask` in the MRO (stopping at the first one that does not call
`super().ask`) plus the source of each `self._name(` helper that `ask` calls (one hop), and sets
`runs_loop = any(marker in text for marker in MARKERS)`. The assertion is
`cls.supports_tool_loop is (runs_loop or cls.__name__ in EXTERNAL_LOOP_CLIENTS)`, with
`EXTERNAL_LOOP_CLIENTS = frozenset({"OpenAICodexClient"})` and a docstring explaining why. The
prototype of this rule, run on `dev @ 8758f61456`, classifies all 39 installed provider keys
(§6 table) with exactly the four `False` classes above — no other allowlist entry is needed.

### Component Diagram

```
AbstractClient.supports_tool_loop (base.py)          ── declarative, default True
   ├── TransformersClient = False (hf)
   ├── JevClient          = False (jev)
   └── GeminiLiveClient   = False (google/live)

PageIndexToolkit._agentic_client() ──checks──▶ client.supports_tool_loop ──False──▶ ValueError
AgenticRetriever.__init__          ──checks──▶ client.supports_tool_loop ──False──▶ ValueError

tests/clients/test_tool_loop_capability.py ── MRO audit of every installed provider
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` (`base.py:297`) | extends | new class attribute after `budget_supported_methods` (`:322`) |
| `TransformersClient` (`hf/client.py:31`) | modifies | `supports_tool_loop = False` after `client_name` (`:40`) |
| `JevClient` (`jev/client.py:119`) | modifies | `supports_tool_loop = False` after `client_name` (`:157`) |
| `GeminiLiveClient` (`google/live.py:328`) | modifies | `supports_tool_loop = False` after `client_name` (`:373`) |
| `PageIndexToolkit._agentic_client` (`toolkit.py:1145`) | modifies | fail-fast `ValueError` |
| `AgenticRetriever.__init__` (`agentic.py:163`) | modifies | fail-fast `ValueError` |
| `LLMFactory.supported_clients()` (`factory.py`) | uses | provider enumeration in the guard test |
| `wiki/knowledge/pageindex-agentic-retrieval.md:173` | updates | corrected provider table |
| `wiki/clients/abstract-client.md` | updates | documents the attribute |

### Data Models

None. One `bool` class attribute.

### New Public Interfaces

```python
# parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):
    supports_tool_loop: bool = True
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: flag + overrides | yes | attribute name, default, placement (after `budget_supported_methods`), the three `False` classes, comment text | — |
| M2: fail-fast in agentic retrieval | yes | two check sites, `ValueError`, exact message format | — |
| M3: guard test | yes | enumeration via `LLMFactory.supported_clients()`, MRO + one-hop rule, `MARKERS`, `EXTERNAL_LOOP_CLIENTS` | — |
| M4: documentation | yes | two pages, corrected table, FEAT-843 §8 note | — |

### Module 1: Capability flag and provider overrides
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`,
  `packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py`,
  `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py`,
  `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`
- **Responsibility**: declare the capability on the base class; set it `False` on the three
  clients without a tool loop.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  # base.py (modifies :322 — insert after the budget_supported_methods declaration)
  class AbstractClient(EventEmitterMixin, ABC):                        # verified: base.py:297
      budget_supported_methods: FrozenSet[str] = frozenset()           # verified: base.py:322
      # FEAT-848: whether ask()/ask_stream() execute the model's tool calls and feed the results
      # back until a final answer (in-process or through an agent bridge the client drives to
      # completion). False = tools are ignored or only forwarded; callers that need a completed
      # loop (AgenticRetriever) fail fast on it instead of reading tool_calls == 0.
      supports_tool_loop: bool = True

  # hf/client.py (modifies :40)
  class TransformersClient(AbstractClient):                            # verified: hf/client.py:31
      client_name: str = "transformers"                                # verified: hf/client.py:40
      supports_tool_loop: bool = False  # ask() warns and ignores tools (:373-374)

  # jev/client.py (modifies :157)
  class JevClient(AbstractClient):                                     # verified: jev/client.py:119
      client_name: str = "jev"                                         # verified: jev/client.py:157
      supports_tool_loop: bool = False  # ask() warns and ignores tools (:546-547)

  # google/live.py (modifies :373)
  class GeminiLiveClient(AbstractClient):                              # verified: live.py:328
      client_name: str = "google_live"                                 # verified: live.py:373
      supports_tool_loop: bool = False  # ask() takes no tools and yields voice (:1289)
  ```

### Module 2: Fail fast in agentic retrieval
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`,
  `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py`
- **Responsibility**: refuse a client without a tool loop before any work is done.
- **Depends on**: Module 1 (reads `supports_tool_loop`; `getattr(client, "supports_tool_loop", True)`
  so a test `StubClient` built before M1 lands still passes).
- **Interface Skeleton**:
  ```python
  # agentic.py (new module-level helper, placed before clone_for_tools :82; used by both sites)
  def require_tool_loop(client: AbstractClient) -> None:
      """Raise ``ValueError`` naming the client when it declares ``supports_tool_loop = False``.

      Message: ``"agentic retrieval requires a client that executes tool calls inside ask(); "
      f"{type(client).__name__} ({client.client_type}) declares supports_tool_loop=False"``."""

  # agentic.py (modifies :163-174 — first statement of AgenticRetriever.__init__)
  class AgenticRetriever:                                              # verified: agentic.py:158
      def __init__(self, *, client, model, read_tools, load_revision) -> None:   # verified: agentic.py:163
          """Unchanged signature; calls ``require_tool_loop(client)`` before storing it."""

  # toolkit.py (modifies :1145-1153 — after the client is resolved, before return)
  class PageIndexToolkit:
      def _agentic_client(self) -> AbstractClient:                     # verified: toolkit.py:1145
          """Unchanged contract; additionally calls ``require_tool_loop`` on the override or the
          clone, so ``agentic_retrieve`` (:1191) raises before candidate search."""
  ```

### Module 3: Guard test
- **Path**: `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` (new);
  `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` (append)
- **Responsibility**: the flag never drifts from what the providers do; the fail-fast path is
  covered.
- **Depends on**: Module 1, Module 2.
- **Interface Skeleton**:
  ```python
  # tests/clients/test_tool_loop_capability.py (new)
  MARKERS: tuple[str, ...] = ("_run_tool_call_loop", "_execute_tool(", "_handle_multiturn_function_calls", "_run_tool_loop(")
  EXTERNAL_LOOP_CLIENTS: frozenset[str] = frozenset({"OpenAICodexClient"})
      # tools are executed by the Codex process through CodexToolBridge and consumed before ask() returns

  def _installed_classes() -> dict[str, type[AbstractClient]]:
      """Same enumeration as test_credential_env._classes (LLMFactory.supported_clients, skip uninstalled)."""   # verified: test_credential_env.py:12-19

  def _resolved_ask_text(cls: type[AbstractClient]) -> str:
      """Source of every ``ask`` in the MRO up to the first that does not call ``super().ask``,
      plus the source of each ``self._helper(`` the ask bodies call (one hop)."""

  def test_default_is_true() -> None: ...                              # AbstractClient.supports_tool_loop is True
  @pytest.mark.parametrize("provider", sorted(_installed_classes()))
  def test_flag_matches_resolved_ask(provider: str) -> None: ...       # flag is (runs_loop or name in EXTERNAL_LOOP_CLIENTS)
  def test_known_false_classes() -> None: ...                          # hf/jev/google-live declare False when installed (skip otherwise)

  # tests/knowledge/pageindex/test_agentic_retrieval.py (append after :481)
  class NoLoopClient(StubClient):                                      # StubClient verified: test_agentic_retrieval.py:27
      supports_tool_loop = False
  async def test_agentic_retrieve_fails_fast_without_tool_loop(tmp_path: Path) -> None:
      """Toolkit with agentic_client=NoLoopClient(): agentic_retrieve raises ValueError naming
      NoLoopClient and stub; the stub recorded zero ask() calls."""
  def test_agentic_retriever_rejects_no_loop_client() -> None:
      """AgenticRetriever(client=NoLoopClient(), ...) raises ValueError at construction."""
  ```

### Module 4: Documentation
- **Path**: `wiki/clients/abstract-client.md`, `wiki/knowledge/pageindex-agentic-retrieval.md`,
  `sdd/specs/pageindex-agentic-retrieval.spec.md` (one line)
- **Responsibility**: document the attribute; replace the wrong provider table; close FEAT-843's
  escalated item by pointing at this spec.
- **Depends on**: Module 1 (names), Module 2 (error text).
- **Interface Skeleton** (content contract, not code):
  - `abstract-client.md` — under `## Public API`: `supports_tool_loop` (what `True` promises, the
    classification rule, the four `False` classes, "declarative: `ask()` never reads it"); under
    `## Gotchas`: a `False` client offered tools warns and ignores them — check the flag first.
  - `pageindex-agentic-retrieval.md:170-178` — replace the two-column table with: **runs the loop**
    — every installed provider except: `hf`/`transformers` (`TransformersClient`), `jev`/`typesafe`
    (`JevClient`), `gemini-live` (`GeminiLiveClient`); `OpenAICodexClient` runs it through the
    Codex bridge. State that `agentic_retrieve` now raises `ValueError` on a `False` client, and
    that `stopped="no_tool_calls"` is reserved for a capable client whose model made no call.
    Remove "OpenRouter is not in the verified table" (it inherits `OpenAIBaseClient.ask`).
  - `pageindex-agentic-retrieval.spec.md:939` — append `— Resolved by FEAT-848 (client-tool-loop-capability)`
    to the open item; the checkbox stays as the FEAT-843 author left it (historical document).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_default_is_true` | M1 | `AbstractClient.supports_tool_loop is True` |
| `test_known_false_classes` | M1 | installed `TransformersClient`/`JevClient`/`GeminiLiveClient` declare `False`; skipped per class when the satellite is absent |
| `test_flag_matches_resolved_ask[provider]` | M3 | MRO + one-hop audit agrees with the flag for every installed provider; `OpenAICodexClient` passes through `EXTERNAL_LOOP_CLIENTS` |
| `test_agentic_retriever_rejects_no_loop_client` | M2 | construction raises `ValueError` with class name and `client_type` |
| `test_agentic_retrieve_fails_fast_without_tool_loop` | M2 | toolkit raises before any `ask()`; stub call counter is 0 |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_cited_evidence` (existing, `test_agentic_retrieval.py:443`) | unchanged — `ScriptedToolLoopClient` inherits `True` and the loop still runs |
| `test_credential_env.py` (existing) | the sibling declarative attribute keeps working; same enumeration helper |

### Validation Contract

tests:
- packages/ai-parrot/tests/clients/test_tool_loop_capability.py
- packages/ai-parrot/tests/clients/test_credential_env.py
- packages/ai-parrot/tests/clients/test_import_hygiene.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py
markers: none

### Test Data / Fixtures

```python
# test_agentic_retrieval.py already provides StubClient (:27), ScriptedToolLoopClient (:59),
# _read_tool (:110), _retriever (:119) and the agentic_toolkit fixture (:418). The new tests add
# only NoLoopClient(StubClient) with supports_tool_loop = False and an ask() call counter.
```

---

## 5. Acceptance Criteria

- [ ] AC-1 Every file in the Validation Contract passes; no `real_llm` test is added.
- [ ] AC-2 `AbstractClient.supports_tool_loop` exists, is a class attribute, defaults to `True`, and
  `ask()`/`ask_stream()` in `base.py` do not read it (G1).
- [ ] AC-3 `TransformersClient`, `JevClient` and `GeminiLiveClient` declare `supports_tool_loop = False`;
  no other provider class in the workspace declares `False` (G2).
- [ ] AC-4 `AgenticRetriever(client=<False client>, ...)` raises `ValueError` whose message contains the
  class name and `client_type`; `PageIndexToolkit.agentic_retrieve` with such a client raises the same
  error before any `ask()` call and before candidate search (G3).
- [ ] AC-5 `test_flag_matches_resolved_ask` passes for every installed provider with
  `EXTERNAL_LOOP_CLIENTS == {"OpenAICodexClient"}` and no `xfail`/`skip` on a provider that is
  installed (G4).
- [ ] AC-6 `wiki/knowledge/pageindex-agentic-retrieval.md` no longer lists meta, local, vllm, moonshot,
  nvidia or openrouter as unsupported; `wiki/clients/abstract-client.md` documents the attribute;
  `parrot sdd techwiki check` passes for both pages (G5).
- [ ] AC-7 No breaking change: no signature changes, `EvidenceBundle`/`StopReason` unchanged,
  `test_import_hygiene.py` still passes (the attribute adds no import to `base.py`).

---

## 6. Codebase Contract

> Verified against `dev @ 8758f61456` (2026-11-09). `base.py` last changed 2026-11-01 (`7c624bfe33`).

### Verified Imports

```python
from parrot.clients.base import AbstractClient                 # verified: agentic.py:14, test_credential_env.py:8
from parrot.clients.factory import LLMFactory                  # verified: test_credential_env.py:9
from parrot.tools.manager import ToolManager                   # verified: agentic.py:26
from parrot.knowledge.pageindex.agentic import AgenticRetriever, EvidenceBundle, clone_for_tools   # verified: toolkit.py:38
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                                  # :297
    version: str = "0.1.0"                                                     # :300
    client_type: str = "generic"                                               # :304
    client_name: str = "generic"                                               # :305
    use_session: bool = False                                                  # :306
    credential_env: Optional[Tuple[str, ...]] = None                           # :312  (declarative precedent)
    @classmethod
    def has_server_credentials(cls) -> bool: ...                               # :315
    budget_supported_methods: FrozenSet[str] = frozenset()                     # :322  (declarative precedent)
    def __init_subclass__(cls, **kwargs: Any) -> None: ...                     # :324
    # __init__: self._tool_manager (ToolManager) :532-534; self.tools = {} :535; self.enable_tools = use_tools :536
    async def ask(self, prompt, model, max_tokens=None, temperature=0.7, files=None, system_prompt=None,
                  history=None, structured_output=None, tools=None, use_tools=None, deep_research=False,
                  background=False, lazy_loading=False) -> MessageResponse     # :1944-1982, raises NotImplementedError (providers implement)
    @abstractmethod
    async def ask_stream(...)                                                  # :1984

# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):
    async def _run_tool_call_loop(...) -> tuple[result, response, all_tool_calls, usage, round_number]   # :513-661 (while getattr(result, "tool_calls") :617; _execute_tool :657)
    async def ask(...)         # calls _run_tool_call_loop at :995  → inherited by Local/vLLM/Moonshot/NVIDIA/OpenRouter; Meta calls it at meta/client.py:801

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: Dict[str, Any] = _LazyClientRegistry()                      # :100 (entry points group "parrot.clients", :147)
class LLMFactory:
    @staticmethod
    def supported_clients() -> Dict[str, Any]: ...                             # used by test_credential_env.py:14; values are classes or zero-arg loaders
    @staticmethod
    def list_providers() -> Dict[str, str]: ...                                # :215

# packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py
class TransformersClient(AbstractClient):                                      # :31
    client_type: str = "transformers"                                          # :39
    client_name: str = "transformers"                                          # :40
    async def ask(..., tools: Optional[List[Dict[str, Any]]] = None, ...)      # :319; `if tools: self.logger.warning("Tool calling not supported by TransformersClient")` :373-374

# packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py
class JevClient(AbstractClient):                                               # :119
    client_type: str = "jev"                                                   # :156
    client_name: str = "jev"                                                   # :157
    async def ask(..., tools=None, use_tools=None, ...)                        # :496; `if tools or use_tools: self.logger.warning("JevClient ignores tools: ...")` :546-547

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py
class GeminiLiveClient(AbstractClient):                                        # :328
    client_type: str = "google_live"                                           # :372
    client_name: str = "google_live"                                           # :373
    async def ask(self, question, system_prompt=None, history=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]   # :1289 (no tools parameter)

# packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py
class OpenAICodexClient(AbstractClient):                                       # :71
    client_type = "openai_codex"; client_name = "openai-codex"                 # :79-80
    async def ask(..., use_tools: Optional[bool] = None, ...)                  # :122; expose_parrot_tools = use_tools :135-136; tools served via CodexToolBridge (:26)

# packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
StopReason = Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]   # :42
class EvidenceBundle(BaseModel): ... grounded: bool = False; tool_calls: int = 0                            # :63-75
def clone_for_tools(client: AbstractClient) -> AbstractClient                                               # :82-93
class AgenticRetriever:                                                                                     # :158
    def __init__(self, *, client: AbstractClient, model: Optional[str], read_tools: Sequence[AbstractTool],
                 load_revision: Callable[[str, str], Optional[DocumentRevision]]) -> None                 # :163-174
    # stopped = "no_tool_calls" when controller.admitted == 0 :354-355

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit:
    def __init__(..., agentic_client: Optional[AbstractClient] = None, ...)    # :167; self._agentic_client_override :207
    def _agentic_client(self) -> AbstractClient                               # :1145-1153 (override → adapter check → clone_for_tools :1152)
    async def agentic_retrieve(self, tree_name, query, top_k=5, draft_answer=True, ...)   # :1155; client = self._agentic_client() :1191; AgenticRetriever(...) :1249

# packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py
class StubClient(AbstractClient): client_type = "stub"                        # :27
class ScriptedToolLoopClient(StubClient)                                      # :59
def _read_tool() -> ToolkitTool; def _retriever(client) -> AgenticRetriever   # :110, :119
agentic_toolkit fixture                                                       # :418
def test_tool_listed_and_llm_dependent(tmp_path: Path) -> None                # :481 (last test in file)
```

### Provider audit (MRO-resolved, `dev @ 8758f61456`)

| Resolved `ask()` runs the loop | Classes (provider keys) |
|---|---|
| yes — in-process | `AnthropicClient` (anthropic, anthropic-aws, bedrock, claude), `ClaudeAgentClient`, `GoogleGenAIClient`, `GeminiOpenAICompatClient`, `OpenAIClient`, `OpenRouterClient`, `MetaClient` (meta, meta-muse, muse), `LocalLLMClient` (local, localllm, llamacpp, ollama), `vLLMClient`, `MoonshotClient` (moonshot, kimi), `NvidiaClient`, `GroqClient`, `GrokClient` (grok, xai), `ZaiClient` (zai, z.ai), `Gemma4Client`, `BedrockConverseClient`, `BedrockMantleClient` (bedrock-mantle, mantle), `NovaClient` |
| yes — external process | `OpenAICodexClient` (codex-agent, codex-code, openai-codex) — `EXTERNAL_LOOP_CLIENTS` |
| **no** | `TransformersClient` (hf, transformers), `JevClient` (jev, typesafe), `GeminiLiveClient` (gemini-live) |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractClient.supports_tool_loop` | subclasses | class attribute lookup | `base.py:322` (insertion point) |
| `require_tool_loop()` | `PageIndexToolkit._agentic_client()` | call before `return` | `toolkit.py:1145-1153` |
| `require_tool_loop()` | `AgenticRetriever.__init__` | first statement | `agentic.py:163-174` |
| guard test | `LLMFactory.supported_clients()` | enumeration | `test_credential_env.py:12-19` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractClient.supports_tool_loop`~~, ~~`supports_tools`~~, ~~`has_tool_loop`~~ — nothing of the kind exists today (`grep -n supports_ base.py` → none).
- ~~`AbstractClient.capabilities`~~ / ~~`client_capabilities`~~ — no capability object; the only declarative attributes are `credential_env`, `budget_supported_methods`, `client_type`, `client_name`, `use_session`.
- ~~`parrot.clients.protocols.ToolLoopCapable`~~ — only `VoiceCapable` exists (`protocols.py:17`); this spec adds no Protocol.
- ~~`AgenticRetriever.require_tool_loop`~~ — the helper is module-level in `agentic.py`, not a method.
- ~~`StopReason` value `"unsupported_client"`~~ — not added; the fail-fast path raises instead.
- ~~`OpenAIBaseClient.ask` without a loop~~ — it does run `_run_tool_call_loop` (`:995`); FEAT-843 §6's "NO tool execution in ask(): meta, local, vllm, moonshot, nvidia" is wrong and must not be copied.
- ~~`parrot sdd ids` ownership of FEAT-847 by this slug~~ — the ledger reserved FEAT-847 under this label first, but `sdd-agy-compatibility.spec.md` already carried a hand-assigned FEAT-847; this spec uses the second reservation, FEAT-848 (§8).

### Edit Sites (Blueprint Anchors)

Verified against: `8758f61456`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | `budget_supported_methods: FrozenSet[str] = frozenset()` | `base.py:322` | 1 |
| `packages/ai-parrot-client-hf/src/parrot/clients/hf/client.py` | MODIFY | `client_name: str = "transformers"` | `hf/client.py:40` | 1 |
| `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` | MODIFY | `client_name: str = "jev"` | `jev/client.py:157` | 1 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` | MODIFY | `client_name: str = "google_live"` | `live.py:373` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | MODIFY | `def clone_for_tools(client: AbstractClient) -> AbstractClient:` (helper inserted before) | `agentic.py:82` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | MODIFY | `load_revision: Callable[[str, str], Optional[DocumentRevision]],` (check inserted at the start of the body below) | `agentic.py:169` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `self._agentic_clone = clone_for_tools(self._adapter.client)` | `toolkit.py:1152` | 1 |
| `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | MODIFY | `def test_tool_listed_and_llm_dependent(tmp_path: Path) -> None:` (append after this test) | `test_agentic_retrieval.py:481` | 1 |
| `wiki/knowledge/pageindex-agentic-retrieval.md` | MODIFY | `\| anthropic, google, openai (via` (table row to replace) | `:173` | 1 |
| `wiki/clients/abstract-client.md` | MODIFY | `## Gotchas` (attribute documented under `## Public API` above it and a gotcha here) | `:231` | 1 |
| `sdd/specs/pageindex-agentic-retrieval.spec.md` | MODIFY | the `[ ] Should \`AbstractClient\` gain a capability flag` item | `:939` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Declarative class attribute with a comment block, exactly like `credential_env` (`base.py:308-312`)
  and `budget_supported_methods` (`base.py:319-322`). No property, no `__init__` plumbing.
- `base.py` gains no import (`test_import_hygiene.py` subprocess-checks `FORBIDDEN_ON_IMPORT`).
- Fail-fast reads the flag with `getattr(client, "supports_tool_loop", True)`; a duck-typed client
  without the attribute is treated as capable (today's behaviour).
- The guard test uses `inspect.getsource` on functions reached through the MRO; wrap each lookup in
  `try/except (OSError, TypeError)` (Cython/compiled or dynamically built methods) and treat a
  missing source as "no marker".
- Satellite tests are not touched; everything lives in `packages/ai-parrot/tests` and skips when a
  satellite is not installed (the enumeration drops uninstalled extras, `test_credential_env.py:16-18`).

### Known Risks / Gotchas
- **The audit is a heuristic.** A provider that renames its loop helper breaks
  `test_flag_matches_resolved_ask`; the fix is to extend `MARKERS` (if it still runs a loop) or set
  the flag (if it stopped). Either way the test forces the decision to be written down — that is its
  job. Allowlist growth must be justified in the test docstring.
- **`OpenAICodexClient` and the bridge**: the loop runs in the Codex process; `expose_parrot_tools`
  can be `False`, in which case tools are not offered at all — still `True` for the flag (the client
  *can* run the loop). Document in the test.
- **`GeminiLiveClient.ask` is a voice iterator**; `False` is about the text `ask()` contract.
  `LiveToolAdapter` (`live.py:81`) executes function calls inside the realtime session — that is not
  the `ask()` loop and must not flip the flag.
- **Provider aliases**: the audit sees the same class under several keys (e.g. `AnthropicClient`
  under `bedrock`); parametrising by provider key is intentional so a registry change is visible.
- **FEAT-843 wiki page** is the only user-facing place that lists the wrong providers; the FEAT-843
  spec §6 comment stays as written (historical), with the §8 pointer added.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none added |

---

## Decisions

```yaml
schema_version: 1
document_id: client-tool-loop-capability
entries:
  - id: tool-loop-flag-is-declarative
    statement: AbstractClient declares whether ask() executes tool calls through the class attribute supports_tool_loop (default True); ask() never reads it, and a provider whose ask() ignores or merely forwards tools must set it to False.
    relation: requires
    about: [clients]
    targets:
      - file:packages/ai-parrot/src/parrot/clients/base.py
    contradicts: []
    supersedes: []
    rationale: "Callers that need a completed tool loop (AgenticRetriever) fail fast on a declared fact instead of inferring it from tool_calls == 0 after a wasted LLM call."
    rejected_alternatives:
      - "A typing.Protocol (ToolLoopCapable) — a yes/no fact does not need structural typing; budget_supported_methods is the precedent."
      - "Detecting the loop at runtime from EvidenceBundle.stopped — costs the LLM call the flag exists to avoid."
  - id: agentic-retrieval-requires-tool-loop
    statement: PageIndexToolkit.agentic_retrieve and AgenticRetriever reject a client with supports_tool_loop False by raising ValueError before any candidate search or LLM call.
    relation: requires
    about: [knowledge-pageindex]
    targets:
      - file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
      - file:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
    contradicts: []
    supersedes: []
    rationale: "stopped=no_tool_calls stays reserved for a capable client whose model made no call; a configuration error should not look like a model outcome."
    rejected_alternatives:
      - "A new StopReason value (unsupported_client) — changes the bundle contract for a case that is a caller error."
```

## Consequences

<!-- decision-audit: input_digest=sha256:837dfed57c0d972b85f85ee295095e79412186c1310c01aef0bc1b388bb71479 evaluation_digest=sha256:591a264b48b845c9db74ef04b19bccd2b57ba3ec701111034130fbfae430fe8a rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: clients, knowledge-pageindex
- Unmapped tags: agentic-retrieval, capability, tool-loop
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "clients",
      "knowledge-pageindex"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "agentic-retrieval",
      "capability",
      "tool-loop"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:591a264b48b845c9db74ef04b19bccd2b57ba3ec701111034130fbfae430fe8a",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:837dfed57c0d972b85f85ee295095e79412186c1310c01aef0bc1b388bb71479",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:bb381ecbfeb0f4e84ed2b2cbe385cd9a76a9c2ec15ca304256d083c253d9c532",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Which providers really lack a tool loop? — *Resolved in this spec (§6 audit)*: `TransformersClient`,
  `JevClient`, `GeminiLiveClient`; `OpenAICodexClient` runs it externally. FEAT-843's list of seven was
  a grep artefact (inherited `OpenAIBaseClient.ask`).
- [x] Flag or Protocol? — *Resolved*: class attribute `supports_tool_loop: bool = True` (precedent
  `budget_supported_methods`).
- [x] Fail fast how? — *Resolved*: `ValueError` naming class and `client_type`, at
  `PageIndexToolkit._agentic_client()` and `AgenticRetriever.__init__`; `StopReason` unchanged.
- [x] Feature ID — *Resolved*: the ledger issued FEAT-847 first, but `sdd-agy-compatibility.spec.md`
  already carries a hand-assigned FEAT-847 (never reserved). This spec takes the second reservation,
  FEAT-848, so no two specs share an ID; the ledger's FEAT-847 row therefore covers the agy spec under
  the wrong label (cosmetic — `existing-feature-id` resolves by spec, not by ledger label).
- [ ] Should `AbstractBot`/`Agent` warn (or refuse) when a `False` client is configured with tools,
  instead of silently running prompt-only? — *Owner: Jesus Lara*; follow-up, not this slice.
- [ ] Should `ask_stream()` have its own flag? Today every `False` client is `False` for both paths and
  every loop client streams its loop too (`_max_tool_rounds = 25` on the streaming paths). Revisit only
  if a provider diverges. — *Owner: Jesus Lara*.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over
> this spec). Model: `—` · Status: skipped (no exploration document — follow-up spec seeded from
> FEAT-843 §8; codex is installed but the seat requires an accepted brainstorm or proposal)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/clients/abstract-client.md` — update: document `supports_tool_loop` under Public API and
    a Gotcha for `False` clients.
  - `wiki/knowledge/pageindex-agentic-retrieval.md` — update: corrected provider table, fail-fast
    behaviour, `no_tool_calls` semantics.
- **API modules**:
  - `parrot.clients.base`

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara | Initial draft from FEAT-843 §8 escalation; MRO audit corrects the provider list. |
