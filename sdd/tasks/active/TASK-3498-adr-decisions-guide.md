# TASK-3498: User guide for the ADR decision plane

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3496
**Assigned-to**: unassigned

---

## Context

Module 7's documentation half, and AC13 is unusually prescriptive about what the
guide must cover:

> Guide documents parsing subset, Python-only automatic citation extraction,
> rename behavior, local/remote freshness, generation costs/limits, and review
> policy.

Each of those six is a **limitation** a user would otherwise discover by being
surprised. The guide's job is to make the boundaries legible before someone
relies on behaviour the feature does not have — most importantly that accepting
a candidate does not turn a hypothesis into history.

---

## Scope

- Write `docs/guides/wiki-adr-decisions.md` covering all six AC13 topics plus a
  worked provenance example.
- Add an `adr` command section to the existing `docs/guides/llm-wiki-guide.md`
  and list it in that file's Table of Contents.
- Verify every command and flag shown actually exists by running it.

**NOT in scope**: code changes of any kind, and any new documentation outside
these two files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/guides/wiki-adr-decisions.md` | CREATE | The ADR decision-plane guide |
| `docs/guides/llm-wiki-guide.md` | MODIFY | `adr` command section + ToC entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified references

```
docs/guides/llm-wiki-guide.md:1    "# LLM Wiki — Complete Guide"
docs/guides/llm-wiki-guide.md:9    "## Table of Contents"
docs/guides/llm-wiki-guide.md:229  "## Querying"
docs/guides/llm-wiki-guide.md:296  "### status — Check Graph Health"
docs/guides/llm-wiki-guide.md:314  "## Persistent Memory"   <- SECTION BOUNDARY
docs/guides/llm-wiki-guide.md:445  "## Coding Assistant Integration"
docs/guides/llm-wiki-guide.md:550  "### MCP Server (Native Tools)"
```

The guide's house style: `##` for top-level sections, `###` for one command
each, a fenced `bash` block per command, and a ToC entry per `##`.

### Facts the guide must state, with their sources

| Claim | Source |
|---|---|
| Frontmatter subset is `id`, `title`, `status`, `supersedes`; nested YAML unsupported | spec §2 "ADR parsing and references" |
| Sections: `Context`, `Decision`, `Consequences`, `Status`; fenced headings ignored | spec §2 |
| Missing `Decision` ⇒ ordinary document, not an ADR | spec §2 |
| Automatic citation extraction is **Python only**, from comments and docstrings | spec §2, AC13 |
| Other languages: explicit Markdown `sym:` links only | spec §2 |
| A rename creates a **new** record; the old one stays with missing evidence | spec §2 |
| Freshness: `current` / `stale` / `missing` / `unverified`; remote = `unverified` | spec §2 |
| Generation defaults: 8 files, 12000 in, 2000 out, 3 candidates, 60s, one call | spec §8 Q4 |
| Generation is opt-in; `WIKI_ADR_LLM` or an injected client; credentials env-only | spec §2 |
| Acceptance is a maintainer CLI action; no ADR file is required | spec §8 Q3, AC11 |
| Accepted candidates stay `inferred` / `unknown` forever | AC11 |
| No MCP tool or model can accept a candidate | spec §2, AC11 |
| Default inventory bound 10000; overflow is `ADR_INVENTORY_LIMIT` | spec §2, AC14 |
| `--ns all` unsupported in v1 | spec §2 Module 6 |

### Does NOT Exist — do not document

- ~~`--force` on `adr generate`~~ — not in v1 (spec §2).
- ~~an automatic ADR commit on acceptance~~ — `adr export` prints to stdout only.
- ~~Git-history mining, drift verdicts, PR/Jira ingestion, a review UI~~ — all
  §1 Non-Goals. Do not imply any of them are planned.
- ~~`backend: postgres` in `.parrot/wiki.json`~~ — the Literal is
  `sqlite|memory|arangodb` (`project.py:414`). Postgres is direct-instantiation
  only (spec §6).
- ~~automatic citation extraction for JS/PHP/Rust~~ — deferred (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/guides/wiki-adr-decisions.md", "action": "CREATE"},
    {"path": "docs/guides/llm-wiki-guide.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Run every command you document.** AC13 is about accuracy, and a guide that
  shows a flag the CLI does not have is worse than no guide.
- Lead the review section with the limitation, not the capability: the single
  most likely misreading of this feature is that accepting a candidate makes it
  documented history.
- Match the existing guide's tone and formatting; no new documentation style.

---

## Implementation Blueprint

### Steps (in order)

1. Run `wikitoolkit adr --help` and each subcommand's `--help`, and build the
   guide's command reference from that output — *why*: it makes the flag list
   correct by construction rather than by transcription.
2. Write the new guide following the outline below.
3. Add the `llm-wiki-guide.md` section and its ToC entry.
4. Re-run every documented command against a scratch repository.

### `docs/guides/wiki-adr-decisions.md` (CREATE)

Write the file with exactly these `##` sections, in this order:

```markdown
# Architectural Decisions in the LLM Wiki

<!-- FILL IN: two-paragraph intro — what the decision plane does (extract ADRs,
     answer "why" with citations, generate labeled candidates) and, immediately,
     the one thing it deliberately does not do: turn an inference into history.
     Bounded by spec §1 Goals + Non-Goals. -->

## Quick Start
<!-- FILL IN: a bash block — wikitoolkit build (ADRs refresh automatically),
     adr lookup, adr why. Show real output including the [DOCUMENTED / ACCEPTED]
     labels. Bounded by AC13. -->

## Documented vs Inferred — Read the Labels
<!-- FILL IN: THE central concept. A table of the four label combinations
     ([DOCUMENTED / ACCEPTED], [DOCUMENTED / UNKNOWN], [INFERRED / UNREVIEWED],
     [INFERRED / ACCEPTED]) and what each does and does NOT license a reader to
     conclude. State plainly: an accepted candidate is a team agreement, not a
     historical record. Bounded by AC11 + AC3. -->

## What Gets Parsed
<!-- FILL IN: the configured globs; the four frontmatter keys; the four
     sections; case-insensitivity; fenced headings ignored; missing Decision =>
     ordinary document; status conflict => unknown + ADR_STATUS_CONFLICT;
     unknown status preserved verbatim; nested YAML unsupported and why (the
     parser never evaluates the document). Bounded by AC13 + spec §2. -->

## How Decisions Attach to Code
<!-- FILL IN: automatic citation extraction is PYTHON ONLY, from comment tokens
     and docstrings; an executable string literal is never a citation; module
     comments attach at file scope; other languages use an explicit Markdown
     sym: link; applicability never propagates through the call graph; duplicate
     ADR-42 aliases stay unresolved. Bounded by AC13 + AC2. -->

## Freshness, Renames, and What Goes Stale
<!-- FILL IN: the four freshness values and what each means; a remote namespace
     is always `unverified`; stale means the cited code changed, NOT that the
     decision is wrong; a rename creates a new record and leaves the old one
     with missing evidence — v1 does not infer identity across renames.
     Bounded by AC13 + AC7. -->

## Generating Candidates (opt-in)
<!-- FILL IN: how to enable (decisions.generation_enabled + WIKI_ADR_LLM);
     credentials are environment-only; the exact budget table from spec §8 Q4
     (1 call, 8 files, 12000 in, 2000 out, 3 candidates, 60s); no Git history;
     a rerun over unchanged evidence reuses and costs nothing; every candidate
     cites supplied evidence only, with observations kept apart from hypotheses.
     Bounded by AC13 + AC4 + AC6. -->

## Reviewing and Accepting
<!-- FILL IN: LEAD with the limitation — acceptance changes review status ONLY;
     origin stays inferred and source status stays unknown, forever. Then: why
     review is CLI-only and no MCP tool or model can accept; the four actions;
     --expected-revision and what ADR_REVISION_CONFLICT means; rejection does
     not delete; revise resets to unreviewed; adr export prints Markdown and
     committing it is optional. Bounded by AC13 + AC11 + spec §8 Q3. -->

## Limits and Error Codes
<!-- FILL IN: the inventory bound (10000, ADR_INVENTORY_LIMIT) and that it is a
     deliberate v1 tradeoff; the 1 MiB record cap; --ns all unsupported; a table
     of every ADR_* code with one line each on what it means and what to do.
     Bounded by AC14 + spec §2 "Errors and transport". -->

## What This Feature Does Not Do
<!-- FILL IN: the §1 Non-Goals, stated as boundaries rather than a roadmap —
     no compliance/drift verdicts, no Git-history mining, no PR/Jira ingestion,
     no automatic ADR commits, no review UI, no automatic citation extraction
     outside Python. Bounded by spec §1 Non-Goals. -->

## Command Reference
<!-- FILL IN: one ### per adr subcommand, each with a bash block and its real
     flags, taken from `wikitoolkit adr <cmd> --help`. Include the exit-code
     table (0 ok/empty/ambiguous, 1 failed, 2 invalid argument). Bounded by
     spec §2 Module 6. -->
```

**Why this outline**: "Documented vs Inferred" comes third, before anything a
reader would act on, because every later section depends on that distinction
being internalized. "Reviewing and Accepting" leads with the limitation because
that is the section a maintainer reads right before doing the one thing the
spec most wants them not to misunderstand (AC11). "What This Feature Does Not
Do" is a section rather than scattered caveats so a reader can check a
capability in one place.

### `docs/guides/llm-wiki-guide.md` (MODIFY)

```markdown
<!-- occurrences: 1 (verified: grep -c '^## Persistent Memory' docs/guides/llm-wiki-guide.md) -->
<!-- BEFORE — insert a new `## Architectural Decisions (adr)` section directly
     ABOVE `## Persistent Memory` (verified: docs/guides/llm-wiki-guide.md:314),
     so it closes out the query-side sections that start at `## Querying`
     (line 229): -->

## Architectural Decisions (adr)

<!-- FILL IN: a short section — one paragraph plus a bash block showing
     `adr lookup`, `adr why` and `adr review`, each with one line of
     explanation, then a link to docs/guides/wiki-adr-decisions.md for the full
     treatment. Keep it to roughly the length of the `## Querying`
     subsections (lines 231-313) — this is a pointer, not a duplicate.
     State in one sentence that candidates are labeled inferred and that
     accepting one does not make it documented history. -->
```

Add the matching entry to the Table of Contents at
`docs/guides/llm-wiki-guide.md:9`, positioned to match the new section's place
in the document.

### FILL IN checklist

- [ ] `wiki-adr-decisions.md` — all ten sections; bounded by AC13's six required topics
- [ ] `wiki-adr-decisions.md` — Command Reference built from real `--help` output
- [ ] `llm-wiki-guide.md` — the `## Architectural Decisions (adr)` section
- [ ] `llm-wiki-guide.md:9` — the ToC entry

---

## Acceptance Criteria

- [ ] `docs/guides/wiki-adr-decisions.md` exists with all ten sections
- [ ] AC13's six topics are each covered: parsing subset, Python-only citation extraction, rename behaviour, local/remote freshness, generation costs/limits, review policy
- [ ] The documented-vs-inferred distinction appears before any actionable instruction
- [ ] The review section states that acceptance leaves `origin='inferred'` and `source_status='unknown'` (AC11)
- [ ] It states that no MCP tool or model can accept a candidate (AC11)
- [ ] Every `ADR_*` error code is listed with a one-line meaning
- [ ] The §1 Non-Goals appear as stated boundaries, not as a roadmap
- [ ] **Every command and flag shown was executed and produced the documented output**
- [ ] No documented flag is absent from the CLI, and no CLI flag in scope is undocumented
- [ ] `llm-wiki-guide.md` gains the `adr` section and its ToC entry, in the existing house style
- [ ] Nothing from "Does NOT Exist" is documented as if it existed
- [ ] No code file is modified by this task

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

> Documentation carries no tests of its own; this command confirms the CLI
> surface being documented still behaves as described. Accuracy is verified by
> running each documented command by hand (see Agent Instructions).

---

## Agent Instructions

1. **Read the spec** §1 Non-Goals, §2 (all subsections), §8 Q3/Q4, and AC13.
2. **Run `wikitoolkit adr --help` and every subcommand's `--help`** before writing the Command Reference.
3. **Write** both files from the blueprint; complete every `<!-- FILL IN -->`.
4. **Verify** by running every documented command against a scratch repository and comparing the output to what you wrote. Save the transcript under `artifacts/logs/` (AC12).
5. **Verify** the Validation Command passes.
6. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
7. **Fill in the Completion Note**, listing any command whose real output differed from the spec's description.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
