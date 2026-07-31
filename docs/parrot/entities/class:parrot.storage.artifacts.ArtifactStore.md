---
type: Wiki Entity
title: ArtifactStore
id: class:parrot.storage.artifacts.ArtifactStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Artifact CRUD operations against the configured storage backend.
---

# ArtifactStore

Defined in [`parrot.storage.artifacts`](../summaries/mod:parrot.storage.artifacts.md).

```python
class ArtifactStore
```

Artifact CRUD operations against the configured storage backend.

Args:
    dynamodb: Initialised ``ConversationBackend`` instance (param name
        kept for backward compatibility with existing callers).
    s3_overflow: Initialised ``OverflowStore`` instance (param name
        kept for backward compatibility).

## Methods

- `async def save_artifact(self, user_id: str, agent_id: str, session_id: str, artifact: Artifact) -> None` — Persist an artifact, offloading to overflow store if necessary.
- `async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[Artifact]` — Retrieve a single artifact with its full definition.
- `async def list_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[ArtifactSummary]` — List all artifacts for a session as lightweight summaries.
- `async def update_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, definition: Dict[str, Any]) -> None` — Replace the definition of an existing artifact.
- `async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> bool` — Delete an artifact from storage and clean up any overflow data.
- `async def get_public_url(self, user_id: Union[str, int], agent_id: str, session_id: str, artifact_id: str, *, format: Literal['html', 'json']='html') -> str` — Return a presigned URL for the artifact's overflow object.
