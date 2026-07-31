---
type: Wiki Entity
title: EXIFPlugin
id: class:parrot.interfaces.images.plugins.exif.EXIFPlugin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: EXIFPlugin is a plugin for extracting EXIF data from images.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# EXIFPlugin

Defined in [`parrot.interfaces.images.plugins.exif`](../summaries/mod:parrot.interfaces.images.plugins.exif.md).

```python
class EXIFPlugin(ImagePlugin)
```

EXIFPlugin is a plugin for extracting EXIF data from images.
It extends the ImagePlugin class and implements the analyze method to extract EXIF data.

## Methods

- `def convert_to_degrees(self, value: tuple[IFDRational])` — Convert a 3-tuple of (deg, min, sec)—each component either an IFDRational or a float/int—
- `def extract_gps_datetime(self, exif: dict)` — Extract GPS coordinates and a timestamp (preferring GPSDateStamp+GPSTimeStamp if available,
- `async def extract_iptc_data(self, image) -> dict` — Extract IPTC metadata from an image.
- `async def extract_exif_heif(self, heif_image) -> Optional[Dict]` — Extract EXIF data from a HEIF/HEIC image using the heif library.
- `async def extract_exif_data(self, image) -> dict` — Extract EXIF data from the image file object.
- `async def analyze(self, image: Optional[Image.Image]=None, heif: Any=None, **kwargs) -> dict` — Extract EXIF data from the given image.
