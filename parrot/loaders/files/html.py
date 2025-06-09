from bs4 import BeautifulSoup
from .text import TextFile

class HTMLFile(TextFile):
    """
    A class to handle HTML files asynchronously.
    """
    async def read(self) -> str:
        """
        Asynchronously read the content of the html file.

        Returns:
            BeautifulSoup object of HTML File.
        """
        if self._file is None:
            await self.open()

        try:
            content = await self._file.read()
            soup = BeautifulSoup(content, 'html.parser')
            return soup, content
        except Exception as e:
            self.logger.error(
                f"Error reading HTML file {self.path}: {str(e)}"
            )
            raise
