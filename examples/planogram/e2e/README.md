# Live E2E Planogram Compliance Tests

This directory contains opt-in live integration tests that run the full planogram
compliance cycle (perceive → identify → compare) against real provider endpoints
using private, locally-supplied assets. These tests are **not a CI gate** and are
never run automatically.

## Purpose

The live E2E tests verify that the three-stage planogram cycle works correctly
with real photos, real OCR, and real LLM calls. They use human-labelled ground
truth (expected positions, occupancy, and rule outcomes) with explicit tolerance
values to determine pass/fail.

Accuracy signoff for the planogram compliance feature requires three successful
local runs — one for each case type (`shelves`, `ink-wall`, `backlit-endcap`) —
producing signed reports that demonstrate the system meets the configured
tolerances on private retailer data.

## Privacy

This repository is public. Only the harness Python files (`.gitignore` permits
`conftest.py`, `test_compliance.py`, `models.py`, `runner.py` and this README)
are tracked. All private assets — manifests, photos, configs, ground truth,
caches, renders, and reports — must live under ignored paths inside this
directory or outside the repository entirely.

**Never** `git add -f` any private file. The `.gitignore` rules in the parent
directory block accidental commits of common private-asset patterns.

## Prerequisites

1. **Installed packages**: `ai-parrot-pipelines` (optionally with the `planogram`
   extra for local OCR via RapidOCR).

2. **Provider credentials**: Set the required environment variables for your
   chosen backend (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, AWS credentials).
   The manifest declares which variables each case needs.

3. **Migrated configs**: Planogram configuration rows must be exported from
   `troc.planogram_configurations` and migrated to the new JSON format. See
   `docs/pipelines/planogram-cycle-migration.md` for migration instructions.

4. **Private assets**: You need:
   - A manifest JSON file describing the cases.
   - One or more photos per case.
   - One config JSON file per case (exported from the database).
   - One ground-truth JSON file per case (human-labelled).

## Manifest Format

The manifest is a JSON file that describes all cases and their credential
requirements. Below is a **fictitious** template:

```json
{
  "cases": [
    {
      "case_id": "shelves",
      "planogram_type": "product_on_shelves",
      "photos": ["/path/to/private/demo-shelf-01.jpg", "/path/to/private/demo-shelf-02.jpg"],
      "config_path": "/path/to/private/config-shelf-demo.json",
      "ground_truth_path": "/path/to/private/ground-truth-shelf-demo.json",
      "backend": "openai:gpt-4o-mini",
      "cache_dir": "/path/to/private/cache/shelves",
      "output_dir": "/path/to/private/output/shelves",
      "max_provider_requests": 64,
      "timeout_seconds": 600.0
    },
    {
      "case_id": "ink-wall",
      "planogram_type": "ink_wall",
      "photos": ["/path/to/private/demo-inkwall-01.jpg"],
      "config_path": "/path/to/private/config-inkwall-demo.json",
      "ground_truth_path": "/path/to/private/ground-truth-inkwall-demo.json",
      "backend": "openai:gpt-4o-mini",
      "cache_dir": "/path/to/private/cache/ink-wall",
      "output_dir": "/path/to/private/output/ink-wall"
    },
    {
      "case_id": "backlit-endcap",
      "planogram_type": "endcap_backlit_multitier",
      "photos": ["/path/to/private/demo-endcap-01.jpg"],
      "config_path": "/path/to/private/config-endcap-demo.json",
      "ground_truth_path": "/path/to/private/ground-truth-endcap-demo.json",
      "backend": "openai:gpt-4o-mini",
      "cache_dir": "/path/to/private/cache/backlit-endcap",
      "output_dir": "/path/to/private/output/backlit-endcap"
    }
  ],
  "required_env": {
    "openai": ["OPENAI_API_KEY"]
  }
}
```

### Field descriptions

| Field | Description |
|-------|-------------|
| `case_id` | Unique identifier: `shelves`, `ink-wall`, or `backlit-endcap` |
| `planogram_type` | Must match the case_id mapping in `models.CASE_TYPES` |
| `photos` | List of absolute or manifest-relative paths to JPEG/PNG photos |
| `config_path` | Path to an exported `troc.planogram_configurations` row as JSON |
| `ground_truth_path` | Path to human-labelled expectations (see below) |
| `backend` | Explicit provider:model (e.g., `openai:gpt-4o-mini`) |
| `cache_dir` | Directory for vision-response cache (created if missing) |
| `output_dir` | Directory for compliance.json, report.json, and renders |
| `max_provider_requests` | Cap on uncached provider calls (default: 64) |
| `timeout_seconds` | Per-case timeout (default: 600.0) |
| `required_env` | Map of provider name to list of required env-var names |

Paths are resolved relative to the manifest's directory unless they are absolute.

## Config File Format

Each config file is an exported row from `troc.planogram_configurations`:

```json
{
  "config_name": "acme-store-001-shelf",
  "planogram_type": "product_on_shelves",
  "planogram_config": {
    "layout_profile": {
      "shape_profiles": [...],
      "anchor_rule": "shape_is_slot",
      "perception_mode": "cv"
    },
    "slots_definition": { ... },
    "reference_images": { ... },
    "llm_backend": "openai:gpt-4o-mini"
  }
}
```

The `planogram_type` in the config must match the case's `planogram_type`.

## Ground Truth Format

Ground truth is human-labelled data that defines what the system *should* find.
Labels are created by a human looking at the photo — never copied from a run.

```json
{
  "expected_positions": {
    "shelf-1:slot-01": "Acme-Cola-12oz",
    "shelf-1:slot-02": "Acme-Cola-24oz",
    "shelf-2:slot-01": "Acme-Chips-Original",
    "shelf-2:slot-02": "Acme-Chips-BBQ"
  },
  "expected_occupancy": {
    "shelf-1:slot-01": "occupied",
    "shelf-1:slot-02": "occupied",
    "shelf-1:slot-03": "empty",
    "shelf-2:slot-01": "occupied",
    "shelf-2:slot-02": "occupied"
  },
  "expected_rules": {
    "brand-adjacent": true,
    "no-misplaced": true
  },
  "overall_score": 0.85,
  "score_tolerance": 0.05,
  "min_coverage": 0.90,
  "max_identity_errors": 1,
  "max_occupancy_errors": 0
}
```

### Field descriptions

| Field | Description |
|-------|-------------|
| `expected_positions` | Map of facing_id → expected product identity |
| `expected_occupancy` | Map of facing_id → `occupied`, `empty`, or `unknown` |
| `expected_rules` | Map of rule_id → expected pass/fail boolean; informative rules such as `fact_tag_present:<facing_id>` are accepted too |
| `overall_score` | Expected compliance score in [0, 1] |
| `score_tolerance` | Permissible deviation from `overall_score` |
| `min_coverage` | Minimum required coverage in [0, 1] |
| `max_identity_errors` | Budget for mismatched product identities |
| `max_occupancy_errors` | Budget for occupancy mismatches |

Facing IDs come from the slots definition. Occupancy values: `occupied` means a
product is visible; `empty` means the slot should have no product (e.g., a
divider or gap); `unknown` skips the occupancy check.

## Running the Tests

### Full suite (all three cases)

```bash
PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/your/manifest.json pytest examples/planogram/e2e -q
```

### Single case

```bash
PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/your/manifest.json pytest examples/planogram/e2e -q -k shelves
```

### Verbose output

```bash
PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/your/manifest.json pytest examples/planogram/e2e -v -rs
```

The `-rs` flag shows skip reasons.

## Skip vs. Fail

| Condition | Result | Reason shown |
|-----------|--------|--------------|
| `PARROT_TEST_REAL_LLM` not set to `1` | Skip | "Set PARROT_TEST_REAL_LLM=1..." |
| `PLANOGRAM_E2E_MANIFEST` not set | Skip | "Set PLANOGRAM_E2E_MANIFEST..." |
| Manifest file does not exist | Skip | "Manifest file not found: ..." |
| Case not configured in manifest | Skip | "case 'shelves' is not configured..." |
| Photo, config, or truth file missing | Skip | "missing file: /path/to/..." |
| Required env variable missing | Skip | "missing required environment variable: ..." |
| Manifest is malformed JSON | **Fail** | JSON decode error |
| Ground truth fails validation | **Fail** | Pydantic validation error |
| Config fails preflight | **Fail** | "invalid planogram config: ..." |
| Any ground-truth assertion fails | **Fail** | List of violations + report path |

Skips happen **before** any provider client is created, so no API calls are made
when prerequisites are missing.

## Outputs

Each case writes two JSON files to its `output_dir`:

- **`compliance.json`**: The raw pipeline output (JSON-safe, images removed).
- **`report.json`**: A summary including:
  - Case ID, planogram type, backend used
  - SHA256 hashes of config and photos
  - Layout profile used
  - Prompt version
  - Reference selection details
  - Provider request count and budget status
  - Cache statistics (entries before/after)
  - Render file paths
  - Errors encountered
  - Ground-truth assertion results

If a test fails, the assertion message includes the report path so you can
inspect the detailed output.

## Cost and Cache

Each case defaults to a maximum of **64 uncached provider requests** and a
**600-second** timeout. Every provider call counts — detection, identification,
and rule-evidence collection all consume the budget.

The cache lives in the case's `cache_dir`. Cache hits are free only when the
image content, reference images, prompt version, model, and schema are
unchanged. Changing any of those invalidates the cache.

Expect roughly 10–30 provider calls per case depending on the photo complexity
and whether the LLM detector fallback is triggered.

## Signoff

To claim accuracy for the planogram compliance feature (AC17), you must produce
three successful local reports — one for each case type — where every
ground-truth assertion passes. Save these reports as evidence of the system's
behavior on private retailer data.
