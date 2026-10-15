"""Transport-neutral wiki operation descriptors (FEAT-540 M5)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.wiki.decisions.operations import (
    op_decision_generate,
    op_decision_why,
    op_decisions_for_symbol,
)
from parrot.knowledge.wiki.ledger.operations import (
    op_ledger_claim,
    op_ledger_close,
    op_ledger_context,
    op_ledger_open,
    op_ledger_ready,
)
from parrot.knowledge.wiki.operations import (
    OperationResult,
    op_ingest_batch,
    op_lint,
    op_note,
    op_page,
    op_page_hashes,
    op_query,
    op_related,
    op_remember,
    op_standup,
    op_status,
    op_sync_pull,
    op_sync_push,
    op_vault_ingest,
)
from parrot.knowledge.wiki.schema.operations import (
    op_schema_lookup,
    op_schema_neighbors,
    op_schema_search,
    op_schema_sources,
)
from parrot.knowledge.wiki.structural.operations import (
    op_blast_radius,
    op_code_outline,
    op_symbol_lookup,
)

if TYPE_CHECKING:
    from parrot.knowledge.wiki.mcp_server import WikiToolBundle


class OperationDescriptor(BaseModel):
    """One wiki tool, independent of transport."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    schema_fingerprint: str
    mount: str
    invoke: Callable[[BaseModel], Awaitable[OperationResult]]


_MOUNTS = {
    "wiki_query": "core",
    "wiki_page": "core",
    "wiki_related": "core",
    "wiki_remember": "core",
    "wiki_note": "core",
    "wiki_status": "core",
    "wiki_lint": "core",
    "wiki_standup": "core",
    "wiki_symbol_lookup": "structural",
    "wiki_code_outline": "structural",
    "wiki_blast_radius": "structural",
    "wiki_decisions_for_symbol": "decisions",
    "wiki_decision_why": "decisions",
    "wiki_decision_generate": "decisions",
    "wiki_schema_lookup": "schema",
    "wiki_schema_search": "schema",
    "wiki_schema_neighbors": "schema",
    "wiki_schema_sources": "schema",
    "ledger_open": "ledger",
    "ledger_ready": "ledger",
    "ledger_claim": "ledger",
    "ledger_close": "ledger",
    "ledger_context": "ledger",
    "wiki_page_hashes": "bulk",
    "wiki_ingest_batch": "bulk",
    "wiki_sync_push": "bulk",
    "wiki_sync_pull": "bulk",
    "vault_ingest": "vault",
}


def schema_fingerprint(model: type[BaseModel]) -> str:
    """Return the SHA-256 digest of a canonical Pydantic JSON schema.

    Args:
        model: Pydantic input model used by an operation.

    Returns:
        Stable hexadecimal digest of the model JSON schema.
    """
    canonical_schema = json.dumps(model.model_json_schema(), sort_keys=True)
    return hashlib.sha256(canonical_schema.encode()).hexdigest()


def _operation_invoke(tool: Any) -> Callable[[BaseModel], Awaitable[OperationResult]]:
    """Bind one framework tool's plain operation to its existing context.

    Args:
        tool: Configured framework tool from a ``WikiToolBundle``.

    Returns:
        An operation coroutine that accepts the tool's validated input model.

    Raises:
        ValueError: If the tool does not belong to the wiki operation surface.
    """
    name = tool.name

    if name == "wiki_query":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_query(tool._store, params)

    elif name == "wiki_page":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_page(tool._store, params)

    elif name == "wiki_related":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_related(tool._store, params)

    elif name == "wiki_remember":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_remember(tool._store, params, storage_dir=tool._storage_dir)

    elif name == "wiki_note":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_note(tool._store, params, storage_dir=tool._storage_dir)

    elif name == "wiki_status":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_status(tool._store, params)

    elif name == "wiki_lint":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_lint(tool._store, params, storage_dir=tool._storage_dir)

    elif name == "wiki_standup":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_standup(tool._store, params.model_dump(), root=tool._root, config=tool._config)

    elif name == "wiki_symbol_lookup":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_symbol_lookup(None, params, service_factory=tool._service_factory)

    elif name == "wiki_code_outline":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_code_outline(None, params, service_factory=tool._service_factory)

    elif name == "wiki_blast_radius":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_blast_radius(None, params, service_factory=tool._service_factory)

    elif name == "wiki_decisions_for_symbol":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_decisions_for_symbol(None, params, service_factory=tool._service_factory)

    elif name == "wiki_decision_why":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_decision_why(None, params, service_factory=tool._service_factory)

    elif name == "wiki_decision_generate":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_decision_generate(None, params, service_factory=tool._service_factory)

    elif name == "wiki_schema_lookup":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_lookup(
                None,
                params,
                service=tool._service,
                annotation_store=tool._annotation_store,
            )

    elif name == "wiki_schema_search":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_search(None, params, service=tool._service)

    elif name == "wiki_schema_neighbors":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_neighbors(None, params, service=tool._service)

    elif name == "wiki_schema_sources":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_sources(None, params, service=tool._service)

    elif name == "ledger_open":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_open(tool._ledger_service, params)

    elif name == "ledger_ready":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_ready(tool._ledger_service, params)

    elif name == "ledger_claim":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_claim(tool._ledger_service, params)

    elif name == "ledger_close":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_close(tool._ledger_service, params)

    elif name == "ledger_context":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_context(tool._ledger_service, params)

    elif name == "wiki_page_hashes":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_page_hashes(tool._store, params)

    elif name == "wiki_ingest_batch":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ingest_batch(tool._store, params, root=tool._root, config=tool._config)

    elif name == "wiki_sync_push":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_sync_push(tool._store, params, wiki_name=tool._wiki_name)

    elif name == "wiki_sync_pull":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_sync_pull(tool._store, params)

    elif name == "vault_ingest":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_vault_ingest(tool._store, params, root=tool._root, config=tool._config)

    else:
        raise ValueError(f"Unsupported wiki operation: {name}")
    return invoke


def build_operation_descriptors(bundle_inputs: WikiToolBundle | Any) -> list[OperationDescriptor]:
    """Build descriptors for every operation mounted in a wiki tool bundle.

    The bundle is assembled by ``abuild_wiki_tools`` and already encodes all
    configuration gates: ledger availability, schema-plane presence, bulk
    exposure, and vault availability. Only ``vault_ingest`` is part of this
    registry; the accompanying Obsidian-management tools are not wiki
    operations.

    Args:
        bundle_inputs: A configured ``WikiToolBundle``.

    Returns:
        Ordered, transport-neutral descriptors for each mounted wiki operation.

    Raises:
        ValueError: If a mounted operation name is duplicated or unsupported.
    """
    tools = [*bundle_inputs.tools, *(tool for tool in bundle_inputs.vault_tools if tool.name == "vault_ingest")]
    descriptors: list[OperationDescriptor] = []
    seen_names: set[str] = set()
    for tool in tools:
        name = tool.name
        if name in seen_names:
            raise ValueError(f"Duplicate wiki operation name: {name}")
        seen_names.add(name)
        mount = _MOUNTS.get(name)
        if mount is None:
            raise ValueError(f"Unsupported wiki operation: {name}")
        input_model = tool.args_schema
        descriptors.append(
            OperationDescriptor(
                name=name,
                description=tool.description,
                input_model=input_model,
                schema_fingerprint=schema_fingerprint(input_model),
                mount=mount,
                invoke=_operation_invoke(tool),
            )
        )
    return descriptors
