"""Top-level CLI entrypoint for Parrot utilities.

Subcommands are lazy-imported so that 'parrot setup' and 'parrot conf init'
work on a fresh checkout without navconfig's env/ directory.
"""
import importlib
import click


class LazyGroup(click.Group):
    """Click group that imports subcommands on first invocation."""

    _lazy_commands: dict[str, str] = {}

    def list_commands(self, ctx):
        return sorted(self._lazy_commands.keys())

    def get_command(self, ctx, cmd_name):
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
}

if __name__ == "__main__":
    cli()
