# Architectural Decisions in the LLM Wiki

The LLM Wiki's decision plane extracts Architectural Decision Records (ADRs) from your codebase and answers "why" questions with cited decision excerpts. It can also generate labeled candidate rationales for code sections that lack documented decisions. However, it deliberately does not turn an inference into documented history — accepting a candidate records the team's agreement, but the record stays inferred with an unknown source status forever.

## Quick Start

```bash
# Build the wiki (ADRs refresh automatically)
wikitoolkit build

# Look up decisions that apply to a symbol
wikitoolkit adr lookup sym:parrot.knowledge.wiki.cli.WikiStore

# Answer a "why" question with cited decisions
wikitoolkit adr why "why does the wiki use SQLite?"
```

## Documented vs Inferred — Read the Labels

The central concept is the distinction between documented and inferred decisions:

| Origin | Review Status | Meaning | Licensed Conclusion |
|--------|---------------|---------|---------------------|
| `DOCUMENTED` | `ACCEPTED` | ADR file in the repo, accepted by the team | This is documented history |
| `DOCUMENTED` | `UNKNOWN` | ADR file in the repo, never reviewed | This is documented but unvalidated |
| `INFERRED` | `UNREVIEWED` | Generated candidate, never reviewed | This is a hypothesis only |
| `INFERRED` | `ACCEPTED` | Generated candidate, accepted by the team | The team agrees with this rationale |

An accepted candidate is a team agreement, not a historical record. The origin stays `inferred` and the source status stays `unknown` forever.

## What Gets Parsed

ADRs are parsed from Markdown files matching the configured globs (defaults to `docs/adr/**/*.md`, `docs/architecture/**/*.md`). The parser extracts:

- **Frontmatter**: `id`, `title`, `status`, `supersedes` (case-insensitive). Nested YAML is unsupported.
- **Sections**: `Context`, `Decision`, `Consequences`, `Status` (case-insensitive). Fenced headings are ignored.
- **Missing `Decision`** section means the file is treated as an ordinary document, not an ADR.
- **Status conflicts** (e.g., frontmatter says `accepted` but section says `deprecated`) result in `unknown` status and `ADR_STATUS_CONFLICT` in diagnostics.

## How Decisions Attach to Code

Automatic citation extraction is **Python only**, from comment tokens and docstrings:

- Module comments attach at file scope
- Function/class docstrings attach to the respective symbol
- An executable string literal is never a citation
- Applicability never propagates through the call graph
- Duplicate ADR-42 aliases stay unresolved

Other languages use explicit Markdown `sym:` links only.

## Freshness, Renames, and What Goes Stale

Freshness values indicate the relationship between cited code and decision evidence:

- `current` — cited code matches the decision's evidence exactly
- `stale` — cited code changed since the decision was last refreshed
- `missing` — cited code no longer exists
- `unverified` — decision comes from a remote namespace

A remote namespace is always `unverified`. Stale means the cited code changed, NOT that the decision is wrong. A rename creates a new record and leaves the old one with missing evidence — v1 does not infer identity across renames.

## Generating Candidates (opt-in)

Generation is opt-in and requires:
- `decisions.generation_enabled = true` in `.parrot/wiki.json`
- `WIKI_ADR_LLM` environment variable or an injected client
- Credentials in environment variables only (never in config)

Budget limits (per call):
- 1 LLM call
- 8 files maximum
- 12000 input tokens
- 2000 output tokens
- 3 candidates maximum
- 60-second timeout

A rerun over unchanged evidence reuses and costs nothing. Every candidate cites supplied evidence only, with observations kept apart from hypotheses.

## Reviewing and Accepting

**Acceptance changes review status ONLY** — origin stays inferred and source status stays unknown, forever. This is the single most important limitation to understand.

Review is CLI-only — no MCP tool or model can accept a candidate. The four actions are:

- `accept` — mark as team-agreed (review_status=accepted, origin=inferred forever)
- `reject` — mark as team-rejected (review_status=rejected)
- `revise` — replace with edited content (--edit-file required)
- `link` — associate with a documented ADR (--documented-id required)

Use `--expected-revision` to guard against concurrent edits. `ADR_REVISION_CONFLICT` means the decision was edited since you last read it. Rejection does not delete; revise resets to unreviewed. `wikitoolkit adr export` prints Markdown and committing it is optional.

## Limits and Error Codes

Inventory bound: 10000 records (deliberate v1 tradeoff). Configurable via `ADR_INVENTORY_LIMIT`.

| Error Code | Meaning | What To Do |
|------------|---------|------------|
| `ADR_INVALID_ARGUMENT` | Bad CLI flag or request | Check the command syntax |
| `ADR_RECORD_NOT_FOUND` | No such decision ID | Check the ID spelling |
| `ADR_RECORD_TOO_LARGE` | Record exceeds 1 MiB | Split into smaller decisions |
| `ADR_REVISION_CONFLICT` | Expected revision mismatch | Re-read before editing |
| `ADR_STATUS_CONFLICT` | Frontmatter vs section status | Make them consistent |
| `ADR_INVENTORY_LIMIT` | Too many records | Delete unused decisions |
| `ADR_GENERATION_DISABLED` | Generation not enabled | Enable in config |
| `ADR_NO_MODEL_CONFIGURED` | No LLM for generation | Set WIKI_ADR_LLM |

## What This Feature Does Not Do

This feature does not:
- Provide compliance or drift verdicts
- Mine Git history for decisions
- Ingest PRs or Jira tickets as decisions
- Automatically commit accepted candidates
- Provide a review UI
- Extract citations outside Python automatically

These are all §1 Non-Goals, not roadmap items.

## Command Reference

### adr sync

```bash
wikitoolkit adr sync [OPTIONS] [PATHS]...

  Refresh ADR records from source. Never invokes a model.

Options:
  --path PATH  Project root.
  --json       Emit the SyncResult as JSON.
```

### adr lookup

```bash
wikitoolkit adr lookup [OPTIONS] SYMBOL

  Find the decisions that apply to SYMBOL, with citations.

Options:
  --path PATH             Project root.
  --include-history       Include rejected/deprecated/superseded records.
  --limit INTEGER         Maximum hits (1-50).  [default: 10]
  --budget INTEGER        Token budget (min 256).  [default: 3000]
  --json                  Emit the typed result as JSON.
  --ns TEXT               Namespace to read ('all' is not supported).
```

### adr why

```bash
wikitoolkit adr why [OPTIONS] QUESTION

  Answer a 'why' question with cited decision excerpts.

Options:
  --path PATH             Project root.
  --include-history       Include rejected/deprecated/superseded records.
  --limit INTEGER         Maximum hits (1-50).  [default: 10]
  --budget INTEGER        Token budget (min 256).  [default: 3000]
  --json                  Emit the typed result as JSON.
  --ns TEXT               Namespace to read ('all' is not supported).
```

### adr generate

```bash
wikitoolkit adr generate [OPTIONS] TARGET

  Generate labeled CANDIDATE rationale for TARGET (a sym: id or a file).

  Requires generation to be enabled and a model configured. Candidates are
  created unreviewed; accepting one is a separate, explicit `adr review`.

Options:
  --path PATH  Project root.
  --json       Emit the GenerationResult as JSON.
```

### adr review

```bash
wikitoolkit adr review [OPTIONS] DECISION_ID

  Accept, reject, revise, or link a decision record.

  Accepting a candidate records the team's agreement. It does NOT turn the
  candidate into documented history: the record stays inferred with an
  unknown source status, and no ADR file is written (Q3, AC11).

Options:
  --action [accept|reject|revise|link]  [required]
  --expected-revision INTEGER           Revision you read; guards concurrent edits.  [required]
  --actor TEXT                          Who is reviewing, e.g. 'human:jlara'. Attribution is mandatory.  [required]
  --reason TEXT                         Why.
  --edit-file PATH                      CandidateEdit JSON; required for --action revise.
  --documented-id TEXT                  Documented ADR to associate; required for --action link.
  --path PATH                           Project root.
  --json                                Emit the updated record as JSON.
```

### adr export

```bash
wikitoolkit adr export [OPTIONS] DECISION_ID

  Print DECISION_ID as Markdown on stdout.

  Writing or committing this output is deliberately outside the feature —
  accepting a candidate in the wiki is sufficient (Q3).

Options:
  --path PATH  Project root.
```

Exit codes:
- 0 — Success or empty/ambiguous result
- 1 — Failed (error occurred)
- 2 — Invalid argument