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
        # Optional per-command install hint shown when a lazy module fails
        # to import (e.g. an optional extra wasn't installed). Generic --
        # any lazy command may register one; falls back to a generic
        # message naming the failing module path when absent (FEAT-422).
        self._lazy_extras: dict[str, str] = {}

    def list_commands(self, ctx):
        """Return sorted list of registered subcommand names.

        Args:
            ctx: Click context.

        Returns:
            Sorted list of command names.
        """
        return sorted(self._lazy_commands.keys())

    @staticmethod
    def _is_missing_target(module_path: str, exc: ImportError) -> bool:
        """Report whether `exc` means the lazy module itself is absent.

        CPython sets ``ImportError.name`` to the module that could not be
        found. For a genuinely uninstalled subcommand that is the target
        module or one of its parent packages; for a failure raised from
        *within* an installed module it is the inner dependency instead
        (e.g. ``google`` for ``from google import genai``). Only the former
        justifies pointing the user at an optional extra.

        Args:
            module_path: Dotted path of the lazily imported module.
            exc: The raised ``ImportError``.

        Returns:
            ``True`` if the target module (or a parent package) is missing.
        """
        failed = getattr(exc, "name", None)
        if not failed:
            return False
        return failed == module_path or module_path.startswith(f"{failed}.")

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
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            hint = self._lazy_extras.get(cmd_name)
            if hint and self._is_missing_target(module_path, exc):
                message = f"'parrot {cmd_name}' requires {hint}"
            else:
                # The target module IS installed — an ImportError raised
                # *inside* it (a missing transitive dependency) must report
                # its own cause instead of blaming an unrelated extra.
                message = (
                    f"'parrot {cmd_name}' is unavailable: could not import "
                    f"{module_path!r} ({type(exc).__name__}: {exc})"
                )
            raise click.ClickException(message) from exc
        attr_name = cmd_name.replace("-", "_")
        return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)


@click.group(cls=LazyGroup)
def cli():
    """Parrot command-line interface."""
    pass


# Register subcommands — imported only when invoked
cli._lazy_commands = {
    "setup": "parrot.setup.cli",
    "conf": "parrot.install.conf",
    "install": "parrot.install.cli",
    "wiki": "parrot.knowledge.wiki.cli",
    "bookstore": "parrot.knowledge.bookstore.cli",
    "mcp": "parrot.mcp.cli",
    "mcp-local": "parrot.mcp.local_cli",
    "autonomous": "parrot.autonomous.cli",
    "agent": "parrot.cli.agent_repl",
    "claude": "parrot.knowledge.wiki.claude_code.cli",
    "codex": "parrot.knowledge.wiki.codex.cli",
    "generate-keys": "parrot.cli.generate_keys",
    "devloop": "parrot.cli.devloop",
    # FEAT-422 — Agent CLI Daemon (agentd), ships in ai-parrot-integrations.
    "serve": "parrot.integrations.agentd.cli",
    "attach": "parrot.integrations.agentd.cli",
    "ask": "parrot.integrations.agentd.cli",
    "status": "parrot.integrations.agentd.cli",
    "install-service": "parrot.integrations.agentd.cli",
    "mcp-serve": "parrot.integrations.agentd.cli",
}

_AGENTD_INSTALL_HINT = "ai-parrot-integrations[agentd]: pip install ai-parrot-integrations[agentd]"
cli._lazy_extras = {
    "serve": _AGENTD_INSTALL_HINT,
    "attach": _AGENTD_INSTALL_HINT,
    "ask": _AGENTD_INSTALL_HINT,
    "status": _AGENTD_INSTALL_HINT,
    "install-service": _AGENTD_INSTALL_HINT,
    "mcp-serve": _AGENTD_INSTALL_HINT,
}

if __name__ == "__main__":
    cli()
