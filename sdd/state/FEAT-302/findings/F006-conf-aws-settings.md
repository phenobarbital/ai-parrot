---
id: F006
slug: conf-aws-settings
query: grep AWS in conf.py
type: grep
---

## Finding: AWS Configuration in parrot.conf

**Path**: `packages/ai-parrot/src/parrot/conf.py` (lines 464-480)

Existing AWS config variables:
- `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_SESSION_TOKEN`
- `ANTHROPIC_AWS_WORKSPACE_ID`
- `BEDROCK_AWS_REGION`, `AWS_REGION_NAME`
- `BACKEND_AWS_ACCESS_KEY`, `BACKEND_AWS_SECRET_KEY`

**Reusable for new client**: yes. The new `BedrockClient` can read these same config variables
to construct `aioboto3.Session(region_name=BEDROCK_AWS_REGION, ...)`.

May need additions: `BEDROCK_GUARDRAIL_ID`, `BEDROCK_GUARDRAIL_VERSION` for guardrail support.
