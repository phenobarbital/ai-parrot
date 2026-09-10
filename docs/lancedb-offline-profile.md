# Fully offline local agent with LanceDB (FEAT-542)

## What "offline" means here

**Storage locality is not offline.** A local LanceDB directory needs no
network at all for connect/ingest/vector/FTS/hybrid — this was proven
directly against the real SDK in `sdd/state/FEAT-542/lancedb-sdk-contract.md`
(TASK-3057's gate) and re-proven at the store level in
`test_offline_storage_path_denies_sockets`
(`packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py`). But a
local directory alone would still dial out for embeddings and for LLM
completions if either pointed at a remote provider.

This profile (`examples/lancedb_local_agent.py`) is offline because **both
the embedding model and the LLM are local and provisioned in advance** —
never downloaded at runtime, and never falling back to a remote provider.

## Provisioning (network required — done once, before going offline)

1. **Embedding model.** Download a sentence-transformers model to a local
   path (any model already supported by
   `parrot.embeddings.huggingface.SentenceTransformerModel`, e.g.
   `sentence-transformers/all-mpnet-base-v2` or a smaller model such as
   `all-MiniLM-L6-v2`):
   ```bash
   python -c "from sentence_transformers import SentenceTransformer; \
     SentenceTransformer('sentence-transformers/all-mpnet-base-v2') \
       .save('./local-models/all-mpnet-base-v2')"
   ```
   The saved directory path is what `--model-path` expects — the profile
   passes it as `embedding_model={"model_type": "huggingface", "model_name":
   <local path>}`, never a hub identifier fetched at runtime.

2. **Local LLM server.** Provision an OpenAI-compatible local server, e.g.
   [Ollama](https://ollama.com):
   ```bash
   ollama pull llama3.1:8b
   ollama serve  # exposes an OpenAI-compatible API at http://localhost:11434/v1
   ```
   Any of `LocalLLMClient`'s documented targets works (Ollama, vLLM,
   llama.cpp, LM Studio) — see
   `packages/ai-parrot-client-local/src/parrot/clients/local/client.py`.

   **If the local model is a reasoning model**, start the server with thinking
   disabled (llama.cpp: `--reasoning off`, or `--reasoning-budget 0`).
   `run_cycle()` reads `response.content`; with `--reasoning-format deepseek`
   a thinking model puts its chain of thought in `reasoning_content` and can
   spend its entire token budget there, leaving `content` empty. Observed
   directly: Qwen3.6-35B-A3B emitted 3 849 reasoning tokens (~15 min at
   4.5 t/s) for a one-sentence retrieval question before being cut off. This
   is a property of the *model configuration*, not of the offline path.

3. **LanceDB collection directory.** A plain local filesystem path — no
   provisioning step beyond having free disk space. No PostgreSQL, no
   Docker, no storage account, no remote endpoint.

## Running with egress denied

The acceptance test
(`packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_offline_agent.py::TestRealOfflineRun::test_full_cycle_with_egress_denied`)
monkeypatches `socket.socket.connect` so that any outbound connection whose
destination host is not the configured local LLM server's loopback host
(`localhost` / `127.0.0.1` / `::1` / the exact `--llm-base-url` host) raises
`AssertionError` immediately. This denies outside DNS/HTTP and any automatic
model-fetch attempt across the WHOLE exercised path (ingest, vector search,
FTS, hybrid search, and the LLM call) — not only the storage layer, which is
the distinction spec v0.2 added to AC6 (see spec §9 S11).

The test is gated behind the existing `real_llm` marker (registered in
`pytest.ini`, **not** a new custom marker) plus three environment variables:

| Variable | Meaning |
|---|---|
| `PARROT_TEST_REAL_LLM=1` | Opt in to real-model tests, per the existing repo convention. |
| `PARROT_LOCAL_EMBEDDING_MODEL_PATH` | Local filesystem path to the provisioned embedding model (step 1 above). |
| `PARROT_LOCAL_LLM_BASE_URL` | Base URL of the provisioned local LLM server (step 2 above), e.g. `http://localhost:11434/v1`. |
| `PARROT_LOCAL_LLM_MODEL` | Optional; model identity served by that URL. Defaults to `llama3.1:8b`. |
| `LOCAL_LLM_API_KEY` | Optional; bearer token, when the local server was started with one (llama.cpp's `--api-key` / `LLAMA_API_KEY`). Read by `LocalLLMClient` itself, not by the test. A key for a loopback server is not a remote credential — the profile still refuses any non-loopback `--llm-base-url`. |
| `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` | Recommended. Stops `sentence-transformers`/`transformers` from making revision-check calls to huggingface.co for a locally-saved model. Without them the egress guard is what catches the attempt — as an `AssertionError`, not a skip. |

Without these set, the test **skips with an explicit reason** rather than
running against a fake provider — a deterministic fake embedding/LLM
provider is NOT offline certification for AC6 (spec v0.2). General/unit
tests elsewhere in this feature use the deterministic 8-D fixture; this one
specific test is the one that must run against real local assets to certify
the offline claim.

## Verified run (evidence)

AC6 was certified on 2026-09-10 against real local assets on this hardware:

| Component | What was actually used |
|---|---|
| Embedding model | `sentence-transformers/all-mpnet-base-v2`, saved to a local directory (768-dim), loaded on `cuda` from that path — never a hub identifier |
| LLM server | llama.cpp (`ai-parrot/llama-server:cuda`, container `parrot-llama-server`), `http://localhost:8089/v1`, model alias `qwen3.6-35b-a3b` (`bartowski/Qwen_Qwen3.6-35B-A3B-GGUF:Q4_K_M`) |
| Store | `LanceDBStore` on a `tmp_path` directory, `lancedb==0.38.0`, hybrid `LanceDBOrigin` |
| Egress | `socket.socket.connect` patched to allow only the loopback LLM host; the whole ingest → vector/FTS/hybrid → answer path ran under it |

Full command and output: `artifacts/logs/TASK-3068-lancedb.log`.

Note on the client lifecycle: `run_cycle()` enters the client as an async
context manager (`async with llm_client as client`). `AbstractClient.__aenter__`
is what builds the per-event-loop SDK client via `_ensure_client()`; calling
`ask()` on a merely-constructed `LocalLLMClient` raises
`AttributeError: 'NoneType' object has no attribute 'chat'`. That defect was
present until the real run exercised it — a deterministic fake client would
never have caught it, which is the concrete argument for AC6 requiring a real
run.

## Failure modes

| Condition | What happens |
|---|---|
| Embedding model path does not exist | `assert_assets_provisioned()` raises `SystemExit` naming the missing path. No download is attempted. |
| `--llm-base-url` is not a documented loopback address | `assert_assets_provisioned()` raises `SystemExit` explaining the profile never falls back to a remote LLM provider. |
| Local LLM server is unreachable | The real-run test skips (guard tests) or the OpenAI-compatible client raises a connection error at call time (real run) — never silently retried against a remote endpoint. |
| Reopening with an incompatible embedding dimension/identity | `LanceDBStore.create_collection()` raises `ValueError` naming the mismatch; existing data is never overwritten (see `CollectionManifest.check_compatible`, TASK-3059/3062). |

## What this profile does NOT do

- Download or vendor weights — provisioning (above) is a separate, prior,
  network-requiring step the profile script never performs itself.
- Make the whole AI-Parrot framework offline — only this documented
  ingest → retrieve → answer path, using `LanceDBStore`, `LanceDBOrigin`
  and `LocalLLMClient`, is covered.
- Use a full agentic tool-calling loop (`BasicAgent`) — the profile wires
  retrieval (`LanceDBOrigin.search`) directly into a single grounded
  `LocalLLMClient.ask()` call, which is the smallest path that still
  exercises the real offline contract end to end without guessing at a
  separately-evolving tool-registration surface this task's Codebase
  Contract does not pin down.
