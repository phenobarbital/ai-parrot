---
type: Concept
title: parse_candidate_document_data()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_document_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Document/Attachment data for Candidate.
---

# parse_candidate_document_data

```python
def parse_candidate_document_data(candidate_data: Dict[str, Any], candidate_id: Optional[str]=None, pdf_directory: Optional[str]=None) -> Dict[str, Any]
```

Parse Document/Attachment data for Candidate.

Args:
    candidate_data: Candidate data dictionary
    candidate_id: Candidate ID for organizing PDF files
    pdf_directory: Base directory to save PDF files

Returns:
    Dictionary with document info including attachments list (JSONB ready) and legacy fields
    - attachments: List of dicts with filename, path, mime_type, source, attachment_id
    - Files with same name are overwritten (saved once)
