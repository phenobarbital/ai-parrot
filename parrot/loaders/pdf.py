from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any
from io import BytesIO
import re
import ftfy
import fitz
import pytesseract
from pytesseract import Output
from paddleocr import PaddleOCR
import torch
import cv2
from transformers import (
    # DonutProcessor,
    # VisionEncoderDecoderModel,
    # VisionEncoderDecoderConfig,
    # ViTImageProcessor,
    # AutoTokenizer,
    LayoutLMv3FeatureExtractor,
    LayoutLMv3TokenizerFast,
    LayoutLMv3ForTokenClassification,
    LayoutLMv3Processor
)
from pdf4llm import to_markdown
from PIL import Image
from langchain.docstore.document import Document
from navconfig.logging import logging
from .basepdf import BasePDF


logging.getLogger(name='ppocr').setLevel(logging.INFO)

# Function to rescale bounding boxes
def rescale_bounding_boxes(bboxes, image_width, image_height, target_size=1000):
    """Rescale bounding boxes to fit within the target size for LayoutLMv3."""
    rescaled_bboxes = []
    for bbox in bboxes:
        x1, y1 = bbox[0]
        x2, y2 = bbox[2]
        # Rescale based on the image dimensions
        rescaled_bbox = [
            int(x1 / image_width * target_size),
            int(y1 / image_height * target_size),
            int(x2 / image_width * target_size),
            int(y2 / image_height * target_size)
        ]
        rescaled_bboxes.append(rescaled_bbox)
    return rescaled_bboxes


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
        self.page_as_images = kwargs.get('page_as_images', False)
        if self.page_as_images is True:
            # Load the processor and model from Hugging Face
            # self.feature_extractor = LayoutLMv3FeatureExtractor(apply_ocr=False)
            # self.image_tokenizer = LayoutLMv3TokenizerFast.from_pretrained(
            #     "microsoft/layoutlmv3-base"
            # )
            # self.image_processor = LayoutLMv3Processor(
            #     self.feature_extractor,
            #     self.image_tokenizer
            # )
            self.image_processor = LayoutLMv3Processor.from_pretrained(
                "microsoft/layoutlmv3-base",
                apply_ocr=False
            )
            # LayoutLMv3ForSequenceClassification.from_pretrained
            self.image_model = LayoutLMv3ForTokenClassification.from_pretrained(
                "microsoft/layoutlmv3-base"
                # "HYPJUDY/layoutlmv3-base-finetuned-funsd"
            )
            # Set device to GPU if available
            self.image_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.image_model.to(self.image_device)

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

    # def explain_image(self, image_path):
    #     """Function to explain the image."""
    #     # with open(image_path, "rb") as image_file:
    #     #     image_content = image_file.read()

    #     # Open the image
    #     image = cv2.imread(image_path)
    #     task_prompt = "<s_docvqa><s_question>{user_input}</s_question><s_answer>"
    #     question = "Extract Questions about Happily Greet"
    #     prompt = task_prompt.replace("{user_input}", question)

    #     decoder_input_ids = self.image_processor.tokenizer(
    #         prompt,
    #         add_special_tokens=False,
    #         return_tensors="pt",
    #     ).input_ids

    #     pixel_values = self.image_processor(
    #         image,
    #         return_tensors="pt"
    #     ).pixel_values

    #     # Send inputs to the appropriate device
    #     pixel_values = pixel_values.to(self.image_device)
    #     decoder_input_ids = decoder_input_ids.to(self.image_device)

    #     outputs = self.image_model.generate(
    #         pixel_values,
    #         decoder_input_ids=decoder_input_ids,
    #         max_length=self.image_model.decoder.config.max_position_embeddings,
    #         pad_token_id=self.image_processor.tokenizer.pad_token_id,
    #         eos_token_id=self.image_processor.tokenizer.eos_token_id,
    #         bad_words_ids=[[self.image_processor.tokenizer.unk_token_id]],
    #         # use_cache=True
    #         return_dict_in_generate=True,
    #     )

    #     sequence = self.image_processor.batch_decode(outputs.sequences)[0]


    #     sequence = sequence.replace(
    #         self.image_processor.tokenizer.eos_token, ""
    #     ).replace(
    #         self.image_processor.tokenizer.pad_token, ""
    #     )
    #     # remove first task start token
    #     sequence = re.sub(r"<.*?>", "", sequence, count=1).strip()
    #     # Print the extracted sequence
    #     print("Extracted Text:", sequence)

    #     print(self.image_processor.token2json(sequence))

    #     # Format the output as Markdown (optional step)
    #     markdown_text = self.format_as_markdown(sequence)
    #     print("Markdown Format:\n", markdown_text)

    #     return None

    def convert_to_markdown(self, text):
        """
        Convert the cleaned text into a markdown format.
        You can enhance this function to detect tables, headings, etc.
        """
        # For example, we can identify sections or headers and format them in Markdown
        markdown_text = text
        # Detect headings and bold them
        markdown_text = re.sub(r"(^.*Scorecard.*$)", r"## \1", markdown_text)
        # Convert lines with ":" to a list item (rough approach)
        # markdown_text = re.sub(r"(\w+):", r"- **\1**:", markdown_text)
        # Return the markdown formatted text
        return markdown_text

    def clean_tokenized_text(self, tokenized_text):
        """
        Clean the tokenized text by fixing encoding issues and formatting, preserving line breaks.
        """
        # Fix encoding issues using ftfy
        cleaned_text = ftfy.fix_text(tokenized_text)

        # Remove <s> and </s> tags (special tokens)
        cleaned_text = cleaned_text.replace("<s>", "").replace("</s>", "")

        # Replace special characters like 'Ġ' and fix multiple spaces, preserving new lines
        cleaned_text = cleaned_text.replace("Ġ", " ")

        # Avoid collapsing line breaks, but still normalize multiple spaces
        # Replace multiple spaces with a single space, but preserve line breaks
        cleaned_text = re.sub(r" +", " ", cleaned_text)

        return cleaned_text.strip()

    def create_bounding_box(self, bbox_data):
        xs = []
        ys = []
        for x, y in bbox_data:
            xs.append(x)
            ys.append(y)

        left = int(min(xs))
        top = int(min(ys))
        right = int(max(xs))
        bottom = int(max(ys))

        return [left, top, right, bottom]

    def extract_page_text(self, image_path) -> str:
        # Open the image
        image = Image.open(image_path).convert("RGB")
        image_width, image_height = image.size

        # Initialize PaddleOCR with English language
        ocr = PaddleOCR(use_angle_cls=True, lang='en')
        ocr_result = ocr.ocr(str(image_path), cls=True)

        # Collect the text and bounding boxes
        text_with_boxes = []
        for line in ocr_result[0]:
            text = line[1][0]  # Extract the text
            bbox = line[0]     # Extract the bounding box
            text_with_boxes.append((text, bbox))

        # Step 2: Sort text based on y-coordinate (top-down order)
        def average_y(bbox):
            return sum([point[1] for point in bbox]) / len(bbox)

        text_with_boxes.sort(key=lambda x: average_y(x[1]))

        # Insert line breaks based on y-coordinate differences
        words_with_newlines = []
        last_y = None
        threshold = 20  # You can adjust this value based on the document's layout

        for _, (word, bbox) in enumerate(text_with_boxes):
            current_y = average_y(bbox)
            if last_y is not None and current_y - last_y > threshold:
                words_with_newlines.append("\n")  # Insert a line break
            words_with_newlines.append(word)
            last_y = current_y

        # # Step 3: Extract words and bounding boxes after sorting
        # words = [item[0] for item in text_with_boxes]
        # bounding_boxes = [item[1] for item in text_with_boxes]

        # # Step 4: Rescale bounding boxes to the 0-1000 range for LayoutLMv3
        # boxes = rescale_bounding_boxes(
        #     bounding_boxes,
        #     image_width,
        #     image_height
        # )

        # # Print extracted text and bounding boxes
        # # for word, bbox in zip(words, boxes):
        # #    print(f"Word: {word}, Bounding Box: {bbox}")

        # # Processor handles the OCR internally, no need for words or boxes
        # encoded_inputs = self.image_processor(image, words, boxes=boxes, return_tensors="pt")
        # outputs = self.image_model(**encoded_inputs)

        # Step 7: Join the sorted words into a paragraph
        paragraph = " ".join(words_with_newlines)

        cleaned_text = self.clean_tokenized_text(paragraph)
        markdown_text = self.convert_to_markdown(cleaned_text)
        return markdown_text

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
            try:
                md_text = to_markdown(pdf) # get markdown for all pages
                try:
                    summary_document = self.get_summary_from_text(md_text)
                except Exception:
                    summary_document = ''
                _meta = {
                    "url": f'{path}',
                    "source": f"{path.name}",
                    "filename": path.name,
                    "type": 'pdf',
                    "question": '',
                    "answer": '',
                    "source_type": self._source_type,
                    "data": {},
                    "summary": '-',
                    "document_meta": {
                        "title": pdf.metadata.get("title", ""),  # pylint: disable=E1101
                        "creationDate": pdf.metadata.get("creationDate", ""),  # pylint: disable=E1101
                        "author": pdf.metadata.get("author", ""),  # pylint: disable=E1101
                    }
                }
                docs.append(
                    Document(
                        page_content=md_text,
                        metadata=_meta
                    )
                )
                if summary_document:
                    summary_document = f"**Summary**\n{path.name}\n" + summary_document
                    docs.append(
                        Document(
                            page_content=summary_document,
                            metadata=_meta
                        )
                    )
            except Exception:
                pass
            for page_number in range(pdf.page_count):
                page = pdf[page_number]
                text = page.get_text()
                # first: text
                if text:
                    page_num = page_number + 1
                    try:
                        summary = self.get_summary_from_text(text)
                    except Exception:
                        summary = '-'
                    metadata = {
                        "url": f"{path}:#{page_num}",
                        "source": f"{path.name} Page.#{page_num}",
                        "filename": path.name,
                        # "index": f"{page_num}",
                        "type": 'pdf',
                        "question": '',
                        "answer": '',
                        "source_type": self._source_type,
                        "data": {},
                        "summary": '',
                        "document_meta": {
                            "title": pdf.metadata.get("title", ""),  # pylint: disable=E1101
                            "author": pdf.metadata.get("author", ""),  # pylint: disable=E1101
                        }
                    }
                    docs.append(
                        Document(
                            page_content=text,
                            metadata=metadata
                        )
                    )
                    # And Summary Document:
                    if summary:
                        sm = f"**Summary**\n{path.name} Page.#{page_num}\n" + summary
                        docs.append(
                            Document(
                                page_content=sm,
                                metadata=metadata
                            )
                        )
                # Extract images and use OCR to get text from each image
                # second: images
                file_name = path.stem.replace(' ', '_').replace('.', '').lower()
                if self.parse_images is True:
                    # extract any images in page:
                    image_list = page.get_images(full=True)
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
                            # "index": f"{path.name}:{page_num}",
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
                            "url": f"{path.name} Page.#{page_num} Table.#{tab_idx}",
                            "source": f"{path.name} Page.#{page_num} Table.#{tab_idx}",
                            "filename": path.name,
                            # "index": f"{path.name}:{page_num}",
                            "question": '',
                            "answer": '',
                            "type": 'table',
                            "data": {},
                            "summary": '-',
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
                # fourth: page as image
                if self.page_as_images is True:
                    # Convert the page to a Pixmap (which is an image)
                    mat = fitz.Matrix(2, 2)
                    pix = page.get_pixmap(dpi=600, matrix=mat) # Increase DPI for better resolution
                    img_name = f'{file_name}_page_{page_num}.png'
                    img_path = self._imgdir.joinpath(img_name)
                    print('IMAGE > ', img_path)
                    if img_path.exists():
                        img_path.unlink(missing_ok=True)
                    self.logger.notice(
                        f"Saving Page {page_number} as Image on {img_path}"
                    )
                    pix.save(
                        img_path
                    )
                    # TODO passing the image to a AI visual to get explanation
                    # Get the extracted text from the image
                    text = self.extract_page_text(img_path)
                    # print('TEXT EXTRACTED >> ', text)
                    url = f'/static/images/{img_name}'
                    image_meta = {
                        "url": url,
                        "source": f"{path.name} Page.#{page_num}",
                        "filename": path.name,
                        # "index": f"{path.name}:{page_num}",
                        "question": '',
                        "answer": '',
                        "type": 'page',
                        "data": {},
                        "summary": '-',
                        "document_meta": {
                            "image_name": img_name,
                            "page_number": f"{page_number}"
                        },
                        "source_type": self._source_type
                    }
                    docs.append(
                        Document(page_content=text, metadata=image_meta)
                    )
            pdf.close()
            return docs
        else:
            return []

    def get_paddleocr(self, img_path) -> list:
        # Initialize PaddleOCR
        ocr_model = PaddleOCR(
            lang='en',
            det_model_dir=None,
            rec_model_dir=None,
            rec_char_dict_path=None,
            # table=True,
            use_angle_cls=True,
            # use_gpu=True
        )
        result = ocr_model.ocr(img_path, cls=True)
        return result
