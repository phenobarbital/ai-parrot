# Decision Audit (FEAT-784)

## What it does

The Decision Audit subsystem governs the authoritative dossier of architectural decisions and enforces a consequence gate on specification changes. It provides a structured way to document, track, and verify decisions without requiring LLM calls, ensuring that architectural constraints are consistently applied across the codebase.

The consequence gate verifies that every specification change complies with approved architectural decisions. When a specification declares a `## Decisions` block, the system checks that all referenced decisions are valid, non-contradictory, and properly approved. This prevents accidental violations of architectural rules and maintains consistency across the repository.

## Is my repository configured?

A repository is configured for decision audit when either `sdd/taxonomy/subsystems.yaml` or `sdd/decisions/approvals.jsonl` exists. If neither file exists, all decision-related surfaces report `skipped` (exit code 0) and specification processing proceeds without decision validation. A specification that declares `## Decisions` in an unconfigured repository is considered `invalid`.

## The `## Decisions` block

The `## Decisions` block uses a structured YAML format to declare architectural decisions. The schema includes:

- `schema_version`: Currently only version 1 is supported
- `document_id`: Unique identifier for the document (must match `[a-z0-9_-]+`)
- `entries`: List of decision entries, each with:
  - `id`: Unique entry identifier (must match `[a-z0-9_-]+`)
  - `statement`: The decision statement text
  - `relation`: One of `constrains`, `forbids`, or `requires`
  - `about`: List of topics this decision concerns
  - `targets`: List of affected code locations (using `sym:`, `file:`, or `dir:` prefixes)
  - `revision`: Revision number (default 1)
  - `previous_revision`: Optional previous revision number
  - `contradicts`: List of `DecisionRef` objects this decision contradicts
  - `supersedes`: List of `DecisionRef` objects this decision supersedes
  - `rationale`: Explanation for the decision
  - `rejected_alternatives`: List of alternatives considered and rejected

Each decision entry has a stable identity of the form `adr:spec:<document_id>#<entry_id>`.

Common error codes include:
- `SPEC_BLOCK_MISSING`: No decisions block found
- `SPEC_BLOCK_INVALID_YAML`: Malformed YAML in the block
- `SPEC_INVALID_ID`: Invalid document or entry ID
- `SPEC_EMPTY_ABOUT`: Empty 'about' field
- `SPEC_EMPTY_TARGETS`: Empty 'targets' field
- `SPEC_DUPLICATE_ENTRY_ID`: Duplicate entry ID
- `SPEC_DANGLING_REF`: Reference to non-existent decision
- `SPEC_UNKNOWN_FIELD`: Unknown field in the block

The `## Decision Waivers` block follows the same structure and allows documenting approved exceptions to decisions.

## Findings and the exit matrix

| status | exit | meaning |
|---|---|---|
| pass | 0 | No blocking finding - all decisions are valid and consistent |
| skipped | 0 | Repository not configured, no decision validation performed |
| conflict | 1 | Unresolved explicit `contradicts` link between decisions |
| invalid | 2 | Malformed block, unknown taxonomy ID, unresolved target, bad supersession, or unconfigured repo with a decisions block |
| incomplete | 3 | Inventory overflow, unstable snapshot, truncated impact, stale or missing generated sections, or operational failure |

Advisory findings (potential-conflict, possible-supersession, blast-radius, evidence-gap) never block specification processing but provide warnings about potential issues.

## Approval and publication

Approval makes a decision authoritative by binding it to a specific git commit. Each approval creates an entry in `sdd/decisions/approvals.jsonl` with:

- `kind`: Type of approval (`spec`, `seed`, `retirement`, or `waiver`)
- `batch_id`: Shared identifier for related approvals
- `spec_path`: Path to the specification file
- `document_id`: Document identifier
- `entries`: List of decision references with their revisions
- `block_sha256`: SHA-256 hash of the canonical decision block
- `commit`: Git commit hash that approved these decisions
- `actor`: Author of the approving commit
- `recorded_at`: Timestamp of approval recording

The `GitCommitApprovalAdapter` verifies approvals by checking:
- The commit exists in the repository
- The commit is an ancestor of the base branch
- The commit author matches the recorded actor
- The decision block at the commit matches the recorded hash
- The current decision block matches the recorded hash (no edits after approval)

Editing a decision block after approval makes it non-authoritative until a new approval entry is recorded.

The `wikitoolkit decisions publish --batch <id>` command publishes all decisions in a batch as wiki pages, operating in an all-or-nothing, idempotent manner. Retirement entries mark decisions as superseded or obsolete.

## Seed procedure

1. Commit seed ADRs under `docs/decisions/` (flat frontmatter + `## Decision Metadata` block) in one commit
2. Record one `kind: seed` entry per file, sharing a batch id, pointing at that commit
3. Merge the PR with a **merge commit** - a squash merge rewrites the commit SHA and the seed batch will no longer verify
4. After merge: `wikitoolkit decisions publish --batch seed-architecture-rules-v1`

The merge-commit requirement is critical because this repository uses merge commits for PRs (e.g., "Merge pull request #1897"), which preserve the original commit SHAs. A squash merge would orphan the seed commit SHA and break verification.

## Commands

- `wikitoolkit spec governing <spec>` - Show governing decisions for a specification
- `wikitoolkit spec consequences render|check <spec>` - Render or check consequences of decisions
- `python -m scripts.sdd.check_spec_consequences <spec> [--json] [--render] [--advisory]` - Script interface for consequence checking
- `MCP wiki_spec_consequences(spec_path, mode, budget_tokens)` - Machine-copilot interface for consequence checking
