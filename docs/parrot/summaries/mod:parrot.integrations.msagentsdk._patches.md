---
type: Wiki Summary
title: parrot.integrations.msagentsdk._patches
id: mod:parrot.integrations.msagentsdk._patches
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Runtime patches for the Microsoft 365 Agents SDK.
relates_to:
- concept: func:parrot.integrations.msagentsdk._patches.patch_mcs_connector_empty_response
  rel: defines
---

# `parrot.integrations.msagentsdk._patches`

Runtime patches for the Microsoft 365 Agents SDK.

The SDK is vendored as an installed dependency, so these patches monkeypatch
specific methods at runtime rather than editing the package on disk (which a
reinstall would clobber). Every patch here is idempotent and guarded so a
missing SDK symbol degrades to a no-op instead of raising at import time.

## Functions

- `def patch_mcs_connector_empty_response() -> None` — Make the MCS connector tolerate an empty / non-JSON 200 response.
