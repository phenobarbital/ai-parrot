"""``python -m parrot_tools.contracts`` entrypoint (FEAT-539 M11).

Deployment configuration (DSN, storage roots, ontology directory, LLM
adapter) lives outside this package, so the module-level entrypoint asks
for a service factory rather than inventing one. Wire it in your
deployment::

    from parrot_tools.contracts.cli import main
    raise SystemExit(main(factory=build_contract_services))
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
