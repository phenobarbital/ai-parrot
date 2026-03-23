from PIL import Image
from imagehash import phash, dhash
from .abstract import ImagePlugin


class ImageHashPlugin(ImagePlugin):
    """
    ImageHashPlugin is a plugin for generating perceptual hashes of images.
    It extends the ImagePlugin class and implements the analyze method to generate hashes.
    """
    column_name: str = "image_hash"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hash_type: str = kwargs.get("model", "phash")
        self._hash_size: int = kwargs.get("hash_size", 8)
        self._hash_func = self._get_hash_function(self._hash_type)

    def _get_hash_function(self, hash_type: str):
        """
        Get the hash function based on the specified hash type.

        :param hash_type: Type of hash to generate (e.g., 'phash', 'dhash').
        :return: Hash function.
        """
        if hash_type == "phash":
            return phash
        elif hash_type == "dhash":
            return dhash
        else:
            raise ValueError(
                f"Unsupported hash type: {hash_type}"
            )

    async def analyze(self, image: Image.Image, **kwargs) -> str:
        """
        Generate a perceptual hash of the given image.

        :param image: Image Bytes opened with PIL Image.open
        :return: Perceptual hash of the image.
        """
        try:
            hash_value = self._hash_func(image, hash_size=self._hash_size)
            if hash_value:
                return str(hash_value)
            else:
                return ''
        except Exception as e:
            self.logger.error(
                f"Error in ImageHash analysis: {str(e)}"
            )
            return ''
