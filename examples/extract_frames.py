import os
from pathlib import PurePath, Path
import cv2
from navconfig import BASE_DIR

def better_resolution(image_path, output_path):
    # Load the super-resolution model (example using the EDSR model)
    sr = cv2.dnn_superres.DnnSuperResImpl_create()

    # Read the model
    path_to_model = 'EDSR_x4.pb'
    # You need to download this model from OpenCV's model zoo
    sr.readModel(path_to_model)

    # Set the model and scale
    sr.setModel("edsr", 4)  # EDSR model with 4x upscaling

    # Read the input image
    image = cv2.imread(image_path)

    # Upscale the image
    upscaled_image = sr.upsample(image)

    # Save the result
    cv2.imwrite(output_path, upscaled_image)
    print(f"Saved super-resolution image: {output_path}")

def extract_frames(
    video_path,
    output_dir: PurePath,
    interval=5,
    upscale_factor=2
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
            # Get the original dimensions
            height, width = frame.shape[:2]
            # Upscale the frame by the given factor
            frame_upscaled = cv2.resize(
                frame,
                (width * upscale_factor, height * upscale_factor),
                interpolation=cv2.INTER_CUBIC
            )
            frame_name = f"frame_{frame_count}.jpg"
            upscaled_name = f"frame_{frame_count}_upscaled.jpg"
            frame_path = os.path.join(output_dir, frame_name)
            upscaled_path = output_dir.joinpath(upscaled_name)
            cv2.imwrite(frame_path, frame_upscaled)
            # better_resolution(frame_path, upscaled_path)
            print(f"Extracted {frame_name}")

        frame_count += 1
        success, frame = cap.read()

    cap.release()
    print("Finished extracting frames.")

# Usage
if __name__ == '__main__':
    video_file = BASE_DIR.joinpath('documents', 'video_2024-09-11_19-43-58.mp4')
    output_folder = BASE_DIR.joinpath('documents', 'extracted_frames')
    extract_frames(video_file, output_folder, interval=2)
