---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [ontology, snapshot, tests, bugfix]
---

# Feature Specification: Snapshot conformance vs historical as_of

**Feature ID**: FEAT-868
**Date**: 2026-11-10
**Author**: Jesus Lara
**Status**: approved
**Discovered-from**: `issue:870a5b73930d`

## Problem

`issue:870a5b73930d` reported 6 failing ontology vocabulary tests. FEAT-864 (PR #2072) fixed 5.
The remaining one, `test_snapshot_store.py::test_conformance_snapshot[case_expand_multiple_inheritance]`,
fails because FEAT-864 pinned that shared conformance case to `as_of=1`. A `SnapshotOntologyStore`
serves only its own version by design (`_version_for` raises `OntologyVersionNotFound` for any other
`as_of`), and the fixture builds a v2 snapshot.

## Solution

Test-only. Run the snapshot conformance suite over every case except the one that needs history, and
add a snapshot-specific test that builds a **v1** snapshot and checks the dual-parent ancestors there.
No production code changes.

## Acceptance Criteria

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary` passes with 0 failures against live Postgres.
- Multiple-inheritance expansion is still covered for the snapshot backend.
