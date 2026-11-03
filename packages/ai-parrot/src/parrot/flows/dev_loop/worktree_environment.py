"""Compatibility shim — moved to ``parrot.sdd.scripts.worktree_environment`` (FEAT-633 C16/C19).

Importers keep ``from parrot.flows.dev_loop.worktree_environment import …``. Run as a script (the live
``python3 <this path> --hook`` hooks), it executes the moved file with the stdlib only, so a bare
interpreter keeps working. Imported bare (``import worktree_environment``) by a ``python -S`` sibling
script such as ``feature_launcher.py`` (FEAT-768), ``parrot`` is not importable, so the moved file is
loaded by path — also stdlib only.
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
    try:
        from parrot.sdd.scripts import worktree_environment as _impl
    except ImportError:  # python -S sibling import: no site-packages, so no `parrot` — load by path
        import importlib.util
        from pathlib import Path

        _path = Path(__file__).resolve().parents[2] / "sdd" / "scripts" / "worktree_environment.py"
        _spec = importlib.util.spec_from_file_location(__name__, _path)
        assert _spec is not None and _spec.loader is not None
        _impl = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_impl)

    sys.modules[__name__] = _impl
