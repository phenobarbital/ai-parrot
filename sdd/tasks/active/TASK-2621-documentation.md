# TASK-2621: Document the telemetry planes and delivery rules

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2611, TASK-2612, TASK-2613, TASK-2614, TASK-2615, TASK-2616, TASK-2617, TASK-2618, TASK-2619, TASK-2620
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 8.

This feature exists because two pieces of knowledge weren't written down where
anyone would find them:

1. **Which registry you subscribe to determines whether your data is exact.**
   `emit()` awaits; `emit_nowait()` and `forward_to_global()` do not. Nothing
   in the codebase says this in one place, so the next person wiring a
   subscriber will get it wrong the same way.
2. **A usage pipeline already existed** in `observability/recorders/`. This
   spec's own first two drafts proposed rebuilding it, because
   `ls observability/subscribers/` looked like the whole story. The same
   mistake is waiting for the next author.

Documenting these is the durable deliverable — the code fixes this instance,
the docs prevent the next one.

---

## Scope

- Document the **three planes** (live UI / accounting / observability), what
  question each answers, and which substrate owns it.
- Document the **delivery-semantics rule** as a table: which emission paths are
  awaited-exact and which are fire-and-forget, and the consequence for
  anything that must be complete at run close.
- Document **how to add a usage sink** (implement `AbstractLogger`, register it
  through `UsageRecordingSubscriber` — not a new subscriber).
- Document **seat attribution**: what a seat is, why it is a free string rather
  than a `NodeId`, and how `usage_attribution()` is used.
- Note the FEAT-405 R4 override with a pointer to spec §3 Module 3.
- Save durable findings to the LLM wiki (see below).

**NOT in scope**: rewriting the existing `observability/README.md` privacy
contract; documenting OTel setup (already covered).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/telemetry-accounting.md` | CREATE | The main document |
| `docs/dev_loop/` index or README | MODIFY | Link the new page, if an index exists |
| `packages/ai-parrot/src/parrot/observability/recorders/__init__.py` | MODIFY | Add `run_ledger` to the package docstring listing |

---

## Codebase Contract (Anti-Hallucination)

### Facts to document (all verified during this feature)

```python
# DELIVERY SEMANTICS — navigator_eventbus/lifecycle/registry.py
async def emit(event)            # line 235  AWAITED, sequential, never raises
def emit_nowait(event)           # line 366  loop.create_task -> fire-and-forget
def forward_to_global(event)     # line 392  loop.create_task -> fire-and-forget
# Subscriber errors isolate into SubscriberErrorEvent (lines 267-273).
# After*/*Failed* events dispatch in REVERSE registration order (line 260).

# clients/base.py
_emit_after_call  -> await self.events.emit(event)   # line 630  EXACT
_emit_round_event -> self.events.emit_nowait(event)  # line 582  BEST-EFFORT
# Client registries are isolated (forward_to_global=False) and forward
# explicitly at lines 634 / 587.

# THE EXISTING USAGE PIPELINE
recorders/subscriber.py:30   UsageRecordingSubscriber (EventProvider, sync register at :63)
recorders/models.py:22       UsageRecord  (privacy contract in docstring lines 8-11)
recorders/base.py:16         AbstractLogger  (record() :31, aclose() :39)  <-- extension point
recorders/logging_recorder.py:17 / openlit_recorder.py:25 / prometheus_recorder.py:84
observability/bootstrap.py:129,138  the GLOBAL registration

# NODE EVENTS
bots/flows/flow/telemetry.py:48   FlowLifecycleAdapter (uses emit_nowait at :93)
bots/flows/flow/flow.py:400       add_node_event_listener (sync or async)
bots/flows/flow/flow.py:452       _drain_event_tasks — the end-of-run barrier
bots/flows/flow/flow.py:2074      where it is awaited, before run_flow returns

# ATTRIBUTION
observability/context.py:42,46,50  current_agent_name / user_id / session_id (FEAT-228)
observability/context.py:55,83     agent_identity / invocation_context
```

### Does NOT Exist (worth documenting AS not existing)

- ~~`parrot.observability.subscribers.usage`~~ — the usage pipeline is under
  `recorders/`, not `subscribers/`. **This is the single most useful sentence
  in the document**: it is the exact wrong turn this spec's first two drafts
  took.
- ~~`AgentsFlow.drain_node_events()`~~ — the public-sounding name does not
  exist; the real method is `_drain_event_tasks` and it is already wired.
- ~~`DispatchState.model`~~ — session state carries no model identity; that is
  why the report reads the ledger.

---

## Implementation Notes

### Lead with the delivery table

```markdown
| Path | Delivery | Safe for accounting? |
|---|---|---|
| `await registry.emit(e)` on the emitting registry | awaited, sequential | ✅ yes |
| `registry.emit_nowait(e)` | `loop.create_task` | ❌ no |
| `registry.forward_to_global(e)` | `loop.create_task` | ❌ no |

**Rule**: if your subscriber's data must be complete at a known point,
subscribe it on the registry that *emits*, not on the global registry.
```

That table is the thing worth reading. Put it near the top, not in an appendix.

### Explain *why*, not just what

The three planes make sense only with the failure they prevent. State it
plainly: one overwritten `DispatchState` field was serving three different
questions, so retries clobbered totals, pool workers vanished, and dev-flow
went dark. Then the split is obvious rather than arbitrary.

### Wiki entries (required)

Per `CLAUDE.md`, save the durable cross-file facts:

```bash
wikitoolkit remember "The dev-loop/dev-flow usage pipeline lives in \
parrot/observability/recorders/ (UsageRecordingSubscriber + UsageRecord + \
AbstractLogger sinks), NOT in observability/subscribers/ (which holds only \
trace.py and metrics.py). Add a usage consumer by implementing AbstractLogger \
and registering it through UsageRecordingSubscriber — never by writing a second \
subscriber." --category lesson --title "Usage pipeline lives in recorders/, not subscribers/"

wikitoolkit remember "EventRegistry.emit() awaits subscribers sequentially and \
is exact; emit_nowait() and forward_to_global() both schedule via \
loop.create_task and are fire-and-forget. Anything that must be complete at run \
close must be subscribed on the registry that EMITS, not on the global registry." \
  --category concept --title "Lifecycle bus delivery semantics"
```

### Key Constraints

- Every code reference carries a `file:line`. Stale docs are worse than none.
- Write for the next implementer, not as a feature changelog.
- Do not restate the spec — link to it for rationale, especially the FEAT-405
  R4 override in §3 Module 3.

### References in Codebase

- `packages/ai-parrot/src/parrot/observability/README.md` — the privacy contract to cross-reference
- `docs/dev_loop/nova-backend.md` — tone and structure precedent for this directory

---

## Acceptance Criteria

- [ ] `docs/dev_loop/telemetry-accounting.md` exists and covers: the three
      planes, the delivery-semantics table, how to add a sink, and seat
      attribution.
- [ ] The delivery table names all three paths with their real `file:line`.
- [ ] The document states explicitly that the usage pipeline is under
      `recorders/`, not `subscribers/`.
- [ ] The FEAT-405 R4 override is noted with a pointer to spec §3 Module 3.
- [ ] Every code reference includes a file path and line number, spot-checked
      against the tree at writing time.
- [ ] Linked from the `docs/dev_loop/` index if one exists.
- [ ] `recorders/__init__.py`'s docstring lists `run_ledger`.
- [ ] Both `wikitoolkit remember` entries are saved (verify with
      `wikitoolkit memories`).
- [ ] No stale reference to `RunUsageSubscriber` or
      `observability/subscribers/usage.py` anywhere in the new doc.

---

## Test Specification

Documentation task — no unit tests. Verify by:

```bash
# every file:line reference resolves
grep -oE '[a-z_/]+\.py:[0-9]+' docs/dev_loop/telemetry-accounting.md | sort -u
# ^ spot-check each against the tree

# no stale references to the withdrawn design
! grep -qE 'RunUsageSubscriber|subscribers/usage\.py' docs/dev_loop/telemetry-accounting.md

# wiki entries saved
wikitoolkit memories | grep -i "recorders\|delivery semantics"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** in full — this task documents its conclusions
2. **Check dependencies** — all other FEAT-479 tasks must be in
   `sdd/tasks/completed/`; read their Completion Notes, since the §8
   open-question answers recorded there belong in the docs
3. **Verify the Codebase Contract** — re-check every line number as you write
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2621-documentation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
