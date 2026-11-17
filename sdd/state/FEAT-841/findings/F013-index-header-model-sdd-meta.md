---
id: F013
query_id: Q028
type: read
intent: "Read the per-spec index header model (sdd_meta) — fields available to carry an escrow block and the completion stamp."
executed_at: 2026-11-07T01:24:35Z
duration_ms: 1500
parent_id: null
depth: 1
merged_from: [FC-013]
---

# F013 — sdd_meta models flow metadata (FlowMeta, DocTaxonomy, WorktreePlan), not the index header; the index header is untyped JSON

## Summary

`packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` (74 lines) is a pure re-export of `parrot.knowledge.wiki.ledger.sdd_meta` plus a CLI (`parse`, `taxonomy`, `resolve-flow`). The real module (read as depth-1 follow-up) defines `FlowMeta` (`type: Literal["feature","hotfix"]`, `base_branch`, `hotfix_base`), `DocTaxonomy` (`projects`, `tags`), `resolve_flow()`, `WorktreePlan` (`name`, `path`, `base_ref`) and `plan_worktree()`. **No Pydantic model for the per-spec index header exists here** — the header (`feature, feature_id, spec, type, base_branch, created_at, completed_at, parallel_semantics, validation_contract, test_contract, tasks[]`, FC-020) is manipulated as a raw dict by `close_task.update_index` and by `jq` in /sdd-done. An `escrow` block in the header would be a schema-less addition unless a header model is introduced.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py`
  lines: 1-5
  symbol: null
  excerpt: |
    """Re-export of :mod:`parrot.knowledge.wiki.ledger.sdd_meta` for in-package SDD helpers (FEAT-633).
    Same names as the repo-local ``scripts/sdd/sdd_meta.py`` shim, so moved helpers import
    ``from parrot.sdd.scripts.sdd_meta import …`` without touching the repo-local ``scripts`` package.

- path: `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py`
  lines: 15-29
  symbol: null
  excerpt: |
    from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401
        KNOWN_BRANCHES, KNOWN_PROJECTS, PROJECT_ALIASES, WORK_KIND_FLOW,
        DocTaxonomy, FlowMeta, WorktreePlan,
        emit, normalize_project, normalize_tag, parse, parse_taxonomy, plan_worktree, resolve_flow,
    )

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`
  lines: 108-114
  symbol: `FlowMeta`
  excerpt: |
    class FlowMeta(BaseModel):
        type: Literal["feature", "hotfix"]
        base_branch: str
        hotfix_base: str = Field(default=DEFAULT_HOTFIX_BASE, exclude=True)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`
  lines: 267-271
  symbol: `DocTaxonomy`
  excerpt: |
    class DocTaxonomy(BaseModel):
        projects: list[str] = Field(default_factory=list)
        tags: list[str] = Field(default_factory=list)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`
  lines: 387-400
  symbol: `WorktreePlan`
  excerpt: |
    class WorktreePlan(BaseModel):
        name: str
        path: str
        base_ref: str
    def plan_worktree(
        meta: FlowMeta,
        slug: str,
        feature_id: str | None = None,
        jira_key: str | None = None,

## Notes

- Depth-1 follow-up (parent Q028): `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` outline only (class/def lines), not fully read.
