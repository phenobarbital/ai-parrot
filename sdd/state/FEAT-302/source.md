---
kind: file
jira_key: null
fetched_at: 2026-07-11
summary_oneline: Native Bedrock client (Converse API) + Nova 2 Sonic voice for ai-parrot
---

## Source

Uses the research in `sdd/proposals/compass_artifact_wf-766f01e9-ac55-5ac0-86a0-78dd7870fc59_text_markdown.md` to develop a new client for Amazon AWS Bedrock support including newer Sonic Nova 2.

### Research Document Key Points

- Use Converse API (`converse`/`converse_stream`) as primary route for Claude on Bedrock
- For async, use `aioboto3`/`aiobotocore` (wrapping boto3/botocore)
- Nova Sonic bidirectional HTTP/2 requires experimental SDK `aws_sdk_bedrock_runtime` (Pre-Alpha v0.7.0, Python >= 3.12)
- PII guardrails only apply to text; for Nova Sonic apply `ApplyGuardrail` on transcriptions
- Converse API has feature parity with Messages API in 2026 (tool use, extended thinking, prompt caching, structured output, guardrails)
- `invoke_model` fallback needed for models without ARN-versioned IDs (Opus 4.8, Fable 5)
