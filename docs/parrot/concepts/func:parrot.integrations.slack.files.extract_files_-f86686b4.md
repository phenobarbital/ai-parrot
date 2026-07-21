---
type: Concept
title: extract_files_from_event()
id: func:parrot.integrations.slack.files.extract_files_from_event
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract file information from a Slack event.
---

# extract_files_from_event

```python
def extract_files_from_event(event: Dict[str, Any]) -> List[Dict[str, Any]]
```

Extract file information from a Slack event.

Args:
    event: The Slack event dictionary.

Returns:
    List of file info dictionaries from the event.
