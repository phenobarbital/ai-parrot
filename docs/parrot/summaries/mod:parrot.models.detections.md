---
type: Wiki Summary
title: parrot.models.detections
id: mod:parrot.models.detections
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.models.detections
relates_to:
- concept: class:parrot.models.detections.AdvertisementEndcap
  rel: defines
- concept: class:parrot.models.detections.AisleConfig
  rel: defines
- concept: class:parrot.models.detections.BoundingBox
  rel: defines
- concept: class:parrot.models.detections.BrandDetectionConfig
  rel: defines
- concept: class:parrot.models.detections.CategoryDetectionConfig
  rel: defines
- concept: class:parrot.models.detections.Detection
  rel: defines
- concept: class:parrot.models.detections.DetectionBox
  rel: defines
- concept: class:parrot.models.detections.Detections
  rel: defines
- concept: class:parrot.models.detections.IdentificationResponse
  rel: defines
- concept: class:parrot.models.detections.IdentifiedProduct
  rel: defines
- concept: class:parrot.models.detections.PlanogramConfigBuilder
  rel: defines
- concept: class:parrot.models.detections.PlanogramDescription
  rel: defines
- concept: class:parrot.models.detections.PlanogramDescriptionFactory
  rel: defines
- concept: class:parrot.models.detections.SectionRegion
  rel: defines
- concept: class:parrot.models.detections.ShelfConfig
  rel: defines
- concept: class:parrot.models.detections.ShelfProduct
  rel: defines
- concept: class:parrot.models.detections.ShelfRegion
  rel: defines
- concept: class:parrot.models.detections.ShelfSection
  rel: defines
- concept: class:parrot.models.detections.TextRequirement
  rel: defines
- concept: func:parrot.models.detections.build_planogram_json_diagram
  rel: defines
- concept: func:parrot.models.detections.planogram_diagram_to_markdown
  rel: defines
---

# `parrot.models.detections`

## Classes

- **`BoundingBox(BaseModel)`** — Normalized bounding box coordinates
- **`Detection(BaseModel)`** — Generic detection result
- **`Detections(BaseModel)`** — Collection of detections in an image
- **`DetectionBox(BaseModel)`** — Bounding box from object detection
- **`ShelfRegion(BaseModel)`** — Detected shelf region
- **`IdentifiedProduct(BaseModel)`** — Product identified by LLM using reference images
- **`IdentificationResponse(BaseModel)`** — Response from product identification
- **`BrandDetectionConfig(BaseModel)`** — Configuration for brand detection parameters
- **`CategoryDetectionConfig(BaseModel)`** — Configuration for product category detection
- **`ShelfProduct(BaseModel)`** — Configuration for products expected on a shelf
- **`SectionRegion(BaseModel)`** — Normalized x/y ratio boundaries defining a sub-region within a shelf.
- **`ShelfSection(BaseModel)`** — A named sub-section within a shelf, defining a region and expected products.
- **`ShelfConfig(BaseModel)`** — Configuration for a single shelf
- **`TextRequirement(BaseModel)`** — Text requirement for promotional materials
- **`AdvertisementEndcap(BaseModel)`** — Configuration for advertisement endcap
- **`AisleConfig(BaseModel)`** — Configuration for aisle-specific settings
- **`PlanogramDescription(BaseModel)`** — Comprehensive, configurable planogram description
- **`PlanogramDescriptionFactory`** — Factory class for creating PlanogramDescription objects from dictionaries
- **`PlanogramConfigBuilder`** — Builder class for easier construction of planogram configurations

## Functions

- `def build_planogram_json_diagram(planogram) -> Dict[str, Any]` — Produce a compact, human-friendly JSON 'diagram' of a PlanogramDescription.
- `def planogram_diagram_to_markdown(diagram: Mapping[str, Any]) -> str` — Render the JSON diagram as Markdown ready for reports.
