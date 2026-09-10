"""Fully offline local agent over LanceDB (FEAT-542, AC6).

Provisioning is a SEPARATE, prior step: this script never downloads weights
and never falls back to a remote provider. Missing assets are actionable
failures.

"Offline" here means the WHOLE path — embedding + LLM — is local and
provisioned in advance, not merely that storage is a local directory (see
``docs/lancedb-offline-profile.md``).

Run (after provisioning a local embedding model and a local OpenAI-compatible
LLM server, e.g. Ollama):

    python examples/lancedb_local_agent.py \\
        --data-dir ./data/agent-knowledge \\
        --model-path /path/to/local/sentence-transformers/model \\
        --llm-base-url http://localhost:11434/v1 \\
        --llm-model llama3.1:8b \\
        --collection agent_knowledge \\
        --query "What does the corpus say about X?"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Loopback hosts permitted for the local LLM server — no other host is
# accepted (spec §1 Non-Goals: no remote provider fallback at runtime).
_ALLOWED_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Local directory for the LanceDB collection (storage).")
    parser.add_argument(
        "--model-path",
        required=True,
        help="Local filesystem path to a pre-provisioned sentence-transformers embedding model.",
    )
    parser.add_argument(
        "--llm-base-url",
        required=True,
        help="Base URL of a local OpenAI-compatible LLM server (loopback only).",
    )
    parser.add_argument("--llm-model", required=True, help="Model identity served by the local LLM server.")
    parser.add_argument("--collection", default="agent_knowledge", help="LanceDB collection name.")
    parser.add_argument("--dimension", type=int, default=768, help="Embedding vector dimension.")
    parser.add_argument("--query", required=True, help="The question to answer using retrieved context.")
    return parser.parse_args()


def assert_assets_provisioned(args: argparse.Namespace) -> None:
    """Fail with an actionable message if any local asset is missing.

    Raises:
        SystemExit: missing weights, a non-local LLM URL, or an embedding
            model path that does not exist. Never downloads anything.
    """
    model_path = Path(args.model_path)
    if not model_path.exists():
        raise SystemExit(
            f"Missing embedding model asset at {model_path!s}. This script never "
            f"downloads weights — provision the model locally first (see "
            f"docs/lancedb-offline-profile.md 'Provisioning')."
        )

    parsed = urlparse(args.llm_base_url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in _ALLOWED_LOOPBACK_HOSTS:
        raise SystemExit(
            f"--llm-base-url {args.llm_base_url!r} is not a documented loopback address "
            f"({sorted(_ALLOWED_LOOPBACK_HOSTS)}). This profile never falls back to a "
            f"remote LLM provider."
        )

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)  # local directory creation is not "downloading"


async def build_agent(args: argparse.Namespace):
    """Wire LanceDBStore -> LanceDBOrigin -> LocalLLMClient for one retrieval+answer cycle.

    Returns:
        A tuple ``(store, origin, llm_client)`` — the minimal set of
        already-verified components needed for :func:`run_cycle`. This
        profile deliberately does not route through a full agentic
        tool-calling loop (``BasicAgent``): that would require verifying a
        materially larger, separately-evolving constructor/tool-registration
        surface that this task's Codebase Contract does not pin down in
        enough detail to implement without guessing. Retrieval + a single
        grounded LLM call is the smallest path that still exercises the
        real offline contract end to end (spec §2, AC6).
    """
    from parrot.clients.local import (
        LocalLLMClient,
    )  # verified: packages/ai-parrot-client-local/src/parrot/clients/local/__init__.py:1
    from parrot.stores.lancedb import LanceDBStore
    from parrot_tools.multistoresearch.origins import LanceDBOrigin

    embedding_model = {
        "model_type": "huggingface",
        "model_name": args.model_path,  # local path, not a hub identifier
    }
    store = LanceDBStore(
        uri=args.data_dir,
        collection_name=args.collection,
        dimension=args.dimension,
        embedding_model=embedding_model,
        embedding_id=f"local:{args.model_path}",
    )
    await store.connection()

    origin = LanceDBOrigin(store, name="lancedb-local", mode="hybrid", collection=args.collection)

    # ``LocalLLMClient`` resolves an optional bearer token from the
    # ``LOCAL_LLM_API_KEY`` environment variable — required by servers started
    # with a key (e.g. llama.cpp's ``--api-key`` / ``LLAMA_API_KEY``), ignored
    # by servers that accept anonymous requests. A local key is not "remote
    # credentials": the profile still refuses any non-loopback base URL above.
    llm_client = LocalLLMClient(base_url=args.llm_base_url, model=args.llm_model)

    return store, origin, llm_client


async def run_cycle(origin, llm_client, query: str) -> str:
    """One retrieval + answer cycle grounded in locally retrieved content."""
    hits = await origin.search(query, k=5)
    if not hits:
        context = "(no matching local documents were found)"
    else:
        context = "\n\n".join(f"- {hit.content}" for hit in hits)

    prompt = (
        "Answer the question using ONLY the context below. If the context does "
        "not contain the answer, say so explicitly.\n\n"
        f"Context:\n{context}\n\nQuestion: {query}\nAnswer:"
    )
    # ``AbstractClient.__aenter__`` is what builds the per-event-loop SDK
    # client (``_ensure_client()``); calling ``ask()`` on a merely-constructed
    # client raises ``AttributeError: 'NoneType' object has no attribute
    # 'chat'``. The context manager is the documented public lifecycle —
    # entering it here keeps ``build_agent()``'s return contract unchanged.
    async with llm_client as client:
        response = await client.ask(prompt)
    return getattr(response, "content", str(response))


async def main() -> None:
    args = parse_args()
    assert_assets_provisioned(args)
    store, origin, llm_client = await build_agent(args)
    try:
        answer = await run_cycle(origin, llm_client, args.query)
        logger.info("Answer: %s", answer)
    finally:
        await store.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
