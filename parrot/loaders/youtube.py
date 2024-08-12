from typing import Optional, Union
from pytube import YouTube
from youtube_transcript_api import NoTranscriptFound
import torch
from langchain.docstore.document import Document
from langchain_community.document_loaders.parsers.audio import (
    OpenAIWhisperParserLocal
)
from langchain_community.document_loaders import YoutubeLoader as YTLoader
from langchain_community.document_loaders.generic import (
    GenericLoader
)
from langchain_community.document_loaders.blob_loaders.youtube_audio import (
    YoutubeAudioLoader
)
from .video import VideoLoader


def extract_video_id(url):
    parts = url.split("?v=")
    video_id = parts[1].split("&")[0]
    return video_id


class YoutubeLoader(VideoLoader):
    """
    Loader for Youtube videos.
    """
    _extension = ['.youtube']
    encoding = 'utf-8'
    chunk_size = 768

    def get_video_info(self, url: str) -> dict:
        yt = YouTube(url)
        return  {
            "url": url,
            "video_id": yt.video_id,
            "watch_url": yt.watch_url,
            "embed_url": yt.embed_url,
            "title": yt.title or "Unknown",
            "description": yt.description or "Unknown",
            "view_count": yt.views or 0,
            #"thumbnail_url": yt.thumbnail_url or "Unknown",
            "publish_date": yt.publish_date.strftime("%Y-%m-%d %H:%M:%S") if yt.publish_date else "Unknown",
            # "length": yt.length or 0,
            "author": yt.author or "Unknown",
        }

    def load_video(self, url: str, video_title: str, transcript: Optional[Union[str, None]] = None) -> list:
        # first: load video metadata:
        video_info = self.get_video_info(url)
        # Second: load video transcript (if any)
        if transcript is None:
            try:
                documents = []
                docs = []
                # first: download video
                file_path = self.download_video(url, self._video_path)
                audio_path = file_path.with_suffix('.mp3')
                transcript_path = file_path.with_suffix('.vtt')
                # second: extract audio
                self.extract_audio(file_path, audio_path)
                transcript_whisper = self.get_whisper_transcript(audio_path)
                transcript = transcript_whisper['text']
                # Summarize the transcript
                try:
                    summary = self.get_summary_from_text(transcript)
                except Exception:
                    summary = ''
                # Create Two Documents, one is for transcript, second is VTT:
                metadata = {
                    "url": f"{url}",
                    "source": f"{url}",
                    "index": video_title,
                    "filename": video_title,
                    "question": '',
                    "answer": '',
                    "source_type": self._source_type,
                    'type': 'video_transcript',
                    "summary": f"{summary!s}",
                    "document_meta": {
                        "language": self._language,
                        "title": video_title,
                        "docinfo": video_info
                    }
                }
                if self.topics:
                    metadata["document_meta"]['topic_tags'] = self.topics
                doc = Document(
                    page_content=transcript,
                    metadata=metadata
                )
                documents.append(doc)
                # VTT version:
                transcript = self.transcript_to_vtt(transcript_whisper, transcript_path)
                if transcript:
                    doc = Document(
                        page_content=transcript,
                        metadata=metadata
                    )
                    documents.append(doc)
                # Saving every dialog chunk as a separate document
                dialogs = self.transcript_to_blocks(transcript_whisper)
                for chunk in dialogs:
                    _meta = {
                        "index": f"{video_title}:{chunk['id']}",
                        "document_meta": {
                            "start": f"{chunk['start_time']}",
                            "end": f"{chunk['end_time']}",
                            "id": f"{chunk['id']}",
                            "language": self._language,
                            "title": video_title,
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
            except Exception:
                try:
                    loader = YTLoader.from_youtube_url(
                        url,
                        add_video_info=True,
                        language=[self._language],
                    )
                    docs = loader.load()
                except NoTranscriptFound:
                    loader = GenericLoader(
                        YoutubeAudioLoader([url], str(self._video_path)),
                        OpenAIWhisperParserLocal(
                            # lang_model='openai/whisper-medium.en',
                            lang_model='openai/whisper-small.en',
                            device=self._get_device()
                        )
                    )
                    docs = loader.load()
                if not docs:
                    self.logger.warning(
                        f"Unable to load Youtube Video {url}"
                    )
                    return []
                summary = self.get_summary(
                    docs
                )
                for doc in docs:
                    doc.metadata['source_type'] = self._source_type
                    doc.metadata['summary'] = f"{summary!s}"
                    doc.metadata['index'] = ''
                    doc.metadata['filename'] = ''
                    doc.metadata['question'] = ''
                    doc.metadata['answer'] = ''
                    doc.metadata['type'] = 'video_transcript'
                    doc.metadata['document_meta'] = {}
                    if self.topics:
                        doc.metadata['document_meta']['topic_tags'] = self.topics
                    # add video metadata to document metadata:
                    for key, value in video_info.items():
                        doc.metadata['document_meta'][key] = f"{value!s}"
                return docs
        else:
            with open(transcript, 'r') as f:
                transcript = f.read()
            if transcript:
                summary = self.get_summary_from_text(transcript)
                transcript_whisper = None
                metadata = {
                    "source": url,
                    "url": url,
                    "index": '',
                    "filename": '',
                    "question": '',
                    "answer": '',
                    "source_type": self._source_type,
                    'type': 'video_transcript',
                    'summary': f"{summary!s}",
                    "document_meta": {
                        "language": self._language,
                        "title": video_title
                    },
                }
                if self.topics:
                    metadata['document_meta']['topic_tags'] = self.topics
                doc = Document(
                    page_content=transcript,
                    metadata=metadata
                )
                return [doc]
