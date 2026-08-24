# Integrating the Jira Issues Namespace with an Agent

> How to add the Jira ticket knowledge base (`issues` namespace) to an
> existing AI-Parrot agent — using `FirefliesWikiAgent` as the worked example.

## Prerequisites

1. The Jira Ticket Extractor is set up and the `issues` namespace is
   registered. See [Jira Ticket Extractor guide](./jira-ticket-extractor.md).
2. The agent you want to extend already uses the `LLMWikiToolkit` for at
   least one wiki plane (e.g. `meetings`, `notes`).

---

## How Wiki Namespaces Work in Agents

There are **two distinct integration paths** depending on what the agent needs
to do with the Jira knowledge base:

| Path | Use Case | Complexity |
|---|---|---|
| **A. CLI/MCP federation (read-only)** | The agent queries the issues namespace via `wikitoolkit query --ns issues` or the `wiki_query` MCP tool | **Zero code changes** — just register the namespace |
| **B. Programmatic `LLMWikiToolkit` (read + write)** | The agent ingests documents into the issues wiki plane, creates pages, or manages the corpus programmatically | Requires a new `LLMWikiToolkit` instance |

For most agents, **Path A** is the right choice. The `issues` namespace is a
read-only corpus built by the `ingest-jira` cron sweep — agents query it, they
don't write to it.

---

## Path A: Federation via Namespace Registration (Recommended)

This is the zero-code path. Once the `issues` namespace is registered globally:

```bash
wikitoolkit ns add issues \
  --store ~/.parrot/wikis/issues/.parrot/wiki \
  --global \
  --description "Jira ticket corpus"
```

**Every agent that uses the wiki gets the issues namespace for free.** The
`wikitoolkit` CLI and MCP tools resolve registered namespaces at startup, so:

- `wikitoolkit query "forms tenant problem"` searches **all** namespaces
  (codebase + meetings + notes + issues).
- `wiki_query("forms tenant problem")` does the same via MCP.
- `wikitoolkit query --ns issues "forms tenant problem"` narrows to issues
  only.

### Claude Code sessions

If your project has the wikitoolkit MCP server registered in `.mcp.json`
(which AI-Parrot does), Claude Code sessions can query the issues namespace
immediately:

```json
// .mcp.json (already configured)
{
  "mcpServers": {
    "wikitoolkit": {
      "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/wikitoolkit",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

No changes needed — the MCP server resolves the `issues` namespace from the
global registry at startup.

### FirefliesWikiAgent — no changes needed

`FirefliesWikiAgent` already consumes the wiki via `LLMWikiToolkit`, which
queries the local plane. The **federated** `issues` namespace is reachable
through the CLI/MCP layer that Claude Code sessions use. If the agent itself
needs to run wiki queries programmatically, it can shell out to
`wikitoolkit query --ns issues` or call the MCP tools.

---

## Path B: Programmatic LLMWikiToolkit Instance

If an agent needs to **write** to the issues wiki plane (e.g. programmatically
ingest tickets, create pages, manage the corpus), it needs its own
`LLMWikiToolkit` instance pointed at the issues storage root.

> **Note**: For the Jira issues namespace specifically, this is rarely needed
> — the `ingest-jira` sweep handles all writing. But this pattern is useful for
> building new wiki-backed agents.

### Pattern: Adding a wiki plane to an existing agent

Follow the `FirefliesWikiAgent` pattern — it already manages **two** separate
wiki planes (`meetings` and `notes`):

```python
"""Example: adding an issues wiki plane to an agent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from navconfig import config

logger = logging.getLogger(__name__)

# Configuration (matches FEAT-454 defaults)
_ISSUES_WIKI_NAME: str = config.get("JIRA_WIKI_NAMESPACE", fallback="issues")
_ISSUES_WIKI_STORAGE_DIR: str = config.get(
    "JIRA_WIKI_ISSUES_DIR",
    fallback=str(Path.home() / ".parrot" / "wikis" / "issues"),
)


class MyAgent(SomeBaseAgent):
    """An agent that can query and write to the Jira issues wiki plane."""

    def __init__(
        self,
        issues_wiki_name: Optional[str] = None,
        issues_wiki_storage_dir: Optional[str | Path] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.issues_wiki_name: str = issues_wiki_name or _ISSUES_WIKI_NAME
        self.issues_wiki_storage_dir: Path = Path(
            issues_wiki_storage_dir or _ISSUES_WIKI_STORAGE_DIR
        ).expanduser()

        # Set in configure(); None when the issues plane is unavailable.
        self._issues_wiki: Optional[Any] = None

    async def configure(self, app=None) -> None:
        """Configure the parent, then build the issues wiki plane."""
        await super().configure(app)
        self._issues_wiki = await self._build_issues_wiki_toolkit()

    async def _build_issues_wiki_toolkit(self) -> Optional[Any]:
        """Construct the LLMWikiToolkit for the issues plane.

        Best-effort: any failure leaves ``self._issues_wiki`` as ``None``
        and logs a warning. The agent still boots.

        Returns:
            A wired ``LLMWikiToolkit``, or ``None``.
        """
        try:
            from parrot.knowledge.wiki.models import WikiConfig
            from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

            # For a READ-ONLY plane (issues), we don't need PageIndex or
            # GraphIndex — just the retrieval surface.
            storage = self.issues_wiki_storage_dir
            if not storage.exists():
                logger.warning(
                    "Issues wiki storage dir does not exist: %s — "
                    "run 'wikitoolkit ingest-jira' first.",
                    storage,
                )
                return None

            wiki_config = WikiConfig(
                wiki_name=self.issues_wiki_name,
                storage_dir=storage,
                sync_graph=False,  # read-only — no graph writes
            )
            toolkit = LLMWikiToolkit(
                None,       # no pageindex (read-only)
                None,       # no graph toolkit (read-only)
                None,       # no ontology
                wiki_config,
                agent_id=self.name,
            )
            logger.info(
                "Issues LLMWikiToolkit ready (wiki=%s, storage=%s)",
                self.issues_wiki_name,
                storage,
            )
            return toolkit
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Issues LLMWikiToolkit unavailable (%s); "
                "Jira ticket queries will not be available.",
                exc,
            )
            return None
```

### Key design constraints

1. **One `LLMWikiToolkit` per plane.** `_config_for` raises `ValueError`
   when the requested `wiki_name` does not match the toolkit's configured wiki.
   You cannot serve `meetings`, `notes`, and `issues` from a single toolkit
   instance — each needs its own.

2. **Storage roots are isolated.** Each plane uses a different storage root
   (`~/.parrot/wikis/meetings`, `~/.parrot/wikis/notes`,
   `~/.parrot/wikis/issues`). They share no manifest and no `wiki.db`.

3. **Best-effort construction.** Follow the try/except pattern: if the issues
   wiki is not built yet, the agent still boots — it just can't answer Jira
   questions.

4. **Lazy dependency imports.** The `jira` package is an optional dependency.
   Always import `LLMWikiToolkit` (and any Jira-specific modules) inside the
   method, not at module level:
   ```python
   # ✅ Correct — lazy import
   async def _build_issues_wiki_toolkit(self):
       from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
       ...

   # ❌ Wrong — breaks when jira is not installed
   from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
   ```

---

## Worked Example: Extending FirefliesWikiAgent

Here is a concrete example of adding Jira ticket context to
`FirefliesWikiAgent`'s meeting analysis. The agent already syncs Fireflies
meetings → Obsidian → wiki; adding Jira context lets it cross-reference
meeting discussions with related tickets.

### Option 1: Query the issues namespace in analysis prompts

The simplest approach — use `wikitoolkit query` in the analysis step to fetch
relevant tickets as context:

```python
import subprocess

async def _get_related_tickets(self, meeting_summary: str) -> str:
    """Query the issues namespace for tickets related to a meeting.

    Args:
        meeting_summary: The meeting's extracted summary text.

    Returns:
        Formatted ticket context string, or empty string if unavailable.
    """
    # Extract key phrases from the summary for the query
    query = meeting_summary[:200]  # first 200 chars as search seed

    try:
        result = subprocess.run(
            ["wikitoolkit", "query", "--ns", "issues", "--json", query],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            import json
            pages = json.loads(result.stdout)
            if pages:
                lines = ["## Related Jira Tickets"]
                for p in pages[:5]:  # top 5 matches
                    lines.append(f"- [{p['title']}] (id: {p['concept_id']})")
                return "\n".join(lines)
    except Exception:
        pass
    return ""
```

### Option 2: Full programmatic integration

For deeper integration, build an `LLMWikiToolkit` for the issues plane and
use its retrieval methods directly:

```python
class EnhancedFirefliesWikiAgent(FirefliesWikiAgent):
    """FirefliesWikiAgent with Jira ticket cross-referencing."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._issues_wiki = None

    async def configure(self, app=None):
        await super().configure(app)
        self._issues_wiki = await self._build_issues_wiki_toolkit()

    async def _build_issues_wiki_toolkit(self):
        """Build a read-only LLMWikiToolkit for the issues namespace."""
        try:
            from parrot.knowledge.wiki.models import WikiConfig
            from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

            storage = Path(
                config.get("JIRA_WIKI_ISSUES_DIR")
                or str(Path.home() / ".parrot" / "wikis" / "issues")
            ).expanduser()

            if not (storage / ".parrot" / "wiki" / "wiki.db").exists():
                self.logger.info("Issues wiki not built yet — skipping.")
                return None

            wiki_config = WikiConfig(
                wiki_name="issues",
                storage_dir=storage,
                sync_graph=False,
            )
            return LLMWikiToolkit(
                None, None, None, wiki_config,
                agent_id=self.name,
            )
        except Exception as exc:
            self.logger.warning("Issues wiki unavailable: %s", exc)
            return None

    async def sync_meetings_to_wiki(self):
        """Override sync to add Jira cross-references after base sync."""
        report = await super().sync_meetings_to_wiki()

        if self._issues_wiki and report.get("status") == "ok":
            # Optionally enrich meeting notes with ticket references
            self.logger.info("Cross-referencing meetings with Jira tickets...")
            # ... your cross-referencing logic here

        return report
```

---

## Summary: Which Path to Choose

| Scenario | Path | What to do |
|---|---|---|
| Claude Code sessions need Jira context | A (federation) | Just register the namespace — done |
| An agent needs to *query* Jira tickets | A (federation) | Register the namespace; use CLI/MCP tools |
| An agent needs to *write* to the issues plane | B (programmatic) | Build a `LLMWikiToolkit` instance |
| Cross-referencing meetings with tickets | A or B | Start with A (CLI query); upgrade to B if you need deep integration |
| Building a new Jira-aware agent from scratch | B (programmatic) | Follow the `FirefliesWikiAgent` pattern |

For the **common case** — making Jira tickets queryable alongside the codebase
and meeting notes — **Path A (namespace registration) is all you need**. The
federated wiki plane makes the corpus available to every tool and session
automatically.

---

## See Also

- [Jira Ticket Extractor setup](./jira-ticket-extractor.md) — installation,
  credentials, cron setup
- [WikiToolkit as Claude Code infrastructure](../wiki-claude-code.md) —
  namespaces, MCP tools, CLI reference
- [LLM Wiki architecture](../llm-wiki.md) — PageIndex + GraphIndex +
  Ontology layers
- `agents/fireflies_wiki.py` — the `FirefliesWikiAgent` source (the reference
  for multi-plane wiki integration)
- Spec: `sdd/specs/jira-extractor-llmwiki.spec.md`
