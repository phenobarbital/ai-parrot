---
type: Wiki Summary
title: parrot_tools.security.parsers._types
id: mod:parrot_tools.security.parsers._types
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared types for the catalog-level scanner parser registry.
relates_to:
- concept: class:parrot_tools.security.parsers._types.ParsedReport
  rel: defines
- concept: class:parrot_tools.security.parsers._types.ReportParser
  rel: defines
- concept: func:parrot_tools.security.parsers._types.load_bytes
  rel: defines
- concept: func:parrot_tools.security.parsers._types.sort_findings
  rel: defines
- concept: func:parrot_tools.security.parsers._types.validate_section
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
---

# `parrot_tools.security.parsers._types`

Shared types for the catalog-level scanner parser registry.

These types are SEPARATE from parrot_tools.security.models (which serves
scanner-internal normalization). This layer normalizes into the catalog's
EmbeddedFinding / SeverityBreakdown shapes.

## Classes

- **`ParsedReport`** — Result returned by every catalog-level parser's ``parse()`` method.
- **`ReportParser(Protocol)`** — Protocol every catalog-level parser must satisfy.

## Functions

- `def validate_section(section: str) -> None` — Raise ValueError if section is not in the supported set.
- `def sort_findings(findings: list[EmbeddedFinding]) -> list[EmbeddedFinding]` — Sort findings by severity desc, then finding_id asc (deterministic).
- `def load_bytes(content: bytes | Path) -> bytes` — Normalise content to bytes regardless of input type.
