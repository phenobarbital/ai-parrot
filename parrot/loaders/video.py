from collections.abc import Callable
from typing import Any, Union, List
from abc import abstractmethod
from pathlib import Path
import subprocess
from .basevideo import BaseVideoLoader


class VideoLoader(BaseVideoLoader):
    """
    Generating Video transcripts from Videos.
    """
    _extension = ['.youtube']
    encoding = 'utf-8'
    chunk_size = 768

    def __init__(
        self,
        urls: List[str],
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'video',
        language: str = "en",
        video_path: Union[str, Path] = None,
        **kwargs
    ):
        super().__init__(
            urls,
            tokenizer,
            text_splitter,
            source_type,
            language=language,
            video_path=video_path,
            **kwargs
        )

    def download_video(self, url: str, path: str) -> Path:
        """
        Downloads a video from a URL using yt-dlp.

        Args:
            video_url (str): The URL of the video to download.
            output_path (str): The directory where the video will be saved.
        """
        command = [
            "yt-dlp",
            "--get-filename",
            url
        ]
        try:
            result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
            filename = result.stdout.strip()  # Remove any trailing newline characters
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
                str(file_path)
            ]
            subprocess.run(command, check=True)
            return file_path
        except subprocess.CalledProcessError as e:
            print(f"Error downloading video: {e}")


    def load(self) -> list:
        documents = []
        for url in self.urls:
            transcript = None
            if isinstance(url, dict):
                path = list(url.keys())[0]
                parts = url[path]
                if isinstance(parts, str):
                    video_title = parts
                elif isinstance(parts, dict):
                    video_title = parts['title']
                    transcript = parts.get('transcript', None)
                url = path
            else:
                video_title = url
            docs = self.load_video(url, video_title, transcript)
            documents.extend(docs)
        # return documents
        return self.split_documents(documents)

    @abstractmethod
    def load_video(self, url: str, video_title: str, transcript: str) -> list:
        pass

    def parse(self, source):
        pass
