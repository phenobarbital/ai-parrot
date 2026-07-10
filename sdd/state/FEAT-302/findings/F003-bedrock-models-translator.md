---
id: F003
slug: bedrock-models-translator
query: Read bedrock_models.py
type: read
---

## Finding: Bedrock Model ID Translator

**Path**: `packages/ai-parrot/src/parrot/models/bedrock_models.py`

`PUBLIC_TO_BEDROCK` dict maps public IDs → Bedrock IDs (e.g. `claude-sonnet-4-6` → `anthropic.claude-sonnet-4-6-20260115-v1:0`).

`translate(public_id, region_prefix=None)`:
1. Pass-through if already Bedrock-shaped (contains `anthropic.`, starts with `arn:`, or has region prefix)
2. Map lookup from `PUBLIC_TO_BEDROCK`
3. Prepend region prefix if provided (e.g. `us.anthropic.claude-...`)
4. Unknown IDs returned unchanged with warning

Region prefixes: `us.`, `eu.`, `apac.`

**Reusable for new client**: yes, the translator is provider-agnostic and can be used by a native BedrockClient.
Needs extension: add Nova model IDs (`amazon.nova-sonic-v1:0`, `amazon.nova-2-sonic-v1:0`) and any
other non-Anthropic Bedrock models the new client will support.
