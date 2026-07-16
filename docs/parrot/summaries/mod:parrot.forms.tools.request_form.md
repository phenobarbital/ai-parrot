---
type: Wiki Summary
title: parrot.forms.tools.request_form
id: mod:parrot.forms.tools.request_form
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: RequestFormTool — platform-agnostic form request tool.
relates_to:
- concept: class:parrot.forms.tools.request_form.RequestFormInput
  rel: defines
- concept: class:parrot.forms.tools.request_form.RequestFormTool
  rel: defines
- concept: mod:parrot.forms.extractors.tool
  rel: references
- concept: mod:parrot.forms.registry
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.forms.tools.request_form`

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
