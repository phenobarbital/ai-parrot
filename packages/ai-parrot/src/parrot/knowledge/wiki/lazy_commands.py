"""Lazy ADR registration preserving the real Click command contract.

``cli.py`` used to register the ``adr`` command group by importing
``parrot.knowledge.wiki.decisions.cli`` at module load time — pulling in
``decisions.models``/``render``/``repository``/``review``/``service`` (and,
transitively, ``structural.service``) on *every* ``wikitoolkit`` invocation,
including the Claude Code ``claude-hook`` fast path that never touches ADRs
(FEAT-584 / TASK-3569).

``LazyAdrGroup`` is a :class:`click.Group` that defers that import to the
moment Click actually needs to resolve an ``adr`` subcommand — help text and
top-level listing for ``wiki --help`` are served from the static ``help``
string passed at registration, never from the real module.
"""

from __future__ import annotations

import click


class LazyAdrGroup(click.Group):
    """Load ``decisions.cli`` only when the ADR command tree is actually used."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the lazy group with an empty real-group cache."""
        super().__init__(*args, **kwargs)
        self._real_group: click.Group | None = None

    def _load_real_group(self) -> click.Group:
        """Import and cache the real ``adr`` group on first use."""
        if self._real_group is None:
            from parrot.knowledge.wiki.decisions.cli import adr as _real_adr_group

            self._real_group = _real_adr_group
        return self._real_group

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Delegate ADR subcommand resolution to the lazily imported group."""
        return self._load_real_group().get_command(ctx, cmd_name)

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List real ADR commands for ADR help/completion, never hook startup."""
        return self._load_real_group().list_commands(ctx)
