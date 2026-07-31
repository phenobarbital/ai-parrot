---
type: Wiki Entity
title: YOLOPlugin
id: class:parrot.interfaces.images.plugins.yolo.YOLOPlugin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: YOLOPlugin is a plugin for performing object detection using the YOLO (You
  Only Look Once) model.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# YOLOPlugin

Defined in [`parrot.interfaces.images.plugins.yolo`](../summaries/mod:parrot.interfaces.images.plugins.yolo.md).

```python
class YOLOPlugin(ImagePlugin)
```

YOLOPlugin is a plugin for performing object detection using the YOLO (You Only Look Once) model.
It extends the ImagePlugin class and implements the analyze method to perform object detection.

## Methods

- `async def dispose(self)` — Close the YOLO model.
- `async def analyze(self, image: Image.Image, **kwargs) -> dict` — Perform object detection on the given image using the YOLO model.
