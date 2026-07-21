# F004 — BedrockConverseClient: text engine + aws_id credential pattern (with a latent bug)

**Query**: Q007 · **Type**: wiki_page + read · `packages/ai-parrot/src/parrot/clients/bedrock.py` (1,130 lines, FEAT-302)

- `class BedrockConverseClient(AbstractClient)` — native Bedrock **Converse API**
  via `aioboto3` (lazy import in `get_client()`); supports ANY Bedrock model
  family including Nova text models. Full `ask()` tool-use loop, `ask_stream()`,
  guardrails, prompt caching, structured output, `_invoke_native()` fallback.
- Thin SDK wrappers: `_sdk_create` (converse), `_sdk_stream` (converse_stream).
- Model translation via `parrot.models.bedrock_models.translate()` +
  `region_prefix` for cross-region inference profiles.
- **aws_id credential resolution** (added in wip commit 3672eb2f4, lines 109-120):
  `aws_id` kwarg → `AWS_CREDENTIALS.get(aws_id)` → reads
  `credentials.get("access_key") / ("secret_key") / ("session_token") / ("region")`.
- **⚠ Latent bug 1 — key mismatch**: `AWS_CREDENTIALS` profiles in `conf.py`
  use keys `aws_key` / `aws_secret` / `region_name` (F006), so the
  `access_key`/`secret_key`/`region` lookups always return `None`.
- **⚠ Latent bug 2 — unbound attributes**: when `aws_id` is given but NOT found
  in `AWS_CREDENTIALS`, the `if credentials :=` branch is skipped and
  `_aws_access_key`/`_aws_secret_key`/`_aws_session_token`/`_region` are never
  assigned → AttributeError at `get_client()` time.
- `parrot/interfaces/aws.py:46-56` already implements the canonical resolver:
  `AWS_CREDENTIALS.get(aws_id, {})` with fallback to the `'default'` profile —
  and uses the CORRECT keys.

## Citations
- packages/ai-parrot/src/parrot/clients/bedrock.py:62-140 (init, aws_id branch)
- packages/ai-parrot/src/parrot/interfaces/aws.py:14,46-56
- git 3672eb2f4 (wip: nova model)
