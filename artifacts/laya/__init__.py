"""FEAT-589 — standalone CPU evaluation of Laya typed decisions (spec: sdd/specs/laya-adoption.spec.md).

Host-side modules depend on Pydantic and (where stated) on ``parrot``; ``worker.py`` is the only
module that runs inside the isolated Laya environment and imports nothing from this package.
"""
