# PageIndex — Tree-Based RAG for Document Retrieval

PageIndex builds a **hierarchical semantic tree** from PDF and Markdown documents using LLM reasoning, then uses that tree for **vectorless, context-aware retrieval**. Unlike embedding-based RAG, PageIndex navigates the document structure to find relevant sections — no vector database required.

> [!TIP]
> PageIndex works with **any LLM provider** supported by ai-parrot: OpenAI, Google Gemini, Claude, Groq, and more.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [LLM Adapter](#llm-adapter)
- [Building Trees from PDFs](#building-trees-from-pdfs)
- [Building Trees from Markdown](#building-trees-from-markdown)
- [Tree Search Retriever](#tree-search-retriever)
- [Integration with Agents](#integration-with-agents)
- [Configuration Options](#configuration-options)
- [API Reference](#api-reference)

---

## Quick Start

```python
import asyncio
from parrot.clients.google.client import GoogleGenAIClient
from parrot.pageindex import (
    PageIndexLLMAdapter,
    PageIndexRetriever,
    build_page_index,
)

async def main():
    # 1. Create an LLM client (any provider works)
    client = GoogleGenAIClient()
    adapter = PageIndexLLMAdapter(client, model="gemini-3-flash-preview")

    # 2. Build a tree from a PDF
    tree = await build_page_index("report.pdf", adapter)

    # 3. Search the tree
    retriever = PageIndexRetriever(tree, adapter)
    context = await retriever.retrieve("What are the key findings?")
    print(context)

asyncio.run(main())
```

---

## Core Concepts

### How It Works

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   PDF    │────▶│  TOC detect  │────▶│  Tree build  │────▶│  Summaries   │
│ document │     │  & extract   │     │  & structure │     │  & metadata  │
└──────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                       │                     │                     │
                       ▼                     ▼                     ▼
                    LLM calls          Hierarchical            LLM calls
                 (any provider)        tree (JSON)          (any provider)
```

1. **Document Parsing** — Extract text from each page using PyMuPDF or PyPDF2.
2. **TOC Detection** — LLM examines the first N pages to determine if a Table of Contents exists.
3. **TOC Extraction** — If found, the TOC is extracted and mapped to physical page indices.
4. **Tree Construction** — Sections are organized into a hierarchical tree with `start_index`/`end_index` page ranges.
5. **Summarization** — Each node gets an LLM-generated summary for retrieval guidance.
6. **Retrieval** — At query time, the LLM reasons over the tree structure to identify relevant nodes.

### Tree Structure

The output is a JSON tree where each node represents a document section:

```json
{
  "doc_name": "report.pdf",
  "doc_description": "Annual financial report for fiscal year 2024...",
  "structure": [
    {
      "title": "Introduction",
      "node_id": "0000",
      "start_index": 1,
      "end_index": 3,
      "summary": "Overview of the company's performance...",
      "nodes": [
        {
          "title": "Executive Summary",
          "node_id": "0001",
          "start_index": 1,
          "end_index": 2,
          "summary": "Key highlights and metrics..."
        }
      ]
    }
  ]
}
```

---

## LLM Adapter

`PageIndexLLMAdapter` wraps any ai-parrot `AbstractClient`, providing PageIndex-specific methods with retry logic and structured output support.

### Creating an Adapter

```python
from parrot.pageindex import PageIndexLLMAdapter

# With Google Gemini
from parrot.clients.google.client import GoogleGenAIClient
client = GoogleGenAIClient()
adapter = PageIndexLLMAdapter(client, model="gemini-3-flash-preview")

# With OpenAI
from parrot.clients.openai import OpenAIClient
client = OpenAIClient()
adapter = PageIndexLLMAdapter(client, model="gpt-4o")

# With Claude
from parrot.clients.claude import ClaudeClient
client = ClaudeClient()
adapter = PageIndexLLMAdapter(client, model="claude-sonnet-4-20250514")

# With Groq
from parrot.clients.groq import GroqClient
client = GroqClient()
adapter = PageIndexLLMAdapter(client, model="llama-3.3-70b-versatile")
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | `AbstractClient` | *required* | Any ai-parrot LLM client |
| `model` | `str \| None` | Client default | Override the model used for all calls |
| `max_retries` | `int` | `3` | Number of retries on LLM failure |
| `retry_delay` | `float` | `1.0` | Base delay between retries (multiplied by attempt number) |

### Methods

#### `ask(prompt, structured_output=None, temperature=0.0, system_prompt=None)`
Send a prompt, return raw text. Optionally pass a Pydantic class for structured output.

#### `ask_structured(prompt, output_type, temperature=0.0, system_prompt=None)`
Send a prompt, return a validated Pydantic model instance. Tries native structured output first, falls back to JSON extraction.

#### `ask_json(prompt, temperature=0.0, system_prompt=None)`
Send a prompt, return a parsed `dict` or `list`.

#### `ask_with_finish_info(prompt, temperature=0.0, chat_history=None, system_prompt=None)`
Returns `(text, finish_reason)` where `finish_reason` is `"finished"` or `"max_output_reached"`. Used internally to detect when LLM output was truncated.

---

## Building Trees from PDFs

### Basic Usage

```python
from parrot.pageindex import build_page_index, PageIndexLLMAdapter
from parrot.clients.google.client import GoogleGenAIClient

client = GoogleGenAIClient()
adapter = PageIndexLLMAdapter(client, model="gemini-3-flash-preview")

tree = await build_page_index("document.pdf", adapter)
```

### With Options

```python
tree = await build_page_index(
    doc="document.pdf",
    adapter=adapter,
    options={
        "if_add_node_id": "yes",          # Assign unique IDs to nodes
        "if_add_node_summary": "yes",     # Generate summaries per node
        "if_add_doc_description": "yes",  # Generate document-level description
        "if_add_node_text": "no",         # Include raw page text in nodes
        "toc_check_page_num": 20,         # Pages to check for TOC
        "max_page_num_each_node": 10,     # Max pages before splitting
        "max_token_num_each_node": 20000, # Max tokens before splitting
    },
)
```

### From BytesIO

```python
from io import BytesIO

with open("document.pdf", "rb") as f:
    pdf_bytes = BytesIO(f.read())

tree = await build_page_index(doc=pdf_bytes, adapter=adapter)
```

### Saving and Loading Trees

```python
import json

# Save
with open("tree.json", "w") as f:
    json.dump(tree, f, indent=2)

# Load
with open("tree.json") as f:
    tree = json.load(f)
```

---

## Building Trees from Markdown

For Markdown documents, use `md_to_tree` which parses headers into a hierarchical structure:

```python
from parrot.pageindex import md_to_tree, PageIndexLLMAdapter
from parrot.clients.google.client import GoogleGenAIClient

client = GoogleGenAIClient()
adapter = PageIndexLLMAdapter(client, model="gemini-3-flash-preview")

md_text = open("README.md").read()
tree = await md_to_tree(
    md_text=md_text,
    adapter=adapter,
    doc_name="README.md",
    options={
        "if_add_node_id": "yes",
        "if_add_node_summary": "yes",
    },
)
```

The Markdown builder:
- Parses `#` through `######` headers into a nested tree
- Assigns each node its text content and token count
- Thins out nodes below a token threshold (default: 50)
- Generates summaries via the LLM adapter

---

## Tree Search Retriever

`PageIndexRetriever` performs LLM-based tree search — the core RAG mechanism. Instead of vector similarity, the LLM **reasons** over the tree structure to find relevant sections.

### Basic Retrieval

```python
from parrot.pageindex import PageIndexRetriever

retriever = PageIndexRetriever(tree, adapter)

# Search: returns TreeSearchResult with thinking + node_list
result = await retriever.search("What OCR engine is used?")
print(result.thinking)    # LLM reasoning about which nodes match
print(result.node_list)   # ["0004", "0005"]

# Retrieve: returns concatenated text from matched nodes
context = await retriever.retrieve("What OCR engine is used?")
```

### With Expert Knowledge

Guide the search with domain expertise:

```python
retriever = PageIndexRetriever(
    tree=tree,
    adapter=adapter,
    expert_knowledge="OCR configuration is discussed in Section 3.2 AI Models",
)
context = await retriever.retrieve("What OCR options are available?")
```

### With PDF Pages (Full Text Extraction)

When you need the full page text from matched nodes, pass the original PDF pages:

```python
from parrot.pageindex.utils import get_page_tokens

pdf_pages = get_page_tokens("document.pdf")
context = await retriever.retrieve(
    "What are the results?",
    pdf_pages=pdf_pages,
)
```

### Loading from Saved JSON

```python
retriever = PageIndexRetriever.from_json(
    "tree.json",
    adapter=adapter,
    expert_knowledge="Focus on methodology sections",
)
```

### Retrieval Priority

When extracting text from matched nodes, the retriever follows this priority:

1. **Node `text` field** — If the tree was built with `if_add_node_text: "yes"`
2. **PDF pages** — If `pdf_pages` argument is provided, extracts from `start_index` to `end_index`
3. **Node summary** — Falls back to the `summary` or `prefix_summary` field

---

## Integration with Agents

### System Prompt Injection

The simplest integration: inject the tree structure into the bot's system prompt so the LLM has document awareness.

```python
retriever = PageIndexRetriever(tree, adapter)
tree_context = retriever.get_tree_context()

# Use with any bot's create_system_prompt
system_prompt = await bot.create_system_prompt(
    pageindex_context=tree_context,
    user_context="...",
)
```

### RAG-Augmented Conversations

Combine tree search with the conversational pipeline:

```python
from parrot.bots.base import BaseBot
from parrot.pageindex import PageIndexLLMAdapter, PageIndexRetriever

class DocumentQABot(BaseBot):
    """Bot that answers questions using a PageIndex tree."""

    def __init__(self, tree_path: str, **kwargs):
        super().__init__(**kwargs)
        self._tree_path = tree_path
        self._retriever = None

    async def _get_retriever(self) -> PageIndexRetriever:
        if self._retriever is None:
            adapter = PageIndexLLMAdapter(self.llm_client, model=self.model)
            self._retriever = PageIndexRetriever.from_json(
                self._tree_path, adapter
            )
        return self._retriever

    async def conversation(self, question: str, **kwargs):
        retriever = await self._get_retriever()

        # Get relevant context via tree search
        context = await retriever.retrieve(question)

        # Get tree overview for system prompt
        tree_ctx = retriever.get_tree_context()

        # Build system prompt with both contexts
        system_prompt = await self.create_system_prompt(
            pageindex_context=tree_ctx,
            vector_context=context,
        )

        # Ask the LLM with the enriched context
        response = await self.ask(
            question=question,
            system_prompt=system_prompt,
        )
        return response
```

### Pre-Built Tree Workflow

For production, build the tree once and reuse it:

```python
import json

# === Indexing phase (run once per document) ===
async def index_document(pdf_path: str, output_path: str):
    client = GoogleGenAIClient()
    adapter = PageIndexLLMAdapter(client, model="gemini-3-flash-preview")
    tree = await build_page_index(
        doc=pdf_path,
        adapter=adapter,
        options={"if_add_node_summary": "yes", "if_add_doc_description": "yes"},
    )
    with open(output_path, "w") as f:
        json.dump(tree, f, indent=2)

# === Query phase (run per user question) ===
async def query_document(tree_path: str, question: str):
    client = GoogleGenAIClient()
    adapter = PageIndexLLMAdapter(client, model="gemini-3-flash-preview")
    retriever = PageIndexRetriever.from_json(tree_path, adapter)
    return await retriever.retrieve(question)
```

### Multi-Document Search

Search across multiple document trees:

```python
async def multi_doc_search(tree_paths: list[str], query: str, adapter):
    all_contexts = []
    for path in tree_paths:
        retriever = PageIndexRetriever.from_json(path, adapter)
        result = await retriever.search(query)
        if result.node_list:
            context = await retriever.retrieve(query)
            tree_data = retriever.get_tree_json()
            all_contexts.append({
                "doc_name": tree_data.get("doc_name", path),
                "context": context,
                "nodes": result.node_list,
            })
    return all_contexts
```

---

## Configuration Options

Options passed to `build_page_index` or `md_to_tree`:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | `str` | `"gpt-4o"` | Default LLM model (overridden by adapter's model) |
| `toc_check_page_num` | `int` | `20` | Number of pages to scan for TOC |
| `max_page_num_each_node` | `int` | `10` | Max pages per node before recursive splitting |
| `max_token_num_each_node` | `int` | `20000` | Max tokens per node before recursive splitting |
| `if_add_node_id` | `str` | `"yes"` | Assign `node_id` to each node (`"yes"` / `"no"`) |
| `if_add_node_summary` | `str` | `"yes"` | Generate LLM summaries per node |
| `if_add_doc_description` | `str` | `"no"` | Generate a document-level description |
| `if_add_node_text` | `str` | `"no"` | Include raw page text in each node |

---

## API Reference

### Public Imports

```python
from parrot.pageindex import (
    build_page_index,       # PDF → tree pipeline
    md_to_tree,             # Markdown → tree pipeline
    PageIndexLLMAdapter,    # LLM adapter wrapper
    PageIndexRetriever,     # Tree search retriever
    PageIndexNode,          # Pydantic model for tree nodes
    TreeSearchResult,       # Pydantic model for search results
    TocItem,                # Pydantic model for TOC entries
)
```

### `build_page_index(doc, adapter, options=None) → dict`

Build a PageIndex tree from a PDF.

| Param | Type | Description |
|-------|------|-------------|
| `doc` | `str \| BytesIO` | Path to PDF file or BytesIO stream |
| `adapter` | `PageIndexLLMAdapter` | LLM adapter for all LLM calls |
| `options` | `dict \| SimpleNamespace \| None` | Configuration overrides |

**Returns:** `dict` with keys `doc_name`, `structure`, and optionally `doc_description`.

### `md_to_tree(md_text, adapter, options=None, doc_name="document.md") → dict`

Build a PageIndex tree from Markdown text.

| Param | Type | Description |
|-------|------|-------------|
| `md_text` | `str` | Full Markdown document text |
| `adapter` | `PageIndexLLMAdapter` | LLM adapter |
| `options` | `dict \| SimpleNamespace \| None` | Configuration overrides |
| `doc_name` | `str` | Document identifier |

### `PageIndexRetriever(tree, adapter, expert_knowledge=None)`

| Method | Returns | Description |
|--------|---------|-------------|
| `search(query)` | `TreeSearchResult` | LLM reasoning + matched node IDs |
| `retrieve(query, pdf_pages=None)` | `str` | Concatenated text from matched nodes |
| `get_tree_context(include_summaries=True)` | `str` | Formatted tree for system prompts |
| `get_tree_json()` | `dict` | Raw tree data |
| `from_json(path_or_dict, adapter, expert_knowledge=None)` | `PageIndexRetriever` | Class method constructor |

### `TreeSearchResult`

```python
class TreeSearchResult(BaseModel):
    thinking: str         # LLM's reasoning about relevant sections
    node_list: list[str]  # List of matched node_id values
```

### Utility Functions

```python
from parrot.pageindex.utils import (
    get_page_tokens,        # Extract (text, token_count) per PDF page
    get_text_of_pages,      # Get text from a page range
    count_tokens,           # Count tokens in a string
    find_node_by_id,        # Find a node in the tree by node_id
    get_nodes,              # Flatten tree to list of nodes
    get_leaf_nodes,         # Get all leaf nodes
    write_node_id,          # Assign sequential IDs to tree nodes
    print_toc,              # Print tree as indented text
)
```
