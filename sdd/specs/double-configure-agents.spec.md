---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [tools, agents, lifecycle, idempotency, toolkits]
---

# Feature Specification: Double-`configure()` Is Not a Crash

**Feature ID**: FEAT-721
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Calling `configure()` twice on the *same* bot instance corrupts the agent.
Found while bringing up two or more agents in parallel in one process; the
defect is **upstream of any particular wiring** — it belongs to the
double-`configure()` path itself, and every agent whose `post_configure()`
registers a toolkit shares it, `ParrotReviewer` (`GitHubReviewer`) included.

The mechanism, verified against `c3f8b5ded`:

1. `AbstractBot.configure()` ends by awaiting `post_configure()`
   (`abstract.py:1727`), and its `finally` always flips `_configured = True`
   (`abstract.py:1765`) — even when the body raised.
2. Subclass `post_configure()` bodies **build a fresh toolkit instance and
   register it unconditionally**: `FirefliesInsightsAgent` constructs a new
   `WorkingMemoryToolkit` on every call (`fireflies_insights.py:165`),
   `GitHubReviewer` a new `GitToolkit` + `JiraToolkit`
   (`github_reviewer.py:989-995`), `JiraSpecialist` a new `JiraToolkit` +
   `ReminderToolkit` (`jira_specialist.py:443`, `:487`).
3. `ToolManager.register_tool()` treats *any* second claim on a tool name
   from a **prefixed** toolkit as a hard error (`manager.py:891`), because
   namespacing is supposed to make names unique per toolkit.

So the second `configure()` splits into two failure shapes, both wrong:

| Toolkit | `tool_prefix` | Second registration |
|---|---|---|
| `WorkingMemoryToolkit` (`working_memory/tool.py:81`) | `"wm"` | **raises `ToolNameCollisionError`** |
| `ReminderToolkit` (`tools/reminder.py:177`) | `"reminder"` | **raises `ToolNameCollisionError`** |
| `GitToolkit`, `JiraToolkit` | none | warn-and-skip → **silent split-brain** |

Reproduced verbatim (`WorkingMemoryToolkit`, two instances, one manager):

```
first: 13 tools
RAISED ToolNameCollisionError: Tool name collision: 'wm_compute_and_store'
is already registered by another toolkit. Pick a different `tool_prefix`
or rename the method.
```

The blast radius is worse than one exception:

- **Fireflies-shaped agents crash the caller.** `post_configure()` errors are
  logged and re-raised by `configure()` (`abstract.py:1728-1733`), so the
  second `configure()` propagates — while `finally` has already marked the
  bot `is_configured`. The agent is advertised as ready and is not.
- **Reviewer-shaped agents fail silently.** `_attach_toolkit()` swallows the
  exception (`github_reviewer.py:1267`) and `register_toolkit()` skips
  unprefixed collisions, so `self.git_toolkit` / `self.jira_toolkit` end up
  pointing at **brand-new, authenticated, unregistered** toolkits while the
  manager still serves the *first* instance's tools. The LLM calls one
  object, the agent's own code touches another.
- **Everything else in `configure()` runs twice too**: a second LLM client, a
  second embeddings/store warm-up, a second `AgentConfiguredEvent`.

The repo already fixed this twice, locally and by hand — `apply_tooling_specs`
guards itself with `_tooling_applied` (`interfaces/tools.py:228`) and
`_configure_episodic_memory` bails when `ep_*` is already registered
(`memory/episodic/mixin.py:181-205`, with this exact crash described in its
docstring). Those two precedents prove the hazard is structural; a third
hand-rolled guard per agent is not the fix.

### Goals

- A second `configure()` on the same instance must never raise and never
  leave an agent half-wired, for **any** agent — including third-party
  subclasses nobody edits.
- Re-registering an already-registered toolkit is a no-op, not a collision.
- A genuine collision — two *different* toolkits claiming one tool name —
  keeps raising `ToolNameCollisionError` exactly as today.
- Deliberate reconfiguration stays possible through one explicit, documented
  entry point.
- An agent attribute (`self.working_memory`, `self.git_toolkit`, …) always
  names the toolkit the `ToolManager` actually serves.

### Non-Goals (explicitly out of scope)

- Concurrency safety: two coroutines calling `configure()` on one instance at
  the same time. The guard is a plain flag, not a lock; parallel agent
  *startup* means one `configure()` per instance, concurrently across
  instances, which is unaffected.
- Reworking `_configured` / `is_configured` semantics (callers across
  `BotManager` gate on it; `configure()`'s `finally` contract stays).
- Hot-reload and per-user clone paths — they already build a **fresh**
  instance (`manager.py:1114`, `JiraSpecialist.clone_for_user`) and are
  correct today.
- Making `tool_prefix` mandatory (an existing, separate migration).

---

## 2. Architectural Design

### Overview

Three layers, outermost first, each one a backstop for the next.

**M1 — `ToolManager` keeps the first registration.** `register_toolkit()`
resolves the candidate's **class and prefix before constructing anything**;
when a toolkit of the same exact class and the same `tool_prefix` is already
registered, it returns that owner's already-registered tools and mutates
nothing. This is the load-bearing fix: it makes every `post_configure()` in
the repo — and every third-party one — idempotent with respect to toolkit
registration, without those bodies changing. Cross-owner collisions (a
different class claiming the same name) still raise. Two instances of one
class under *different* prefixes still both register.

Keep-first (not replace) was chosen deliberately: a displaced toolkit may
hold an open pool or session, and `cleanup_toolkits()` (`manager.py:2867`)
discovers toolkits only through the registered tools, so replacing would
leak the old instance's resources for the life of the process.

**M2 — `AbstractBot.configure()` is idempotent.** An entry counter plus one
rule: re-entry with the *same* app short-circuits; re-entry with a
*different* app is a genuine reconfiguration and runs the pipeline (M1 keeps
that safe). This stops the duplicate LLM client, store warm-up and
`AgentConfiguredEvent`, and stops `post_configure()` from being called a
second time at all. `reconfigure()` is the explicit escape hatch.

**M3 — the three concrete `post_configure()` bodies adopt instead of
rebuild.** Because M1 keeps the first registration, an agent that assigns a
*new* instance to its own attribute would otherwise point at a toolkit the
manager does not serve. Each body now asks the manager for the live instance
first (`find_registered_toolkit`) and only constructs when there is none —
which also stops a second authenticated Git/Jira client from being built.

### Component Diagram

```
caller ──→ AbstractBot.configure(app)
               │
               ├─ [M2] entry guard: count > 1 and app unchanged ──→ return
               │
               ├─ apply_tooling_specs()      (already guarded: _tooling_applied)
               ├─ LLM / store / KB / prompt
               └─ post_configure()           ← subclass
                        │
                        ├─ [M3] find_registered_toolkit(cls) or build
                        └─ tool_manager.register_toolkit(toolkit)
                                   │
                                   └─ [M1] same class + same prefix already
                                           registered?
                                             yes → return existing tools
                                             no  → register (collision still
                                                   raises for a foreign owner)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ToolManager.register_toolkit` | modifies | Early keep-first return before the instance is built (`manager.py:1190`) |
| `get_toolkit_owner` | uses | Owner discovery for the lookup helper (`manager.py:53`) |
| `ToolManager.cleanup_toolkits` | unchanged | Keep-first means no displaced owner to close (`manager.py:2867`) |
| `ToolManager._bind_compression_tee` | unchanged | Re-binds per `execute_tool()`; keep-first leaves the bound WM toolkit valid |
| `AbstractBot.configure` | modifies | Entry guard + counter (`abstract.py:1564`) |
| `AbstractBot.post_configure` | docs only | Contract note: a body may run once per *successful* configure (`abstract.py:1767`) |
| `apply_tooling_specs` | pattern source | `_tooling_applied` is the precedent M2 generalizes (`interfaces/tools.py:228`) |
| `FirefliesInsightsAgent.post_configure` | modifies | Adopt WM + Jira toolkits (`fireflies_insights.py:162`) |
| `GitHubReviewer.post_configure` | modifies | Adopt Git + Jira toolkits; de-duplicate `self.tools` (`github_reviewer.py:956`) |
| `JiraSpecialist.post_configure` | modifies | Adopt Jira + Reminder toolkits (`jira_specialist.py:432`) |
| `BotManager` | unaffected | Every call site either gates on `is_configured` or configures a fresh instance |

### Data Models

No new Pydantic models. Two new pieces of instance state:

```python
# ToolManager — none (the lookup is a scan over the existing self._tools)

# AbstractBot
self._configure_count: int = 0   # entries into configure(), reset by reconfigure()
```

### New Public Interfaces

```python
class ToolManager:
    def find_registered_toolkit(
        self,
        toolkit_cls: type["AbstractToolkit"],
        *,
        tool_prefix: str | None = None,
    ) -> Optional["AbstractToolkit"]:
        ...


class AbstractBot:
    @property
    def configure_count(self) -> int:
        ...

    async def reconfigure(self, app=None) -> None:
        ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: ToolManager keep-first re-registration | yes | Match rule `type(owner) is cls and owner.tool_prefix == prefix`; detection before `build_toolkit`; return `self._registered_tools_of(owner)`; log DEBUG when `owner is candidate`, WARNING otherwise; foreign-owner collision untouched | — |
| M2: `configure()` idempotency | yes | `_configure_count` incremented at entry; short-circuit when `count > 1` **and** resolved app `is` the previously bound app; `reconfigure()` resets the counter to 0 then awaits `configure()` | — |
| M3: adopt-instead-of-rebuild in the three agents | yes | Each body calls `find_registered_toolkit(<cls>)` first and only builds on `None`; attribute assigned to whatever is registered; `self.tools` extended only with names not already present | — |
| M4: regression tests | yes | Files and cases enumerated in §4 | — |
| M5: lifecycle doc | yes | One new page, contents fixed in §7 | — |

### Module 1: ToolManager keep-first re-registration
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`
- **Responsibility**: Make re-registering an already-registered toolkit a
  no-op that returns the live tools, while keeping a foreign-owner name
  collision a hard `ToolNameCollisionError`.
- **Depends on**: existing `get_toolkit_owner` (`manager.py:53`),
  `AbstractToolkit.tool_prefix` (`toolkit.py:276`).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/tools/manager.py  (modifies manager.py:1190)

  def find_registered_toolkit(                      # new
      self,
      toolkit_cls: type["AbstractToolkit"],          # AbstractToolkit verified: tools/toolkit.py:225
      *,
      tool_prefix: str | None = None,
  ) -> Optional["AbstractToolkit"]:
      """Return the registered instance of ``toolkit_cls``, or ``None``.

      Matches on the EXACT class (never a subclass) and, when
      ``tool_prefix`` is given, on an equal ``tool_prefix`` — so the same
      toolkit class registered twice under two different prefixes stays
      two distinct registrations. Owners are discovered through
      ``get_toolkit_owner`` over ``self._tools``  # verified: manager.py:53
      """

  def _registered_tools_of(self, owner: "AbstractToolkit") -> List[AbstractTool]:
      """Return the tools in ``self._tools`` owned by ``owner``, registration order."""

  def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type], **kwargs) -> List[AbstractTool]:
      """Register all tools from a toolkit.  # verified: manager.py:1190

      Re-registration is a NO-OP that keeps the FIRST registration: when a
      toolkit of the same exact class and the same ``tool_prefix`` is
      already registered, the already-registered tools are returned and
      nothing is mutated — the candidate is not even constructed when it
      was passed as a name or a class, so no second pool/session is
      opened. A name claimed by a DIFFERENT owner still raises
      ``ToolNameCollisionError``  # verified: manager.py:891
      """
  ```

### Module 2: `AbstractBot.configure()` idempotency
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: Make a second `configure()` on one instance a logged
  no-op, keep an app arriving later a real reconfiguration, and expose the
  one explicit way to force a re-run.
- **Depends on**: Module 1 (a forced re-run re-enters `post_configure()`).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies abstract.py:1564)

  self._configure_count: int = 0   # __init__, beside self._configured  # verified: abstract.py:368

  async def configure(self, app=None) -> None:
      """Basic Configuration of Bot.  # verified: abstract.py:1564

      Idempotent per instance. The counter is incremented on entry; a
      second or later entry returns immediately (INFO log) when the
      resolved app is the SAME object as the one already bound —
      including both being ``None``. An app arriving where none was bound
      before (CLI first, server later) is a genuine reconfiguration and
      runs the pipeline; Module 1 makes the toolkit re-registration in
      that path safe.

      Subclass overrides that do their own work AFTER
      ``await super().configure(app)`` guard it with
      ``if self.configure_count > 1: return``.

      The ``finally`` contract is unchanged: ``_configured`` is always
      flipped to ``True``, so a failed configure is not retried blindly.
      """

  async def reconfigure(self, app=None) -> None:
      """Reset the idempotency counter and run :meth:`configure` again.

      The ONLY supported way to re-run the pipeline on a live instance.
      """

  @property
  def configure_count(self) -> int:
      """How many times :meth:`configure` has been entered on this instance."""

  async def post_configure(self) -> None:
      """Hook called at the end of :meth:`configure`.  # verified: abstract.py:1767

      Called once per configure() that actually runs its pipeline. An
      override MUST be safe to run more than once per instance: adopt an
      already-registered toolkit via
      ``self.tool_manager.find_registered_toolkit(...)`` instead of
      building a second one.
      """
  ```

### Module 3: Adopt-instead-of-rebuild in the three shipped agents
- **Path**: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py`,
  `packages/ai-parrot/src/parrot/bots/github_reviewer.py`,
  `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Keep each agent's own attribute pointing at the toolkit
  the `ToolManager` serves, and stop building a second authenticated client.
- **Depends on**: Module 1 (`find_registered_toolkit`).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/bots/fireflies_insights.py  (modifies fireflies_insights.py:162)
  async def post_configure(self) -> None:
      """Wire WorkingMemoryToolkit and JiraToolkit once self.app exists.

      Re-entrant: adopts the registered toolkits instead of constructing
      new ones, so ``self.working_memory`` is always the instance the
      manager serves (keep-first, Module 1).
      """

  # packages/ai-parrot/src/parrot/bots/github_reviewer.py  (modifies github_reviewer.py:956)
  async def post_configure(self) -> None:
      """Wire GitToolkit and JiraToolkit once self.app is attached.

      Re-entrant: ``_build_git_toolkit`` / ``_build_jira_toolkit`` are
      skipped when the manager already serves that toolkit, so a second
      pass opens no second authenticated client.
      """

  def _attach_toolkit(self, toolkit: Any, name: str) -> None:
      """Register ``toolkit`` and extend ``self.tools`` with its exports.  # verified: github_reviewer.py:1261

      Extends ``self.tools`` only with tools whose name is not already
      present, so a re-entrant post_configure cannot grow duplicates.
      """

  # packages/ai-parrot/src/parrot/bots/jira_specialist.py  (modifies jira_specialist.py:432)
  async def post_configure(self) -> None:
      """Wire the JiraToolkit and ReminderToolkit using app-scoped credentials.

      Re-entrant, same adoption rule; ``ReminderToolkit`` carries
      ``tool_prefix = "reminder"``  # verified: tools/reminder.py:177
      """
  ```

### Module 4: Regression tests
- **Path**: `packages/ai-parrot/tests/tools/test_toolkit_reregistration.py` (new),
  `packages/ai-parrot/tests/bots/test_double_configure.py` (new)
- **Responsibility**: Pin every rule in §5 — including the two that must NOT
  change (foreign-owner collision still raises; two prefixes still register
  twice).
- **Depends on**: Modules 1-3.
- **Interface Skeleton**: see §4.

### Module 5: Lifecycle documentation
- **Path**: `docs/agent-configure-lifecycle.md` (new)
- **Responsibility**: One page stating the configure/post_configure contract
  an agent author must satisfy, next to the existing
  `docs/bot-cleanup-lifecycle.md`.
- **Depends on**: Modules 1-3.
- **Interface Skeleton**: prose; contents fixed in §7 *Patterns to Follow*.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_reregistering_same_toolkit_keeps_first` | M1 | Two `WorkingMemoryToolkit` instances, one manager: no raise, `_tools` identity unchanged, the first instance still owns `wm_get_stored` |
| `test_reregistration_returns_registered_tools` | M1 | The second call returns the same tool objects the first call returned |
| `test_reregistration_by_class_does_not_construct` | M1 | Passing the class (not an instance) a second time returns early — `build_toolkit` is never called |
| `test_second_instance_logs_warning` | M1 | Distinct instance, same class+prefix → WARNING; identical object → DEBUG |
| `test_same_class_different_prefix_registers_twice` | M1 | Two instances with different `tool_prefix` both register (no keep-first) |
| `test_foreign_owner_collision_still_raises` | M1 | A different prefixed toolkit claiming an existing name still raises `ToolNameCollisionError` |
| `test_find_registered_toolkit_exact_class_only` | M1 | A subclass instance does not match the parent class lookup |
| `test_second_configure_is_noop` | M2 | `configure()` twice: `configure_count == 2`, `post_configure` awaited once |
| `test_configure_with_new_app_reruns` | M2 | `configure()` then `configure(app)` → pipeline runs again, no raise |
| `test_reconfigure_reruns_pipeline` | M2 | `reconfigure()` re-enters `post_configure` and does not raise |
| `test_failed_configure_still_marks_configured` | M2 | Existing `finally` contract unchanged |
| `test_fireflies_post_configure_twice_adopts` | M3 | Second `post_configure()` leaves `working_memory` identical to the registered owner, no raise |
| `test_github_reviewer_post_configure_twice_adopts` | M3 | `git_toolkit` / `jira_toolkit` unchanged, builders not called again, `self.tools` free of duplicates |
| `test_jira_specialist_post_configure_twice_adopts` | M3 | Jira + Reminder toolkits adopted, `reminder_*` registered exactly once |

### Integration Tests

| Test | Description |
|---|---|
| `test_two_agents_parallel_configure` | Two agent instances configured concurrently in one process each keep their own toolkits — the keep-first rule is per `ToolManager`, not global |
| `test_configure_twice_end_to_end` | A fireflies-shaped agent survives `configure()` → `configure()` with its working memory still callable |

### Validation Contract

tests:
- packages/ai-parrot/tests/tools/test_toolkit_reregistration.py
- packages/ai-parrot/tests/bots/test_double_configure.py
- packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py
- packages/ai-parrot/tests/bots/test_fireflies_insights.py
- packages/ai-parrot/tests/bots/test_github_reviewer.py
- packages/ai-parrot/tests/tools/test_toolkit_resolver.py
- packages/ai-parrot/tests/tools/test_auto_registration_hooks.py
- packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def manager():
    """A bare ToolManager (no search tool) for registration tests."""
    from parrot.tools.manager import ToolManager
    return ToolManager(include_search_tool=False)


@pytest.fixture
def wm_pair():
    """Two independent WorkingMemoryToolkit instances (tool_prefix='wm')."""
    from parrot.tools.working_memory import WorkingMemoryToolkit
    return WorkingMemoryToolkit(session_id="s1"), WorkingMemoryToolkit(session_id="s2")
```

`AbstractBot` tests follow the existing in-repo pattern of
`AbstractBot.__new__(AbstractBot)` plus explicit attribute stubbing — see
`packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py:11`
— and the fireflies tests reuse `_bare_agent()` from
`packages/ai-parrot/tests/bots/test_fireflies_insights.py:26`.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Registering a toolkit whose exact class **and** `tool_prefix` are
      already registered returns the already-registered tools, raises
      nothing, and leaves `ToolManager._tools` byte-identical.
- [ ] That early return happens **before** the candidate is constructed when
      the toolkit is passed as a name or a class, so no second pool, client
      or session is opened.
- [ ] A tool name claimed by a **different** owner still raises
      `ToolNameCollisionError` with the current message.
- [ ] Two instances of one toolkit class under **different** `tool_prefix`
      values both register, as today.
- [ ] `find_registered_toolkit()` matches the exact class only — a subclass
      instance does not satisfy a parent-class lookup.
- [ ] A keep-first skip of a *different* instance logs a WARNING naming the
      class and prefix; re-registering the *identical* object logs DEBUG.
- [ ] `await bot.configure(app); await bot.configure(app)` raises nothing,
      awaits `post_configure()` exactly once, and emits exactly one
      `AgentConfiguredEvent`.
- [ ] `await bot.configure(); await bot.configure(app)` (an app arriving
      later) **does** run the pipeline again and binds `self.app`.
- [ ] `bot.configure_count` reports entries into `configure()`;
      `reconfigure()` resets it and re-runs the pipeline without raising.
- [ ] `configure()` still flips `_configured`/`is_configured` to `True` in
      `finally`, including when the body raised (unchanged contract).
- [ ] Calling `post_configure()` twice on `FirefliesInsightsAgent`,
      `GitHubReviewer` and `JiraSpecialist` raises nothing, and each agent's
      toolkit attribute `is` the instance the `ToolManager` serves.
- [ ] `GitHubReviewer.self.tools` contains no duplicate tool names after two
      `post_configure()` passes, and the Git/Jira builders are not called a
      second time.
- [ ] `docs/agent-configure-lifecycle.md` documents the contract and
      `AbstractBot.post_configure`'s docstring points at it.
- [ ] No breaking change to any public signature: `register_toolkit`,
      `configure`, `post_configure` keep their current parameters.
- [ ] The §4 Validation Contract passes:
      `pytest packages/ai-parrot/tests/tools/test_toolkit_reregistration.py packages/ai-parrot/tests/bots/test_double_configure.py packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py packages/ai-parrot/tests/bots/test_fireflies_insights.py packages/ai-parrot/tests/bots/test_github_reviewer.py -q`
- [ ] `ruff check` clean on every touched file.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `c3f8b5ded` (2026-10-22).

### Verified Imports

```python
from parrot.tools.manager import ToolManager, ToolNameCollisionError, get_toolkit_owner  # verified: tools/manager.py:43, :53 (ToolManager: :289)
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool                            # verified: tools/toolkit.py:225, :37
from parrot.tools.working_memory import WorkingMemoryToolkit                             # verified: tools/working_memory/__init__.py:3,29
from parrot.tools.reminder import ReminderToolkit                                        # verified: tools/reminder.py:177 (tool_prefix)
from parrot.bots.abstract import AbstractBot                                             # verified: tests/interfaces/test_configure_applies_tooling.py:7
from parrot.bots.fireflies_insights import FirefliesInsightsAgent                        # verified: bots/fireflies_insights.py:101
from parrot.bots.github_reviewer import GitHubReviewer                                   # verified: bots/github_reviewer.py:495
from parrot_tools.jiratoolkit import JiraToolkit                                         # verified: bots/github_reviewer.py:86
from parrot_tools.gittoolkit import GitToolkit                                           # verified: bots/github_reviewer.py:79
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolNameCollisionError(ValueError): ...                                   # line 43
def get_toolkit_owner(tool: Any) -> Optional["AbstractToolkit"]: ...            # line 53 (module-level function, NOT a method)

class ToolManager:
    self._tools: Dict[str, Any]                                                 # name -> tool, the single registry
    self._wired_toolkits: set                                                   # line 363, auto-wire tracking (by id)
    self._compression_tee: CompressionTee                                       # line 377, re-bound per execute_tool()
    def add_tool(self, tool, name=None) -> None: ...                            # line 827 (overwrites, no collision check)
    def register_tool(self, tool=None, name=None, description=None,
                      input_schema=None, function=None) -> None: ...            # line 853
        #   line 881: `if tool_name in self._tools:`  → prefixed: raise (891); legacy: warn+return
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type],
                         **kwargs) -> List[AbstractTool]: ...                   # line 1190
        #   str  → ToolkitRegistry.get(name) then self.build_toolkit(...)
        #   type → self.build_toolkit(toolkit, self._slug_of_class(toolkit), kwargs)
        #   instance → used directly
        #   then: tools = toolkit_instance.get_tools_sync(); set_tool_manager(self);
        #         per-tool register_tool() with ToolNameCollisionError re-raised (line 1272)
    def build_toolkit(self, cls: type, slug: str, params: Dict[str, Any], *,
                      phase: Optional[str] = None) -> Any: ...                  # line 628
    def get_tool(self, tool_name: str) -> Optional[Any]: ...                    # line 1373
    def unregister_tool(self, tool_name: str) -> bool: ...                      # line 1415
    def remove_tool(self, tool_name: str) -> None: ...                          # line 1428
    def _find_working_memory_toolkit(self) -> Optional[Any]: ...                # line 2703 (WM-specific; M1's helper generalizes it)
    def _bind_compression_tee(self) -> None: ...                                # line 2724
    async def cleanup_toolkits(self) -> None: ...                               # line 2867 (discovers toolkits via self._tools)

# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):                                                # line 37
    self.bound_method: callable                                                 # line 55 (owner reachable via .__self__)
class AbstractToolkit:
    tool_prefix: str | None = None                                              # line 276 (CLASS attribute)
    prefix_separator: str = "_"                                                 # line 279
    def _resolve_tool_name(self, method_name: str) -> str: ...                  # line 554
    #   line 615: `tool._from_prefixed_toolkit = bool(self.tool_prefix)`  ← gates the hard raise
    def get_tools_sync(self) -> list: ...                                       # used at manager.py:1260

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):              # line 47
    tool_prefix: str = "wm"                                                     # line 81  → 13 tools, wm_*

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    self._configured: bool = False                                              # line 368
    async def configure(self, app=None) -> None: ...                            # line 1564
        #   1576: self._configured = False ; 1577: self.app = None  (app re-resolved from the arg)
        #   1588: await self.apply_tooling_specs()      (self-guarded, interfaces/tools.py:228)
        #   1727: await self.post_configure()           (errors logged AND re-raised, 1728-1733)
        #   1765: self._configured = True  in `finally` (always, even on failure)
    async def post_configure(self) -> None: ...                                 # line 1767 (base is a no-op `return None`)
    @property
    def is_configured(self) -> bool: ...                                        # line 1842

# packages/ai-parrot/src/parrot/interfaces/tools.py
async def apply_tooling_specs(self, *, tooling_policy=None, tooling_subject=None,
                              tooling_owner=None) -> list[str]: ...             # line 215
    #   228: `if getattr(self, "_tooling_applied", False): return []` ; 230 sets it  ← precedent

# packages/ai-parrot/src/parrot/memory/episodic/mixin.py
async def _configure_episodic_memory(self) -> None: ...                         # line 181
    #   docstring 181-205 describes THIS bug; guard = `_episodic_store is not None`
    #   or `tool_manager.get_tool("ep_get_warnings") is not None`                ← precedent

# packages/ai-parrot/src/parrot/bots/fireflies_insights.py
class FirefliesInsightsAgent(SkillRegistryMixin, Agent):                        # line 101
    self.working_memory: WorkingMemoryToolkit | None                            # line 144
    self.jira_toolkit: JiraToolkit | None                                       # line 145
    async def configure(self, app=None) -> None: ...                            # line 150 (awaits super() then its own work)
    async def post_configure(self) -> None: ...                                 # line 162
        #   165: self.working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-meetings")  ← unconditional
        #   167-169: for toolkit in (...): self.tool_manager.register_toolkit(toolkit)  ← untried, propagates
    def _build_jira_toolkit(self) -> JiraToolkit | None: ...                    # line 171

# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):                                                    # line 495
    async def post_configure(self) -> None: ...                                 # line 956
        #   989: self.git_toolkit = self._build_git_toolkit()
        #   992: self.jira_toolkit = self._build_jira_toolkit()
        #   994-995: self._attach_toolkit(self.git_toolkit, "Git") / (self.jira_toolkit, "Jira")
    async def _attach_webhook_listener(self) -> None: ...                       # line 1230 (ALREADY idempotent: `not in listeners`)
    def _attach_toolkit(self, toolkit: Any, name: str) -> None: ...             # line 1261 (swallows every Exception, then self.tools.extend)
    def _build_git_toolkit(self) -> Optional[GitToolkit]: ...                   # line 1281
    #   _wiki_toolkits_attached guard at line 1196 — the existing, correct pattern

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
    async def post_configure(self) -> None: ...                                 # line 432
        #   443: self.jira_toolkit = self._configure_jira()
        #   487: reminder_toolkit = ReminderToolkit(scheduler_manager=scheduler_manager)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ToolManager.find_registered_toolkit` | `get_toolkit_owner()` | module-level function over `self._tools` | `tools/manager.py:53` |
| `ToolManager.register_toolkit` keep-first | `ToolkitRegistry.get` / `build_toolkit` | class resolved before construction | `tools/manager.py:1190`, `:628` |
| keep-first match rule | `AbstractToolkit.tool_prefix` | class attribute read pre-build | `tools/toolkit.py:276` |
| `AbstractBot.configure` guard | `self._configure_count` | new attribute beside `_configured` | `bots/abstract.py:368` |
| `AbstractBot.reconfigure` | `AbstractBot.configure` | resets counter, awaits configure | `bots/abstract.py:1564` |
| M3 bodies | `ToolManager.find_registered_toolkit` | adopt-or-build | this spec, M1 |

### Does NOT Exist (Anti-Hallucination)

- ~~`ToolManager.unregister_toolkit()`~~ — only `unregister_tool(name)`
  (`manager.py:1415`) and `remove_tool(name)` (`:1428`) exist.
- ~~`ToolManager._toolkits` / `ToolManager._registered_toolkits`~~ — there is
  **no** toolkit registry; toolkits are discovered only through `self._tools`
  (that is why keep-first, not replace, is the chosen semantics).
- ~~`ToolManager.get_toolkit(name)`~~ / ~~`find_toolkit()`~~ — do not exist.
  `_find_working_memory_toolkit()` (`:2703`) is the only lookup and it is
  WorkingMemory-specific.
- ~~`AbstractBot._configure_completed`~~, ~~`AbstractBot._configure_count`~~,
  ~~`AbstractBot.reconfigure()`~~, ~~`AbstractBot.configure_count`~~ — all new
  in this feature.
- ~~`AbstractBot.configure(app, force=True)`~~ — `configure()` takes only
  `app`; do NOT add a keyword (20+ subclass overrides declare
  `configure(self, app=None)` without `**kwargs`, so a new keyword would
  `TypeError` through them). Force goes through `reconfigure()`.
- ~~`GitToolkit.tool_prefix`~~ / ~~`JiraToolkit.tool_prefix`~~ — neither
  declares one; their duplicate registration is the *silent* warn-and-skip
  path, not the raising one.
- ~~`AbstractToolkit.is_registered`~~ / ~~`AbstractToolkit.tool_manager`~~ as a
  registration flag — `set_tool_manager()` is called on registration
  (`manager.py:1264`) but is not a reliable "am I registered" signal.
- ~~`parrot/tools/__init__.py` exporting `get_toolkit_owner`~~ — import it
  from `parrot.tools.manager`.

### Edit Sites (Blueprint Anchors)

<!-- Verified against: c3f8b5ded -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type], **kwargs) -> List[AbstractTool]:` | `manager.py:1190` | 1 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `    def _find_working_memory_toolkit(self) -> Optional[Any]:` | `manager.py:2703` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        self._configured: bool = False` | `abstract.py:368` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `    async def configure(self, app=None) -> None:` | `abstract.py:1564` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `    async def post_configure(self) -> None:` | `abstract.py:1767` | 1 |
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | `    async def post_configure(self) -> None:` | `fireflies_insights.py:162` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `    async def post_configure(self) -> None:` | `github_reviewer.py:956` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `    def _attach_toolkit(self, toolkit: Any, name: str) -> None:` | `github_reviewer.py:1261` | 1 |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | `    async def post_configure(self) -> None:` | `jira_specialist.py:432` | 1 |
| `packages/ai-parrot/tests/tools/test_toolkit_reregistration.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/test_double_configure.py` | CREATE | — | — | — |
| `docs/agent-configure-lifecycle.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **The repo's own precedent is "guard the step, once per instance"**:
  `_tooling_applied` (`interfaces/tools.py:228`) and the `ep_*` probe
  (`memory/episodic/mixin.py:181`). M2 generalizes it; do not invent a new
  mechanism.
- `GitHubReviewer._wiki_toolkits_attached` (`github_reviewer.py:1196`) and
  `_attach_webhook_listener`'s `if self.handle_hook_event not in listeners`
  (`:1246`) are the in-file style for M3 — follow them.
- Keep-first must be decided **on the class**, before `build_toolkit()`.
  `tool_prefix` is a class attribute (`toolkit.py:276`), so the pre-build
  check reads `kwargs.get("tool_prefix", getattr(cls, "tool_prefix", None))`;
  for an instance it reads `toolkit.tool_prefix`.
- Logging is `self.logger` (`manager.py` uses `%s` style) — never `print`.
- `docs/agent-configure-lifecycle.md` must state, in this order: `configure()`
  is idempotent per instance; `reconfigure()` is the only way to force a
  re-run; `post_configure()` may run more than once per instance and must
  adopt, not rebuild; `find_registered_toolkit()` is how you adopt;
  keep-first means the manager wins, so never assume your fresh instance is
  the registered one.

### Known Risks / Gotchas

- **An app arriving after an app-less `configure()`.** A blanket
  "second call returns" would silently skip binding `self.app`, killing
  `GitHubReviewer`'s webhook listener. Hence the rule: short-circuit only
  when the resolved app `is` the already-bound one. Capture the previous app
  **before** `configure()` resets `self.app = None` (`abstract.py:1577`).
- **A failed first `configure()` cannot be retried by re-calling
  `configure()`** — the counter, like `_configured`, is set in `finally`.
  That matches today's behavior (`BotManager` gates on `is_configured`, which
  is already `True` after a failure); `reconfigure()` is the retry.
- **Keep-first makes M3 mandatory, not optional.** Without it an agent that
  builds a fresh toolkit keeps a reference the manager does not serve — the
  exact split-brain this feature is fixing. Any new agent must adopt.
- **`get_tools_sync()` has side effects** (`_generate_tools`): the early
  return must happen before it is called on the candidate.
- **Subclass `configure()` bodies still run their own post-`super()` work on a
  second call** — the base guard cannot stop code it does not own. M3's
  bodies are idempotent; `configure_count > 1` is the documented guard for
  anyone else.
- **Do not add a keyword to `configure()`**: 20+ overrides declare
  `configure(self, app=None)`.
- **The compression tee** re-binds on every `execute_tool()`
  (`manager.py:2724`), so keep-first leaves it pointed at a live toolkit —
  no extra work, but do not "helpfully" rebind it in `register_toolkit`.
- **Concurrency is out of scope**: the counter is not a lock. Two coroutines
  entering `configure()` on the *same* instance simultaneously can still both
  pass the guard; M1 keeps that from raising, which is the practical
  protection. Say so in the doc rather than implying a guarantee.

### External Dependencies

None. No new packages.

---

## 8. Open Questions

- [ ] Should a keep-first skip of a *different* instance be a WARNING forever,
      or become an error once `tool_prefix` is mandatory for all toolkits?
      — *Owner: Jesus Lara* (decide at the prefix-migration, not here)
- [ ] Do any out-of-tree agents (the gitignored `agents/` tree,
      `ParrotReviewer` among them) rely on `post_configure()` rebuilding a
      toolkit per call? A grep of the shipped packages says no.
      — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-721
  (`.claude/worktrees/feat-FEAT-721-double-configure-agents`, base
  `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree
  inside it.
- **Module dependency graph**:
  - M2 → M1 — `AbstractBot.reconfigure()` re-enters `post_configure()`, which
    is only safe once `register_toolkit` keeps the first registration
    (`manager.py:1190`).
  - M3 → M1 — the three bodies call `ToolManager.find_registered_toolkit()`,
    introduced by M1.
  - M4 → M1, M2, M3 — the regression tests assert all three behaviours.
  - M5 → M1, M2, M3 — the doc states the finished contract.
  - M1 has no inbound edge. M2 and M3 touch disjoint files
    (`bots/abstract.py` vs. the three agent modules) and are expected to run
    concurrently once M1 has merged.
- **Shared files**: none. M1 owns `tools/manager.py`, M2 owns
  `bots/abstract.py`, M3 owns the three agent modules, M4 the two new test
  files, M5 the new doc. No file is touched by two modules, so no task pair
  needs serializing on a shared file.
- **Exclusive resources**: none — no extension rebuild, no lockfile change,
  no migration. All tasks are `parallel: true` apart from the M1 edges above.
- **Cross-feature dependencies**: none. FEAT-721 bases on `dev` at
  `c3f8b5ded` and depends on no unmerged spec.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `n/a` · Status: skipped (no exploration
> document: this spec was written from inline notes, so §3b's precondition —
> an `accepted` brainstorm/proposal, or an intake run — was not met)
> · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.
