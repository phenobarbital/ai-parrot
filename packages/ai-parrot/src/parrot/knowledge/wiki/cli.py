"""CLI entry point for querying an existing LLM Wiki (FEAT-260).

Exposes ``parrot llmwiki`` — a thin, read-only console over a wiki
retrieval plane built by ``scripts/build_llm_wiki.py``.  It resolves the
wiki location from the environment (``WIKI_STORE`` /
``WIKI_STORE_BACKEND``, overridable per-invocation), runs a BM25 lexical
search (:meth:`BaseWikiStore.search_fts`), and renders ranked page stubs.

Usage::

    parrot llmwiki "agent crew orchestration"
    parrot llmwiki "agent crew orchestration" limit=5
    parrot llmwiki "pgvector store" --limit 3 --category concept
    parrot llmwiki "AgentsFlow DAG executor" --body      # full top-hit body
    parrot llmwiki "memory redis" --json                 # machine output

Configuration (env/.env, read via navconfig)::

    WIKI_STORE="docs/parrot"      # storage root (holds wiki.db for sqlite)
    WIKI_STORE_BACKEND="sqlite"   # "sqlite" or "memory"
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import logging
from pathlib import Path
from typing import Any, Optional

import click
from navconfig import config

from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store

logger = logging.getLogger(__name__)

#: Fallbacks used when the corresponding env variables are unset.
DEFAULT_WIKI_STORE = "docs/parrot"
DEFAULT_WIKI_BACKEND = "sqlite"

#: Extra ``key=value`` tokens accepted on the command line (mirrors the
#: ``limit=5`` shorthand) and the option they map onto.
_INLINE_KEYS = frozenset({"limit", "category", "store", "backend"})


def _parse_inline_args(tokens: tuple[str, ...]) -> dict[str, str]:
    """Parse trailing ``key=value`` tokens into an override mapping.

    Supports the ``parrot llmwiki "<query>" limit=5`` shorthand alongside
    the canonical ``--limit`` option.  Unknown keys raise a usage error so
    typos are surfaced instead of silently ignored.

    Args:
        tokens: Extra positional tokens captured after the query.

    Returns:
        Mapping of recognised keys to their raw string values.

    Raises:
        click.UsageError: If a token is not ``key=value`` or the key is
            not one of :data:`_INLINE_KEYS`.
    """
    overrides: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            raise click.UsageError(
                f"Unexpected argument {token!r} — expected key=value "
                f"(one of: {', '.join(sorted(_INLINE_KEYS))})."
            )
        key, _, value = token.partition("=")
        key = key.strip().lower()
        if key not in _INLINE_KEYS:
            raise click.UsageError(
                f"Unknown inline option {key!r} — expected one of: "
                f"{', '.join(sorted(_INLINE_KEYS))}."
            )
        overrides[key] = value.strip()
    return overrides


async def _run_search(
    store: BaseWikiStore,
    query: str,
    category: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Run a lexical search and optionally hydrate the top hit's body.

    Args:
        store: An instantiated wiki retrieval-plane backend.
        query: Free-form natural-language query.
        category: Optional exact category pre-filter.
        limit: Maximum number of results.

    Returns:
        Ranked page-stub dicts (best first) as returned by
        :meth:`BaseWikiStore.search_fts`.
    """
    return await store.search_fts(query, category=category, limit=limit)


def _resolve_backend_store(
    store_override: Optional[str],
    backend_override: Optional[str],
) -> tuple[Path, str]:
    """Resolve the wiki storage root and backend from CLI + environment.

    Precedence: explicit CLI override > env variable > hard-coded default.

    Args:
        store_override: ``--store`` / ``store=`` value, if provided.
        backend_override: ``--backend`` / ``backend=`` value, if provided.

    Returns:
        A ``(storage_dir, backend)`` tuple.
    """
    store_path = store_override or config.get(
        "WIKI_STORE", fallback=DEFAULT_WIKI_STORE
    )
    backend = backend_override or config.get(
        "WIKI_STORE_BACKEND", fallback=DEFAULT_WIKI_BACKEND
    )
    return Path(store_path), backend


def _render_results(
    results: list[dict[str, Any]],
    query: str,
    show_body: bool,
) -> None:
    """Pretty-print ranked results as a Rich table (+ optional body panel).

    Args:
        results: Ranked page-stub dicts from the store.
        query: The original query (used in the table title).
        show_body: When ``True``, fetch and render the top hit's full body.
    """
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    if not results:
        console.print(
            f"[yellow]No wiki pages matched[/yellow] [bold]{query!r}[/bold]."
        )
        return

    table = Table(title=f"LLM Wiki · {query!r}", title_justify="left")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Title", style="bold")
    table.add_column("Summary")

    for idx, row in enumerate(results, start=1):
        score = row.get("score")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
        summary = (row.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 140:
            summary = summary[:137] + "..."
        table.add_row(
            str(idx),
            score_str,
            str(row.get("category", "")),
            str(row.get("title", "")),
            summary,
        )
    console.print(table)

    if show_body and results:
        top = results[0]
        body = (top.get("body") or "").strip()
        if body:
            console.print(
                Panel(
                    Markdown(body),
                    title=f"{top.get('title', '')} · {top.get('concept_id', '')}",
                    border_style="green",
                )
            )


@click.command()
@click.argument("query")
@click.argument("extra", nargs=-1)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=None,
    help="Maximum number of results to return (default: 5).",
)
@click.option(
    "--category",
    "-c",
    default=None,
    help="Restrict results to an exact page category (e.g. 'concept').",
)
@click.option(
    "--store",
    "store_opt",
    default=None,
    help="Wiki storage root (overrides WIKI_STORE env var).",
)
@click.option(
    "--backend",
    "backend_opt",
    default=None,
    help="Retrieval backend: 'sqlite' or 'memory' (overrides WIKI_STORE_BACKEND).",
)
@click.option(
    "--body",
    "-b",
    is_flag=True,
    default=False,
    help="Render the full markdown body of the top-ranked page.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit results as JSON instead of a rendered table.",
)
def llmwiki(
    query: str,
    extra: tuple[str, ...],
    limit: Optional[int],
    category: Optional[str],
    store_opt: Optional[str],
    backend_opt: Optional[str],
    body: bool,
    as_json: bool,
) -> None:
    """Query an existing LLM Wiki from the command line.

    \b
    Examples:
      parrot llmwiki "agent crew orchestration"
      parrot llmwiki "agent crew orchestration" limit=5
      parrot llmwiki "pgvector store" --limit 3 --category concept
      parrot llmwiki "AgentsFlow DAG executor" --body

    The wiki location defaults to the WIKI_STORE / WIKI_STORE_BACKEND
    environment variables (env/.env), overridable with --store / --backend.
    """
    inline = _parse_inline_args(extra)

    # Inline key=value tokens fill in only where the flag was not given.
    if limit is None and "limit" in inline:
        try:
            limit = int(inline["limit"])
        except ValueError as exc:
            raise click.UsageError(
                f"limit must be an integer, got {inline['limit']!r}."
            ) from exc
    if limit is None:
        limit = 5
    if limit < 1:
        raise click.UsageError("limit must be a positive integer.")

    category = category or inline.get("category")
    store_override = store_opt or inline.get("store")
    backend_override = backend_opt or inline.get("backend")

    storage_dir, backend = _resolve_backend_store(store_override, backend_override)

    if backend == "sqlite":
        db_path = storage_dir / "wiki.db"
        if not db_path.exists():
            raise click.ClickException(
                f"No wiki database found at {db_path}. Build it first with "
                f"scripts/build_llm_wiki.py, or point --store at the right root."
            )

    logger.debug(
        "Querying wiki backend=%s store=%s query=%r limit=%s category=%s",
        backend,
        storage_dir,
        query,
        limit,
        category,
    )

    store = create_wiki_store(storage_dir, backend=backend)
    results = asyncio.run(_run_search(store, query, category, limit))

    if body and results:
        hydrated = asyncio.run(
            store.get_page(results[0]["concept_id"], include_body=True)
        )
        if hydrated:
            results[0] = {**results[0], **hydrated}

    if as_json:
        click.echo(jsonlib.dumps(results, indent=2, ensure_ascii=False))
        return

    _render_results(results, query, show_body=body)
