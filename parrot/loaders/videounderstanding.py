from typing import Union, List, Optional
from collections.abc import Callable
import re
import json
from pathlib import PurePath, Path
from datetime import datetime
from ..stores.models import Document
from .basevideo import BaseVideoLoader
from ..clients.google import GoogleGenAIClient
from ..models.google import GoogleModel


def split_text(text, max_length):
    """Split text into chunks of a maximum length, ensuring not to break words."""
    # Split the transcript into paragraphs
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    for paragraph in paragraphs:
        # If the paragraph is too large, split it into sentences
        if len(paragraph) > max_length:
            # Split paragraph into sentences
            sentences = re.split(r'(?<=[.!?]) +', paragraph)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > max_length:
                    # Save the current chunk and start a new one
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # Add sentence to the current chunk
                    current_chunk += " " + sentence
        else:
            # If adding the paragraph exceeds max size, start a new chunk
            if len(current_chunk) + len(paragraph) + 2 > max_length:
                chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                # Add paragraph to the current chunk
                current_chunk += "\n\n" + paragraph
    # Add any remaining text to chunks
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def extract_scenes_from_response(response_text: str) -> List[dict]:
    """
    Extract structured scenes from the AI response.
    Attempts to parse JSON-like structures or creates scenes from the text.
    """
    scenes = []

    # Try to extract JSON from the response
    try:
        # Look for JSON blocks
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_data = json.loads(json_match.group())
            if 'scenes' in json_data:
                return json_data['scenes']
    except json.JSONDecodeError:
        pass

    # Fallback: Parse text-based scenes
    # Look for scene markers like "Scene 1:", "Step 1:", etc.
    scene_pattern = r'(?:Scene|Step)\s*(\d+)[:.]?\s*(.*?)(?=(?:Scene|Step)\s*\d+|$)'
    matches = re.findall(scene_pattern, response_text, re.DOTALL | re.IGNORECASE)

    for i, (scene_num, content) in enumerate(matches):
        # Extract quoted text (spoken text)
        quotes = re.findall(r'"([^"]*)"', content)

        # Extract instructions (non-quoted text)
        instructions = re.sub(r'"[^"]*"', '', content).strip()
        instructions = re.sub(r'\s+', ' ', instructions)

        scene_data = {
            'scene_number': int(scene_num) if scene_num.isdigit() else i + 1,
            'instructions': instructions,
            'spoken_text': ' '.join(quotes) if quotes else '',
            'content': content.strip(),
            'timestamp': f"Scene {scene_num}" if scene_num else f"Scene {i + 1}"
        }
        scenes.append(scene_data)

    # If no scenes found, create one scene with all content
    if not scenes:
        scenes.append({
            'scene_number': 1,
            'instructions': response_text,
            'spoken_text': '',
            'content': response_text,
            'timestamp': 'Full Video'
        })

    return scenes


class VideoUnderstandingLoader(BaseVideoLoader):
    """
    Video analysis loader using Google GenAI for understanding video content.
    Extracts step-by-step instructions and spoken text from training videos.
    """
    extensions: List[str] = ['.mp4', '.webm', '.avi', '.mov', '.mkv']

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'video_understanding',
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW,
        temperature: float = 0.2,
        prompt: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )

        # Google GenAI configuration
        self.model = model
        self.temperature = temperature
        self.google_client = None

        # Custom prompts
        self.prompt = prompt
        self.custom_instructions = custom_instructions

        # Default prompt for video analysis
        self.default_prompt = """
Analyze the video and extract step-by-step instructions for employees to follow, and the spoken text into quotation marks, related to the training content shown in this video.
"""

        # Default instruction for video analysis
        self.default_instructions = """
Video Analysis Instructions:
            1. Videos are training materials for employees to learn how to use Workday.
            2. There are several step-by-step processes shown in the video, with screenshots and spoken text.
            3. Break down the video into distinct scenes based on changes in visuals or context.
            4. For each scene, extract all step-by-step instructions, including any spoken text in quotation marks.
            5. Place each caption into an object with the timecode of the caption in the video.
"""

    async def _get_google_client(self) -> GoogleGenAIClient:
        """Get or create Google GenAI client."""
        if self.google_client is None:
            self.google_client = GoogleGenAIClient(model=self.model)
        return self.google_client

    async def _analyze_video_with_ai(self, video_path: Path) -> str:
        """Analyze video using Google GenAI."""
        try:
            client = await self._get_google_client()

            # Use custom prompt or default
            prompt = self.prompt or self.default_prompt
            instructions = self.custom_instructions or self.default_instructions

            async with client as ai_client:
                self.logger.info(f"Analyzing video with Google GenAI: {video_path.name}")

                response = await ai_client.video_understanding(
                    video=video_path,
                    prompt=prompt,
                    prompt_instruction=instructions,
                    temperature=self.temperature,
                    stateless=True
                )

                return response.output if hasattr(response, 'output') else str(response)

        except Exception as e:
            self.logger.error(f"Error analyzing video with AI: {e}")
            return f"Error analyzing video: {str(e)}"

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """Load and analyze video file."""
        if isinstance(path, (str, PurePath)):
            path = Path(path)
        if not path.exists():
            self.logger.error(f"Video file not found: {path}")
            return []

        self.logger.info(f"Processing video: {path.name}")

        # Base metadata
        base_metadata = {
            "url": f"file://{path}",
            "source": str(path),
            "filename": path.name,
            "type": "video_understanding",
            "source_type": self._source_type,
            "category": self.category,
            "created_at": datetime.now().strftime("%Y-%m-%d, %H:%M:%S"),
            "document_meta": {
                "language": self._language,
                "model_used": str(self.model.value if hasattr(self.model, 'value') else self.model),
                "analysis_type": "video_understanding",
                "video_title": path.stem
            }
        }

        documents = []

        try:
            # Analyze video with Google GenAI
            ai_response = await self._analyze_video_with_ai(path)

            # Save AI response to file
            response_path = path.with_suffix('.ai_analysis.txt')
            self.saving_file(response_path, ai_response.encode('utf-8'))

            # Extract scenes from AI response
            scenes = extract_scenes_from_response(ai_response)

            # Create main analysis document
            main_doc_metadata = {
                **base_metadata,
                "type": "video_analysis_full",
                "document_meta": {
                    **base_metadata["document_meta"],
                    "total_scenes": len(scenes),
                    "analysis_timestamp": datetime.now().isoformat()
                }
            }

            # Split if too long
            if len(ai_response) > 65534:
                chunks = split_text(ai_response, 32767)
                for i, chunk in enumerate(chunks):
                    chunk_metadata = {
                        **main_doc_metadata,
                        "type": "video_analysis_chunk",
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

            # Create individual scene documents
            for scene in scenes:
                scene_metadata = {
                    **base_metadata,
                    "type": "video_scene",
                    "source": f"{path.name}: {scene.get('timestamp', 'Scene')}",
                    "document_meta": {
                        **base_metadata["document_meta"],
                        "scene_number": scene.get('scene_number', 1),
                        "timestamp": scene.get('timestamp', ''),
                        "has_spoken_text": bool(scene.get('spoken_text', '').strip()),
                        "has_instructions": bool(scene.get('instructions', '').strip())
                    }
                }

                # Create content combining instructions and spoken text
                content_parts = []

                if scene.get('instructions'):
                    content_parts.append(f"INSTRUCTIONS:\n{scene['instructions']}")

                if scene.get('spoken_text'):
                    content_parts.append(f"SPOKEN TEXT:\n\"{scene['spoken_text']}\"")

                scene_content = "\n\n".join(content_parts) if content_parts else scene.get('content', '')

                if scene_content.strip():
                    scene_doc = Document(
                        page_content=scene_content,
                        metadata=scene_metadata
                    )
                    documents.append(scene_doc)

            # Create separate documents for instructions and spoken text if needed
            all_instructions = []
            all_spoken = []

            for scene in scenes:
                if scene.get('instructions'):
                    all_instructions.append(f"Scene {scene.get('scene_number', '')}: {scene['instructions']}")
                if scene.get('spoken_text'):
                    all_spoken.append(f"Scene {scene.get('scene_number', '')}: \"{scene['spoken_text']}\"")

            # Instructions summary document
            if all_instructions:
                instructions_metadata = {
                    **base_metadata,
                    "type": "video_instructions_summary",
                    "document_meta": {
                        **base_metadata["document_meta"],
                        "content_type": "instructions_only",
                        "scene_count": len(all_instructions)
                    }
                }

                instructions_content = "STEP-BY-STEP INSTRUCTIONS:\n\n" + "\n\n".join(all_instructions)

                instructions_doc = Document(
                    page_content=instructions_content,
                    metadata=instructions_metadata
                )
                documents.append(instructions_doc)

            # Spoken text summary document
            if all_spoken:
                spoken_metadata = {
                    **base_metadata,
                    "type": "video_spoken_summary",
                    "document_meta": {
                        **base_metadata["document_meta"],
                        "content_type": "spoken_text_only",
                        "scene_count": len(all_spoken)
                    }
                }

                spoken_content = "SPOKEN TEXT TRANSCRIPT:\n\n" + "\n\n".join(all_spoken)

                spoken_doc = Document(
                    page_content=spoken_content,
                    metadata=spoken_metadata
                )
                documents.append(spoken_doc)

            self.logger.info(f"Generated {len(documents)} documents from video analysis")

        except Exception as e:
            self.logger.error(f"Error processing video {path}: {e}")
            # Create error document
            error_metadata = {
                **base_metadata,
                "type": "video_analysis_error",
                "document_meta": {
                    **base_metadata["document_meta"],
                    "error": str(e),
                    "error_timestamp": datetime.now().isoformat()
                }
            }

            error_doc = Document(
                page_content=f"Error analyzing video {path.name}: {str(e)}",
                metadata=error_metadata
            )
            documents.append(error_doc)

        return documents

    async def load_video(self, url: str, video_title: str, transcript: str) -> list:
        """
        Required abstract method implementation.
        This method is not used in our implementation but required by BaseVideoLoader.
        """
        # This method is required by the abstract base class but not used in our implementation
        # We use _load instead for our video analysis
        return []

    async def close(self):
        """Clean up resources."""
        super().clear_cuda()
