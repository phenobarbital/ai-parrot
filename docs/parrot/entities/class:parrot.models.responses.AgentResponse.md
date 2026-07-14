---
type: Wiki Entity
title: AgentResponse
id: class:parrot.models.responses.AgentResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: AgentResponse is a model that defines the structure of the response for Any
  Parrot agent.
---

# AgentResponse

Defined in [`parrot.models.responses`](../summaries/mod:parrot.models.responses.md).

```python
class AgentResponse(BaseModel)
```

AgentResponse is a model that defines the structure of the response for Any Parrot agent.

## Methods

- `def content(self) -> Any` — Get content as a string. This is an alias for to_text property
- `def content(self, value: Any) -> None` — Set content by updating the output field.
- `def sync_documents_and_paths(self)` — Automatically populate documents list from individual path fields
- `def add_document(self, path: Union[str, Path]) -> None` — Add a document to the documents list also document path.
- `def add_file(self, path: Union[str, Path]) -> None` — Add a file to the files list.
- `def add_image(self, path: Union[str, Path]) -> None` — Add an image to the images list.
- `def add_media(self, path: Union[str, Path]) -> None` — Add a media file to the media list.
- `def set_podcast_path(self, path: Union[str, Path]) -> None` — Set the podcast_path and automatically add to files list.
- `def set_pdf_path(self, path: Union[str, Path]) -> None` — Set the pdf_path and automatically add to documents list.
