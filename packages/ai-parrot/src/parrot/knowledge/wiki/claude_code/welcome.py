"""Post-install welcome renderer for ``parrot claude install`` (FEAT-799)."""

from __future__ import annotations

from parrot.self_.doctor import DoctorCheck, check_bwrap_sandbox

SYSCTL_FIX = """sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
sudo sysctl -w kernel.unprivileged_userns_clone=1
cat <<'EOF' | sudo tee /etc/sysctl.d/60-apparmor-namespace.conf
kernel.apparmor_restrict_unprivileged_userns=0
kernel.unprivileged_userns_clone=1
EOF
sudo sysctl --system"""

APPARMOR_FIX = """sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap"""

VERIFY_CMD = 'bwrap --ro-bind / / --dev /dev -- bwrap --ro-bind / / --dev /dev -- echo "nested works"'


def run_bwrap_diagnostic() -> list[DoctorCheck]:
    """Run the bwrap nested-userns diagnostic (Linux-only; empty list elsewhere)."""
    return check_bwrap_sandbox()


def build_welcome_markdown(actions: list[str], bwrap_checks: list[DoctorCheck], sandbox_mode: str | None) -> str:
    """Compose the welcome Markdown document without performing I/O.

    Args:
        actions: Completed integration-install actions.
        bwrap_checks: Linux Bubblewrap diagnostic results, if applicable.
        sandbox_mode: Chosen Claude Code sandbox mode, if one was selected.

    Returns:
        Render-ready Markdown for the post-install welcome.
    """
    lines = ["# AI-Parrot — Claude Code Integration Installed", ""]

    if actions:
        lines.extend(["## Installed Components", ""])
        lines.extend(f"- ✓ {action}" for action in actions)
        lines.append("")

    if bwrap_checks:
        lines.extend(["## Sandbox Status", ""])
        failures = [check for check in bwrap_checks if not check.ok]
        if not failures:
            lines.extend(["✅ nested Bubblewrap works", ""])
        else:
            lines.append("Nested Bubblewrap needs OS setup:")
            lines.extend(f"- {check.name}: {check.detail}" for check in failures)
            lines.extend(
                [
                    "",
                    "See [SDD Sandbox — OS Setup](docs/sdd/sandbox-setup.md), then run:",
                    "",
                    "```bash",
                    SYSCTL_FIX,
                    "```",
                    "",
                    "```bash",
                    APPARMOR_FIX,
                    "```",
                    "",
                    "Verify the setup:",
                    "",
                    "```bash",
                    VERIFY_CMD,
                    "```",
                    "",
                ]
            )

    if sandbox_mode is not None:
        mode_description = {
            "native": "native (Claude Code sandbox, `required`)",
            "legacy": "legacy (SDD Bubblewrap wrapper)",
        }.get(sandbox_mode, sandbox_mode)
        lines.extend([f"Sandbox mode: {mode_description}", ""])

    lines.extend(
        [
            "## Next Steps",
            "",
            "- Query your project knowledge with `wikitoolkit query`.",
            "- Use `/parrotwiki` in Claude Code to search the knowledge wiki.",
            "- Run `parrot self doctor --sdd` to verify SDD readiness.",
        ]
    )
    return "\n".join(lines)


def render_welcome(
    actions: list[str],
    bwrap_checks: list[DoctorCheck],
    sandbox_mode: str | None,
    *,
    non_interactive: bool = False,
) -> None:
    """Print a rich-text post-install welcome with OS guidance.

    Args:
        actions: Completed integration-install actions.
        bwrap_checks: Linux Bubblewrap diagnostic results, if applicable.
        sandbox_mode: Chosen Claude Code sandbox mode, if one was selected.
        non_interactive: Accepted for caller API stability; rendering is unchanged.
    """
    from rich.markdown import Markdown

    from parrot.cli.console import get_console

    get_console().print(Markdown(build_welcome_markdown(actions, bwrap_checks, sandbox_mode)))
