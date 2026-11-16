"""Lazy memory CLI registration; resource acquisition belongs to command execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import click

from parrot.memory.agent_memory.toolkit import AgentMemoryToolkit
from parrot.memory.episodic.models import MemoryNamespace

def _toolkit(settings: dict[str, Any]) -> AgentMemoryToolkit:
    """Construct a lazy toolkit from explicit trusted command options."""
    return AgentMemoryToolkit(config=settings["config"], namespace=settings["namespace"])


async def _invoke(
    settings: dict[str, Any],
    operation: Callable[[AgentMemoryToolkit], Awaitable[Any]],
) -> Any:
    """Run one operation and close every resource acquired during that command."""
    toolkit = _toolkit(settings)
    try:
        return await operation(toolkit)
    finally:
        if toolkit._manager is not None or toolkit._opened:
            await toolkit._close()


def _execute(
    settings: dict[str, Any],
    operation: Callable[[AgentMemoryToolkit], Awaitable[Any]],
) -> None:
    """Bridge one async operation to Click and emit deterministic JSON."""
    try:
        result = asyncio.run(_invoke(settings, operation))
    except (TypeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, sort_keys=True, separators=(",", ":")))


def _decode_object(value: str, option_name: str) -> dict[str, Any]:
    """Decode one JSON object option with a stable CLI error."""
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter("must be a JSON object", param_hint=option_name) from exc
    if not isinstance(decoded, dict):
        raise click.BadParameter("must be a JSON object", param_hint=option_name)
    return decoded


def register_memory_commands(group: click.Group) -> None:
    """Attach status/recall/cite/review/forget/sync/import-feedback/export-reviews commands."""
    if "memory" in group.commands:
        return

    @click.group(name="memory")
    @click.option(
        "--storage-path",
        required=True,
        type=click.Path(dir_okay=False, path_type=Path),
        help="Explicit SQLite memory store path.",
    )
    @click.option("--tenant-id", default="default", show_default=True)
    @click.option("--agent-id", required=True)
    @click.option("--user-id", default=None)
    @click.option("--session-id", default=None)
    @click.option("--room-id", default=None)
    @click.option("--crew-id", default=None)
    @click.option("--model-id", default=None)
    @click.option("--episodic/--no-episodic", default=True, show_default=True)
    @click.option("--user-memory/--no-user-memory", default=False, show_default=True)
    @click.option("--dynamics/--no-dynamics", default=True, show_default=True)
    @click.pass_context
    def memory(
        ctx: click.Context,
        storage_path: Path,
        tenant_id: str,
        agent_id: str,
        user_id: str | None,
        session_id: str | None,
        room_id: str | None,
        crew_id: str | None,
        model_id: str | None,
        episodic: bool,
        user_memory: bool,
        dynamics: bool,
    ) -> None:
        """Operate on one explicitly configured agent-memory store."""
        ctx.obj = {
            "config": {
                "enable_episodic_memory": episodic,
                "enable_user_memory": user_memory,
                "memory_dynamics": dynamics,
                "storage_path": str(storage_path),
            },
            "namespace": {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "user_id": user_id,
                "session_id": session_id,
                "room_id": room_id,
                "crew_id": crew_id,
                "model_id": model_id,
            },
        }

    @memory.command("status")
    @click.pass_obj
    def status(settings: dict[str, Any]) -> None:
        """Report configured capabilities and durable backend state."""
        _execute(settings, lambda toolkit: toolkit.memory_status())

    @memory.command("recall")
    @click.argument("query")
    @click.option("--limit", default=5, show_default=True, type=click.IntRange(1, 100))
    @click.pass_obj
    def recall(settings: dict[str, Any], query: str, limit: int) -> None:
        """Recall memory inside the configured scope."""
        _execute(settings, lambda toolkit: toolkit.memory_recall(query, limit))

    @memory.command("cite")
    @click.option("--memory-id", "memory_ids", multiple=True, required=True)
    @click.option("--exposure-id", required=True)
    @click.pass_obj
    def cite(settings: dict[str, Any], memory_ids: tuple[str, ...], exposure_id: str) -> None:
        """Cite delivered episodic references without assigning a grade."""
        _execute(settings, lambda toolkit: toolkit.memory_cite(list(memory_ids), exposure_id))

    @memory.command("review")
    @click.option("--memory-id", "memory_ids", multiple=True, required=True)
    @click.option("--exposure-id", required=True)
    @click.option("--signal", required=True, help="Trusted ReviewSignal JSON receipt.")
    @click.pass_obj
    def review(
        settings: dict[str, Any],
        memory_ids: tuple[str, ...],
        exposure_id: str,
        signal: str,
    ) -> None:
        """Apply verified evidence to references cited for one exposure."""
        payload = _decode_object(signal, "--signal")
        _execute(settings, lambda toolkit: toolkit.memory_review(list(memory_ids), payload, exposure_id))

    @memory.command("forget")
    @click.option("--command", required=True, help="Revision-checked UserKnowledgeCommand JSON.")
    @click.pass_obj
    def forget(settings: dict[str, Any], command: str) -> None:
        """Forget one fact when user memory and trusted user scope are explicit."""
        payload = _decode_object(command, "--command")
        _execute(settings, lambda toolkit: toolkit.memory_forget(payload))

    @memory.command("sync")
    @click.pass_obj
    def sync(settings: dict[str, Any]) -> None:
        """Report replay synchronization without double-applying committed reviews."""
        _execute(settings, lambda toolkit: toolkit.memory_sync())

    @memory.command("import-feedback")
    @click.pass_obj
    def import_feedback_command(settings: dict[str, Any]) -> None:
        """Import coder feedback from the shared checkout ledger."""
        _execute(settings, lambda toolkit: toolkit.memory_import_feedback())

    @memory.command("export-reviews")
    @click.option(
        "--output",
        required=True,
        type=click.Path(dir_okay=False, path_type=Path),
        help="Output path for the export file.",
    )
    @click.pass_obj
    def export_reviews_command(settings: dict[str, Any], output: Path) -> None:
        """Export the configured store's committed reviews as a replayable archive."""
        from parrot.memory.dynamics.export import export_reviews as do_export

        async def run_export(toolkit: AgentMemoryToolkit) -> dict[str, Any]:
            namespace = MemoryNamespace(**settings["namespace"])
            manager = await toolkit._opened_manager()
            if manager.episodic is None:
                raise click.ClickException("episodic memory is not enabled")
            return await do_export(
                namespace=namespace,
                destination=output,
                store=manager.episodic,
            )

        _execute(settings, run_export)

    group.add_command(memory)
