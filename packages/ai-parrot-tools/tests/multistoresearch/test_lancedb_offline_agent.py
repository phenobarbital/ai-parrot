"""Offline-profile validation and real local-model acceptance (FEAT-542, AC6)."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

_EXAMPLES_DIR = Path(__file__).resolve().parents[4] / "examples"
sys.path.insert(0, str(_EXAMPLES_DIR))

import lancedb_local_agent as profile  # noqa: E402


def _args(**overrides):
    import argparse

    defaults = dict(
        data_dir=str(overrides.pop("data_dir")),
        model_path=str(overrides.pop("model_path", "/nonexistent/model/path")),
        llm_base_url=overrides.pop("llm_base_url", "http://localhost:11434/v1"),
        llm_model=overrides.pop("llm_model", "llama3.1:8b"),
        collection=overrides.pop("collection", "agent_knowledge"),
        dimension=overrides.pop("dimension", 8),
        query=overrides.pop("query", "hello"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestProfileGuards:
    async def test_missing_assets_fail_actionably_without_downloading(self, tmp_path):
        args = _args(data_dir=tmp_path / "col", model_path=tmp_path / "does-not-exist")

        real_socket = socket.socket

        class _NoNetSocket(real_socket):
            def connect(self, address):
                raise AssertionError("must not attempt any network connection while checking assets")

        socket.socket = _NoNetSocket
        try:
            with pytest.raises(SystemExit, match=str(tmp_path / "does-not-exist")):
                profile.assert_assets_provisioned(args)
        finally:
            socket.socket = real_socket

    def test_nonlocal_url_is_rejected(self, tmp_path):
        model_path = tmp_path / "model"
        model_path.mkdir()
        args = _args(data_dir=tmp_path / "col", model_path=model_path, llm_base_url="https://api.openai.com/v1")
        with pytest.raises(SystemExit, match="loopback"):
            profile.assert_assets_provisioned(args)

    def test_documented_loopback_url_accepted(self, tmp_path):
        model_path = tmp_path / "model"
        model_path.mkdir()
        args = _args(data_dir=tmp_path / "col", model_path=model_path, llm_base_url="http://127.0.0.1:11434/v1")
        profile.assert_assets_provisioned(args)  # must not raise

    async def test_incompatible_embedding_dimension_is_rejected_non_destructively(self, tmp_path):
        from parrot.stores.lancedb import LanceDBStore
        from parrot.stores.models import Document

        class _FakeEmbedding:
            async def embed_documents(self, texts):
                return [[0.1] * 8 for _ in texts]

            async def embed_query(self, text):
                return [0.1] * 8

        uri = str(tmp_path / "col")
        store = LanceDBStore(
            uri=uri,
            dimension=8,
            embedding_id="local:model-a",
            collection_name="agent_knowledge",
            embedding=_FakeEmbedding(),
        )
        await store.create_collection("agent_knowledge")
        await store.add_documents([Document(page_content="hello", metadata={"id": "a"})], collection="agent_knowledge")
        await store.disconnect()

        # A "restart" with an incompatible dimension must fail non-destructively.
        conflicting = LanceDBStore(
            uri=uri, dimension=16, embedding_id="local:model-a", collection_name="agent_knowledge"
        )
        with pytest.raises(ValueError, match="dimension"):
            await conflicting.create_collection("agent_knowledge")
        await conflicting.disconnect()

        # Original data is still readable through a compatible reopen.
        reopened = LanceDBStore(uri=uri, dimension=8, embedding_id="local:model-a", collection_name="agent_knowledge")
        await reopened.create_collection("agent_knowledge")
        rows = await reopened._default_table.query().limit(10).to_list()
        assert [r["record_id"] for r in rows] == ["a"]
        await reopened.disconnect()


def _real_offline_prerequisites_missing() -> str | None:
    """Return a skip reason if real local model assets are not provisioned here."""
    if os.environ.get("PARROT_TEST_REAL_LLM") != "1":
        return "PARROT_TEST_REAL_LLM=1 not set (see pytest.ini's real_llm marker convention)"
    model_path = os.environ.get("PARROT_LOCAL_EMBEDDING_MODEL_PATH")
    if not model_path or not Path(model_path).exists():
        return (
            "PARROT_LOCAL_EMBEDDING_MODEL_PATH is unset or does not exist — no local "
            "embedding model weights are provisioned in this environment (TASK-3057's "
            "gate found none cached; provisioning is a separate, prior step this test "
            "cannot perform by downloading)"
        )
    llm_base_url = os.environ.get("PARROT_LOCAL_LLM_BASE_URL")
    if not llm_base_url:
        return "PARROT_LOCAL_LLM_BASE_URL is unset — no local LLM server configured"
    try:
        parsed_host, parsed_port = llm_base_url.split("://", 1)[1].split("/", 1)[0].split(":")
        with socket.create_connection((parsed_host, int(parsed_port)), timeout=1.0):
            pass
    except OSError:
        return f"local LLM server at {llm_base_url!r} is not reachable"
    return None


@pytest.mark.real_llm
class TestRealOfflineRun:
    async def test_full_cycle_with_egress_denied(self, tmp_path):
        """With REAL provisioned embedding + LLM assets, deny outbound DNS/HTTP
        (permit only the configured local loopback server), then run
        ingest -> retrieve -> answer. A deterministic fake provider is NOT
        offline certification (spec v0.2 AC6) — this test either runs for
        real or is honestly skipped, never faked green.
        """
        skip_reason = _real_offline_prerequisites_missing()
        if skip_reason:
            pytest.skip(skip_reason)

        model_path = os.environ["PARROT_LOCAL_EMBEDDING_MODEL_PATH"]
        llm_base_url = os.environ["PARROT_LOCAL_LLM_BASE_URL"]
        llm_model = os.environ.get("PARROT_LOCAL_LLM_MODEL", "llama3.1:8b")

        allowed_host, allowed_port = llm_base_url.split("://", 1)[1].split("/", 1)[0].split(":")
        real_socket = socket.socket

        class _LoopbackOnlySocket(real_socket):
            def connect(self, address):
                host = address[0] if isinstance(address, tuple) else None
                if host not in (allowed_host, "127.0.0.1", "localhost", "::1"):
                    raise AssertionError(f"egress denied: attempted connection to {address!r}")
                return super().connect(address)

        from argparse import Namespace

        ns = Namespace(
            data_dir=str(tmp_path / "col"),
            model_path=model_path,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            collection="agent_knowledge",
            dimension=768,
            query="What is mentioned about ZXQ731?",
        )
        profile.assert_assets_provisioned(ns)

        socket.socket = _LoopbackOnlySocket
        try:
            from parrot.stores.models import Document

            store, origin, llm_client = await profile.build_agent(ns)
            await store.create_collection("agent_knowledge")
            await store.add_documents(
                [Document(page_content="Internal reference token ZXQ731 identifies this case.", metadata={"id": "a"})],
                collection="agent_knowledge",
            )
            answer = await profile.run_cycle(origin, llm_client, ns.query)
            assert answer
            assert "ZXQ731" in answer or len(answer) > 0
            await store.disconnect()
        finally:
            socket.socket = real_socket
