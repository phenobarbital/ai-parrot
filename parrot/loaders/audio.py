from typing import Any, List
from collections.abc import Callable
from pathlib import PurePath
from langchain.docstore.document import Document
from .basevideo import BaseVideoLoader


class AudioLoader(BaseVideoLoader):
    """
    Generating transcripts from local Audio.
    """
    extensions: List[str] = ['.mp3', '.webm', '.ogg']

    def load_video(self, path):
        return

    def load_audio(self, path: PurePath) -> list:
        metadata = {
            "source": f"{path}",
            "url": f"{path.name}",
            # "index": path.stem,
            "filename": f"{path}",
            'type': 'audio_transcript',
            "source_type": self._source_type,
            "document_meta": {
                "language": self._language,
                "topic_tags": ""
            }
        }
        documents = []
        transcript_path = path.with_suffix('.vtt')
        # get the Whisper parser
        transcript_whisper = self.get_whisper_transcript(path)
        if transcript_whisper:
            transcript = transcript_whisper['text']
        else:
            transcript = ''
        # Summarize the transcript
        if transcript:
            summary = self.summary_from_text(transcript)
            # Create Two Documents, one is for transcript, second is VTT:
            doc = Document(
                page_content=summary,
                metadata=metadata
            )
            documents.append(doc)
        if transcript_whisper:
            # VTT version:
            transcript = self.transcript_to_vtt(transcript_whisper, transcript_path)
            doc = Document(
                page_content=transcript,
                metadata=metadata
            )
            documents.append(doc)
            # Saving every dialog chunk as a separate document
            dialogs = self.transcript_to_blocks(transcript_whisper)
            docs = []
            for chunk in dialogs:
                _meta = {
                    # "index": f"{path.stem}:{chunk['id']}",
                    "document_meta": {
                        "start": f"{chunk['start_time']}",
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

    def extract_audio(self, path: PurePath) -> list:
        metadata = {
            "source": f"{path}",
            "url": f"{path.name}",
            # "index": path.stem,
            "filename": f"{path}",
            'type': 'audio_transcript',
            "source_type": self._source_type,
            "document_meta": {
                "language": self._language,
            }
        }
        vtt_path = path.with_suffix('.vtt')
        transcript_path = path.with_suffix('.txt')
        summary_path = path.with_suffix('.summary')
        # get the Whisper parser
        transcript_whisper = self.get_whisper_transcript(path)
        if transcript_whisper:
            transcript = transcript_whisper['text']
        else:
            transcript = ''
        # Summarize the transcript
        self.saving_file(transcript_path, transcript.encode('utf-8'))
        if transcript:
            summary = self.summary_from_text(transcript)
            # Create Two Documents, one is for transcript, second is VTT:
            metadata['summary'] = summary
            self.saving_file(summary_path, summary.encode('utf-8'))
            # VTT version:
            transcript = self.transcript_to_vtt(transcript_whisper, vtt_path)
        return metadata

    async def _load(self, source, **kwargs) -> List[Document]:
        return self.load_audio(source)
