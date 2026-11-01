"""Compatibility shim — moved to ``parrot.sdd.scripts.worktree_environment`` (FEAT-633 C16/C19).

Importers keep ``from parrot.flows.dev_loop.worktree_environment import …``. Run as a script (the live
``python3 <this path> --hook`` hooks), it executes the moved file with the stdlib only, so a bare
interpreter keeps working.
"""
import sys

if __name__ == "__main__":
    import runpy
    from pathlib import Path

    # parrot/flows/dev_loop/worktree_environment.py -> parents[2] is the `parrot` package dir.
    runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "sdd" / "scripts" / "worktree_environment.py"),
        run_name="__main__",
    )
else:
    from parrot.sdd.scripts import worktree_environment as _impl

    sys.modules[__name__] = _impl
