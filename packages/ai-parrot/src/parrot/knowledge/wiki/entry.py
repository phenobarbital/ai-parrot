"""Light console-script entry point for ``wikitoolkit`` (FEAT-595).

``wikitoolkit claude-hook`` runs before every matching Claude Code tool
call, so it must not import the click CLI (~240 ms). This dispatcher
imports only :mod:`sys` at module level: the hook subcommand goes straight
to the hook runtime, and every other invocation is handed to the regular
click CLI unchanged.
"""

from __future__ import annotations

import sys

#: The hidden click subcommand the installed hook command invokes. Kept as a
#: literal (equal to ``claude_code.assets.HOOK_SUBCOMMAND``, asserted in the
#: tests) because importing ``assets`` here would load the ``claude_code``
#: package on every non-hook invocation too.
HOOK_ARGV = ["claude-hook"]


def main() -> None:
    """Dispatch ``claude-hook`` to the light hook runtime, anything else to the click CLI."""
    if sys.argv[1:] == HOOK_ARGV:
        from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook

        sys.exit(run_pre_tool_use_hook())
    from parrot.knowledge.wiki.cli import main as cli_main

    cli_main()


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    main()
