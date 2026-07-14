---
type: Wiki Entity
title: NetworkNinjaTool
id: class:parrot_tools.networkninja.NetworkNinjaTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: NetworkNinja Batch Processing API Tool.
relates_to:
- concept: class:parrot_tools.resttool.RESTTool
  rel: extends
---

# NetworkNinjaTool

Defined in [`parrot_tools.networkninja`](../summaries/mod:parrot_tools.networkninja.md).

```python
class NetworkNinjaTool(RESTTool)
```

NetworkNinja Batch Processing API Tool.

This tool provides access to NetworkNinja's batch processing capabilities.
It automatically handles environment-based URL routing and provides
convenient methods for batch operations.

Natural Language Examples:
- "please, run via GET get_batch for batch_id=xyz"
- "list all completed batches"
