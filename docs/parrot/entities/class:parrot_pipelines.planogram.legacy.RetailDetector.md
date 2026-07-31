---
type: Wiki Entity
title: RetailDetector
id: class:parrot_pipelines.planogram.legacy.RetailDetector
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Reference-guided Phase-1 detector.
relates_to:
- concept: class:parrot_pipelines.detector.AbstractDetector
  rel: extends
---

# RetailDetector

Defined in [`parrot_pipelines.planogram.legacy`](../summaries/mod:parrot_pipelines.planogram.legacy.md).

```python
class RetailDetector(AbstractDetector)
```

Reference-guided Phase-1 detector.

1) Enhance image (contrast/brightness) to help OCR/YOLO/CLIP.
2) Localize the promotional poster using:
   - OCR ('EPSON', 'Hello', 'Savings', etc.)
   - CLIP similarity with your FIRST reference image.
3) Crop to poster width (+ margin) to form an endcap ROI (remember offsets).
4) Detect shelf lines within ROI (Hough) => top/middle/bottom bands.
5) YOLO proposals inside ROI (low conf, class-agnostic).
6) For each proposal: OCR + CLIP vs remaining reference images
   => label as promotional/product/box candidate.
7) Shrink, merge, suppress items that are inside the poster.

## Methods

- `async def detect(self, image: Image.Image, image_array: np.array, endcap: Detection, ad: Detection, planogram: Optional[PlanogramDescription]=None, debug_yolo: Optional[str]=None, debug_phase1: Optional[str]=None, debug_phases: Optional[str]=None)`
- `def set_detection_phases(self, phases: List[Dict[str, Any]])` — Set custom detection phases for the RetailDetector
