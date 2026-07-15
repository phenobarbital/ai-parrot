"""Top-level CLI entrypoint for Parrot utilities.

Subcommands are lazy-imported so that 'parrot setup' and 'parrot conf init'
work on a fresh checkout without navconfig's env/ directory.

This package also provides the interactive agent REPL subpackage:

- ``parrot.cli.agent_repl`` — ``parrot agent`` Click command
- ``parrot.cli.renderer`` — Rich-based response renderer
- ``parrot.cli.repl`` — AgentREPL engine
- ``parrot.cli.loaders`` — StandaloneAgentLoader, ServerAgentProxy
- ``parrot.cli.commands`` — SlashCommandDispatcher
"""
import importlib
import click


class LazyGroup(click.Group):
    """Click group that imports subcommands on first invocation."""

    def __init__(self, *args, **kwargs):
        """Initialise LazyGroup with an empty lazy command registry.

        Args:
            *args: Positional arguments forwarded to ``click.Group``.
            **kwargs: Keyword arguments forwarded to ``click.Group``.
        """
        super().__init__(*args, **kwargs)
        self._lazy_commands: dict[str, str] = {}

    def list_commands(self, ctx):
        """Return sorted list of registered subcommand names.

        Args:
            ctx: Click context.

        Returns:
            Sorted list of command names.
        """
        return sorted(self._lazy_commands.keys())

    def get_command(self, ctx, cmd_name):
        """Lazily import and return a subcommand by name.

        Args:
            ctx: Click context.
            cmd_name: Name of the subcommand to load.

        Returns:
            Click command object, or None if not found.
        """
        if cmd_name not in self._lazy_commands:
            return None
        module_path = self._lazy_commands[cmd_name]
        mod = importlib.import_module(module_path)
        # The command object has the same name as the last part of the module
        return getattr(mod, cmd_name)


@click.group(cls=LazyGroup)
def cli():
    """Parrot command-line interface."""
    pass


# Register subcommands — imported only when invoked
cli._lazy_commands = {
    "setup": "parrot.setup.cli",
    "conf": "parrot.install.conf",
    "install": "parrot.install.cli",
    "mcp": "parrot.mcp.cli",
    "autonomous": "parrot.autonomous.cli",
    "agent": "parrot.cli.agent_repl",
    "llmwiki": "parrot.knowledge.wiki.cli",
}

if __name__ == "__main__":
    cli()
