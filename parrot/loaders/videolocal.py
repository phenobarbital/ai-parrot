from typing import Any, Union, List
from collections.abc import Callable
import re
import math
from pathlib import PurePath
from langchain.docstore.document import Document
from .basevideo import BaseVideoLoader


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


class VideoLocalLoader(BaseVideoLoader):
    """
    Generating Video transcripts from local Videos.
    """
    _extension = ['.mp4', '.webm']

    def __init__(
        self,
        *args,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'video',
        **kwargs
    ):
        super().__init__(
            tokenizer,
            text_splitter,
            source_type=source_type,
            **kwargs
        )
        self.extract_frames: bool = kwargs.pop('extract_frames', False)
        self.seconds_per_frame: int = kwargs.pop('seconds_per_frame', 1)
        self.compress_speed: bool = kwargs.pop('compress_speed', False)
        self.speed_factor: float = kwargs.pop('speed_factor', 1.5)

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        metadata = {
            "url": f"{path}",
            "source": f"{path}",
            "filename": f"{path.name}",
            "question": '',
            "answer": '',
            'type': 'video_transcript',
            "source_type": self._source_type,
            "data": {},
            "summary": '',
            "document_meta": {
                "language": self._language,
                "topic_tags": ""
            }
        }
        documents = []
        transcript_path = path.with_suffix('.txt')
        vtt_path = path.with_suffix('.vtt')
        summary_path = path.with_suffix('.summary')
        audio_path = path.with_suffix('.mp3')
        # second: extract audio from File
        self.extract_audio(
            path,
            audio_path,
            compress_speed=self.compress_speed,
            speed_factor=self.speed_factor
        )
        # get the Whisper parser
        transcript_whisper = self.get_whisper_transcript(audio_path)
        if transcript_whisper:
            transcript = transcript_whisper['text']
        else:
            transcript = ''
        # Summarize the transcript
        if transcript:
            # first: extract summary, saving summary as a document:
            summary = self.summary_from_text(transcript)
            self.saving_file(summary_path, summary.encode('utf-8'))
            # second: saving transcript to a file:
            self.saving_file(transcript_path, transcript.encode('utf-8'))
            # Create Three Documents:
            # one is for transcript
            # split document only if size > 65.534
            if len(transcript) > 65534:
                # Split transcript into chunks
                transcript_chunks = split_text(transcript, 32767)
                for chunk in transcript_chunks:
                    doc = Document(
                        page_content=chunk,
                        metadata=metadata
                    )
                    documents.append(doc)
            else:
                doc = Document(
                    page_content=transcript,
                    metadata=metadata
                )
                documents.append(doc)
            # second is Summary
            if summary:
                _meta = {
                    **metadata,
                    "type": 'video summary'
                }
                doc = Document(
                    page_content=summary,
                    metadata=_meta
                )
            # Third is VTT:
        if transcript_whisper:
            # VTT version:
            transcript = self.transcript_to_vtt(transcript_whisper, vtt_path)
            _meta = {
                **metadata,
                "type": 'video subte vtt'
            }
            if len(transcript) > 65535:
                transcript_chunks = split_text(transcript, 65535)
                for chunk in transcript_chunks:
                    doc = Document(
                        page_content=chunk,
                        metadata=_meta
                    )
                    documents.append(doc)
            else:
                doc = Document(
                    page_content=transcript,
                    metadata=_meta
                )
                documents.append(doc)
            # Saving every dialog chunk as a separate document
            dialogs = self.transcript_to_blocks(transcript_whisper)
            docs = []
            for chunk in dialogs:
                start_time = chunk['start_time']
                _meta = {
                    "source": f"{path.name}: min. {start_time}",
                    "type": "video dialog",
                    "document_meta": {
                        "start": f"{start_time}",
                        "end": f"{chunk['end_time']}",
                        "id": f"{chunk['id']}",
                        "language": self._language,
                        "title": f"{path.stem}",
                        "topic_tags": ""
                    }
                }
                _info = {**metadata, **_meta}
                doc = Document(
                    page_content=chunk['text'],
                    metadata=_info
                )
                docs.append(doc)
            documents.extend(docs)
        return documents
