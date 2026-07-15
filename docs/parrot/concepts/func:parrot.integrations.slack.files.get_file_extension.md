---
type: Concept
title: get_file_extension()
id: func:parrot.integrations.slack.files.get_file_extension
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Get file extension from file info.
---

# get_file_extension

```python
def get_file_extension(file_info: Dict[str, Any]) -> str
```

Get file extension from file info.

Args:
    file_info: File metadata from Slack event.

Returns:
    File extension including the dot (e.g., ".pdf").
