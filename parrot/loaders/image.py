from typing import Any
from collections.abc import Callable
from pathlib import Path, PurePath
import numpy as np
from PIL import Image
from langchain.docstore.document import Document
from transformers import CLIPModel
import torch
from torchvision import transforms
from .abstract import AbstractLoader
from ..stores.abstract import AbstractStore


class ImageLoader(AbstractLoader):
    """
    Image Loader.
    """
    _extension = ['.jpg', '.jpeg', '.png']
    chunk_size = 768

    def __init__(
        self,
        path: PurePath,
        store: AbstractStore,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'image',
        **kwargs
    ):
        super().__init__(tokenizer, text_splitter, source_type, **kwargs)
        self.path = path
        if isinstance(path, str):
            self.path = Path(path).resolve()
        # Model:
        self._model = CLIPModel.from_pretrained(
            # "openai/clip-vit-base-patch32"
            "openai/clip-vit-large-patch14-336"
        )
        # Define image preprocessing
        self._preprocess = transforms.Compose(
            [
                transforms.Resize((336, 336)),  # Adjust the size to match the model's expected input
                transforms.CenterCrop(336),  # Optionally add a center crop if needed
                transforms.ToTensor(),
                transforms.Normalize(
                    (0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711)
                )  # CLIP's original normalization
            ]
        )
        # required Milvus Store:
        self.store = store

    def transform_image(self, img_data):
        image = self._preprocess(img_data)
        image = image.unsqueeze(0)
        with torch.no_grad():
            features = self._model.get_image_features(pixel_values=image)
        embedding = features.squeeze().cpu().numpy()
        return embedding.astype(np.float32)

    def _insert_image(self, data):
        return self.store.insert(data)

    def _load_image(self, path) -> list:
        """
        Load an Image file.
        Args:
            path (Path): The path to the Image file.
        Returns:
            list: A list of Langchain Documents.
        """
        if self._check_path(path):
            self.logger.info(f"Loading Image file: {path}")
            img = Image.open(path).convert('RGB')
            embedding = self.transform_image(img).tolist()
            data={
                "url": '',
                "source": f"{path.name}",
                "filename": path,
                "question": '',
                "answer": '',
                "source_type": self._source_type,
                "type": "image",
                "text": '',
                "vector": embedding,
                "document_meta": {
                    "image": path.name,
                    "extension": path.suffix
                }
            }
            self._insert_image([embedding])
        return []

    def load(self) -> list:
        """
        Load data from a Image file.
        Returns:
            list: A list of Langchain Documents.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"Image file/directory not found: {self.path}")
        if self.path.is_dir():
            # iterate over the files in the directory
            for ext in self._extension:
                for item in self.path.glob(f'*{ext}'):
                    self._load_image(item)
        elif self.path.is_file():
            self._load_image(self.path)
        else:
            raise ValueError(
                f"Image Loader: Invalid path: {self.path}"
            )
        # Load Image loads the image directly to database.
        return True

    def parse(self, source):
        raise NotImplementedError(
            "Parser method is not implemented for ImageLoader."
        )
