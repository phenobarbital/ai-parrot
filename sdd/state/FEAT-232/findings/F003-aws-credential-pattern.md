# F003 — Existing AWS credential resolution pattern (parrot.conf → env)

**Query**: existing AWS credential reading / region config in the repo.

## Summary
The repo already has a canonical "parrot.conf first, env fallback, SDK chain
last" AWS credential pattern. `parrot/conf.py` exports `AWS_ACCESS_KEY`,
`AWS_SECRET_KEY`, `AWS_REGION_NAME`, `AWS_CREDENTIALS` (navconfig-backed).
`AWSInterface` consumes them and deliberately lets aioboto3 fall through to the
standard boto3 chain (`~/.aws/credentials`, `AWS_ACCESS_KEY_ID`, IMDS) when no
explicit profile is requested — exactly the behavior the proposal wants from
`AnthropicBedrock`.

## Citations
- `packages/ai-parrot/src/parrot/interfaces/aws.py:10-14` — imports `AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION_NAME, AWS_CREDENTIALS` from `..conf`
- `packages/ai-parrot/src/parrot/interfaces/aws.py:51-83` — credential resolution: named-profile lookup, `default` fallback to env-backed constants, `region_name` override, optional `aws_session_token`
- `packages/ai-parrot/src/parrot/interfaces/aws.py:69-77` — documents the deliberate fall-through to boto3's own chain
- `packages/ai-parrot/src/parrot/storage/backends/__init__.py:42-89` — second precedent: `BACKEND_AWS_ACCESS_KEY`/`BACKEND_AWS_SECRET_KEY` namespaced env vars

## Relevance
The Bedrock client should read `aws_access_key`/`aws_secret_key`/`aws_region`
from these `parrot.conf` constants first, fall back to env, and pass `None` to
the SDK to let it resolve via the standard AWS chain — mirroring `AWSInterface`.
The AWS-workspace client reads `ANTHROPIC_API_KEY` + `ANTHROPIC_AWS_WORKSPACE_ID`
via `config.get(...)` (navconfig), same as the existing `AnthropicClient.__init__`.
