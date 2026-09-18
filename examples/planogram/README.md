# Planogram compliance check (label-anchored, autonomous)

This tool runs an 8-stage pipeline to check store photos against a planogram: detect price tags, build a grid of product slots, read slot contents with an LLM, verify against expectations, register slots to planogram facings, merge observations, score compliance, and write a report.

## What stays local
Photos, `planogram_page1.json`, PDFs, videos and every result directory are git-ignored on purpose (this repository is public). Only code, tests and this README are tracked.

## Install
Activate the repo venv (`source .venv/bin/activate`) and ensure the following packages are installed: opencv-python, numpy, rapidocr + onnxruntime (optional — without it prices are read by the LLM only), rapidfuzz, pydantic, pillow, ai-parrot + ai-parrot-client-google (+ -local). Credentials are provided via environment variables only (e.g. GOOGLE_API_KEY).

## Product descriptors (in the planogram)
The planogram is the only reference file: each position says *where* a product goes **and** *what its package
shows*. Positions carry these descriptor fields next to `product` (the part number) and `brand`:
- `display_name`: what the package shows — a position is *described* only when this is non-empty
- `family`: product family / model number printed on the box (e.g. `"31"`)
- `xl`: whether this is an XL variant (`true`/`false`)
- `colors`: list of color variants (e.g. `["black"]`, `["tri-color"]`)
- `pack`: number of units in the pack (`null` = 1)
- `identifiers`: extra codes printed on the box (the part number is always one)
- `aliases`: alternative names that appear on the package
- `price`: expected shelf price (optional; enables price compliance)

`--init-descriptors` adds every missing field as `null` to each position of the planogram, in place (existing
values are never touched); then fill them in. A synthetic example position:

```json
"pos 1:1": {
  "position": 1, "segment": "left", "segment_number": 1, "slot": 1, "segment_slot": 1,
  "product": "AC-11", "brand": "Acme", "shelf": 1, "facings": 1,
  "confidence": "high", "read_method": "direct", "notes": null,
  "display_name": "Acme 10 Black", "family": "10", "xl": false, "colors": ["black"], "pack": 1,
  "identifiers": null, "aliases": ["Acme 10 Black Ink"], "price": "29.99"
}
```

Fill `family`/`xl`/`colors`/`pack`, not just `display_name`: identity resolution compares those fields and never
merges XL, color or pack variants. A SKU used in several positions may be described in any of them, but every
described occurrence must agree. Undescribed identity-required SKUs are listed in `run.undescribed_skus`; a
planogram with no described position is rejected (exit 1).

## Usage
```bash
python examples/planogram/planogram_check.py --init-descriptors   # once, then fill the fields in
python examples/planogram/planogram_check.py --output examples/planogram/results/run1
```

Options:
- `--images-dir <path>`: directory containing store photos (default: `examples/planogram/images`)
- `--images <file>...`: explicit list of photo files
- `--planogram <file>`: planogram JSON with product descriptors (default: `examples/planogram/planogram_page1.json`)
- `--output <dir>`: new directory for results (required)
- `--llm <provider:model>`: LLM for identification (default: `google:gemini-3.8-flash`)
- `--ocr-llm <provider:model>`: LLM for price OCR fallback
- `--base-url <url>`: base URL for local OpenAI-compatible servers
- `--prices <file>`: optional JSON mapping SKUs to expected prices; overrides the planogram `price` fields
- `--roi L T R B`: region of interest (0 <= L < R <= 1, 0 <= T < B <= 1)
- `--verify-pass` / `--no-verify-pass`: enable/disable closed-set verification (default: auto)
- `--no-marks`: disable Set-of-Marks outlines
- `--concurrency <n>`: concurrent LLM calls (1-16, default: 4)
- `--cache-dir <dir>`: cache directory (default: `examples/planogram/results/.plancheck_cache`)
- `--visit-id <id>`: visit identifier (default: `visit`)
- `--init-descriptors`: add the missing descriptor fields (as `null`) to the planogram in place, and exit

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
