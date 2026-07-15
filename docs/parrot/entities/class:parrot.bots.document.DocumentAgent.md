---
type: Wiki Entity
title: DocumentAgent
id: class:parrot.bots.document.DocumentAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A specialized agent for document processing - converting Word docs to Markdown,
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# DocumentAgent

Defined in [`parrot.bots.document`](../summaries/mod:parrot.bots.document.md).

```python
class DocumentAgent(BasicAgent)
```

A specialized agent for document processing - converting Word docs to Markdown,
analyzing content, processing Excel files, and generating narrated summaries.

This agent extends BasicAgent and integrates document-specific tools without
relying on Langchain dependencies.

## Methods

- `async def configure(self, app=None) -> None` — Configure the DocumentAgent with necessary setup.
- `async def load_document(self, url: str) -> Dict[str, Any]` — Load a document from a URL using WordToMarkdownTool.
- `async def generate_summary(self, max_length: int=500) -> Dict[str, Any]` — Generate a summary of the loaded document using the LLM.
- `async def generate_audio(self, text: str, voice_gender: str='FEMALE', language_code: str='en-US') -> Dict[str, Any]` — Generate audio narration from text using GoogleVoiceTool.
- `async def process_document_workflow(self, document_url: str, generate_audio_summary: bool=True) -> Dict[str, Any]` — Run a complete document processing workflow:
- `def extract_filenames(self, response: Union[AIMessage, AgentResponse]) -> Dict[str, Dict[str, Any]]` — Extract filenames from agent response.
- `async def analyze_document(self, document_url: str, analysis_type: str='comprehensive') -> Dict[str, Any]` — Analyze a document with specific analysis type.
