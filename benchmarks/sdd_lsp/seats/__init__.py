"""Operator-owned pilot seats for the FEAT-580 live evaluation (TASK-3514).

A "seat" here is exactly what ``benchmarks.sdd_lsp.runner`` expects in a
``PilotManifest.seats`` entry's ``argv``: a real, already-existing CLI the
operator configured, never invented or auto-selected by the harness
(spec §3 M5). Nothing in this package is a new LLM client or CLI
dispatcher -- every capability it composes (``BedrockMantleClient`` via
``LLMFactory``, ``parrot.bots.Agent``'s tool-calling loop,
``parrot_tools.lsp.toolkit.LSPToolkit``) already ships in this repo.
"""

__all__ = ()
