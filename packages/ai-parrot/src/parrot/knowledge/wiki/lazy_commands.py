"""Lazy Click command registration that preserves the real command contract."""

from __future__ import annotations

import importlib

import click


class LazyGroup(click.Group):
    """Load a real Click command only when its own command tree is used."""

    def __init__(self, *args: object, import_path: str, attr: str, **kwargs: object) -> None:
        """Initialize the import target and an empty command cache."""
        super().__init__(*args, **kwargs)
        self._import_path = import_path
        self._attr = attr
        self._real_group: click.Command | None = None

    def _load_real_group(self) -> click.Command:
        """Import and cache the selected command object."""
        if self._real_group is None:
            module = importlib.import_module(self._import_path)
            command = getattr(module, self._attr, None)
            if not isinstance(command, click.Command):
                raise TypeError(f"{self._import_path}:{self._attr} is not a Click command")
            self._real_group = command
        return self._real_group

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: object,
    ) -> click.Context:
        """Parse actual options, including standalone command options."""
        return self._load_real_group().make_context(info_name, args, parent=parent, **extra)

    def invoke(self, ctx: click.Context) -> object:
        """Invoke the real command after lazy context construction."""
        return self._load_real_group().invoke(ctx)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Delegate child resolution when the selected command is a group."""
        command = self._load_real_group()
        if isinstance(command, click.Group):
            return command.get_command(ctx, cmd_name)
        return None

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List child commands only when the selected command is a group."""
        command = self._load_real_group()
        if isinstance(command, click.Group):
            return command.list_commands(ctx)
        return []


class LazyAdrGroup(LazyGroup):
    """Backward-compatible ADR proxy with the existing constructor surface."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Bind the compatibility proxy to the ADR command group."""
        super().__init__(
            *args,
            import_path="parrot.knowledge.wiki.decisions.cli",
            attr="adr",
            **kwargs,
        )
