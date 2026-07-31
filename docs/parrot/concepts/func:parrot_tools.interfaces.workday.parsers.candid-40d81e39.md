---
type: Concept
title: save_attachment()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.save_attachment
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Save attachment file from base64 content to disk.
---

# save_attachment

```python
def save_attachment(file_content_base64: str, filename: str, candidate_id: str, storage_path: Optional[str]=None) -> Optional[str]
```

Save attachment file from base64 content to disk.

Args:
    file_content_base64: Base64 encoded file content
    filename: Original filename
    candidate_id: Candidate ID for organizing files
    storage_path: Base directory path to save files (defaults to /tmp/workday_attachments)
                 Files will be saved to: {storage_path}/{candidate_id}/{filename}

Returns:
    Path to saved file or None if failed
