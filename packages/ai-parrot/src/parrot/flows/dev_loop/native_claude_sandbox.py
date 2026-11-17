"""Compatibility shim — moved to ``parrot.sdd.scripts.native_claude_sandbox`` (FEAT-633 TASK-5093).

Importers keep ``from parrot.flows.dev_loop import native_claude_sandbox``. Run as a script (the
``launch-worker`` entry used by ``scripts/sdd/launch_worker.sh``) it executes the moved file with the stdlib
only. Imported bare (``import native_claude_sandbox``) by a ``python -S`` sibling script such as
``feature_launcher.py``, ``parrot`` is not importable, so the moved file is loaded by path — also stdlib only.
"""
import sys

if __name__ == "__main__":
    import runpy
    from pathlib import Path

    # parrot/flows/dev_loop/native_claude_sandbox.py -> parents[2] is the `parrot` package dir.
    runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "sdd" / "scripts" / "native_claude_sandbox.py"),
        run_name="__main__",
    )
else:
    try:
        from parrot.sdd.scripts import native_claude_sandbox as _impl
    except ImportError:  # python -S sibling import: no site-packages, so no `parrot` — load by path
        import importlib.util
        from pathlib import Path

        _path = Path(__file__).resolve().parents[2] / "sdd" / "scripts" / "native_claude_sandbox.py"
        _spec = importlib.util.spec_from_file_location(__name__, _path)
        assert _spec is not None and _spec.loader is not None
        _impl = importlib.util.module_from_spec(_spec)
        sys.modules[__name__] = _impl  # the moved file's own sibling imports may look it up
        _spec.loader.exec_module(_impl)

    sys.modules[__name__] = _impl
