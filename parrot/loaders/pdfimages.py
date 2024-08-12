from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any
import fitz
from pdf4llm import to_markdown
from PIL import Image
from langchain.docstore.document import Document
from langchain.text_splitter import MarkdownTextSplitter
from transformers import (
    AutoTokenizer,
    AutoProcessor,
    LlavaForConditionalGeneration,
    pipeline,
    BitsAndBytesConfig
)
import torch
from .basepdf import BasePDF


quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16
)


class PDFImageLoader(BasePDF):
    """
    Loader for PDF files.
    """
    default_prompt: str = "<|user|>\n<image>\nExplain this schematic diagram or technical installation instructions and wire diagrams, please be detailed about descriptions of steps:<|end|>\n<|assistant|>\n"
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
        self._image_model = kwargs.get('image_model', 'llava-hf/llava-v1.6-vicuna-7b-hf')
        self._task = kwargs.get('task', 'image-to-text')
        self._max_tokens = kwargs.get('max_tokens', 600)
        # Loading the model with low CPU memory usage
        # model = LlavaForConditionalGeneration.from_pretrained(
        #     self._image_model,
        #     quantization_config=quantization_config,
        #     device_map="auto",
        #     torch_dtype=torch.float16,
        #     low_cpu_mem_usage=True
        # )
        # # Load the processor
        # processor = AutoProcessor.from_pretrained(self._image_model, use_fast=True)
        self._pipeline = pipeline(
            self._task,
            model=self._image_model,
            # tokenizer=processor.tokenizer,
            # image_processor=processor.image_processor,
            model_kwargs={"quantization_config": quantization_config},
            # device=self._device,
            max_new_tokens=self._max_tokens,
            # low_cpu_mem_usage=True,
            use_fast=True
        )
        # default prompt
        self._prompt = kwargs.get('prompt', self.default_prompt)
        # Markdown Splitter
        self._splitter = MarkdownTextSplitter(
            chunk_size = self._chunk_size,
            chunk_overlap=10
        )

    def pixmap_to_pil_image(self, pix):
        """Converts a PyMuPDF Pixmap object to a PIL Image"""
        return Image.frombytes(
            "RGB",
            [pix.width, pix.height],
            pix.samples
        )

    def _load_pdf(self, path: Path) -> list:
        """
        Load a PDF file as Images.

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
                # get markdown for all pages and saved separately
                md_text = to_markdown(pdf)
                try:
                    summary = self.get_summary_from_text(md_text)
                except Exception:
                    summary = ''
                metadata = {
                    "url": '',
                    "idx": str(path.name),
                    "filename": str(path.name),
                    "source": str(path.name),
                    "type": 'pdf',
                    "question": '',
                    "answer": '',
                    "data": {},
                    "summary": summary,
                    "source_type": self._source_type,
                    "document_meta": {
                        "title": pdf.metadata.get("title", ""),
                        "author": pdf.metadata.get("author", ""),
                    }
                }
                for idx, chunk in enumerate(self._splitter.split_text(md_text)):
                    _info = {
                        "index": f"{idx}",
                        **metadata
                    }
                    docs.append(
                        Document(
                            page_content=chunk,
                            metadata=_info
                        )
                    )
            except (IndexError, ValueError) as exc:
                self.logger.warning(
                    f"There is no text data to load on {path.name}: {exc}"
                )
            # Then, processing the pages one by one as Images:
            file_name = path.stem.replace(" ", "_").replace(".", "_")
            for page_number in range(pdf.page_count):
                page_num = page_number + 1
                self.logger.notice(
                    f"Processing PDF {path} on Page {page_num}"
                )
                page = pdf[page_number]
                pix = page.get_pixmap(colorspace=fitz.csRGB, alpha=False)
                zoom_x = 2.0  # horizontal zoom
                zoom_y = 2.0  # vertical zoom
                mat = fitz.Matrix(zoom_x, zoom_y)  # zoom factor 2 in each dimension
                img_stream = self.pixmap_to_pil_image(pix)
                url = ''
                img_name = f'image_{file_name}_{page_num}.png'
                if self.save_images is True:
                    img_path = self.save_image(
                        img_stream,
                        img_name,
                        self._imgdir
                    )
                    url = f'/static/images/{img_name}'
                # extracting features and explanations:
                outputs = self._pipeline(
                    img_stream,
                    prompt=self._prompt,
                    generate_kwargs={"max_new_tokens": self._max_tokens}
                )
                documents = []
                for idx, output in enumerate(outputs):
                    generated_text = output['generated_text']
                    # Split using the special tokens, if available
                    split_text = generated_text.split("<|assistant|>")
                    prompt_text = split_text[0].replace("<|prompt|>", "").strip() if "<|prompt|>" in generated_text else ""
                    response_text = split_text[1].strip() if len(split_text) > 1 else ""
                    # Attach the image using Markdown syntax
                    image_markdown = f"\n\n![Image]({url})\n"
                    response_text += image_markdown
                    _meta = {
                        "url": f"{url}",
                        "filename": str(path.name),
                        "index": f"Page {page_num}, part: {idx}",
                        "source": str(path.name),
                        "type": 'pdf',
                        "question": prompt_text,
                        "answer": '',
                        "data": {},
                        "summary": '',
                        "source_type": self._source_type,
                        "document_meta": {
                            "page": f"Page {page}",
                            "image": f"{img_name}",
                            "url": f"{url}"
                        }
                    }
                    documents.append(
                        Document(
                            page_content=response_text,
                            metadata=_meta
                        )
                    )
            return docs + documents

    def load(self) -> list:
        try:
            return super().load()
        finally:
            self._pipeline = None
