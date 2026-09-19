"""Research pilot benchmark for FEAT-580 (SDD LSP toolkit adoption).

This package holds the offline-safe contracts and accounting for the
five-arm, 12-task, three-repetition pilot described in
``sdd/specs/sdd-research-lsp.spec.md`` §2 Evaluation. Nothing in this
module spawns a process, calls a provider SDK, or invents a price: an
unknown token count or price stays ``None`` and never becomes a savings
claim.

Run the (future) offline pilot CLI with::

    python -m benchmarks.sdd_lsp --manifest <path> --output-dir <path>
"""

__all__ = ()
