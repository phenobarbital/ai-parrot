from typing import List
from abc import abstractmethod
from pathlib import Path
import subprocess
from ..stores.models import Document
from .basevideo import BaseVideoLoader


class VideoLoader(BaseVideoLoader):
    """
    Generating Video transcripts from URL Videos.
    """
    def download_video(self, url: str, path: str) -> Path:
        """
        Downloads a video from a URL using yt-dlp.

        Args:
            video_url (str): The URL of the video to download.
            output_path (str): The directory where the video will be saved.
        """
        try:
            command = [
                "yt-dlp",
                "--get-filename",
                "-o",
                str(path / "%(title)s.%(ext)s"),
                url
            ]
            result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
        except Exception as e:
            try:
                command = [
                    "yt-dlp",
                    "--get-filename",
                    url
                ]
                result = subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.PIPE,
                    text=True
                )
            except Exception as e:
                raise ValueError(
                    f"Unable to Download Video: {e}"
                )
        try:
            filename = result.stdout.strip()  # Remove any trailing newline characters
            print('FILENAME > ', filename)
            file_path = path.joinpath(filename)
            if file_path.exists():
                print(f"Video already downloaded: {filename}")
                return file_path
            print(f"Downloading video: {filename}")
            # after extracted filename, download the video
            command = [
                "yt-dlp",
                url,
                "-o",
                str(path / "%(title)s.%(ext)s")
            ]
            subprocess.run(command, check=True)
            return file_path
        except subprocess.CalledProcessError as e:
            print(f"Error downloading video: {e}")


    async def _load(self, source: str, **kwargs) -> List[Document]:
        documents = []
        transcript = None
        video_title = source
        if isinstance(source, dict):
            path = list(source.keys())[0]
            parts = source[path]
            if isinstance(parts, str):
                video_title = parts
            elif isinstance(parts, dict):
                video_title = parts['title']
        docs = await self.load_video(source, video_title, transcript)
        documents.extend(docs)
        # return documents
        return documents

    @abstractmethod
    async def load_video(self, url: str, video_title: str, transcript: str) -> list:
        pass

    def parse(self, source):
        pass
