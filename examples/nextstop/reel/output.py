"""
make_video_aspect.py

Like before, but:
- TARGET_ASPECT lets you set 16:9, 9:16, 1:1, 4:5, etc.
- RESIZE_MODE: "crop" (fill & center-crop) or "letterbox" (fit & pad)
"""
from pathlib import Path
from moviepy import (
    ImageClip, VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeAudioClip, CompositeVideoClip, vfx
)
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
from navconfig import BASE_DIR

# -----------------------------
# CONFIG
# -----------------------------
BASE_OUTPUT_DIR = BASE_DIR / "examples" / "nextstop" / "reel" / "outputs"
OUTPUT_PATH = BASE_OUTPUT_DIR / "final_video.mp4"

# ➜ Choose your aspect ratio and final size
TARGET_ASPECT = "9:16"          # e.g., "16:9", "9:16", "1:1", "4:5"
LONG_SIDE = 1920                # longest dimension in pixels (e.g., 1920 → 1080x1920 for 9:16)
RESIZE_MODE = "crop"            # "crop" | "letterbox"
TARGET_FPS = 30

# Defaults
CLIP_DEFAULT_DURATION = 4.0
CROSSFADE_DUR = 0.6
KEN_BURNS = True
KEN_BURNS_ZOOM = 1.08

# Audio levels
VOICE_GAIN = 1.0
MUSIC_GAIN = 0.10
MUSIC_FADE_IN = 2.0
MUSIC_FADE_OUT = 2.0

# Media
images = [
    BASE_OUTPUT_DIR / "generated_image_270f56cf-04ae-4523-843d-fb7de0b35ddb.jpg",
    BASE_OUTPUT_DIR / "generated_image_4457dfa3-dd0c-46e3-b01c-79a34fc86428.jpg",
    BASE_OUTPUT_DIR / "generated_image_143247d8-6578-4e42-ad59-689b941e0412.jpg",
    BASE_OUTPUT_DIR / "generated_image_f2a58e57-5858-4ad8-a9e8-df327b5fedc1.jpg",
]
videos = [
    BASE_OUTPUT_DIR / "video_20251001_005241_0.mp4",  # intro logo
    BASE_OUTPUT_DIR / "video_20251001_001224_0.mp4",
    BASE_OUTPUT_DIR / "video_20251001_001659_0.mp4",
    BASE_OUTPUT_DIR / "video_20250930_234852_0.mp4",
    BASE_OUTPUT_DIR / "video_20251001_000356_0.mp4",
    BASE_OUTPUT_DIR / "video_20251001_003602_0.mp4",  # ending logo
]
podcast_voice = BASE_OUTPUT_DIR / "podcast_voice.wav"
background_music = BASE_OUTPUT_DIR / "Eldar Kedem - Walking Around.mp3"
image_durations = [3.5, 3.5, 3.5, 3.5]  # seconds, or None to use default

# -----------------------------
# ASPECT HELPERS
# -----------------------------
def parse_aspect(s: str) -> tuple[int, int]:
    a, b = s.split(":")
    return int(a), int(b)

def compute_target_size(aspect: str, long_side: int) -> tuple[int, int]:
    aw, ah = parse_aspect(aspect)
    if aw >= ah:
        # landscape-ish → width is long side
        w = long_side
        h = int(round(long_side * ah / aw))
    else:
        # portrait-ish → height is long side
        h = long_side
        w = int(round(long_side * aw / ah))
    # Ensure even dimensions for H.264
    w += w % 2
    h += h % 2
    return w, h

TARGET_W, TARGET_H = compute_target_size(TARGET_ASPECT, LONG_SIDE)

def fit_clip_to_target(clip, mode="crop"):
    """
    mode="crop": scale to cover, then center-crop to TARGET_WxTARGET_H
    mode="letterbox": scale to fit, then pad with black to TARGET_WxTARGET_H
    """
    src_aspect = clip.w / clip.h
    tgt_aspect = TARGET_W / TARGET_H

    if mode == "crop":
        # Scale to cover (like CSS background-size: cover)
        if src_aspect >= tgt_aspect:
            # too wide → match height
            clip = clip.resized(height=TARGET_H)
            extra_w = clip.w - TARGET_W
            x_center = clip.w / 2
            clip = clip.cropped(x1=x_center - TARGET_W/2, y1=0,
                               x2=x_center + TARGET_W/2, y2=TARGET_H)
        else:
            # too tall → match width
            clip = clip.resized(width=TARGET_W)
            extra_h = clip.h - TARGET_H
            y_center = clip.h / 2
            clip = clip.cropped(x1=0, y1=y_center - TARGET_H/2,
                               x2=TARGET_W, y2=y_center + TARGET_H/2)
        return clip

    # letterbox: scale to fit then pad
    if src_aspect >= tgt_aspect:
        # too wide → match width, pad top/bottom
        clip = clip.resized(width=TARGET_W)
    else:
        # too tall → match height, pad left/right
        clip = clip.resized(height=TARGET_H)

    # Pad with black bars
    return clip.with_effects([vfx.Margin(
        left=(TARGET_W - clip.w) // 2,
        right=(TARGET_W - clip.w) - (TARGET_W - clip.w) // 2,
        top=(TARGET_H - clip.h) // 2,
        bottom=(TARGET_H - clip.h) - (TARGET_H - clip.h) // 2,
        color=(0, 0, 0)
    )])

# -----------------------------
# CLIP BUILDERS
# -----------------------------
def make_image_clip(path: str, duration: float) -> ImageClip:
    base = ImageClip(str(path)).with_duration(duration)
    clip = fit_clip_to_target(base, RESIZE_MODE)

    if KEN_BURNS:
        # Smooth zoom from 1.0 to KEN_BURNS_ZOOM across duration
        def zoom_factor(t):
            progress = t / max(clip.duration, 1e-6)
            scale = 1.0 + (KEN_BURNS_ZOOM - 1.0) * progress
            return scale
        clip = clip.resized(zoom_factor)

    return clip.with_fps(TARGET_FPS)

def make_video_clip(path: str) -> VideoFileClip:
    base = VideoFileClip(str(path))
    clip = fit_clip_to_target(base, RESIZE_MODE)
    return clip.with_fps(TARGET_FPS)

def build_video_timeline(image_paths, video_paths, image_durs=None, crossfade=CROSSFADE_DUR):
    """
    Build timeline in this order:
      1. First video (intro logo)
      2. First image
      3. Second video
      4. Second image
      ... continue alternating
      N. Last video (ending logo)
    """
    clips = []

    if not video_paths:
        raise ValueError("Need at least one video (intro).")

    # Start with intro video
    clips.append(make_video_clip(video_paths[0]))

    # Interleave images and middle videos
    # videos[1:-1] are the middle videos (between intro and ending)
    middle_videos = video_paths[1:-1] if len(video_paths) > 1 else []

    for idx in range(max(len(image_paths), len(middle_videos))):
        # Add image if available
        if idx < len(image_paths):
            dur = (image_durs[idx] if image_durs and idx < len(image_durs)
                   else CLIP_DEFAULT_DURATION)
            clips.append(make_image_clip(image_paths[idx], dur))

        # Add middle video if available
        if idx < len(middle_videos):
            clips.append(make_video_clip(middle_videos[idx]))

    # End with ending video (if there are at least 2 videos)
    if len(video_paths) > 1:
        clips.append(make_video_clip(video_paths[-1]))

    if not clips:
        raise ValueError("No clips to concatenate.")

    # Apply crossfade
    if crossfade > 0 and len(clips) > 1:
        clips = [clips[0]] + [c.with_effects([vfx.CrossFadeIn(crossfade)]) for c in clips[1:]]
        final = concatenate_videoclips(clips, method="compose", padding=-crossfade)
    else:
        final = concatenate_videoclips(clips, method="compose")

    return final

def build_audio_mix(timeline: CompositeVideoClip,
                    voice_path: str,
                    music_path: str,
                    music_gain=MUSIC_GAIN,
                    voice_gain=VOICE_GAIN,
                    fade_in=MUSIC_FADE_IN,
                    fade_out=MUSIC_FADE_OUT):
    voice = AudioFileClip(str(voice_path)).with_volume_scaled(voice_gain)
    music = (AudioFileClip(str(music_path))
             .with_volume_scaled(music_gain)
             .with_effects([AudioFadeIn(fade_in), AudioFadeOut(fade_out)]))

    # Loop/trim music to match duration
    if music.duration < timeline.duration:
        music = music.with_effects([vfx.Loop(duration=timeline.duration)])
    else:
        music = music.subclipped(0, timeline.duration)

    mixed = CompositeAudioClip([music, voice.with_start(0)]).with_duration(timeline.duration)
    return mixed

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    print(f"Target size: {TARGET_W}x{TARGET_H} ({TARGET_ASPECT}), mode={RESIZE_MODE}")

    video_timeline = build_video_timeline(images, videos, image_durations, crossfade=CROSSFADE_DUR)

    if Path(podcast_voice).exists() and Path(background_music).exists():
        mixed_audio = build_audio_mix(video_timeline, podcast_voice, background_music)
        final = video_timeline.with_audio(mixed_audio)
    elif Path(podcast_voice).exists():
        final = video_timeline.with_audio(
            AudioFileClip(str(podcast_voice)).with_volume_scaled(VOICE_GAIN)
        )
    elif Path(background_music).exists():
        music = (AudioFileClip(str(background_music))
                 .with_volume_scaled(MUSIC_GAIN)
                 .with_effects([AudioFadeIn(MUSIC_FADE_IN), AudioFadeOut(MUSIC_FADE_OUT)]))
        music = music.with_effects([vfx.Loop(duration=video_timeline.duration)])
        final = video_timeline.with_audio(music.with_duration(video_timeline.duration))
    else:
        final = video_timeline

    final.write_videofile(
        str(OUTPUT_PATH),
        codec="libx264",
        audio_codec="aac",
        fps=TARGET_FPS,
        preset="medium",
        threads=4,
        temp_audiofile="__temp_audio.m4a",
        remove_temp=True
    )

    print(f"✅ Done. Wrote: {OUTPUT_PATH}")
