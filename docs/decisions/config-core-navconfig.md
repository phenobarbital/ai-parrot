---
id: ADR-SEED-0005
title: Configuration uses NavConfig
status: accepted
---

## Context

Source: `sdd/specs/sdd-decision-audit.spec.md` § Module 10 and `.claude/rules/codebase-conventions.md` § Stack.

## Decision

Repository packages use `navconfig` as the configuration core instead of ad-hoc environment parsing
or independent settings frameworks.

## Consequences

Configuration behavior stays consistent across packages and is extended through the shared core.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-config-core-navconfig
entries:
  - id: rule
    statement: Repository packages use navconfig as the configuration core.
    relation: requires
    about: [config]
    targets: [dir:packages]
    rationale: Shared configuration avoids divergent environment parsing and settings frameworks.
```
