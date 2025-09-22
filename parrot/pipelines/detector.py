from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Tuple
import cv2
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from navconfig.logging import logging
try:
    from ultralytics import YOLO  # yolo12m works with this API
except Exception:
    YOLO = None
from ..models.detections import DetectionBox

class AbstractDetector(ABC):
    """Abstract base class for all detectors."""
    def __init__(
        self,
        yolo_model: str = "yolo12l.pt",
        conf: float = 0.15,
        iou: float = 0.5,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        **kwargs
    ):
        if isinstance(yolo_model, str):
            assert YOLO is not None, "ultralytics is required"
            self.yolo = YOLO(yolo_model)
        else:
            self.yolo = yolo_model
        self.conf = conf
        self.iou = iou
        self.device = device
        self.logger = logging.getLogger(
            f'parrot.pipelines.{self.__class__.__name__}'
        )
        self._define_clip()

    # ----------------------- enhancement & CLIP -------------------------------
    def _embed_image(self, path: Optional[str]):
        if not path:
            return None
        im = Image.open(path).convert("RGB")
        with torch.no_grad():
            inputs = self.proc(images=im, return_tensors="pt").to(self.device)
            feat = self.clip.get_image_features(**inputs)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat

    def _define_clip(self):
        self.clip = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(self.device)
        self.proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    def _iou(self, a: DetectionBox, b: DetectionBox) -> float:
        ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
        ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        ua = a.area + b.area - inter
        return inter / float(max(1, ua))

    def _normalized_y(self, b, h: int) -> Tuple[float, float, float]:
        y1n, y2n = b.y1 / h, b.y2 / h
        yc = 0.5 * (y1n + y2n)
        return y1n, yc, y2n

    def _iou_box_tuple(self, d: DetectionBox, box: tuple[int,int,int,int]) -> float:
        ax1, ay1, ax2, ay2 = box
        ix1, iy1 = max(d.x1, ax1), max(d.y1, ay1)
        ix2, iy2 = min(d.x2, ax2), min(d.y2, ay2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        return inter / float(d.area + (ax2-ax1)*(ay2-ay1) - inter + 1e-6)

    def _coerce_bbox(self, bbox, W, H):
        if bbox is None:
            return None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x1, y1, x2, y2 = map(float, bbox)
        elif isinstance(bbox, dict):
            if {"x1","y1","x2","y2"} <= bbox.keys():
                x1, y1, x2, y2 = map(float, (bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]))
            elif {"x","y","w","h"} <= bbox.keys():
                x1, y1 = float(bbox["x"]), float(bbox["y"])
                x2, y2 = x1 + float(bbox["w"]), y1 + float(bbox["h"])
            else:
                return None
        else:
            return None
        def to_px(v, M):
            return int(round(v * M)) if v <= 1.5 else int(round(v))
        x1, y1, x2, y2 = to_px(x1, W), to_px(y1, H), to_px(x2, W), to_px(y2, H)
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        x1 = max(0, min(W-1, x1))
        x2 = max(0, min(W-1, x2))
        y1 = max(0, min(H-1, y1))
        y2 = max(0, min(H-1, y2))
        if (x2-x1) < 4 or (y2-y1) < 4:
            return None
        return (x1, y1, x2, y2)

    @abstractmethod
    async def detect(
        self,
        image: Any,
        image_array: Any,
        **kwargs: Any
    ) -> Tuple[Any, List[Any]]:
        """
        Abstract method for detecting objects in an image.

        Args:
            image: The input image.
            image_array: The input image as a numpy array.
            **kwargs: Additional keyword arguments.

        Returns:
            A tuple containing the processed image and a list of detections.
        """
        pass
