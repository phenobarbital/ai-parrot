# TASK-4621: Correct the configure-lifecycle documentation

**Feature**: FEAT-726 — Configure-Override Idempotency & `speech_report` Hardening
**Spec**: `sdd/specs/bots-agent-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4618
**Assigned-to**: unassigned

**Discovered-from**: `issue:81fa838a18c1`

---

## Context

Implements spec §3 Module 6.

`issue:81fa838a18c1` offers two acceptable resolutions: guard the override sites,
**or** "document the gap in `docs/agent-configure-lifecycle.md`". This feature
does both — and the documentation half is not optional bookkeeping, because the
doc currently prescribes a recipe that is **wrong**:

> §6 Work after `super().configure()`
> Subclass overrides that do their own work AFTER `await super().configure(app)`
> should guard it with `if self.configure_count > 1: return`.

That misfires on the one path FEAT-721 deliberately kept alive. When an app
arrives where none was bound before (CLI first, server later), the base runs its
**full pipeline** with `_configure_count == 2`. An override following §6 would
skip its own setup on a configure that genuinely ran — a silent missing-setup
bug. The next contributor who reads §6 and copies its recipe reintroduces
exactly what this feature just fixed.

TASK-4616 already corrected the in-code docstring (`abstract.py:1587-1588`).
This task corrects the prose doc, and records the four sites that are
deliberately **not** guarded so a later reader does not "complete" the fix.

This task is documentation-only. No source or test file changes.

---

## Scope

- Rewrite `docs/agent-configure-lifecycle.md` §6 around `configure_skipped`,
  stating explicitly why `configure_count > 1` is wrong.
- Add a new §8 documenting the pre-super `configure_is_noop(app)` shape.
- Reproduce the "Assessed and deliberately left unguarded" table (spec §1) in
  the doc, with each site's reason.
- Renumber the existing §7 ("Not a concurrency guarantee") if the new section
  is inserted before it — or append the new section as §8 after it, keeping §7
  as-is. Prefer appending; do not renumber unnecessarily.

**NOT in scope**:
- Any change under `packages/` — no source, no tests. If the doc and the code
  disagree, the **code** (as landed by TASK-4616/4617/4618) is correct; fix the
  doc, and report the discrepancy in the Completion Note.
- The `configure()` docstring at `abstract.py:1587-1588` — already corrected by
  TASK-4616. Read it and keep this doc consistent with it; do not edit it again.
- §1-§5 and §7 of the doc. §1 (idempotency), §2 (`reconfigure`), §3
  (`post_configure` re-entrancy), §4 (`find_registered_toolkit`), §5
  (keep-first) and §7 (not a concurrency guarantee) are all still accurate —
  leave them alone.
- Any other doc under `docs/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent-configure-lifecycle.md` | MODIFY | rewrite §6, add §8 (pre-super shape + exemptions table) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `36b9847aa`. Anchor re-confirmed `grep -c` = 1.

### Verified Imports

None — documentation only.

### Existing Signatures to Use

The doc must name these exactly as they land. Verify each in the source before
writing (TASK-4616 created the first three):

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
    @property
    def configure_skipped(self) -> bool: ...          # post-super signal (TASK-4616)
    def configure_is_noop(self, app=None) -> bool:    # pre-super signal, PLAIN def (TASK-4616)
    def _resolve_configure_app(self, app): ...        # private; mention only if §8 needs it (TASK-4616)

    @property
    def configure_count(self) -> int: ...             # line 1887 — pre-existing, still public
    async def reconfigure(self, app=None) -> None:    # line 1891 — pre-existing, unchanged
```

Existing doc structure, verified (`docs/agent-configure-lifecycle.md`):

```
## 1. `configure()` is idempotent per instance
## 2. Forcing a re-run: `reconfigure()`
## 3. `post_configure()` must be re-entrant
## 4. Adopting a toolkit: `find_registered_toolkit()`
## 5. Keep-first: the manager wins
## 6. Work after `super().configure()`        <- line 85, THE SECTION TO REWRITE
## 7. Not a concurrency guarantee
```

The four exempt sites and their verified evidence (spec §1):

| Site | Why no guard |
|---|---|
| `bots/data.py:876-889` | pre-super work self-gates on `if self._queries and not self.dataframes` (`:881`); `_sync_dataframes_from_dm()` is a pure re-sync |
| `bots/mixins/narrative.py:51-52` | pure cooperative passthrough — `await super().configure(*args, **kwargs)` and nothing else |
| `bots/mixins/infographic_authoring.py:109-118` | pre-super `set_bot()` is verified idempotent: `_inject_prompt_guidance` returns early on the sentinel `"## Infographic Generation Mode" in tmpl` (`tools/infographic_toolkit.py:437-447`) |
| `bots/mixins/identity.py:49` | not code — an `async def configure` inside the `IdentityMixin` class **docstring**'s usage example |

### Does NOT Exist

- ~~`if self.configure_count > 1: return` as a correct post-super guard~~ — this
  is the text being removed. Do not leave it anywhere in the doc except as an
  explicitly-labelled "do not do this".
- ~~`ObsidianAgent`~~ — the class is `FirefliesObsidianAgent`
  (`agents/obsidian.py:264`).
- ~~`ChromeAgent`~~ — the class is `WebAgent` (`bots/chrome.py:338`).
- ~~a `configure()` override in `bots/base.py` or at `bots/agent.py:1562`~~ —
  neither `BaseBot` nor `Agent` overrides `configure`.
- ~~`await self.configure_is_noop(app)`~~ — it is a plain `def`. Any example in
  the doc must call it without `await`.
- ~~a §8 in the current doc~~ — it ends at §7; §8 is new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/agent-configure-lifecycle.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_skipped",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_is_noop",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure_count",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.reconfigure"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Match the existing document's voice: short numbered sections, a fenced Python
example per pattern, no marketing tone. §3's shape is the model —

```markdown
## 3. `post_configure()` must be re-entrant

<two or three sentences of contract>

```python
<the recommended pattern>
```

<one sentence on what the pattern guarantees>
```

### Key Constraints

- **Keep the feature/spec header** at the top of the file
  (`> **Feature**: FEAT-721 …`). Add FEAT-726 beside it rather than replacing
  it — FEAT-721 established the lifecycle and FEAT-726 corrected it; a reader
  needs both trails.
- **Say plainly why `configure_count > 1` is wrong**, with the CLI-then-server
  case named. A silent swap of the recipe teaches nothing and the next
  contributor re-derives the wrong guard from `configure_count`'s existence.
- `configure_count` remains public and documented — it is still a legitimate
  thing to read. The doc must say it is not the *guard*, not that it is gone.
- Every symbol name must be verified in the source first. This doc's current
  §6 is wrong precisely because it was written ahead of the code.
- No `await` on `configure_is_noop` in any example.
- The exemptions table must give each site's **reason**, not just its path —
  a bare list invites someone to "finish the job".
- Markdown only; no changes under `packages/`.

### References in Codebase

- `docs/agent-configure-lifecycle.md` — the file; read all of it before editing
- `packages/ai-parrot/src/parrot/bots/abstract.py:1575-1615` — `configure()` and
  its corrected docstring (TASK-4616)
- `sdd/specs/bots-agent-tech-debt.spec.md` §1, §2 — the mechanism and the two
  canonical patterns, already written out
- `sdd/specs/double-configure-agents.spec.md` — FEAT-721, which this doc
  originally described

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4618 is `done` — *why*: this doc names
   `configure_skipped` and `configure_is_noop` as they actually landed;
   documenting them before they exist is how §6 became wrong in the first place.
2. Read the whole of `docs/agent-configure-lifecycle.md` — *why*: §6 must stay
   consistent with §1-§5 and §7, which are unchanged and still correct.
3. Read `abstract.py:1575-1615` and the two new members — *why*: verify the
   final names and the exact no-op condition before describing them.
4. Rewrite §6 — *why*: it is the wrong recipe a future contributor would copy.
5. Append §8 with the pre-super shape and the exemptions table — *why*: the
   pre-super shape is undocumented, and the exemptions need a reason on record.
6. Re-read the result against the two canonical patterns in spec §2 — *why*: the
   doc and the spec must not drift on the first day.

### `docs/agent-configure-lifecycle.md` (MODIFY — §6 rewrite)

```markdown
<!-- occurrences: 1 (verified: grep -c '## 6. Work after `super().configure()`' docs/agent-configure-lifecycle.md) -->
<!-- REPLACE the whole of section 6 — from the heading at line 85 down to (but NOT
     including) the `## 7. Not a concurrency guarantee` heading — with: -->

## 6. Work after `super().configure()`: `configure_skipped`

A subclass override that does its own work AFTER `await super().configure(app)`
must skip that work when the base call was an idempotent no-op. Read
`configure_skipped`:

```python
async def configure(self, app=None) -> None:
    await super().configure(app)
    if self.configure_skipped:
        return
    ...  # own setup
```

`configure_skipped` is `True` only when the entry that just returned skipped the
pipeline. It is `False` before the first `configure()`, after any entry that ran
the pipeline, and after `reconfigure()`.

> **Do not use `if self.configure_count > 1: return`.** Earlier revisions of
> this document and of the `configure()` docstring prescribed it; it is wrong.
> On the CLI-then-server path — an app arriving where none was bound before —
> the base runs its **full pipeline** with `configure_count == 2`. An override
> guarded on the counter would skip its own setup on a configure that genuinely
> ran, trading a double-run bug for a silent missing-setup bug.
> `configure_count` is still public and fine to read for diagnostics; it is just
> not the guard.
```

```markdown
<!-- FILL IN: confirm the exact end boundary of the current section 6 by reading
     docs/agent-configure-lifecycle.md from line 85 to the `## 7.` heading, and
     replace exactly that range — bounded by "§7 is unchanged" (AC: §1-§5 and §7
     untouched). -->
```

**Why**: the blockquote is the load-bearing part. Removing the wrong recipe
silently would leave `configure_count` sitting there as the obvious-looking
guard, and the next contributor would reach for it again.

### `docs/agent-configure-lifecycle.md` (MODIFY — new §8)

```markdown
<!-- APPEND at end of file, after section 7 -->

## 8. Work before `super().configure()`: `configure_is_noop()`

An override that does its own work BEFORE `await super().configure(app)` cannot
use `configure_skipped` — by the time the base returns, the work has already
run. It asks in advance instead:

```python
async def configure(self, app=None) -> None:
    if self.configure_is_noop(app):
        await super().configure(app)   # keeps the counter and the INFO log truthful
        return
    ...  # own setup
    await super().configure(app)
```

`configure_is_noop(app)` is `True` when a `configure(app)` call made right now
would early-return. It is deliberately a plain `def`, not a coroutine, so it can
be consulted before the override's first `await`.

Note the `super().configure(app)` call on the no-op path: it looks redundant and
is not. Returning without it would skip the entry-counter increment and the INFO
log, and leave `configure_count` under-counting — which
`configure_is_noop` itself reads.

### Sites deliberately left unguarded

These need no guard. They are listed with their reasons so the inventory reads
as complete rather than unfinished:

| Site | Why no guard |
|---|---|
| `bots/data.py:876-889` | its pre-super work self-gates on `if self._queries and not self.dataframes`; `_sync_dataframes_from_dm()` is a pure re-sync |
| `bots/mixins/narrative.py:51-52` | pure cooperative passthrough — it awaits `super().configure()` and does nothing else |
| `bots/mixins/infographic_authoring.py:109-118` | its pre-super `set_bot()` is idempotent: `_inject_prompt_guidance` returns early on a sentinel header already present in the prompt |
| `bots/mixins/identity.py:49` | not code — an `async def configure` inside the `IdentityMixin` class docstring's usage example |

<!-- FILL IN: before publishing the table, re-verify each path:line against the
     source — these were verified at spec time and the guard tasks have since
     edited neighbouring files — bounded by "every line reference in the doc is
     accurate" (AC: symbol and line references verified). -->
```

**Why**: §8 documents the shape that had no documentation at all, and the
exemptions table is the part that stops a future reader from "finishing" the fix
by guarding four sites that are correct as they stand.

### FILL IN checklist

- [ ] `docs/agent-configure-lifecycle.md` — exact end boundary of the current §6 before replacing it; bounded by AC "§1-§5 and §7 untouched"
- [ ] `docs/agent-configure-lifecycle.md` — re-verify every `path:line` in the exemptions table against the source; bounded by AC "line references accurate"

---

## Acceptance Criteria

- [ ] `docs/agent-configure-lifecycle.md` contains **no** prescription of
      `if self.configure_count > 1: return`, except inside the explicit
      "do not use" blockquote.
- [ ] §6 documents the post-super `configure_skipped` pattern with a runnable
      example and states why the counter-based guard is wrong, naming the
      CLI-then-server path.
- [ ] A new §8 documents the pre-super `configure_is_noop(app)` pattern,
      including why the no-op path still calls `super().configure(app)`.
- [ ] No example in the doc `await`s `configure_is_noop`.
- [ ] The "sites deliberately left unguarded" table lists all four sites with a
      reason each, and every `path:line` in it is verified against the source.
- [ ] `configure_count` is still described as public and readable — not as
      removed.
- [ ] The FEAT-721 header trail is kept, with FEAT-726 added beside it.
- [ ] §1-§5 and §7 are unchanged.
- [ ] The doc is consistent with the corrected `configure()` docstring at
      `abstract.py:1587-1588`.
- [ ] **No file under `packages/` is modified** by this task.

---

## Validation Commands

> Documentation-only task — it changes no importable code. The FEAT-721
> lifecycle suite is re-run to prove exactly that: the doc edit broke nothing.
>
> `tests/bots/test_configure_override_guards.py` is deliberately NOT listed
> here: this task declares no test file of its own (TASK-4616 creates that one),
> and naming an undeclared path trips `check_task_graph`'s
> `validation-path-unknown`. It is in the feature-level Validation Contract
> (spec §4), so `/sdd-done` still runs it for this feature.

- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`
- `pytest packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py -q`

---

## Test Specification

No new tests — this task produces documentation. Verification is by review
against the Acceptance Criteria plus the two suites above, run inside the
worktree with `PYTHONPATH=packages/ai-parrot/src`. If you want the feature's own
guard suite as well, run
`pytest packages/ai-parrot/tests/bots/test_configure_override_guards.py -q`
by hand — it exists once TASK-4616 has landed.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug bots-agent-tech-debt --feature-id FEAT-726`)
2. **Read the spec** at `sdd/specs/bots-agent-tech-debt.spec.md` (§1's two
   tables and the exemptions table, §2 for the two canonical patterns, §3
   Module 6)
3. **Check dependencies** — TASK-4618 must be `"done"` in
   `sdd/tasks/index/bots-agent-tech-debt.json`; `configure_skipped` and
   `configure_is_noop` must exist in `abstract.py` before you describe them
4. **Verify the Codebase Contract** — confirm both new member names and every
   `path:line` in the exemptions table against the source
5. **Update status** in `sdd/tasks/index/bots-agent-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only `docs/agent-configure-lifecycle.md`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4621 bots-agent-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

<!-- Filled in by the implementing agent at close time. -->
