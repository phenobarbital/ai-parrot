# Planogram compliance check (label-anchored, autonomous)

This tool runs an 8-stage pipeline to check store photos against a planogram: detect price tags, build a grid of product slots, read slot contents with an LLM, verify against expectations, register slots to planogram facings, merge observations, score compliance, and write a report.

## What stays local
Photos, `planogram_page1.json`, PDFs, videos and every result directory are git-ignored on purpose (this repository is public). Only code, tests, this README and the synthetic `catalog.example.json` are tracked.

## Install
Activate the repo venv (`source .venv/bin/activate`) and ensure the following packages are installed: opencv-python, numpy, rapidocr + onnxruntime (optional — without it prices are read by the LLM only), rapidfuzz, pydantic, pillow, ai-parrot + ai-parrot-client-google (+ -local). Credentials are provided via environment variables only (e.g. GOOGLE_API_KEY).

## The catalog (required)
The catalog bridges planogram part numbers to consumer-facing package names. Use `--emit-catalog-template <path>` to generate a skeleton from the planogram, then fill in the descriptor fields. Each item has:
- `sku`: the part number from the planogram
- `brand`: the brand name
- `display_name`: what the package shows
- `family`: optional product family
- `xl`: whether this is an XL variant
- `colors`: list of color variants
- `pack`: number of units in the pack
- `identifiers`: alternative part numbers
- `aliases`: alternative display names
- `provenance`: optional source note

See `catalog.example.json` for a synthetic example. The resolver never merges XL, color or pack variants — each must have its own catalog entry.

## Usage
```bash
python examples/planogram/planogram_check.py --emit-catalog-template my_catalog.json
python examples/planogram/planogram_check.py --catalog my_catalog.json --output examples/planogram/results/run1
```

Options:
- `--images-dir <path>`: directory containing store photos (default: `examples/planogram/images`)
- `--images <file>...`: explicit list of photo files
- `--planogram <file>`: planogram JSON (default: `examples/planogram/planogram_page1.json`)
- `--catalog <file>`: catalog JSON (required)
- `--output <dir>`: new directory for results (required)
- `--llm <provider:model>`: LLM for identification (default: `google:gemini-3.8-flash`)
- `--ocr-llm <provider:model>`: LLM for price OCR fallback
- `--base-url <url>`: base URL for local OpenAI-compatible servers
- `--prices <file>`: optional JSON mapping SKUs to expected prices
- `--roi L T R B`: region of interest (0 <= L < R <= 1, 0 <= T < B <= 1)
- `--verify-pass` / `--no-verify-pass`: enable/disable closed-set verification (default: auto)
- `--no-marks`: disable Set-of-Marks outlines
- `--concurrency <n>`: concurrent LLM calls (1-16, default: 4)
- `--cache-dir <dir>`: cache directory (default: `examples/planogram/results/.plancheck_cache`)
- `--visit-id <id>`: visit identifier (default: `visit`)
- `--emit-catalog-template <path>`: write a catalog skeleton and exit

Exit codes: 0 (success), 1 (invalid input), 2 (completed with errors).

## Outputs
The `compliance.json` report contains:
- `run`: metadata (visit, planogram, LLM, errors)
- `images`: per-image info (tag rows, slots, registration)
- `slots`: per-slot observations
- `positions`: per-facing results
- `shelves`: per-shelf metrics
- `brands`: brand share analysis
- `compliance`: headline numbers
- `notes`: standing notes

Annotated images (`annotated_<image_id>.jpg`) show slot outlines color-coded by status. The `slots/` directory contains per-slot crops, and `tags/` contains tag crops. `run.snapshot.json` captures the full run parameters.

## Scoring semantics
Position statuses:
- `match`: correct product in the correct slot
- `misplaced`: correct product but wrong slot
- `variant_unresolved`: XL/color/pack variant unclear
- `mismatch`: wrong product
- `empty`: slot is empty
- `inferred_present`: product inferred from context
- `occupied_unassigned`: slot occupied but product unknown
- `conflict`: conflicting observations
- `not_assessed`: not evaluated
- `not_visible`: slot not visible

Strict credit: 1.0 for `match`, 0.0 otherwise. Lenient credit: 1.0 for `match`, 0.5 for `misplaced`/`variant_unresolved`/`inferred_present`, 0.0 otherwise. Default weights: misplaced=0.5, variant_unresolved=0.5, inferred_present=0.5, verified_by_expectation=1.0. Coverage is the fraction of expected facings observed. Occupancy is the fraction of slots occupied. Brand share is computed from facings and linear measurements. Reference confidence is `*_direct_reference`; `run.reference_provisional` indicates the planogram is a draft. Price compliance is optional.

## Local server recipe
Use `--llm llamacpp:<alias> --base-url http://127.0.0.1:8089/v1` for a local backend. PREREQUISITE: feature `localllm-ask-to-image` (adds `ask_to_image()` to `LocalLLMClient`) — until it is merged, this exits 1 with a message naming it. Local defaults: sub-strips of ≤ 8 slots, verify pass off, concurrency 1. For llama.cpp + LFM2.5-VL, use `cache_prompt: false` with JSON-schema constraints.

## Data egress
Cloud backends (the default `google:gemini-3.8-flash`) receive **strips of your store photos** and tag contact sheets. Use a local backend if the photos must not leave the machine.

## Set-of-Marks A/B
Marks are on by default. Fill this table from the first real run (`--no-marks` on the same cached images); flip the default if marks hurt.

| Run | Marks | Direct resolutions | Unknown slot ids dropped | Strict % | Lenient % | Notes |
|---|---|---|---|---|---|---|
| | on | | | | | |
| | off | | | | | |

## Tests
```bash
pytest examples/planogram/tests/test_plancheck_cli.py -q
```

The worktree PYTHONPATH is set by the conftest to include the `examples/planogram` directory.

## Limitations
- Axis-aligned boxes only (no rectification)
- No accuracy claim (no ground truth)
- The reference planogram is a draft
- Bottom-shelf tags out of frame → no price there
