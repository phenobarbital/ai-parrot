import asyncio
import subprocess
from typing import Optional, Union, List
import logging
from pathlib import Path
import re
import json
import aiofiles
import yt_dlp
try:
    from pytube import YouTube  # optional, best-effort only
except Exception:
    YouTube = None  # type: ignore
from ..stores.models import Document
from .video import VideoLoader


_YT_ID_RE = re.compile(r"(?:v=|\/)([0-9A-Za-z_-]{11})")


def extract_video_id(url: str) -> Optional[str]:
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


logging.getLogger("yt_dlp").setLevel(logging.WARNING)
logging.getLogger("h5py._conv").setLevel(logging.WARNING)
logging.getLogger("tensorflow").setLevel(logging.WARNING)

class YoutubeLoader(VideoLoader):
    """
    Loader for Youtube videos.
    """

    def _ensure_video_dir(self, path: Optional[Union[str, Path]]) -> Path:
        """
        Normalize/ensure a usable download directory.
        Priority: explicit arg > self._video_path > ./videos
        """
        if isinstance(path, (str, Path)) and path:
            p = Path(path)
        else:
            default = getattr(self, "_video_path", None)
            if isinstance(default, (str, Path)) and default:
                p = Path(default)
            else:
                p = Path.cwd() / "videos"
                self._video_path = p
        p.mkdir(parents=True, exist_ok=True)
        self._video_path = p
        return p

    def get_video_info(self, url: str) -> dict:
        # Primary: yt-dlp (no download)
        try:
            ydl_opts = {"quiet": True, "noprogress": True, "skip_download": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            upload_date = info.get("upload_date")  # YYYYMMDD
            publish = (
                f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]} 00:00:00"
                if upload_date else "Unknown"
            )
            vid = info.get("id") or extract_video_id(url) or "unknown"
            return {
                "url": url,
                "video_id": vid,
                "watch_url": info.get("webpage_url") or url,
                "embed_url": f"https://www.youtube.com/embed/{vid}" if vid != "unknown" else url,
                "title": info.get("title") or "Unknown",
                "description": info.get("description") or "Unknown",
                "view_count": info.get("view_count") or 0,
                "publish_date": publish,
                "author": info.get("uploader") or info.get("channel") or "Unknown",
            }
        except Exception as e:
            self.logger.error(f"yt-dlp metadata failed for {url}: {e}")

        # Best-effort fallback: pytube (optional)
        if YouTube:
            try:
                yt = YouTube(url)
                return {
                    "url": url,
                    "video_id": yt.video_id or extract_video_id(url) or "unknown",
                    "watch_url": yt.watch_url or url,
                    "embed_url": yt.embed_url or url,
                    "title": yt.title or "Unknown",
                    "description": yt.description or "Unknown",
                    "view_count": yt.views or 0,
                    "publish_date": yt.publish_date.strftime("%Y-%m-%d %H:%M:%S") if yt.publish_date else "Unknown",
                    "author": yt.author or "Unknown",
                }
            except Exception as e2:
                self.logger.error(f"pytube fallback failed for {url}: {e2}")

        # Final fallback
        vid = extract_video_id(url) or "unknown"
        return {
            "url": url,
            "video_id": vid,
            "watch_url": url,
            "embed_url": f"https://www.youtube.com/embed/{vid}" if vid != "unknown" else url,
            "title": "Unknown",
            "description": "Unknown",
            "view_count": 0,
            "publish_date": "Unknown",
            "author": "Unknown",
        }

    def download_audio_wav(self, url: str, path: Optional[Union[str, Path]] = None) -> Path:
        """
        Download best audio and convert to WAV (16 kHz mono) via ffmpeg (required by yt-dlp).
        Returns the final .wav Path.
        """
        out_dir = self._ensure_video_dir(path)
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "noprogress": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "0"},
            ],
            # enforce mono 16k
            "postprocessor_args": ["-ac", "1", "-ar", "16000"],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # final file is same basename with .wav
            wav_path = Path(ydl.prepare_filename(info)).with_suffix(".wav")
        if not wav_path.exists():
            # try to find the newest .wav if ext varied
            candidates = list((out_dir).glob("*.wav"))
            wav_path = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
        if not wav_path or not wav_path.exists():
            raise ValueError("WAV file not produced by yt-dlp/ffmpeg")
        return wav_path

    def download_video(self, url: str, path: Path) -> Path:
        """
        Downloads a video from a URL using yt-dlp with enhanced error handling.

        Args:
            url (str): The URL of the video to download.
            path (Path): The directory where the video will be saved.
        """
        try:
            self.logger.debug(f"Starting video download for: {url}")
            path = self._ensure_video_dir(path)
            self.logger.debug(f"Download path: {path}")

            # Ensure path exists
            path.mkdir(parents=True, exist_ok=True)

            ydl_opts = {
                "noplaylist": True,
                "format": "bv*[height<=720]+ba/b[height<=720]/b",
                "outtmpl": str(path / "%(title)s.%(ext)s"),
                "merge_output_format": "mp4",   # or "mkv"
                "quiet": True,
                "noprogress": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = Path(ydl.prepare_filename(info))
            # return file_path

        except subprocess.TimeoutExpired:
            self.logger.error("Timeout getting filename from yt-dlp")
            raise ValueError("Timeout getting video filename")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"yt-dlp get-filename failed: {e}")
            self.logger.error(f"yt-dlp stderr: {e.stderr}")
        except FileNotFoundError:
            raise ValueError("yt-dlp not found on PATH. Please install yt-dlp.")

        try:
            # raw_name = result.stdout.strip().splitlines()[-1].strip()
            # candidate = Path(raw_name)
            # file_path = candidate if candidate.is_absolute() else (path / candidate)

            # Already downloaded?
            if file_path.exists():
                self.logger.info(f"Video already downloaded: {file_path.name}")
                return file_path

            self.logger.info(f"Downloading video: {file_path.name}")

            dl_cmd = [
                "yt-dlp",
                "--no-playlist",
                "--format", "best[height<=720]/best",  # prefer <=720p; fallback best
                "-o", "%(title)s.%(ext)s",
                "-P", str(path),
                url
            ]
            self.logger.debug(f"Download command: {' '.join(dl_cmd)}")
            subprocess.run(
                dl_cmd,
                check=True,
                timeout=600,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            if not file_path.exists():
                # Sometimes container chooses a different ext; re-probe actual filename in folder by id or title
                # Simple fallback: pick the newest file in the dir
                latest = max(path.glob(f"{file_path.stem}.*"), key=lambda p: p.stat().st_mtime, default=None)
                if not latest:
                    raise ValueError(f"Downloaded file not found: {file_path}")
                file_path = latest

            self.logger.info(f"Successfully downloaded video: {file_path}")
            return file_path

        except subprocess.TimeoutExpired:
            self.logger.error("Timeout downloading video with yt-dlp")
            raise ValueError("Timeout downloading video")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error downloading video with yt-dlp: {e}")
            raise ValueError(f"Unable to Download Video: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in download_video: {e}")
            raise ValueError(f"Unexpected error downloading video: {e}")

    async def save_file_async(self, file_path: Path, content: Union[str, bytes]) -> None:
        """Async file saving utility."""
        mode = 'wb' if isinstance(content, bytes) else 'w'
        encoding = None if isinstance(content, bytes) else 'utf-8'

        async with aiofiles.open(str(file_path), mode=mode, encoding=encoding) as f:
            await f.write(content)

    async def read_file_async(self, file_path: Path) -> str:
        """Async file reading utility."""
        async with aiofiles.open(str(file_path), 'r', encoding='utf-8') as f:
            return await f.read()

    async def load_video(
        self,
        url: str,
        video_title: str,
        transcript: Optional[Union[str, None]] = None
    ) -> List[Document]:
        """
        Async method to load video and create documents.
        """
        # Get video metadata
        video_info = self.get_video_info(url)

        if transcript is None:
            try:
                documents = []
                docs = []

                # Download video
                if self._download_video:
                    file_path = await asyncio.get_running_loop().run_in_executor(
                        None, self.download_video, url, self._video_path
                    )
                    audio_path = file_path.with_suffix('.wav')
                    # Extract audio
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.extract_audio, file_path, audio_path
                    )
                else:
                    # Download bestaudio → WAV (16k mono)
                    audio_path = await asyncio.get_running_loop().run_in_executor(
                        None, self.download_audio_wav, url, self._video_path
                    )

                transcript_path = audio_path.with_suffix('.vtt')

                # Get transcript using Whisper
                transcript_whisper = await asyncio.get_event_loop().run_in_executor(
                    None, self.get_whisper_transcript, audio_path
                )
                if not transcript_whisper or not transcript_whisper.get('text'):
                    raise ValueError("Transcription failed or empty")

                transcript_text = transcript_whisper['text']

                # Generate summary
                try:
                    summary = await self.summary_from_text(transcript_text)
                except Exception:
                    summary = ''

                # Metadata
                base_metadata = {
                    "url": url,
                    "source": url,
                    "filename": video_title or video_info.get("title") or url,
                    "question": '',
                    "answer": '',
                    "source_type": self._source_type,
                    "type": "video_transcript",
                    "summary": f"{summary!s}",
                    "document_meta": {
                        "language": self._language,
                        "title": video_title or video_info.get("title") or url,
                        "docinfo": video_info,
                    },
                }

                if self.topics:
                    base_metadata["document_meta"]['topic_tags'] = self.topics

                # Create main transcript document
                doc = Document(
                    page_content=transcript_text,
                    metadata=base_metadata.copy()
                )
                documents.append(doc)

                # Create VTT document
                vtt_content = self.transcript_to_vtt(transcript_whisper, transcript_path)
                if vtt_content:
                    vtt_doc = Document(
                        page_content=vtt_content,
                        metadata=base_metadata.copy()
                    )
                    documents.append(vtt_doc)

                # Create individual dialog chunk documents
                dialogs = self.transcript_to_blocks(transcript_whisper)
                for chunk in dialogs:
                    chunk_metadata = base_metadata.copy()
                    chunk_metadata["document_meta"].update({
                        "start": f"{chunk['start_time']}",
                        "end": f"{chunk['end_time']}",
                        "id": f"{chunk['id']}",
                    })

                    doc = Document(
                        page_content=chunk['text'],
                        metadata=chunk_metadata
                    )
                    docs.append(doc)

                documents.extend(docs)
                return documents

            except Exception as e:
                self.logger.warning(f"Error processing video {url}: {e}")
                # Fallback to basic processing without chunks
                return await self._fallback_processing(url, video_info)

        else:
            # Load transcript from file
            if isinstance(transcript, (str, Path)):
                transcript_content = await self.read_file_async(Path(transcript))
            else:
                transcript_content = transcript

            if transcript_content:
                try:
                    summary = await self.summary_from_text(transcript_content)
                except Exception as e:
                    self.logger.warning(f"Error summarizing transcript for {url}: {e}")
                    summary = ''

                metadata = {
                    "source": url,
                    "url": url,
                    "filename": video_title,
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
                    page_content=transcript_content,
                    metadata=metadata
                )
                return [doc]

        return []

    async def _fallback_processing(self, url: str, video_info: dict) -> List[Document]:
        try:
            audio_path = await asyncio.get_running_loop().run_in_executor(
                None, self.download_audio_wav, url, self._video_path
            )
            transcript_result = await asyncio.get_running_loop().run_in_executor(
                None, self.get_whisper_transcript, audio_path
            )
            if not transcript_result:
                self.logger.warning(f"Unable to load Youtube Video {url}")
                return []

            transcript_text = transcript_result['text']
            try:
                summary = await self.summary_from_text(transcript_text)
            except Exception:
                summary = ''
            metadata = {
                "source": url,
                "url": url,
                "source_type": self._source_type,
                "summary": f"{summary!s}",
                "filename": video_info.get('title', 'Unknown'),
                "question": '',
                "answer": '',
                "type": "video_transcript",
                "document_meta": video_info,
            }
            if self.topics:
                metadata['document_meta']['topic_tags'] = self.topics

            return [Document(page_content=transcript_text, metadata=metadata)]
        except Exception as e:
            self.logger.error(f"Fallback processing failed for {url}: {e}")
            return []

    async def extract_video(self, url: str) -> dict:
        """
        Extract video and return metadata with file paths.
        """
        # Get video metadata
        video_info = self.get_video_info(url)

        # Download video
        file_path = self.download_video(url, self._video_path)
        audio_path = file_path.with_suffix('.wav')
        transcript_path = file_path.with_suffix('.txt')
        vtt_path = file_path.with_suffix('.vtt')
        summary_path = file_path.with_suffix('.summary')

        # Extract audio
        await asyncio.get_event_loop().run_in_executor(
            None, self.extract_audio, file_path, audio_path
        )

        # Get transcript
        transcript_whisper = await asyncio.get_event_loop().run_in_executor(
            None, self.get_whisper_transcript, audio_path
        )
        transcript_text = transcript_whisper['text']

        # Generate summary
        try:
            summary = await self.summary_from_text(transcript_text)
            await self.save_file_async(summary_path, summary.encode('utf-8'))
        except Exception:
            summary = ''

        # Create VTT format
        vtt_content = self.transcript_to_vtt(transcript_whisper, vtt_path)

        # Save transcript
        await self.save_file_async(transcript_path, transcript_text.encode('utf-8'))

        # Create metadata
        metadata = {
            "url": f"{url}",
            "source": f"{url}",
            "source_type": self._source_type,
            'type': 'video_transcript',
            "summary": f"{summary!s}",
            "video_info": video_info,
            "transcript": transcript_path,
            "summary_file": summary_path,
            "vtt": vtt_path,
            "audio": audio_path,
            "video": file_path
        }

        return metadata

    async def extract(self) -> List[dict]:
        """
        Extract all videos and return metadata.
        """
        documents = []
        tasks = []

        # Create async tasks for all URLs
        for url in self.urls:
            task = self.extract_video(url)
            tasks.append(task)

        # Run all extractions concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Error extracting video: {result}")
            else:
                documents.append(result)

        return documents
