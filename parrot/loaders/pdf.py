from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any
from io import BytesIO
import fitz
import pytesseract
from PIL import Image
from langchain.docstore.document import Document
from .basepdf import BasePDF


class PDFLoader(BasePDF):
    """
    Loader for PDF files.
    """
    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'pdf',
        language: str = "eng",
        **kwargs
    ):
        super().__init__(
            path=path,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            language=language,
            **kwargs
        )
        self.parse_images = kwargs.get('parse_images', False)
        # Table Settings:
        self.table_settings = {
            #"vertical_strategy": "text",
            # "horizontal_strategy": "text",
            "intersection_x_tolerance": 3,
            "intersection_y_tolerance": 3
        }
        table_settings = kwargs.get('table_setttings', {})
        if table_settings:
            self.table_settings.update(table_settings)

    def _load_pdf(self, path: Path) -> list:
        """
        Load a PDF file using the Fitz library.

        Args:
            path (Path): The path to the PDF file.

        Returns:
            list: A list of Langchain Documents.
        """
        if self._check_path(path):
            self.logger.info(f"Loading PDF file: {path}")
            pdf = fitz.open(str(path))  # Open the PDF file
            docs = []
            for page_number in range(pdf.page_count):
                page = pdf[page_number]
                text = page.get_text()
                # first: text
                if text:
                    page_num = page_number + 1
                    try:
                        summary = self.get_summary_from_text(text)
                    except Exception:
                        summary = ''
                    metadata = {
                        "url": '',
                        "source": f"{path.name} Page.#{page_num}",
                        "filename": path.name,
                        "index": f"{page_num}",
                        "type": 'pdf',
                        "question": '',
                        "answer": '',
                        "source_type": self._source_type,
                        "data": {},
                        "summary": summary,
                        "document_meta": {
                            "title": pdf.metadata.get("title", ""),
                            # "subject": pdf.metadata.get("subject", ""),
                            # "keywords": pdf.metadata.get("keywords", ""),
                            "creationDate": pdf.metadata.get("creationDate", ""),
                            # "modDate": pdf.metadata.get("modDate", ""),
                            # "producer": pdf.metadata.get("producer", ""),
                            # "creator": pdf.metadata.get("creator", ""),
                            "author": pdf.metadata.get("author", ""),
                        }
                    }
                    docs.append(
                        Document(
                            page_content=text,
                            metadata=metadata
                        )
                    )
                # Extract images and use OCR to get text from each image
                # second: images
                if self.parse_images is True:
                    image_list = page.get_images(full=True)
                    file_name = path.stem.replace(' ', '_').replace('.', '').lower()
                    for img_index, img in enumerate(image_list):
                        xref = img[0]
                        base_image = pdf.extract_image(xref)
                        image = Image.open(BytesIO(base_image["image"]))
                        url = ''
                        if self.save_images is True:
                            img_name = f'image_{file_name}_{page_num}_{img_index}.png'
                            img_path = self._imgdir.joinpath(img_name)
                            self.logger.notice(
                                f"Saving Image Page on {img_path}"
                            )
                            try:
                                image.save(
                                    img_path,
                                    format="png",
                                    optimize=True
                                )
                                url = f'/static/images/{img_name}'
                            except OSError:
                                pass
                        # Use Tesseract to extract text from image
                        image_text = pytesseract.image_to_string(
                            image,
                            lang=self._lang
                        )
                        # TODO: add the summary (explanation)
                        # Create a document for each image
                        image_meta = {
                            "url": url,
                            "source": f"{path.name} Page.#{page_num}",
                            "filename": path.name,
                            "index": f"{path.name}:{page_num}",
                            "question": '',
                            "answer": '',
                            "type": 'image',
                            "data": {},
                            "summary": '',
                            "document_meta": {
                                "image_index": img_index,
                                "image_name": img_name,
                                "description": f"Extracted from {page_number}."
                            },
                            "source_type": self._source_type
                        }
                        docs.append(
                            Document(page_content=image_text, metadata=image_meta)
                        )
                # third: tables
                # Look for tables on this page and display the table count
                try:
                    tabs = page.find_tables()
                    for tab_idx, tab in enumerate(tabs):
                        # iterating over all tables in page:
                        df = tab.to_pandas()  # convert to pandas DataFrame
                        # converting to markdown, but after pre-processing pandas
                        df = df.dropna(axis=1, how='all')
                        df = df.dropna(how='all', axis=0)  # Drop empty rows
                        table_meta = {
                            "url": '',
                            "source": f"{path.name} Page.#{page_num} Table.#{tab_idx}",
                            "filename": path.name,
                            "index": f"{path.name}:{page_num}",
                            "question": '',
                            "answer": '',
                            "type": 'table',
                            "data": {},
                            "summary": '',
                            "document_meta": {
                                "table_index": tab_idx,
                                "table_shape": df.shape,
                                "table_columns": df.columns.tolist(),
                                "description": f"Extracted from {page_number}."
                            },
                            "source_type": self._source_type
                        }
                        txt = df.to_markdown()
                        if txt:
                            docs.append(
                                Document(page_content=txt, metadata=table_meta)
                            )
                except Exception as exc:
                    print(exc)
            pdf.close()
            return docs
        else:
            return []
