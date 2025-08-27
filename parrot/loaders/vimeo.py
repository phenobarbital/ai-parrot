from typing import Optional, Union
from ..stores.models import Document
from .youtube import YoutubeLoader


class VimeoLoader(YoutubeLoader):
    """
    Loader for Vimeo videos.
    """
    async def load_video(
        self,
        url: str,
        video_title: str,
        transcript: Optional[Union[str, None]] = None
    ) -> list:
        metadata = {
            "source": url,
            "url": url,
            # "index": url,
            "filename": video_title,
            "question": '',
            "answer": '',
            'type': 'video_transcript',
            "source_type": self._source_type,
            "summary": '',
            "document_meta": {
                "language": self._language,
                "title": video_title,
                "topic_tags": ""
            }
        }
        if self.topics:
            metadata['document_meta']['topic_tags'] = self.topics
        if transcript is None:
            documents = []
            docs = []
            # first: download video
            try:
                file_path = self.download_video(url, self._video_path)
            except Exception:
                return []
            if not file_path:
                self.logger.warning(
                    f"Error downloading File for video: {self._video_path}"
                )
                return []
            transcript_path = file_path.with_suffix('.vtt')
            audio_path = file_path.with_suffix('.mp3')
            # second: extract audio
            self.extract_audio(file_path, audio_path)
            # get the Whisper parser
            transcript_whisper = self.get_whisper_transcript(audio_path)
            if transcript_whisper:
                transcript = transcript_whisper['text']
            else:
                transcript = ''
            # Summarize the transcript
            if transcript:
                summary = self.summary_from_text(transcript)
                # Create Two Documents, one is for transcript, second is VTT:
                metadata['summary'] = summary
                doc = Document(
                    page_content=transcript,
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
                for chunk in dialogs:
                    _meta = {
                        # "index": f"{video_title}:{chunk['id']}",
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
        else:
            # using the transcript file
            with open(transcript, 'r') as f:
                transcript = f.read()
                summary = self.summary_from_text(transcript)
                transcript_whisper = None
            metadata['summary'] = f"{summary!s}"
            # Create Two Documents, one is for transcript, second is VTT:
            doc = Document(
                page_content=transcript,
                metadata=metadata
            )
            return [doc]

    def extract_video(
        self,
        url: str
    ) -> list:
        metadata = {
            "source": url,
            "url": url,
            'type': 'video_transcript',
            "source_type": self._source_type,
            "summary": '',
            "document_meta": {
                "language": self._language
            }
        }
        # first: download video
        try:
            file_path = self.download_video(url, self._video_path)
        except Exception:
            return None
        if not file_path:
            self.logger.warning(
                f"Error downloading File for video: {self._video_path}"
            )
            return None
        vtt_path = file_path.with_suffix('.vtt')
        transcript_path = file_path.with_suffix('.txt')
        audio_path = file_path.with_suffix('.mp3')
        summary_path = file_path.with_suffix('.summary')
        # second: extract audio
        self.extract_audio(file_path, audio_path)
        # get the Whisper parser
        transcript_whisper = self.get_whisper_transcript(audio_path)
        if transcript_whisper:
            transcript = transcript_whisper['text']
            self.saving_file(transcript_path, transcript.encode('utf-8'))
            # Summarize the transcript
            if transcript:
                summary = self.summary_from_text(transcript)
                # Create Two Documents, one is for transcript, second is VTT:
                metadata['summary'] = summary
                self.saving_file(summary_path, summary.encode('utf-8'))
        # VTT version:
        transcript = self.transcript_to_vtt(transcript_whisper, vtt_path)
        metadata['transcript'] = transcript_path
        metadata['summary_file'] = summary_path
        metadata["vtt"] = vtt_path
        metadata['audio'] = audio_path
        metadata['video'] = file_path
        return metadata

    def extract(self) -> list:
        # Adding also Translation to other language.
        documents = []
        for url in self.urls:
            doc = self.extract_video(url)
            documents.append(doc)
        return documents
