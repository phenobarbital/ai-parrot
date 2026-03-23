import aiofiles
from .abstract import FilePlugin

class TextFile(FilePlugin):
    """
    A class to handle text files asynchronously.
    """
    def __init__(self, path: str, encoding: str = 'utf-8'):
        """
        Initialize the TextFile with a file path.

        Args:
            path: Path to the text file.
            encoding: File encoding (default: utf-8)
        """
        super().__init__()
        self.path = path
        self.encoding = encoding
        self._file = None

    async def open(self):
        """
        Asynchronously open the text file.
        """
        try:
            self._file = await aiofiles.open(self.path, mode='r', encoding=self.encoding)
            self.logger.debug(
                f"Successfully opened file: {self.path}"
            )
        except Exception as e:
            self.logger.error(f"Error opening file {self.path}: {str(e)}")
            raise

    async def close(self):
        """
        Asynchronously close the text file.
        """
        if self._file is not None:
            try:
                await self._file.close()
                self.logger.debug(f"Successfully closed file: {self.path}")
            except Exception as e:
                self.logger.error(f"Error closing file {self.path}: {str(e)}")
                raise
            finally:
                self._file = None

    async def read(self) -> str:
        """
        Asynchronously read the content of the text file.

        Returns:
            Content of the text file as a string.
        """
        if self._file is None:
            await self.open()

        try:
            content = await self._file.read()
            return content
        except Exception as e:
            self.logger.error(f"Error reading file {self.path}: {str(e)}")
            raise
