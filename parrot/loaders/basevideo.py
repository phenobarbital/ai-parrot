from collections.abc import Callable
from typing import Any, Union, List, Optional
from abc import abstractmethod
from pathlib import Path
from moviepy.editor import VideoFileClip
from pydub import AudioSegment
import torch
from transformers import (
    pipeline,
    AutoModelForSpeechSeq2Seq,
    AutoProcessor,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
)
from ..stores.models import Document
from .abstract import AbstractLoader


def extract_video_id(url):
    parts = url.split("?v=")
    video_id = parts[1].split("&")[0]
    return video_id


class BaseVideoLoader(AbstractLoader):
    """
    Generating Video transcripts from Videos.
    """
    extensions: List[str] = ['.youtube']
    encoding = 'utf-8'

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'video',
        language: str = "en",
        video_path: Union[str, Path] = None,
        download_video: bool = True,
        **kwargs
    ):
        self._download_video: bool = download_video
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        if isinstance(source, str):
            self.urls = [source]
        else:
            self.urls = source
        self._task = kwargs.get('task', "automatic-speech-recognition")
        # Topics:
        self.topics: list = kwargs.get('topics', [])
        self._model_size: str = kwargs.get('model_size', 'medium')
        self.summarization_model = "facebook/bart-large-cnn"
        self._model_name: str = kwargs.get('model_name', 'whisper')
        device, _, dtype = self._get_device()
        self.summarizer = pipeline(
            "summarization",
            tokenizer=AutoTokenizer.from_pretrained(
                self.summarization_model
            ),
            model=AutoModelForSeq2SeqLM.from_pretrained(
                self.summarization_model
            ),
            device=device,
            torch_dtype=dtype,
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
            start_vtt = f"{int(start // 3600):02}:{int(start % 3600 // 60):02}:{int(start % 60):02}.{int(start * 1000 % 1000):03}"  # noqa
            end_vtt = f"{int(end // 3600):02}:{int(end % 3600 // 60):02}:{int(end % 60):02}.{int(end * 1000 % 1000):03}"  # noqa

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

    def extract_audio(
        self,
        video_path: Path,
        audio_path: Path,
        compress_speed: bool = False,
        output_path: Optional[Path] = None,
        speed_factor: float = 1.5
    ):
        """
        Extract audio from video. Prefer WAV 16k mono for Whisper.
        """
        video_path = Path(video_path)
        audio_path = Path(audio_path)

        if audio_path.exists():
            print(f"Audio already extracted: {audio_path}")
            return

        # Extract as WAV 16k mono PCM
        print(f"Extracting audio (16k mono WAV) to: {audio_path}")
        clip = VideoFileClip(str(video_path))
        if not clip.audio:
            print("No audio found in video.")
            clip.close()
            return

        # moviepy/ffmpeg: pcm_s16le, 16k, mono
        # Ensure audio_path has .wav
        if audio_path.suffix.lower() != ".wav":
            audio_path = audio_path.with_suffix(".wav")

        clip.audio.write_audiofile(
            str(audio_path),
            fps=16000,
            nbytes=2,
            codec="pcm_s16le",
            ffmpeg_params=["-ac", "1"]
        )
        clip.audio.close()
        clip.close()

        # Optional speed compression (still output WAV @16k mono)
        if compress_speed:
            print(f"Compressing audio speed by factor: {speed_factor}")
            audio = AudioSegment.from_file(audio_path)
            sped = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * speed_factor)})
            sped = sped.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            sped.export(str(output_path or audio_path), format="wav")
            print(f"Compressed audio saved to: {output_path or audio_path}")
        else:
            print(f"Audio extracted: {audio_path}")

    def get_whisper_transcript(
        self,
        audio_path: Path,
        chunk_length: int = 30,
        word_timestamps: bool = False
    ):
        """
        Transcribe `audio_path` with Hugging Face Transformers Whisper pipeline, returning
        chunk timestamps (and optionally word-level timestamps).

        Returns a dict like:
        {
            "text": "...",
            "chunks": [{"text": "...", "timestamp": (start, end)}, ...]
        }
        so your existing transcript_to_vtt/SRT functions keep working.
        """
        # 1) Resolve model id
        # Default to multilingual Large v3 if nothing explicit is provided.
        # Use English-only checkpoints when asked for EN and <= medium size.
        lang = (self._language or "en").lower()

        if self._model_name in (None, "", "whisper", "openai/whisper"):
            size = (self._model_size or "medium").lower()
            if lang == "en" and size in {"tiny", "base", "small", "medium"}:
                model_id = f"openai/whisper-{size}.en"
            elif size == 'turbo':
                model_id = "openai/whisper-large-v3-turbo"
            else:
                # Large-v3 (or turbo) are multilingual and strong defaults.
                # If you want maximum speed, switch to "-v3-turbo".
                model_id = "openai/whisper-large-v3"
        else:
            model_id = self._model_name

        # 2) Safety checks
        audio_path = Path(audio_path)
        if not (audio_path.exists() and audio_path.stat().st_size > 0):
            return None

        # 3) Device + dtype
        device_idx, dev, torch_dtype = self._get_device()  # expect -1 (CPU) or 0/1/...

        # 4) Load model & processor
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True
        ).to(dev)

        processor = AutoProcessor.from_pretrained(model_id)

        # 5) Properly set language/task via forced decoder prompt ids
        generate_kwargs = {}
        try:
            forced_ids = processor.get_decoder_prompt_ids(language=lang, task="transcribe")
            if forced_ids:
                generate_kwargs["forced_decoder_ids"] = forced_ids
        except Exception:
            # Some community checkpoints might not expose this utility; it's fine to skip.
            pass

        # 6) Build the pipeline
        asr = pipeline(
            task="automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=device_idx,
            chunk_length_s=chunk_length,  # long-form chunking
            torch_dtype=torch_dtype,      # <-- fp16/bf16 on CUDA
            batch_size=8,                 # adjust for your VRAM
        )

        # 7) Run — choose chunk timestamps (default) or word-level timestamps
        ts_param = "word" if word_timestamps else True  # returns `chunks` either way
        return asr(str(audio_path), return_timestamps=ts_param, generate_kwargs=generate_kwargs)


    @abstractmethod
    async def _load(self, source: str, **kwargs) -> List[Document]:
        pass

    @abstractmethod
    async def load_video(self, url: str, video_title: str, transcript: str) -> list:
        pass
