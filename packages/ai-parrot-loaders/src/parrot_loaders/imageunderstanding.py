"""Image Understanding Loader using Google GenAI for analyzing images."""
from typing import Union, List, Optional
from collections.abc import Callable
import re
import json
from pathlib import PurePath, Path
from datetime import datetime
from parrot.stores.models import Document
from parrot.loaders.abstract import AbstractLoader
from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import GoogleModel


def split_text(text: str, max_length: int) -> List[str]:
    """Split text into chunks of a maximum length, ensuring not to break words."""
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_length:
            sentences = re.split(r'(?<=[.!?]) +', paragraph)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > max_length:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    current_chunk += " " + sentence
        else:
            if len(current_chunk) + len(paragraph) + 2 > max_length:
                chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                current_chunk += "\n\n" + paragraph
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks


def extract_sections_from_response(response_text: str) -> List[dict]:
    """
    Extract structured sections from the AI image analysis response.
    Attempts to parse JSON-like structures or creates sections from the text.
    """
    sections = []

    # Try to extract JSON from the response
    try:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_data = json.loads(json_match.group())
            if 'sections' in json_data:
                return json_data['sections']
            if 'elements' in json_data:
                return json_data['elements']
    except json.JSONDecodeError:
        pass

    # Fallback: Parse text-based sections
    section_pattern = r'(?:Section|Element|Part|Area)\s*(\d+)[:.]?\s*(.*?)(?=(?:Section|Element|Part|Area)\s*\d+|$)'
    matches = re.findall(section_pattern, response_text, re.DOTALL | re.IGNORECASE)

    for i, (section_num, content) in enumerate(matches):
        section_data = {
            'section_number': int(section_num) if section_num.isdigit() else i + 1,
            'content': content.strip(),
            'label': f"Section {section_num}" if section_num else f"Section {i + 1}"
        }
        sections.append(section_data)

    # If no sections found, create one section with all content
    if not sections:
        sections.append({
            'section_number': 1,
            'content': response_text,
            'label': 'Full Image'
        })

    return sections


class ImageUnderstandingLoader(AbstractLoader):
    """
    Image analysis loader using Google GenAI for understanding image content.
    Extracts descriptions, text, objects, and structured information from images.
    Uses the flash preview image model for analysis.
    """
    extensions: List[str] = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif']

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'image_understanding',
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
        temperature: float = 0.2,
        prompt: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        language: str = "en",
        detect_objects: bool = False,
        **kwargs
    ):
        """Initialize the ImageUnderstandingLoader.

        Args:
            source: Path or list of paths to image files.
            tokenizer: Tokenizer to use for text splitting.
            text_splitter: Text splitter to use.
            source_type: Type identifier for the source.
            model: Google GenAI model to use for image analysis.
            temperature: Temperature for generation.
            prompt: Custom prompt for image analysis.
            custom_instructions: Custom system instructions for analysis.
            language: Language for analysis output.
            detect_objects: Whether to enable object detection.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )

        self.model = model
        self.temperature = temperature
        self.google_client = None
        self._language = language
        self.detect_objects = detect_objects

        # Custom prompts
        self.prompt = prompt
        self.custom_instructions = custom_instructions

        self.default_prompt = """
Analyze the image and extract all relevant information including:
1. A detailed description of the image content.
2. Any visible text (OCR).
3. Key objects, elements, or subjects identified.
4. Layout and structural information.
5. Any relevant context or meaning conveyed by the image.
"""

        self.default_instructions = """
Image Analysis Instructions:
    1. Provide a thorough and accurate analysis of the image.
    2. Extract any text visible in the image verbatim.
    3. Identify and describe all key elements, objects, and subjects.
    4. Describe the layout, composition, and spatial relationships.
    5. Note any colors, patterns, or visual styles that are significant.
    6. If the image contains diagrams, charts, or infographics, extract the data and relationships.
"""

    async def _get_google_client(self) -> GoogleGenAIClient:
        """Get or create Google GenAI client."""
        if self.google_client is None:
            self.google_client = GoogleGenAIClient(model=self.model)
        return self.google_client

    async def _analyze_image_with_ai(self, image_path: Path) -> str:
        """Analyze image using Google GenAI image_understanding method."""
        try:
            client = await self._get_google_client()

            prompt = self.prompt or self.default_prompt
            instructions = self.custom_instructions or self.default_instructions

            async with client as ai_client:
                self.logger.info(f"Analyzing image with Google GenAI: {image_path.name}")

                response = await ai_client.image_understanding(
                    prompt=prompt,
                    images=image_path,
                    model=self.model,
                    prompt_instruction=instructions,
                    temperature=self.temperature,
                    stateless=True,
                    detect_objects=self.detect_objects,
                )

                return response.output if hasattr(response, 'output') else str(response)

        except Exception as e:
            self.logger.error(f"Error analyzing image with AI: {e}")
            return f"Error analyzing image: {str(e)}"

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """Load and analyze image file(s)."""
        if isinstance(path, list):
            documents = []
            for p in path:
                docs = await self._process_single_image(Path(p))
                documents.extend(docs)
            return documents

        return await self._process_single_image(Path(path))

    async def _process_single_image(self, path: Path) -> List[Document]:
        """Process a single image file and return documents."""
        if not path.exists():
            self.logger.error(f"Image file not found: {path}")
            return []

        self.logger.info(f"Processing image: {path.name}")

        base_metadata = {
            "url": f"file://{path}",
            "source": str(path),
            "filename": path.name,
            "type": "image_understanding",
            "source_type": self._source_type,
            "category": self.category,
            "created_at": datetime.now().strftime("%Y-%m-%d, %H:%M:%S"),
            "document_meta": {
                "language": self._language,
                "model_used": str(self.model.value if hasattr(self.model, 'value') else self.model),
                "analysis_type": "image_understanding",
                "image_title": path.stem
            }
        }

        documents = []

        try:
            # Analyze image with Google GenAI
            ai_response = await self._analyze_image_with_ai(path)

            # Save AI response to file
            response_path = path.with_suffix('.ai_analysis.txt')
            self.saving_file(response_path, ai_response.encode('utf-8'))

            # Extract sections from AI response
            sections = extract_sections_from_response(ai_response)

            # Create main analysis document
            main_doc_metadata = {
                **base_metadata,
                "type": "image_analysis_full",
                "document_meta": {
                    **base_metadata["document_meta"],
                    "total_sections": len(sections),
                    "analysis_timestamp": datetime.now().isoformat()
                }
            }

            # Split if too long
            if len(ai_response) > 65534:
                chunks = split_text(ai_response, 32767)
                for i, chunk in enumerate(chunks):
                    chunk_metadata = {
                        **main_doc_metadata,
                        "type": "image_analysis_chunk",
                        "document_meta": {
                            **main_doc_metadata["document_meta"],
                            "chunk_number": i + 1,
                            "total_chunks": len(chunks)
                        }
                    }
                    doc = Document(
                        page_content=chunk,
                        metadata=chunk_metadata
                    )
                    documents.append(doc)
            else:
                doc = Document(
                    page_content=ai_response,
                    metadata=main_doc_metadata
                )
                documents.append(doc)

            # Create individual section documents
            for section in sections:
                section_metadata = {
                    **base_metadata,
                    "type": "image_section",
                    "source": f"{path.name}: {section.get('label', 'Section')}",
                    "document_meta": {
                        **base_metadata["document_meta"],
                        "section_number": section.get('section_number', 1),
                        "label": section.get('label', ''),
                    }
                }

                section_content = section.get('content', '')

                if section_content.strip():
                    section_doc = Document(
                        page_content=section_content,
                        metadata=section_metadata
                    )
                    documents.append(section_doc)

            self.logger.info(f"Generated {len(documents)} documents from image analysis")

        except Exception as e:
            self.logger.error(f"Error processing image {path}: {e}")
            error_metadata = {
                **base_metadata,
                "type": "image_analysis_error",
                "document_meta": {
                    **base_metadata["document_meta"],
                    "error": str(e),
                    "error_timestamp": datetime.now().isoformat()
                }
            }

            error_doc = Document(
                page_content=f"Error analyzing image {path.name}: {str(e)}",
                metadata=error_metadata
            )
            documents.append(error_doc)

        return documents

    async def close(self):
        """Clean up resources."""
        self.google_client = None
