---
title: Necessity Ladder (FEAT 908)
summary: How the SDD flow decides whether a module has to be written at all, and how that decision binds tasks and review.
---

# Necessity Ladder (FEAT-908)

## Purpose

The code a feature produces is fixed by its spec: `/sdd-task` and the coders build only what the
spec's Interface Skeletons name. The Necessity Ladder is the check, applied while the spec is
written, that each module is needed and that nothing already in reach does the job.
Each candidate module walks the rungs in order and stops at the first one that fully covers it:

| Rung | Question | Evidence the spec must carry |
|---|---|---|
| R1 | Does a Goal or acceptance criterion need it? | If not: a `Deferred:` line in §1 Non-Goals |
| R2 | Is it already in this repository? | `verified: path:NN`, also in §6 |
| R3 | Does the standard library do it? | The symbol |
| R4 | Is it a feature of a platform already in the stack? | The symbol + one `path:NN` where it is used |
| R5 | Does a declared dependency do it? | The manifest line + the symbol |
| R6 | Can it be one change at an existing site? | Its MODIFY row in §6 Edit Sites |
| R7 | None of the above: write the minimum | A §6 "Does NOT Exist" entry + the query that came back empty |

## Public API

- Spec template §3 `#### Necessity Ladder` table: `Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC`, then a `Totals:` line.
- Spec template §1 `- Deferred: <thing> — <what would justify building it>`; §7 optional `### Known Shortcuts`.
- `/sdd-spec` §4c builds the table, §5a Lean Review (checks L1–L10) checks it, §7 prints a `Ladder:` line.
- `/sdd-proposal` and `/sdd-brainstorm` state *If not built* for every new capability and list the rest as deferred.
- Tasks open their `## Scope` with `**Ladder**: <rung> · reuses <evidence> · est. <n> LOC`.

## Configuration & Parameters

No flag: the ladder always runs. Rung R5 reads the repository's reuse list, `sdd/CONVENTIONS.md`
§ Reuse first (ai-parrot keeps its list in `codebase-conventions.md`: `asyncdb`, `navconfig`,
`navigator-auth`, `navigator-eventbus`).

## Usage Examples

A hypothetical feature, "post to a chat channel when a report finishes". The paths are made up,
so line numbers stay `NN`; in a real spec each one is a verified location.

| Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC |
|---|---|---|---|---|---|
| M1: Report-finished hook | R2 | `ReportRunner.on_complete` — verified: `src/reports/runner.py:NN` | AC 1 | none | 0 |
| M2: Retry on rate limits | R5 | `backoff.on_exception` — `pyproject.toml:NN` | AC 2 | one decorator | ~3 |
| M3: Channel notifier | R7 | `AbstractNotifier` — verified: `src/notify/base.py:NN`. Nothing covers chat channels: Does NOT Exist `notify.chat.ChannelNotifier` (query: `grep -rn "class .*ChannelNotifier" src/` → 0 hits) | AC 3 | 1 class, 1 method | ~40 |

Totals: 3 modules — reuse 1 · stdlib/platform 0 · dependency 1 · single change 0 · new 1 · deferred 0 · est. new LOC 43

## Gotchas

- Never cut: validation at trust boundaries, error handling that prevents data loss, security,
  accessibility, anything a governing decision or the user requires.
- A capability the brainstorm, proposal or intake requires is kept; doubting it opens a §8 question.
- "Est. LOC" is a reference: around twice the estimate is a review finding to explain, never a blocker.
- A deliberately limited solution carries `# shortcut: <limit>, <when to upgrade>` in code and a
  Known Shortcuts row in the spec; the reviewer flags one without the other.

## Related

- [Decision Audit](./decision-audit.md) — its consequence gate (`/sdd-spec` §5b) runs right after the
  Lean Review (§5a); a module a governing decision requires is never cut by the ladder.
- [Validation Contract](./test-selection-validation-contract.md) — how a spec names the tests that pin
  it; this feature's text is pinned by `tests/sdd_scripts/test_necessity_ladder_contract.py`.
