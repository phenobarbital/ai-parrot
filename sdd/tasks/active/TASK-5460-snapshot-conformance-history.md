# TASK-5460: Snapshot conformance excludes the historical as_of case

**Feature**: FEAT-868 fixgroup-f093dea55b64
**Spec**: `sdd/specs/fixgroup-f093dea55b64.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:870a5b73930d`

## Scope

See spec. NOT in scope: production code, the postgres conformance suite.

## Files to Modify

- `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_store.py`

## Codebase Contract

- `store_conformance.ALL_CASES` and `case_expand_multiple_inheritance` exist.
- `build_snapshot(content, dest_root)`, `PostgresOntologyStore.load_version(ontology_id, version=)`,
  `SnapshotOntologyStore(snapshot_dir)` exist.

## Validation Commands

`PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary -q`

## Completion Note
