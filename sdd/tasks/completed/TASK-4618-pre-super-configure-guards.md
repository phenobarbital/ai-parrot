# TASK-4618: Guard the three pre-super `configure()` override sites

**Feature**: FEAT-726 — Configure-Override Idempotency & `speech_report` Hardening
**Spec**: `sdd/specs/bots-agent-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4617
**Assigned-to**: unassigned

**Discovered-from**: `issue:81fa838a18c1`

---

## Context

Implements spec §3 Module 3 — the second half of the fix for
`issue:81fa838a18c1`.

Three `AbstractBot` descendants do their own setup **BEFORE**
`await super().configure(app)`. The base's own guard cannot help them: by the
time `super()` decides to no-op, the subclass body has already run. And
`configure_skipped` (TASK-4616) is no help either, because it is only meaningful
*after* the `super()` call.

| Site | Repeat-call effect |
|---|---|
| `bots/chatbot.py:134-158` (`Chatbot`) | a second `from_database()` DB round-trip, or a second `from_manual_config()` |
| `bots/voice.py:394-400` (`VoiceBot`) | **`setup_a2a(app, url)` re-registers aiohttp routes** on the same app |
| `bots/database/agent.py:197-331` (`DatabaseAgent`) | re-starts toolkit pools and re-runs prefix/collision validation |

These read the other signal TASK-4616 published: `configure_is_noop(app)`, a
**sync** predicate that answers "would `configure(app)` be a no-op right now?"
before the first `await`.

Note the deliberate shape: the guard still calls `await super().configure(app)`
on the no-op path. That keeps the entry counter and the INFO log truthful — the
call really did happen, it just did no work.

---

## Scope

- Add the pre-super guard to `Chatbot.configure`, `VoiceBot.configure` and
  `DatabaseAgent.configure`.
- Append the Module 3 tests to
  `packages/ai-parrot/tests/bots/test_configure_override_guards.py`.

**NOT in scope**:
- Post-super sites — TASK-4617.
- **`bots/data.py`, `bots/mixins/narrative.py`,
  `bots/mixins/infographic_authoring.py`: assessed and deliberately exempt.**
  Do NOT guard them. Their evidence is in spec §1's "Assessed and deliberately
  left unguarded" table:
  - `data.py:876-889` — pre-super work self-gates on
    `if self._queries and not self.dataframes` (`:881`);
    `_sync_dataframes_from_dm()` is a pure re-sync.
  - `mixins/narrative.py:51-52` — pure cooperative passthrough, no own work.
  - `mixins/infographic_authoring.py:109-118` — pre-super `set_bot()` is
    **verified** idempotent: `_inject_prompt_guidance` returns early on the
    sentinel `"## Infographic Generation Mode" in tmpl`
    (`tools/infographic_toolkit.py:437-447`).
- `bots/mixins/identity.py:49` — inside a **docstring**, not code.
- Normalizing `bots/data.py`'s extra `queries` parameter
  (`data.py:864-868`). Leave that signature alone.
- Refactoring the large `DatabaseAgent.configure` body. Only the guard is added.
- `docs/agent-configure-lifecycle.md` — TASK-4621.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | `Chatbot.configure` pre-super guard |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | `VoiceBot.configure` pre-super guard |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | `DatabaseAgent.configure` pre-super guard |
| `packages/ai-parrot/tests/bots/test_configure_override_guards.py` | MODIFY | append Module 3 tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `36b9847aa`. Every anchor re-confirmed `grep -c` = 1.

### Verified Imports

No new imports. `configure_is_noop` is inherited from `AbstractBot`
(`bots/abstract.py:201`) via `BaseBot` (`bots/base.py:91`, which does **not**
override `configure`).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — added by TASK-4616 (must be "done" first)
    def configure_is_noop(self, app=None) -> bool: ...    # plain def, NOT async

# packages/ai-parrot/src/parrot/bots/chatbot.py:33
class Chatbot(BaseBot):
    async def configure(self, app=None) -> None:          # line 132
        """Load configuration for this Chatbot."""        # line 133  <-- anchor
        # own work :134-158 — from_database() / from_manual_config()
        # super() LAST, at :160

# packages/ai-parrot/src/parrot/bots/voice.py
class VoiceBot(A2AEnabledMixin, BaseBot):
    async def configure(self, app=None) -> None:          # line 391
        # own work :394-400 — memory_type default, then setup_a2a(app, url)
        url = getattr(self, "url", None)                  # line 398  <-- anchor
        # super() LAST, at :401

# packages/ai-parrot/src/parrot/bots/database/agent.py
class DatabaseAgent(BasicAgent):
    async def configure(self, app: Any = None) -> None:   # line 197
        # long docstring :198-226; own work follows; super() LAST at :331
        await super().configure(app=app)                  # line 331  <-- anchor
```

### Does NOT Exist

- ~~`await self.configure_is_noop(app)`~~ — it is a plain `def`, not a
  coroutine. Awaiting it raises `TypeError`. TASK-4616 ships
  `test_configure_is_noop_is_sync` precisely to pin this.
- ~~`AbstractBot.configure_skipped` as the pre-super signal~~ — it only becomes
  meaningful *after* `super().configure()` returns, which is too late here. Use
  `configure_is_noop(app)`.
- ~~`configure_count > 1` as the guard~~ — wrong on the CLI-then-server path.
- ~~`BaseBot.configure`~~ — `BaseBot` does not override `configure`; `Chatbot`'s
  `super().configure(app)` reaches `AbstractBot.configure` directly.
- ~~a pre-super site in `bots/mixins/identity.py`~~ — the `:49` match is inside
  the `IdentityMixin` class docstring.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/chatbot.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/voice.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/database/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_configure_override_guards.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_is_noop",
    "sym:packages/ai-parrot/src/parrot/bots/chatbot.py#Chatbot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/database/agent.py#DatabaseAgent.configure"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

```python
async def configure(self, app=None) -> None:
    if self.configure_is_noop(app):
        await super().configure(app)   # keeps the counter + INFO log truthful
        return
    ...  # existing pre-super body, unchanged
    await super().configure(app)       # existing trailing call, unchanged
```

### Key Constraints

- **The guard goes at the very top of the method, before the first side
  effect** — not merely before the `super()` call. In `DatabaseAgent.configure`
  the body spans `:197-331`; a guard placed near the bottom would let every
  toolkit pool restart first and defeat the point.
- **Still call `super().configure(app)` on the no-op path.** Returning without
  it would skip the counter increment and the INFO log, and would leave
  `configure_count` under-counting — which `configure_is_noop` itself reads.
  This is the one place the pattern looks redundant and is not.
- **Match each site's existing call convention.** `DatabaseAgent` calls
  `await super().configure(app=app)` (keyword); `Chatbot` and `VoiceBot` call
  `await super().configure(app)` (positional). Use each file's existing form on
  the no-op path too.
- Do NOT `await` `configure_is_noop`.
- Do not reorder or reformat the existing bodies; the diff adds only the guard.
- `ruff check --fix` on each touched file; 120-column lines.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/abstract.py:1575-1610` — the no-op
  condition `configure_is_noop` mirrors
- `packages/ai-parrot/src/parrot/bots/data.py:876-889` — the shape of an
  *already idempotent* pre-super body (exempt; read it to see why)
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:437-447` — the
  sentinel-header idempotency that exempts the infographic mixin

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4617 is `done` and `AbstractBot.configure_is_noop` exists —
   *why*: this task reads it, and TASK-4617 also appends to the shared test
   file, so running out of order causes a merge conflict in that file.
2. Read each of the three `configure` bodies in full before editing — *why*:
   `DatabaseAgent.configure` is ~130 lines and the guard must precede *all* of
   it, which you cannot judge from an anchor alone.
3. Insert each guard at the top of its method — *why*: it is the whole fix for
   the pre-super half.
4. Append the Module 3 tests — *why*: `setup_a2a` re-registration is the failure
   most likely to reach production, and only a test pins it.

### `packages/ai-parrot/src/parrot/bots/chatbot.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        """Load configuration for this Chatbot."""' packages/ai-parrot/src/parrot/bots/chatbot.py)
# AFTER — insert below `        """Load configuration for this Chatbot."""` (verified: chatbot.py:133)
        if self.configure_is_noop(app):
            await super().configure(app)
            return
```

**Why**: `Chatbot`'s own work (`:134-158`) is a database round-trip plus
attribute assignment, all of it ahead of the `super()` call at `:160`. The guard
immediately after the docstring is the first statement in the method, so nothing
runs twice. The trailing `await super().configure(app)` at `:160` stays as it is.

### `packages/ai-parrot/src/parrot/bots/voice.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        url = getattr(self, "url", None)' packages/ai-parrot/src/parrot/bots/voice.py)
# The guard goes at the TOP of VoiceBot.configure (voice.py:391), i.e. below its
# docstring and ABOVE the `memory_type` default block at :394-397 — NOT at the
# `url = ...` anchor (:398), which is already mid-body.
        if self.configure_is_noop(app):
            await super().configure(app)
            return
```

```python
# FILL IN: read voice.py:391-401 and place the guard immediately after the
# method docstring, above the first statement of the body (the
# `if not self.memory_type or self.memory_type == "memory":` block). The `url`
# anchor above is given only to locate the method — bounded by "the guard
# precedes every side effect, setup_a2a included" (AC: setup_a2a called once).
```

**Why**: `setup_a2a(app, url)` at `:400` is the dangerous statement — re-adding
aiohttp routes to the same app. But the `memory_type` default above it is also
part of the body, so the guard belongs above both, not just above `setup_a2a`.

### `packages/ai-parrot/src/parrot/bots/database/agent.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        await super().configure(app=app)' packages/ai-parrot/src/parrot/bots/database/agent.py)
# The anchor above is the method's LAST line (:331). The guard goes at the TOP of
# DatabaseAgent.configure (:197), below its docstring (:198-226) and above the
# first statement of the body.
        if self.configure_is_noop(app):
            await super().configure(app=app)
            return
```

```python
# FILL IN: read database/agent.py:197-331 in full, then place the guard
# immediately after the closing `"""` of the docstring and above the first
# executable statement. Note this site calls super() with the KEYWORD form
# (`app=app`) — use that form in the guard too — bounded by "no toolkit pool is
# started twice" (AC: pre-super guard precedes every side effect).
```

**Why**: this body creates cache partitions, starts toolkits, and runs the
FEAT-172 prefix/collision validation before reaching `super()` at `:331`.
Re-running it re-opens asyncdb pools. The docstring is long, so the insertion
point must be found by reading, not by anchoring on the last line.

### `packages/ai-parrot/tests/bots/test_configure_override_guards.py` (MODIFY)

```python
# APPEND at end of file (after TASK-4617's appended tests)


@pytest.mark.asyncio
async def test_pre_super_work_skipped_on_repeat_configure() -> None:
    """A pre-super override body runs ONCE across two configure() calls."""
    # FILL IN: stub subclass whose configure() does
    #   if self.configure_is_noop(app): await super().configure(app); return
    #   self.calls += 1; await super().configure(app)
    # configure twice with the same app; assert calls == 1
    # — bounded by AC "chatbot.py, voice.py and database/agent.py consult configure_is_noop"


@pytest.mark.asyncio
async def test_pre_super_noop_path_still_increments_counter() -> None:
    """The no-op path still enters super(), so the counter and log stay truthful."""
    # FILL IN: after two configures on the stub, assert configure_count == 2
    # — bounded by AC "still enter super().configure(app) on the no-op path"


@pytest.mark.asyncio
async def test_pre_super_work_runs_when_app_arrives_later() -> None:
    """CLI-then-server: the pre-super body DOES run when an app arrives."""
    # FILL IN: configure() with no app, then configure(app); assert calls == 2
    # — bounded by AC "the CLI-then-server path still runs every override's own work"


@pytest.mark.asyncio
async def test_voice_setup_a2a_called_once_across_two_configures(monkeypatch) -> None:
    """VoiceBot must not re-register A2A routes on a repeat configure."""
    # FILL IN: build a VoiceBot with `url` set, monkeypatch setup_a2a to count calls,
    # configure twice with the same app; assert one call
    # — bounded by AC "A second configure() ... registers no duplicate ... agent"


@pytest.mark.asyncio
async def test_chatbot_from_database_not_reloaded_on_repeat_configure(monkeypatch) -> None:
    """Chatbot must not make a second from_database() round-trip."""
    # FILL IN: Chatbot with _from_database True, monkeypatch bot_exists/from_database
    # to count calls, configure twice; assert one call. Keep it offline — no real DB.
    # — bounded by AC "no second DB round-trip"
```

**Why**: the first three pin the mechanism with an offline stub (including the
counter-still-increments property, which is the subtle part of this pattern);
the last two pin the two real sites. All offline — no aiohttp server, no
database.

### FILL IN checklist

- [ ] `voice.py` — exact insertion point at the top of `VoiceBot.configure`, above the `memory_type` block; bounded by AC "`setup_a2a` called once"
- [ ] `database/agent.py` — exact insertion point after the `:198-226` docstring, above the first statement; keyword `app=app` form; bounded by AC "no toolkit pool started twice"
- [ ] `test_configure_override_guards.py::test_pre_super_work_skipped_on_repeat_configure` — stub subclass; bounded by AC "three sites consult `configure_is_noop`"
- [ ] `test_configure_override_guards.py::test_pre_super_noop_path_still_increments_counter` — counter assertion; bounded by AC "still enter `super()` on the no-op path"
- [ ] `test_configure_override_guards.py::test_pre_super_work_runs_when_app_arrives_later` — CLI-then-server; bounded by AC "CLI-then-server still runs"
- [ ] `test_configure_override_guards.py::test_voice_setup_a2a_called_once_across_two_configures` — monkeypatched `setup_a2a`; bounded by AC "no duplicate registration"
- [ ] `test_configure_override_guards.py::test_chatbot_from_database_not_reloaded_on_repeat_configure` — monkeypatched DB access; bounded by AC "no second DB round-trip"

---

## Acceptance Criteria

- [ ] `Chatbot.configure`, `VoiceBot.configure` and `DatabaseAgent.configure`
      each consult `self.configure_is_noop(app)` as the **first statement** of
      the method body (after the docstring), before any side effect.
- [ ] Each guard still calls `super().configure(...)` on the no-op path, using
      that site's existing call convention (`app=app` for `DatabaseAgent`,
      positional for the other two), so `configure_count` still increments and
      the INFO log still fires.
- [ ] `configure_is_noop` is called, never awaited.
- [ ] `bots/data.py`, `bots/mixins/narrative.py`,
      `bots/mixins/infographic_authoring.py` and `bots/mixins/identity.py` are
      **unmodified** by this task.
- [ ] A repeat `configure()` makes no second `from_database()` round-trip, no
      second `setup_a2a()` call, and starts no toolkit pool twice.
- [ ] The CLI-then-server path still runs all three bodies.
- [ ] Each override's own body is otherwise byte-identical.
- [ ] The five appended tests pass.
- [ ] `ruff check` clean on all four touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_configure_override_guards.py -q`
- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`

> `tests/interfaces/test_configure_applies_tooling.py` was dropped from this list:
> it is red on `dev` independently of this feature
> (`AbstractBot.__new__(AbstractBot)` on a class with unimplemented abstract
> methods), filed as `issue:487531e66e0b`.

---

## Test Specification

See the Implementation Blueprint's MODIFY block for
`test_configure_override_guards.py`. Run inside the worktree with
`PYTHONPATH=packages/ai-parrot/src`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug bots-agent-tech-debt --feature-id FEAT-726`)
2. **Read the spec** at `sdd/specs/bots-agent-tech-debt.spec.md` (§1 for the
   pre-super table AND the exemptions table, §3 Module 3)
3. **Check dependencies** — TASK-4617 must be `"done"` in
   `sdd/tasks/index/bots-agent-tech-debt.json` (it appends to the same test file)
4. **Verify the Codebase Contract** — re-run each `grep -c`, and read each
   `configure` body in full before choosing the insertion point
5. **Update status** in `sdd/tasks/index/bots-agent-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the four files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4618 bots-agent-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

All three sites guarded with `if self.configure_is_noop(app): await
super().configure(...); return` as the first statement after the docstring —
above every side effect, not merely above the `super()` call. `DatabaseAgent`
uses its existing keyword form (`app=app`) on the no-op path.

The MRO chain was checked end to end, because `Chatbot` sits between
`AbstractBot` and `BasicAgent` and both now guard. On a repeat entry
`Chatbot.configure` short-circuits, awaits `AbstractBot.configure` (which sets
`_configure_skipped = True` and returns), and returns; back in
`BasicAgent.configure` the post-super guard from TASK-4617 then sees
`configure_skipped is True` and returns. On the CLI-then-server path both
guards correctly fall through. Covered by the behavioural tests.

Tests: four behavioural (repeat / counter-still-moves / CLI-then-server /
reconfigure) on a `_PreSuperBot` stub, plus a parametrized structural check
over the three real sites asserting the guard precedes every `super()` call,
is not awaited, and that its branch awaits `super()` and then returns.

Three pre-existing failures found in `voice.py`'s neighbourhood and NOT fixed
(out of scope, verified unrelated):
`test_voicebot_provider_switch.py::TestVoiceBotLazyClientWiring::test_resolve_branches_on_provider`,
`::test_create_branches_on_provider` and
`test_voicebot_refinements.py::TestVoiceBotVoiceCapableCheck::test_both_provider_branches_still_present`.
They assert on the AST source of `_resolve_llm_config` / `_create_llm_client`,
not `configure`. Verified pre-existing by reverting `voice.py` to the base
commit and re-running them — identical failures. Also 4 pre-existing ruff
findings in `voice.py` (unused imports at :33/:42/:932, unused local at :692);
`chatbot.py` and `database/agent.py` are ruff-clean.

Validation: `pytest tests/bots/test_configure_override_guards.py
tests/bots/test_double_configure.py -q` -> **39 passed**. The wider sweep
(voice + database + guards) was **300 passed, 9 skipped, 3 failed** — the three
pre-existing voice failures above.
