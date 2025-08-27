import asyncio
import time
from typing import Union, List, Optional, Tuple, Dict, Any
from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from navconfig.logging import logging
from .abstract import AbstractLoader
from ..stores.models import Document


logging.getLogger(name='selenium.webdriver').setLevel(logging.WARNING)
logging.getLogger(name='WDM').setLevel(logging.WARNING)
logging.getLogger(name='matplotlib').setLevel(logging.WARNING)


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class WebDriverPool:
    """Async WebDriver pool for efficient browser management."""

    def __init__(self, max_drivers: int = 3, browser: str = "chrome", **driver_kwargs):
        self.max_drivers = max_drivers
        self.browser = browser.lower()
        self.driver_kwargs = driver_kwargs
        self.pool = asyncio.Queue(maxsize=max_drivers)
        self.active_drivers = set()
        self.lock = asyncio.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def get_driver(self) -> webdriver:
        """Get a driver from the pool or create a new one."""
        try:
            # Try to get an existing driver from the pool
            driver = self.pool.get_nowait()
            self.logger.debug("Reusing driver from pool")
            return driver
        except asyncio.QueueEmpty:
            # Pool is empty, create new driver if under limit
            async with self.lock:
                if len(self.active_drivers) < self.max_drivers:
                    driver = await asyncio.get_event_loop().run_in_executor(
                        None, self._create_driver
                    )
                    self.active_drivers.add(driver)
                    self.logger.debug(f"Created new driver. Active: {len(self.active_drivers)}")
                    return driver
                else:
                    # Wait for a driver to become available
                    self.logger.debug("Waiting for available driver")
                    return await self.pool.get()

    def _create_driver(self) -> webdriver:
        """Create a new WebDriver instance synchronously."""
        chrome_args = [
            "--headless=new",
            "--enable-automation",
            "--lang=en",
            "--disable-extensions",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]

        firefox_args = [
            "-headless",
        ]

        if self.browser == "firefox":
            options = FirefoxOptions()
            for arg in firefox_args:
                options.add_argument(arg)

            user_agent = self.driver_kwargs.get('user_agent')
            if user_agent:
                options.set_preference("general.useragent.override", user_agent)

            page_load_strategy = self.driver_kwargs.get('page_load_strategy', 'normal')
            caps = webdriver.DesiredCapabilities.FIREFOX.copy()
            caps["pageLoadStrategy"] = page_load_strategy

            service = FirefoxService(GeckoDriverManager().install())
            return webdriver.Firefox(service=service, options=options)

        else:  # Chrome
            options = ChromeOptions()
            for arg in chrome_args:
                options.add_argument(arg)

            user_agent = self.driver_kwargs.get('user_agent', DEFAULT_UA)
            if user_agent:
                options.add_argument(f"user-agent={user_agent}")

            page_load_strategy = self.driver_kwargs.get('page_load_strategy', 'normal')
            options.page_load_strategy = page_load_strategy

            service = ChromeService(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=options)

    async def return_driver(self, driver: webdriver):
        """Return a driver to the pool after cleaning it."""
        try:
            # Clean the driver (clear cookies, navigate to blank page, etc.)
            await asyncio.get_event_loop().run_in_executor(
                None, self._clean_driver, driver
            )

            # Return to pool
            await self.pool.put(driver)
            self.logger.debug("Returned cleaned driver to pool")
        except Exception as e:
            self.logger.error(f"Error returning driver to pool: {e}")
            await self._destroy_driver(driver)

    def _clean_driver(self, driver: webdriver):
        """Clean driver state synchronously."""
        try:
            driver.delete_all_cookies()
            driver.execute_script("window.localStorage.clear();")
            driver.execute_script("window.sessionStorage.clear();")
            driver.get("about:blank")
        except Exception as e:
            self.logger.warning(f"Error cleaning driver: {e}")

    async def _destroy_driver(self, driver: webdriver):
        """Destroy a driver and remove it from active set."""
        try:
            await asyncio.get_event_loop().run_in_executor(None, driver.quit)
        except Exception as e:
            self.logger.error(f"Error quitting driver: {e}")
        finally:
            async with self.lock:
                self.active_drivers.discard(driver)

    async def close_all(self):
        """Close all drivers in the pool."""
        async with self.lock:
            # Close drivers in pool
            while not self.pool.empty():
                try:
                    driver = await self.pool.get()
                    await self._destroy_driver(driver)
                except:
                    pass

            # Close active drivers
            destroy_tasks = [self._destroy_driver(driver) for driver in self.active_drivers.copy()]
            if destroy_tasks:
                await asyncio.gather(*destroy_tasks, return_exceptions=True)

            self.active_drivers.clear()
            self.logger.info("Closed all WebDriver instances")


class WebLoader(AbstractLoader):
    """Load web pages and extract HTML + Markdown + structured bits (videos/nav/tables)."""

    def __init__(
        self,
        source_type: str = 'website',
        *,
        browser: str = "chrome",
        timeout: int = 60,
        page_load_strategy: str = "normal",
        user_agent: Optional[str] = DEFAULT_UA,
        max_drivers: int = 3,
        driver_pool: Optional[WebDriverPool] = None,
        **kwargs
    ):
        super().__init__(source_type=source_type, **kwargs)

        self.timeout = timeout
        self.browser = browser.lower()
        self.page_load_strategy = page_load_strategy
        self.user_agent = user_agent
        self.max_drivers = max_drivers

        # Use provided pool or create our own
        if driver_pool:
            self.driver_pool = driver_pool
            self._own_pool = False
        else:
            self.driver_pool = WebDriverPool(
                max_drivers=max_drivers,
                browser=browser,
                page_load_strategy=page_load_strategy,
                user_agent=user_agent
            )
            self._own_pool = True

        self.driver = None

    async def open(self):
        """Initialize resources - called by AbstractLoader's __aenter__."""
        self.logger.debug("Opening WebLoader")
        # Driver pool is ready to use, no additional setup needed
        pass

    async def close(self):
        """Clean up resources - called by AbstractLoader's __aexit__."""
        self.logger.debug("Closing WebLoader")
        if self._own_pool and self.driver_pool:
            await self.driver_pool.close_all()

    def md(self, soup: BeautifulSoup, **options) -> str:
        """Convert BeautifulSoup to Markdown."""
        return MarkdownConverter(**options).convert_soup(soup)

    def _text(self, node: Any) -> str:
        """Extract text content from a node."""
        if node is None:
            return ""
        if isinstance(node, NavigableString):
            return str(node).strip()
        return node.get_text(" ", strip=True)

    def _collect_video_links(self, soup: BeautifulSoup) -> List[str]:
        """Extract video links from the page."""
        items: List[str] = []

        # iframes (YouTube/Vimeo/etc.)
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src")
            if not src:
                continue
            items.append(f"Video Link: {src}")

        # <video> and <source>
        for video in soup.find_all("video"):
            src = video.get("src")
            if src:
                items.append(f"Video Link: {src}")
            for source in video.find_all("source"):
                s = source.get("src")
                if s:
                    items.append(f"Video Source: {s}")

        # Deduplicate while preserving order
        seen = set()
        result = []
        for x in items:
            if x not in seen:
                result.append(x)
                seen.add(x)
        return result

    def _collect_navbars(self, soup: BeautifulSoup) -> List[str]:
        """Extract navigation menus as Markdown lists."""
        nav_texts: List[str] = []

        def nav_to_markdown(nav) -> str:
            lines = []
            blocks = nav.find_all(["ul", "ol"], recursive=True)
            if not blocks:
                # Fallback: collect links directly under nav
                for a in nav.find_all("a", href=True):
                    txt = self._text(a)
                    href = a.get("href", "")
                    if txt or href:
                        lines.append(f"- {txt} (Link: {href})" if href else f"- {txt}")
            else:
                for block in blocks:
                    for li in block.find_all("li", recursive=False):
                        a = li.find("a", href=True)
                        if a:
                            txt = self._text(a)
                            href = a.get("href", "")
                            lines.append(f"- {txt} (Link: {href})" if href else f"- {txt}")
                        else:
                            t = self._text(li)
                            if t:
                                lines.append(f"- {t}")

                        # nested lists
                        for sub in li.find_all(["ul", "ol"], recursive=False):
                            for sub_li in sub.find_all("li", recursive=False):
                                a2 = sub_li.find("a", href=True)
                                if a2:
                                    txt2 = self._text(a2)
                                    href2 = a2.get("href", "")
                                    lines.append(f"  - {txt2} (Link: {href2})" if href2 else f"  - {txt2}")
                                else:
                                    t2 = self._text(sub_li)
                                    if t2:
                                        lines.append(f"  - {t2}")
            return "\n".join(lines)

        # <nav> regions
        for nav in soup.find_all("nav"):
            md_list = nav_to_markdown(nav)
            if md_list.strip():
                nav_texts.append("Navigation:\n" + md_list)

        # Common menu containers if no <nav>
        if not nav_texts:
            candidates = soup.select("[role='navigation'], .navbar, .menu, .nav")
            for nav in candidates:
                md_list = nav_to_markdown(nav)
                if md_list.strip():
                    nav_texts.append("Navigation:\n" + md_list)

        return nav_texts

    def _table_to_markdown(self, table) -> str:
        """Convert a <table> to GitHub-flavored Markdown."""
        # Caption
        caption_el = table.find("caption")
        caption = self._text(caption_el) if caption_el else ""

        # Headers
        headers = []
        thead = table.find("thead")
        if thead:
            ths = thead.find_all("th")
            if ths:
                headers = [self._text(th) for th in ths]

        # If no thead, try first row as headers
        if not headers:
            first_row = table.find("tr")
            if first_row:
                cells = first_row.find_all(["th", "td"])
                headers = [self._text(c) for c in cells]

        # Rows
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td"])
            if not cells:
                continue
            rows.append([self._text(td) for td in cells])

        if not headers and rows:
            headers = [f"Col {i+1}" for i in range(len(rows[0]))]

        # Normalize column count
        ncol = len(headers)
        norm_rows = []
        for r in rows:
            if len(r) < ncol:
                r = r + [""] * (ncol - len(r))
            elif len(r) > ncol:
                r = r[:ncol]
            norm_rows.append(r)

        def esc(cell: str) -> str:
            return (cell or "").replace("|", "\\|").strip()

        md = []
        if caption:
            md.append(f"Table: {caption}\n")
        if headers:
            md.append("| " + " | ".join(esc(h) for h in headers) + " |")
            md.append("| " + " | ".join("---" for _ in headers) + " |")
        for r in norm_rows:
            md.append("| " + " | ".join(esc(c) for c in r) + " |")
        return "\n".join(md).strip()

    def _collect_tables(self, soup: BeautifulSoup, max_tables: int = 25) -> List[str]:
        """Extract tables as Markdown."""
        out = []
        for i, table in enumerate(soup.find_all("table")):
            if i >= max_tables:
                break
            try:
                out.append(self._table_to_markdown(table))
            except Exception:
                continue
        return out

    def _fetch_page_sync(self, driver: webdriver, url: str, args: dict) -> str:
        """Synchronously fetch page content using WebDriver."""
        # Waiting / cookie handling
        locator = args.get('locator', (By.TAG_NAME, 'body'))
        wait = WebDriverWait(driver, self.timeout)
        acookies = args.get('accept_cookies', False)
        sleep_after = args.get('sleep_after', 0)

        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located(locator))

            if acookies:
                try:
                    btn = wait.until(EC.element_to_be_clickable(acookies))
                    btn.click()
                except Exception:
                    pass
        except Exception as exc:
            self.logger.error(f"Failed to load {url}: {exc}")
            raise

        if sleep_after:
            time.sleep(float(sleep_after))

        return driver.page_source

    def clean_html(
        self,
        html: str,
        tags: List[str],
        objects: List[Dict[str, Dict[str, Any]]] = [],
        *,
        parse_videos: bool = True,
        parse_navs: bool = True,
        parse_tables: bool = True
    ) -> Tuple[List[str], str, str]:
        """Clean and extract content from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script/style/link early
        for el in soup(["script", "style", "link", "noscript"]):
            el.decompose()

        # Title
        page_title = ""
        try:
            if soup.title and soup.title.string:
                page_title = soup.title.string.strip()
            if not page_title:
                og = soup.find("meta", property="og:title")
                if og and og.get("content"):
                    page_title = og["content"].strip()
        except Exception:
            page_title = ""

        # Full-page Markdown
        md_text = self.md(soup)

        content: List[str] = []

        # Paragraphs/headers/sections
        for p in soup.find_all(tags):
            text = ' '.join(p.get_text(" ", strip=True).split())
            if text:
                content.append(text)

        # Videos
        if parse_videos:
            content.extend(self._collect_video_links(soup))

        # Navbars
        if parse_navs:
            content.extend(self._collect_navbars(soup))

        # Tables
        if parse_tables:
            content.extend(self._collect_tables(soup))

        # Custom objects (keeping existing behavior)
        if objects:
            for obj in objects:
                (element, args), = obj.items()
                if 'parse_list' in args:
                    parse_list = args.pop('parse_list')
                    container = soup.find(element, attrs=args)
                    if not container:
                        continue
                    name_type = parse_list.pop('type', 'List')
                    params = parse_list.get('find', [])
                    el = params[0] if params else 'ul'
                    attrs = params[1] if len(params) > 1 else {}
                    elements = container.find_all(el, attrs=attrs)
                    structured_text = ''
                    for element in elements:
                        title_el = element.find('span', class_='title')
                        title = title_el.get_text(strip=True) if title_el else ''
                        lists = element.find_all('ul')
                        if lists:
                            if title:
                                structured_text += f"\nCategory: {title}\n{name_type}:\n"
                            for ul in lists:
                                items = [f"- {li.get_text(strip=True)}" for li in ul.select('li')]
                                structured_text += '\n'.join(items)
                            structured_text += "\n"
                    if structured_text.strip():
                        content.append(structured_text.strip())
                else:
                    elements = soup.find_all(element, attrs=args)
                    for element in elements:
                        for link in element.find_all('a'):
                            link_text = link.get_text(strip=True)
                            href = link.get('href', '')
                            formatted = f"{link_text} (Link: {href})" if href else link_text
                            link.replace_with(formatted)

                        for ul in element.find_all('ul'):
                            items = [li.get_text(strip=True) for li in ul.select('li')]
                            if items:
                                content.append('\n'.join(items))

                        cleaned_text = ' '.join(element.get_text().split())
                        if cleaned_text:
                            content.append(cleaned_text)

        return (content, md_text, page_title)

    def _normalize_url_args(self, address, kwargs):
        """Normalize URL and arguments from different input formats."""
        if isinstance(address, str):
            url = address
            args = dict(kwargs) if kwargs else {}
            return url, args

        if isinstance(address, dict):
            (url, args), = address.items()
            args = dict(args or {})
            if kwargs:
                args.update(kwargs)
            return url, args

        raise TypeError(f"Unsupported address type for WebLoader: {type(address)}")

    async def _load(self, address: Union[str, dict], **kwargs) -> List[Document]:
        """Load a single web page."""
        url, args = self._normalize_url_args(address, kwargs)
        self.logger.info(f'Loading URL: {url}')

        # Get driver from pool
        driver = await self.driver_pool.get_driver()

        try:
            # Fetch page content in executor
            html_content = await asyncio.get_event_loop().run_in_executor(
                None, self._fetch_page_sync, driver, url, args
            )

            # Process content
            extract_tags = args.get('tags', ['p', 'title', 'h1', 'h2', 'section', 'article'])
            objects = args.get('objects', [])
            parse_videos = args.get('parse_videos', True)
            parse_navs = args.get('parse_navs', True)
            parse_tables = args.get('parse_tables', True)
            source_type = args.get('source_type', self._source_type)

            content, md_text, page_title = self.clean_html(
                html_content,
                extract_tags,
                objects,
                parse_videos=parse_videos,
                parse_navs=parse_navs,
                parse_tables=parse_tables
            )

            if not page_title:
                page_title = url

            metadata = {
                "source": url,
                "url": url,
                "filename": page_title,
                "source_type": source_type,
                "type": "webpage",
                "document_meta": {
                    "language": "en",
                    "title": page_title,
                },
            }

            docs: List[Document] = []
            if md_text:
                docs.append(
                    Document(
                        page_content=md_text,
                        metadata={**metadata, "content_kind": "markdown_full"}
                    )
                )

            for chunk in content:
                if chunk and isinstance(chunk, str):
                    docs.append(
                        Document(
                            page_content=chunk,
                            metadata={**metadata, "content_kind": "fragment"}
                        )
                    )

            return docs

        except Exception as exc:
            self.logger.error(f"Failed to load {url}: {exc}")
            raise
        finally:
            # Return driver to pool
            await self.driver_pool.return_driver(driver)
