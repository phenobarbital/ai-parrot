---
type: Concept
title: is_processable_file()
id: func:parrot.integrations.slack.files.is_processable_file
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Check if a file can be processed by AI-Parrot loaders.
---

# is_processable_file

```python
def is_processable_file(file_info: Dict[str, Any]) -> bool
```

Check if a file can be processed by AI-Parrot loaders.

Args:
    file_info: File metadata from Slack event.

Returns:
    True if the file's MIME type is supported.
