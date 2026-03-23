from ultralytics import YOLO
from PIL import Image
from .abstract import ImagePlugin


class YOLOPlugin(ImagePlugin):
    """
    YOLOPlugin is a plugin for performing object detection using the YOLO (You Only Look Once) model.
    It extends the ImagePlugin class and implements the analyze method to perform object detection.
    """
    column_name: str = "image_features"

    def __init__(self, *args, **kwargs):
        self._model_name: str = kwargs.get("model_name", "yolov8n")
        self._model_path: str = kwargs.get("model_path", "yolov11l.pt")
        if not self._model_name or not self._model_path:
            raise ValueError(
                "Model name and model path are required."
            )
        super().__init__(*args, **kwargs)
        try:
            self.model = YOLO(self._model_path)
        except Exception as e:
            raise RuntimeError(
                f"Error loading YOLO model: {str(e)}"
            ) from e

    async def dispose(self):
        """
        Close the YOLO model.
        """
        if hasattr(self, "model"):
            self.model = None

    async def analyze(self, image: Image.Image, **kwargs) -> dict:
        """
        Perform object detection on the given image using the YOLO model.

        :param image: Image Bytes opened with PIL Image.open
        :return: Dictionary containing detected objects and their bounding boxes.
        """
        try:
            if image is None:
                return {}
            results = self.model.predict(source=image, conf=0.25, save=False, verbose=False)
            return self._parse_results(results)
        except Exception as e:
            self.logger.error(f"Error in YOLO analysis: {str(e)}")
            return {}

    def _parse_results(self, results) -> dict:
        """
        Parse the results from the YOLO model.

        :param results: Results from the YOLO model.
        :return: Dictionary containing detected objects and their bounding boxes.
        """
        detections = []
        for r in results:
            for box in r.boxes:
                detections.append({
                    "label": r.names[int(box.cls)],
                    "conf": float(box.conf),
                    "box": box.xyxy[0].tolist()
                })
        return {"detections": detections}
