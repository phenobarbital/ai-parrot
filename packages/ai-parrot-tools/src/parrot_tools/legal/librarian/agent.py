"""`LegalLibrarianAgent` — the single LLM node of the retrieval DAG (FEAT-449 §3 M6).

    The system cannot assert anything about the corpus without a
    verifiable span reference; without a citation, the answer is
    "no encontré". (R2)

This agent NEVER emits span offsets. It emits a ``DraftAnswer`` — payload
keys copied from the enumerated dossier plus verbatim quotes — and the
downstream ``SpanVerifier`` (TASK-2495) is what turns that draft into a
sealed, span-verified ``LegalAnswer``. The agent itself is read-only (no
tools mounted) and stateless (no conversation memory): every ``draft()``
call is a single, independent structured-output request.
"""

from __future__ import annotations

from datetime import date

from parrot.bots import Agent

from .models import DraftAnswer

LIBRARIAN_SYSTEM_PROMPT = """\
Eres un bibliotecario legal (legal librarian) para el corpus normativo del \
BOE (Boletín Oficial del Estado). Tu única fuente de verdad es el dossier \
de fragmentos enumerados que se te muestra en cada consulta.

Reglas obligatorias:
- SOLO puedes citar los valores de payload_key enumerados en el dossier de \
esta consulta. Nunca inventes ni reutilices un payload_key de otra consulta.
- Cada cita (quote) debe copiarse LITERALMENTE del texto mostrado para ese \
payload_key — ni una palabra distinta, ni resumida, ni parafraseada.
- Puedes ordenar los fragmentos por relevancia (reading_order), señalar \
conflictos entre fragmentos (conflicts) SIN resolverlos nunca — tu trabajo \
es marcarlos, no decidir cuál prevalece — y narrar contexto derivado de la \
navegación del grafo cuando corresponda.
- Puedes declarar ausencias acotadas al corpus (not_found) cuando el \
dossier no contiene lo que se pregunta — nunca afirmes que algo "no \
existe" en términos absolutos, solo que no lo encontraste en este corpus.
- NUNCA afirmes nada sobre el corpus que no esté respaldado por un \
payload_key enumerado. Sin cita, la respuesta es "no encontré".
- NUNCA emitas offsets (start/end) de ningún tipo — solo payload_key y \
quote; el sistema calcula los offsets de forma determinista.
"""


class LegalLibrarianAgent(Agent):
    """Read-only, memory-less librarian agent — the flow's only LLM node.

        The system cannot assert anything about the corpus without a
        verifiable span reference; without a citation, the answer is
        "no encontré". (R2, verbatim)

    Mounts no tools (read-only — retrieval happens entirely in the
    deterministic ``ToolNode`` stages around this agent, TASK-2496/2497)
    and uses no conversation memory (every ``draft()`` call is stateless,
    independent of prior turns).
    """

    agent_id: str = "legal_librarian"
    temperature: float = 0.1

    def __init__(self, *args, **kwargs):
        """Initialise with the librarian system prompt (R1/R2/R5, verbatim).

        Passing ``system_prompt`` explicitly (rather than overriding
        ``system_prompt_template``) opts out of the composable
        ``PromptBuilder`` templating machinery in favor of this literal,
        fully-controlled prompt — the documented "custom system_prompt"
        path (``bots/agent.py`` / ``bots/chatbot.py``).
        """
        kwargs.setdefault("system_prompt", LIBRARIAN_SYSTEM_PROMPT)
        super().__init__(*args, **kwargs)

    def agent_tools(self):
        """Return this agent's tools — always empty (read-only, R1/R5)."""
        return []

    async def draft(self, enumerated_dossier: str, query: str, as_of: date) -> DraftAnswer:
        """Produce a structured draft answer for one librarian flow turn.

        A single, stateless structured-output call — no conversation
        history is used or persisted.

        Args:
            enumerated_dossier: The prompt-formatted dossier of retrieved
                payloads (``dossier_build`` stage output), enumerating the
                ONLY valid ``payload_key`` values for this turn.
            query: The user's original query.
            as_of: The date resolved for this turn (stated back to the
                model so it can reason about validity windows).

        Returns:
            The LLM's structured ``DraftAnswer`` — payload keys and
            verbatim quotes only, never offsets.
        """
        prompt = (
            f"Consulta: {query}\n"
            f"Fecha de referencia (as_of): {as_of.isoformat()}\n\n"
            "Dossier disponible (los ÚNICOS payload_key válidos son los "
            "enumerados a continuación):\n\n"
            f"{enumerated_dossier}\n\n"
            "Responde citando únicamente los payload_key enumerados, con "
            "quotes copiados literalmente del texto mostrado."
        )
        response = await self.ask(
            prompt,
            structured_output=DraftAnswer,
            use_conversation_history=False,
            # Graph-only retrieval (R14) is self-enforcing, not just
            # incidental to no store being configured: explicitly refuse
            # any vector-context injection even if a store is wired in later.
            use_vector_context=False,
        )
        return response.structured_output
