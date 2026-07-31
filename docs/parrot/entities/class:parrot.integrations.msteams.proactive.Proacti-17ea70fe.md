---
type: Wiki Entity
title: ProactiveDeliveryError
id: class:parrot.integrations.msteams.proactive.ProactiveDeliveryError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when a proactive send fails fatally (cold-create + org-install).
---

# ProactiveDeliveryError

Defined in [`parrot.integrations.msteams.proactive`](../summaries/mod:parrot.integrations.msteams.proactive.md).

```python
class ProactiveDeliveryError(Exception)
```

Raised when a proactive send fails fatally (cold-create + org-install).

The caller (``TeamsHumanChannel``) catches this and returns ``False``
per spec §5 (OQ-COLD fail-fast policy).
