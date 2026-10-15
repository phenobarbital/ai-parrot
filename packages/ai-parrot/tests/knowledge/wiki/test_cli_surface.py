"""CLI command/option inventory unchanged (FEAT-540 §5).

Regenerate the baseline deliberately with ``UPDATE_GOLDEN=1 pytest tests/knowledge/wiki/test_cli_surface.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from parrot.knowledge.wiki.cli import wiki

GOLDEN = Path(__file__).parent / "golden" / "cli_surface.json"


def collect_surface(cmd: click.Command, path: list[str], parent: click.Context | None = None) -> dict[str, dict]:
    """Recursively collect ``{command path: {options, arguments}}`` for a click command tree."""
    ctx = click.Context(cmd, info_name=path[-1], parent=parent)
    options = sorted({o for p in cmd.params if isinstance(p, click.Option) for o in (*p.opts, *p.secondary_opts)})
    arguments = sorted(p.name or "" for p in cmd.params if isinstance(p, click.Argument))
    surface: dict[str, dict] = {" ".join(path): {"arguments": arguments, "options": options}}
    if isinstance(cmd, click.Group):
        for name in cmd.list_commands(ctx):
            sub = cmd.get_command(ctx, name)
            if sub is not None:
                surface.update(collect_surface(sub, [*path, name], ctx))
    return surface


def test_cli_surface_matches_golden() -> None:
    """Every command path and option name equals the captured baseline."""
    current = collect_surface(wiki, ["wiki"])
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    baseline = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(current) == sorted(baseline), (
        f"commands added={sorted(set(current) - set(baseline))} removed={sorted(set(baseline) - set(current))}"
    )
    for name, entry in baseline.items():
        assert current[name] == entry, f"{name}: {current[name]} != {entry}"
