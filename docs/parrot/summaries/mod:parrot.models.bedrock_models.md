---
type: Wiki Summary
title: parrot.models.bedrock_models
id: mod:parrot.models.bedrock_models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bedrock model-ID translator for AI-Parrot.
relates_to:
- concept: func:parrot.models.bedrock_models.translate
  rel: defines
---

# `parrot.models.bedrock_models`

Bedrock model-ID translator for AI-Parrot.

Translates public Anthropic/Amazon model IDs (e.g. ``claude-sonnet-4-6``,
``nova-2-sonic``) to the AWS Bedrock ID format (e.g.
``us.anthropic.claude-sonnet-4-5-20250929-v1:0``, ``amazon.nova-2-sonic-v1:0``).

Translation strategy (applied in order):
1. **Pass-through**: IDs that are already Bedrock-shaped (contain ``anthropic.``
   or ``amazon.``, start with ``arn:``, or begin with a known region prefix
   like ``us.`` / ``eu.`` / ``apac.``) are returned verbatim.
2. **Map**: public ID looked up in a static ``PUBLIC_TO_BEDROCK`` dict; the map
   values are the Bedrock base IDs (``anthropic.<id>-vN:0`` form).
3. **Region prefix**: when *region_prefix* is provided (e.g. ``"us"``), the
   prefix ``"<prefix>."`` is prepended to the mapped base ID to form a
   cross-region inference-profile ID.
4. **Unknown fallback**: IDs not in the map and not Bedrock-shaped are returned
   unchanged and a warning is logged — no exception is raised.

## Functions

- `def translate(public_id: str, region_prefix: str | None=None) -> str` — Translate a public Anthropic model ID to its AWS Bedrock equivalent.
