---
type: Wiki Summary
title: parrot_pipelines.planogram.legacy
id: mod:parrot_pipelines.planogram.legacy
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 3-Step Planogram Compliance Pipeline
relates_to:
- concept: class:parrot_pipelines.planogram.legacy.PlanogramCompliancePipeline
  rel: defines
- concept: class:parrot_pipelines.planogram.legacy.RetailDetector
  rel: defines
- concept: mod:parrot.models.compliance
  rel: references
- concept: mod:parrot.models.detections
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot_pipelines.abstract
  rel: references
- concept: mod:parrot_pipelines.detector
  rel: references
- concept: mod:parrot_pipelines.models
  rel: references
---

# `parrot_pipelines.planogram.legacy`

3-Step Planogram Compliance Pipeline
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification

## Classes

- **`RetailDetector(AbstractDetector)`** — Reference-guided Phase-1 detector.
- **`PlanogramCompliancePipeline(AbstractPipeline)`** — Pipeline for planogram compliance checking.
