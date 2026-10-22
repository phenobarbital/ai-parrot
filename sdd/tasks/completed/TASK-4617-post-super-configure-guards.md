# TASK-4617: Guard the nine post-super `configure()` override sites

**Feature**: FEAT-726 — Configure-Override Idempotency & `speech_report` Hardening
**Spec**: `sdd/specs/bots-agent-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4616
**Assigned-to**: unassigned

**Discovered-from**: `issue:81fa838a18c1`

---

## Context

Implements spec §3 Module 2 — the main fix for `issue:81fa838a18c1`.

Nine `AbstractBot` descendants do their own setup AFTER
`await super().configure(app)`. When the base no-ops (a repeat `configure()`
with an unchanged app), that setup still runs. The consequences are not
cosmetic:

| Site | Repeat-call effect |
|---|---|
| `bots/agent.py:191-193` (`BasicAgent`) | re-wires tool namespaces, **re-starts the task-memory runtime**, re-adopts task memory |
| `bots/fireflies_insights.py:153-160` (`FirefliesInsightsAgent`) | re-loads the skill registry, re-reads wiki config, re-`mkdir`s the inbox |
| `agents/obsidian.py:276-285` (`FirefliesObsidianAgent`) | **re-registers `ObsidianToolkit` tools**, re-inits Fireflies MCP, re-backfills the meeting registry |
| `bots/chrome.py:351-362` (`WebAgent`) | **re-adds the Chrome DevTools MCP server** |
| `bots/flows/agents/orchestrator.py:113-115` (`OrchestratorAgent`) | **re-registers every specialist agent** |
| `bots/flows/agents/a2a_orchestrator.py:275-280` (`A2AOrchestratorAgent`) | **re-registers `ListAvailableA2AAgentsTool`** (name-collision risk) and re-connects endpoints |
| `bots/a2a_agent.py:19` (`A2AAgent`) | **re-registers A2A routes** — and this override is wired as an aiohttp middleware (`a2a_agent.py:14`), so repeat entry is the normal case |
| `parrot_tools/computer/agent.py:135-139` (`ComputerAgent`) | re-attaches the computer-use safety handler |
| `bots/document.py:253` (`DocumentAgent`) | emits a duplicate "configured" log line |

TASK-4616 published the base's decision as `configure_skipped`. This task reads
it at all nine sites.

---

## Scope

- Insert `if self.configure_skipped:` / `return` immediately after the existing
  `await super().configure(...)` call in each of the nine files listed above.
- Append the Module 2 tests to
  `packages/ai-parrot/tests/bots/test_configure_override_guards.py` (created by
  TASK-4616).

**NOT in scope**:
- Pre-super sites (`chatbot.py`, `voice.py`, `database/agent.py`) — TASK-4618.
- `bots/data.py`, `bots/mixins/narrative.py`,
  `bots/mixins/infographic_authoring.py` — assessed and deliberately exempt;
  see spec §1's "Assessed and deliberately left unguarded" table. Do NOT touch
  them.
- `bots/mixins/identity.py:49` — that `async def configure` is inside a
  **docstring**, not code. Do NOT edit it.
- The `speech_report` changes in `agent.py` — TASK-4619 (it depends on this task
  because it edits the same file).
- Rewriting `docs/agent-configure-lifecycle.md` — TASK-4621.
- Any change to `post_configure()` bodies. FEAT-721 settled their re-entrancy
  (adopt via `find_registered_toolkit`); do not revisit it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `BasicAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | `FirefliesInsightsAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | MODIFY | `FirefliesObsidianAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/bots/chrome.py` | MODIFY | `WebAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/bots/document.py` | MODIFY | `DocumentAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` | MODIFY | `OrchestratorAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py` | MODIFY | `A2AOrchestratorAgent.configure` post-super guard |
| `packages/ai-parrot/src/parrot/bots/a2a_agent.py` | MODIFY | `A2AAgent.configure` post-super guard |
| `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` | MODIFY | `ComputerAgent.configure` post-super guard |
| `packages/ai-parrot/tests/bots/test_configure_override_guards.py` | MODIFY | append Module 2 tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `36b9847aa`. Every anchor re-confirmed `grep -c` = 1.

### Verified Imports

No new imports. `configure_skipped` is an inherited property — every class below
is an `AbstractBot` descendant through the verified MRO chain:

```
AbstractBot (bots/abstract.py:201)
  → BaseBot (bots/base.py:91 — does NOT override configure)
    → Chatbot (bots/chatbot.py:33)
      → BasicAgent (bots/agent.py)
        → Agent (bots/agent.py:1562 — does NOT override configure)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — added by TASK-4616 (must be "done" first)
    @property
    def configure_skipped(self) -> bool: ...

# The nine override signatures, verbatim (do NOT change any of them):
# packages/ai-parrot/src/parrot/bots/agent.py:179
class BasicAgent(Chatbot, NotificationMixin):
    async def configure(self, app=None) -> None:          # super() at :188, own work :189-193

# packages/ai-parrot/src/parrot/bots/fireflies_insights.py:150
class FirefliesInsightsAgent(SkillRegistryMixin, Agent):
    async def configure(self, app=None) -> None:          # super() at :152, own work :153-160

# packages/ai-parrot/src/parrot/agents/obsidian.py:264
class FirefliesObsidianAgent(BasicAgent):
    async def configure(self, app=None) -> None:          # super() at :273, own work :276-285+

# packages/ai-parrot/src/parrot/bots/chrome.py:338
class WebAgent(BasicAgent):
    async def configure(self, app=None) -> None:          # super() at :350, own work :351-362+

# packages/ai-parrot/src/parrot/bots/document.py:245
class DocumentAgent(BasicAgent):
    async def configure(self, app=None) -> None:          # super() at :252, own work :253

# packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py:110
class OrchestratorAgent(BasicAgent):
    async def configure(self, app=None) -> None:          # super() at :112, own work :113-115

# packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py:264
class A2AOrchestratorAgent(A2AClientMixin, OrchestratorAgent):
    async def configure(self, app=None) -> None:          # super() at :272, own work :275-280+

# packages/ai-parrot/src/parrot/bots/a2a_agent.py:16
class A2AAgent(BasicAgent, A2AEnabledMixin):
    async def configure(self):                            # NOTE: no `app` parameter. super() at :18, own work :19

# packages/ai-parrot-tools/src/parrot_tools/computer/agent.py:127
class ComputerAgent(Agent):
    async def configure(self, app: Any = None) -> None:   # super() at :134, own work :135-139+
```

### Does NOT Exist

- ~~`ObsidianAgent`~~ — the class in `agents/obsidian.py` is
  **`FirefliesObsidianAgent`**. The ledger issue's prose says `ObsidianAgent`;
  that name does not exist.
- ~~`ChromeAgent`~~ — the class in `bots/chrome.py` is **`WebAgent`**.
- ~~`AbstractBot.configure_count > 1` as the correct guard~~ — it is `2` on the
  CLI-then-server path where the pipeline genuinely ran. Use
  `configure_skipped`. The old `docs/agent-configure-lifecycle.md` §6 and the
  pre-TASK-4616 docstring both prescribe the wrong thing; ignore them.
- ~~`BaseBot.configure`~~ / ~~`Agent.configure`~~ — neither overrides
  `configure`. There is nothing to guard in `bots/base.py` or at
  `bots/agent.py:1562`.
- ~~a `configure()` override in `bots/mixins/identity.py`~~ — the match at
  `:49` is inside the `IdentityMixin` class docstring's usage example.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/agents/obsidian.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/chrome.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/document.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/a2a_agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/computer/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_configure_override_guards.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_skipped",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/fireflies_insights.py#FirefliesInsightsAgent.configure",
    "sym:packages/ai-parrot/src/parrot/agents/obsidian.py#FirefliesObsidianAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/chrome.py#WebAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/document.py#DocumentAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py#OrchestratorAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py#A2AOrchestratorAgent.configure",
    "sym:packages/ai-parrot/src/parrot/bots/a2a_agent.py#A2AAgent.configure",
    "sym:packages/ai-parrot-tools/src/parrot_tools/computer/agent.py#ComputerAgent.configure"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Every one of the nine edits is the same two lines, inserted directly after the
existing `super()` call:

```python
async def configure(self, app=None) -> None:
    await super().configure(app)
    if self.configure_skipped:
        return
    ...  # existing body, unchanged
```

### Key Constraints

- **Two inserted lines per file and nothing else.** Do not reformat, reorder,
  or "improve" the surrounding bodies. This task's diff should be ~18 added
  lines of code plus the tests.
- **Insert after the `super()` call, before the first own statement.** In
  several files there is a blank line or a comment between them (`obsidian.py`
  has a blank line at `:274` then a `# ---` comment at `:275`); the guard goes
  immediately after the `await super().configure(...)` line, above that blank
  line.
- **`a2a_agent.py` has no `app` parameter** — its signature is
  `async def configure(self)` and it calls `await super().configure()`. The
  guard is identical; do NOT add an `app` parameter while you are in there.
- **`computer/agent.py` lives in a different distribution**
  (`packages/ai-parrot-tools/src/`). Its tests need
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
- Do not use `configure_count > 1`. See the "Does NOT Exist" entry.
- `ruff check --fix` on each touched file; 120-column lines.

### References in Codebase

- `docs/agent-configure-lifecycle.md` §6 — **currently prescribes the wrong
  recipe**; TASK-4621 fixes it. Follow this task file, not that doc.
- `packages/ai-parrot/tests/bots/test_double_configure.py` — FEAT-721 helpers
- `packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py` — the
  shape of an existing re-entrancy test

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4616 is `done` in the per-spec index and that
   `AbstractBot.configure_skipped` exists — *why*: every edit here reads that
   property; without it all nine sites raise `AttributeError`.
2. For each of the nine files, re-run the `grep -c` in its block below — *why*:
   nine files across two distributions is the most likely place for anchor
   drift, and a wrong insert point silently disables an agent's setup.
3. Insert the two-line guard at each site — *why*: it is the whole fix for
   `issue:81fa838a18c1`'s post-super half.
4. Append the Module 2 tests — *why*: a guard with no test is indistinguishable
   from a guard inserted in the wrong place.
5. Run the Validation Commands with the two-entry `PYTHONPATH` — *why*: one of
   the nine files is in `ai-parrot-tools`, which is not on the default path.

### The nine MODIFY blocks

Each block is the same insert. The anchor named in each is the **first own
statement after** `await super().configure(...)`; insert the guard directly
**above** that anchor (and above any blank line or comment that precedes it).

```python
# AFTER each `await super().configure(...)` line, insert verbatim:
        if self.configure_skipped:
            return
```

| File | Anchor to insert ABOVE | occurrences (verified `grep -c`) | super() line |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | `        if self._llm is not None:` | 1 (verified at `agent.py:189`) | `:188` |
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | `        await self._configure_skill_file_registry()` | 1 | `:152` |
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | `        self._initialize_tools([self.obsidian_toolkit])` | 1 | `:273` |
| `packages/ai-parrot/src/parrot/bots/chrome.py` | `        config = self.chrome_config` | 1 | `:350` |
| `packages/ai-parrot/src/parrot/bots/document.py` | `        self.logger.info(f"DocumentAgent '{self.name}' configured with {len(self.tools)} tools")` | 1 | `:252` |
| `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` | `        for name in self._pending_agent_names:` | 1 | `:112` |
| `packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py` | `        self._discovery_tool = ListAvailableA2AAgentsTool(self)` | 1 | `:272` |
| `packages/ai-parrot/src/parrot/bots/a2a_agent.py` | `        self.setup_a2a(self.app, self.url)` | 1 | `:18` |
| `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` | `        client = getattr(self, "_llm", None)` | 1 | `:134` |

All nine anchors were occurrence-verified at `36b9847aa`; re-run each `grep -c`
before inserting. If any returns `> 1`, disambiguate by quoting 2-3 lines of
context (e.g. for `agent.py` the sequence `await super().configure(app)` /
`if self._llm is not None:` / `self.client = self._llm` is unique to
`BasicAgent.configure`, `agent.py:188-190`). A count of `0` means the anchor is
gone — stop and report the drift rather than inventing an attachment point.

**Why this shape**: the guard must sit between the `super()` call and the first
own side effect. Putting it before the `super()` call would skip the base
pipeline entirely and break every bot; putting it after the first own statement
would leave that statement running twice. The anchors above are the first own
statement at each site, so "insert above the anchor" is exactly the right
position.

### `packages/ai-parrot/tests/bots/test_configure_override_guards.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_configure_is_noop_is_sync' packages/ai-parrot/tests/bots/test_configure_override_guards.py)
# APPEND at end of file (created by TASK-4616; insert below its last test)


@pytest.mark.asyncio
async def test_post_super_work_skipped_on_repeat_configure() -> None:
    """A post-super override body runs ONCE across two configure() calls.

    Uses a local stub subclass with a counter, not a real agent — the nine real
    sites all share this one mechanism and a stub keeps the test offline.
    """
    # FILL IN: define a stub subclass whose configure() does
    #   await super().configure(app); if self.configure_skipped: return; self.calls += 1
    # configure twice with the same app, assert calls == 1
    # — bounded by AC "All 9 post-super override sites return early on configure_skipped"


@pytest.mark.asyncio
async def test_post_super_work_runs_when_app_arrives_later() -> None:
    """The same body DOES run on a genuine reconfiguration (CLI-then-server).

    This is the regression a `configure_count > 1` guard would introduce.
    """
    # FILL IN: configure() with no app, then configure(app); assert calls == 2
    # — bounded by AC "the CLI-then-server path still runs every override's own work"


@pytest.mark.asyncio
async def test_a2a_agent_setup_a2a_called_once_across_two_configures() -> None:
    """A2AAgent.configure is wired as middleware, so repeat entry is normal.

    Its setup_a2a must not re-register routes on the second entry.
    """
    # FILL IN: build an A2AAgent with a stubbed setup_a2a (monkeypatch) and a fake app;
    # call configure() twice; assert setup_a2a was called once
    # — bounded by AC "A second configure() ... registers no duplicate ... MCP server/agent"


@pytest.mark.asyncio
async def test_orchestrator_specialist_agents_registered_once() -> None:
    """OrchestratorAgent must not re-register its specialists on a repeat configure."""
    # FILL IN: stub add_agent_by_name / register_specialist_agents and count calls
    # across two configures with the same app
    # — bounded by AC "registers no duplicate toolkit/tool/MCP server/agent"
```

**Why**: the first two tests pin the mechanism with an offline stub; the last two
pin the two sites whose repeat-run is most likely to raise in production
(duplicate aiohttp routes, duplicate agent/tool registration). Keep them offline
— no real Chrome, no real Fireflies MCP, no network.

### FILL IN checklist

- [ ] `test_configure_override_guards.py::test_post_super_work_skipped_on_repeat_configure` — stub subclass + assertion; bounded by AC "9 sites return early"
- [ ] `test_configure_override_guards.py::test_post_super_work_runs_when_app_arrives_later` — CLI-then-server assertion; bounded by AC "CLI-then-server still runs"
- [ ] `test_configure_override_guards.py::test_a2a_agent_setup_a2a_called_once_across_two_configures` — monkeypatched `setup_a2a`; bounded by AC "no duplicate registration"
- [ ] `test_configure_override_guards.py::test_orchestrator_specialist_agents_registered_once` — stubbed registration counters; bounded by AC "no duplicate registration"

---

## Acceptance Criteria

- [ ] All nine files have `if self.configure_skipped: return` immediately after
      their `await super().configure(...)` call and before their first own
      statement.
- [ ] No file uses `configure_count > 1` as the guard.
- [ ] `a2a_agent.py`'s signature is still `async def configure(self)` — no `app`
      parameter added.
- [ ] `bots/data.py`, `bots/mixins/narrative.py`,
      `bots/mixins/infographic_authoring.py` and `bots/mixins/identity.py` are
      **unmodified** by this task.
- [ ] Each override's own body is otherwise byte-identical — the diff adds only
      the guard lines.
- [ ] A second `configure()` with an unchanged app registers no duplicate
      toolkit, tool, MCP server or specialist agent, and starts no second
      runtime.
- [ ] The CLI-then-server path still runs every override's own work.
- [ ] The four appended tests pass.
- [ ] `ruff check` clean on all ten touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_configure_override_guards.py -q`
- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`
- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`
- `pytest packages/ai-parrot/tests/tools/test_toolkit_reregistration.py -q`

> `tests/interfaces/test_configure_applies_tooling.py` was dropped from this list:
> it is red on `dev` independently of this feature
> (`AbstractBot.__new__(AbstractBot)` on a class with unimplemented abstract
> methods), filed as `issue:487531e66e0b`.

---

## Test Specification

See the Implementation Blueprint's MODIFY block for
`test_configure_override_guards.py`. Run inside the worktree with
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` — two entries,
because this task touches both distributions.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug bots-agent-tech-debt --feature-id FEAT-726`)
2. **Read the spec** at `sdd/specs/bots-agent-tech-debt.spec.md` (§1 for the
   per-site effects, §3 Module 2, §6 Edit Sites)
3. **Check dependencies** — TASK-4616 must be `"done"` in
   `sdd/tasks/index/bots-agent-tech-debt.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` in the table above;
   nine files is where drift hides
5. **Update status** in `sdd/tasks/index/bots-agent-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the ten files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4617 bots-agent-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

All nine sites guarded with the two-line `if self.configure_skipped: return`
immediately after their `super().configure(...)` call; the diff is exactly 18
added lines of source plus tests, no reformatting.

Tests took a different shape than the blueprint sketched, for a reason worth
recording. Behaviourally mocking nine real agents (Chrome DevTools MCP,
Fireflies MCP, A2A routes, specialist-agent registration) would have meant nine
fragile mock stacks testing one shared two-line mechanism. Instead:

* three behavioural tests on a stub subclass cover the mechanism itself —
  repeat configure, CLI-then-server, and `reconfigure()`;
* one parametrized test covers all nine real sites **structurally**: the guard
  must directly follow `super().configure(...)`, and `configure_count > 1` must
  not appear in the method. That is precisely the AC ("grep finds no post-super
  site left unguarded") and it catches the thing that actually regresses — a new
  or edited override losing its guard;
* one parametrized test pins the three assessed exemptions (`PandasAgent`,
  `NarrativeMixin`, `InfographicAuthoringMixin`) as deliberately **unguarded**,
  so someone "completing" the fix trips a test that points at
  docs/agent-configure-lifecycle.md §8.

Two pre-existing problems found and NOT fixed here (both out of scope,
both recorded):

1. `tests/interfaces/test_configure_applies_tooling.py::test_configure_calls_apply_tooling_specs_once`
   is red on `dev`: `AbstractBot.__new__(AbstractBot)` cannot work for a class
   with unimplemented abstract methods. Verified pre-existing by re-running it
   with this feature's `abstract.py` change reverted — identical failure. Filed
   as `issue:487531e66e0b` and removed from this feature's validation contract
   (spec §4 records why); it was inherited from FEAT-721's list.
2. `ruff check` reports 10 findings across these files (bare `except` in
   obsidian.py/document.py, unused imports in a2a_orchestrator.py, PIE790/B905
   in orchestrator.py). Verified pre-existing by running ruff on the base
   versions: the same 10 findings appear, two lines earlier. Left untouched per
   the minimal-diff rule. The AC's "ruff clean" therefore holds for the lines
   this task adds, not for the files as a whole.

Validation: `pytest tests/bots/test_configure_override_guards.py
tests/bots/test_double_configure.py tests/bots/test_fireflies_insights.py
tests/bots/test_jira_specialist_reconfigure.py
tests/tools/test_toolkit_reregistration.py -q` → **74 passed**.
