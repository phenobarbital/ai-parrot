# TASK-355: Add ONTOLOGY_* Configuration Variables

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: —
**Assigned-to**: —

---

## Context

> Add all ONTOLOGY_* configuration variables to `parrot/conf.py` via the established navconfig pattern.
> Implements spec Module 1.

---

## Scope

### Modify `parrot/conf.py`

Add the following 12 configuration variables after the existing config section, following the `config.get()` pattern:

1. `ONTOLOGY_DIR` — Base directory for ontology YAML files (Path, default: `BASE_DIR / 'ontologies'`)
2. `ONTOLOGY_BASE_FILE` — Base ontology filename (str, default: `'base.ontology.yaml'`)
3. `ONTOLOGY_DOMAINS_DIR` — Domains subdirectory (str, default: `'domains'`)
4. `ONTOLOGY_CLIENTS_DIR` — Clients subdirectory (str, default: `'clients'`)
5. `ENABLE_ONTOLOGY_RAG` — Global on/off switch (bool, default: `False`)
6. `ONTOLOGY_DB_TEMPLATE` — ArangoDB DB naming template (str, default: `'{tenant}_ontology'`)
7. `ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE` — PgVector schema template (str, default: `'{tenant}'`)
8. `ONTOLOGY_CACHE_PREFIX` — Redis key prefix (str, default: `'parrot:ontology'`)
9. `ONTOLOGY_CACHE_TTL` — Cache TTL in seconds (int, default: `86400`)
10. `ONTOLOGY_MAX_TRAVERSAL_DEPTH` — Max AQL traversal depth (int, default: `4`)
11. `ONTOLOGY_AQL_MODEL` — LLM model for AQL generation (str, default: `'gemini-2.5-flash'`)
12. `ONTOLOGY_REVIEW_DIR` — Review queue directory (str, default: `None` → resolved at runtime to `{ONTOLOGY_DIR}/review/`)

Follow the existing pattern: `config.get()` / `config.getboolean()` / `config.getint()` with fallbacks. Path resolution for `ONTOLOGY_DIR` should match `PLANOGRAM_FOLDER` pattern (resolve, create if not exists).

---

## Acceptance Criteria

- [ ] All 12 variables present in `parrot/conf.py` with correct types and defaults.
- [ ] `ONTOLOGY_DIR` creates directory if not exists (matching PLANOGRAM_FOLDER pattern).
- [ ] `ENABLE_ONTOLOGY_RAG` uses `config.getboolean()`.
- [ ] `ONTOLOGY_CACHE_TTL` and `ONTOLOGY_MAX_TRAVERSAL_DEPTH` use `config.getint()`.
- [ ] All variables are importable: `from parrot.conf import ONTOLOGY_DIR, ...`
- [ ] No breaking changes to existing config.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/conf.py` | **Modify** — add ONTOLOGY_* section |
