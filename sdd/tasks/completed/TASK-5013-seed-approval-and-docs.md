# TASK-5013: Seed approval batch + decision-audit docs page (M10c)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5001, TASK-5010, TASK-5012
**Assigned-to**: unassigned

---

## Context

Spec G4/G6, §3 Module 10 (approvals seed + docs), AC13/AC16/AC18. Decisions become authoritative only
through an approval batch bound to a git commit and recorded in the append-only
`sdd/decisions/approvals.jsonl` (spec §2 "Approval"). The nine seed rules committed by TASK-5012 are
approved as **one batch**: this task appends one `ApprovalEntry` per seed document, all sharing one
`batch_id`, each pointing at TASK-5012's seed commit as the approving commit (PLAN decision 7). It also
writes `docs/sdd/decision-audit.md` documenting block grammar, exit matrix, approval flow and seed
procedure (AC18).

**Merge-strategy constraint**: the recorded sha must survive into `dev`. This repository merges PRs with
merge commits ("Merge pull request #1897"), which preserve it; a squash merge would orphan the sha and
the seed batch would fail verification. The docs page must say so, and the PR description for FEAT-784
must request a merge commit.

---

## Scope

- Create `sdd/decisions/approvals.jsonl` with nine lines, one `ApprovalEntry` (`kind: "seed"`) per seed
  file: shared `batch_id` `seed-architecture-rules-v1`; `spec_path` = the seed file path;
  `document_id` = `seed-<rule-slug>`; `entries` = every `DecisionRef(decision_id=spec_decision_id(document_id,
  entry.id), revision=entry.revision)` of that block (rule 4 has two); `block_sha256` =
  `sha256(canonical_block_bytes(block)).hexdigest()`; `commit` = TASK-5012 seed commit sha (full 40 hex);
  `actor` = that commit's author as `git log -1 --format='%an <%ae>' <sha>` (TASK-5001's comparison form); `recorded_at` =
  UTC ISO-8601. Lines are canonical JSON (sorted keys, no spaces), one per line, trailing newline.
- Create `docs/sdd/decision-audit.md`.
- Create `T/test_seed_batch.py` (T = `packages/ai-parrot/tests/knowledge/wiki/decisions`).

**NOT in scope**: publishing the batch into the wiki plane (`wikitoolkit decisions publish --batch …` is
run by the maintainer after the PR merges); the seed files themselves (TASK-5012); template / prompt edits
(TASK-5011); any CI job.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/decisions/approvals.jsonl` | CREATE | Seed approval batch (9 entries, one batch id) |
| `docs/sdd/decision-audit.md` | CREATE | Grammar, exit matrix, approval flow, seed procedure |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_batch.py` | CREATE | Manifest ↔ seed files ↔ git verification tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.codec import spec_decision_id                         # added by TASK-4998
from parrot.knowledge.wiki.decisions.spec_entries import SEED_HEADING, canonical_block_bytes, parse_spec_decisions  # TASK-4999
from parrot.knowledge.wiki.decisions.approvals import ApprovalEntry, ApprovalManifest, GitCommitApprovalAdapter   # TASK-5001
```

### Existing Signatures to Use
```python
# Contracts from earlier tasks (spec §3 skeletons — not renegotiable)
# codec.py (TASK-4998)
def spec_decision_id(document_id: str, entry_id: str) -> str          # "adr:spec:<doc>#<entry>"
# spec_entries.py (TASK-4999)
SEED_HEADING = "## Decision Metadata"
def canonical_block_bytes(block: SpecDecisionsBlock) -> bytes
def parse_spec_decisions(text: str, *, source_path: str, heading: str = DECISIONS_HEADING) -> tuple[SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic]]   # seeds: heading=SEED_HEADING
# approvals.py (TASK-5001)
class ApprovalEntry(_Strict):
    kind: Literal["spec", "seed", "retirement", "waiver"]; batch_id: str; spec_path: str
    document_id: str; entries: list[DecisionRef]; block_sha256: str; commit: str; actor: str; recorded_at: str
class ApprovalManifest:
    entries: list[ApprovalEntry]                          # public attribute set in __init__ (TASK-5001)
    @classmethod
    def load(cls, path: Path) -> "ApprovalManifest"      # malformed line ⇒ DecisionError(APPROVAL_MANIFEST_INVALID)
    def for_document(self, document_id: str) -> list[ApprovalEntry]
class GitCommitApprovalAdapter:
    def __init__(self, root: Path, base_branch: str) -> None
    async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]
        # commit exists · ancestor of base (origin/<base>, or local base with APPROVAL_LOCAL_BASE) ·
        # blob at commit hashes to block_sha256 (spec/seed kinds only) · actor == `%an <%ae>` of the commit
```
Repository fact: recent PR merges are merge commits (`git log` shows "Merge pull request #1897 from
phenobarbital/feat-FEAT-773-delegated-auth-connections"), so a feature-branch sha survives into `dev`.

### Does NOT Exist
- ~~`sdd/decisions/`~~ and ~~`docs/sdd/decision-audit.md`~~ — created here.
- ~~a CLI command that writes approval entries~~ — none exists or is in scope; generate the nine lines with a throwaway script in your scratch dir (not committed), using the imports above.
- ~~one approval entry covering several documents~~ — `ApprovalEntry` has one `spec_path`/`document_id`; a multi-document batch is several entries sharing `batch_id`.
- ~~`DecisionService.review()` as an approval path~~ — review is never a publication path (spec §9 S10).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/decisions/approvals.jsonl", "action": "CREATE"},
    {"path": "docs/sdd/decision-audit.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_batch.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The approving commit is TASK-5012's seed commit — read its sha from TASK-5012's Completion Note and
  confirm with `git log --format='%H %an <%ae>' -- docs/decisions/` (exactly one commit expected).
- Do not edit any seed file after recording: an edit changes `block_sha256` and makes the records
  non-authoritative until a new entry is recorded (AC13). If a seed must change, re-commit seeds and
  record against the new sha.
- `approvals.jsonl` is append-only from now on; never rewrite lines in later work.
- Before the PR merges, ancestry holds only against the feature branch (`HEAD`), not `origin/dev` — the
  test therefore checks ancestry against `HEAD`.

---

## Implementation Blueprint

### Steps (in order)
1. Find the seed commit sha and its author (see Key Constraints) — *why*: it is the approving commit.
2. With a throwaway script in your scratch dir, parse each seed's `## Decision Metadata` block, compute
   `block_sha256`, build `ApprovalEntry` objects and write canonical JSON lines — *why*: hand-typed hashes
   are wrong; the adapter re-hashes the blob.
3. Write `docs/sdd/decision-audit.md` from the outline below — *why*: AC18.
4. Write and run `test_seed_batch.py` — *why*: AC16 "seed batch verifies through the adapter".
5. Commit the three files (separate commit from the seed commit) — *why*: the seed commit must not contain its own approval.

### `sdd/decisions/approvals.jsonl` (CREATE)
```text
# FILL IN: nine canonical JSON lines (no comments in the real file), one per seed, e.g. shape:
# {"actor":"<%an <%ae> of the seed commit>","batch_id":"seed-architecture-rules-v1","block_sha256":"<hex>","commit":"<40-hex>","document_id":"seed-clients-memoryless","entries":[{"decision_id":"adr:spec:seed-clients-memoryless#rule","revision":1}],"kind":"seed","recorded_at":"<UTC ISO-8601>","spec_path":"docs/decisions/clients-memoryless.md"}
#   — bounded by AC13/AC16: every value computed by the script, never typed
```
**Why**: JSONL keeps the manifest append-only and diff-friendly; one batch id makes the nine records
publish all-or-nothing (AC12).

### `docs/sdd/decision-audit.md` (CREATE)
````markdown
# Decision Audit (FEAT-784)

## What it does
<!-- FILL IN: two paragraphs — governing dossier (consumer) + consequence gate (verifier); zero LLM calls -->

## Is my repository configured?
Configured when `sdd/taxonomy/subsystems.yaml` or `sdd/decisions/approvals.jsonl` exists. Otherwise every
surface reports `skipped` (exit 0) and `/sdd-spec` proceeds; a spec that declares `## Decisions` in an
unconfigured repository is `invalid`.

## The `## Decisions` block
<!-- FILL IN: grammar from spec §3 M2 — schema_version, document_id, entries (id, statement, relation
     constrains|forbids|requires, about, targets sym:/file:/dir:, revision, previous_revision, contradicts,
     supersedes, rationale, rejected_alternatives); id charset [a-z0-9_-]+; identity adr:spec:<doc>#<entry>;
     the SPEC_* error codes; `## Decision Waivers` shape -->

## Findings and the exit matrix
| status | exit | meaning |
|---|---|---|
| pass | 0 | no blocking finding |
| skipped | 0 | repository not configured, no block |
| conflict | 1 | unresolved explicit `contradicts` link |
| invalid | 2 | malformed block, unknown taxonomy id, unresolved target, bad supersession, unconfigured repo with a block |
| incomplete | 3 | inventory overflow, unstable snapshot, truncated impact, stale or missing generated sections, operational failure |
<!-- FILL IN: advisory findings (potential-conflict, possible-supersession, blast-radius, evidence-gap) never block -->

## Approval and publication
<!-- FILL IN: approval = commit on base_branch setting **Status**: approved; one approvals.jsonl entry per
     document (spec path, document_id, entries+revisions, sha256 of canonical block, commit, actor);
     adapter checks; editing the block after approval ⇒ non-authoritative until a new entry;
     `wikitoolkit decisions publish --batch <id>` all-or-nothing, idempotent; retirement entries -->

## Seed procedure
1. Commit seed ADRs under `docs/decisions/` (flat frontmatter + `## Decision Metadata` block) in one commit.
2. Record one `kind: seed` entry per file, sharing a batch id, pointing at that commit.
3. Merge the PR with a **merge commit** — a squash merge rewrites the sha and the seed batch no longer verifies.
4. After merge: `wikitoolkit decisions publish --batch seed-architecture-rules-v1`.

## Commands
`wikitoolkit spec governing <spec>` · `wikitoolkit spec consequences render|check <spec>` ·
`python -m scripts.sdd.check_spec_consequences <spec> [--json] [--render] [--advisory]` ·
MCP `wiki_spec_consequences(spec_path, mode, budget_tokens)`.
````

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_batch.py` (CREATE)
```python
"""FEAT-784 M10: the committed seed batch verifies against the seed files and git (AC13, AC16)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from parrot.knowledge.wiki.decisions.approvals import ApprovalManifest, GitCommitApprovalAdapter
from parrot.knowledge.wiki.decisions.spec_entries import SEED_HEADING, canonical_block_bytes, parse_spec_decisions

_REPO_ROOT = Path(__file__).resolve().parents[6]
_MANIFEST = _REPO_ROOT / "sdd/decisions/approvals.jsonl"
BATCH = "seed-architecture-rules-v1"


def _seed_entries():
    return [e for e in ApprovalManifest.load(_MANIFEST).entries if e.batch_id == BATCH]


def test_nine_seed_entries_share_one_batch() -> None:
    # FILL IN: 9 entries, all kind == "seed", one distinct commit, document_ids == seed-<stem> of docs/decisions/*.md
    raise NotImplementedError


def test_block_digests_match_committed_seed_files() -> None:
    # FILL IN: for each entry parse_spec_decisions(text, source_path=entry.spec_path, heading=SEED_HEADING) and assert
    #   hashlib.sha256(canonical_block_bytes(block)).hexdigest() == entry.block_sha256 — AC13
    raise NotImplementedError


def test_seed_commit_is_in_history() -> None:
    # FILL IN: subprocess.run(["git", "-C", str(_REPO_ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
    #   check=False).returncode == 0 — ancestry vs HEAD (origin/dev only after merge; PLAN decision 7)
    raise NotImplementedError


async def test_adapter_verifies_seed_entries() -> None:
    # FILL IN: GitCommitApprovalAdapter(_REPO_ROOT, <current branch name from `git rev-parse --abbrev-ref HEAD`;
    #   origin/<branch> exists once pushed, else the local ref + APPROVAL_LOCAL_BASE>).verify(entry, spec_text=<file text>) is True for every
    #   entry; an APPROVAL_LOCAL_BASE diagnostic is acceptable before merge — AC16
    raise NotImplementedError
```
**Why**: static digest + ancestry checks run anywhere; the adapter test is the AC16 evidence.
`subprocess` here is a sync test helper, not async production code.

### FILL IN checklist
- [ ] approvals.jsonl — nine computed lines
- [ ] docs page sections
- [ ] four test bodies (adapter base ref per TASK-5001)

---

## Acceptance Criteria

- [ ] `approvals.jsonl` holds nine `kind: seed` entries with one `batch_id`, each digest matching its seed file (AC13, AC16).
- [ ] The seed commit is in `HEAD`'s history and the adapter verifies every entry (AC16).
- [ ] `docs/sdd/decision-audit.md` documents block grammar, exit matrix, approval flow, seed procedure and the merge-commit requirement (AC18).
- [ ] `ruff check packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_batch.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_batch.py -q`

---

## Test Specification

See blueprint: `test_nine_seed_entries_share_one_batch`, `test_block_digests_match_committed_seed_files`,
`test_seed_commit_is_in_history`, `test_adapter_verifies_seed_entries`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Confirm TASK-5001, TASK-5010 and TASK-5012 are `done`; take the seed sha from TASK-5012's Completion Note.
3. Mark in-progress, generate the manifest, write the docs page and tests, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the three listed files; close with `scripts/sdd/close_task.sh TASK-5013 sdd-decision-audit verified`.
5. Note in the Completion Note that the FEAT-784 PR must be merged with a merge commit.

---

## Completion Note

Seat: mistral · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 233s · Tokens: 2.03M in / 10.8k out · Tokens: n/a

- Delivered files match the task list.
- Merge-tier validation: 219 passed, 1 failed — pre-existing env-gated test_backend_parity_is_reported. No review fixes.
- Seed batch seed-architecture-rules-v1: 9 kind=seed entries, commit d1e02ea06f (TASK-5012 seed commit), verified ancestor of HEAD.
- NOTE FOR HUMAN REVIEW: the approval records carry actor 'Jesus <jesuslarag@gmail.com>' (the git identity) but were generated by a coder seat, not approved by a human. Confirm or re-record before merge.
