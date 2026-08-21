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

---

## Client Backend Split

AI-Parrot uses **two different client backends** for Bedrock models:

### `bedrock-converse` — Native Converse API (Claude models)

`BedrockConverseClient` calls the AWS Bedrock native Converse API via boto3
with SigV4 authentication. This is the recommended path for all Anthropic
Claude models on Bedrock:

- Uses the `bedrock-converse:<model-id>` LLM string.
- Authenticates with standard AWS credentials (access key + secret, or IAM
  role / instance profile / ECS task role).
- Handles region prefixing automatically via `REQUIRES_REGION_PREFIX`.

### `bedrock-mantle` — OpenAI-Compatible Endpoint (third-party models)

`BedrockMantleClient` calls the Bedrock Mantle endpoint
(`/v1/chat/completions`), which is an OpenAI-compatible API surface for
third-party models (Deepseek, MiniMax, etc.) hosted on Bedrock:

- Uses the `bedrock-mantle:<vendor>.<model-id>` LLM string.
- Vendor-namespaced model IDs (e.g. `minimax.minimax-m2.5`) pass through
  automatically.
- Requires the `AWS_BEDROCK_MANTLE_URL` environment variable pointing to
  the region-specific Mantle endpoint.

> **Why not use `bedrock-mantle` for Claude?**
> Bedrock Mantle's `/v1` path is OpenAI-compatible and does NOT work for
> Claude, whose Mantle endpoint uses `/anthropic/v1/messages` — an
> incompatible message shape. Always use `bedrock-converse` or `bedrock`
> for Claude models.

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

### 4. Bedrock Mantle URL (Deepseek / MiniMax only)

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
    llm="bedrock-converse:anthropic.claude-haiku-4-5",
    # Alternative (Anthropic native SDK with Bedrock backend):
    # llm="bedrock:anthropic.claude-haiku-4-5",
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

### Tool calls return no result

Some models may not support client-side tool calling for all tool schemas.
If a tool call silently fails, the agent falls back to a text-only response.
Check the model's Bedrock documentation for tool calling support.

---

## Related Examples

- `examples/clients/aws.py` — raw client usage (text, streaming, voice)
- `examples/test_agent.py` — reference CLI agent pattern with BasicAgent
