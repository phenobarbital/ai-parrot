---
type: Wiki Entity
title: PlanogramCompliancePipeline
id: class:parrot_pipelines.planogram.legacy.PlanogramCompliancePipeline
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pipeline for planogram compliance checking.
relates_to:
- concept: class:parrot_pipelines.abstract.AbstractPipeline
  rel: extends
---

# PlanogramCompliancePipeline

Defined in [`parrot_pipelines.planogram.legacy`](../summaries/mod:parrot_pipelines.planogram.legacy.md).

```python
class PlanogramCompliancePipeline(AbstractPipeline)
```

Pipeline for planogram compliance checking.

3-Step planogram compliance pipeline:
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification

## Methods

- `async def detect_objects_and_shelves(self, image: Image, image_array: np.ndarray, endcap: Detection, ad: Optional[Detection]=None, brand: Optional[Detection]=None, panel_text: Optional[Detection]=None, planogram_description: Optional[PlanogramDescription]=None)`
- `async def identify_objects_with_references(self, image: Union[str, Path, Image.Image], detections: List[DetectionBox], shelf_regions: List[ShelfRegion], reference_images: List[Union[str, Path, Image.Image]], prompt: str) -> List[IdentifiedProduct]` — Step 2: Use LLM to identify detected objects using reference images
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: PlanogramDescription) -> List[ComplianceResult]` — Check compliance of identified products against the planogram.
- `async def run(self, image: Union[str, Path, Image.Image], debug_raw='/tmp/data/yolo_raw_debug.png', return_overlay: Optional[str]=None, overlay_save_path: Optional[Union[str, Path]]=None) -> Dict[str, Any]` — Run the complete 3-step planogram compliance pipeline
- `def render_evaluated_image(self, image: Union[str, Path, Image.Image], *, shelf_regions: Optional[List[ShelfRegion]]=None, detections: Optional[List[DetectionBox]]=None, identified_products: Optional[List[IdentifiedProduct]]=None, mode: str='identified', show_shelves: bool=True, save_to: Optional[Union[str, Path]]=None) -> Image.Image` — Enhanced render with safe coordinate handling
- `def generate_compliance_json(self, results: Dict[str, Any]) -> Dict[str, Any]` — Generate comprehensive JSON report from pipeline results.
- `def generate_compliance_markdown(self, results: Dict[str, Any], brand_name: Optional[str]=None, additional_notes: Optional[str]=None) -> str` — Generate comprehensive Markdown report from pipeline results.
