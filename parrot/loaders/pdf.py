from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any
from io import BytesIO
import re
import ftfy
import fitz
import pytesseract
from paddleocr import PaddleOCR
import torch
import cv2
from transformers import (
    # DonutProcessor,
    # VisionEncoderDecoderModel,
    # VisionEncoderDecoderConfig,
    # ViTImageProcessor,
    # AutoTokenizer,
    LayoutLMv3ForTokenClassification,
    LayoutLMv3Processor
)
from pdf4llm import to_markdown
from PIL import Image
from langchain.docstore.document import Document
from navconfig import config
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
        self.page_as_images = kwargs.get('page_as_images', False)
        if self.page_as_images is True:
            # # Load the processor and model from Hugging Face
            # self.image_processor = DonutProcessor.from_pretrained(
            #     "naver-clova-ix/donut-base-finetuned-docvqa"
            # )
            # self.image_model = VisionEncoderDecoderModel.from_pretrained(
            #     "naver-clova-ix/donut-base-finetuned-docvqa",

            # )
            # Load the processor and model from Hugging Face
            self.image_processor = LayoutLMv3Processor.from_pretrained(
                "microsoft/layoutlmv3-base",
                apply_ocr=True
            )
            self.image_model = LayoutLMv3ForTokenClassification.from_pretrained(
                # "microsoft/layoutlmv3-base-finetuned-funsd"
                "HYPJUDY/layoutlmv3-base-finetuned-funsd"
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

    def explain_image(self, image_path):
        """Function to explain the image."""
        # with open(image_path, "rb") as image_file:
        #     image_content = image_file.read()

        # Open the image
        image = cv2.imread(image_path)
        task_prompt = "<s_docvqa><s_question>{user_input}</s_question><s_answer>"
        question = "Extract Questions about Happily Greet"
        prompt = task_prompt.replace("{user_input}", question)

        decoder_input_ids = self.image_processor.tokenizer(
            prompt,
            add_special_tokens=False,
            return_tensors="pt",
        ).input_ids

        pixel_values = self.image_processor(
            image,
            return_tensors="pt"
        ).pixel_values

        # Send inputs to the appropriate device
        pixel_values = pixel_values.to(self.image_device)
        decoder_input_ids = decoder_input_ids.to(self.image_device)

        outputs = self.image_model.generate(
            pixel_values,
            decoder_input_ids=decoder_input_ids,
            max_length=self.image_model.decoder.config.max_position_embeddings,
            pad_token_id=self.image_processor.tokenizer.pad_token_id,
            eos_token_id=self.image_processor.tokenizer.eos_token_id,
            bad_words_ids=[[self.image_processor.tokenizer.unk_token_id]],
            # use_cache=True
            return_dict_in_generate=True,
        )

        sequence = self.image_processor.batch_decode(outputs.sequences)[0]


        sequence = sequence.replace(
            self.image_processor.tokenizer.eos_token, ""
        ).replace(
            self.image_processor.tokenizer.pad_token, ""
        )
        # remove first task start token
        sequence = re.sub(r"<.*?>", "", sequence, count=1).strip()
        # Print the extracted sequence
        print("Extracted Text:", sequence)

        print(self.image_processor.token2json(sequence))

        # Format the output as Markdown (optional step)
        markdown_text = self.format_as_markdown(sequence)
        print("Markdown Format:\n", markdown_text)

        return None

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
        markdown_text = re.sub(r"(\w+):", r"- **\1**:", markdown_text)
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

    def extract_page_text(self, image_path) -> str:
        # Open the image
        image = Image.open(image_path).convert("RGB")

        # Processor handles the OCR internally, no need for words or boxes
        encoding = self.image_processor(image, return_tensors="pt", truncation=True)
        encoding = {k: v.to(self.image_device) for k, v in encoding.items()}

        # Forward pass
        outputs = self.image_model(**encoding)
        logits = outputs.logits

        # Get predictions
        predictions = logits.argmax(-1).squeeze().tolist()
        labels = [self.image_model.config.id2label[pred] for pred in predictions]

        # Get the words and boxes from the processor's OCR step
        words = self.image_processor.tokenizer.convert_ids_to_tokens(
            encoding['input_ids'].squeeze().tolist()
        )
        boxes = encoding['bbox'].squeeze().tolist()

        # Combine words and labels, preserving line breaks based on vertical box position
        extracted_text = ""
        last_box = None
        for word, label, box in zip(words, labels, boxes):
            if label != 'O':
                # Check if the current word is on a new line based on the vertical position of the box
                if last_box and abs(box[1] - last_box[1]) > 10:  # A threshold for line breaks
                    extracted_text += "\n"  # Add a line break

                extracted_text += f"{word} "
                last_box = box
        cleaned_text = self.clean_tokenized_text(extracted_text)
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
                _meta = {
                    "url": f'{path}',
                    "source": f"{path.name}",
                    "filename": path.name,
                    "type": 'pdf',
                    "question": '',
                    "answer": '',
                    "source_type": self._source_type,
                    "data": {},
                    "summary": '',
                    "document_meta": {
                        "title": pdf.metadata.get("title", ""),
                        "creationDate": pdf.metadata.get("creationDate", ""),
                        "author": pdf.metadata.get("author", ""),
                    }
                }
                docs.append(
                    Document(
                        page_content=md_text,
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
                            "creationDate": pdf.metadata.get("creationDate", ""),
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
                # fourth: page as image
                if self.page_as_images is True:
                    # Convert the page to a Pixmap (which is an image)
                    mat = fitz.Matrix(2, 2)
                    pix = page.get_pixmap(dpi=300, matrix=mat) # Increase DPI for better resolution
                    img_name = f'{file_name}_page_{page_num}.png'
                    img_path = self._imgdir.joinpath(img_name)
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
                    url = f'/static/images/{img_name}'
                    image_meta = {
                        "url": url,
                        "source": f"{path.name} Page.#{page_num}",
                        "filename": path.name,
                        "index": f"{path.name}:{page_num}",
                        "question": '',
                        "answer": '',
                        "type": 'page',
                        "data": {},
                        "summary": '',
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

    def get_ocr(self, img_path) -> list:
        # Initialize PaddleOCR with table recognition
        self.ocr_model = PaddleOCR(
            lang='en',
            det_model_dir=None,
            rec_model_dir=None,
            rec_char_dict_path=None,
            table=True,
            # use_angle_cls=True,
            # use_gpu=True
        )
        result = self.ocr_model.ocr(img_path, cls=True)

        # extract tables:
        # The result contains the table structure and content
        tables = []
        for line in result:
            if 'html' in line[1]:
                html_table = line[1]['html']
                tables.append(html_table)

        print('TABLES > ', tables)
