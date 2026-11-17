---
id: F017
query_id: Q017
type: grep
intent: "Cross-lane follow-ups: has any FEAT-670 code landed (traversal_spec, helix)? where is the L1 WikiPage cache persisted? does asyncdb ship a SurrealDB driver?"
executed_at: 2026-11-06T14:05:00Z
duration_ms: 0
parent_id: F031
depth: 2
merged_from: [FC-017]
---

# F017 — No HelixDB / `traversal_spec` code on dev, no persistence for the L1 `WikiPage` cache, and asyncdb has no SurrealDB driver

## Summary

Four checks run by the parent after the lanes finished (sequential follow-ups of F029, F031 and F012). (1) `grep -rnE "traversal_spec" packages/ai-parrot/src/parrot/knowledge/ontology` returns nothing, and `grep -rilE "traversal_spec|helix" packages/*/src --include="*.py"` matches a single file, `knowledge/graphindex/protocols.py` (a docstring mention): **no FEAT-670 code has landed**, so the backend-neutral `TraversalPattern.traversal_spec` that FEAT-670 specifies does not exist yet. (2) `git branch -r | grep -iE "helix|670|surreal"` is empty: no remote branch carries HelixDB or SurrealDB work. (3) `WikiPage` is referenced only inside `knowledge/retrieval/` (`wiki_cache.py`, `models.py`, `__init__.py`, `sections.py`, `single_flight.py`), and `wiki_cache.py` contains only Pydantic models and pure functions — no `sqlite`, `asyncpg`, `json.dump`, `write_text` or `open(` match: **the L1 synthesis cache has no persistence layer today**, so a "caché L1" store would be the first one, not a replacement. (4) The installed `asyncdb` 2.16.3 ships drivers `arangodb`, `pg`, `sqlite` and nothing matching `surreal` or `helix`: a SurrealDB store cannot follow the house convention of going through `asyncdb.AsyncDB`; it needs the raw `surrealdb` SDK or a new asyncdb driver.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py`
  lines: 36-278
  symbol: `WikiSection`
  excerpt: |
    36:class SourceDigest(BaseModel):
    52:class GeneratorInfo(BaseModel):
    85:class WikiSection(BaseModel):
    113:class WikiPage(BaseModel):
    130:def compute_page_id(repo: str, scope_uri: str) -> str:
    143:def invalidate_section(section: WikiSection, current_digests: Mapping[str, str]) -> WikiSection:
    175:def invalidate_page(page: WikiPage, current_digests: Mapping[str, str]) -> WikiPage:
    259:class ServingDecision(StrEnum):

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/single_flight.py`
  lines: 1-1
  symbol: module referencing `WikiPage` (file listed by grep -l, not opened)
  excerpt: |
    packages/ai-parrot/src/parrot/knowledge/retrieval/single_flight.py

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/sections.py`
  lines: 1-1
  symbol: module referencing `WikiPage` (file listed by grep -l, not opened)
  excerpt: |
    packages/ai-parrot/src/parrot/knowledge/retrieval/sections.py

## Notes

- Commands, all run from the repository root: `grep -rnE "traversal_spec|helix" packages/*/src --include="*.py" -il`; `grep -rnE "traversal_spec" packages/ai-parrot/src/parrot/knowledge/ontology`; `git branch -r | grep -i -E "helix|670|surreal"`; `grep -rnE "WikiPage\b" packages/*/src --include="*.py" -l`; `grep -nE "^class |^def |^async def |sqlite|asyncpg|json\.dump|write_text|open\(" .../retrieval/wiki_cache.py`; a Python one-liner listing `asyncdb/drivers/*` filtered on `surreal|arango|pg|sqlite|helix`.
- `retrieval/models.py`, `sections.py` and `single_flight.py` were not opened: a cache held in memory by one of them cannot be excluded, only an on-disk or database store in `wiki_cache.py` itself.
- The asyncdb check is against the installed version in the shared venv (2.16.3), not against asyncdb's upstream main.
