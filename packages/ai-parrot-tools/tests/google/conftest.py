"""Google toolkit tests need the real ``parrot.interfaces.file`` package.

The repo-root ``conftest.py`` registers a lightweight ``parrot.interfaces.file``
stub (a plain module, not a package), which makes ``parrot.interfaces.file.gdrive``
unimportable and breaks ``parrot_tools.google`` at collection time. Drop the stub
so the real package is imported.
"""
import sys

sys.modules.pop("parrot.interfaces.file", None)
