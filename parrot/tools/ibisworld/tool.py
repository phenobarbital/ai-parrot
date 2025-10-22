"""
IBISWorld Tool for AI-Parrot
Search and extract content from IBISWorld industry research articles.
"""
from typing import Dict, Any
from pathlib import Path
import tempfile
import aiohttp
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from markitdown import MarkItDown
from ..google.tools import GoogleSiteSearchTool, GoogleSiteSearchArgs
from ..abstract import AbstractTool


class IBISWorldSearchArgs(BaseModel):
    """Arguments schema for IBISWorld Search Tool."""
    query: str = Field(description="Search query for IBISWorld content")
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of results to return"
    )
    extract_content: bool = Field(
        default=True,
        description="If True, extract full article content from each result"
    )
    include_tables: bool = Field(
        default=True,
        description="If True, include tables and structured data from articles"
    )


class IBISWorldTool(GoogleSiteSearchTool):
    """
    IBISWorld search and content extraction tool.

    Searches within ibisworld.com and extracts industry research content,
    including article text, statistics, and tables.
    """

    name = "ibisworld_search"
    description = "Search IBISWorld industry research and extract detailed content from articles"
    args_schema = IBISWorldSearchArgs

    # IBISWorld specific configuration
    IBISWORLD_DOMAIN = "ibisworld.com"

    async def _extract_article_content(
        self,
        url: str,
        include_tables: bool = True
    ) -> Dict[str, Any]:
        """
        Extract content from an IBISWorld article.

        Args:
            url: Article URL
            include_tables: Whether to extract table data

        Returns:
            Dictionary containing extracted content
        """
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                             '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            }

            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return {
                            'error': f'HTTP {response.status}',
                            'content': None
                        }

                    # Check if content is a PDF
                    content_type = response.headers.get('Content-Type', '').lower()
                    is_pdf = url.lower().endswith('.pdf') or 'application/pdf' in content_type

                    if is_pdf:
                        # Handle PDF content using markitdown
                        try:
                            # Download PDF content to a temporary file
                            pdf_content = await response.read()
                            with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as tmp_file:
                                tmp_file.write(pdf_content)
                                tmp_file_path = tmp_file.name

                            # Extract content using markitdown
                            markitdown = MarkItDown()
                            result = markitdown.convert(tmp_file_path)

                            # Clean up temporary file
                            Path(tmp_file_path).unlink(missing_ok=True)

                            # Return PDF content in a structured format
                            content_data = {
                                'url': url,
                                'title': self._extract_pdf_title(url),
                                'content': result.text_content if result.text_content else "PDF content could not be extracted",
                                'metadata': {'content_type': 'application/pdf', 'source': 'markitdown'},
                                'statistics': {},
                                'tables': []
                            }

                            return content_data

                        except Exception as pdf_error:
                            self.logger.error(f"Error extracting PDF content from {url}: {pdf_error}")
                            return {
                                'error': f'PDF extraction error: {str(pdf_error)}',
                                'content': None
                            }
                    else:
                        # Handle regular HTML content
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        # Extract article content
                        content_data = {
                            'url': url,
                            'title': self._extract_title(soup),
                            'content': self._extract_main_content(soup),
                            'metadata': self._extract_metadata(soup),
                        }

                        if include_tables:
                            content_data['tables'] = self._extract_tables(soup)

                        # Extract key statistics if available
                        content_data['statistics'] = self._extract_statistics(soup)

                        return content_data

        except Exception as e:
            self.logger.error(f"Error extracting content from {url}: {e}")
            return {
                'error': str(e),
                'content': None
            }

    def _extract_pdf_title(self, url: str) -> str:
        """Extract title from PDF URL."""
        # Get the filename from the URL
        filename = url.split('/')[-1]
        # Remove .pdf extension and convert hyphens/underscores to spaces
        title = filename.replace('.pdf', '').replace('-', ' ').replace('_', ' ')
        # Capitalize words
        return title.title()

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title."""
        # Try multiple title selectors
        title_selectors = [
            ('h1', {'class': 'article-title'}),
            ('h1', {'class': 'report-title'}),
            ('h1', {}),
            ('title', {}),
        ]

        for tag, attrs in title_selectors:
            title_elem = soup.find(tag, attrs)
            if title_elem:
                return title_elem.get_text(strip=True)

        return "Title not found"

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """Extract main article content."""
        # Common content container selectors for IBISWorld
        content_selectors = [
            {'class': 'article-content'},
            {'class': 'report-content'},
            {'class': 'industry-report'},
            {'class': 'main-content'},
            {'id': 'content'},
            {'class': 'content'},
        ]

        content_parts = []

        # Try to find main content container
        for selector in content_selectors:
            content_elem = soup.find('div', selector) or soup.find('article', selector)
            if content_elem:
                # Extract text from paragraphs
                paragraphs = content_elem.find_all('p')
                content_parts.extend([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])

                # Extract text from sections
                sections = content_elem.find_all(['section', 'div'], class_=lambda x: x and 'section' in x.lower())
                for section in sections:
                    section_text = section.get_text(strip=True)
                    if section_text and section_text not in content_parts:
                        content_parts.append(section_text)

        # If no content found with selectors, try to get all paragraphs
        if not content_parts:
            all_paragraphs = soup.find_all('p')
            content_parts = [p.get_text(strip=True) for p in all_paragraphs if len(p.get_text(strip=True)) > 50]

        return '\n\n'.join(content_parts) if content_parts else "Content not found"

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract metadata from the article."""
        metadata = {}

        # Extract meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name') or meta.get('property')
            content = meta.get('content')
            if name and content:
                metadata[name] = content

        # Extract publication date
        date_selectors = [
            {'class': 'publish-date'},
            {'class': 'article-date'},
            {'itemprop': 'datePublished'},
        ]

        for selector in date_selectors:
            date_elem = soup.find(['time', 'span', 'div'], selector)
            if date_elem:
                metadata['publication_date'] = date_elem.get_text(strip=True)
                break

        # Extract author if available
        author_elem = soup.find(['span', 'div'], class_=lambda x: x and 'author' in x.lower())
        if author_elem:
            metadata['author'] = author_elem.get_text(strip=True)

        return metadata

    def _extract_tables(self, soup: BeautifulSoup) -> list:
        """Extract tables from the article."""
        tables_data = []
        tables = soup.find_all('table')

        for idx, table in enumerate(tables):
            table_data = {
                'table_id': idx + 1,
                'headers': [],
                'rows': []
            }

            # Extract headers
            headers = table.find_all('th')
            table_data['headers'] = [th.get_text(strip=True) for th in headers]

            # Extract rows
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if cells:
                    row_data = [cell.get_text(strip=True) for cell in cells]
                    table_data['rows'].append(row_data)

            if table_data['rows']:  # Only add if there's data
                tables_data.append(table_data)

        return tables_data

    def _extract_statistics(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract key statistics and figures."""
        statistics = {}

        # Look for statistics containers
        stat_selectors = [
            {'class': 'statistics'},
            {'class': 'key-stats'},
            {'class': 'industry-stats'},
            {'class': 'highlights'},
        ]

        for selector in stat_selectors:
            stat_container = soup.find('div', selector)
            if stat_container:
                # Extract key-value pairs
                stat_items = stat_container.find_all(['dt', 'dd', 'li'])
                for item in stat_items:
                    text = item.get_text(strip=True)
                    if ':' in text:
                        key, value = text.split(':', 1)
                        statistics[key.strip()] = value.strip()

        # Look for numeric data in spans or divs with specific classes
        numeric_elements = soup.find_all(['span', 'div'], class_=lambda x: x and any(
            term in x.lower() for term in ['stat', 'metric', 'value', 'number']
        ))

        for elem in numeric_elements:
            text = elem.get_text(strip=True)
            if text and any(char.isdigit() for char in text):
                # Try to find associated label
                label = elem.find_previous(['label', 'span', 'div'])
                if label:
                    label_text = label.get_text(strip=True)
                    if label_text and label_text != text:
                        statistics[label_text] = text

        return statistics

    async def _execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute IBISWorld search and content extraction.

        Args:
            query: Search query
            max_results: Maximum number of results
            extract_content: Whether to extract full content
            include_tables: Whether to extract tables

        Returns:
            Search results with extracted content
        """
        query = kwargs['query']
        max_results = kwargs['max_results']
        extract_content = kwargs.get('extract_content', True)
        include_tables = kwargs.get('include_tables', True)

        self.logger.info(f"Searching IBISWorld for: {query}")

        # Use parent class to perform site search
        search_kwargs = {
            'query': query,
            'site': self.IBISWORLD_DOMAIN,
            'max_results': max_results,
            'preview': False,  # We'll do our own content extraction
            'preview_method': 'aiohttp'
        }

        # Get search results from Google Site Search
        search_results = await super()._execute(**search_kwargs)

        # Extract content from each result if requested
        if extract_content:
            self.logger.info(f"Extracting content from {len(search_results['results'])} results")

            for result in search_results['results']:
                url = result['link']
                self.logger.info(f"Extracting content from: {url}")

                content_data = await self._extract_article_content(
                    url,
                    include_tables=include_tables
                )

                # Add extracted content to result
                result['extracted_content'] = content_data
                result['has_content'] = content_data.get('content') is not None

        # Add IBISWorld-specific metadata to response
        search_results['source'] = 'IBISWorld'
        search_results['domain'] = self.IBISWORLD_DOMAIN
        search_results['content_extracted'] = extract_content

        return search_results


__all__ = ['IBISWorldTool', 'IBISWorldSearchArgs']
