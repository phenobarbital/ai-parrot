"""Specialist that clones an existing agent definition with mutations."""
from __future__ import annotations

from typing import Any, ClassVar, List

from parrot.bots.factory.builders.base import COMMON_SCHEMA_NOTES, BaseFactoryBuilder
from parrot.bots.factory.contracts import (
    BuilderOutput,
    BuilderType,
    FactoryRequest,
    RouterDecision,
)


_CLONE_PROMPT = f"""\
You are CloneAgentBuilder, a specialist that clones an existing ai-parrot
agent definition and applies the user's requested mutations.

Decision flow:
1. Call `list_registered_agents` to confirm the source agent exists.
2. Call `load_agent_definition` with the source agent's name to obtain its
   current YAML payload as a dict.
3. Produce a BuilderOutput whose `definition` mirrors the source EXCEPT for
   the fields the user wants changed (typical: name, system_prompt, tags,
   vector_store.table). Keep model + toolkits unless told otherwise.
4. Generate a new unique `name`. Do not reuse the source name.
5. Add a ProvisioningRecord(kind="other", name="cloned_from:<source>") so
   the orchestrator can surface the lineage.

{COMMON_SCHEMA_NOTES}
"""


class CloneAgentBuilder(BaseFactoryBuilder):
    """Specialist that produces cloned agent definitions."""

    builder_type: ClassVar[BuilderType] = BuilderType.CLONE
    system_prompt: ClassVar[str] = _CLONE_PROMPT

    def _tools(self) -> List[Any]:
        from parrot.bots.factory.tools.introspection import (
            _list_registered_agents_tool,
            _load_agent_definition_tool,
        )

        return [
            *super()._tools(),
            _list_registered_agents_tool,
            _load_agent_definition_tool,
        ]

    def _render_user_prompt(
        self,
        request: FactoryRequest,
        decision: RouterDecision,
    ) -> str:
        clone_hint = ""
        if request.clone_from:
            clone_hint = (
                f"\nSource agent to clone from: {request.clone_from}\n"
                "Load it with `load_agent_definition` before producing the "
                "BuilderOutput.\n"
            )
        return super()._render_user_prompt(request, decision) + clone_hint

    async def build(
        self,
        request: FactoryRequest,
        decision: RouterDecision,
    ) -> BuilderOutput:
        if not request.clone_from:
            raise ValueError(
                "CloneAgentBuilder requires FactoryRequest.clone_from to be "
                "set — the router should have populated it before delegating."
            )
        return await super().build(request, decision)
