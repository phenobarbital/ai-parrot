# AI-Parrot Pipelines

**ai-parrot-pipelines** provides planogram compliance and vision workflows for
[AI-Parrot](https://pypi.org/project/ai-parrot/) agents.

## Installation

```bash
pip install ai-parrot-pipelines
```

Install the optional local-OCR dependencies when needed:

```bash
pip install "ai-parrot-pipelines[planogram]"
```

## Features

- **Planogram Compliance** — a perceive → identify → compare cycle for six types
- **Layout Profiles** — validated, per-type geometry and identification settings
- **Optional Local OCR** — RapidOCR is auto-detected when the `planogram` extra is installed
- **Migration Utility** — converts and preflights six planogram configuration types

## Available Pipelines

| Pipeline/type | Description |
|---|---|
| `PlanogramCompliance` | Planogram compliance pipeline |
| `ProductOnShelves` | Product-facing shelves |
| `InkWall` | Price-tag-anchored ink walls |
| `EndcapBacklitMultitier` | Multi-tier endcaps |
| `EndcapNoShelvesPromotional` | Zone-based promotional endcaps |
| `GraphicPanelDisplay` | Zone-only graphic panels |
| `ProductCounter` | Product and zone counters |

## Quick Start

```python
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.models import PlanogramConfig

config = PlanogramConfig(
    config_name="example",
    planogram_type="product_on_shelves",
    planogram_config={},
    slots_definition={
        "version": "1",
        "shelves": [
            {
                "shelf_id": "shelf_1",
                "shelf_number": 1,
                "facings": [
                    {
                        "facing_id": "facing_1",
                        "shelf_id": "shelf_1",
                        "slot": 1,
                        "product": "example_product",
                        "descriptors": {"display_name": "Example product"},
                    }
                ],
            }
        ],
        "zones": [],
    },
)

pipeline = PlanogramCompliance(planogram_config=config, llm="openai:gpt-4o-mini")
result = await pipeline.run("shelf_photo.jpg")
```

Provide a complete, validated slots definition and rule bindings before a production run. See the
[cycle reference](../../docs/pipelines/planogram-compliance-cycle.md) and the
[migration runbook](../../docs/pipelines/planogram-cycle-migration.md).

## Dependencies

- Python >= 3.11
- [ai-parrot](https://pypi.org/project/ai-parrot/) >= 0.24.2
- [opencv-python-headless](https://pypi.org/project/opencv-python-headless/) >= 4.8
- Optional `planogram` extra: `rapidocr` and `onnxruntime`

## 1.1.0 breaking changes

The removed detector APIs and required configuration migration are documented in the
[migration runbook](../../docs/pipelines/planogram-cycle-migration.md).

## License

MIT
