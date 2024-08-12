import asyncio
import aiohttp
from markdownify import MarkdownConverter
from bs4 import BeautifulSoup as bs
from langchain.text_splitter import MarkdownTextSplitter
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class WebBaseLoader(AbstractLoader):
    """Class to load web pages and extract text as Markdown."""
    def __init__(self, urls: dict, source_type: str = 'website', **kwargs):
        self.urls = urls
        self._source_type = source_type
        self.timeout: int = kwargs.pop('timeout', 60)
        self._wait: int = kwargs.pop('wait', 60)
        super().__init__(source_type=source_type, **kwargs)
        self.md_splitter = MarkdownTextSplitter(
            chunk_size = 1024,
            chunk_overlap=10
        )

    def md(self, soup, **options):
        return MarkdownConverter(**options).convert_soup(soup)

    async def _fetch(
        self, url: str, retries: int = 3, cooldown: int = 2, backoff: float = 1.5
    ) -> str:
        async with aiohttp.ClientSession() as session:
            for i in range(retries):
                try:
                    async with session.get(url, allow_redirects=True) as response:
                        if response.status == 200:
                            return await response.text()
                        elif response.status == 429:
                            # Too many requests
                            if i == retries - 1:
                                return ''
                            self.logger.warning(
                                f"Too many requests to {url}. Waiting {self._wait} seconds."
                            )
                            await asyncio.sleep(self._wait)
                        else:  # Other non-success status codes
                            response.raise_for_status()  # Raise for other errors
                except aiohttp.ClientConnectionError as e:
                    if i == retries - 1:
                        raise
                    else:
                        self.logger.warning(
                            f"Error fetching {url} with attempt "
                            f"{i + 1}/{retries}: {e}. Retrying..."
                        )
                        await asyncio.sleep(cooldown * backoff**i)
                except aiohttp.ClientResponseError as e:
                    self.logger.warning(
                        f"Request failed (ClientResponseError): {e}"
                    )
                    return ''
        self.logger.warning(f"Failed to fetch {url} after {retries} attempts.")
        return ''

    async def get_address(self, url: str) -> list:
        self.logger.info(
            f'Downloading URL {url}'
        )
        html = await self._fetch(url)
        docs = []
        if html:
            soup = bs(html, 'html.parser')
            md_text = self.md(soup)
            try:
                title = soup.title.string
            except AttributeError:
                title = None
            metadata = {
                "url": url,
                "source": url,
                "index": "",
                "filename": '',
                "type": 'webpage',
                "question": '',
                "answer": '',
                "source_type": self._source_type,
                "summary": "",
                "document_meta": {
                    "title": title,
                    "description": soup.find('meta', attrs={'name': 'description'})['content']
                    if soup.find('meta', attrs={'name': 'description'}) else '',
                    "keywords": soup.find('meta', attrs={'name': 'keywords'})['content']
                    if soup.find('meta', attrs={'name': 'keywords'}) else '',
                }
            }
            for chunk in self.md_splitter.split_text(md_text):
                docs.append(
                    Document(
                        page_content=chunk,
                        metadata=metadata
                    )
                )
        return docs

    async def load(self, **kwargs) -> list:
        documents = []
        if self.urls is None:
            return []
        for address in self.urls:
            docs = await self.get_address(address)
            documents.extend(docs)
        return self.split_documents(documents)

    def parse(self, source):
        pass
