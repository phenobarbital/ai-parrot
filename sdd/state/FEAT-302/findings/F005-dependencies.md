---
id: F005
slug: dependencies
query: grep aioboto3, boto3 in pyproject.toml
type: grep
---

## Finding: AWS Dependencies

**Path**: `packages/ai-parrot/pyproject.toml` (lines 348-353, 384)

Current `bedrock` extra: `anthropic[aiohttp,aws]>=0.109.0,<1.0.0` — pulls boto3 via anthropic SDK.

`aioboto3` is NOT a dependency anywhere in ai-parrot. The `db` extra includes `asyncdb[boto3]`
for DynamoDB but that's a different package.

`ai-parrot-tools` has `aws = ["boto3>=1.28"]` for AWS service toolkits.

**Action needed**: New extra group (e.g. `bedrock-native` or extend `bedrock`) adding:
- `aioboto3>=13.0` (for async Bedrock Runtime client)
- `types-aioboto3[bedrock-runtime]` (for type hints, dev only)

For Nova Sonic (experimental): separate extra gated to Python >= 3.12:
- `aws_sdk_bedrock_runtime==0.7.0` (pinned strictly)
