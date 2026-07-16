---
type: Wiki Summary
title: parrot_formdesigner.services._identifiers
id: mod:parrot_formdesigner.services._identifiers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Postgres identifier validation helpers.
relates_to:
- concept: func:parrot_formdesigner.services._identifiers.qualified_table
  rel: defines
- concept: func:parrot_formdesigner.services._identifiers.validate_identifier
  rel: defines
---

# `parrot_formdesigner.services._identifiers`

Postgres identifier validation helpers.

Identifiers (schema, table, tenant) cannot be parameterised via
``$1``/``$2`` placeholders, so they are interpolated into SQL strings.
To stay safe, every identifier that reaches the SQL templates MUST be
validated with :func:`validate_identifier` first — anything that does
not match the strict whitelist regex is rejected with ``ValueError``.

The accepted shape mirrors a conservative subset of unquoted Postgres
identifiers: a leading letter or underscore followed by up to 62
letters/digits/underscores. This is more restrictive than Postgres
itself (which allows quoted identifiers with arbitrary characters) but
removes the entire class of injection bugs at the source.

## Functions

- `def validate_identifier(value: str, *, kind: str='identifier') -> str` — Return ``value`` if it is a safe Postgres identifier.
- `def qualified_table(schema: str, table: str) -> str` — Return ``"<schema>"."<table>"`` after validating both identifiers.
