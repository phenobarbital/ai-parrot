# Google Media Gen (Imagen/Veo/Nano Banana) REST API Documentation

This documentation details the `/api/v1/google/media` endpoint, designed for high-throughput image and video generation using Google's generative models (including **Veo 3.1** and **Nano Banana**). It provides full support for synchronous Flex Inference, asynchronous batch processing, automated local results archiving, and versatile download modes to simplify UI integration.

---

## 1. Endpoint Overview

* **URL Path**: `/api/v1/google/media`
* **HTTP Method**: `POST`
* **Content-Type**: `application/json`
* **Default Port**: Typically `:8080` (Standard AI-Parrot Server)

---

## 2. Key Capabilities

### A. Single vs. Batch Mode
* **Single Mode (`"batch": false`)**: Standard synchronous generation of one asset (image/video). Returns the file directly as a binary stream/file.
* **Batch Mode (`"batch": true`)**: Generates multiple assets concurrently using `asyncio.gather`. It accepts either a simple list of prompts (`"prompts": [...]`) or a list of complete request configurations (`"requests": [...]`). If multiple files are successfully generated, the endpoint automatically compresses them into a temporary ZIP archive and serves that ZIP file directly.

### B. Flex Inference (`"use_flex": true`)
When generating images using Gemini's native **Nano Banana** models (e.g. `gemini-3.1-flash-image-preview`), passing `"use_flex": true` runs requests under the cost-optimized Flex Inference tier. This provides a **50% cost discount** for latency-tolerant generations (targeted completion within minutes).

### C. Download Delivery Modes
* **`"download_mode": "StreamResponse"` (Default)**: Streams files chunk-by-chunk. Highly recommended for web integrations to prevent large server-memory footprints.
* **`"download_mode": "FileResponse"`**: Triggers a direct file download dialog in the browser (`Content-Disposition: attachment`).

---

## 3. Request Payloads

### General Payload Fields

| Parameter Name | Data Type | Required | Default Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| `action` | `string` | **Yes** | — | Must be either `"image"` or `"video"`. |
| `batch` | `boolean` | No | `false` | Set to `true` to run in batch mode. |
| `use_flex` | `boolean` | No | `false` | Enables Flex Inference tier for Nano Banana image models. |
| `download_mode` | `string` | No | `"StreamResponse"` | `"StreamResponse"` (inline view) or `"FileResponse"` (force download). |
| `model` | `string` | No | Action-dependent | Model identifier (e.g., `gemini-3.1-flash-image-preview`, `veo-3.1-generate-preview`). |
| `prompt` | `string` | Conditionally | — | Prompts for Single mode. Required if `batch` is `false`. |
| `prompts` | `array[string]` | Conditionally | — | List of prompts for simple Batch mode. |
| `requests` | `array[object]`| Conditionally | — | List of detailed request dictionaries (each matching single params) for advanced Batch mode. |

---

### Action: `"image"` Payload Specifications

Exposes standard **Imagen 4** or native Gemini **Nano Banana** image generation.

#### Image Configuration Parameters

When submitting an `"image"` action, the following parameters are accepted (either at the top level for a single request, or nested within items in a `"requests"` batch):

| Parameter Name | Data Type | Default Value | Supported Values / Presets | Description |
| :--- | :--- | :--- | :--- | :--- |
| `aspect_ratio` | `string` | `"1:1"` | `"1:1"`, `"16:9"`, `"9:16"`, `"4:3"`, `"3:4"` | The target aspect ratio for generation. |
| `resolution` | `string` | `"1K"` | `"1K"`, `"2K"`, `"768p"` | The output resolution detail level of the image. |
| `auto_upscale` | `boolean` | `false` | `true`, `false` | Automatically enhance and upscale the output using Google's super-resolution models. |
| `styles` | `array[string]`| `[]` | `["photorealistic", "cinematic", "anime", "oil_painting"]` | List of styles or filters to append to the generation pipeline. |
| `negative_prompt`| `string` | `""` | — | A detailed description of what objects, styles, or artifacts to avoid in the image. |

#### Example: Single Image (Direct Streaming)
```json
{
  "action": "image",
  "batch": false,
  "prompt": "A futuristic sci-fi parrot wearing holographic goggles perched on a neon branch",
  "model": "gemini-3.1-flash-image-preview",
  "aspect_ratio": "16:9",
  "resolution": "2K",
  "download_mode": "StreamResponse"
}
```

#### Example: Batch Image Generation (Flex Mode with Zip Delivery)
```json
{
  "action": "image",
  "batch": true,
  "use_flex": true,
  "model": "gemini-3.1-flash-image-preview",
  "download_mode": "FileResponse",
  "requests": [
    {
      "prompt": "An oil painting of a renaissance parrot reading a book",
      "aspect_ratio": "1:1",
      "resolution": "1K"
    },
    {
      "prompt": "A modern flat-design icon of an AI parrot",
      "aspect_ratio": "1:1",
      "resolution": "1K"
    }
  ]
}
```

---

### Action: `"video"` Payload Specifications

Exposes high-quality video generation powered by **Veo 3.1** models.

#### Video Configuration Parameters

When submitting a `"video"` action, the following parameters are accepted (either at the top level for a single request, or nested within items in a `"requests"` batch):

| Parameter Name | Data Type | Default Value | Supported Values / Presets | Description |
| :--- | :--- | :--- | :--- | :--- |
| `aspect_ratio` | `string` | `"16:9"` | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"` | The target aspect ratio for video generation. |
| `resolution` | `string` | `"1080p"` | `"720p"`, `"1080p"`, `"2K"` | The desired output video resolution. |
| `duration` | `integer` | `5` | `5`, `6`, `8` | The desired duration of the video in seconds. |
| `smoothing` | `boolean` | `false` | `true`, `false` | Enable frame rate smoothing / interpolation for a more fluid and less jittery video output. |
| `number_of_videos`| `integer`| `1` | `1` to `4` | The number of alternate video candidates to generate per prompt. |
| `negative_prompt`| `string` | `""` | — | A detailed description of what styles, concepts, or objects to avoid in the video. |

#### Example: Single Video Generation (Forced File Download)
```json
{
  "action": "video",
  "batch": false,
  "prompt": "Cinematic close-up of an robotic parrot taking off from a landing pad, detailed engines, steam, highly realistic",
  "model": "veo-3.1-generate-preview",
  "aspect_ratio": "16:9",
  "duration": 5,
  "download_mode": "FileResponse"
}
```

#### Example: Batch Video Scene Generation (Zip Streaming)
```json
{
  "action": "video",
  "batch": true,
  "prompts": [
    "Scene 1: Close up of an egg hatching on a mossy nest.",
    "Scene 2: Mossy nest empty, a baby parrot looking curiously at the sky.",
    "Scene 3: Baby parrot spreading its wings on a high tree branch."
  ]
}
```

---

## 4. Response Structures

Depending on your parameters and the success of the operation, the endpoint will respond in one of three ways:

### 1. Direct Media Binary (Single Output)
If only **one** file is generated, it will be returned directly.
* **Content-Type**: `image/png` or `video/mp4`
* **Response Body**: Binary byte payload.
* **UI Usage**: Frontends can render this directly using a Blob URL or standard source stream:
  ```javascript
  const blob = await response.blob();
  const mediaUrl = URL.createObjectURL(blob);
  document.getElementById("myImage").src = mediaUrl;
  ```

### 2. Compressed ZIP Archive (Batch Output)
If **multiple** files are generated, the endpoint automatically packages them into a `.zip` archive.
* **Content-Type**: `application/zip`
* **Response Body**: Binary ZIP payload containing files named `gen_{uuid}.png` or `final_{uuid}.mp4`.
* **UI Usage**: Frontends can download this file directly or extract its contents on the client-side (e.g. using `jszip`):
  ```javascript
  const blob = await response.blob();
  const downloadLink = document.createElement("a");
  downloadLink.href = URL.createObjectURL(blob);
  downloadLink.download = "generated_batch.zip";
  downloadLink.click();
  ```

### 3. Metadata JSON Payload
If files are generated but the user is not downloading them directly, or if an error occurs, the server returns metadata:
```json
{
  "message": "Generation completed with no files returned.",
  "metadata": [
    {
      "input": "An oil painting of a renaissance parrot",
      "output": "/home/jesuslara/proyectos/navigator/ai-parrot/batch_results/image_batch_1717614046000/result_0_message.json",
      "response": "Image generated successfully.",
      "model": "gemini-3.1-flash-image-preview",
      "provider": "google",
      "images": ["/app/batch_results/image_batch_1717614046000/images/gen_image_1717614046000.png"]
    }
  ]
}
```

---

## 5. UI Dashboard Design Guide

For developers looking to build a modern, React/Svelte/Vue user interface for this endpoint, we recommend the following layout and state management principles.

### A. Wireframe Layout
```
+-------------------------------------------------------------------------------+
|                        PARROT GOOGLE MEDIA CREATOR                            |
+-------------------------------------------------------------------------------+
| [ Media Action: ( ) Image   (*) Video ]   |  [ Preset / Mode:               ] |
|                                           |  ( ) Single Asset  (*) Batch     |
| [ Model Selection: veo-3.1-generate-prev] |  [ ( ) Standard    (*) Flex Mode ] |
+-------------------------------------------+-----------------------------------+
|  Prompt Input (Multi-line text area)                                          |
|  "Enter your scene descriptions..."                                           |
|                                                                               |
|  [+ Add Batch Prompt]                                                         |
+-------------------------------------------+-----------------------------------+
|  [ Settings Panel ]                       |  [ Action Buttons ]               |
|  - Aspect Ratio: [ 16:9 ]                 |                                   |
|  - Resolution:   [ 2K ]                   |  [ GENERATE ASSETS ]              |
|  - Delivery Mode: [ StreamResponse ]      |                                   |
+-------------------------------------------+-----------------------------------+
|  Live Media Feed / Output Panel                                               |
|  [  Waiting for generation...  ]                                              |
|                                                                               |
|  (Or render image grid / video carousel if loaded)                            |
+-------------------------------------------------------------------------------+
```

### B. UI State & Interaction Flow
1. **Action Selection**: Toggle between `Image` and `Video`. This should dynamically update:
   - Available **models** (images hide Veo, videos hide Nano Banana).
   - Available **aspect ratios** (e.g. 1:1, 16:9, 4:3, 9:16).
   - Available **resolutions** (e.g., 1K vs 2K vs standard).
2. **Preset Selector**:
   - `Single`: Displays one prompt input.
   - `Batch`: Renders a list of prompt inputs where the user can click `+ Add Scene / Prompt`.
3. **Flex Mode Toggle**:
   - Only enabled when `Action` is `Image`. Shows a tooltip: *"Uses Gemini's sheddable Flex Inference tier. It is 50% cheaper but can take 1-3 minutes to return."*
4. **Generating State**:
   - Disable the "GENERATE ASSETS" button.
   - Show a loading spinner. Since generations (especially Veo videos or Flex mode) can take up to 2-3 minutes, show a progressive progress bar or a motivational quote carousel to keep users engaged.
5. **Render Grid**:
   - If the endpoint returns a ZIP file (batch mode), download it, or dynamically unzip on the frontend using JSZip and render an interactive image/video grid.
   - Provide a "Download All (ZIP)" or individual "Download" and "Save to Library" actions next to each generated item.
6. **Local Archiving Integration**:
   - Since the server automatically saves batch executions inside `{BASE_DIR}/batch_results/`, the UI can easily query other endpoints or local job directories to allow users to view historical generation folders later.
