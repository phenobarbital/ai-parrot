from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from langchain.docstore.document import Document
from langchain.text_splitter import MarkdownTextSplitter
from navconfig.logging import logging
from .abstract import AbstractLoader


logging.getLogger(name='selenium.webdriver').setLevel(logging.WARNING)
logging.getLogger(name='WDM').setLevel(logging.WARNING)
logging.getLogger(name='matplotlib').setLevel(logging.WARNING)


class WebLoader(AbstractLoader):
    """Class to load web pages and extract text."""
    chrome_options = [
        "--headless",
        "--enable-automation",
        "--lang=en",
        "--disable-extensions",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-features=NetworkService",
        "--disable-dev-shm-usage",
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    ]
    def __init__(self, urls: dict, source_type: str = 'website', **kwargs):
        self.urls = urls
        self._source_type = source_type
        self._options = Options()
        self.timeout: int = kwargs.pop('timeout', 60)
        for option in self.chrome_options:
            self._options.add_argument(option)
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=self._options
        )
        self._mark_splitter = MarkdownTextSplitter(
            chunk_size = 1024,
            chunk_overlap=10
        )
        super().__init__(source_type=source_type, **kwargs)

    def md(self, soup, **options):
        return MarkdownConverter(**options).convert_soup(soup)

    def clean_html(self, html, tags, objects=[]):
        soup = BeautifulSoup(html, 'html.parser')
        page_title = soup.title.string
        md_text = self.md(soup)
        # Remove script and style elements
        for script_or_style in soup(["script", "style", "link"]):
            script_or_style.decompose()
        # Extract Content
        content = []
        paragraphs = [' '.join(p.get_text().split()) for p in soup.find_all(tags)]
        # Look for iframe elements and format their src attributes into readable strings
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            video_src = iframe.get('src', '')
            # You might want to customize the formatting of this string
            formatted_video = f"Video Link: {video_src}" if video_src else ""
            content.append(formatted_video)
        if objects:
            for obj in objects:
                (element, args), = obj.items()
                if 'parse_list' in args:
                    parse_list = args.pop('parse_list')
                    # Find the element container:
                    container = soup.find(element, attrs=args)
                    # Parse list of objects (UL, LI)
                    name_type = parse_list.pop('type')
                    params = parse_list.get('find')
                    el = params.pop(0)
                    try:
                        attrs = params.pop(0)
                    except IndexError:
                        attrs = {}
                    elements = container.find_all(el, attrs=attrs)
                    structured_text = ''
                    for element in elements:
                        title = element.find('span', class_='title').get_text(strip=True)
                        lists = element.find_all('ul')
                        if lists:
                            structured_text += f"\nCategory: {title}\n{name_type}:\n"
                        for ul in lists:
                            items = [f"- {li.get_text(strip=True)}" for li in ul.select('li')]
                            formatted_list = '\n'.join(items)
                            structured_text += formatted_list
                        structured_text += "\n"
                    content.append(structured_text)
                else:
                    elements = soup.find_all(element, attrs=args)
                    for element in elements:
                        # Handle <a> tags within the current element
                        links = element.find_all('a')
                        for link in links:
                            # Extract link text and href, format them into a readable string
                            link_text = link.get_text(strip=True)
                            href = link.get('href', '')
                            formatted_link = (
                                f"{link_text} (Link: {href})"
                                if href
                                else link_text
                            )
                            # Replace the original link text in the element
                            # with the formatted version
                            link.replace_with(formatted_link)
                        # work with UL lists:
                        lists = element.find_all('ul')
                        for ul in lists:
                            items = [li.get_text(strip=True) for li in ul.select('li')]
                            formatted_list = '\n'.join(items)
                            content.append(formatted_list)
                        cleaned_text = ' '.join(element.get_text().split())
                        content.append(cleaned_text)
        return (content + paragraphs, md_text, page_title)

    def get(self, address: dict) -> list:
        (url, args), = address.items()
        self.logger.info(
            f'Downloading URL {url} with args {args}'
        )
        locator = args.get('locator', (By.TAG_NAME, 'body'))
        wait = WebDriverWait(self.driver, self.timeout)
        acookies = args.get('accept_cookies', False)
        try:
            self.driver.get(url)
            # After loading page, accept cookies
            wait.until(
                EC.presence_of_element_located(
                    locator
                )
            )
            if acookies:
                btn = wait.until(
                    EC.element_to_be_clickable(
                        acookies
                    )
                )
                btn.click()
        except Exception as exc:
            print(f"Failed to Get {url}: {exc}")
            self.logger.exception(
                str(exc), stack_info=True
            )
            raise
        try:
            extract = args.get('tags', ['p', 'title', 'h1', 'h2', 'section', 'article'])
            objects = args.get('objects', [])
            source_type = args.get('source_type', self._source_type)
            html_content = self.driver.page_source
            content, md_text, page_title = self.clean_html(
                html_content,
                extract,
                objects
            )
            metadata = {
                "source": url,
                "index": page_title,
                "url": url,
                "filename": page_title,
                "question": '',
                "answer": '',
                "source_type": source_type,
                'type': 'webpage',
                'summary': '',
                "document_meta": {
                    "language": "en",
                    "title": page_title,
                },
            }
            docs = []
            if md_text:
                docs.append(
                    Document(
                        page_content=md_text,
                        metadata=metadata
                    )
                )
                # for chunk in self._mark_splitter.split_text(md_text):
                #     docs.append(
                #         Document(
                #             page_content=chunk,
                #             metadata=metadata
                #         )
                #     )
            if content:
                site_content = [
                    Document(
                        page_content=paragraph,
                        metadata=metadata
                    ) for paragraph in content
                ]
            return docs + site_content
        except Exception as exc:
            print(f"Failed to load {url}: {exc}")

    def load(self, **kwargs) -> list:
        documents = []
        for address in self.urls:
            docs = self.get(address)
            if docs:
                documents.extend(docs)
        self.driver.quit()
        return self.split_by_tokens(documents)

    def parse(self, source):
        pass
