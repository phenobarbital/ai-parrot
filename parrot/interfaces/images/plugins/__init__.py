"""
Image processing and generation interfaces for Parrot.
"""
from .yolo import YOLOPlugin
from .vision import VisionTransformerPlugin
from .hash import ImageHashPlugin
from .abstract import ImagePlugin
from .exif import EXIFPlugin
from .zerodetect import ZeroShotDetectionPlugin


PLUGINS = {
    "exif": EXIFPlugin,
    "hash": ImageHashPlugin,
    "yolo": YOLOPlugin,
    "vectorization": VisionTransformerPlugin,
    "zeroshot": ZeroShotDetectionPlugin,
}
