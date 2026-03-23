from typing import Any, List, Optional, Dict
import asyncio
import xmltodict
import yaml
from .http import HTTPService
from ..utils import cPrint

class RSSInterface(HTTPService):
    """
    RSSInterface.

    Interface for reading and parsing RSS/Atom feeds.
    """

    async def read_rss(
        self,
        url: str,
        limit: int = 10,
        output_format: str = 'dict'
    ) -> Any:
        """
        Reads an RSS feed from a URL and returns parsed items.

        :param url: URL of the RSS feed.
        :param limit: Maximum number of items to return (default: 10).
        :param output_format: Output format ('dict', 'markdown', 'yaml').
        :return: Parsed feed items in the requested format.
        """
        try:
            # Fetch the feed content
            cPrint(f"RSS: Fetching feed from {url}", level="DEBUG")
            response, error = await self.async_request(
                url=url,
                method='GET',
                accept='application/rss+xml, application/atom+xml, application/xml, text/xml'
            )
            
            if error:
                cPrint(f"RSS Error fetching {url}: {error}", level="ERROR")
                return []

            if not response:
                return []

            # Parse XML content
            if isinstance(response, bytes):
                content = response.decode('utf-8', errors='ignore')
            elif hasattr(response, 'text'):
                 content = response.text
            else:
                 content = str(response)

            try:
                feed_data = xmltodict.parse(content)
            except Exception as e:
                cPrint(f"RSS: Error parsing XML from {url}: {e}", level="ERROR")
                return []

            # Extract items (handle RSS vs Atom)
            items = []
            feed_title = "Unknown Feed"
            
            # RSS 2.0 / 0.9x
            if 'rss' in feed_data and 'channel' in feed_data['rss']:
                channel = feed_data['rss']['channel']
                feed_title = channel.get('title', feed_title)
                items_raw = channel.get('item', [])
            # Atom
            elif 'feed' in feed_data:
                feed = feed_data['feed']
                feed_title = feed.get('title', feed_title)
                items_raw = feed.get('entry', [])
            # RDF (RSS 1.0)
            elif 'rdf:RDF' in feed_data:
                channel = feed_data['rdf:RDF']
                # RSS 1.0 often puts items outside channel or in a weird structure, 
                # but let's try standard 'item' lookups if xmltodict flattened it
                items_raw = channel.get('item', [])
                if not items_raw and 'channel' in channel:
                     feed_title = channel['channel'].get('title', feed_title)
            else:
                cPrint(f"RSS: unrecognized feed format for {url}", level="WARNING")
                items_raw = []

            # Ensure items_raw is a list (xmltodict returns dict for single item)
            if isinstance(items_raw, dict):
                items_raw = [items_raw]
            
            # Slice to limit
            items_raw = items_raw[:limit]

            # Normalize items
            for item in items_raw:
                normalized_item = self._normalize_item(item)
                items.append(normalized_item)

            result = {
                "title": feed_title,
                "url": url,
                "items": items
            }

            # Format output
            if output_format.lower() == 'markdown':
                return self._to_markdown(result)
            elif output_format.lower() == 'yaml':
                return self._to_yaml(result)
            else:
                return result

        except Exception as e:
            cPrint(f"RSS Error: {e}", level="ERROR")
            return []

    def _normalize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Prioritizes standard RSS/Atom fields."""
        return {
            "title": item.get('title', 'No Title'),
            "link": self._get_link(item),
            "description": item.get('description') or item.get('summary') or item.get('content', ''),
            "pubDate": item.get('pubDate') or item.get('published') or item.get('updated', ''),
            "guid": item.get('guid', {}).get('#text') if isinstance(item.get('guid'), dict) else item.get('guid') or item.get('id'),
        }

    def _get_link(self, item: Dict[str, Any]) -> str:
        """Extracts link from RSS or Atom item."""
        link = item.get('link')
        if isinstance(link, list):
            # Atom often has multiple links; prefer rel='alternate' or first
            for l in link:
                if isinstance(l, dict) and l.get('@rel') == 'alternate':
                    return l.get('@href', '')
            # Fallback to first text or href
            return link[0].get('@href', '') if isinstance(link[0], dict) else str(link[0])
        elif isinstance(link, dict):
             return link.get('@href', '') or link.get('#text', '')
        return str(link) if link else ''

    def _to_yaml(self, data: Dict[str, Any]) -> str:
        """Converts feed data to YAML."""
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)

    def _to_markdown(self, data: Dict[str, Any]) -> str:
        """Converts feed data to Markdown."""
        md = f"# {data['title']}\n\n"
        md += f"Source: {data['url']}\n\n"
        
        for item in data['items']:
            md += f"## [{item['title']}]({item['link']})\n"
            md += f"**Date:** {item['pubDate']}\n\n"
            
            desc = item['description']
            if isinstance(desc, dict):
                 desc = desc.get('#text', '')
            
            # Simple content cleaning/truncation could go here if needed
            if desc:
                 md += f"{str(desc)[:500]}...\n\n" # Truncate long descriptions
            
            md += "---\n\n"
        return md
