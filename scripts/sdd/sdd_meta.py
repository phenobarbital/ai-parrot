"""Compatibility shim — the SDD frontmatter parser now ships in ``ai-parrot``.

The implementation lives in :mod:`parrot.knowledge.wiki.ledger.sdd_meta` so the
installed ``wikitoolkit`` CLI can import it outside this repository (a wheel
never contains the repo-local ``scripts`` package). This module re-exports the
same objects so ``from scripts.sdd.sdd_meta import ...`` keeps working for the
SDD commands, agents and tests.
"""

from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401
    KNOWN_BRANCHES,
    KNOWN_PROJECTS,
    PROJECT_ALIASES,
    WORK_KIND_FLOW,
    WORKTREE_ROOT,
    DocTaxonomy,
    FlowMeta,
    WorktreePlan,
    emit,
    normalize_project,
    normalize_tag,
    parse,
    parse_taxonomy,
    plan_worktree,
    resolve_flow,
)
