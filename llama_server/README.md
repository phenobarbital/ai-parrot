# llama-server (CUDA) — local inference, and Qwen3.6-35B-A3B with experts in RAM

This page documents the manual-start `llama-server` stack we use for local
GPU inference, and the `--n-cpu-moe` recipe that fits
[Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) — a 35 B
Mixture-of-Experts model — onto a 16 GB card by keeping its expert tensors in
host RAM.

| File | Purpose |
|---|---|
| [`docker-compose.llama.yml`](docker-compose.llama.yml) | the stack |
| [`Dockerfile`](Dockerfile) | official image + `curl` + `HEALTHCHECK` |
| [`.env.example`](.env.example) | config template → copy to `.env` |
| `models/` | drop-in dir for local `.gguf` files (contents gitignored) |

Consumed by [`parrot.clients.localllm.LocalLLMClient`](../packages/ai-parrot/src/parrot/clients/localllm.py).

Introduced in commit `fb5f18d4`. Moved into its own `llama_server/` folder
afterwards — all `docker compose` / `cp` commands below assume you have
`cd llama_server` first (paths are relative to this file's directory).

---

## Design decisions baked into the stack

These are deliberate; changing them has consequences.

**Manual start only — `restart: "no"`.** The GPU is shared with interactive
development. The container must never come back on its own after a Docker
daemon restart or a reboot, because it would silently hold VRAM you were
about to use. You start it, you stop it:

```bash
docker compose --env-file .env -f docker-compose.llama.yml up -d   # take the GPU
docker compose --env-file .env -f docker-compose.llama.yml down    # give it back
```

**We extend the official image rather than build llama.cpp.** The Dockerfile
is `FROM ghcr.io/ggml-org/llama.cpp:server-cuda` and adds exactly one thing:
`curl`, because the runtime image ships without it and the `HEALTHCHECK`
needs it. Building llama.cpp + CUDA from source takes >20 minutes and
upstream rebuilds almost daily; inheriting is strictly better.

**Port 8089, not 8080.** Host `8089` maps to container `8080`. 8080 is
crowded on a dev box. The endpoint is therefore
`http://localhost:8089/v1`.

**Two volumes, two ways to supply a model.**

- `llama-models:/root/.cache/llama.cpp` — named volume holding models
  auto-downloaded with `-hf`. Survives `down`, wiped by `down -v`.
- `./models:/models:ro` — read-only bind mount for GGUF files
  you fetched yourself.

**`LLAMA_EXTRA_ARGS` is the escape hatch.** The `command:` block hard-codes
`-hf`, `--host`, `--port`, `--ctx-size`, `--n-gpu-layers` and `--parallel`;
everything else — including `--n-cpu-moe` — is appended through
`LLAMA_EXTRA_ARGS`. That is where the MoE work happens.

**`LLAMA_API_KEY` is passed as an environment variable, not a flag.** This
works: `--api-key` is one of the few llama-server options whose env var is
bare `LLAMA_API_KEY` rather than the usual `LLAMA_ARG_*` form. Leave it empty
for no authentication.

---

## Quick start

```bash
cp .env.example .env
docker compose --env-file .env -f docker-compose.llama.yml up -d
docker compose --env-file .env -f docker-compose.llama.yml logs -f
```

> **`--env-file` is mandatory, not decoration.** See
> [the interpolation trap](#the-env_file-interpolation-trap) below — without
> it your `.env` is silently ignored and you get the defaults.

The default in `.env.example` is deliberately small —
`ggml-org/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M`, about 2.5 GB — so a first run
succeeds on a 6 GB card. Verify:

```bash
curl -s http://localhost:8089/v1/models | jq -r '.data[].id'
curl -s http://localhost:8089/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"default","messages":[{"role":"user","content":"Say hello."}],"max_tokens":64}' \
  | jq -r '.choices[0].message.content'
```

Add `-H "Authorization: Bearer $LLAMA_API_KEY"` if you set a key.

The built-in web UI is at <http://localhost:8089/>.

---

## Why experts belong in RAM

Qwen3.6-35B-A3B is a sparse MoE model:

| Property | Value |
|---|---|
| Total parameters | 35 B |
| Activated per token | ~3 B |
| Layers | **40** |
| Experts per layer | 256 |
| Experts activated per token | 8 routed + 1 shared |
| Expert intermediate dim | 512 |
| Hidden dim | 2048 |
| Attention | hybrid — Gated DeltaNet alternating with Gated Attention (16 Q-heads / 2 KV-heads, 256 head dim) |
| Native context | 262,144 tokens |
| Licence | Apache-2.0 |

Where do the weights actually sit? Per layer the MoE block holds
256 experts × 3 matrices (gate/up/down) × 2048 × 512 ≈ **805 M parameters**.
Across 40 layers that is **~32 B of the 35 B total — roughly 92 % of the
model is expert weights.**

Those 92 % are also the *coldest* tensors in the model: only 9 of 256 experts
fire per token, so any given expert matrix is read a fraction of the time.
The remaining 8 % — attention, DeltaNet, embeddings, the router — is touched
on **every** token.

That asymmetry is the whole trick:

- **Dense path → VRAM.** Every token, every layer. Latency-critical.
- **Expert path → system RAM.** Sparse, huge, streamed over PCIe on demand.

llama.cpp exposes the split directly:

| Flag | Meaning |
|---|---|
| `--cpu-moe` | keep **all** MoE expert weights in CPU RAM |
| `--n-cpu-moe N` | keep the MoE weights of the **first N layers** in CPU RAM |

On this 40-layer model, `--n-cpu-moe 40` is equivalent to `--cpu-moe`.
Anything lower pulls layers back onto the GPU — faster, but each layer costs
VRAM.

`--n-gpu-layers 99` (our `LLAMA_NGL` default) and `--n-cpu-moe` compose
correctly and are not in conflict: `-ngl` offloads every layer, then
`--n-cpu-moe` pulls the expert tensors of the first N back out.

> `--n-cpu-moe` supersedes hand-rolled
> `-ot 'blk\.[0-9]+\.ffn_.*_exps\.=CPU'` regexes. The `-ot` route still
> works — it is what `--n-cpu-moe` compiles down to — but the regex is
> architecture-specific and silently matches nothing when tensor names change
> between model families.

---

## Running Qwen3.6-35B-A3B

Quantizations are published at
[`bartowski/Qwen_Qwen3.6-35B-A3B-GGUF`](https://huggingface.co/bartowski/Qwen_Qwen3.6-35B-A3B-GGUF):

| Quant | Size | Notes |
|---|---|---|
| `IQ4_XS` | 19.7 GB | smaller than Q4_K_M at similar quality |
| **`Q4_K_M`** | **22.3 GB** | **the balance point** |
| `Q5_K_M` | 25.9 GB | |
| `Q6_K` | 31.0 GB | near-lossless |
| `Q8_0` | 37.8 GB | split across parts |

Budget before you start: the experts alone are ~19 GB, so you need **≥ 24 GB
of free system RAM**, plus ~23 GB of disk for the download.

In `.env`:

```ini
LLAMA_PORT=8089

# 40-layer MoE. Start with ALL experts in RAM, then tune downward.
LLAMA_HF_MODEL=bartowski/Qwen_Qwen3.6-35B-A3B-GGUF:Q4_K_M
LLAMA_EXTRA_ARGS=--n-cpu-moe 40 --jinja --reasoning-format deepseek --alias qwen3.6-35b-a3b

LLAMA_CTX=32768
LLAMA_NGL=99

# One slot. Expert matmuls run on the CPU; concurrent slots contend for the
# same cores and both get slower.
LLAMA_PARALLEL=1

LLAMA_API_KEY=parrot-local

# The first -hf run downloads ~22 GB; /health is 503 the whole time.
LLAMA_HEALTH_START=30m
```

Then, **with `--env-file`**:

```bash
docker compose --env-file .env -f docker-compose.llama.yml up -d
docker compose --env-file .env -f docker-compose.llama.yml logs -f
```

The first start downloads ~22 GB, and loading it off a cold page cache takes
minutes more.

Three flags in `LLAMA_EXTRA_ARGS` earn their place:

- `--jinja` selects the model's own chat template, which carries its thinking
  mode. Without it you get a generic template and degraded output.
- `--reasoning-format deepseek` moves thoughts into
  `message.reasoning_content` instead of leaving raw `<think>` tags inside
  `content`.
- `--alias qwen3.6-35b-a3b` sets the name served by `/v1/models`. Without it
  the server answers to a path-derived name that is awkward to configure
  against — see [Wiring](#wiring-it-into-ai-parrot).

### Sampling parameters

Qwen recommends different settings per mode. These are request-level — set
them in the client, not the server:

| Mode | temperature | top_p | top_k | presence_penalty |
|---|---|---|---|---|
| Thinking (general) | 1.0 | 0.95 | 20 | 1.5 |
| Coding | 0.6 | 0.95 | 20 | 0.0 |
| Instruct / non-thinking | 0.7 | 0.80 | 20 | 1.5 |

Thinking mode is on by default. To disable it per request, pass
`chat_template_kwargs: {"enable_thinking": false}`.

---

## Tuning `--n-cpu-moe`

> **Start at 40.** `.env.example` originally suggested `--n-cpu-moe 12`
> ("start high, e.g. 16, and come down") — a sizing sketch written before the
> model was available, and too low for the real architecture. Qwen3.6-35B-A3B
> has **40** layers, so `--n-cpu-moe 12` leaves 28 layers of experts (~13 GB)
> on the GPU and OOMs a 16 GB card once the KV cache and dense path are
> added. The recipe in `.env.example` now starts at 40 — every expert in RAM
> — and walks down.

The arithmetic, at Q4_K_M (~4.8 bits/weight):

```
expert weights per layer ≈ 805 M params × 0.6 bytes ≈ 0.48 GB
```

So each layer you pull back from RAM to GPU costs roughly **0.5 GB of VRAM**.

Worked example — 16 GB card (Quadro RTX 5000), 32 K context:

| Consumer | Estimate |
|---|---|
| Non-expert weights (attention, DeltaNet, embeddings, router) | ~3.0 GB |
| KV cache @ 32 K | ~0.5–1.0 GB |
| Compute / CUDA graph buffers | ~1.0 GB |
| Driver + desktop overhead | ~1.0 GB |
| **Free for expert layers** | **~9.5 GB → ~19 layers** |

That lands near `--n-cpu-moe 21` (40 − 19 on GPU). Treat it as a starting
hypothesis, not a fact — the exact split depends on quant, context and driver.

**The procedure — measure, don't guess:**

1. Start at `--n-cpu-moe 40`. Confirm the server answers on `/health`.
2. Read the real numbers out of the startup log rather than trusting the
   table above:
   ```bash
   docker compose --env-file .env -f docker-compose.llama.yml logs llama-server \
     | grep -Ei 'buffer size|n_ctx|offloaded|CUDA0'
   ```
   The `CUDA0 model buffer size` and `KV buffer size` lines are ground truth
   for what is actually resident.
3. Benchmark — `timings.predicted_per_second` is your tokens/sec:
   ```bash
   curl -s http://localhost:8089/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"qwen3.6-35b-a3b","messages":[{"role":"user","content":"Write a haiku."}],"max_tokens":256}' \
     | jq '.usage, .timings'
   ```
4. Lower `--n-cpu-moe` by 4, `up -d` again, repeat. Keep going until CUDA
   OOMs at load, then back off by 2–4 and stay there.
5. Leave real headroom. A split that fits at 32 K will OOM at 128 K — the KV
   cache grows with `--ctx-size`, and it grows *after* the weights are placed.

Other levers, roughly in order of payoff:

- **CPU threads.** Expert matmuls execute on the CPU, so thread count is a
  first-order knob. The compose file does not set `--threads`; add
  `--threads <physical cores>` to `LLAMA_EXTRA_ARGS`. Use physical cores —
  hyperthreads usually cost more than they return.
- **KV cache dtype.** Adding `--cache-type-k q8_0 --cache-type-v q8_0`
  roughly halves cache VRAM against `f16` for negligible quality loss, which
  converts directly into more expert layers on the GPU.
- **`LLAMA_CTX`.** Note it is the *total* context split across `--parallel`
  slots — `LLAMA_CTX=8192` with `LLAMA_PARALLEL=2` gives each slot only 4096
  tokens. Ask for the context you actually use, and keep `--parallel 1` for
  this model.
- **Quant.** `IQ4_XS` (19.7 GB) frees ~2.5 GB of RAM against `Q4_K_M` at
  comparable quality.

---

## Wiring it into AI-Parrot

`llama-server` speaks the OpenAI wire protocol at `/v1`, so `LocalLLMClient`
drives it with no adapter. In `env/.env`:

```ini
[localllm]
LOCAL_LLM_BASE_URL=http://localhost:8089/v1
LOCAL_LLM_MODEL=qwen3.6-35b-a3b
LOCAL_LLM_API_KEY=parrot-local
LOCAL_LLM_TIMEOUT=300
```

Four things to get right:

- **Port 8089**, not the llama.cpp default 8080.
- **Keep the `/v1` suffix** — the client passes the base URL to the OpenAI SDK
  verbatim.
- **`LOCAL_LLM_MODEL` must match the server's `--alias`.** Confirm with
  `GET /v1/models` before assuming.
- **Raise `LOCAL_LLM_TIMEOUT`.** The client default is 120 s; with experts
  streaming from RAM, a long thinking-mode generation can exceed it.

```python
from parrot.clients.localllm import LocalLLMClient

client = LocalLLMClient(
    base_url="http://localhost:8089/v1",
    model="qwen3.6-35b-a3b",
    api_key="parrot-local",
)

# AbstractClient initializes its per-loop SDK client in __aenter__ —
# ask()/invoke() do not work outside the context manager.
async with client:
    response = await client.ask(
        "Summarise the CPU-MoE offload strategy in two sentences.",
        temperature=0.7,
        top_p=0.8,
        max_tokens=512,
    )
    print(response.output)
```

Or through `LLMFactory`, using the registered `localllm` provider key:

```python
from parrot.clients.factory import LLMFactory

client = LLMFactory.create(
    llm="localllm:qwen3.6-35b-a3b",
    model_args={"temperature": 0.7, "top_p": 0.8},
)
async with client:
    response = await client.ask("ping", max_tokens=64)
```

Anywhere a bot or agent accepts an `llm=` string,
`"localllm:qwen3.6-35b-a3b"` works the same way.

`LocalLLMModel` has no `QWEN3_6` member — the enum is a convenience list, not
a constraint. Pass the alias as a plain string, or use `LocalLLMModel.CUSTOM`
where an enum is structurally required.

**Structured output.** llama-server enforces `response_format`
`json_schema` by compiling the schema to a GBNF grammar and constraining
decoding with it. Unlike a cloud provider's best-effort JSON mode, malformed
output is not merely unlikely — it is unrepresentable. This makes the local
stack a good target for `StructuredOutputConfig` work.

---

## Operational notes

### The `env_file` interpolation trap

`env_file:` injects variables **into the container**. It does **not** feed
`${...}` interpolation in the compose file itself — Compose resolves those
only from the shell environment, a `.env` at the *project root*, or an
explicit `--env-file`.

Every knob in `.env` — `LLAMA_PORT`, `LLAMA_HF_MODEL`,
`LLAMA_CTX`, `LLAMA_NGL`, `LLAMA_PARALLEL`, `LLAMA_EXTRA_ARGS`,
`LLAMA_HEALTH_START` — is consumed by interpolation. So without
`--env-file .env`, editing that file does **nothing**: the stack
silently starts with the built-in defaults (the 4 B model, 8192 context,
`--parallel 2`, no extra args). No warning, no error — it just serves the
wrong model.

Always pass it, and confirm before starting:

```bash
docker compose --env-file .env -f docker-compose.llama.yml config
```

Read back the resolved `command:` list. If your `--n-cpu-moe` is not in it,
the flag never reached the server.

### Healthcheck timing

`/health` returns **503** for the entire model load, so the healthcheck's
start period has to cover it. The Dockerfile now bakes
`--start-period=900s --retries=5` (was 120 s, which was ample for the 2.5 GB
default model and far too short for a 22 GB MoE — the container reported
`unhealthy` while loading perfectly well).

15 minutes covers a large MoE loading from disk cache. The **first** run with
`-hf` also downloads ~22 GB, which can exceed it; raise
`LLAMA_HEALTH_START=30m` in `.env` for that run. The compose overrides the
baked value, so this needs no rebuild.

Because `restart: "no"`, an `unhealthy` verdict kills nothing and the server
recovers on its own — but do not wire `depends_on: service_healthy` against
this service while serving the big model. Poll instead:

```bash
until curl -fsS http://localhost:8089/health >/dev/null 2>&1; do sleep 5; done
echo "ready"
```

**One GPU.** The compose reserves `count: 1`. On a multi-GPU host, raise it
and add `--split-mode` / `--tensor-split` via `LLAMA_EXTRA_ARGS`.

**`down` releases the VRAM; `down -v` also deletes the model cache.** The
`llama-models` volume holds the ~22 GB download. Do not reach for `-v` out of
habit.

**Version floor.** Qwen3.6's hybrid Gated DeltaNet layers need recent
llama.cpp operators. Since the Dockerfile tracks the floating
`:server-cuda` tag, `docker compose build --pull` fixes an
`unknown model architecture` failure. The same floating tag means an upstream
rebuild can change CUDA/driver expectations under you — once a build works,
pinning it by digest is the conservative move.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unknown model architecture` at load | Image predates Gated DeltaNet support | `docker compose --env-file .env -f docker-compose.llama.yml build --pull` |
| `CUDA out of memory` during load | `--n-cpu-moe` too low | Raise it toward 40 |
| Loads fine, OOMs on a long request | KV cache growth at high `LLAMA_CTX` | Lower `LLAMA_CTX`, add `--cache-type-k q8_0 --cache-type-v q8_0`, or raise `--n-cpu-moe` |
| Container `unhealthy` but serving fine | Load exceeds the start period | Raise `LLAMA_HEALTH_START` (30m for a first `-hf` download) |
| Edits to `.env` have no effect | Missing `--env-file` — `env_file:` does not drive interpolation | Pass `--env-file .env`; verify with `config` |
| Serving the 4 B default when you configured the 35 B | Same as above | Same as above |
| Multi-second stalls mid-generation | Experts being paged out of RAM | Check free RAM; add `--load-mode mmap+mlock` to `LLAMA_EXTRA_ARGS` (needs `ulimits: memlock: -1` in the compose) |
| Very low tok/s, GPU near idle | Expected — experts run on CPU | Add `--threads <physical cores>`; lower `--n-cpu-moe` to move layers to GPU |
| `401` from the API | Bearer token mismatch | `LOCAL_LLM_API_KEY` must equal `LLAMA_API_KEY` |
| `model not found` | Alias mismatch | `LOCAL_LLM_MODEL` must equal `--alias`; verify with `GET /v1/models` |
| `<think>` tags leaking into `content` | Reasoning not extracted | Ensure `--jinja` **and** `--reasoning-format deepseek` are both in `LLAMA_EXTRA_ARGS` |
| Server ignores `LLAMA_HF_MODEL` when set empty | `-hf` is hard-coded in `command:` | To serve a local GGUF, override `command:` or pass `-m /models/<file>.gguf` and edit the compose |
| Connection refused on 8080 | Wrong port | The host port is **8089** |
| No GPU in the container | `nvidia-container-toolkit` not wired in | `docker run --rm --gpus all ghcr.io/ggml-org/llama.cpp:server-cuda --version` to isolate |

Useful endpoints while debugging: `GET /health` (readiness), `GET /props`
(effective config), `GET /slots` (per-slot state and timings).

---

## References

- [Qwen3.6-35B-A3B model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [GGUF quantizations (bartowski)](https://huggingface.co/bartowski/Qwen_Qwen3.6-35B-A3B-GGUF)
- [llama.cpp Docker documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)
- [llama-server README — full flag and env-var reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [`LocalLLMClient` spec](../sdd/specs/localllm-client.spec.md)
