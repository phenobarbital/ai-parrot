---
type: Wiki Summary
title: parrot.models.openai
id: mod:parrot.models.openai
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OpenAI model catalog and deprecation registry.
relates_to:
- concept: class:parrot.models.openai.DeprecationInfo
  rel: defines
- concept: class:parrot.models.openai.OpenAIModel
  rel: defines
- concept: func:parrot.models.openai.get_shutoff_date
  rel: defines
- concept: func:parrot.models.openai.is_deprecated
  rel: defines
- concept: func:parrot.models.openai.resolve_alias
  rel: defines
---

# `parrot.models.openai`

OpenAI model catalog and deprecation registry.

This module defines:
- ``OpenAIModel`` — current upstream catalog (deprecated IDs removed).
- ``DeprecationInfo`` — structured metadata for each deprecated model.
- ``DEPRECATIONS`` — registry of deprecated model IDs.
- Helper functions: ``is_deprecated``, ``get_shutoff_date``, ``resolve_alias``.

## Classes

- **`OpenAIModel(Enum)`** — Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS).
- **`DeprecationInfo(BaseModel)`** — Structured deprecation metadata for a single OpenAI model ID.

## Functions

- `def is_deprecated(model: Union[str, OpenAIModel]) -> bool` — Return True if ``model`` is in DEPRECATIONS or matches an alias entry.
- `def get_shutoff_date(model: Union[str, OpenAIModel]) -> Optional[date]` — Return the API shutoff date for ``model``, or None if not deprecated.
- `def resolve_alias(model: Union[str, OpenAIModel]) -> str` — Map a deprecated model ID to the recommended migration target.
