"""Root conftest.py for the feat-112-per-loop-llm-client-cache worktree.

Ensures the worktree's package sources take precedence over the main-repo
editable installs registered via .pth files in site-packages.  Without this,
pytest would silently import from the main-repo sources, making FEAT-112
changes invisible to tests.

IMPORTANT: The packages/ai-parrot/tests/conftest.py installs lightweight stubs
for many ``parrot.*`` modules via ``sys.modules.setdefault()``.  That conftest
is processed AFTER this root conftest — so we must ensure that the real
``parrot.models.responses`` (and ``parrot.clients.base``) are fully imported
and registered in ``sys.modules`` BEFORE the test conftest runs.  Once
``sys.modules[key]`` is populated, ``setdefault`` is a no-op.
"""
import sys
import os

# Worktree root — the directory that contains THIS file.
_WORKTREE_ROOT = os.path.dirname(os.path.abspath(__file__))

# Prepend the worktree package src directories so they shadow the main-repo
# editable-install .pth entries.
_EXTRA_PATHS = [
    # ai-parrot core: prepend worktree src so FEAT-112 changes to base.py,
    # google/client.py, grok.py etc. are visible to tests.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot", "src"),
    # ai-parrot-tools: also include worktree version.
    os.path.join(_WORKTREE_ROOT, "packages", "ai-parrot-tools", "src"),
]
for _p in reversed(_EXTRA_PATHS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Force the real parrot.models.responses to be imported NOW (before the
# test conftest registers its stub via setdefault).  The test conftest's
# _install_parrot_stubs() uses setdefault so it won't override a module
# that's already present.
import importlib as _importlib

for _mod_name in (
    "parrot.models.responses",
    "parrot.clients.base",
):
    if _mod_name not in sys.modules:
        try:
            _importlib.import_module(_mod_name)
        except ImportError:
            pass  # noqa: S110 — some deps may not be available in all envs
