# WhisperX Setup Guide for AI-Parrot

## Prerequisites

### System Requirements
- Ubuntu 20.04+ or Debian 11+ (for GPU support)
- Python 3.10 or 3.11
- NVIDIA GPU with CUDA support (optional, for faster processing)
- At least 8GB RAM (16GB recommended for larger models)

### NVIDIA GPU Setup (Optional)
If you have an NVIDIA GPU:
1. Install NVIDIA drivers (version 525+ recommended)
2. Install CUDA Toolkit 11.8 or 12.1
3. The Makefile will handle cuDNN installation

## Installation

### Quick Setup
```bash
# Clone the repository
git clone https://github.com/your-org/ai-parrot.git
cd ai-parrot

# Install uv for faster package management
make install-uv

# Create virtual environment
make venv
source .venv/bin/activate

# Install WhisperX with all dependencies
make install-whisperx

# Test installation
make test-whisperx
```

### Manual Installation
If the automatic installation fails:

```bash
# 1. Install system dependencies
sudo apt-get update
sudo apt-get install -y ffmpeg libavutil-dev libavformat-dev libavcodec-dev

# 2. Install cuDNN (for NVIDIA GPUs)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-ubuntu2004.pin
sudo mv cuda-ubuntu2004.pin /etc/apt/preferences.d/cuda-repository-pin-600
export last_public_key=3bf863cc
sudo apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/${last_public_key}.pub
sudo add-apt-repository "deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/ /"
sudo apt-get update
sudo apt-get install libcudnn8 libcudnn8-dev

# 3. Install Python packages
uv pip install torch==2.6.0 torchaudio==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu118
uv pip install whisperx==3.4.2
uv pip install pyannote-audio==3.4.0
```

## Verified Working Versions

The following combination has been tested and works:
- `torch==2.6.0`
- `torchaudio==2.6.0`
- `torchvision==0.21.0`
- `whisperx==3.4.2`
- `pyannote-audio==3.4.0`
- `nvidia-cudnn-cu12==9.1.0.70`
- `libcudnn8` (system package)

## Usage Example

```python
from parrot.loaders import WhisperXLoader

# Initialize loader
loader = WhisperXLoader(
    model_size="base",  # tiny, base, small, medium, large-v2, large-v3
    device="cuda"       # or "cpu"
)

# Transcribe audio file
result = loader.transcribe(
    "path/to/audio.mp3",
    language="en",  # optional, auto-detects if not specified
    align=True      # align timestamps for better accuracy
)

# Convert to documents for RAG
documents = loader.to_documents(result)

# Generate SRT file
loader.to_srt(result, "output.srt")
```

## Troubleshooting

### Common Issues

1. **"libcudnn_ops_infer.so.8: cannot open shared object file"**
   - Solution: Run `make install-system-deps` to install cuDNN

2. **"undefined symbol" errors with torchaudio**
   - Solution: Ensure torch and torchaudio versions match (both 2.6.0)

3. **FFmpeg errors**
   - Solution: Install FFmpeg with `sudo apt-get install ffmpeg`

4. **Out of memory errors**
   - Use a smaller model (tiny or base)
   - Reduce batch_size
   - Use CPU mode if GPU memory is limited

### Checking Installation

```bash
# Check system dependencies
make check-deps

# Check CUDA/GPU status
make cuda-info

# Test WhisperX import
python -c "import whisperx; print('WhisperX OK')"

# Test model loading
make test-whisperx-transcribe
```

## Performance Tips

1. **Model Selection**:
   - `tiny`: Fastest, lowest accuracy (~39MB)
   - `base`: Good balance (~74MB)
   - `small`: Better accuracy (~244MB)
   - `medium`: High accuracy (~769MB)
   - `large-v2/v3`: Best accuracy (~1550MB)

2. **GPU Acceleration**:
   - Use `compute_type="float16"` for faster GPU processing
   - Use `compute_type="int8"` for even faster processing (slight accuracy loss)

3. **Batch Processing**:
   - Increase `batch_size` for faster processing of long audio
   - Default is 16, can go up to 32 for GPUs with >8GB memory

## Integration with AI-Parrot

WhisperX is integrated as a loader in AI-Parrot, allowing you to:
- Transcribe audio/video files
- Generate SRT subtitles
- Extract speaker-labeled segments (with pyannote)
- Feed transcripts into RAG pipelines
- Process multiple languages automatically

## License Note

WhisperX uses models that may have specific licensing requirements:
- Whisper models: MIT License
- Pyannote models: May require accepting terms on HuggingFace

Make sure to review and comply with all relevant licenses.
