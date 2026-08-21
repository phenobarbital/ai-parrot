# AWS Bedrock Agent Examples

Interactive CLI agents demonstrating how to use AI-Parrot's `BasicAgent`
with AWS Bedrock-hosted models. Each script shows tool calling
(PythonREPL, calculator, datetime, system info) with a model available on
Bedrock.

---

## Scripts

| Script | Model | Client Backend |
|---|---|---|
| `agent_claude_opus5.py` | Claude Opus 5 | `bedrock-converse` |
| `agent_claude_fable5.py` | Claude Fable 5 | `bedrock-converse` |
| `agent_claude_haiku45.py` | Claude Haiku 4.5 | `bedrock-converse` |
| `agent_deepseek_v32.py` | Deepseek V3.2 | `bedrock-mantle` |
| `agent_minimax_m25.py` | MiniMax M2.5 | `bedrock-mantle` |
| `agent_qwen3_coder.py` | Qwen3 Coder 480B A35B | `bedrock-mantle` |
| `agent_glm5.py` | Z.AI GLM 5 | `bedrock-mantle` |
| `agent_kimi_k25.py` | Kimi K2.5 | `bedrock-mantle` |
| `agent_nova2_lite.py` | Amazon Nova 2 Lite | `nova` |
| `agent_nova_pro.py` | Amazon Nova Pro | `nova` |
| `agent_nova_micro.py` | Amazon Nova Micro | `nova` |
| `nova_canvas_image.py` | Amazon Nova Canvas (image) | `nova` |
| `nova_reel_video.py` | Amazon Nova Reel (video) | `nova` |

The last two are **not agents** — Canvas and Reel take no messages and
support no tools, so they are one-shot CLIs over
`NovaClient.generate_image()` / `.video_generation()`.

---

## Client Backend Split

AI-Parrot uses **two different client backends** for Bedrock models:

### `bedrock-converse` — Native Converse API (Claude models)

`BedrockConverseClient` calls the AWS Bedrock native Converse API via boto3
with SigV4 authentication. This is the recommended path for all Anthropic
Claude models on Bedrock:

- Uses the `bedrock-converse:<model-id>` LLM string, where `<model-id>` is the
  **public** Anthropic ID (`claude-haiku-4-5`, `claude-opus-5`,
  `claude-fable-5`) — `parrot.models.bedrock_models.translate()` resolves it to
  the full Bedrock inference-profile ID
  (`us.anthropic.claude-haiku-4-5-20251001-v1:0`). Passing a fully-qualified
  Bedrock ID or an ARN also works.
- Authenticates with standard AWS credentials (access key + secret, or IAM
  role / instance profile / ECS task role).
- Handles region prefixing automatically via `REQUIRES_REGION_PREFIX`.

### `bedrock-mantle` — OpenAI-Compatible Endpoint (third-party models)

`BedrockMantleClient` calls the Bedrock Mantle endpoint
(`/v1/chat/completions`), which is an OpenAI-compatible API surface for
third-party models (Deepseek, MiniMax, etc.) hosted on Bedrock:

- Uses the `bedrock-mantle:<vendor>.<model-id>` LLM string.
- Vendor-namespaced model IDs (e.g. `minimax.minimax-m2.5`, `zai.glm-5`,
  `moonshotai.kimi-k2.5`, `qwen.qwen3-coder-480b-a35b-instruct`) pass through
  automatically.
- **Not every third-party model is on Mantle.** Meta's Llama 4 Maverick, for
  instance, is served only on the `bedrock-runtime` endpoint, so it needs
  `bedrock-converse` — check the "APIs supported" / "Endpoints supported"
  table on the model's Bedrock model card before picking a backend. Some
  models also use a *different id per endpoint*: Qwen3 Coder is
  `qwen.qwen3-coder-480b-a35b-instruct` on Mantle but
  `qwen.qwen3-coder-480b-a35b-v1:0` on `bedrock-runtime`.
- Requires the `AWS_BEDROCK_MANTLE_URL` environment variable pointing to
  the region-specific Mantle endpoint.

> **Why not use `bedrock-mantle` for Claude?**
> Bedrock Mantle's `/v1` path is OpenAI-compatible and does NOT work for
> Claude, whose Mantle endpoint uses `/anthropic/v1/messages` — an
> incompatible message shape. Always use `bedrock-converse` or `bedrock`
> for Claude models.

### `nova` — Amazon Nova models (all modalities)

`NovaClient` composes the Converse text engine with the Nova voice and
generation mixins, so one client covers every Nova modality:

- **Text** (Nova 2 Lite, Pro, Micro, Premier): `ask()`/`ask_stream()`/
  `invoke()` — inherited from `BedrockConverseBase`, with client-side tool
  calling. Use the `nova:<model>` LLM string.
- **Image** (Nova Canvas): `generate_image()`.
- **Video** (Nova Reel): `video_generation()` — async job + S3 output.
- **Voice** (Nova Sonic / Nova 2 Sonic): `stream_voice()`, not covered by
  these samples (see `examples/clients/aws.py`).

Unlike `bedrock-converse`, this client defaults `region_prefix="us"`,
because Nova 2 Lite and Nova Premier have **no in-region access at all** and
only resolve through a geo (`us.`/`eu.`/`jp.`) or `global.` inference
profile. Canvas and Reel are the opposite — in-region only, never prefixed —
which `NovaGeneration._translate_in_region_model()` handles separately from
the text path.

### `bedrock` — Anthropic SDK with Bedrock Backend (alternative for Claude)

The `AnthropicClient` with `PROVIDER_BACKEND="bedrock"` is an alternative
for Claude models that routes calls through the Anthropic SDK's Bedrock
integration. Uncomment the `# llm="bedrock:..."` line in any Claude script
to switch.

---

## Prerequisites

### 1. Install AI-Parrot

```bash
pip install ai-parrot
# or for development:
git clone <repo>
cd ai-parrot
uv pip install -e packages/ai-parrot
```

### 2. AWS Credentials

All Bedrock clients use standard AWS credentials. Configure them via
environment variables, `~/.aws/credentials`, or an IAM role:

```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1
```

Or use an IAM role attached to your EC2 instance, ECS task, or Lambda
function — no environment variables needed in that case.

### 3. Enable Model Access on Bedrock

Before using a model, you must enable access in the AWS console:

1. Open the [AWS Bedrock console](https://console.aws.amazon.com/bedrock/).
2. Navigate to **Model access** in the left sidebar.
3. Click **Manage model access**.
4. Enable the models you want to use.
5. Wait for access to be granted (usually instant, but can take up to 24h).

| Model | Access Type |
|---|---|
| Claude Opus 5 | Anthropic — requires acceptance of Anthropic EULA |
| Claude Fable 5 | Anthropic — requires acceptance of Anthropic EULA |
| Claude Haiku 4.5 | Anthropic — requires acceptance of Anthropic EULA |
| Deepseek V3.2 | Deepseek — requires acceptance of Deepseek EULA |
| MiniMax M2.5 | MiniMax — requires acceptance of MiniMax EULA |
| Qwen3 Coder 480B A35B | Qwen — requires acceptance of Qwen EULA |
| Z.AI GLM 5 | Z.AI — requires acceptance of Z.AI EULA |
| Kimi K2.5 | Moonshot AI — requires acceptance of Moonshot AI EULA |
| Nova 2 Lite / Pro / Micro | Amazon — enabled by default in most accounts |
| Nova Canvas / Nova Reel | Amazon — **Legacy, EOL 2026-09-30**; blocked for accounts that have not called them in the last 30 days (see Troubleshooting) |

### 4. Bedrock Mantle URL (`bedrock-mantle` scripts only)

For `bedrock-mantle` scripts, set the Mantle endpoint URL:

```bash
export AWS_BEDROCK_MANTLE_URL=https://bedrock-mantle.us-east-1.amazonaws.com
```

Replace `us-east-1` with your target region.

---

## Environment Variables Reference

### `bedrock-converse` scripts (Claude models)

| Variable | Required | Description |
|---|---|---|
| `AWS_DEFAULT_REGION` | Yes | AWS region (e.g. `us-east-1`) |
| `AWS_ACCESS_KEY_ID` | If no IAM role | AWS access key ID |
| `AWS_SECRET_ACCESS_KEY` | If no IAM role | AWS secret access key |
| `AWS_SESSION_TOKEN` | If using STS | Temporary session token |

### `bedrock` alternative (Claude models, Anthropic SDK)

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `AWS_DEFAULT_REGION` | Yes | AWS region |
| `AWS_ACCESS_KEY_ID` | If no IAM role | AWS access key ID |
| `AWS_SECRET_ACCESS_KEY` | If no IAM role | AWS secret access key |

### `bedrock-mantle` scripts (Deepseek, MiniMax)

| Variable | Required | Description |
|---|---|---|
| `AWS_BEDROCK_MANTLE_URL` | Yes | Mantle endpoint URL |
| `AWS_DEFAULT_REGION` | Yes | AWS region |
| `AWS_ACCESS_KEY_ID` | If no IAM role | AWS access key ID |
| `AWS_SECRET_ACCESS_KEY` | If no IAM role | AWS secret access key |

---

## AWS Region Notes

Claude models on Bedrock require a **region prefix** in the model ID,
which AI-Parrot handles automatically via `REQUIRES_REGION_PREFIX`:

| Model | Region Prefix | Recommended Region |
|---|---|---|
| Claude Opus 5 | `us` | `us-east-1` or `us-west-2` |
| Claude Fable 5 | `global` | any supported region |
| Claude Haiku 4.5 | `us` | `us-east-1` or `us-west-2` |

Set `AWS_DEFAULT_REGION` to a region where your target model is available.

---

## Usage

Run any of the scripts from the repo root:

```bash
# Claude Opus 5 (bedrock-converse)
python examples/agents/aws/agent_claude_opus5.py

# Claude Fable 5 (bedrock-converse)
python examples/agents/aws/agent_claude_fable5.py

# Claude Haiku 4.5 (bedrock-converse) — fastest Claude model
python examples/agents/aws/agent_claude_haiku45.py

# Deepseek V3.2 (bedrock-mantle)
python examples/agents/aws/agent_deepseek_v32.py

# MiniMax M2.5 (bedrock-mantle)
python examples/agents/aws/agent_minimax_m25.py
```

Type your message at the `You >` prompt. Type `exit`, `quit`, or `bye` to
quit.

### Example Session

```
🤖 AWS Bedrock Agent — Claude Haiku 4.5 (bedrock-converse)
   Tools: python_repl, calculator, current_datetime, system_info
   Type 'exit', 'quit', or 'bye' to quit.

You > What is 2 ** 32?
Agent > 2 raised to the power of 32 is 4,294,967,296.

You > What time is it?
Agent > The current UTC time is 2026-08-21T14:32:01.234567+00:00.

You > exit
Goodbye!
```

---

## Tools Available in Every Script

| Tool | Description |
|---|---|
| `python_repl` | Execute arbitrary Python code in a sandboxed REPL |
| `calculator` | Safely evaluate math expressions |
| `current_datetime` | Get the current UTC date and time |
| `system_info` | Get Python version, platform, and working directory |

---

## Switching Client Backends (Claude Models)

Each Claude script includes a commented-out alternative using the
`bedrock` client (Anthropic SDK with Bedrock backend):

```python
agent = BasicAgent(
    name="ClaudeHaiku45Agent",
    llm="bedrock-converse:claude-haiku-4-5",
    # Alternative (Anthropic native SDK with Bedrock backend):
    # llm="bedrock:claude-haiku-4-5",
    ...
)
```

Uncomment the `# llm="bedrock:..."` line and comment out the primary
`llm=` line to switch backends. The `bedrock` backend requires
`ANTHROPIC_API_KEY` in addition to AWS credentials.

---

## Troubleshooting

### `❌ Failed to configure agent: ...`

- Check that your AWS credentials are correctly configured.
- Verify the model is enabled in the Bedrock console (Model access).
- Ensure `AWS_DEFAULT_REGION` matches a region where the model is available.
- For `bedrock-mantle` scripts, check that `AWS_BEDROCK_MANTLE_URL` is set.

### `botocore.exceptions.NoCredentialsError`

AWS credentials are not configured. Set `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`, or configure an IAM role.

### `botocore.exceptions.ClientError: AccessDeniedException`

Your AWS account does not have access to the model. Enable it in the
Bedrock console under **Model access**.

### `ValidationException: The provided model identifier is invalid`

The model ID never resolved to a real Bedrock inference profile. Prefer the
public ID (`bedrock-converse:claude-haiku-4-5`) and let
`parrot.models.bedrock_models.translate()` resolve it; a half-qualified ID such
as `anthropic.claude-haiku-4-5` is missing both the `-vN:0` version suffix and
the `us.` region prefix.

### `ResourceNotFoundException: Model use case details have not been submitted`

An account-level entitlement, not a code problem: submit the Anthropic use
case details form in the Bedrock console, then retry after ~15 minutes. Only
the Anthropic models are gated this way — the `bedrock-mantle` scripts
(Deepseek, MiniMax) are unaffected.

### `ValidationException: \`temperature\` is deprecated for this model`

Claude Opus 5 / Fable 5 / Sonnet 5 / Opus 4.8 / 4.7 dropped the sampling
parameters. `BedrockConverseBase._inference_config()` omits `temperature` for
those families (`NO_SAMPLING_MODEL_FAMILIES` in
`parrot/clients/bedrock.py`) — add a family there if AWS adds another model
that rejects it.

### `ValidationException: data retention mode 'default' is not available for this model`

Account-side, not a payload problem: Claude Fable 5 is not served under the
default/zero data-retention configuration, and the Converse API shape in the
pinned `botocore` (1.35.36) has no data-retention field to send. Configure the
required retention mode for the account in the Bedrock console, or use
`claude-opus-5` — which needs no such configuration.

### `ValidationException: Access to Meta Llama models is not allowed from unsupported countries, regions, or territories`

Meta's EULA geo-restricts Llama models by the *caller's* location, independent
of AWS model access and of the Bedrock region — which is why no Llama script
ships here, even though `parrot.models.bedrock_models` can resolve
`llama4-maverick-17b-instruct` to its mandatory `us.` inference profile.
Nothing in the request works around it: call from a supported location, or use
one of the other models.

### Model IDs differ between the two endpoints

A model can be listed on both endpoints under different IDs (Qwen3 Coder:
`qwen.qwen3-coder-480b-a35b-instruct` on Mantle,
`qwen.qwen3-coder-480b-a35b-v1:0` on `bedrock-runtime`). Sending the Mantle
ID to Converse — or the reverse — yields
`The provided model identifier is invalid`. The **Programmatic Access** table
on each Bedrock model card lists the ID per endpoint.

### `ResourceNotFoundException: This Model is marked by provider as Legacy and you have not been actively using the model in the last 30 days`

Bedrock gates Legacy models on recent usage: an account with no calls in the
last 30 days is refused even with model access granted. It affects Nova
Canvas and Nova Reel (both EOL 2026-09-30) and is account state, not a
payload problem — there is no request-side workaround.

### `AttributeError: 'BedrockRuntime' object has no attribute 'start_async_invoke'`

The installed `botocore` predates the `StartAsyncInvoke` operation (added
with Nova Reel, Dec 2024), so Nova Reel cannot be called at all until the
SDK is upgraded — `uv pip install -U boto3 botocore aioboto3`. Verify with:

```bash
python -c "import botocore, gzip, json, os;   d=json.load(gzip.open(os.path.join(os.path.dirname(botocore.__file__),   'data/bedrock-runtime/2023-09-30/service-2.json.gz')));   print(sorted(d['operations']))"
```

`StartAsyncInvoke` must appear in that list. This affects
`NovaGeneration.video_generation()` in the library, not just the sample.

### Tool calls return no result

Some models may not support client-side tool calling for all tool schemas.
If a tool call silently fails, the agent falls back to a text-only response.
Check the model's Bedrock documentation for tool calling support.

---

## Related Examples

- `examples/clients/aws.py` — raw client usage (text, streaming, voice)
- `examples/test_agent.py` — reference CLI agent pattern with BasicAgent
