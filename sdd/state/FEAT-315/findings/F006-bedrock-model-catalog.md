# F006 — bedrock_models.py: Nova aliases exist; coverage gaps for Premier/Canvas/Reel

**Query**: Q018/Q012 · **Type**: read · `packages/ai-parrot/src/parrot/models/bedrock_models.py` (144 lines)

`PUBLIC_TO_BEDROCK` static map translates public IDs → Bedrock IDs, with
pass-through for already-Bedrock-shaped IDs, optional `region_prefix`
("us"/"eu"/"apac"), and warn+passthrough for unknowns.

Current Nova entries (lines 67-75, extended by wip commit 3672eb2f4):
- `nova-sonic` → `amazon.nova-sonic-v1:0`
- `nova-pro` → `amazon.nova-pro-v1:0`
- `nova-lite` → `amazon.nova-lite-v1:0`
- `nova-micro` → `amazon.nova-micro-v1:0`
- `nova-2-sonic` → `amazon.nova-2-sonic-v1:0`
- `nova-2-lite` → `amazon.nova-2-lite-v1:0`

**Gaps for FEAT-315**: no `nova-premier` (us.amazon.nova-premier-v1:0 —
Premier is inference-profile-only), no `nova-canvas`
(amazon.nova-canvas-v1:0), no `nova-reel` (amazon.nova-reel-v1:0 / v1:1),
no `nova-2-pro` / `nova-2-micro` / `nova-2-premier` if applicable.

## Citations
- packages/ai-parrot/src/parrot/models/bedrock_models.py:38-76,100-144
- git 3672eb2f4
