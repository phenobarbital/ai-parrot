"""Squawk — typed binary inter-agent protocol for parrot-to-parrot cross-network calls (FEAT-746).

The transport-free data contract lives in core ``parrot.interagent``; this package owns
the Cap'n Proto schema and codec, the RPC and bus carriers, the serving dispatcher and
policy gate, the served ledger, the blob store, the client toolkit and the adapters.
"""

from .version import __version__

__all__ = ["__version__"]
