"""FEAT-608 TASK-3808 — entries.py relocation invariants (AC16)."""
import subprocess
import sys

sys.modules.pop("parrot.interfaces.file", None)


def test_entries_module_is_graph_free():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import parrot.interfaces.file.entries, sys; "
            "assert not any(name.startswith(('msgraph', 'kiota', 'aiogoogle')) for name in sys.modules)",
        ],
        check=True,
    )


def test_graph_reexports_relocated_names():
    from parrot.interfaces.file import entries, graph

    assert graph.DriveEntry is entries.DriveEntry
    assert graph._GuardedFileServingExtension is entries.GuardedFileServingExtension
    assert "DriveEntry" in graph.__all__
