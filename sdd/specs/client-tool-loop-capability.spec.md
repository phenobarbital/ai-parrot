---
type: feature
base_branch: dev
projects: [clients, knowledge-pageindex, bots]
tags: [clients, tool-loop, capability, agentic-retrieval, pageindex, bots]
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
**Status**: approved
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
(`openai_base.py:995`). The providers without a text `ask()` tool loop are **three classes**:
`TransformersClient` (hf — warns "Tool calling not supported", `hf/client.py:373-374`),
`JevClient` (jev — warns "ignores tools", `jev/client.py:546-547`), `GeminiLiveClient`
(google-live — `ask()` takes no `tools` and yields voice, `live.py:1289`). `OpenAICodexClient`
and `ClaudeAgentClient` drive external agent loops through tool bridges and remain capable;
their tools must be registered in `ToolManager` (see §2). The wiki page shipped by FEAT-843 repeats the
wrong table (`wiki/knowledge/pageindex-agentic-retrieval.md:173`).

### Goals

- G1 — One declarative class attribute on `AbstractClient`, `supports_tool_loop: bool`, default
  `True`, with the same shape as the existing declarative attributes `credential_env` and
  `budget_supported_methods` (`base.py:312-322`). `False` means: text `ask()` does not execute
  offered tools and feed results back before returning. The flag makes no claim about `ask_stream()`.
- G2 — The providers that do not run a loop declare `False`: `TransformersClient`, `JevClient`,
  `GeminiLiveClient`. `OpenAICodexClient` and `ClaudeAgentClient` stay `True` (registered tool
  results are consumed before `ask()` returns, through their respective bridges).
- G3 — `AgenticRetriever` and `PageIndexToolkit.agentic_retrieve` fail fast with a `ValueError`
  that names the client when the selected client declares `False` — before any candidate search
  or LLM call.
- G4 — A guard test keeps the flag honest: for every installed provider it resolves `ask()`
  through the MRO (plus one hop of `self._helper(` calls) and asserts that the presence of
  executable tool-call evidence matches the declared flag, with an explicit, documented allowlist
  for external agent loops (`OpenAICodexClient`, `ClaudeAgentClient`), each backed by a bridge
  exposure test (Codex's already exists).
- G5 — The documentation says the right thing: the provider table in the agentic-retrieval page
  is corrected, and `abstract-client.md` documents the attribute.
- G6 — `AbstractBot.configure()` logs one warning when the bot is in agent mode (tools enabled,
  tools registered, operation mode not `conversational`) and its LLM client declares
  `supports_tool_loop = False`. It never refuses. Today `TransformersClient` drops a bot's tools
  with no log at all: the bot hands tools over through `tool_manager` with `use_tools=True`, and
  hf only warns on inline `tools=` (`hf/client.py:373-374`). `JevClient` warns on every call.

### Non-Goals (explicitly out of scope)

- Changing any provider's tool loop, adding a loop to hf/jev/live/codex, or adding a caller-
  settable turn cap to `ask()` (FEAT-843 §7 risk; separate work).
- Declaring streaming capability or changing `ask_stream()`. Streaming already differs from
  `ask()` in Grok, Groq and Meta's default Responses path. No streaming flag will be added: those
  three are provider defects, tracked in the ledger (`issue:2d16e4d75557` Grok,
  `issue:3e76568cae48` Groq, `issue:3a0ea22ce45a` Meta) and fixed in the providers (§8).
- Standardizing inline `tools` registration across providers. Callers must use the provider's
  supported registration and enabling path; the agent bridges expose registered manager tools.
- Making `Agent`/`AbstractBot` refuse a `False` client, or change how they call it. They only
  warn once at `configure()` (G6, §3 M5). Per-call client overrides and the
  `ModelSwitchingMixin` secondary client are not checked.
- A `typing.Protocol` (`ToolLoopCapable`) like `VoiceCapable` (`protocols.py:17`). A boolean
  class attribute is enough for a yes/no fact and matches `budget_supported_methods`.
- Rewriting FEAT-843's spec §6. Specs are historical; the correction lives in this spec, the wiki
  page and a one-line note in FEAT-843's §8 item (see §3 M4).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:e7f03f7320757d6476c8c6456d6105f1ec09f11e58ce91dd1a8b815aeabb58ee evaluation_digest=sha256:44d3f846758c517a2da47bb39ab9f535f672bff85a38bc7ca24baa7b648fdf9a rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

A class attribute, three overrides, two fail-fast checks, one configure-time bot warning, one
guard test, two doc pages.

```python
class AbstractClient(EventEmitterMixin, ABC):
    ...
    budget_supported_methods: FrozenSet[str] = frozenset()        # base.py:322 (existing)

    # FEAT-848: whether text ask() executes enabled, registered tools and feeds results
    # back before returning. No claim about ask_stream() or inline tools registration.
    supports_tool_loop: bool = True
```

`TransformersClient`, `JevClient` and `GeminiLiveClient` set `supports_tool_loop = False` next
to their `client_name`. Nothing else in the clients changes: the flag is declarative, read by
callers, never consulted by `ask()` itself (a provider that warns and ignores tools keeps doing
exactly that).

**Classification rule** (what `True` promises): text `ask()` supports executing model-emitted
tool calls and feeding their results back before returning, subject to its existing loop limits.
Tools must be registered and enabled through the provider's supported path. Execution may be
in-process (`_execute_tool`, `_run_tool_call_loop`, `_handle_multiturn_function_calls`,
`_run_tool_loop`) or driven through an external agent (`OpenAICodexClient` via `CodexToolBridge`,
`ClaudeAgentClient` via `ClaudeAgentToolBridge`). `False` means no such text `ask()` loop:
`TransformersClient`, `JevClient`, and the voice iterator `GeminiLiveClient`.

`True` does **not** promise support for inline `ask(tools=...)`: Codex discards that argument
through `**kwargs`, and Claude explicitly ignores it. Both bridges expose tools already
registered in `client.tool_manager`, subject to their run-option exposure filters. PageIndex
already clears and registers its wrapped tools there, then calls `ask(tools=None, use_tools=True)`
(`agentic.py:295-304`). Preserve and test this delivery path. The flag is a class capability,
not a guarantee that a particular model, configuration, or call will invoke a tool.

`ask_stream()` is outside this contract: Grok ignores tools on that path, Groq sends them but
discards the model's tool-call deltas, and Meta's default Responses streaming path omits tool
round trips (`grok/client.py:417-558`, `groq/client.py:797-838`, `meta/client.py:887-892`). These
are provider defects tracked in the ledger, not a second capability (§8).

**Fail fast (FEAT-843 consumer).** `PageIndexToolkit._agentic_client()` (`toolkit.py:1145`)
raises `ValueError` when the resolved client (override or clone) declares `False`; it runs at
`toolkit.py:1191`, before candidate search. `AgenticRetriever.__init__` (`agentic.py:163`) raises
the same error for direct constructions. The message names the class and `client_type`:
`"agentic retrieval requires a client that executes tool calls inside ask(); TransformersClient
(transformers) declares supports_tool_loop=False"`. `EvidenceBundle` and `StopReason` are
unchanged — `no_tool_calls` remains the outcome for a `True` client whose model simply never
called a tool.

**Bot warning (G6).** A new private method `AbstractBot._warn_if_client_lacks_tool_loop()` runs in
`configure()` right after the default client is created and synced (`abstract.py:1693-1694`). It
first checks `getattr(self._llm, "supports_tool_loop", True) is False` and returns otherwise. The
identity check matters: the `configure()` stubs in `test_double_configure.py` use a `MagicMock`
client and a bot built with `object.__new__` that has no `enable_tools`, so a mock must never get
past the first line. Only then it checks `self.is_agent_mode()` (`abstract.py:3704`) and logs one
`self.logger.warning`:
`"%s: LLM client %s (%s) declares supports_tool_loop=False; its %d registered tools will not be
executed"` with the bot name, client class, `client_type` and `self.tool_manager.tool_count()`.
It never raises. Every `Agent` with default settings registers `ToJsonTool` (`agent.py:466`), so an
hf or jev `Agent` always gets this warning — that is intended, since those tools are never run.
`configure()` is idempotent per instance (FEAT-721), so the warning fires once per real run.

**Guard test.** `tests/clients/test_tool_loop_capability.py` enumerates
`LLMFactory.supported_clients()` using `test_credential_env.py::_classes()` as the registry
enumeration precedent (`test_credential_env.py:12-19`). Skip confirmed absent extras only;
do not copy its broad exception swallowing. For each class it
parses dedented source with `ast.parse` for every reachable `ask` in the MRO (following
`super().ask(...)` call nodes), plus each directly called `self._name(...)` helper (one hop).
Only executable `ast.Call` nodes whose function is `self.<name>` count toward
`TOOL_EXECUTION_METHODS`; comments, docstrings, string literals and uncalled method references
do not count. Nested function/class bodies are not evidence unless separately resolved as calls.
The resulting boolean is `runs_loop`. The assertion is
`cls.supports_tool_loop is (runs_loop or cls.__name__ in EXTERNAL_LOOP_CLIENTS)`, with
`EXTERNAL_LOOP_CLIENTS = frozenset({"OpenAICodexClient", "ClaudeAgentClient"})`, documenting each
bridge. The original substring prototype on `dev @ 8758f61456` was insufficient: Claude matched a
comment mentioning `_execute_tool()` (`claude_agent.py:481`). The AST rule above was prototyped on
`dev @ 1c3790c12b` over the 39 installed provider keys (22 classes): it yields exactly the three
`False` classes and the two bridge clients as `ast_loop=NO`, every other class as `yes` — so the
allowlist needs no further entry. Allowlist membership is backed by an exposure test, not by name
alone: Codex is already covered by
`ai-parrot-client-openai/tests/unit/test_codex_agent.py::test_tool_bridge_routes_through_tool_manager`;
this feature adds the Claude counterpart (§3 M3, `test_claude_bridge_exposes_registered_tools`).
Executing tools *through* the bridges is the bridges' own contract (FEAT-434), not this feature's.

### Component Diagram

```
AbstractClient.supports_tool_loop (base.py)          ── declarative, default True
   ├── TransformersClient = False (hf)
   ├── JevClient          = False (jev)
   └── GeminiLiveClient   = False (google/live)

PageIndexToolkit._agentic_client() ──checks──▶ client.supports_tool_loop ──False──▶ ValueError
AgenticRetriever.__init__          ──checks──▶ client.supports_tool_loop ──False──▶ ValueError
AbstractBot.configure()            ──checks──▶ self._llm.supports_tool_loop ──False + agent mode──▶ one warning

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
| `AbstractBot.configure()` (`bots/abstract.py:1604`) | modifies | calls the new warning helper after `self.sync_tools(self._llm)` (`:1694`) |
| `AbstractBot.is_agent_mode()` (`bots/abstract.py:3704`) | uses | agent-mode condition for the warning |
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
| M3: guard test | yes | provider enumeration, MRO + one-hop AST call rule, `TOOL_EXECUTION_METHODS`, both bridge exceptions, one Claude bridge exposure test | — |
| M4: documentation | yes | two pages, corrected table, FEAT-843 §8 note | — |
| M5: bot configure-time warning | yes | helper name and placement, `is False` identity check first, `is_agent_mode()` condition, exact message, never raises | — |

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
      # FEAT-848: whether text ask() executes enabled, registered tools and feeds results back
      # before returning (in-process or through an agent bridge, subject to existing limits).
      # No claim about ask_stream() or inline tools registration. AgenticRetriever fails fast
      # on False instead of reading tool_calls == 0 after a wasted call.
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
  TOOL_EXECUTION_METHODS: frozenset[str] = frozenset({
      "_run_tool_call_loop", "_execute_tool", "_handle_multiturn_function_calls", "_run_tool_loop",
  })
  EXTERNAL_LOOP_CLIENTS: frozenset[str] = frozenset({"OpenAICodexClient", "ClaudeAgentClient"})
      # Registered manager tools are exposed through CodexToolBridge / ClaudeAgentToolBridge;
      # the client drives the external agent to completion before ask() returns.

  def _installed_classes() -> dict[str, type[AbstractClient]]:
      """Enumerate LLMFactory.supported_clients; skip confirmed absent extras, fail other loader errors."""

  def _resolved_ask_calls(cls: type[AbstractClient]) -> frozenset[str]:
      """Return self-method call names from reachable ask bodies and one-hop helpers.

      Parse dedented source with ast; follow actual super().ask() calls through the MRO.
      Ignore comments, strings, uncalled references and nested function/class definitions.
      """

  def test_default_is_true() -> None: ...                              # AbstractClient.supports_tool_loop is True
  @pytest.mark.parametrize("provider", sorted(_installed_classes()))
  def test_flag_matches_resolved_ask(provider: str) -> None: ...       # flag is (runs_loop or name in EXTERNAL_LOOP_CLIENTS)
  def test_known_false_classes() -> None: ...                          # hf/jev/google-live declare False when installed (skip otherwise)
  def test_comment_and_string_markers_do_not_count() -> None: ...      # synthetic no-loop class stays False
  def test_executable_marker_counts_through_mro_and_helper() -> None: ...  # synthetic inherited/wrapped loop
  def test_uncalled_nested_marker_does_not_count() -> None: ...        # dead nested helper stays False
  def test_claude_bridge_exposes_registered_tools() -> None:
      """Register a sentinel tool in ClaudeAgentClient().tool_manager, build the bridge the way
      ask() does (ClaudeAgentToolBridge(client.tool_manager, ...).select(prompt, max_exposed_tools),
      claude_agent.py:465-484) and assert the sentinel is in bridge.exposed_names(). No SDK call,
      no network; pytest.importorskip("claude_agent_sdk"). The Codex counterpart already exists:
      test_codex_agent.py::test_tool_bridge_routes_through_tool_manager (:129)."""

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
  `sdd/specs/pageindex-agentic-retrieval.spec.md` (one line),
  `packages/ai-parrot/tests/clients/test_tool_loop_docs.py` (new — AC-6 content checks)
- **Responsibility**: document the attribute; replace the wrong provider table; close FEAT-843's
  escalated item by pointing at this spec.
- **Depends on**: Module 1 (names), Module 2 (error text), Module 5 (warning text).
- **Interface Skeleton** (content contract, not code):
  - `abstract-client.md` — under `## Public API`: `supports_tool_loop` (what `True` promises, the
    ask-only classification rule, the three `False` classes, "declarative: `ask()` never reads it",
    and the registered-tool prerequisite for both agent bridges); under
    `## Gotchas`: a `False` client ignores offered tools (hf with no log when they come through
    `tool_manager`) — check the flag first; `AbstractBot.configure()` logs one warning when an
    agent-mode bot uses such a client, and never refuses it. `ask_stream()` has no capability
    flag; the Grok, Groq and Meta (Responses) streaming gaps are tracked defects.
  - `pageindex-agentic-retrieval.md:170-178` — replace the two-column table with: **runs the loop**
    — every installed provider except: `hf`/`transformers` (`TransformersClient`), `jev`/`typesafe`
    (`JevClient`), `gemini-live` (`GeminiLiveClient`); `OpenAICodexClient` and `ClaudeAgentClient`
    run it through their respective bridges using registered manager tools. Label the table
    as text `ask()` capability only; explicitly exclude streaming and inline-tool registration
    guarantees. State that `agentic_retrieve` now raises `ValueError` on a `False` client, and
    that `stopped="no_tool_calls"` is reserved for a capable client whose model made no call.
    Remove "OpenRouter is not in the verified table" (it inherits `OpenAIBaseClient.ask`).
  - `pageindex-agentic-retrieval.spec.md:939` — append `— Resolved by FEAT-848 (client-tool-loop-capability)`
    to the open item; the checkbox stays as the FEAT-843 author left it (historical document).

### Module 5: Bot configure-time warning
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`;
  `packages/ai-parrot/tests/bots/test_tool_loop_warning.py` (new)
- **Responsibility**: tell the operator, once, that an agent-mode bot's tools will never run
  because its client declares no tool loop. Log only; behaviour is unchanged.
- **Depends on**: Module 1 (reads `supports_tool_loop` with a `getattr` default of `True`, so it
  works before M1 lands).
- **Interface Skeleton**:
  ```python
  # abstract.py (new private method, inserted before is_agent_mode :3704)
  class AbstractBot:
      def _warn_if_client_lacks_tool_loop(self) -> None:
          """Log one warning when an agent-mode bot's client declares supports_tool_loop=False.

          Order is part of the contract: return unless
          ``getattr(self._llm, "supports_tool_loop", True) is False`` (identity check, so a
          MagicMock client never passes); then return unless ``self.is_agent_mode()``; then
          ``self.logger.warning("%s: LLM client %s (%s) declares supports_tool_loop=False; its %d "
          "registered tools will not be executed", self.name, type(self._llm).__name__,
          getattr(self._llm, "client_type", "?"), self.tool_manager.tool_count())``. Never raises."""

  # abstract.py (modifies :1693-1694 inside configure(), same indentation as the if-statement)
                      if self.tool_manager and hasattr(self._llm, "tool_manager"):   # verified: abstract.py:1693
                          self.sync_tools(self._llm)                                 # verified: abstract.py:1694
                      self._warn_if_client_lacks_tool_loop()                          # new, after the if-block

  # tests/bots/test_tool_loop_warning.py (new) — bot shell and stub pattern from
  # test_double_configure.py (_ConfigureTestBot :12, _stub_bot :32)
  class _NoLoopClient:  supports_tool_loop = False; client_type = "noloop"
  class _LoopClient:    supports_tool_loop = True;  client_type = "loop"
  def test_warns_once_for_agent_mode_no_loop_client() -> None: ...     # enable_tools, 1 tool, adaptive → one warning naming bot, _NoLoopClient, noloop, 1
  def test_silent_for_loop_client() -> None: ...                       # _LoopClient → no warning
  def test_silent_when_not_agent_mode() -> None: ...                   # enable_tools False, or 0 tools, or "conversational" → no warning
  def test_silent_for_mock_client_without_bot_state() -> None: ...     # MagicMock client on an object.__new__ bot with no enable_tools → no warning, no AttributeError
  async def test_configure_calls_warning_after_client_creation() -> None: ...  # _stub_bot + _create_llm_client → _NoLoopClient; configure() warns once; a second configure() adds none
  # _stub_bot defines no enable_tools/operation_mode and its tool_manager is a bare MagicMock:
  # the positive tests set enable_tools=True, operation_mode="adaptive", name, and
  # tool_manager.tool_count.return_value = 1 (is_agent_mode -> has_tools -> get_tools_count :4746).
  # test_double_configure.py:46 and test_configure_override_guards.py:70 return a MagicMock client,
  # which the identity check stops on the first line — both files pass unchanged.
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_default_is_true` | M1 | `AbstractClient.supports_tool_loop is True` |
| `test_known_false_classes` | M1 | installed `TransformersClient`/`JevClient`/`GeminiLiveClient` declare `False`; skipped per class when the satellite is absent |
| `test_flag_matches_resolved_ask[provider]` | M3 | MRO + one-hop AST call audit agrees with the ask-only flag; both agent bridge clients are explicit exceptions |
| `test_comment_and_string_markers_do_not_count` | M3 | comments/docstrings/string literals containing execution method names cannot classify a synthetic no-loop client as capable |
| `test_executable_marker_counts_through_mro_and_helper` | M3 | actual inherited/delegated self-method calls count, including a one-hop helper |
| `test_uncalled_nested_marker_does_not_count` | M3 | an uncalled nested function containing an execution call is not evidence |
| `test_claude_bridge_exposes_registered_tools` | M3 | a sentinel registered in `ClaudeAgentClient().tool_manager` appears in `ClaudeAgentToolBridge(...).exposed_names()`; no SDK call (Codex side already covered by `test_codex_agent.py:129`) |
| `test_agentic_retriever_rejects_no_loop_client` | M2 | construction raises `ValueError` with class name and `client_type` |
| `test_agentic_retrieve_fails_fast_without_tool_loop` | M2 | toolkit raises before any `ask()`; stub call counter is 0 |
| `test_warns_once_for_agent_mode_no_loop_client` | M5 | one warning with bot name, client class, `client_type` and tool count |
| `test_silent_for_loop_client` | M5 | a `True` client logs nothing |
| `test_silent_when_not_agent_mode` | M5 | tools disabled, no tools, or `conversational` mode log nothing |
| `test_silent_for_mock_client_without_bot_state` | M5 | `MagicMock` client on a bare bot: no warning, no `AttributeError` |
| `test_configure_calls_warning_after_client_creation` | M5 | `configure()` warns once; the idempotent second call adds none |
| `test_agentic_provider_table_is_corrected` | M4 | the agentic-retrieval provider table names the three `False` classes and no inherited-loop provider (AC-6) |
| `test_abstract_client_documents_the_flag` | M4 | `abstract-client.md` documents the attribute, the bot warning and the absence of a streaming flag (AC-6) |

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
- packages/ai-parrot/tests/bots/test_tool_loop_warning.py
- packages/ai-parrot/tests/bots/test_double_configure.py
- packages/ai-parrot/tests/bots/test_configure_override_guards.py
- packages/ai-parrot/tests/clients/test_tool_loop_docs.py
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
  neither `ask()` nor `ask_stream()` in `base.py` reads it (G1). Its documented scope is text
  `ask()` only, with provider-supported tool registration/enabling and existing loop limits;
  it makes no streaming or inline-tool registration guarantee.
- [ ] AC-3 `TransformersClient`, `JevClient` and `GeminiLiveClient` declare `supports_tool_loop = False`;
  no other provider class in the workspace declares `False` (G2).
- [ ] AC-4 `AgenticRetriever(client=<False client>, ...)` raises `ValueError` whose message contains the
  class name and `client_type`; `PageIndexToolkit.agentic_retrieve` with such a client raises the same
  error before any `ask()` call and before candidate search (G3).
- [ ] AC-5 `test_flag_matches_resolved_ask` passes for every installed provider with
  `EXTERNAL_LOOP_CLIENTS == {"OpenAICodexClient", "ClaudeAgentClient"}` and no `xfail`/`skip`
  on an installed provider (G4). Only AST call evidence counts; comment/string/nested-definition
  negative fixtures and MRO/helper positive fixtures pass. `test_claude_bridge_exposes_registered_tools`
  passes when `claude_agent_sdk` is installed; the Codex side is covered by the existing
  `test_codex_agent.py::test_tool_bridge_routes_through_tool_manager`.
- [ ] AC-6 `wiki/knowledge/pageindex-agentic-retrieval.md` no longer lists meta, local, vllm, moonshot,
  nvidia or openrouter as unsupported; both pages document the ask-only scope and both bridges'
  manager-registration prerequisite (inline `tools` is ignored by those clients);
  `parrot sdd techwiki check` passes for both pages (G5).
- [ ] AC-7 No breaking change: no signature changes, `EvidenceBundle`/`StopReason` unchanged,
  `test_import_hygiene.py` still passes (the attribute adds no import to `base.py`).
- [ ] AC-8 `AbstractBot.configure()` logs exactly one warning, and never raises, when the bot is in
  agent mode and its client declares `supports_tool_loop = False`; a `True` client, a non-agent-mode
  bot and a `MagicMock` client log nothing. `test_double_configure.py` and
  `test_configure_override_guards.py` still pass unchanged (G6).

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

# packages/ai-parrot/src/parrot/bots/abstract.py   (verified dev @ 474fe3f682)
class AbstractBot:
    # __init__: self.enable_tools: bool = kwargs.get("enable_tools", kwargs.get("use_tools", True))   # :416
    # __init__: self.operation_mode: str = kwargs.get("operation_mode", "adaptive")                   # :568
    async def configure(self, app=None) -> None                                 # :1604
    #   self._llm = self._create_llm_client(config)                             # :1692
    #   if self.tool_manager and hasattr(self._llm, "tool_manager"):            # :1693
    #       self.sync_tools(self._llm)                                          # :1694 (only occurrence)
    def _create_llm_client(self, config: LLMConfig) -> AbstractClient           # :1042 (passes tool_manager=self.tool_manager)
    def is_agent_mode(self) -> bool                                             # :3704 — enable_tools and has_tools() and operation_mode in ["agentic", "adaptive"]
    def get_tools_count(self) -> int                                            # :4746 — self.tool_manager.tool_count()
    def has_tools(self) -> bool                                                 # :4751

# packages/ai-parrot/src/parrot/interfaces/tools.py
    def sync_tools(self, llm: AbstractClient = None) -> None                    # :387 — llm.tool_manager = self.tool_manager; llm.enable_tools = True

# packages/ai-parrot/src/parrot/bots/agent.py
    def _get_default_tools(self, tools, *, use_tools: bool = True) -> List[AbstractTool]   # :451; appends ToJsonTool() :466

# packages/ai-parrot/src/parrot/bots/base.py
    async def ask(...)          # :1069; llm_kwargs "use_tools" :1467 → client.ask (no inline tools=)
    async def ask_stream(...)   # :1878; llm_kwargs "use_tools" :2111 → client.ask_stream(**llm_kwargs) :2159

# packages/ai-parrot/tests/bots/test_double_configure.py
class _ConfigureTestBot(AbstractBot)                                          # :12
def _stub_bot() -> AbstractBot                                                # :32; _create_llm_client → MagicMock() :46
```

### Provider audit (MRO-resolved, `dev @ 8758f61456`)

| Resolved `ask()` runs the loop | Classes (provider keys) |
|---|---|
| yes — in-process | `AnthropicClient` (anthropic, anthropic-aws, bedrock, claude), `GoogleGenAIClient`, `GeminiOpenAICompatClient`, `OpenAIClient`, `OpenRouterClient`, `MetaClient` (meta, meta-muse, muse), `LocalLLMClient` (local, localllm, llamacpp, ollama), `vLLMClient`, `MoonshotClient` (moonshot, kimi), `NvidiaClient`, `GroqClient`, `GrokClient` (grok, xai), `ZaiClient` (zai, z.ai), `Gemma4Client`, `BedrockConverseClient`, `BedrockMantleClient` (bedrock-mantle, mantle), `NovaClient` |
| yes — external agent bridge | `OpenAICodexClient` (codex-agent, codex-code, openai-codex), `ClaudeAgentClient` (claude-agent, claude-code) — `EXTERNAL_LOOP_CLIENTS`; tools must be registered in `ToolManager` |
| **no** | `TransformersClient` (hf, transformers), `JevClient` (jev, typesafe), `GeminiLiveClient` (gemini-live) |

Review correction verified on `dev @ af753b61ce`: this table describes text `ask()` only.
Claude's earlier in-process classification came from a comment-only substring match in
`claude_agent.py:481`; actual delivery uses `ClaudeAgentToolBridge` at `:465-484` and SDK
collection at `:644`. Codex ignores inline tools at `codex_agent.py:133`; Claude does so at
`claude_agent.py:591`. The AST guard rule was then prototyped on `dev @ 1c3790c12b` (the clients
are unchanged since `8758f61456`) and reproduces this table exactly — 3 `False`, 2 bridge
exceptions, 17 in-process classes; the committed test is implementation work, the classification
is not.

### Streaming audit (informational, `dev @ 474fe3f682`)

The same AST rule applied to `ask_stream()` (open-question triage, §8) finds three providers whose
`ask()` runs the loop but whose `ask_stream()` does not. This feature changes none of them and
adds no streaming flag; each is a ledger issue.

| Provider | `ask_stream()` behaviour | Ledger |
|---|---|---|
| `GroqClient` | sends tools with `tool_choice="auto"` but reads only `delta.content`; tool calls dropped, answer can be empty (`groq/client.py:797-838`) | `issue:3e76568cae48` (bug, major) |
| `GrokClient` | `has_tools=False`; tools never sent (`grok/client.py:417-558`, `:451`) | `issue:2d16e4d75557` (bug, minor) |
| `MetaClient` | default `use_responses=True` path streams text only; Chat Completions path runs the loop (`meta/client.py:887-892`) | `issue:3a0ea22ce45a` (feature_gap, minor) |

The AST rule reports Meta's `ask_stream()` as `yes` because the Chat Completions branch reaches the
loop — a per-instance setting (`use_responses`) that no class attribute can express.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractClient.supports_tool_loop` | subclasses | class attribute lookup | `base.py:322` (insertion point) |
| `require_tool_loop()` | `PageIndexToolkit._agentic_client()` | call before `return` | `toolkit.py:1145-1153` |
| `require_tool_loop()` | `AgenticRetriever.__init__` | first statement | `agentic.py:163-174` |
| guard test | `LLMFactory.supported_clients()` | enumeration | `test_credential_env.py:12-19` |
| `AbstractBot._warn_if_client_lacks_tool_loop()` | `AbstractBot.configure()` | call after the `sync_tools` if-block | `abstract.py:1693-1694` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractClient.supports_tool_loop`~~, ~~`supports_tools`~~, ~~`has_tool_loop`~~ — nothing of the kind exists today (`grep -n supports_ base.py` → none).
- ~~`AbstractClient.capabilities`~~ / ~~`client_capabilities`~~ — no capability object; the only declarative attributes are `credential_env`, `budget_supported_methods`, `client_type`, `client_name`, `use_session`.
- ~~`parrot.clients.protocols.ToolLoopCapable`~~ — only `VoiceCapable` exists (`protocols.py:17`); this spec adds no Protocol.
- ~~`AgenticRetriever.require_tool_loop`~~ — the helper is module-level in `agentic.py`, not a method.
- ~~`StopReason` value `"unsupported_client"`~~ — not added; the fail-fast path raises instead.
- ~~`supports_stream_tool_loop`~~ / any `ask_stream()` capability attribute — not added (§8); streaming gaps are ledger issues.
- ~~`AbstractBot.supports_tool_loop`~~ — the bot has no flag of its own; it reads `self._llm.supports_tool_loop`.
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
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `self.sync_tools(self._llm)` (warning call added after this if-block, at the `if` indentation) | `abstract.py:1694` (verified `474fe3f682`) | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `def is_agent_mode(self) -> bool:` (helper inserted before) | `abstract.py:3704` (verified `474fe3f682`) | 1 |
| `packages/ai-parrot/tests/bots/test_tool_loop_warning.py` | CREATE | — | — | — |
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
  missing source as no executable evidence, reporting the unresolved method in assertion diagnostics.
  Parse dedented source with `ast.parse`; method names in comments or strings never count.
  Provider enumeration must skip only confirmed absent optional dependencies, not arbitrary loader
  exceptions; an installed provider's import or audit failure must fail AC-5 visibly.
- Satellite tests are not touched; everything lives in `packages/ai-parrot/tests` and skips when a
  satellite is not installed (the enumeration drops uninstalled extras, `test_credential_env.py:16-18`).
- Bot warning: `self.logger.warning` with `%`-style arguments (no f-string), one call per real
  `configure()` run; check `supports_tool_loop is False` before reading any bot attribute.

### Known Risks / Gotchas
- **The AST audit remains structural, not proof of runtime execution.** A provider that renames
  its loop helper requires updating `TOOL_EXECUTION_METHODS` after checking behavior. Conditions
  can disable otherwise reachable calls; the flag describes capability, not per-call activation.
  Exception membership must be backed by an exposure test (Codex: existing `test_codex_agent.py:129`;
  Claude: this feature). Future allowlist growth requires a documented bridge and an equivalent test.
- **Agent bridges**: `expose_parrot_tools` and exposure filters can prevent registered tools from
  being offered — still `True` for the class flag (the client *can* run the loop). Neither bridge
  registers inline `tools` passed to `ask()`. Preserve PageIndex's manager-registration path and
  configure exposure explicitly in bridge tests.
- **Streaming diverges today**: Grok ignores tools in `ask_stream()`; Groq sends them but drops the
  tool calls; Meta's default Responses streaming path does not run tool round trips. This flag must
  never be used to infer streaming capability. No streaming implementation change belongs to this
  feature; the three fixes are ledger issues (§6 Streaming audit).
- **Bot warning scope**: only the default client created in `configure()` is checked. A per-call
  client override and the `ModelSwitchingMixin` secondary client are not. Every hf/jev `Agent`
  gets the warning because `Agent` registers `ToJsonTool` by default; that is correct, not noise.
  The warning must stay a log line: refusing would break every existing hf/jev `Agent`.
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
    statement: AbstractClient declares text ask() tool-loop capability through supports_tool_loop (default True), assuming provider-supported tool registration and enabling; ask() never reads it. Providers without that loop set False. The flag makes no claim about streaming or inline tools registration; Codex and Claude agent bridges expose registered ToolManager tools. No separate ask_stream() capability flag is declared; providers whose ask_stream() skips the loop their ask() runs (Groq, Grok, Meta on the Responses path) are defects fixed in the provider and tracked as ledger issues.
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
      - "A separate supports_stream_tool_loop flag — only three providers diverge and BaseBot.ask_stream already passes use_tools, so fixing them removes the need; a class attribute also cannot describe MetaClient, whose streaming path depends on the per-instance use_responses setting."
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
  - id: bot-warns-on-no-tool-loop-client
    statement: AbstractBot.configure() logs one warning, and never raises, when the bot is in agent mode and its default LLM client declares supports_tool_loop False. The check reads the flag with an identity test against False before touching any bot state.
    relation: requires
    about: [bots]
    targets:
      - file:packages/ai-parrot/src/parrot/bots/abstract.py
    contradicts: []
    supersedes: []
    rationale: "TransformersClient drops a bot's tools with no log (the bot passes them through tool_manager, hf only warns on inline tools=); operators need one visible signal without breaking existing agents."
    rejected_alternatives:
      - "Refusing with ValueError at configure — breaks every existing hf/jev Agent, since Agent always registers ToJsonTool."
      - "Warning on every ask() — JevClient already does so per call; once per configure is enough."
```

## Consequences

<!-- decision-audit: input_digest=sha256:e7f03f7320757d6476c8c6456d6105f1ec09f11e58ce91dd1a8b815aeabb58ee evaluation_digest=sha256:44d3f846758c517a2da47bb39ab9f535f672bff85a38bc7ca24baa7b648fdf9a rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, knowledge-pageindex
- Unmapped tags: agentic-retrieval, capability, tool-loop
- Targets resolved: 4/4
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
      "bots",
      "clients",
      "knowledge-pageindex"
    ],
    "targets_resolved": 4,
    "targets_total": 4,
    "unmapped_tags": [
      "agentic-retrieval",
      "capability",
      "tool-loop"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:44d3f846758c517a2da47bb39ab9f535f672bff85a38bc7ca24baa7b648fdf9a",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:e7f03f7320757d6476c8c6456d6105f1ec09f11e58ce91dd1a8b815aeabb58ee",
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
    "structural_revision": "sha256:8884be97d7d460a4ba13ab682d409b5b0ce4191dbe664c3cc8c1415e2e01475a",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Which providers really lack a tool loop? — *Resolved in this spec (§6 audit)*: `TransformersClient`,
  `JevClient`, `GeminiLiveClient`; `OpenAICodexClient` and `ClaudeAgentClient` use agent bridges.
  FEAT-843's list of seven was
  a grep artefact (inherited `OpenAIBaseClient.ask`).
- [x] Flag or Protocol? — *Resolved*: class attribute `supports_tool_loop: bool = True` (precedent
  `budget_supported_methods`).
- [x] Fail fast how? — *Resolved*: `ValueError` naming class and `client_type`, at
  `PageIndexToolkit._agentic_client()` and `AgenticRetriever.__init__`; `StopReason` unchanged.
- [x] Feature ID — *Resolved*: the ledger issued FEAT-847 first, but `sdd-agy-compatibility.spec.md`
  already carries a hand-assigned FEAT-847 (never reserved). This spec takes the second reservation,
  FEAT-848, so no two specs share an ID; the ledger's FEAT-847 row therefore covers the agy spec under
  the wrong label (cosmetic — `existing-feature-id` resolves by spec, not by ledger label).
- [x] Should `AbstractBot`/`Agent` warn (or refuse) when a `False` client is configured with tools,
  instead of silently running prompt-only? — *Resolved (Jesus Lara, 2026-11-09)*: warn, never refuse,
  and do it in this feature (G6, §3 M5, AC-8). One `logger.warning` per real `configure()` run when the
  bot is in agent mode and its client declares `False`. The premise holds: `TransformersClient`
  drops a bot's tools with no log, because the bot hands them over through `tool_manager` with
  `use_tools=True` and hf only warns on inline `tools=`. Refusing was rejected: `Agent` always
  registers `ToJsonTool`, so every existing hf/jev `Agent` would fail to start.
- [x] Does this flag cover `ask_stream()`? — *Resolved in review*: no; Grok and Meta (and Groq, found in the 0.4 audit) already
  diverge. All contracts, documentation and guard assertions in this feature cover text `ask()` only.
- [x] Should `ask_stream()` gain a separate capability flag and provider audit? — *Resolved (Jesus Lara,
  2026-11-09)*: no flag. The audit (§6 Streaming audit) found three providers whose `ask_stream()`
  skips the loop their `ask()` runs: Groq (newly found — tool calls are dropped and the answer can
  come back empty), Grok and Meta's Responses path. They are fixed in the providers, not declared:
  `issue:3e76568cae48` (Groq), `issue:2d16e4d75557` (Grok), `issue:3a0ea22ce45a` (Meta). A class
  attribute could not describe Meta anyway, since its streaming path depends on the per-instance
  `use_responses` setting.

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
    a Gotcha for `False` clients, including the `AbstractBot.configure()` warning and the absence of
    a streaming flag.
  - `wiki/knowledge/pageindex-agentic-retrieval.md` — update: corrected provider table, fail-fast
    behaviour, `no_tool_calls` semantics.
- **API modules**:
  - `parrot.clients.base`

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara | Initial draft from FEAT-843 §8 escalation; MRO audit corrects the provider list. |
| 0.2 | 2026-11-09 | Codex | Apply review findings: ask-only capability, AST call evidence with both bridge exceptions, mocked bridge delivery tests, and explicit tool-registration prerequisites. |
| 0.3 | 2026-11-09 | Jesus Lara | Triage of 0.2: every code claim verified (CONFIRM ask-only scope, AST rule, Claude bridge exception); AST rule prototyped over all installed providers — classification confirmed; bridge *delivery* tests trimmed to one Claude *exposure* test (Codex already covered; execution is the bridges' contract); generated Governing Decisions / Consequences re-rendered (gate pass). |
| 0.4 | 2026-11-09 | Jesus Lara | Open questions closed. Bot warning folded in as G6 / M5 / AC-8 (warn once at `configure()`, never refuse). No streaming flag: an `ask_stream()` audit found Groq, Grok and Meta (Responses) gaps, filed as ledger issues `3e76568cae48`, `2d16e4d75557`, `3a0ea22ce45a`; Groq added to every streaming note. Decisions gain `bot-warns-on-no-tool-loop-client`; `tool-loop-flag-is-declarative` now records "no streaming flag"; generated sections re-rendered. |
