# wikitoolkit inbox

*FEAT-626. Spec: `sdd/specs/wikitoolkit-new-ingestion.spec.md`.*

`wikitoolkit inbox` is a drop-folder ingestion pipeline. You put documents
in the repository's inbox directory (default `inbox/`) and run the command.
For each document, it:

1. triages the document;
2. ingests it;
3. classifies it against the charter taxonomy;
4. links it to existing pages;
5. writes it to the wiki and projects it to Markdown;
6. verifies what was written;
7. only then archives the original.

```bash
wikitoolkit inbox --dry-run --json      # preview: triage, classify and plan links only
wikitoolkit inbox                       # process everything, oldest first
wikitoolkit inbox --limit 5             # at most 5 documents
wikitoolkit inbox --no-archive          # persist and verify, but leave the originals in place
```

The command is CLI-only; there is no MCP tool for the inbox.

## Pipeline

Each document goes through these stages in order:

| # | Stage | Model | What happens |
|---|---|---|---|
| 1 | Discover | — | Walks the inbox recursively without following symlinks and ignores dot-files and dot-dirs. Files are sorted by modification time, then by relative path, and `--limit` is applied. |
| 2 | Acquire | — | Text formats (`.md .markdown .txt .text .rst .mdx`) are read directly. Every other format goes through a `parrot_loaders` loader. |
| 3 | Identity recovery | — | If an earlier run already ingested the file, the command finds that run's source and `doc_id` again, so a re-run resumes the document instead of duplicating it. Fireflies transcripts are detected too. |
| 4 | Triage | lightweight, then heavy | Stage 0 heuristics use no model. Stage 1 uses the lightweight model. Stage 2 runs only in the gray zone and uses the heavy model. Novelty scoring uses no model. |
| 5 | Ingest | heavy | `WikiIngestOrchestrator` → PageIndex. This creates the source and its child pages. |
| 6 | Classify | lightweight | Assigns a kind from the taxonomy, a summary and tags, using the first 24,000 characters. |
| 7 | Link | heavy | Builds link candidates from verbatim `sym:`/`file:` references and backticked paths, then from search, then from the tag index. The heavy model chooses among them from a 4,000-character excerpt. If the model fails, only the verbatim candidates are linked, as `references`. |
| 8 | Write | — | Writes the document page, tags and edges, then the Markdown projection and `index.md`, then the optional ADR candidate. |
| 9 | Verify | — | Checks the document page, its claimed child pages and the Markdown projection. |
| 10 | Archive | — | Moves the original to the archive and repoints the source manifest to the new path. |

The model calls in stages 4, 6 and 7 also run under `--dry-run`. A dry run
stops after stage 7 and appends a `DRY_RUN` line to the bookkeeper log. Apart
from that log line, nothing is ingested, written, projected or archived.

### Triage outcomes

| Condition | Result |
|---|---|
| More than 5 MiB of extracted text | Discard, so the row is `rejected` |
| Duplicate: same URI with the same content hash, or the same hash under another source | Discard, so the row is `rejected`. `--force` skips this check, and so does a resumed document. |
| Stage 1 or Stage 2 flags the document as sensitive | Discard, so the row is `rejected` |
| Composite score at or above the admit threshold | Admit, so the row is `admitted` |
| Still in the gray zone after Stage 2 | Archive category, so the row is `archived_category` |
| Unsafe path (symlink, or outside the inbox or the repository), no loader, decode error, empty text or a NUL byte | The row is `skipped` and the file stays in the inbox |
| Any other error: classifier failure or malformed output, verification problems, an invalid `date_format` at archive time | The row is `failed`, and the run moves on to the next document |

The inbox has **no file-suffix allowlist**. If a loader can read the file, it
is a candidate. Rejected documents are still archived, under
`<archive_dir>/<rejected_subdir>/`.

## Options

| Option | Meaning |
|---|---|
| `--path DIR` | Project directory whose `.parrot/wiki.json` and inbox are used. Default: the current repository. |
| `--dry-run` | Stop after triage, classification and link planning (see above). |
| `--limit N` | Process at most `N` documents, oldest first. A negative value is rejected. |
| `--charter PATH` | Charter YAML to use. Default: `.parrot/charter.yaml`. |
| `--lightweight-model SPEC` | Model for triage Stage 1 and classification. |
| `--model SPEC` | Heavy model for triage Stage 2, ingestion and link selection. |
| `--archive` / `--no-archive` | Archive originals after verification (the default), or keep them in place. With `--no-archive`, documents are still persisted and verified. |
| `--force` | Skip only the duplicate check. The size check, sensitivity screening, novelty scoring and the model stages still run. |
| `--json` | Print the run report as one JSON object on stdout. Diagnostics go to stderr. |

### Model resolution

Model specs have the form `provider:model`. Each model is taken from its
flag first, then from its environment variable:

- lightweight: `--lightweight-model`, then `WIKI_LIGHTWEIGHT_MODEL`;
- heavy: `--model`, then `WIKI_MODEL`.

When neither model is set and `PARROT_NO_AUTO_LLM` is unset, a detected
coding-agent CLI is used for both. When only one of the two is set, the
command exits with code 1. When both specs are identical, one client serves
both roles. The URL fetch timeout is fixed at 30 seconds.

## Configuration

Inbox settings live under the `inbox` key of `.parrot/wiki.json`. Every
field is optional.

```json
{
  "inbox": {
    "dir": "inbox",
    "archive_dir": ".parrot/archive",
    "rejected_subdir": "rejected",
    "markdown_dir": null,
    "date_format": "%Y-%m-%d",
    "stage_git": true,
    "max_candidates": 20,
    "lock_timeout": 30.0
  }
}
```

| Field | Default | Notes |
|---|---|---|
| `dir` | `inbox` | Must not be empty. |
| `archive_dir` | `.parrot/archive` | Must not be empty. |
| `rejected_subdir` | `rejected` | A single path segment: no `/`, `\` or `..`. |
| `markdown_dir` | `null`, which means `<storage_dir>/inbox` | Where the Markdown projection is written. |
| `date_format` | `%Y-%m-%d` | Date stamp in archived file names. It is only checked at archive time. |
| `stage_git` | `true` | Runs `git rm --cached` on an archived original that git tracked. |
| `max_candidates` | `20` | Link candidates offered per **document**, from 1 to 100. |
| `lock_timeout` | `30.0` | Seconds to wait for the wiki write lock. Must be ≥ 0. |

`dir`, `archive_dir` and `markdown_dir` may be absolute or relative to the
project root. None of them may be the repository root itself or point outside
it, and no two may be equal or nested inside one another. An invalid layout
exits with code 2.

If you move `markdown_dir` outside the storage directory, exclude it from
`wikitoolkit build` scanning. Otherwise the build indexes the projected pages
a second time.

### Taxonomy

The document taxonomy is closed: a document can only get a kind the taxonomy
lists. It is defined in the `taxonomy` section of the charter. Without that
section, these built-in kinds are used:

| Kind | Wiki category |
|---|---|
| `meeting` | summary |
| `briefing` | overview |
| `decision` | concept |
| `report` | synthesis |
| `memo` | summary |
| `note` (default) | concept |

A custom taxonomy is declared like this:

```yaml
taxonomy:
  default_kind: note        # must be one of the declared kinds
  max_tags: 8               # 1–32
  kinds:
    - id: incident-review   # kebab-case, unique
      description: Post-incident analysis
      category: synthesis   # must be a valid WikiPageCategory
      tag_hints: [incident, outage]
    - id: note
      description: Anything else
      category: concept
```

When the model answers with a kind that is not in the taxonomy, the document
falls back to `default_kind`. A malformed answer, or an adapter error, makes
the row `failed`.

## What gets written

Every page and edge the pipeline writes has `origin=authored` and
`asserted_by=agent:wikitoolkit-inbox`.

| Artifact | Details |
|---|---|
| Document page | Id `doc:<kebab-title, at most 48 chars>-<hash[:8]>`. Its category comes from the kind, or is `archive` for an archived-category decision. The body is frontmatter, including a `triage:` block, then the title and summary, then `## Related` and `## Sections`. |
| Child pages | The PageIndex pages generated during ingestion, each linked to the document page with a `part_of` edge (child → document). |
| Tags | ASCII-folded and kebab-cased. Duplicates and tags longer than 64 characters are dropped, and the list is capped at `max_tags`. Each tag becomes a `tag:<name>` page connected with a `tagged` edge. |
| Links | Edges to existing pages, each one checked against the store before it is written. The edge type is one of `references`, `relates_to`, `mentions`, `follows_up` or `supersedes`. |
| ADR candidate | Only when the kind is `decision` and `decisions.enabled` is true. It is an inferred, unreviewed record, and an existing one is reused. Review it with the normal ADR workflow. |
| Markdown projection | `<markdown_dir>/<category>/<flattened id>.md`, plus a regenerated `<markdown_dir>/index.md`. Both are written atomically. |

## Archive

After a document is verified, the original is moved to
`<archive_dir>/<stem>.<date><ext>`, for example
`.parrot/archive/design-notes.2026-10-03.md`.

- Subfolders inside the inbox are flattened.
- On a name collision a counter is added: `design-notes.2026-10-03-1.md`.
  An existing file is never overwritten.
- Rejected documents go to `<archive_dir>/<rejected_subdir>/` with the same
  naming.
- The source manifest is repointed to the new path and records `archived_to`
  and `archived_at`.
- If `stage_git` is true and git tracked the original, its removal is staged
  with `git rm --cached`.

**The processor never commits.** Review `git status` and commit the result yourself.

## Run report

In text mode, the command prints `Inbox: <status>=<n>, ...`, or `Inbox: empty=0`
when nothing was processed. With `--json`, it prints:

```json
{
  "inbox_dir": "...",
  "charter_version": "...",
  "charter_fingerprint": "...",
  "models": {"lightweight": "provider:model", "heavy": "provider:model"},
  "dry_run": false,
  "counts": {"admitted": 2, "rejected": 1},
  "documents": [
    {
      "source_uri": "...", "status": "admitted", "decision": "admit",
      "composite": 0.82, "decision_source": "auto",
      "kind": "meeting", "category": "summary", "tags": ["release-planning"],
      "links": [{"page_id": "...", "rel": "references", "why": "...", "title": "..."}],
      "doc_page_id": "doc:...", "markdown_path": "...", "archived_to": "...",
      "adr_candidate_id": null, "adr_candidate_reused": false,
      "fireflies_match": null, "verified": true, "error": null
    }
  ]
}
```

Each row's `status` is one of `admitted`, `archived_category`, `rejected`,
`skipped`, `failed` or `dry_run`. `verified` is `false` for dry-run rows and
rejected rows.

## Exit codes and concurrency

| Code | Meaning |
|---|---|
| `0` | No row failed. An empty inbox also exits 0. |
| `1` | At least one row is `failed`. Also: a missing charter, a missing model, or an invalid field in `wiki.json` (for example `rejected_subdir` or `max_candidates` out of range). |
| `2` | Usage error: the inbox directory is missing, the path layout is invalid, or `--limit` is negative. |
| `3` | The wiki write lock is busy because another inbox run or another writer holds it. With `--json`, nothing is printed. |

- **Whole-run lock.** The processor takes the wiki write lock once and holds
  it for the whole run. It polls every 50 ms, without blocking the event
  loop, until `lock_timeout` runs out. The CLI never takes the lock itself.
- **Per-document isolation.** A failing document produces a `failed` row, and
  the run continues with the next one.
- **Verify before archive.** An original is moved only after its pages and
  its Markdown projection are verified.
- **Re-runs are safe.** A document that was ingested but not archived is
  resumed under its existing identity. It is not duplicated.
