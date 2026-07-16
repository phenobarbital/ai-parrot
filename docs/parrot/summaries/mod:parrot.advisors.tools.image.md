---
type: Wiki Summary
title: parrot.advisors.tools.image
id: mod:parrot.advisors.tools.image
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ShowProductImageTool - Show product image on explicit request.
relates_to:
- concept: class:parrot.advisors.tools.image.ShowProductImageArgs
  rel: defines
- concept: class:parrot.advisors.tools.image.ShowProductImageTool
  rel: defines
- concept: mod:parrot.advisors.tools.base
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.advisors.tools.image`

ShowProductImageTool - Show product image on explicit request.

Triggered when user says:
- "Can you show me the image?"
- "What does it look like?"
- "Can you show me a photo?"

## Classes

- **`ShowProductImageArgs(ProductAdvisorToolArgs)`** — Arguments for showing product image.
- **`ShowProductImageTool(BaseAdvisorTool)`** — Show product image without speaking the URL.
