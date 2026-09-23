# Planogram slot identification with Amazon Nova 2 Lite

Feeds real Stage-1 OpenCV detection boxes to Amazon Nova 2 Lite and asks, per box,
whether a product is present and which brand/product it is. Output is flat
`{bbox, brand, product, occupancy}` JSON in source-image pixels, plus an annotated
image.

This is Stage-2 **identification** of the planogram cycle
(`perceive → identify → compare`) running on a different provider — not a new
pipeline. It reuses the pipeline's Set-of-Marks rendering, response cache, repair
retry and id reconciliation unchanged.

This example exists because no parrot client can send Nova an image today —
`BedrockConverseBase` silently drops image attachments. The example works around
that with a local Converse transport shim, producing the empirical evidence that
decides whether to add real image support to the Bedrock client.

## What stays local

Photos, `results/` and the vision cache are git-ignored and stay local — this
repository is public. Only the `.py` files and this README are tracked, via the
negation rules in `.gitignore`.

## Prerequisites

> **Nova 2 Lite has no in-region access in any AWS region.** A geo inference
> profile prefix (`us.` / `eu.` / `jp.` / `global.`) is mandatory. The default
> model id is `us.amazon.nova-2-lite-v1:0`; a bare `amazon.nova-2-lite-v1:0`
> fails with an access error.

1. **Bedrock model access**: Grant access to Nova 2 Lite in the AWS console
   (Bedrock → Model access). The reference runs use `us-east-1`.

2. **IAM permission**: The caller needs `bedrock:InvokeModel` on the inference
   profile ARN (e.g., `arn:aws:bedrock:us-east-1:<account>:inference-profile/us.amazon.nova-2-lite-v1:0`).

3. **Credentials**: Resolved through `parrot.conf`'s `AWS_CREDENTIALS` profile
   chain, not plain environment variables. Select a profile with `--aws-id`
   (falls back to `'default'` then to the SDK's standard env-var chain).
   Profile keys: `aws_key`, `aws_secret`, `region_name`.

## Install

```bash
source .venv/bin/activate
```

The packages needed are `ai-parrot`, `ai-parrot-client-amazon`,
`ai-parrot-pipelines`, `opencv-python`, `numpy`. `aioboto3` is already a
declared dependency of `ai-parrot-client-amazon`; there is nothing extra to
install.

## Usage

```bash
source .venv/bin/activate
python examples/planogram/aws/nova2.py \
    --image examples/planogram/images/shelf_01.jpg \
    --planogram examples/planogram/planogram_page1.json \
    --output examples/planogram/results/nova_run1
```

### Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--image` | Yes | — | Path to the store photo (JPEG/PNG). |
| `--boxes` | No | — | JSON file with pre-computed perception results (bypasses Stage-1). |
| `--planogram` | Yes | — | Planogram JSON with product/brand vocabulary for closed-set prompting. |
| `--output` | Yes | — | Output directory for `detections.json`, `annotated.jpg` and `run.json`. |
| `--model` | No | `nova-2-lite` | Model alias (resolves to `us.amazon.nova-2-lite-v1:0`). |
| `--region` | No | `us-east-1` | AWS region for the Bedrock call. |
| `--aws-id` | No | `default` | `AWS_CREDENTIALS` profile name in `parrot.conf`. |
| `--concurrency` | No | `4` | Concurrent strip calls (1–16). |
| `--no-marks` | No | (off) | Disable Set-of-Marks outlines on strips. |
| `--cache-dir` | No | — | Directory for the vision response cache (makes re-runs free). |

## Outputs

Three files are written to `--output`:

- `detections.json`: Flat array of detections, one per target. Each row has
  `bbox` in **source-image pixels** `[x1, y1, x2, y2]`, `occupancy`
  (`occupied`/`empty`/`unknown`), `brand`, `product`, `confidence`, `evidence`,
  `source` (`cv` or `llm_added`), `inferred` and `uncertain` flags.

- `annotated.jpg`: The source image with boxes drawn and labelled
  `brand / product`. Empty slots are shown in a distinct colour.

- `run.json`: Metadata including the resolved model id, region, prompt version,
  `strips`, `calls`, `cache_hits`, `incomplete_retries`, `image_bytes_sent`,
  token counts and wall time.

### Exit codes

- `0`: Success.
- `1`: Invalid input (missing required file, bad `--boxes`, zero shapes
  perceived, malformed planogram).
- `2`: Completed with errors (some strips failed; check `run.json` for details).

## Cost and repeat runs

One strip can cost up to **three** provider calls: the initial request, a schema
repair retry (if the answer is malformed), and a missing-id repair prompt (if the
answer omits requested ids). Read `run.json`'s `calls`, not `strips`, when
reasoning about cost.

Use `--cache-dir` to make a re-run free and byte-identical. The cache key
includes the prompt version, model id and image content hash.

## Known limitations

1. **Prototype transport**: The shim is throwaway code. Parrot's Bedrock client
   still drops image attachments, and this example works around that with a
   local Converse call. When `BedrockConverseBase` gains real image support, this
   shim is superseded.

2. **Closed-set prompt is example-local**: The prompt builder lives in
   `prompt.py` and is not part of the pipeline. The pipeline's
   `build_identify_prompt` remains contractually open-set.

3. **No automated test of the live Converse round-trip**: The request is guarded
   at runtime instead — `ask_to_image` refuses to send a call with no image
   block, and `run.json` reports `image_bytes_sent` for audit. There is no
   fake-`aioboto3` test.

4. **Nova 2 Lite has no in-region access**: A geo-prefix is mandatory. The
   default `region_prefix="us"` is correct for `us-east-1`; other regions need
   the matching prefix (`eu.`, `jp.`, `global.`).
