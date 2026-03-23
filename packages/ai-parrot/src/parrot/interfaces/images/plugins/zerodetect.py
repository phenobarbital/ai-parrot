from typing import Optional, List
from collections import Counter
import torch
from PIL import Image
import numpy as np
from transformers import (
    AutoProcessor,
    AutoModelForZeroShotObjectDetection,
    Owlv2Processor,
    Owlv2ForObjectDetection
)
from transformers.utils.constants import OPENAI_CLIP_MEAN, OPENAI_CLIP_STD
from .abstract import ImagePlugin

SUPPORTED_MODELS = {
    "grounding-dino-base": {
        "model": "IDEA-Research/grounding-dino-base",
        "model_object": AutoModelForZeroShotObjectDetection,
        "processor": AutoProcessor,
        "model_type": "grounding-dino"
    },
    "grounding-dino-tiny": {
        "model": "IDEA-Research/grounding-dino-tiny",
        "model_object": AutoModelForZeroShotObjectDetection,
        "processor": AutoProcessor,
        "model_type": "grounding-dino"
    },
    "owlv2-large": {
        "model": "google/owlv2-large-patch14-finetuned",
        "model_object": Owlv2ForObjectDetection,
        "processor": Owlv2Processor,
        "model_type": "google-owlv2"
    },
    "owlv2-base": {
        "model": "google/owlv2-base-patch16",
        "model_object": Owlv2ForObjectDetection,
        "processor": Owlv2Processor,
        "model_type": "google-owlv2"
    },
    "glip-large": {
        "model": "microsoft/glip-large",
        "model_object": AutoModelForZeroShotObjectDetection,
        "processor": AutoProcessor,
        "model_type": "glip"
    }
}


class ZeroShotDetectionPlugin(ImagePlugin):
    """
    ZeroShotDetectionPlugin is a plugin for performing zero-shot object detection using the Grounding DINO model.
    """
    column_name: str = "image_detections"

    def __init__(self, *args, device: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._vector_model: str = kwargs.get("model_name", "grounding-dino-base")
        self._model_info = SUPPORTED_MODELS.get(self._vector_model)
        self.prompt: List[str] = kwargs.get("prompt", ["person"])
        self._model_type: str = self._model_info.get("model_type", "grounding-dino")
        self._image_threshold: float = kwargs.get("image_threshold", 0.4)
        if not self._model_info:
            raise ValueError(
                f"Unsupported model name: {self._vector_model}. "
                f"Supported models are: {list(SUPPORTED_MODELS.keys())}"
            )
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    async def start(self):
        """
        Initialize the model and processor.
        """
        processor = self._model_info["processor"]
        model_object = self._model_info["model_object"]
        model_name = self._model_info["model"]
        if model_name == "google/owlvit-base-patch14-ensemble":
            self.processor = processor.from_pretrained(model_name)
            self.model = model_object.from_pretrained(model_name).to(self.device)
        elif model_name == "google/owlv2-base-patch16":
            self.processor = AutoProcessor.from_pretrained(model_name)
            self.model = Owlv2ForObjectDetection.from_pretrained(model_name).to(self.device)
        else:
            self.processor = processor.from_pretrained(model_name)
            self.model = model_object.from_pretrained(model_name).to(self.device)
        self.model.eval()
        return self

    async def dispose(self):
        """
        Close the model and processor.
        """
        if hasattr(self, "model"):
            del self.model
        if hasattr(self, "processor"):
            del self.processor
        torch.cuda.empty_cache()
        return self

    @staticmethod
    def _to_xyxy(box_tensor):
        """torch.Tensor([x1,y1,x2,y2]) → rounded python list"""
        return [round(float(x), 2) for x in box_tensor.tolist()]

    def _unnormalise(self, pixel_values):
        px = pixel_values.squeeze().cpu().numpy()   # ★ .cpu()
        unnorm = (px * np.array(OPENAI_CLIP_STD)[:, None, None]) \
            + np.array(OPENAI_CLIP_MEAN)[:, None, None]
        unnorm = (unnorm * 255).astype(np.uint8)
        h, w = unnorm.shape[1], unnorm.shape[2]
        return h, w

    async def analyze(self, image: Image.Image, **kwargs) -> dict:
        """
        Generate a vector representation of the given image.

        :param image: Image Bytes opened with PIL Image.open
        :return: Vector representation of the image.
        """
        if image is None:
            return None
        try:
            image = image.convert("RGB")
            text_labels = [self.prompt]
            args = {
                "return_tensors": "pt",
                "images": image,
                "text": text_labels,
            }
            if self._model_type in {'google-owlv2', 'glip'}:
                args['text'] = self.prompt  # list of strings
            # ---------- encode ----- #
            inputs = self.processor(
                **args
            ).to(self.device)
            with torch.no_grad():
                outputs = self.model(**inputs)

            if self._model_type == "grounding-dino":
                results = self.processor.post_process_grounded_object_detection(
                    outputs,
                    threshold=self._image_threshold,
                    text_threshold=0.35,
                    target_sizes=[(image.height, image.width)]
                )[0]                          # batch size 1
                boxes = results["boxes"]
                scores = results["scores"]
                # Grounding‑DINO returns phi indexes, map to strings:
                if "text_labels" in results:
                    label_texts = results["text_labels"]
                else:
                    raw_labels = results["labels"]
                    # raw_labels may be tensor, list[int], or list[str]
                    if isinstance(raw_labels[0], (int, torch.Tensor)):
                        label_texts = [self.prompt[int(i)] for i in raw_labels]
                    else:  # already strings
                        label_texts = list(raw_labels)
            elif self._model_type == "google-owlv2":
                # Convert outputs (bounding boxes and class logits) to final bounding boxes and scores
                h, w = self._unnormalise(inputs.pixel_values)
                target_sizes = [(h, w)]
                results = self.processor.post_process_grounded_object_detection(
                    outputs,
                    target_sizes=target_sizes,
                    threshold=self._image_threshold,
                )[0]                          # batch size 1
                boxes = results["boxes"]
                scores = results["scores"]
                # OWLv2 returns the actual text index already
                label_ids = results["labels"]
                # label_texts = [text_labels[i] for i in label_ids]
                label_texts = [self.prompt[i] for i in label_ids]
            else:
                raise ValueError(
                    f"Unsupported model type: {self._model_type}. "
                    f"Supported models are: {list(SUPPORTED_MODELS.keys())}"
                )
            detections = []
            for box, score, label in zip(boxes, scores, label_texts):
                detection = {
                    "box": self._to_xyxy(box),
                    "score": round(float(score), 2),
                    "label": label
                }
                detections.append(detection)
            counts = Counter(d["label"] for d in detections)
            list_of_objects = sorted(counts)  # unique labels, alphabetic
            return {
                "total_objects": len(detections),
                "objects_detected": dict(counts),
                "objects": list_of_objects,
                "detections": detections
            }
        except Exception as e:
            self.logger.error(
                f"ZeroShot Detection: Error Processing Image: {e}"
            )
            return None
