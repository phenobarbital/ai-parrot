---
id: ADR-SEED-0006
title: Authentication uses Navigator Auth
status: accepted
---

## Context

Source: `sdd/specs/sdd-decision-audit.spec.md` § Module 10 and `.agent/CONTEXT.md` § Per-tenant skills.

## Decision

The server uses `navigator-auth` for authentication, authorization, ABAC, and PBAC instead of custom
authentication middleware.

## Consequences

Server identity and policy enforcement integrate with the platform-provided Navigator tenant and auth
contracts.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-auth-platform-navigator-auth
entries:
  - id: rule
    statement: The server uses navigator-auth for authentication, authorization, ABAC, and PBAC.
    relation: requires
    about: [auth, server]
    targets: [dir:packages/ai-parrot-server]
    rationale: Platform auth contracts replace custom authentication middleware.
```
