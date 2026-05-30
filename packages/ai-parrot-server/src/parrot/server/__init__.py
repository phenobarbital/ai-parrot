# parrot/server/__init__.py
"""AI-Parrot Server package metadata.

Holds the distribution version for ``ai-parrot-server``. The server's
runtime code lives in the sibling ``parrot.*`` namespace packages
(``parrot.handlers``, ``parrot.mcp``, ``parrot.a2a``, ``parrot.scheduler``,
``parrot.autonomous``, ...).
"""
from .version import __version__

__all__ = ["__version__"]
