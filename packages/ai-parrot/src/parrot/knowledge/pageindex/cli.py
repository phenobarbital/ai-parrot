"""``parrot pageindex`` command group (FEAT-846)."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import click


@click.group()
def pageindex() -> None:
    """PageIndex trees (optimize, inspect)."""


@pageindex.command("optimize")
@click.argument("tree")
@click.option("--storage-dir", required=True)
@click.option("--node", default=None)
@click.option("--apply", is_flag=True)
@click.option("--llm", default=None, help="provider:model; default none")
@click.option("--target-tokens", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def optimize(
    tree: str,
    storage_dir: str,
    node: Optional[str],
    apply: bool,
    llm: Optional[str],
    target_tokens: Optional[int],
    as_json: bool,
) -> None:
    """Dry-run (default) or apply the optimizer on TREE in STORAGE_DIR."""
    from parrot.knowledge.pageindex import PageIndexToolkit

    client = None
    if llm is not None:
        from parrot.knowledge.bookstore._llm import resolve_adapter

        _adapter, _lightweight_model, client = resolve_adapter(llm)

    toolkit = PageIndexToolkit(storage_dir=storage_dir, llm_client=client)
    report = asyncio.run(
        toolkit.optimize(
            tree,
            node_id=node,
            apply=apply,
            target_leaf_tokens=target_tokens,
        )
    )

    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
        return

    mode = "applied" if apply else "dry-run"
    click.echo(f"{mode}: {tree}")
    click.echo(
        f"nodes: {report.get('nodes_before', 0)} -> {report.get('nodes_after', 0)}; "
        f"merged: {len(report.get('merged', []))}; expanded: {len(report.get('expanded', []))}"
    )
    click.echo(f"llm: {report.get('llm_passes', 'unknown')}")
    for error in report.get("errors", []):
        click.echo(f"error: {error}", err=True)
