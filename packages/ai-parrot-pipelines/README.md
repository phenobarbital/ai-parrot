# AI-Parrot Pipelines

**ai-parrot-pipelines** provides vision and compliance pipelines for [AI-Parrot](https://pypi.org/project/ai-parrot/) agents. It includes planogram compliance checking, retail product detection, and image analysis workflows.

## Installation

```bash
pip install ai-parrot-pipelines
```

## Features

- **Planogram Compliance** — verify product placement against planogram specifications
- **Retail Detection** — detect products on shelves, graphic panels, and endcaps
- **Abstract Pipeline** — base class for building custom vision pipelines
- **Abstract Detector** — base class for object detection integrations

## Available Pipelines

| Pipeline | Description |
|----------|-------------|
| `PlanogramCompliance` | Full planogram compliance checking pipeline |
| `ProductOnShelves` | Detect and validate products on shelf displays |
| `GraphicPanelDisplay` | Validate graphic panel displays |
| `RetailDetector` | General retail product detection |

## Quick Start

```python
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.models import PlanogramConfig

config = PlanogramConfig(
    image_path="shelf_photo.jpg",
    reference_path="planogram_spec.json",
)

pipeline = PlanogramCompliance(config=config)
result = await pipeline.run()
```

## Dependencies

- Python >= 3.11
- [ai-parrot](https://pypi.org/project/ai-parrot/) >= 0.24.2
- [opencv-python-headless](https://pypi.org/project/opencv-python-headless/) >= 4.8
- [pytesseract](https://pypi.org/project/pytesseract/) >= 0.3.13

**Note:** `pytesseract` requires [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system.

## License

MIT
