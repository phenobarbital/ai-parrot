"""Deterministic page renderers (FEAT-481, spec §3.1).

Every contract page template is reproduced **verbatim** (exact heading
structure, section order, tables) by a Python renderer here — the LLM
never emits page markdown directly; it returns a validated Pydantic
model whose typed fields the renderer places into the fixed structure.
This confines the LLM to *content*, never *layout* (§3.1), and makes
conformance testable heading-by-heading (Module 16).
"""

from __future__ import annotations
