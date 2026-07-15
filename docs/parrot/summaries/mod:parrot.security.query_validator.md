---
type: Wiki Summary
title: parrot.security.query_validator
id: mod:parrot.security.query_validator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Query safety validator — shared across ai-parrot and parrot-tools.
relates_to:
- concept: class:parrot.security.query_validator.QueryLanguage
  rel: defines
- concept: class:parrot.security.query_validator.QueryValidator
  rel: defines
---

# `parrot.security.query_validator`

Query safety validator — shared across ai-parrot and parrot-tools.

Provides ``QueryLanguage`` (the supported query dialects) and
``QueryValidator`` (a static, dependency-free safety check for SQL, Flux,
and Elasticsearch JSON DSL).

This module lives in ``parrot.security`` so both the ``DatabaseQueryTool``
(in ``parrot-tools``) and the ``DatabaseToolkit`` (in ``ai-parrot``) can
reuse it without creating a circular dependency between packages.

## Classes

- **`QueryLanguage(str, Enum)`** — Supported query languages.
- **`QueryValidator`** — Validates queries based on query language.
