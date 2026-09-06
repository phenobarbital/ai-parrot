# Bookstore Conceptual Relations — the book graph (FEAT-533)

Bookstore's catalog (`sdd/specs/bookstore-indexed-library.spec.md`) is a
flat list of fichas: one `BookCard` per book, searchable by topic. This
feature adds a **typed, provenance-bearing graph over that catalog** —
relations between books, and communities of related books — so a
research agent can discover an author's other works, sibling works of
the same tradition/era, or conceptually adjacent works, without those
connections happening to share a lexical keyword.

See also: `docs/bookstore-codex.md` (Codex installer + session guide),
`sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md` (the
full design spec this document summarizes for users).

## Relation types and their determinism

Every edge in the graph carries a `rel` (kind), an `origin`, a
`weight`, and — for LLM-derived edges — a `confidence` and a
`rationale`. Three families, in increasing order of "trust the exact
number less, but the signal is richer":

| `rel` | `origin` | Computed from |
|---|---|---|
| `same_author` | `deterministic` | Shared author, slug-normalised (accents/case collapse; single-initial or non-Latin fallback slugs are excluded to avoid false positives) |
| `shares_topic` | `deterministic` | Jaccard similarity over slugified topics, ≥ 0.2; edge weight **is** the Jaccard score |
| `same_tradition` | `deterministic` | Shared tradition/school, slug-normalised |
| `same_genre` | `deterministic` | Equal, classified (non-`"other"`) genre |
| `same_era` | `deterministic` | `\|year_a - year_b\| ≤ 50`, or an equal period slug |
| `same_language` | `deterministic` | Both books have the same language set |
| `influenced_by` | `llm` | LLM judges the source book was influenced by the candidate — **directed** |
| `responds_to` | `llm` | LLM judges the source book responds to/critiques the candidate — **directed** |
| `parallels` | `llm` | LLM judges the two books explore similar ideas independently — symmetric |
| `contrasts_with` | `llm` | LLM judges the two books present opposing views — symmetric |
| `same_community` | `community` | Both books ended up in the same detected community (derived, not an input to clustering) |

Deterministic relations (Stage 1) run with **no LLM**, over every
visible book, and are always recomputed from scratch for any book
touched by a `bookstore relate` run — stale edges never linger.

## The `relate` cost model and the judgement log

Conceptual relations (`influenced_by`/`responds_to`/`parallels`/
`contrasts_with`) are the only part of the graph that costs an LLM
call, and they are **never** computed implicitly:

- **Bounded to one prompt per book.** `bookstore relate` sends at most
  **N prompts for N target books** — never one prompt per candidate
  pair. Each prompt includes the source book's brief plus up to 8
  pre-filtered candidates (Stage-1 deterministic neighbours, unioned
  with a catalog-search shortlist).
- **A confidence floor of 0.5.** Every candidate the model judges is
  logged in a `relation_judgements` table — including `rel="none"` and
  below-floor verdicts — but only judgements with `confidence ≥ 0.5`
  and `rel != "none"` become a graph edge.
- **Zero cost on re-run.** A second `bookstore relate --all` issues
  **zero** LLM prompts, because every already-judged pair is skipped.
  Pass `--force` to re-ask (e.g. after a book's summary/topics
  changed).
- **Never automatic.** Plain `bookstore add`/`add-folder` never touch
  the relation LLM — opt in per book with `--relate`, or run
  `bookstore relate` explicitly.
- **Community labelling** costs one additional prompt **per detected
  community** (not per book), only when Stage 3 runs with an LLM
  configured; it falls back to a deterministic label
  (`derive_community_label`, or the sole/centroid book's title) when
  no LLM is configured or labelling fails for one community.

## Communities

`bookstore relate` (or the standalone `--communities-only` pass) also
clusters the merged project+global book graph with the same
Leiden/Louvain algorithm wikitoolkit uses (Leiden by default, silent
Louvain fallback when the optional `leidenalg`/`python-igraph`
dependencies aren't installed — `bookstore communities` always shows
which one ran). Every relation kind contributes a clustering weight
(`influenced_by` weighs the most, `same_language` the least); a book
needs ≥ 3 visible books in the library before communities are computed
at all.

Communities are **re-derived on every run** — community ids are
membership hashes, so they change whenever membership changes — and
persisted as: `community_id`/`community_label` stamped on every
member's ficha, plus one row per community (label, algorithm, size,
cohesion, member ids, inter-community relations) in a `communities`
table (written once, to the project DB when one exists, else global).

## Agent tools (read-only, MCP)

Three new `bookstore_*` tools, on top of the seven from the base
catalog (ten total):

| Tool | LLM? | Purpose |
|---|---|---|
| `bookstore_related_books` | no | Books related to one book (`rel`/`depth 1-2`/`top_k` filters); cite the `origin` |
| `bookstore_communities` | no | Every detected community, member briefs |
| `bookstore_get_community` | no | Full detail for one community, incl. inter-community relations |

`bookstore_search` also gained an opt-in `expand_related` flag: when
`True`, the catalog shortlist is widened with each candidate's
depth-1 related books (pure SQL, no extra LLM call) before the
`max_books` cap is applied.

### Funnel step 1b — expand by relations

The research funnel now reads: `bookstore_catalog_search` → **1b.
expand by relations** (`bookstore_related_books` on the best hit, or
`bookstore_communities` for thematic/comparative questions) →
`bookstore_get_toc` → `bookstore_search_book`/`bookstore_search` →
`bookstore_read_section`. When a relation drives a claim, cite its
origin — e.g. *"the library links these as parallels (LLM-inferred,
0.7)"* vs *"same author (deterministic)"*.

## `export-wiki` and namespace registration

`bookstore export-wiki` is a **one-way, CLI-only** projection of the
book graph into a dedicated wikitoolkit plane (never imported on the
MCP read path — `parrot.knowledge.wiki` never enters `sys.modules`
there):

- One page per book (`category="book"`), one edge per relation
  (`extracted` provenance for deterministic/community edges, `inferred`
  for LLM ones).
- `graph.html`/`graph.json` (same renderer wikitoolkit's own `build`
  uses), so `wikitoolkit communities --kinds book` and the interactive
  graph work over the exported plane.
- By default also registers namespace `bookstore` — into the project's
  `.parrot/wiki.json` (relative store path) when run from a git repo,
  or `${PARROT_HOME:-~/.parrot}/wikis.json` (absolute path) with
  `--global` or when no git root is found — so `wikitoolkit query --ns
  bookstore` resolves it. `--no-register` skips this; re-running
  against the *same* store is a no-op success, a conflicting existing
  entry under a *different* store is refused (remove it first with
  `wikitoolkit ns remove bookstore`).
- Idempotent: `wiki.db` is rebuilt from scratch on every export (no
  delete-edges primitive exists to prune stale edges surgically), so a
  relation that no longer holds never lingers in the exported plane.

## Degradation matrix

| Configuration | Stage 1 (deterministic) | Stage 2 (LLM relations) | Stage 3 (communities) |
|---|---|---|---|
| LLM configured (`PARROT_BOOKSTORE_LLM`) | full | full, floor 0.5, judgement log | full, LLM labels |
| No LLM configured | full | skipped (`skipped_llm_reason` set, exit 0) | full, deterministic/title labels |

Read tools (`bookstore_related_books`, `bookstore_communities`,
`bookstore_get_community`) are SQL-only and work identically in both
rows — they never touch an LLM, whether or not one is configured.

## CLI reference

```bash
bookstore relate [BOOK_ID...] [--all] [--no-llm] [--communities-only] \
                  [--force] [--resolution F] [--llm SPEC]
bookstore related BOOK_ID [--rel REL] [--depth N] [--json]
bookstore communities [--json]
bookstore export-wiki [--out DIR] [--global] [--no-register]
bookstore add FILE --relate            # relate the new book after ingest
bookstore add-folder DIR --relate      # relate each file, communities once at the end
bookstore list --by-community          # group the inventory by community
```
