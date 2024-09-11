import os
from pathlib import PurePath, Path
import cv2
from navconfig import BASE_DIR

def extract_frames(
    video_path,
    output_dir: PurePath,
    interval=5
):
    if not output_dir.exists():
        output_dir.mkdir(mode=0o777, parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))

    # Get frames per second (fps) of the video
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(fps * interval)

    frame_count = 0
    success, frame = cap.read()

    while success:
        if frame_count % frame_interval == 0:
            frame_name = f"frame_{frame_count}.jpg"
            frame_path = os.path.join(output_dir, frame_name)
            cv2.imwrite(frame_path, frame)
            print(f"Extracted {frame_name}")

        frame_count += 1
        success, frame = cap.read()

    cap.release()
    print("Finished extracting frames.")

# Usage
if __name__ == '__main__':
    video_file = BASE_DIR.joinpath('documents', 'video_2024-09-11_19-43-58.mp4')
    output_folder = BASE_DIR.joinpath('documents', 'extracted_frames')
    extract_frames(video_file, output_folder, interval=5)
