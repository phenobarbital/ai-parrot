from navconfig import BASE_DIR
from parrot.llms.vertex import VertexLLM
from parrot.loaders.videolocal import (
    VideoLocalLoader
)

# Vertex:
vertex = VertexLLM(
    model='gemini-1.5-pro',
    temperature=0.1,
    top_p=0.6,
    top_k=30
)

# Video Loader:
video_dir = BASE_DIR.joinpath(
    'videos',
    'video_2024-09-11_19-43-58.mp4'
)
print(video_dir, video_dir.exists())
video_loader = VideoLocalLoader(
    video_dir,
    source_type='video transcripts',
    llm=vertex.get_llm()
)
try:
    video = video_loader.extract()
    print(video)
except Exception as e:
    print(e)
