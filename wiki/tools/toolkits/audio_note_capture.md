# AudioNoteCaptureToolkit

**Package:** `ai-parrot-tools`  
**Module:** `parrot_tools.audio_note_capture`  
**TOOL_REGISTRY key:** `audio_note_capture`

## Overview

`AudioNoteCaptureToolkit` is a single-purpose toolkit that captures a raw
transcript (voice-transcribed or typed text), structures it via one LLM call,
writes it as a frontmattered Obsidian vault note, and best-effort ingests it
into an LLM Wiki plane.

It exposes exactly **one tool** to the LLM: `capture_audio_note`.

### What it does

1. **Structure** — Sends the transcript to the agent's LLM with a prompt
   that produces: English title, English tags, source-language summary,
   key points, and action items.  Falls back to a verbatim note on any
   LLM/parse failure.
2. **Vault write** — Creates the note at
   `<notes_folder>/YYYY-MM-DD-<slug>.md` via the agent's `ObsidianToolkit`,
   with OKF frontmatter and the raw transcript preserved under
   `## Transcript`.  Retries with a `-2`, `-3` suffix on same-day slug
   collisions.
3. **Wiki ingest** — Best-effort calls `ingest_source` on the notes wiki
   plane.  A failure here never loses the vault note.

---

## Installation

The toolkit ships with `ai-parrot-tools` (no extra required):

```bash
uv pip install ai-parrot-tools
```

---

## Quick Start

```python
from parrot_tools.audio_note_capture import AudioNoteCaptureToolkit

toolkit = AudioNoteCaptureToolkit(
    obsidian_toolkit=my_obsidian_toolkit,
    notes_wiki_provider=lambda: my_wiki_toolkit,   # or lambda: None
    llm_call=my_llm_client.complete,
    vault_path=Path("~/vaults/notes"),
)

result = await toolkit.capture_audio_note(
    "recordar comprar leche en la tienda",
    language="es",
)
# result: {'note_title': '2026-08-23-buy-milk', 'vault_path': 'audio-notes/...', ...}
```

---

## Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `obsidian_toolkit` | `ObsidianToolkit` | *(required)* | The agent's Obsidian toolkit. `create_note` must be in its `allowed_operations`. |
| `notes_wiki_provider` | `Callable[[], Optional[Any]]` | *(required)* | Zero-arg callable returning the wiki toolkit, or `None` when unavailable. A callable (not the instance) so the tool always sees the latest value. |
| `llm_call` | `Callable[[str], Awaitable[str]]` | *(required)* | Single-prompt callable routed through the agent's `AbstractClient`. |
| `vault_path` | `Path` | *(required)* | The Obsidian vault root (used to build absolute paths for `ingest_source`). |
| `notes_folder` | `str` | `"audio-notes"` | Vault subfolder for captured notes. |
| `wiki_name` | `str` | `"notes"` | Target wiki identifier for `ingest_source`. |

---

## Wiring with `post_configure`

The recommended way to attach `AudioNoteCaptureToolkit` to an existing agent
is via the **`post_configure()`** lifecycle hook. This hook runs at the end of
`configure()`, after the LLM client, tool manager, and any other resources
(Obsidian vault, wiki planes) have been initialised.

### Why `post_configure`?

The toolkit depends on resources that only exist after `configure()`:

- `self.client` — the LLM client (for `llm_call`)
- `self.obsidian_toolkit` — the vault writer
- `self._notes_wiki` — the wiki plane (optional)

Constructing the toolkit in `__init__` would fail because those attributes
haven't been set yet.  `configure()` itself is busy with base setup.
`post_configure()` is the sanctioned extension point — the same pattern used
by `JiraSpecialist` (Jira + Reminder toolkits) and `GitHubReviewer` (Git +
Jira toolkits).

### Pattern

```python
from parrot_tools.audio_note_capture import AudioNoteCaptureToolkit

class MyObsidianAgent(Agent):
    """An agent that already has an ObsidianToolkit."""

    async def post_configure(self) -> None:
        # 1. Always chain the parent first.
        await super().post_configure()

        # 2. Construct the toolkit with agent resources.
        capture = AudioNoteCaptureToolkit(
            obsidian_toolkit=self.obsidian_toolkit,
            notes_wiki_provider=lambda: getattr(self, '_notes_wiki', None),
            llm_call=self.client.complete,
            vault_path=self.vault_path,
            notes_folder="audio-notes",
            wiki_name="notes",
        )

        # 3. Register via tool_manager and extend self.tools.
        tools = self.tool_manager.register_toolkit(capture)
        self.tools.extend(tools)

        # 4. (Optional) Keep a reference for direct calls (e.g. /note).
        self._capture_toolkit = capture
```

### Full Example: Adding to an Agent with ObsidianToolkit

```python
from pathlib import Path
from parrot.bots import Agent
from parrot.tools.obsidian import ObsidianToolkit
from parrot_tools.audio_note_capture import AudioNoteCaptureToolkit


class NoteTakingAgent(Agent):
    """Agent that takes voice/typed notes into an Obsidian vault."""

    def __init__(self, vault_path: str = "~/vaults/notes", **kwargs):
        super().__init__(**kwargs)
        self.vault_path = Path(vault_path).expanduser()

        # ObsidianToolkit needs 'create' in allowed_operations.
        self.obsidian_toolkit = ObsidianToolkit(
            vault_path=self.vault_path,
            allowed_operations={"read", "search", "create"},
        )

        # Will be set in post_configure.
        self._capture_toolkit = None

    async def configure(self, app=None) -> None:
        await super().configure(app)
        # Register the Obsidian toolkit (base tools).
        self._initialize_tools([self.obsidian_toolkit])

    async def post_configure(self) -> None:
        await super().post_configure()

        # Wire the capture toolkit — depends on self.client and
        # self.obsidian_toolkit which are ready after configure().
        capture = AudioNoteCaptureToolkit(
            obsidian_toolkit=self.obsidian_toolkit,
            notes_wiki_provider=lambda: None,  # no wiki plane
            llm_call=self.client.complete,
            vault_path=self.vault_path,
        )
        self._capture_toolkit = capture
        tools = self.tool_manager.register_toolkit(capture)
        self.tools.extend(tools)
```

### Without a Wiki Plane

If you don't have a wiki plane, pass `lambda: None` as `notes_wiki_provider`.
The toolkit writes the vault note normally and reports `wiki_ingested=False`,
`wiki_reason="notes wiki toolkit unavailable"` — no error, no data loss.

---

## The `capture_audio_note` Tool

This is the single tool exposed to the LLM.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `transcript` | `str` | *(required)* | The raw note text (transcribed voice or typed). |
| `language` | `Optional[str]` | `None` | ISO 639-1 code for voice input (e.g. `"es"`). `None` for typed input — the LLM detects the language. |

### Return Value

A dict matching `AudioNoteResult`:

```python
{
    "note_title": "2026-08-23-buy-milk",
    "vault_path": "audio-notes/2026-08-23-buy-milk.md",
    "wiki_ingested": True,
    "wiki_reason": None,        # populated when wiki_ingested is False
    "structured": True,          # False when LLM structuring failed
}
```

### LLM Tool Description

The tool's docstring (which becomes its LLM-facing description) says:

> *Call this when the user is recording something to REMEMBER (a note, idea,
> decision, reminder or follow-up) rather than asking a question.*

You can supplement this with agent-level `instructions` to nudge the LLM
toward the tool on capture intent:

```python
GUIDANCE = (
    "When the user is recording something to REMEMBER — a note, idea, "
    "decision, reminder or follow-up — rather than asking a question, "
    "call the capture_audio_note tool."
)
agent = MyAgent(instructions=GUIDANCE, ...)
```

---

## Data Models

### `AudioNoteStructure`

The intermediate structure produced by the LLM:

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | English title (3-8 words). |
| `tags` | `list[str]` | 2-5 English tags. |
| `summary` | `str` | Source-language summary. |
| `key_points` | `list[str]` | Source-language key points (may be empty). |
| `action_items` | `list[str]` | Source-language action items (may be empty). |

### `AudioNoteResult`

The final return value (see table above).

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| LLM call fails | Verbatim fallback: title = first 60 chars, summary = first 280 chars. `structured=False`. |
| LLM response unparseable | Same verbatim fallback. |
| Vault slug collision | Retries with `-2`, `-3`, etc. suffix. |
| Vault write fails | **Propagates** — this is the durable step. |
| Wiki unavailable | `wiki_ingested=False`, note preserved. |
| Wiki ingest fails | `wiki_ingested=False`, note preserved, reason captured. |

---

## Testing

```bash
# Standalone toolkit tests (no agents/ dependency)
pytest tests/tools/test_audio_note_capture.py -v

# Full integration tests (via agents/fireflies_wiki.py)
pytest tests/test_fireflies_wiki_agent.py -v
```

---

## Migration from Agent-Local Code

Before the extraction, `AudioNoteCaptureToolkit` lived inline in
`agents/fireflies_wiki.py`.  The agent file now imports from
`parrot_tools.audio_note_capture` and re-exports the symbols for
backwards compatibility.

If you were importing directly from the agent module:

```python
# Old (still works via re-export)
from agents.fireflies_wiki import AudioNoteCaptureToolkit

# New (preferred)
from parrot_tools.audio_note_capture import AudioNoteCaptureToolkit
```

The `FirefliesWikiAgent.configure()` method no longer registers the
toolkit inline — it now uses `post_configure()`, following the same
pattern as `JiraSpecialist` and `GitHubReviewer`.
