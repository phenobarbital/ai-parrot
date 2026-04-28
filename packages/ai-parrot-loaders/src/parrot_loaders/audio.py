from typing import Any, List
from collections.abc import Callable
from pathlib import PurePath
from parrot.stores.models import Document
from .basevideo import BaseVideoLoader


class AudioLoader(BaseVideoLoader):
    """
    Generating transcripts from local Audio.
    """
    extensions: List[str] = ['.mp3', '.webm', '.ogg']

    def load_video(self, path):
        return

    async def load_audio(self, path: PurePath) -> list:
        metadata = self.create_metadata(
            path,
            doctype='audio_transcript',
            source_type=self._source_type,
        )
        documents = []

        # Paths for outputs
        vtt_path = path.with_suffix(".vtt")
        txt_path = path.with_suffix(".txt")
        srt_path = path.with_suffix(".srt")

        # ensure a clean 16k Hz mono wav file for whisper
        wav_path = self.ensure_wav_16k_mono(path)
        # get the Whisper parser
        transcript_whisper = self.get_whisperx_transcript(wav_path)
        transcript = transcript_whisper.get('text', '') if transcript_whisper else ''
        try:
            self.saving_file(txt_path, transcript.encode("utf-8"))
            print(f"Saved TXT transcript to: {txt_path}")
        except Exception as exc:
            print(f"Error saving TXT transcript: {exc}")
        if transcript:
            doc = Document(
                page_content=transcript,
                metadata=self.create_metadata(
                    txt_path,
                    doctype='audio_transcript',
                    source_type='AUDIO',
                    origin=f"{path}",
                )
            )
        # diarization:
        if self._diarization:
            if (srt := self.audio_to_srt(
                audio_path=wav_path,
                asr=transcript_whisper,
                output_srt_path=srt_path,
                max_gap_s=0.5,
                max_chars=90,
                max_duration_s=0.9,
            )):
                doc = Document(
                    page_content=srt,
                    metadata=self.create_metadata(
                        srt_path,
                        doctype='srt_transcript',
                        source_type='AUDIO',
                        origin=f"{path}",
                    )
                )
        # Summarize the transcript (only if enabled)
        if self._summarization and transcript:
            try:
                summary = await self.summary_from_text(transcript)
                # Create Two Documents, one is for transcript, second is VTT:
                doc = Document(
                    page_content=summary,
                    metadata=self.create_metadata(
                        path,
                        doctype='audio_summary',
                        source_type='TEXT',
                        origin=f"{path}",
                    )
                )
                documents.append(doc)
            except Exception as exc:
                print(f"Error generating summary: {exc}")
        if transcript_whisper:
            # VTT version:
            vtt_text = self.transcript_to_vtt(transcript_whisper, vtt_path)
            doc = Document(
                page_content=vtt_text,
                metadata=self.create_metadata(
                    vtt_path,
                    doctype='vtt_transcript',
                    source_type='TEXT',
                    origin=f"{path}",
                )
            )
            documents.append(doc)
            # Saving every dialog chunk as a separate document
            dialogs = self.transcript_to_blocks(transcript_whisper)
            docs = []
            for chunk in dialogs:
                _info = self.create_metadata(
                    path,
                    doctype='audio_dialog',
                    source_type=self._source_type,
                    title=path.stem,
                    start=str(chunk['start_time']),
                    end=str(chunk['end_time']),
                    chunk_id=str(chunk['id']),
                )
                doc = Document(
                    page_content=chunk['text'],
                    metadata=_info
                )
                docs.append(doc)
            documents.extend(docs)
        return documents

    async def extract_audio(self, path: PurePath) -> list:
        """
        Extract audio transcript and summary from a local audio file.
        """
        vtt_path = path.with_suffix('.vtt')
        transcript_path = path.with_suffix('.txt')
        srt_path = path.with_suffix('.srt')
        summary_path = path.with_suffix('.summary')
        metadata = self.create_metadata(
            path,
            doctype='audio_transcript',
            source_type=self._source_type,
            vtt_path=f"{vtt_path}",
            transcript_path=f"{transcript_path}",
            srt_path=f"{srt_path}",
            summary_path=f"{summary_path}",
        )
        # get the Whisper parser
        # ensure a clean 16k Hz mono wav file for whisper
        wav_path = self.ensure_wav_16k_mono(path)
        # get the Whisper parser
        transcript_whisper = self.get_whisperx_transcript(wav_path)
        if transcript_whisper:
            transcript = transcript_whisper['text']
        else:
            transcript = ''
        if self._diarization:
            srt = self.audio_to_srt(
                audio_path=wav_path,
                asr=transcript_whisper,
                output_srt_path=srt_path,
                max_gap_s=0.5,
                max_chars=90,
                max_duration_s=0.9,
            )
            if srt:
                try:
                    self.saving_file(srt_path, srt.encode("utf-8"))
                    print(f"Saved SRT transcript to: {srt_path}")
                except Exception as exc:
                    print(f"Error saving SRT transcript: {exc}")
        # Summarize the transcript (only if enabled)
        self.saving_file(transcript_path, transcript.encode('utf-8'))
        if self._summarization and transcript:
            try:
                summary = await self.summary_from_text(transcript)
                # Create Two Documents, one is for transcript, second is VTT:
                metadata['summary'] = summary
                self.saving_file(summary_path, summary.encode('utf-8'))
            except Exception as exc:
                print(f"Error generating summary: {exc}")
            # VTT version:
            transcript = self.transcript_to_vtt(transcript_whisper, vtt_path)
        return metadata

    async def _load(self, source, **kwargs) -> List[Document]:
        return await self.load_audio(source)
