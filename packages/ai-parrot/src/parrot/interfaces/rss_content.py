"""RSSContentInterface - RSS parsing with content extraction from linked pages."""
from typing import Any, Optional, Dict, List
import asyncio
import re
from bs4 import BeautifulSoup
from .rss import RSSInterface
from ..utils import cPrint


class RSSContentInterface(RSSInterface):
    """Extends RSSInterface to fetch and summarize content from linked pages."""

    # Content container selectors in priority order
    CONTENT_SELECTORS = [
        'main',
        'article',
        '[role="main"]',
        '.post-content',
        '.article-content',
        '.entry-content',
        '.content',
        '.post',
        '.article',
        '#content',
    ]

    async def read_rss_with_content(
        self,
        url: str,
        limit: int = 10,
        max_chars: int = 1000,
        output_format: str = 'dict',
        fetch_content: bool = True
    ) -> Any:
        """
        Read RSS feed and fetch content summaries from linked pages.

        :param url: URL of the RSS feed.
        :param limit: Maximum number of items to return.
        :param max_chars: Maximum characters for content summary (~1000 default).
        :param output_format: Output format ('dict', 'markdown', 'yaml').
        :param fetch_content: If False, skip content fetching (just RSS parsing).
        :return: Parsed feed with content summaries.
        """
        # First, get the RSS feed using parent method
        result = await self.read_rss(url=url, limit=limit, output_format='dict')

        if not result or not isinstance(result, dict):
            return result

        items = result.get('items', [])
        if not items or not fetch_content:
            return self._format_output(result, output_format)

        # Fetch content for each item concurrently
        tasks = []
        for item in items:
            link = item.get('link', '')
            if link:
                tasks.append(self._fetch_and_summarize(link, max_chars))
            else:
                tasks.append(asyncio.coroutine(lambda: '')())

        summaries = await asyncio.gather(*tasks, return_exceptions=True)

        # Add content_summary to each item
        for i, item in enumerate(items):
            summary = summaries[i] if i < len(summaries) else ''
            if isinstance(summary, Exception):
                cPrint(f"RSS Content: Error fetching {item.get('link')}: {summary}", level="WARNING")
                summary = ''
            item['content_summary'] = summary

        return self._format_output(result, output_format)

    async def _fetch_and_summarize(self, url: str, max_chars: int = 1000) -> str:
        """Fetch page and extract content summary."""
        try:
            html = await self._fetch_page_content(url)
            if not html:
                return ''
            return self._extract_main_content(html, max_chars)
        except Exception as e:
            cPrint(f"RSS Content: Failed to fetch {url}: {e}", level="DEBUG")
            return ''

    async def _fetch_page_content(self, url: str) -> Optional[str]:
        """Fetch page HTML via HTTP."""
        try:
            response, error = await self.async_request(
                url=url,
                method='GET',
                accept='text/html'
            )

            if error:
                cPrint(f"RSS Content: HTTP error for {url}: {error}", level="DEBUG")
                return None

            if not response:
                return None

            if isinstance(response, bytes):
                return response.decode('utf-8', errors='ignore')
            elif hasattr(response, 'text'):
                return response.text
            elif hasattr(response, 'get_text'):
                # BeautifulSoup object
                return str(response)
            else:
                return str(response)

        except Exception as e:
            cPrint(f"RSS Content: Exception fetching {url}: {e}", level="DEBUG")
            return None

    def _extract_main_content(self, html: str, max_chars: int = 1000) -> str:
        """Extract and summarize main content from HTML."""
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove noise elements
            for tag in soup(['script', 'style', 'nav', 'header', 'footer',
                            'aside', 'noscript', 'iframe', 'form']):
                tag.decompose()

            # Find main content container
            container = self._find_content_container(soup)

            if container:
                # Extract paragraphs from container
                paragraphs = container.find_all('p')
                text = self._extract_paragraphs(paragraphs, max_chars)
            else:
                # Fallback: get first paragraphs from body
                paragraphs = soup.find_all('p')
                text = self._extract_paragraphs(paragraphs, max_chars)

            return self._clean_and_summarize(text, max_chars)

        except Exception as e:
            cPrint(f"RSS Content: Parse error: {e}", level="DEBUG")
            return ''

    def _find_content_container(self, soup: BeautifulSoup) -> Optional[Any]:
        """Find the main content container element."""
        for selector in self.CONTENT_SELECTORS:
            container = soup.select_one(selector)
            if container:
                # Verify it has substantial content
                text = container.get_text(strip=True)
                if len(text) > 100:  # At least 100 chars
                    return container
        return None

    def _extract_paragraphs(self, paragraphs: List, max_chars: int) -> str:
        """Extract text from paragraphs up to max_chars."""
        collected = []
        total_len = 0

        for p in paragraphs:
            text = p.get_text(strip=True)
            # Skip short or empty paragraphs
            if len(text) < 20:
                continue
            # Skip common non-content paragraphs
            if self._is_boilerplate(text):
                continue

            collected.append(text)
            total_len += len(text)

            # Stop after we have enough content
            if total_len >= max_chars:
                break

        return ' '.join(collected)

    def _is_boilerplate(self, text: str) -> bool:
        """Check if text is likely boilerplate (ads, navigation, etc.)."""
        text_lower = text.lower()
        boilerplate_patterns = [
            'cookie', 'subscribe', 'newsletter', 'sign up', 'log in',
            'advertisement', 'sponsored', 'privacy policy', 'terms of service',
            'all rights reserved', 'copyright ©', 'follow us'
        ]
        return any(pattern in text_lower for pattern in boilerplate_patterns)

    def _clean_and_summarize(self, text: str, max_chars: int) -> str:
        """Clean text and limit to max_chars, ending at sentence boundary."""
        if not text:
            return ''

        # Normalize whitespace
        text = ' '.join(text.split())

        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)

        # Limit length
        if len(text) <= max_chars:
            return text.strip()

        # Try to cut at sentence boundary
        truncated = text[:max_chars]
        last_period = truncated.rfind('. ')
        last_question = truncated.rfind('? ')
        last_exclaim = truncated.rfind('! ')

        cut_point = max(last_period, last_question, last_exclaim)

        if cut_point > max_chars // 2:
            return truncated[:cut_point + 1].strip()
        else:
            # No good sentence boundary, cut at word boundary
            last_space = truncated.rfind(' ')
            if last_space > max_chars // 2:
                return truncated[:last_space].strip() + '...'
            return truncated.strip() + '...'

    def _format_output(self, data: Dict[str, Any], output_format: str) -> Any:
        """Format output based on requested format."""
        if output_format.lower() == 'markdown':
            return self._to_content_markdown(data)
        elif output_format.lower() == 'yaml':
            return self._to_yaml(data)
        return data

    def _to_content_markdown(self, data: Dict[str, Any]) -> str:
        """Convert feed data with content summaries to Markdown."""
        md = f"# {data.get('title', 'RSS Feed')}\n\n"
        md += f"Source: {data.get('url', '')}\n\n"

        for item in data.get('items', []):
            md += f"## [{item.get('title', 'No Title')}]({item.get('link', '')})\n"
            md += f"**Date:** {item.get('pubDate', '')}\n\n"

            summary = item.get('content_summary', '')
            if summary:
                md += f"{summary}\n\n"
            elif item.get('description'):
                desc = item['description']
                if isinstance(desc, dict):
                    desc = desc.get('#text', '')
                md += f"{str(desc)[:500]}...\n\n"

            md += "---\n\n"

        return md
