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

    def shell_complete(self, ctx, incomplete):
        """Complete subcommand names without failing on an uninstalled one.

        Click's default resolves every matching command through :meth:`get_command`, so one absent
        optional distribution would abort ``parrot <TAB>``. Such a command is still offered, marked
        unavailable.

        Args:
            ctx: Click context.
            incomplete: The partial word being completed.

        Returns:
            Completion items for subcommands, then for the group's own options.
        """
        from click.shell_completion import CompletionItem

        results = []
        for name in self.list_commands(ctx):
            if not name.startswith(incomplete):
                continue
            try:
                cmd = self.get_command(ctx, name)
            except click.ClickException:
                results.append(CompletionItem(name, help="(unavailable)"))
                continue
            if cmd is not None and not cmd.hidden:
                results.append(CompletionItem(name, help=cmd.get_short_help_str()))
        results.extend(click.Command.shell_complete(self, ctx, incomplete))
        return results

    def format_commands(self, ctx, formatter):
        """List subcommands in ``--help`` without failing on an uninstalled one.

        Click resolves every listed command to render its short help. A lazy
        command whose optional distribution is absent (``e2e``, ``serve``, …
        in the managed runtime) makes :meth:`get_command` raise, which used to
        turn a plain ``parrot --help`` into exit 1. Here such a command is
        listed with its availability message instead; invoking it directly
        still fails with that same message.

        Args:
            ctx: Click context.
            formatter: Click help formatter to write the commands section to.
        """
        rows: list[tuple[str, click.Command | None, str]] = []
        for name in self.list_commands(ctx):
            try:
                cmd = self.get_command(ctx, name)
            except click.ClickException as exc:
                rows.append((name, None, f"(unavailable) {exc.format_message()}"))
                continue
            if cmd is None or cmd.hidden:
                continue
            rows.append((name, cmd, ""))
        if not rows:
            return
        limit = formatter.width - 6 - max(len(name) for name, _cmd, _note in rows)
        entries = [(name, cmd.get_short_help_str(limit) if cmd is not None else note) for name, cmd, note in rows]
        with formatter.section("Commands"):
            formatter.write_dl(entries)


@click.group(cls=LazyGroup)
def cli():
    """Parrot command-line interface."""


# Register subcommands — imported only when invoked
cli._lazy_commands = {
    "setup": "parrot.setup.cli",
    "conf": "parrot.install.conf",
    "install": "parrot.install.cli",
    "wiki": "parrot.knowledge.wiki.cli",
    "bookstore": "parrot.knowledge.bookstore.cli",
    "mcp": "parrot.mcp.cli",
    "mcp-local": "parrot.mcp.local_cli",
    "toolkits": "parrot.cli.toolkits",
    # FEAT-633 — managed-runtime lifecycle (`parrot status` is agentd's; diagnostics live here).
    "self": "parrot.self_.cli",
    # FEAT-650 — FormDesigner dialect tools, ships in parrot-formdesigner.
    "formdesigner": "parrot_formdesigner.cli",
    "autonomous": "parrot.autonomous.cli",
    "agent": "parrot.cli.agent_repl",
    "claude": "parrot.knowledge.wiki.claude_code.cli",
    "codex": "parrot.knowledge.wiki.codex.cli",
    "google": "parrot.knowledge.wiki.google.cli",
    "gemini": "parrot.knowledge.wiki.google.cli",
    "generate-keys": "parrot.cli.generate_keys",
    "devloop": "parrot.cli.devloop",
    # FEAT-633 — SDD flow installer (parrot sdd install|uninstall|status|run).
    "sdd": "parrot.sdd.cli",
    # FEAT-601 — Procedure Graph manuals CLI, ships in ai-parrot-tools.
    "manuals": "parrot_tools.procedures.cli",
    # FEAT-696 — Jira toolkit CLI (local 3LO auth, KB sync), ships in ai-parrot-tools.
    "jiratoolkit": "parrot_tools.jira_cli",
    # FEAT-581 — Deterministic E2E gate, ships in ai-parrot-server.
    "e2e": "parrot.e2e.cli",
    # FEAT-422 — Agent CLI Daemon (agentd), ships in ai-parrot-integrations.
    "serve": "parrot.integrations.agentd.cli",
    "attach": "parrot.integrations.agentd.cli",
    "ask": "parrot.integrations.agentd.cli",
    "status": "parrot.integrations.agentd.cli",
    "install-service": "parrot.integrations.agentd.cli",
    "mcp-serve": "parrot.integrations.agentd.cli",
}

_AGENTD_INSTALL_HINT = "ai-parrot-integrations[agentd]: pip install ai-parrot-integrations[agentd]"
_E2E_INSTALL_HINT = "ai-parrot-server: pip install ai-parrot-server"
cli._lazy_extras = {
    "serve": _AGENTD_INSTALL_HINT,
    "attach": _AGENTD_INSTALL_HINT,
    "ask": _AGENTD_INSTALL_HINT,
    "status": _AGENTD_INSTALL_HINT,
    "install-service": _AGENTD_INSTALL_HINT,
    "mcp-serve": _AGENTD_INSTALL_HINT,
    "e2e": _E2E_INSTALL_HINT,
    "manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot[manuals]",
    "formdesigner": "parrot-formdesigner: pip install parrot-formdesigner[ai-parrot]",
    "jiratoolkit": "ai-parrot-tools: pip install ai-parrot-tools",
}

if __name__ == "__main__":
    cli()
