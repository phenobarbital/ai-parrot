---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wiki, decisions, adr, graphindex, namespaces]
---

# Feature Specification: Prefixed ADR Aliases

**Feature ID**: FEAT-760
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.29.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The ADR decision plane (FEAT-578) identifies every architectural decision by a
bare alias, `ADR-<n>`. The grammar admits no prefix: the regex is literally
`\bADR[\s\-/]?(\d{1,5})\b` (`decisions/parser.py:45`). Each record's internal
`decision_id` is path-derived and therefore unique, but the alias — the thing a
code comment cites and a `supersedes:` header names — is a flat global
namespace shared by every ADR visible in one wiki plane.

That is fine today because no repository in the organization has written a
single ADR. It stops being fine immediately: ai-parrot is about to publish its
architectural decisions to dozens of consuming repositories (fieldsync,
flowtask, querysource, the TypeScript frontends, and every repo running the SDD
flow), and those repositories will author **their own** ADRs alongside the
imported ones. The moment fieldsync has an `ADR-7` and also holds parrot's
`ADR-7`, `_alias_index` sees two records claiming one alias, drops the alias
from the map entirely, and emits `ADR_REFERENCE_AMBIGUOUS`
(`decisions/ingest.py:62-79`). Every citation to either decision stops
resolving. The records survive; the ADR → symbol anchoring and the
`supersedes` graph do not.

The failure is quiet. `ADR_REFERENCE_AMBIGUOUS` is a sync diagnostic, not an
error: the build succeeds, `adr lookup` simply returns nothing, and an agent
asking "why is this code like this?" gets an empty answer rather than a wrong
one — which is better than wrong, and still a silent loss of exactly the
knowledge the publication effort exists to deliver.

Worse, the current grammar actively mis-parses the obvious workaround. A
human who writes `FS-ADR-3` to disambiguate gets `ADR-3`: the `\b` before
`ADR` matches after the hyphen, so the prefix is silently discarded and the
citation collides anyway.

### Goals

- A decision alias MAY carry a repository/namespace prefix: `PARROT-ADR-7`,
  `FS-ADR-3`. Prefixed aliases from different origins never collide.
- The bare `ADR-<n>` form keeps working exactly as it does today, in ADR
  files, in `supersedes:` headers, and in code citations.
- The wiki decision plane and the GraphIndex citation extractor continue to
  agree, span for span, on what text is a design reference — the invariant
  the current code comment at `decisions/parser.py:37-44` exists to protect.
- A repository can declare which prefix it owns and which foreign prefixes it
  expects to host, so an unrecognized prefix degrades predictably instead of
  silently.

### Non-Goals (explicitly out of scope)

- `adr publish` / `adr pull`, distributable ADR sets, the pull lock file, and
  GitHub authentication. That is the follow-on feature; it is blocked on a
  design document that has not been written yet. This spec only removes the
  identity collision that would make it unsafe.
- Writing real ADR files under `docs/adr/decisions/`. The repository contains
  none today and this feature adds none.
- Migrating or renumbering existing ADRs — there are none to migrate.
- Multiple citations per comment or docstring. `normalize_adr_alias` returns
  only the first match in a block (`decisions/evidence.py:147,160`); that
  limitation is preserved unchanged.
- Prefixing `RFC-<n>` references. RFCs are an external numbering space;
  namespacing them means nothing. The shared prefix group matches them
  lexically — that is what keeps the two planes span-identical — but
  `_register` DISCARDS the prefix when the kind is `RFC`, so every RFC
  Rationale node keeps the title it has today (Q1, resolved).

---

## 2. Architectural Design

### Overview

The change is one grammar, applied at two layers that are deliberately kept
apart:

**Lexical layer (pure, config-free).** Both regexes gain an optional prefix
group. This layer is where the two planes must agree span-for-span. The canonical form becomes `<PREFIX>-ADR-<n>`, where `<PREFIX>` matches
`[A-Za-z][A-Za-z0-9]*` and is upper-cased on normalization; the number keeps
its existing `[\s\-/]?` separator and `\d{1,5}` bound, and leading zeros are
still stripped. This layer answers only "is this text a design reference, and
what are its parts?". It is where the two planes must agree, and the agreement
is enforced by a parity test that compares match spans and extracted triples
over a shared corpus. Compact citation-shaped prefixes matching
`^(?:ADR|RFC)[0-9]{1,5}$` (case-insensitive) are reserved: config rejects them,
and both citation regexes exclude them before consuming a prefix. Thus
`ADR1-ADR-2` retains both old references, and `ADR1-RFC-2` retains its ADR
match in both planes. Other alphanumeric prefixes remain valid.

**Resolution layer (config-aware, BOTH planes).** `normalize_adr_alias` gains an
optional `known_prefixes` argument, and `CodeExtractor` gains a matching
constructor parameter so GraphIndex applies the SAME allowlist (Q1, resolved:
the planes agree on labels, not only on spans). When it is `None` or empty — every
repository that exists today — a syntactic prefix is **ignored** and the token
normalizes to the bare `ADR-<n>`, which is byte-for-byte today's behavior. A
prefix is honored only when it appears in the repository's configured
allowlist. This is what makes the feature a no-op for unconfigured repos and
what keeps prose like `# see-ADR-3: ...` resolving the way it does now instead
of becoming a phantom `SEE-ADR-3` — in the wiki's alias map AND in GraphIndex's
Rationale node titles.

`known_prefixes` is maintained by hand in `.parrot/wiki.json` (Q2, resolved).
It is NOT derived from whatever `adr pull` has installed: that would couple this
feature's configuration to a feature that does not exist yet, and an allowlist
is a statement about what this repository agrees to trust — the kind of thing a
human writes down.

ai-parrot's own `local_prefix` is **`PARROT`**, frozen before the first ADR is
written (Q3, resolved). Changing it later invalidates every citation that used
the bare form, so it is fixed now, while the cost of being wrong is zero.

Citation resolution then uses a two-step lookup: the citation's canonical alias
is tried against the alias map first; if the citation was bare and the project
declares a `local_prefix`, `<local_prefix>-ADR-<n>` is tried second. That lets
a repository's own code keep writing `# ADR-3` while its ADR files carry the
fully qualified `FS-ADR-3`. At each candidate, check the ambiguous-alias set
BEFORE the map: ambiguity returns `ADR_REFERENCE_AMBIGUOUS` immediately and
never falls through to another candidate. An exact hit also ends the lookup.
Only an absent, unambiguous bare alias may try the local candidate.

A RECOGNIZED prefixed alias that has no record returns `ADR_REFERENCE_MISSING`
and is never retried as bare. An UNLISTED syntactic prefix is deliberately
removed during normalization, even in a configured repository; its resulting
bare alias follows the ordinary exact/local lookup. For example, with only
`FS` allowed, `XX-ADR-3` may resolve `ADR-3` or `FS-ADR-3`. This compatibility
choice does not detect misspelled or undeclared namespaces. AC8 applies only
to recognized prefixes; it is not a guarantee against all namespace typos.

ADR identity is never rewritten. `parse_adr` does not inject `local_prefix`
into a bare `id:`; a file that declares `ADR-7` owns the alias `ADR-7`. This
matters for the follow-on `pull`: a copied ADR file must keep the identity its
author gave it, not acquire the identity of whatever repository it landed in.

### Component Diagram

```
                     ┌──────────────────────────────┐
  lexical layer      │  <PREFIX>-ADR-<n> grammar     │
  (config-free,      │  prefix? + kind + number      │
   parity-tested)    └───────┬──────────────┬───────┘
                             │              │
          decisions/parser.py│              │graphindex/extractors/code.py
           ADR_REFERENCE_RE  │              │ _CITATION_RE  (keeps RFC)
                             ▼              ▼
              normalize_adr_alias(     _register(prefix, kind,
                text, known_prefixes)    number, target)
                             │              │
  resolution layer           │              └──→ Rationale node titled
  (both planes)              │                   "<PREFIX>-ADR-<n>"
                             ▼
         ingest._alias_index  →  exact alias  →  hit
                             └→  bare + local_prefix  →  hit
                             └→  neither  →  ADR_REFERENCE_MISSING
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `decisions/parser.py` `ADR_REFERENCE_RE` | modifies | optional prefix group; separator class for the number unchanged |
| `decisions/parser.py` `normalize_adr_alias` | extends signature | new optional `known_prefixes` arg; default preserves today's output |
| `decisions/parser.py` `FILENAME_ID_RE` | modifies | optional `<prefix>-` before digits; parser accepts the candidate only for allowed prefixes |
| `decisions/parser.py` `parse_adr` | modifies | identity precedence and `supersedes` accept prefixed aliases |
| `decisions/models.py` `DecisionConfig` | extends | `local_prefix`, `known_prefixes` fields |
| `decisions/ingest.py` `_resolve_citations` | modifies | two-step lookup; passes config into normalization |
| `decisions/evidence.py` `extract_python_citations` | extends signature | threads `known_prefixes` to `normalize_adr_alias` |
| `graphindex/extractors/code.py` `_CITATION_RE` / `_register` | modifies | prefix captured, filtered through the allowlist, carried into the node title; discarded for `RFC` |
| `graphindex/extractors/code.py` `CodeExtractor.__init__` | extends signature | new optional `known_prefixes` param, same plain-data pattern as `tag_set` (`code.py:84`) |
| `graphindex/cli.py` `CodeExtractor(...)` | modifies | the single production construction site passes the allowlist through (`cli.py:132`) |
| `WikiProjectConfig.decisions` | unchanged | new fields arrive through the existing nested model (`project.py:695`) |

### Data Models

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class DecisionConfig(_Strict):
    """Project-level ADR settings; generation is opt-in and off by default."""

    # ... existing fields unchanged ...
    local_prefix: str | None = None
    known_prefixes: list[str] = Field(default_factory=list)
```

`local_prefix` is the alias prefix this repository owns. For ai-parrot it is
`"PARROT"` (Q3). The field DEFAULT stays `None` — a repository that has not
declared a prefix must behave exactly as it does today, so `PARROT` is written
into this repo's `.parrot/wiki.json`, never baked into the model.
`known_prefixes` is the hand-maintained set of prefixes this repository's plane
is allowed to honor (Q2); `local_prefix`, when set, is always treated as a member
whether or not it is listed. Both are upper-cased and validated against
`^[A-Za-z][A-Za-z0-9]*$`; an invalid value is a config error, not a silent
drop. Additionally reject compact citation-shaped names matching
`^(?:ADR|RFC)[0-9]{1,5}$` case-insensitively, so configured prefixes cannot
conflict with existing compact references.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py

def normalize_adr_alias(text: str, known_prefixes: frozenset[str] | None = None) -> str | None:
    """Return the canonical decision alias in ``text``, or ``None``.

    With ``known_prefixes`` unset or empty, a syntactic ``<X>-`` prefix is
    discarded and the result is the bare ``ADR-<n>`` — today's behavior,
    preserved so that unconfigured repositories and hyphenated prose are
    unaffected. A prefix is honored, and returned upper-cased as
    ``<PREFIX>-ADR-<n>``, only when it is a member of ``known_prefixes``.
    """

def split_decision_alias(alias: str) -> tuple[str | None, int]:
    """Split a canonical alias into ``(prefix_or_None, number)``."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Alias grammar (wiki) | yes | regex shape, `normalize_adr_alias` signature, identity precedence, canonical upper-casing all fixed in §2 | — |
| M2: Config surface | yes | field names, types, defaults, validation regex fixed in §2 | — |
| M3: GraphIndex parity | yes | regex shape and `_register` normalization fixed in §2 | — |
| M4: Citation resolution | yes | two-step lookup order and the no-implicit-fallback rule fixed in §2 | — |
| M5: Parity & regression tests | yes | corpus and invariants enumerated in §4 | — |
| M6: Documentation | yes | target file and sections enumerated below | — |

### Module 1: Alias grammar — wiki plane
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py`
- **Responsibility**: the optional-prefix grammar, canonical normalization,
  prefixed filename identity, and prefixed `supersedes` parsing.
- **Depends on**: nothing in this spec (foundational).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py
  #   (modifies packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py:45)

  #: ``FS-ADR-3`` / ``ADR-42`` / ``ADR/042`` / ``ADR 42`` -> canonical alias.
  #: The optional prefix group and the number's separator class are kept in
  #: lockstep with GraphIndex's ``_CITATION_RE``
  #: (graphindex/extractors/code.py:35). Do NOT widen either independently —
  #: M5's parity test fails if the two disagree on any span.
  ADR_REFERENCE_RE = re.compile(
      r"\b(?:(?!(?:ADR|RFC)\d{1,5}-)([A-Za-z][A-Za-z0-9]*)-)?ADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE
  )  # verified: decisions/parser.py:45

  #: A leading ``0042-`` or ``fs-0042-`` style filename prefix.
  FILENAME_ID_RE = re.compile(
      r"^(?:([A-Za-z][A-Za-z0-9]*)-)?0*(\d+)[-_]"
  )  # verified: decisions/parser.py:48

  def normalize_adr_alias(
      text: str, known_prefixes: frozenset[str] | None = None
  ) -> str | None:
      """Return the canonical alias in ``text``, or ``None``.

      An unlisted prefix is discarded, not rejected: the token degrades to
      the bare ``ADR-<n>`` so that unconfigured repositories behave exactly
      as they do today.
      """  # verified: decisions/parser.py:55

  def split_decision_alias(alias: str) -> tuple[str | None, int]:
      """Split a canonical alias into ``(prefix_or_None, number)``."""

  def parse_adr(
      rel_path: str, text: str, known_prefixes: frozenset[str] | None = None
  ) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]:
      """Parse one ADR document.

      Identity precedence is unchanged (frontmatter ``id`` -> H1 -> filename)
      and frontmatter/H1 candidates use ``normalize_adr_alias``.
      A numeric filename keeps its old alias. A prefixed filename supplies
      an alias ONLY if its upper-cased prefix is in ``known_prefixes``;
      otherwise it supplies NO candidate, never a degraded bare alias.
      With FS allowed, frontmatter ``FS-ADR-7`` and filename ``0007-...``
      still report ``conflicting ADR identifiers``.
      ``local_prefix`` is NEVER injected into a bare id.
      """  # verified: decisions/parser.py:236
  ```

### Module 2: Config surface
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
- **Responsibility**: declare and validate `local_prefix` / `known_prefixes`.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
  #   (modifies packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:75)

  class DecisionConfig(_Strict):
      local_prefix: str | None = None
      known_prefixes: list[str] = Field(default_factory=list)

      @field_validator("local_prefix", "known_prefixes")
      @classmethod
      def _validate_prefixes(cls, value): ...
          """Upper-case each prefix; reject anything not matching
          ``^[A-Za-z][A-Za-z0-9]*$`` or matching the reserved compact
          citation pattern ``^(?:ADR|RFC)[0-9]{1,5}$`` with a ValueError."""

      def effective_prefixes(self) -> frozenset[str]:
          """``known_prefixes`` plus ``local_prefix`` when it is set."""
  ```

### Module 3: GraphIndex parity and allowlist
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`,
  `packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py`
- **Responsibility**: match the same spans as M1, apply the same allowlist, and
  carry an allowed ADR prefix into the Rationale node's title, `citation_ref`
  and node id — never an RFC's.
- **Depends on**: M1's grammar (contract only — different file, no shared edit)
  and M2 (the caller resolves `effective_prefixes()` before constructing the
  extractor).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py
  #   (modifies graphindex/extractors/code.py:35)

  # Design-reference citations in comments/docstrings, e.g. "ADR-12",
  # "FS-ADR-3", "RFC 4180", "ADR/007". The optional prefix group mirrors
  # decisions/parser.py:ADR_REFERENCE_RE exactly; the two are parity-tested.
  _CITATION_RE = re.compile(
      r"\b(?:(?!(?:ADR|RFC)\d{1,5}-)([A-Za-z][A-Za-z0-9]*)-)?(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE
  )  # verified: graphindex/extractors/code.py:35

  class CodeExtractor:
      def __init__(
          self,
          tag_set: Optional[set[str]] = None,
          ignore_file: Optional[str] = None,
          known_prefixes: Optional[frozenset[str]] = None,
      ) -> None:
          """``known_prefixes`` is plain data, resolved from config by the
          CALLER — the extractor never imports WikiProjectConfig, keeping the
          FEAT-540 seam intact."""  # verified: graphindex/extractors/code.py:84

  def _register(
      prefix: Optional[str], raw_kind: str, number: str, link_target: Optional[str]
  ) -> None:
      """Register one citation node.

      ``norm`` becomes ``<PREFIX>-<KIND>-<n>`` only when ``prefix`` is a member
      of ``self._known_prefixes`` AND ``raw_kind`` is ``ADR``; otherwise it is
      ``<KIND>-<n>``. An RFC is NEVER prefixed — namespacing an external
      numbering space is meaningless (§1 Non-Goals). An unprefixed corpus, and
      any corpus in a repository with no configured prefixes, therefore produces
      byte-identical node ids to today's.
      """  # verified: graphindex/extractors/code.py:594
  ```
  Both `_CITATION_RE.finditer` call sites (`code.py:631`, `code.py:656`) pass
  the new group through; the docstring-scanning site at `code.py:631` and the
  comment-walking site at `code.py:656` are the only two. The single production
  construction site, `graphindex/cli.py:132`, passes `known_prefixes` in;
  `OdooCodeExtractor` (`extractors/odoo_code.py:165`) inherits `__init__`
  unchanged.

### Module 4: Citation resolution
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py`
- **Responsibility**: thread the effective prefix set into citation extraction
  and implement the two-step alias lookup.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py
  #   (modifies decisions/evidence.py:92)
  def extract_python_citations(
      rel_path: str, source: str, known_prefixes: frozenset[str] | None = None
  ) -> tuple[list[Citation], list[DecisionDiagnostic]]:
      """Find ADR references in comments and docstrings of one Python file."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
  #   (modifies decisions/ingest.py:62)
  def _alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]:
      """Map canonical alias -> decision_id, plus the ambiguous aliases.

      Keys on the FULL canonical alias, so ``PARROT-ADR-7`` and ``FS-ADR-7``
      are distinct entries and neither is marked ambiguous.
      """

  def _lookup_alias(
      alias: str,
      alias_map: dict[str, str],
      ambiguous_aliases: set[str],
      local_prefix: str | None,
  ) -> tuple[str | None, str | None]:
      """Resolve a citation alias to an id or a diagnostic code.

      Return (decision_id, diagnostic_code): success is (id, None);
      failure is (None, ADR_REFERENCE_AMBIGUOUS or ADR_REFERENCE_MISSING).
      Check the exact candidate for ambiguity before its map entry. Stop on
      ambiguity or a hit. Only an absent bare alias with ``local_prefix``
      may try ``<local_prefix>-ADR-<n>``; apply the same ambiguity-first rule
      there. A recognized prefixed alias is NEVER retried as bare.
      The caller attaches path/context to the returned diagnostic code.
      """
  ```
  `_resolve_citations` passes BOTH `_alias_index` outputs to `_lookup_alias`
  for each citation. The second `_alias_index` call in `refresh_decisions`
  remains a code-walk guard (`alias_map or ambiguous_aliases`), not a lookup.
  Thread `config.effective_prefixes()` into both `parse_adr` and
  `extract_python_citations`, and pass `config.local_prefix` into resolution.
  Cold and incremental sync must use this same resolution path.

### Module 5: Parity and regression tests
- **Path**: `packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py` (new),
  plus edits to `test_parser.py`, `test_evidence.py`, `test_ingest.py`, `conftest.py`
- **Responsibility**: pin the grammar, prove cross-plane parity, prove
  back-compat.
- **Depends on**: M1, M3, M4.

### Module 6: Documentation
- **Path**: `docs/guides/wiki-adr-decisions.md`
- **Responsibility**: document the prefix grammar, the two config keys, the
  resolution order, and the unlisted-prefix degradation.
- **Depends on**: M1–M4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_prefixed_alias_normalization` | M1 | `FS-ADR-3` with `{"FS"}` → `FS-ADR-3`; `fs-adr-3` → `FS-ADR-3` |
| `test_unlisted_prefix_degrades_to_bare` | M1 | `SEE-ADR-3` with `known_prefixes=None` → `ADR-3` (today's behavior) |
| `test_bare_alias_unchanged` | M1 | the existing `["ADR-42", "ADR/042", "ADR 42", "adr42"]` matrix still yields `ADR-42` under both prefix modes |
| `test_separators_graphindex_rejects_still_rejected` | M1 | `ADR_42`, `ADR--42`, `ADR - 42` stay `None` with and without prefixes configured |
| `test_prefixed_filename_supplies_alias` | M1 | `fs-0042-use-pgvector.md` → `FS-ADR-42` when `FS` is known |
| `test_conflicting_prefixed_ids_diagnose` | M1 | frontmatter `FS-ADR-7` + H1 `ADR-9` → `conflicting ADR identifiers` |
| `test_supersedes_accepts_prefixed_aliases` | M1 | `supersedes: FS-ADR-3, PARROT-ADR-4` → two `supersedes` links |
| `test_local_prefix_never_injected` | M1 | a bare `id: ADR-7` stays `ADR-7` even with `local_prefix="FS"` |
| `test_prefix_validation_rejects_bad_values` | M2 | `"1FS"`, `"F S"`, `""` raise; `"fs"` normalizes to `"FS"` |
| `test_effective_prefixes_includes_local` | M2 | `local_prefix="FS"` is a member even when absent from `known_prefixes` |
| `test_graphindex_node_title_carries_prefix` | M3 | `# FS-ADR-3` with `known_prefixes={"FS"}` yields a Rationale node titled `FS-ADR-3` |
| `test_graphindex_unlisted_prefix_degrades` | M3 | `# see-ADR-3` with no prefixes configured yields a node titled `ADR-3`, not `SEE-ADR-3` |
| `test_graphindex_never_prefixes_rfc` | M3 | `# FS-RFC-2119` with `known_prefixes={"FS"}` yields `RFC-2119` |
| `test_graphindex_unconfigured_ids_unchanged` | M3 | with `known_prefixes=None`, every node id, title and `citation_ref` is byte-identical to the pre-change run, including for hyphenated prose |
| `test_graphindex_allowlist_matches_wiki_labels` | M3 | over the parity corpus and one allowlist, GraphIndex's ADR labels equal the wiki's aliases |
| `test_distinct_prefixes_are_not_ambiguous` | M4 | two records `PARROT-ADR-7` / `FS-ADR-7` both resolve; no `ADR_REFERENCE_AMBIGUOUS` |
| `test_bare_citation_falls_back_to_local_prefix` | M4 | `# ADR-3` resolves to `FS-ADR-3` when `local_prefix="FS"` |
| `test_prefixed_citation_never_falls_back_to_bare` | M4 | `# XX-ADR-3` with `XX` known and no record → `ADR_REFERENCE_MISSING` |
| `test_same_prefix_duplicate_is_still_ambiguous` | M4 | two files both claiming `FS-ADR-7` still raise `ADR_REFERENCE_AMBIGUOUS` |
| `test_compact_citations_are_not_prefixes` | M1/M3 | all old references survive in `ADR1-ADR-2`, `RFC1-ADR-2`, `ADR1-RFC-2`; compare all ADR spans and all GraphIndex labels |
| `test_reserved_prefixes_rejected` | M2 | reject `ADR1`, `adr00001`, `RFC2119` in both fields; accept `ADR123456` and `FS` |
| `test_unlisted_filename_is_not_identity` | M1 | with None, empty or unrelated prefixes, `fs-0042-topic.md` adds neither alias nor conflict, with and without explicit `id: ADR-7` |
| `test_unlisted_citation_uses_bare_resolution` | M4 | `XX-ADR-3` with only FS known resolves the exact bare record first, then local FS record if bare is absent |
| `test_local_fallback_ambiguity` | M4 | bare `ADR-7` plus duplicated `FS-ADR-7` returns ambiguous, not missing |
| `test_exact_ambiguity_stops_fallback` | M4 | duplicated bare `ADR-7` plus unique `FS-ADR-7` stays ambiguous |
| `test_exact_hit_precedes_local_ambiguity` | M4 | unique bare `ADR-7` wins even if `FS-ADR-7` is ambiguous |

### Integration Tests

| Test | Description |
|---|---|
| `test_lexical_parity_wiki_vs_graphindex` | over a shared corpus of prefixed, bare, RFC, near-miss and prose strings, both regexes produce identical match spans and identical `(prefix, number)` pairs for every `ADR` hit |
| `test_sync_with_two_origins_links_both` | an `adr sync` over a tree holding `PARROT-ADR-*` and `FS-ADR-*` ADRs plus Python citing each produces `explains` links for both sets |
| `test_unconfigured_repo_is_byte_identical` | a full `adr sync` of a tree with no prefixes configured produces the same records, links and diagnostics as the pre-change implementation |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py
- packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py
- packages/ai-parrot/tests/knowledge/graphindex/test_cli.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def parity_corpus() -> list[str]:
    """Strings both planes must agree on, span for span.

    Minimum regression corpus shared with the executable design probe.
    Compare ALL GraphIndex matches, not just the first search result.
    """
    return [
        "ADR-42", "ADR/042", "ADR 42", "adr42",
        "FS-ADR-3", "parrot-ADR-7", "PARROT-adr/007",
        "ADR_42", "ADR--42", "ADR - 42",
        "see-ADR-3 for why", "RFC 4180", "FS-RFC-2119",
        "ADR1-ADR-2", "RFC1-ADR-2", "ADR1-RFC-2", "ADR1-RFC2",
        "FS-ADR1-ADR-2", "ADR-99999", "ADR-123456",
        "x = \"see ADR-42\"",
    ]
```

---

## 5. Acceptance Criteria

- [ ] AC1 — `normalize_adr_alias("FS-ADR-3", frozenset({"FS"})) == "FS-ADR-3"`.
- [ ] AC2 — `normalize_adr_alias("FS-ADR-3")` (no prefixes configured) `== "ADR-3"`.
- [ ] AC3 — every string in the pre-change `test_alias_normalization` and
      `test_separators_graphindex_rejects_are_not_references` matrices yields
      its pre-change result under both prefix modes.
- [ ] AC4 — `ADR_REFERENCE_RE` and `_CITATION_RE` return identical match spans
      and identical `(prefix, number)` pairs for every `ADR` hit in the parity
      corpus; the test fails loudly if either regex is edited alone.
- [ ] AC5 — a plane holding `PARROT-ADR-7` and `FS-ADR-7` resolves citations to
      both and emits no `ADR_REFERENCE_AMBIGUOUS`.
- [ ] AC6 — two records claiming the SAME canonical alias still emit
      `ADR_REFERENCE_AMBIGUOUS` and still drop the alias from the map.
- [ ] AC7 — a bare `# ADR-3` citation prefers a unique exact `ADR-3` record.
      Only when that alias is absent and unambiguous does `local_prefix="FS"`
      permit fallback to `FS-ADR-3`; without a local prefix, absence is missing.
- [ ] AC8 — a RECOGNIZED prefixed citation whose alias has no record yields
      `ADR_REFERENCE_MISSING` and is never retried as the bare alias. Unlisted
      prefixes degrade to bare first and follow exact/local lookup.
- [ ] AC9 — `parse_adr` never injects `local_prefix` into a bare `id:`.
- [ ] AC10 — `DecisionConfig` rejects a prefix not matching
      `^[A-Za-z][A-Za-z0-9]*$` or matching reserved
      `^(?:ADR|RFC)[0-9]{1,5}$` case-insensitively, and upper-cases accepted values.
- [ ] AC11 — a GraphIndex run with `known_prefixes=None` produces byte-identical
      Rationale node ids, titles and `citation_ref` values to the pre-change run
      for EVERY corpus, hyphenated prose included. The probe measured what the
      allowlist exists to prevent: without it, `see-ADR-3` retitles to
      `SEE-ADR-3` and `FS-RFC-2119` to `FS-RFC-2119`.
- [ ] AC12 — `docs/guides/wiki-adr-decisions.md` documents the grammar, both
      config keys, the two-step resolution order, and the unlisted-prefix
      degradation.
- [ ] AC13 — `ruff check` clean on every changed file; the Validation Contract
      suites pass.
- [ ] AC14 — for the same allowlist, GraphIndex's ADR node label equals the
      wiki's canonical alias on every string in the parity corpus; the two
      planes agree on labels, not only on spans.
- [ ] AC15 — `_register` never prefixes an `RFC`: `FS-RFC-2119` yields
      `RFC-2119` even when `FS` is an allowed prefix.

- [ ] AC16 — unlisted prefixed filenames supply no identity candidate and
      introduce no conflict diagnostic; numeric filenames retain old behavior.
- [ ] AC17 — ambiguity in either exact or local-fallback candidates emits
      `ADR_REFERENCE_AMBIGUOUS`; ambiguous exact aliases never fall through,
      and exact hits win over any local candidate.

The revised design probe (`sdd/state/FEAT-760/grammar_parity_probe.py`) asserts
all-match parity, unconfigured labels, filename gating and lookup outcomes.
It exits nonzero on a violation. This is design evidence only: implementation
must still pass the real parser, extractor and sync tests, including node ids.


---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.parser import (            # verified: decisions/parser.py:55,236
    normalize_adr_alias, parse_adr, resolve_status, split_sections,
)
from parrot.knowledge.wiki.decisions.models import (            # verified: decisions/models.py:62
    ADR_REFERENCE_AMBIGUOUS, ADR_REFERENCE_MISSING, DecisionConfig,
    DecisionDiagnostic, DecisionLink, DecisionRecord, EvidenceRef,
)
from parrot.knowledge.wiki.decisions.evidence import (          # verified: decisions/evidence.py:92
    build_evidence, extract_python_citations,
)
from parrot.knowledge.wiki.decisions.codec import documented_decision_id, normalize_rel_path  # verified: decisions/parser.py:18
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py
FRONTMATTER_KEYS = ("id", "title", "status", "supersedes")                  # line 28
SECTION_NAMES = ("context", "decision", "consequences", "status")           # line 31
KNOWN_STATUSES = ("accepted", "proposed", "rejected", "deprecated", "superseded")  # line 34
ADR_REFERENCE_RE = re.compile(r"\bADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)   # line 45
FILENAME_ID_RE = re.compile(r"^0*(\d+)[-_]")                                # line 48
def normalize_adr_alias(text: str) -> str | None:                           # line 55
def parse_adr(rel_path: str, text: str) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]:  # line 236
    #   identity precedence block                                            # lines 290-306
    #   supersedes parsing block                                             # lines 332-340

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class DecisionConfig(_Strict):                                              # line 62
    enabled: bool = True                                                    # line 65
    adr_globs: list[str] = Field(default_factory=lambda: [...])             # line 66
    max_records: int = Field(default=10_000, ge=1, le=100_000)              # line 69
    timeout_seconds: int = Field(default=60, gt=0)                          # line 75
class DecisionRecord(_Strict):
    external_id: str | None = None                                          # line 158

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
def _alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]:  # line 62
async def _resolve_citations(root, code_paths, inventory) -> tuple[_ResolvedLinks, list[DecisionDiagnostic]]:  # line 84
    alias_map, ambiguous_aliases = _alias_index(inventory)                  # line 107
    alias_map, ambiguous_aliases = _alias_index(combined_inventory)         # line 272

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py
def extract_python_citations(rel_path: str, source: str) -> tuple[list[Citation], list[DecisionDiagnostic]]:  # line 92
    alias = normalize_adr_alias(token.string)                               # line 147 (comments)
    alias = normalize_adr_alias(docstring)                                  # line 160 (docstrings)

# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py
_CITATION_RE = re.compile(r"\b(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)  # line 35
class CodeExtractor:                                                        # line 65
    def __init__(self, tag_set: Optional[set[str]] = None,                  # line 84
                 ignore_file: Optional[str] = None) -> None: ...            # lines 86-88
def _register(raw_kind: str, number: str, link_target: Optional[str]) -> None:  # line 594
    norm = f"{raw_kind.upper()}-{int(number)}"                              # line 595
    for match in _CITATION_RE.finditer(node.summary):                       # line 631
    matches = list(_CITATION_RE.finditer(text))                             # line 656

# packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py
    extractor = CodeExtractor(ignore_file=str(ignore_file) if ignore_file else None)  # line 132
#   -> the ONLY production construction site; OdooCodeExtractor subclasses
#      CodeExtractor without overriding __init__ (extractors/odoo_code.py:165)

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                                         # line 588
    decisions: DecisionConfig = Field(default_factory=DecisionConfig, ...)  # line 695
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `normalize_adr_alias(known_prefixes=)` | `extract_python_citations` | keyword argument | `decisions/evidence.py:147,160` |
| `DecisionConfig.effective_prefixes()` | `_resolve_citations` | passed into citation extraction | `decisions/ingest.py:107` |
| `_lookup_alias` | `_alias_index` output | dict lookup + local-prefix retry | `decisions/ingest.py:62,107,272` |
| `_register(prefix, …)` | `_CITATION_RE` groups | positional argument | `graphindex/extractors/code.py:631,656` |
| `DecisionConfig` new fields | `.parrot/wiki.json` `decisions` object | nested Pydantic model | `wiki/project.py:695` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.config`~~ — there is no `wiki/config.py`; the project
  config model is `WikiProjectConfig` in `wiki/project.py:588`.
- ~~`decisions/parser.py` prefix support of any kind~~ — the current regex has a
  single capture group (the number) and no prefix concept.
- ~~`DecisionConfig.local_prefix` / `.known_prefixes`~~ — M2 creates both; they do
  not exist today.
- ~~`split_decision_alias`~~ — M1 creates it; no alias-splitting helper exists.
- ~~Markdown `sym:` link extraction in the ADR parser~~ — `parser.py` and
  `ingest.py` contain no `sym:` handling at all. ADR→symbol attachment comes
  only from Python comments and docstrings (`decisions/evidence.py:92-182`).
  The user guide's claim that other languages "use explicit Markdown `sym:`
  links" is not backed by code in this plane.
- ~~Multiple citations per comment block~~ — `normalize_adr_alias` uses
  `.search()`, returning only the first match.
- ~~`docs/adr/`, `docs/adrs/`, `docs/decisions/`~~ — none of the three default
  glob roots exists in this repository.
- ~~`sdd/templates/adr.md`~~ — there is no ADR template anywhere in the repo.

### Edit Sites (Blueprint Anchors)

Verified against: `028063330`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | MODIFY | `ADR_REFERENCE_RE = re.compile(r"\bADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)` | `parser.py:45` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | MODIFY | `FILENAME_ID_RE = re.compile(r"^0*(\d+)[-_]")` | `parser.py:48` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | MODIFY | `def normalize_adr_alias(text: str) -> str \| None:` | `parser.py:55` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | MODIFY | `    filename_match = FILENAME_ID_RE.match(filename)` | `parser.py:294` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | MODIFY | `    supersedes_raw = fields.get("supersedes", "")` | `parser.py:332` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | MODIFY | `    timeout_seconds: int = Field(default=60, gt=0)` | `models.py:75` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | `def _alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]:` | `ingest.py:62` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py` | MODIFY | `def extract_python_citations(rel_path: str, source: str) -> tuple[list[Citation], list[DecisionDiagnostic]]:` | `evidence.py:92` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | MODIFY | `_CITATION_RE = re.compile(r"\b(ADR\|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)` | `code.py:35` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | MODIFY | `        def _register(raw_kind: str, number: str, link_target: Optional[str]) -> None:` | `code.py:594` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | MODIFY | `    def __init__(` | `code.py:84` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py` | MODIFY | `    extractor = CodeExtractor(` | `cli.py:132` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py` | MODIFY | `    def test_alias_normalization(self, text):` | `test_parser.py:100` | 1 |
| `docs/guides/wiki-adr-decisions.md` | MODIFY | `## What Gets Parsed` | `wiki-adr-decisions.md` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 `field_validator` for prefix validation; `_Strict` base keeps
  unknown config keys an error, so the new fields must be real fields.
- Both regexes stay module-level compiled constants with the cross-reference
  comment intact — the comment at `parser.py:37-44` is load-bearing
  documentation and must be updated, not deleted.
- New keyword arguments are optional with defaults that reproduce today's
  behavior; no call site outside this feature is required to change.
- Google-style docstrings, strict type hints, 120 columns, `ruff check --fix`
  per changed file.

### Known Risks / Gotchas

- **The two regexes are a single contract split across two packages.** The only
  thing stopping a future edit from desynchronizing them is M5's parity test.
  It must compare match *spans*, not just extracted values, or a divergence in
  what counts as a boundary will pass unnoticed.
- **`ADR--42`, `ADR - 42` and `ADR_42` must stay non-matches.** The optional
  prefix group creates a new path to accidentally accept them: `ADR--42` could
  parse as prefix `ADR` + separator. **Measured** (`sdd/state/FEAT-760/grammar_parity_probe.py`,
  run 2026-10-27): all three still return `None` under the proposed regex, in
  both planes. Keep the probe's corpus as the test corpus.
- **The proposed grammar changes match SPANS, not values.** `FS-ADR-3` matched
  at `(3, 8)` under the old regex and matches at `(0, 8)` under the new one,
  while still normalizing to `ADR-3` for an unconfigured repo. Neither plane
  uses the span for identity — the wiki returns only the alias string, and a
  GraphIndex node id is `_make_node_id(file_path, f"__citation__{norm}")`
  (`code.py:598`) — so this is inert today. It is recorded because any future
  code that starts using the span inherits the shift.
- **The allowlist must reach BOTH planes or the labels diverge.** `CodeExtractor`
  defaults `known_prefixes` to `None`, which is the safe default but also means
  a caller that forgets to pass it silently gets unprefixed labels while the
  wiki gets prefixed ones. `graphindex/cli.py:132` is the only production
  construction site; AC14 is what catches a second one appearing later.
- **Hyphenated prose is the back-compat hazard.** `# see-ADR-3: ...` resolves
  to `ADR-3` today. The unlisted-prefix-degrades-to-bare rule is what preserves
  that; dropping the rule in favor of "any syntactic prefix is a prefix" would
  silently break every such comment into a phantom alias.
- **`local_prefix` is a resolution aid, never an identity rewrite.** Injecting
  it into a bare ADR `id:` would give a pulled ADR file the identity of the
  repository that received it — the exact bug the follow-on `pull` must not have.
- **Preserve ambiguous aliases throughout resolution.** `_alias_index` is
  called for citation resolution and for the refresh code-walk guard. The
  guard stays true for an ambiguity-only inventory. Lookup receives both
  outputs and checks ambiguity on exact AND local candidates.
- **GraphIndex node ids are content-derived** (`_make_node_id(file_path,
  f"__citation__{norm}")`, `code.py:598`). Changing `norm` changes node ids for
  prefixed citations only; AC11 pins that unprefixed corpora are unaffected.

### External Dependencies

None. No new packages.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-760; the `sdd-coder` engine
  gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M4 → M1 (imports `normalize_adr_alias`'s new signature) and → M2
    (calls `DecisionConfig.effective_prefixes()`).
  - M3 → M1 by contract only (the grammar is fixed in §2 and M3 edits
    different files, so M3 and M1 may run concurrently) and M3 → M2 for real
    (`graphindex/cli.py` calls `effective_prefixes()` before constructing the
    extractor).
  - M5 → M1, M3, M4 (asserts all three).
  - M6 → M1–M4 (documents their behavior).
  - M1 and M2 have no edge between them and are expected to run concurrently.
- **Shared files**: none across modules. `decisions/parser.py` belongs
  exclusively to M1; `graphindex/extractors/code.py` exclusively to M3, together with `graphindex/cli.py`. M5's
  edits to `test_parser.py` are the only tests M1 also plausibly touches —
  M1's task owns the production file, M5's owns every test file.
- **Exclusive resources**: none. No extension rebuild, lockfile or migration.
- **Cross-feature dependencies**: none. This feature must merge BEFORE any
  work on `adr publish` / `adr pull`.

---

## 8. Open Questions

- [x] Q1 — Should GraphIndex apply the same `known_prefixes` allowlist the wiki
      uses, or stay purely lexical? — *Resolved 2026-10-27*: **it applies the
      allowlist.** `CodeExtractor.__init__` already takes plain-data config
      (`tag_set`, `ignore_file`, `code.py:84-88`) and has exactly one production
      construction site (`graphindex/cli.py:132`), so passing a
      `frozenset[str]` costs one optional parameter and does not make the
      extractor import `WikiProjectConfig` — the FEAT-540 seam is untouched.
      Sub-decision (spec author's call, not the owner's): the prefix is
      DISCARDED for `RFC`, because namespacing an external numbering space
      means nothing.
- [x] Q2 — Hand-maintained `known_prefixes`, or derived from what `adr pull`
      installed? — *Resolved 2026-10-27*: **hand-maintained** in
      `.parrot/wiki.json`. Deriving it would couple this feature to one that
      does not exist yet.
- [x] Q3 — Is ai-parrot's `local_prefix` `PARROT`, frozen before the first ADR?
      — *Resolved 2026-10-27*: **yes, `PARROT`, frozen now.** The model default
      stays `None`; `PARROT` is written into this repository's config, so no
      other repository inherits it.

No open questions remain. The follow-on `adr publish` / `adr pull` feature is
blocked on its own design document, not on this spec.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; this spec was
> authored directly from an interactive design conversation, so §3b had no
> neutral brief to render — feeding the reviewer the spec itself is forbidden
> by the step's own rules) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

An adversarial `codex` review of the implemented diff is still expected at
`/sdd-codereview` time, per `CLAUDE.md` § Adversarial Second Opinion.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft |
| 0.2 | 2026-10-27 | Jesus Lara | Q1/Q2/Q3 resolved: GraphIndex applies the allowlist (RFC never prefixed), `known_prefixes` hand-maintained, `local_prefix` frozen as `PARROT`. M3 extended to `CodeExtractor.__init__` + `graphindex/cli.py`; AC11 rewritten, AC14/AC15 added. |
| 0.3 | 2026-10-27 | Codex | Resolve review findings: protect compact citation boundaries, reserve conflicting prefix names, clarify recognized/unlisted lookup, gate prefixed filenames, preserve exact/fallback ambiguity, and strengthen executable regression evidence. |
