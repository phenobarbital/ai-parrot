"""CrossDomainRouter for multi-agent memory sharing.

Ports the cross-domain routing logic from AgentCoreMemory into a standalone
component for the UnifiedMemoryManager. Enables agents to discover other
agents whose expertise is semantically relevant to a given query and include
their memories (with a decay factor) in the results.

Agent expertise embeddings are computed on-the-fly from domain descriptions
and cached in-memory. Tenant boundaries are strictly enforced.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentExpertise(BaseModel):
    """Registry entry for an agent's domain expertise.

    Args:
        agent_id: The agent's unique identifier.
        tenant_id: The tenant this agent belongs to (isolation boundary).
        domain_description: Human-readable description of the agent's expertise.
        embedding: Cached embedding of the domain description (None until computed).
    """

    agent_id: str
    tenant_id: str
    domain_description: str
    embedding: list[float] | None = None


class CrossDomainRouter(BaseModel):
    """Routes memory queries to relevant agent namespaces for multi-agent sharing.

    Maintains an in-memory registry of agent expertise descriptions. When
    ``find_relevant_agents()`` is called, it embeds each registered agent's
    domain description (lazily, then cached) and computes cosine similarity
    with the query embedding. Agents above the similarity threshold (excluding
    the current agent and different tenants) are returned.

    The ``cross_domain_decay`` factor is available to callers for weighting
    cross-domain results lower than same-agent results.

    Args:
        similarity_threshold: Minimum cosine similarity for an agent to be
            considered relevant. Default 0.5.
        cross_domain_decay: Decay factor to apply to cross-domain results.
            Default 0.6. (Callers apply this; router does not modify scores.)
        max_relevant_agents: Maximum number of agents to return. Default 2.
    """

    similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    cross_domain_decay: float = Field(default=0.6, ge=0.0, le=1.0)
    max_relevant_agents: int = Field(default=2, ge=1)

    # Private registry: agent_id → AgentExpertise
    # Using a plain dict (not Pydantic field) to avoid serialization issues
    model_config = {"arbitrary_types_allowed": True}

    def model_post_init(self, __context: Any) -> None:
        """Initialize the private registry after Pydantic model init."""
        object.__setattr__(self, "_registry", {})
        object.__setattr__(self, "_lock", asyncio.Lock())

    def register_agent_expertise(
        self,
        agent_id: str,
        tenant_id: str,
        domain_description: str,
    ) -> None:
        """Register or update an agent's domain expertise.

        Invalidates any cached embedding for this agent if the description
        has changed.

        Args:
            agent_id: The agent's unique identifier.
            tenant_id: The tenant this agent belongs to.
            domain_description: Human-readable description of the agent's expertise.
        """
        registry: dict[str, AgentExpertise] = object.__getattribute__(self, "_registry")
        existing = registry.get(agent_id)
        if existing is not None and existing.domain_description != domain_description:
            # Invalidate cached embedding on description change
            registry[agent_id] = AgentExpertise(
                agent_id=agent_id,
                tenant_id=tenant_id,
                domain_description=domain_description,
                embedding=None,
            )
        else:
            registry[agent_id] = AgentExpertise(
                agent_id=agent_id,
                tenant_id=tenant_id,
                domain_description=domain_description,
                embedding=existing.embedding if existing else None,
            )

    def list_registered_agents(self) -> list[str]:
        """Return list of registered agent IDs.

        Returns:
            List of agent IDs in the registry.
        """
        registry: dict[str, AgentExpertise] = object.__getattribute__(self, "_registry")
        return list(registry.keys())

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            a: First embedding vector.
            b: Second embedding vector.

        Returns:
            Cosine similarity in [-1.0, 1.0], or 0.0 if either vector is zero.
        """
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def find_relevant_agents(
        self,
        query_embedding: list[float],
        current_agent_id: str,
        embedding_provider: Any,
        tenant_id: str,
    ) -> list[str]:
        """Find agents whose expertise is semantically relevant to the query.

        Computes cosine similarity between the query embedding and each
        registered agent's domain embedding (computed lazily and cached).
        Returns agents above ``similarity_threshold``, excluding the current
        agent and agents from different tenants.

        Args:
            query_embedding: Pre-computed embedding vector for the query.
            current_agent_id: The calling agent's ID (excluded from results).
            embedding_provider: An object with ``async def embed(text) -> list[float]``.
                Used to compute domain description embeddings on first access.
            tenant_id: The calling agent's tenant (cross-tenant sharing is forbidden).

        Returns:
            List of relevant agent IDs, sorted by descending similarity,
            up to ``max_relevant_agents``.
        """
        registry: dict[str, AgentExpertise] = object.__getattribute__(self, "_registry")
        lock: asyncio.Lock = object.__getattribute__(self, "_lock")

        if not registry:
            return []

        # Ensure all expertise embeddings are computed
        agents_to_embed = [
            expertise
            for agent_id, expertise in registry.items()
            if expertise.embedding is None
            and expertise.tenant_id == tenant_id
            and agent_id != current_agent_id
        ]

        if agents_to_embed:
            async with lock:
                # Re-check under lock (another coroutine may have populated)
                for expertise in agents_to_embed:
                    if expertise.embedding is None:
                        try:
                            emb = await embedding_provider.embed(expertise.domain_description)
                            registry[expertise.agent_id] = AgentExpertise(
                                agent_id=expertise.agent_id,
                                tenant_id=expertise.tenant_id,
                                domain_description=expertise.domain_description,
                                embedding=emb,
                            )
                        except Exception as e:
                            logger.warning(
                                "Failed to embed expertise for agent %s: %s",
                                expertise.agent_id,
                                e,
                            )

        # Compute similarities
        scored: list[tuple[float, str]] = []
        for agent_id, expertise in registry.items():
            # Exclude current agent
            if agent_id == current_agent_id:
                continue
            # Enforce tenant boundary
            if expertise.tenant_id != tenant_id:
                continue
            # Skip agents without embeddings
            if expertise.embedding is None:
                continue

            similarity = self._cosine_similarity(query_embedding, expertise.embedding)
            if similarity >= self.similarity_threshold:
                scored.append((similarity, agent_id))

        # Sort by similarity descending, return top N
        scored.sort(key=lambda x: x[0], reverse=True)
        return [agent_id for _, agent_id in scored[: self.max_relevant_agents]]
