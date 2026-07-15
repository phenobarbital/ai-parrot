---
type: Wiki Summary
title: parrot_formdesigner.tools.request_form
id: mod:parrot_formdesigner.tools.request_form
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RequestFormTool — platform-agnostic form request tool.
relates_to:
- concept: class:parrot_formdesigner.tools.request_form.RequestFormInput
  rel: defines
- concept: class:parrot_formdesigner.tools.request_form.RequestFormTool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.extractors.tool
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
---

# `parrot_formdesigner.tools.request_form`

RequestFormTool — platform-agnostic form request tool.

Allows the LLM to request a structured form from the user when it needs to
collect parameters for another tool. Migrated from
parrot/integrations/msteams/tools/request_form.py — no longer Teams-specific.

Flow:
1. LLM calls request_form(target_tool="search", known_values={"limit": 10})
2. RequestFormTool looks up the target tool in ToolManager
3. Uses ToolExtractor to generate FormSchema, excluding known fields
4. Returns ToolResult(status="form_requested", metadata={"form": schema_dict, ...})
5. The platform wrapper (Teams, Telegram, web) detects status and renders the form

## Classes

- **`RequestFormInput(BaseModel)`** — Input schema for the request_form tool.
- **`RequestFormTool(AbstractTool)`** — Platform-agnostic tool that requests a form to collect missing parameters.
