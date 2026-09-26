"""``python -m parrot_tools.procedures`` entrypoint (FEAT-601 M13)."""

from __future__ import annotations

from .cli import manuals

if __name__ == "__main__":  # pragma: no cover - process entrypoint
    manuals(prog_name="python -m parrot_tools.procedures")
