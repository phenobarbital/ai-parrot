"""Post-install welcome renderer for ``parrot claude install`` (FEAT-799)."""

from __future__ import annotations

from pathlib import Path
import tomllib

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
                    "See [SDD Sandbox — OS Setup](wiki/tools/sdd/sandbox-setup.md), then run:",
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


_MODE_MAP = {"native": "required", "legacy": "legacy"}
_WIZARD_TEXT = """Sandbox mode for SDD sessions:

  1. native (recommended) — Claude Code's built-in sandbox; requires
     nested bwrap (the OS fix above).
  2. legacy — SDD's own Bubblewrap wrapper (no nested namespaces needed,
     but no Claude Code sandbox protection).
  3. skip — keep current setting, decide later.
"""


def current_sandbox_mode(root: Path) -> str | None:
    """Return "native"/"legacy" as persisted for ``root``, or None if unset/unreadable."""
    try:
        from parrot.knowledge.wiki.claude_code.installer import _load_settings
        from parrot.sdd.scripts.native_claude_sandbox import MODE_ENV

        settings = _load_settings(root / ".claude" / "settings.local.json")
        environment = settings.get("env") if settings else None
        if isinstance(environment, dict) and environment.get(MODE_ENV) == "legacy":
            return "legacy"

        pyproject_path = root / "pyproject.toml"
        if not pyproject_path.is_file():
            return None
        config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        sdd_config = config.get("tool", {}).get("parrot", {}).get("sdd", {})
        if isinstance(sdd_config, dict) and sdd_config.get("sandbox") == "required":
            return "native"
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def write_sandbox_mode(root: Path, choice: str) -> str:
    """Persist ``choice`` ("native"|"legacy"); return the resolved mode string written."""
    if choice not in _MODE_MAP:
        raise ValueError(f"Unknown sandbox mode {choice!r}; expected native or legacy")
    if choice == "native":
        _set_pyproject_sandbox(root, "required")
        _set_local_env(root, None)
    else:
        _set_local_env(root, "legacy")
    return _MODE_MAP[choice]


def _set_pyproject_sandbox(root: Path, value: str) -> None:
    """Set [tool.parrot.sdd] sandbox = value with minimal text edits; validate with tomllib."""
    path = root / "pyproject.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines(keepends=True)
    section_start = next((index for index, line in enumerate(lines) if line.strip() == "[tool.parrot.sdd]"), None)

    if section_start is None:
        updated = f'{original}\n[tool.parrot.sdd]\nsandbox = "{value}"\n'
    else:
        section_end = next(
            (index for index in range(section_start + 1, len(lines)) if lines[index].lstrip().startswith("[")),
            len(lines),
        )
        sandbox_line = next(
            (
                index
                for index in range(section_start + 1, section_end)
                if "=" in lines[index] and lines[index].split("=", 1)[0].strip() == "sandbox"
            ),
            None,
        )
        if sandbox_line is None:
            lines.insert(section_start + 1, f'sandbox = "{value}"\n')
        else:
            lines[sandbox_line] = f'sandbox = "{value}"\n'
        updated = "".join(lines)

    try:
        tomllib.loads(updated)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot update {path}: generated invalid TOML ({exc})") from exc
    if updated != original:
        path.write_text(updated, encoding="utf-8")


def _set_local_env(root: Path, value: str | None) -> None:
    """Set (or remove when None) env[MODE_ENV] in .claude/settings.local.json."""
    from parrot.knowledge.wiki.claude_code.installer import _load_settings, _write_settings
    from parrot.sdd.scripts.native_claude_sandbox import MODE_ENV

    path = root / ".claude" / "settings.local.json"
    settings = _load_settings(path) or {}
    changed = False
    environment = settings.get("env")
    if environment is None:
        if value is None:
            return
        environment = settings["env"] = {}
        changed = True
    if not isinstance(environment, dict):
        raise RuntimeError(f"{path}: 'env' is not a JSON object")

    if value is None:
        if MODE_ENV in environment:
            environment.pop(MODE_ENV)
            changed = True
        if not environment:
            if "env" in settings:
                settings.pop("env")
                changed = True
    else:
        if environment.get(MODE_ENV) != value:
            environment[MODE_ENV] = value
            changed = True
    if changed:
        _write_settings(path, settings)


def sandbox_mode_wizard(root: Path, *, non_interactive: bool = False, preset: str | None = None) -> str | None:
    """Interactive sandbox-mode selection; returns the chosen mode ("native"/"legacy") or None (skipped)."""
    if preset is not None:
        write_sandbox_mode(root, preset)
        return preset
    if non_interactive:
        return current_sandbox_mode(root)
    from rich.prompt import Prompt

    from parrot.cli.console import get_console

    get_console().print(_WIZARD_TEXT)
    answer = Prompt.ask("Choice", choices=["1", "2", "3"], default="1", console=get_console())
    if answer == "1":
        write_sandbox_mode(root, "native")
        return "native"
    if answer == "2":
        write_sandbox_mode(root, "legacy")
        return "legacy"
    return current_sandbox_mode(root)
