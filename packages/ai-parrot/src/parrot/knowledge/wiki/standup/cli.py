"""Click entry point for the shared standup pipeline."""

import asyncio
import inspect
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from parrot.knowledge.wiki.project import (
    WikiConfigError,
    find_project_root,
    load_effective_config,
    resolve_arango_params,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.standup.pipeline import StandupOptions, StandupStoreError, run
from parrot.knowledge.wiki.standup.render import render_markdown
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store


def _run(coro: Any) -> Any:
    """Run an async pipeline operation from a synchronous Click command."""
    return asyncio.run(coro)


def _find_root(path_: Path | None) -> Path:
    """Resolve an explicit or discovered wiki project root."""
    if path_ is not None:
        root = path_.resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
        return root
    root = find_project_root()
    if root is None:
        raise click.ClickException(
            "No wiki project found (no .parrot/wiki.json or .git upwards from here). Run inside a repository or pass --path."
        )
    return root


def _open_store(root: Path, effective: Any, store_opt: Path | None, backend_opt: str | None) -> BaseWikiStore:
    """Open the explicit or local plane before entering the shared pipeline."""
    config = effective.config
    if backend_opt is not None:
        config.backend = backend_opt
    if store_opt is not None:
        storage = store_opt.expanduser()
        if not storage.is_dir():
            raise click.ClickException(f"No wiki store directory: {storage}")
        return create_wiki_store(storage, backend=config.backend)
    storage = config.storage_path(root)
    if config.backend == "arangodb":
        return create_wiki_store(
            storage,
            wiki_name=config.wiki_name,
            backend="arangodb",
            arango_params=resolve_arango_params(config),
            database=config.arango_database or "",
            text_analyzer=config.arango_text_analyzer,
        )
    if not config.is_built(root):
        raise click.ClickException(f"Wiki not built yet for {root}. Run `wikitoolkit build` first.")
    return create_wiki_store(
        storage,
        wiki_name=config.wiki_name,
        backend=config.backend,
        sqlite_policy=sqlite_policy_from_config(config),
    )


def _resolve_run_inputs(
    path_: Path | None, store_opt: Path | None, backend_opt: str | None
) -> tuple[Path, Any, BaseWikiStore | None]:
    """Resolve a project configuration and concrete local write target."""
    root = _find_root(path_)
    try:
        effective = load_effective_config(root)
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    if store_opt is None and backend_opt is None:
        return root, effective, None
    return root, effective, _open_store(root, effective, store_opt, backend_opt)


async def _execute(root: Path, options: StandupOptions, effective: Any, store: BaseWikiStore | None) -> Any:
    """Run the pipeline and close only the store constructed by this CLI."""
    try:
        return await run(root, options, store=store, effective=effective)
    finally:
        closer = getattr(store, "close", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result


@click.command(name="standup")
@click.option("--period", type=click.Choice(["day", "week", "month"]), default="day")
@click.option("--date", "date_", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--horizon", type=click.IntRange(1, 90))
@click.option("--team", is_flag=True)
@click.option("--me")
@click.option("--language", type=click.Choice(["en", "es"]))
@click.option("--json", "as_json", is_flag=True)
@click.option("--no-llm", is_flag=True)
@click.option("--out", type=click.Path(path_type=Path))
@click.option("--no-store", is_flag=True)
@click.option("--no-file", is_flag=True)
@click.option("--ns", "namespaces")
@click.option("--path", "path_", type=click.Path(path_type=Path))
@click.option("--store", "store_opt", type=click.Path(path_type=Path))
@click.option("--backend", "backend_opt")
def standup(
    period: str,
    date_: datetime | None,
    horizon: int | None,
    team: bool,
    me: str | None,
    language: str | None,
    as_json: bool,
    no_llm: bool,
    out: Path | None,
    no_store: bool,
    no_file: bool,
    namespaces: str | None,
    path_: Path | None,
    store_opt: Path | None,
    backend_opt: str | None,
) -> None:
    """Render a deterministic brief, optionally storing it and adding a model summary."""
    if team and me is not None:
        raise click.UsageError("--team and --me cannot be used together.")
    root, effective, store = _resolve_run_inputs(path_, store_opt, backend_opt)
    options = StandupOptions(
        period=period,
        anchor=date_.date() if date_ is not None else None,
        horizon_days=horizon,
        team=team,
        me=me,
        language=language,
        use_llm=not no_llm,
        write_page=not no_store,
        write_file=not no_file,
        out_dir=out,
        namespaces=namespaces,
    )
    try:
        document = _run(_execute(root, options, effective, store))
    except StandupStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(document.model_dump(mode="json"), ensure_ascii=False, default=str))
        return
    click.echo(render_markdown(document, document.language))
