from collections.abc import Callable
from typing import Any, Union, List
from abc import abstractmethod
from pathlib import Path
from moviepy.editor import VideoFileClip
from transformers import (
    pipeline,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    GenerationConfig
)
from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    WhisperTimeStampLogitsProcessor
)

from langchain.chains.summarize import load_summarize_chain
from langchain.text_splitter import (
    TokenTextSplitter,
)
from .abstract import AbstractLoader


def extract_video_id(url):
    parts = url.split("?v=")
    video_id = parts[1].split("&")[0]
    return video_id


class BaseVideoLoader(AbstractLoader):
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
        super().__init__(tokenizer, text_splitter, source_type, **kwargs)
        self.urls = urls
        self._task = kwargs.get('task', "automatic-speech-recognition")
        # Topics:
        self.topics: list = kwargs.get('topics', [])
        self._model_size: str = kwargs.get('model_size', 'medium')
        self.summarization_model = "facebook/bart-large-cnn"
        self._model_name: str = kwargs.get('model_name', 'whisper')
        self.summarizer = pipeline(
            "summarization",
            tokenizer=AutoTokenizer.from_pretrained(
                self.summarization_model
            ),
            model=AutoModelForSeq2SeqLM.from_pretrained(
                self.summarization_model
            ),
            device=self._get_device()
        )
        # language:
        self._language = language
        # directory:
        if isinstance(video_path, str):
            self._video_path = Path(video_path).resolve()
        self._video_path = video_path

    def transcript_to_vtt(self, transcript: str, transcript_path: Path) -> str:
        """
        Convert a transcript to VTT format.
        """
        vtt = "WEBVTT\n\n"
        for i, chunk in enumerate(transcript['chunks'], start=1):
            start, end = chunk['timestamp']
            text = chunk['text'].replace("\n", " ")  # Replace newlines in text with spaces

            if start is None or end is None:
                print(f"Warning: Missing timestamp for chunk {i}, skipping this chunk.")
                continue

            # Convert timestamps to WebVTT format (HH:MM:SS.MMM)
            start_vtt = f"{int(start // 3600):02}:{int(start % 3600 // 60):02}:{int(start % 60):02}.{int(start * 1000 % 1000):03}"
            end_vtt = f"{int(end // 3600):02}:{int(end % 3600 // 60):02}:{int(end % 60):02}.{int(end * 1000 % 1000):03}"

            vtt += f"{i}\n{start_vtt} --> {end_vtt}\n{text}\n\n"
        # Save the VTT file
        try:
            with open(str(transcript_path), "w") as f:
                f.write(vtt)
            print(f'Saved VTT File on {transcript_path}')
        except Exception as exc:
            print(f"Error saving VTT file: {exc}")
        return vtt

    def format_timestamp(self, seconds):
        # This helper function takes the total seconds and formats it into hh:mm:ss,ms
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds % 1) * 1000)
        seconds = int(seconds)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

    def transcript_to_blocks(self, transcript: str) -> list:
        """
        Convert a transcript to blocks.
        """
        blocks = []
        for i, chunk in enumerate(transcript['chunks'], start=1):
            current_window = {}
            start, end = chunk['timestamp']
            if start is None or end is None:
                print(f"Warning: Missing timestamp for chunk {i}, skipping this chunk.")
                continue

            start_srt = self.format_timestamp(start)
            end_srt = self.format_timestamp(end)
            text = chunk['text'].replace("\n", " ")  # Replace newlines in text with spaces
            current_window['id'] = i
            current_window['start_time'] = start_srt
            current_window['end_time'] = end_srt
            current_window['text'] = text
            blocks.append(current_window)
        return blocks

    def transcript_to_srt(self, transcript: str) -> str:
        """
        Convert a transcript to SRT format.
        """
        # lines = transcript.split("\n")
        srt = ""
        for i, chunk in enumerate(transcript['chunks'], start=1):
            start, end = chunk['timestamp']
            text = chunk['text'].replace("\n", " ")  # Replace newlines in text with spaces
            # Convert start and end times to SRT format HH:MM:SS,MS
            start_srt = f"{start // 3600:02}:{start % 3600 // 60:02}:{start % 60:02},{int(start * 1000 % 1000):03}"
            end_srt = f"{end // 3600:02}:{end % 3600 // 60:02}:{end % 60:02},{int(end * 1000 % 1000):03}"
            srt += f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n"
        return srt

    def chunk_text(self, text, chunk_size, tokenizer):
        # Tokenize the text and get the number of tokens
        tokens = tokenizer.tokenize(text)
        # Split the tokens into chunks
        for i in range(0, len(tokens), chunk_size):
            yield tokenizer.convert_tokens_to_string(
                tokens[i:i+chunk_size]
            )

    def get_summary(self, documents: list) -> str:
        """
        Get a summary of a text.
        """
        try:
            splitter = TokenTextSplitter(
                chunk_size=5000,
                chunk_overlap=100,
            )
            summarize_chain = load_summarize_chain(
                llm=self._llm,
                chain_type="refine"
            )
            chunks = splitter.split_documents(documents)
            summary = summarize_chain.invoke(chunks)
            return summary
        except Exception as e:
            print('ERROR in get_summary:', e)
            return ""

    def summarization(self, text: str) -> str:
        """
        Get a summary of a text considering token limits.
        """
        try:
            tokenizer = self.summarizer.tokenizer
            # to be safe under the limit
            max_length = tokenizer.model_max_length - 10
            summaries = []
            for text_chunk in self.chunk_text(text, max_length, tokenizer):
                chunk_summary = self.summarizer(
                    text_chunk,
                    max_length=150,
                    min_length=30,
                    do_sample=False)[0]['summary_text']
                summaries.append(chunk_summary)
            return " ".join(summaries)
        except Exception as e:
            print('ERROR in summarization:', e)
            return ""

    def extract_audio(self, video_path, audio_path):
        """
        Extracts the audio from a video file and saves it as an audio file.

        Args:
            video_path (str): Path to the video file.
            audio_path (str): Path where the extracted audio file will be saved.
        """
        if audio_path.exists():
            print(f"Audio already extracted: {audio_path}")
            return
        video_clip = VideoFileClip(str(video_path))
        audio_clip = video_clip.audio
        if not audio_clip:
            return
        audio_clip.write_audiofile(str(audio_path))
        audio_clip.close()
        video_clip.close()

    def get_whisper_transcript(self, audio_path: Path, chunk_length: int = 30):
        # Initialize the Whisper parser
        if self._model_name == 'whisper':
            if self._language == 'en':
                model_name = f"openai/whisper-{self._model_size}.en"
            elif self._language == 'es':
                model_name = f"juancopi81/whisper-{self._model_size}-es"
            else:
                model_name = "openai/whisper-large-v3"
        else:
            model_name = self._model_name

        # Load the model and processor
        model = WhisperForConditionalGeneration.from_pretrained(model_name)
        processor = WhisperProcessor.from_pretrained(model_name)

        # Try to load the generation config, fallback to default if it doesn't exist
        try:
            generation_config = GenerationConfig.from_pretrained(model_name)
        except EnvironmentError:
            print(
                f"Warning: No generation_config.json found for model {model_name}. Using default configuration."
            )
            generation_config = model.generation_config

        # Check and set the no_timestamps_token_id if it doesn't exist
        if not hasattr(model.config, 'no_timestamps_token_id'):
            model.config.no_timestamps_token_id = processor.tokenizer.convert_tokens_to_ids('<|notimestamps|>')

        # Define the generation configuration with WhisperTimeStampLogitsProcessor
        try:
            model.config.logits_processor = [
                WhisperTimeStampLogitsProcessor(generation_config)
            ]
        except Exception:
            model.config.logits_processor = [
                WhisperTimeStampLogitsProcessor(model.config)
            ]

        whisper_pipe = pipeline(
            task=self._task,
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=self._get_device(),
            chunk_length_s=chunk_length,
            use_fast=True
        )
        if audio_path.exists() and audio_path.stat().st_size > 0:
            # Use the parser to extract transcript
            return whisper_pipe(
                str(audio_path),
                return_timestamps=True
            )
        return None

    @abstractmethod
    def load(self) -> list:
        pass

    @abstractmethod
    def load_video(self, url: str, video_title: str, transcript: str) -> list:
        pass

    def parse(self, source):
        pass
