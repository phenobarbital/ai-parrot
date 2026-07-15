---
type: Concept
title: save_worker_document()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.save_worker_document
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Save worker document file from base64 content to disk.
---

# save_worker_document

```python
def save_worker_document(file_content_base64: str, filename: str, worker_id: str, storage_path: Optional[str]=None) -> Optional[str]
```

Save worker document file from base64 content to disk.

Args:
    file_content_base64: Base64 encoded file content
    filename: Original filename
    worker_id: Worker/Employee ID for organizing files
    storage_path: Base directory path to save files (defaults to /tmp/workday_worker_documents)
                 Files will be saved to: {storage_path}/{worker_id}/{filename}

Returns:
    Path to saved file or None if failed
