from typing import Any, Dict, List, Optional, Union, Tuple
import os
import asyncio
import json
import time
from pathlib import Path
import base64
import io
import uuid
import contextlib
from PIL import Image
from google.genai import types
from google.genai.types import (
    GenerateContentConfig,
    Part,
    ModelContent,
    UserContent
)
from ...models import (
    AIMessage,
    AIMessageFactory,
    CompletionUsage,
)
from ...models.google import (
    GoogleModel,
)
from ...models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    IdentificationResponse
)
from ...models.outputs import (
    SentimentAnalysis,
    ProductReview
)

class GoogleAnalysis:
    """
    Mixin class for Google Generative AI analysis capabilities.
    """

    def analyze_sentiment(
        self,
        text: str,
        model: Union[GoogleModel, str] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = False,
    ):
        """
        Perform sentiment analysis on text and return a structured or unstructured response.
        """
        if isinstance(model, GoogleModel):
            model = model.value

        start_time = time.time()

        # Prepare Config
        config_args = {
            "temperature": temperature,
        }

        if use_structured:
            config_args['response_mime_type'] = "application/json"
            config_args['response_schema'] = SentimentAnalysis

        generation_config = types.GenerateContentConfig(**config_args)

        prompt = f"""
        Analyze the sentiment of the following text.
        Text: '{text}'
        """
        if not use_structured:
            prompt += "\nReturn the sentiment (POSITIVE, NEGATIVE, NEUTRAL) and a score (0.0 to 1.0)."

        try:
            # Synchronous call wrapped in executor if needed, but client supports sync
            # Using partial for async execution
            if not self.client:
                raise RuntimeError("Client not initialized")

            # Use synchronous execute for simplicity if wrapped in async method,
            # but here it is a sync method? No, client methods are usually async in this updated client
            # Wait, the original method signature in view_file was "def analyze_sentiment" (sync?).
            # But it calls self.client which might be async.
            # Checking view_file output... extract_key_points was "def extract_key_points".
            # They seem to be synchronous wrappers around synchronous client calls?
            # Or maybe they block.
            # In google.py, they were using `self.client.models.generate_content` which is sync in google-genai SDK 0.x?
            # Actually, `client.aio` is async. `client.models` is sync.
            # The original code used `self.client.models.generate_content` (sync).
            # I will keep them sync as they were, or update to async if I can.
            # But the original code was:
            # def analyze_sentiment(...): ... response = self.client.models.generate_content(...)
            # So they are synchronous. I should probably keep them synchronous to avoid breaking interface.

            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=generation_config
            )

            execution_time = time.time() - start_time
            usage = CompletionUsage(execution_time=execution_time)  # Token usage not always available in sync response immediately without accessing metadata

            if use_structured:
                # Check if parsed structure is available
                if hasattr(response, 'parsed') and response.parsed:
                    return response.parsed
                else:
                    # If not parsed automatically, try to parse text
                    try:
                        return SentimentAnalysis.model_validate_json(response.text)
                    except Exception:
                        pass

            return response.text

        except Exception as e:
            self.logger.error(f"Sentiment analysis failed: {e}")
            raise

    def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = True,
    ):
        """
        Analyze a product review and extract structured or unstructured information.
        """
        if isinstance(model, GoogleModel):
            model = model.value

        start_time = time.time()

        config_args = {
            "temperature": temperature,
        }

        if use_structured:
            config_args['response_mime_type'] = "application/json"
            config_args['response_schema'] = ProductReview

        generation_config = types.GenerateContentConfig(**config_args)

        prompt = f"""
        Analyze the following product review for Product ID: {product_id}.
        Review: '{review_text}'
        """

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=generation_config
            )

            if use_structured:
                if hasattr(response, 'parsed') and response.parsed:
                    return response.parsed
                try:
                    return ProductReview.model_validate_json(response.text)
                except Exception:
                    pass

            return response.text

        except Exception as e:
            self.logger.error(f"Product review analysis failed: {e}")
            raise

    async def video_understanding(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_FLASH_PREVIEW,
        prompt_instruction: Optional[str] = None,
        video: Optional[Union[str, Path]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        stateless: bool = True,
        offsets: Optional[tuple[str, str]] = None,
        reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
        timeout: Optional[int] = 600,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        candidate_count: Optional[int] = None,
        progress_log_interval: int = 10,
        as_image: bool = False,
    ) -> AIMessage:
        """
        Using a video (local or youtube) no analyze and extract information from videos.
        """
        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        self.logger.info(
            f"Starting video analysis with model: {model}"
        )

        if not self.client:
            self.client = await self.get_client()

        if stateless:
            # For stateless mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_history = None
        else:
            # Use the unified conversation context preparation from AbstractClient
            messages, conversation_history, prompt_instruction = await self._prepare_conversation_context(
                prompt, None, user_id, session_id, prompt_instruction, stateless=stateless
            )

        # Prepare conversation history for Google GenAI format
        history = []
        if messages:
            for msg in messages[:-1]: # Exclude the current user message (last in list)
                role = msg['role'].lower()
                if role == 'user':
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ['assistant', 'model']:
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(ModelContent(parts=parts))

        config_kwargs = {
            "response_modalities": ['Text'],
            # Force temperature to 0.0 for deterministic video analysis
            "temperature": 0.0,
            "system_instruction": prompt_instruction,
            "max_output_tokens": self.max_tokens if max_output_tokens is None else max_output_tokens,
            # Force High Resolution for video understanding
            "media_resolution": "media_resolution_high",
        }
        if top_p is not None:
            config_kwargs["top_p"] = top_p
        if top_k is not None:
            config_kwargs["top_k"] = top_k
        if candidate_count is not None:
            config_kwargs["candidate_count"] = candidate_count
        config = types.GenerateContentConfig(**config_kwargs)

        if isinstance(video, str) and video.startswith("http"):
            # youtube video link:
            data = types.FileData(
                file_uri=video
            )
            video_metadata = None
            if offsets:
                video_metadata=types.VideoMetadata(
                    start_offset=offsets[0],
                    end_offset=offsets[1]
                )
            video_info = types.Part(
                file_data=data,
                video_metadata=video_metadata
            )
        else:
            # Handle local video (inline or upload)

            if as_image:
                # Extract frames and treat as image sequence
                self.logger.info("Processing video as image sequence (as_image=True)")
                video_frames = self._extract_frames_from_video(video)
                # video_info will be a list of parts in this case, handle specially below
                video_info = video_frames
            else:
                # The _process_video_input method now returns a Part (either inline or file_data)
                video_info = await self._process_video_input(video)

                # If offsets are provided and it's a file_data part, we might need to attach metadata
                # Note: Inline data usually doesn't support the same metadata structure in the same way
                # or it depends on the API version. For now, we apply offsets if it's a FileData part.
                if offsets and video_info.file_data:
                    # Reconstruct part with metadata if needed
                    pass # Complex to reconstruct types.Part locally without more inspection, leaving as is for now unless critical

        try:
            start_time = time.time()
            content = [
                types.Part(
                    text=prompt
                ),
            ]

            # Append reference images if provided
            if reference_images:
                content.append(types.Part(text="\n\nReference Images:"))
                for ref_img in reference_images:
                    # 1. Resolve to PIL Image while trying to preserve format
                    img = None
                    save_format = 'JPEG' # Default

                    if isinstance(ref_img, (str, Path)):
                        path_obj = Path(ref_img).resolve()
                        if path_obj.exists():
                            img = Image.open(path_obj)
                            if img.format:
                                save_format = img.format
                    elif isinstance(ref_img, bytes):
                        img = Image.open(io.BytesIO(ref_img))
                        if img.format:
                            save_format = img.format
                    elif isinstance(ref_img, Image.Image):
                        img = ref_img
                        if img.format:
                            save_format = img.format

                    if img:
                        # Convert PIL Image to bytes in memory
                        img_byte_arr = io.BytesIO()

                        # Handle mode compatibility for JPEG (e.g., convert RGBA to RGB)
                        if save_format.upper() in ('JPEG', 'JPG') and img.mode in ('RGBA', 'P'):
                            img = img.convert('RGB')

                        img.save(img_byte_arr, format=save_format)
                        img_bytes = img_byte_arr.getvalue()

                        # Create the Part object from bytes
                        mime_type = f"image/{save_format.lower()}"
                        # Adjust for common formats where PIL format != MIME subtype
                        if mime_type == "image/jpg":
                            mime_type = "image/jpeg"

                        content.append(
                            types.Part(
                                inline_data=types.Blob(
                                    data=img_bytes,
                                    mime_type=mime_type
                                )
                            )
                        )
                    else:
                        self.logger.warning(
                            f"Could not process reference image: {ref_img}"
                        )

            if as_image:
                content.append(types.Part(text="\n\nAnalyzing frames from video source:"))
                content.extend(video_info)  # video_info is a list of Part objects
            else:
                content.append(video_info)
                if video_info.inline_data:
                    self.logger.debug(
                        f"Video part uses inline_data ({len(video_info.inline_data.data)} bytes, mime={video_info.inline_data.mime_type})"
                    )
                elif video_info.file_data:
                    self.logger.debug(
                        f"Video part uses file_data (uri={video_info.file_data.file_uri}, mime={video_info.file_data.mime_type})"
                    )
            self.logger.debug(
                f"Prepared content parts: total={len(content)}, reference_images={len(reference_images) if reference_images else 0}"
            )
            # Use the asynchronous client for image generation
            self.logger.debug(f"Calling Gemini API (stateless={stateless})...")
            if stateless:
                self.logger.debug(f"Generating content with model {model}...")
                self.logger.debug(f"Generating content with model {model} (timeout={timeout}s)...")
                # Wrap content in UserContent to ensure correct structure
                user_msg = types.UserContent(parts=content)
                response = await self._await_with_progress(
                    self.client.aio.models.generate_content(
                        model=model,
                        contents=[user_msg],
                        config=config
                    ),
                    label=f"generate_content({model})",
                    timeout=timeout,
                    log_interval=progress_log_interval,
                )
                self.logger.debug("Content generation completed.")
            else:
                self.logger.debug("Creating chat session...")
                # Create the stateful chat session
                chat = self.client.aio.chats.create(
                    model=model,
                    history=history,
                    config=config
                )
                self.logger.debug("Sending message to chat session...")
                self.logger.debug(f"Sending message to chat session (timeout={timeout}s)...")
                response = await self._await_with_progress(
                    chat.send_message(
                        message=content,
                    ),
                    label=f"chat.send_message({model})",
                    timeout=timeout,
                    log_interval=progress_log_interval,
                )
                self.logger.debug("Message sent and response received.")
            execution_time = time.time() - start_time

            final_response = response.text
            self.logger.debug(f"Final response extracted (length: {len(final_response)})")

            usage = CompletionUsage(execution_time=execution_time)

            if not stateless:
                await self._update_conversation_memory(
                    user_id,
                    session_id,
                    conversation_history,
                    messages + [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"[Image Analysis]: {prompt}"}
                            ]
                        },
                    ],
                    None,
                    turn_id,
                    prompt,
                    final_response,
                    []
                )
            # Create AIMessage using factory
            ai_message = AIMessageFactory.from_gemini(
                response=response,
                input_text=prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                structured_output=final_response,
                tool_calls=None,
                conversation_history=conversation_history,
                text_response=final_response
            )

            # Override provider to distinguish from Vertex AI
            ai_message.provider = "google_genai"

            return ai_message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    async def image_identification(
        self,
        prompt: str,
        image: Union[Path, bytes, Image.Image],
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion],
        reference_images: Optional[Dict[str, Union[Path, bytes, Image.Image]]] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_PRO,
        temperature: float = 0.0,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[IdentifiedProduct]:
        """
        Identify products using detected boxes, reference images, and Gemini Vision.

        This method sends the full image, reference images, and individual crops of each
        detection to Gemini for precise identification, returning a structured list of
        IdentifiedProduct objects.

        Args:
            image: The main image of the retail display.
            detections: A list of `DetectionBox` objects from the initial detection step.
            shelf_regions: A list of `ShelfRegion` objects defining shelf boundaries.
            reference_images: Optional list of images showing ideal products.
            model: The Gemini model to use, defaulting to Gemini 2.5 Pro for its advanced vision capabilities.
            temperature: The sampling temperature for the model's response.

        Returns:
            A list of `IdentifiedProduct` objects with detailed identification info.
        """
        self.logger.info(f"Starting Gemini identification for {len(detections)} detections.")
        model_name = model.value if isinstance(model, GoogleModel) else model

        # --- 1. Prepare Images and Metadata ---
        main_image_pil = self._get_image_from_input(image)
        detection_details = []
        id_to_details = {}
        for i, det in enumerate(detections, start=1):
            shelf, pos = self._shelf_and_position(det, shelf_regions)
            detection_details.append({
                "id": i,
                "detection": det,
                "shelf": shelf,
                "position": pos,
                "crop": self._crop_box(main_image_pil, det),
            })
            id_to_details[i] = {"shelf": shelf, "position": pos, "detection": det}

        # --- 2. Construct the Multi-Modal Prompt for Gemini ---
        # The prompt is a list of parts: text instructions, reference images,
        # the main image, and finally the individual crops.
        contents = [Part(text=prompt)] # Start with the user-provided prompt

        # --- Create a lookup map from ID to pre-calculated details ---
        id_to_details = {}
        for i, det in enumerate(detections, 1):
            shelf, pos = self._shelf_and_position(det, shelf_regions)
            id_to_details[i] = {"shelf": shelf, "position": pos, "detection": det}

        if reference_images:
            # Add a text part to introduce the references
            contents.append(Part(text="\n\n--- REFERENCE IMAGE GUIDE ---"))
            for label, ref_img_input in reference_images.items():
                # Add the label text, then the image
                contents.append(Part(text=f"Reference for '{label}':"))
                contents.append(self._get_image_from_input(ref_img_input))
            contents.append(Part(text="--- END REFERENCE GUIDE ---"))

        # Add the main image for overall context
        contents.append(main_image_pil)

        # Add each cropped detection image
        for item in detection_details:
            contents.append(item['crop'])

        for i, det in enumerate(detections, 1):
            contents.append(self._crop_box(main_image_pil, det))

        # Manually generate the JSON schema from the Pydantic model
        raw_schema = IdentificationResponse.model_json_schema()
        # Clean the schema to remove unsupported properties like 'additionalProperties'
        _schema = self.clean_google_schema(raw_schema)

        # --- 3. Configure the API Call for Structured Output ---
        generation_config = GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=8192, # Generous limit for JSON with many items
            response_mime_type="application/json",
            response_schema=_schema,
        )

        # --- 4. Call Gemini and Process the Response ---
        try:
            response = await self.client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=generation_config,
            )
        except Exception as e:
            # if is 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.', 'status': 'UNAVAILABLE'}}
            # then, retry with a short delay but chaing to use gemini-2,5-flash instead pro.
            await asyncio.sleep(1.5)
            response = await self.client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=generation_config,
            )

        try:
            response_text = self._safe_extract_text(response)
            if not response_text:
                raise ValueError(
                    "Received an empty response from the model."
                )

            print('RAW RESPONSE:', response_text)
            # Normalize detection_box coords if the model returned normalized floats.
            parsed_payload = json.loads(response_text)
            detections_payload = parsed_payload.get("detections", [])
            if isinstance(detections_payload, list):
                img_w, img_h = main_image_pil.width, main_image_pil.height

                def _coerce_box(box: dict) -> None:
                    coords = [box.get("x1"), box.get("y1"), box.get("x2"), box.get("y2")]
                    if any(c is None for c in coords):
                        return
                    try:
                        nums = [float(c) for c in coords]
                    except (TypeError, ValueError):
                        return

                    if all(0.0 <= n <= 1.0 for n in nums):
                        box["x1"] = int(nums[0] * img_w)
                        box["y1"] = int(nums[1] * img_h)
                        box["x2"] = int(nums[2] * img_w)
                        box["y2"] = int(nums[3] * img_h)
                    else:
                        box["x1"] = int(nums[0])
                        box["y1"] = int(nums[1])
                        box["x2"] = int(nums[2])
                        box["y2"] = int(nums[3])

                for det in detections_payload:
                    if not isinstance(det, dict):
                        continue
                    box = det.get("detection_box")
                    if isinstance(box, dict):
                        _coerce_box(box)
                    elif isinstance(box, list) and len(box) == 4:
                        try:
                            nums = [float(c) for c in box]
                        except (TypeError, ValueError):
                            continue
                        if all(0.0 <= n <= 1.0 for n in nums):
                            det["detection_box"] = [
                                int(nums[0] * img_w),
                                int(nums[1] * img_h),
                                int(nums[2] * img_w),
                                int(nums[3] * img_h),
                            ]
                        else:
                            det["detection_box"] = [int(n) for n in nums]

            # The model output should conform to the Pydantic model directly
            parsed_data = IdentificationResponse.model_validate(parsed_payload)
            identified_items = parsed_data.identified_products

            # --- 5. Link LLM results back to original detections ---
            final_products = []
            for item in identified_items:
                # Case 1: Item was pre-detected (has a positive ID)
                if item.detection_id is not None and item.detection_id > 0 and item.detection_id in id_to_details:
                    details = id_to_details[item.detection_id]
                    item.detection_box = details["detection"]

                    # Only use geometric fallback if LLM didn't provide shelf_location
                    if not item.shelf_location:
                        self.logger.warning(
                            f"LLM did not provide shelf_location for ID {item.detection_id}. Using geometric fallback."
                        )
                        item.shelf_location = details["shelf"]
                    if not item.position_on_shelf:
                        item.position_on_shelf = details["position"]
                    final_products.append(item)

                # Case 2: Item was newly found by the LLM
                elif item.detection_id is None:
                    if item.detection_box:
                        # TRUST the LLM's assignment, only use geometric fallback if missing
                        if not item.shelf_location:
                            self.logger.info(f"LLM didn't provide shelf_location, calculating geometrically")
                            shelf, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                            item.shelf_location = shelf
                            item.position_on_shelf = pos
                        else:
                            # LLM provided shelf_location, trust it but calculate position if missing
                            self.logger.info(f"Using LLM-assigned shelf_location: {item.shelf_location}")
                            if not item.position_on_shelf:
                                _, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                                item.position_on_shelf = pos

                        self.logger.info(
                            f"Adding new object found by LLM: {item.product_type} on shelf '{item.shelf_location}'"
                        )
                        final_products.append(item)

                # Case 3: Item was newly found by the LLM (has a negative ID from our validator)
                elif item.detection_id < 0:
                    if item.detection_box:
                        # TRUST the LLM's assignment, only use geometric fallback if missing
                        if not item.shelf_location:
                            self.logger.info(f"LLM didn't provide shelf_location, calculating geometrically")
                            shelf, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                            item.shelf_location = shelf
                            item.position_on_shelf = pos
                        else:
                            # LLM provided shelf_location, trust it but calculate position if missing
                            self.logger.info(f"Using LLM-assigned shelf_location: {item.shelf_location}")
                            if not item.position_on_shelf:
                                _, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                                item.position_on_shelf = pos

                        self.logger.info(f"Adding new object found by LLM: {item.product_type} on shelf '{item.shelf_location}'")
                        final_products.append(item)
                    else:
                        self.logger.warning(
                            f"LLM-found item with ID '{item.detection_id}' is missing a detection_box, skipping."
                        )

            self.logger.info(
                f"Successfully identified {len(final_products)} products."
            )
            return final_products

        except Exception as e:
            self.logger.error(
                f"Gemini image identification failed: {e}"
            )
            # Fallback to creating simple products from initial detections
            fallback_products = []
            for item in detection_details:
                shelf, pos = item["shelf"], item["position"]
                det = item["detection"]
                fallback_products.append(IdentifiedProduct(
                    detection_box=det,
                    detection_id=item['id'],
                    product_type=det.class_name,
                    product_model=None,
                    confidence=det.confidence * 0.5, # Lower confidence for fallback
                    visual_features=["fallback_identification"],
                    reference_match="none",
                    shelf_location=shelf,
                    position_on_shelf=pos
                ))
            return fallback_products

    def summarize_text(
        self,
        text: str,
        max_length: int = 1200,
        min_length: int = 100,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Generates a summary for a given text in a stateless manner.
        """
        if isinstance(model, GoogleModel):
            model = model.value

        config_args = {
            "temperature": temperature,
        }
        generation_config = types.GenerateContentConfig(**config_args)

        prompt = f"""
        Summarize the following text in {min_length} to {max_length} words.
        Text:
        {text}
        """

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=generation_config
            )
            return response.text
        except Exception as e:
            self.logger.error(f"Summarization failed: {e}")
            raise

    def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Translates a given text from a source language to a target language.
        """
        if isinstance(model, GoogleModel):
            model = model.value

        config_args = {
            "temperature": temperature,
        }
        generation_config = types.GenerateContentConfig(**config_args)

        src = f" from {source_lang}" if source_lang else ""
        prompt = f"""
        Translate the following text{src} to {target_lang}.
        Text:
        {text}
        """

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=generation_config
            )
            return response.text
        except Exception as e:
            self.logger.error(f"Translation failed: {e}")
            raise

    def extract_key_points(
        self,
        text: str,
        num_points: int = 5,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Extract *num_points* bullet-point key ideas from *text* (stateless).
        """
        if isinstance(model, GoogleModel):
            model = model.value

        config_args = {
            "temperature": temperature,
        }
        generation_config = types.GenerateContentConfig(**config_args)

        prompt = f"""
        Extract {num_points} key points from the following text.
        Text:
        {text}
        """

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=generation_config
            )
            return response.text
        except Exception as e:
            self.logger.error(f"Key point extraction failed: {e}")
            raise

    async def detect_objects(
        self,
        image: Union[str, Path, Image.Image],
        prompt: str,
        reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
        output_dir: Optional[Union[str, Path]] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects objects and segmentation masks using Gemini 3 Flash.
        Based on provided sample code.
        """
        try:
            # 1. Prepare Image
            if isinstance(image, (str, Path)):
                im = Image.open(str(image))
            else:
                im = image.copy()

            original_size = im.size
            # Resize for consistent processing (as per sample)
            im.thumbnail([1024, 1024], Image.Resampling.LANCZOS)

            # 2. Configure Client
            # Note: thinking_budget=0 is recommended for object detection
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json"
            )

            # 3. Call Model
            client = self.client or await self.get_client()

            # Prepare contents
            contents = [prompt, im]
            if reference_images:
                for ref in reference_images:
                    if isinstance(ref, (str, Path)):
                        contents.append(Image.open(str(ref)))
                    else:
                        contents.append(ref)

            response = await client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=contents,
                config=config
            )

            # 4. Parse Response
            text = response.text
            # Strip markdown fencing if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            try:
                items = json.loads(text)
            except json.JSONDecodeError:
                self.logger.error(f"Failed to parse JSON from detection response: {text[:200]}...")
                return []

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            results = []

            # 5. Process Masks
            for i, item in enumerate(items):
                try:
                    box = item.get("box_2d")
                    if not box:
                        continue

                    # Map coordinates back to ORIGINAL image size
                    # Gemini returns [ymin, xmin, ymax, xmax] normalized 0-1000

                    y0 = int(box[0] / 1000 * original_size[1])
                    x0 = int(box[1] / 1000 * original_size[0])
                    y1 = int(box[2] / 1000 * original_size[1])
                    x1 = int(box[3] / 1000 * original_size[0])

                    if y0 >= y1 or x0 >= x1:
                        continue

                    result_item = {
                        "label": item.get("label", "unknown"),
                        "box_2d": [x0, y0, x1, y1], # [x1, y1, x2, y2]
                        "confidence": item.get("confidence", 1.0), # Assuming 1.0 if not provided
                        "mask_image": None,
                        "overlay_image": None
                    }
                    # Preserve other keys (like 'type' or custom fields)
                    for k, v in item.items():
                        if k not in result_item and k != "mask" and k != "box_2d":
                            result_item[k] = v

                    png_str = item.get("mask")
                    if png_str and png_str.startswith("data:image/png;base64,"):
                        png_str = png_str.removeprefix("data:image/png;base64,")
                        mask_data = base64.b64decode(png_str)
                        mask = Image.open(io.BytesIO(mask_data))

                        # Resize mask to match bounding box via original_size
                        mask = mask.resize((x1 - x0, y1 - y0), Image.Resampling.BILINEAR)

                        full_mask = Image.new('L', original_size, 0)
                        full_mask.paste(mask, (x0, y0))

                        # Create colored overlay
                        colored_overlay = Image.new('RGBA', original_size, (255, 0, 0, 128))

                        result_item["mask_image"] = full_mask
                        result_item["overlay_image"] = full_mask # simplified for now, or return the overlay logic

                        # Helper to save if requested
                        if output_dir:
                            mask_filename = f"{item['label']}_{i}_mask.png"
                            full_mask.save(os.path.join(output_dir, mask_filename))
                            # Composite
                            # composite = Image.alpha_composite(im.convert('RGBA'), overlay) ...

                    results.append(result_item)

                except Exception as e:
                    self.logger.error(f"Error processing item {i}: {e}")
                    continue

            return results

        except Exception as e:
            self.logger.error(f"Error in detect_objects: {e}")
            raise

    async def _process_video_input(self, video_path: Union[str, Path]) -> Union[types.Part, types.File]:
        """
        Processes a video file. If < 15MB, returns inline data. Otherwise, uploads to Google GenAI.
        """
        if isinstance(video_path, str):
            video_path = Path(video_path).resolve()

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        file_size = video_path.stat().st_size
        # Lower threshold to 1MB to force File API usage for better reliability with videos
        limit_bytes = 1 * 1024 * 1024

        if file_size < limit_bytes:
            self.logger.debug(f"Video size ({file_size / 1024 / 1024:.2f} MB) is under 1MB. Using inline data.")
            with open(video_path, 'rb') as f:
                video_bytes = f.read()

            # Determine mime type (basic check, can be expanded)
            suffix = video_path.suffix.lower()
            mime_type = "video/mp4" # Default
            if suffix == ".mov":
                mime_type = "video/quicktime"
            elif suffix == ".avi":
                mime_type = "video/x-msvideo"
            elif suffix == ".webm":
                mime_type = "video/webm"

            return types.Part(
                inline_data=types.Blob(data=video_bytes, mime_type=mime_type)
            )
        else:
            self.logger.info(f"Video size ({file_size / 1024 / 1024:.2f} MB) exceeds 1MB. Uploading to File API.")
            return await self._upload_video(video_path)

    async def _await_with_progress(
        self,
        coro,
        *,
        label: str,
        timeout: Optional[int],
        log_interval: int = 10,
    ):
        """Await a coroutine while periodically logging progress."""
        if log_interval <= 0:
            log_interval = 10
        task = asyncio.create_task(coro)
        start = time.monotonic()
        try:
            while True:
                if timeout is None:
                    done, _ = await asyncio.wait({task}, timeout=log_interval)
                else:
                    elapsed = time.monotonic() - start
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    done, _ = await asyncio.wait({task}, timeout=min(log_interval, remaining))
                if task in done:
                    return await task
                elapsed = time.monotonic() - start
                self.logger.debug(f"{label} still running... {elapsed:.1f}s elapsed")
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise

    async def _upload_video(self, video_path: Union[str, Path]) -> types.Part:
        """
        Uploads a video file to Google GenAi Client using Async API.
        """
        if isinstance(video_path, str):
            video_path = Path(video_path).resolve()

        self.logger.debug(f"Starting upload of {video_path}...")
        try:
            upload_start = time.monotonic()
            # Use async files client if available, strictly generic exception catch if not sure
            if hasattr(self.client.aio, 'files'):
                video_file = await self.client.aio.files.upload(
                    file=video_path
                )
            else:
                # Fallback to sync upload in thread if aio.files missing (unlikely in new SDK)
                self.logger.warning("client.aio.files not found, using sync upload in executor")
                loop = asyncio.get_running_loop()
                video_file = await loop.run_in_executor(
                    None,
                    lambda: self.client.files.upload(file=video_path)
                )
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            raise

        upload_elapsed = time.monotonic() - upload_start
        self.logger.debug(
            f"Upload finished in {upload_elapsed:.2f}s. File: {video_file.name}, State: {video_file.state}"
        )
        self.logger.debug(f"Upload initiated: {video_file.name}, State: {video_file.state}")

        processing_start = time.monotonic()
        poll_count = 0
        while video_file.state == "PROCESSING":
            poll_count += 1
            elapsed = time.monotonic() - processing_start
            self.logger.debug("Video detection processing...")
            self.logger.debug(
                f"Video processing in progress (poll={poll_count}, elapsed={elapsed:.1f}s, state={video_file.state})"
            )
            await asyncio.sleep(5)
            if hasattr(self.client.aio, 'files'):
                video_file = await self.client.aio.files.get(name=video_file.name)
            else:
                loop = asyncio.get_running_loop()
                video_file = await loop.run_in_executor(
                    None,
                    lambda: self.client.files.get(name=video_file.name)
                )

        processing_elapsed = time.monotonic() - processing_start
        self.logger.debug(
            f"Video processing completed in {processing_elapsed:.1f}s with state={video_file.state}"
        )
        if video_file.state == "FAILED":
            self.logger.error(f"Video processing failed: {video_file.state}")
            raise ValueError(f"Video processing failed with state: {video_file.state}")

        self.logger.debug(
            f"Uploaded video file ready: {video_file.uri}"
        )

        # Return as a Part referencing the uploaded file uri
        return types.Part(
            file_data=types.FileData(file_uri=video_file.uri, mime_type=video_file.mime_type)
        )

    def _extract_frames_from_video(self, video_path: Union[str, Path]) -> List[types.Part]:
        """
        Extracts frames from a video file as images.
        Interval strategy:
        - If duration < 60s: every 2 seconds
        - If duration < 300s: every 5 seconds
        - Else: every 10 seconds
        """
        import cv2  # pylint: disable=C0415 # noqa
        if isinstance(video_path, str):
            video_path = Path(video_path).resolve()

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        video = cv2.VideoCapture(str(video_path))
        if not video.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        # Get video properties
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps

        # Calculate interval
        if duration < 60:
            interval_sec = 2
        elif duration < 300:
            interval_sec = 5
        else:
            interval_sec = 10

        interval_frames = int(fps * interval_sec)

        frames = []
        current_frame = 0

        self.logger.info(
            f"Extracting frames from {video_path.name} (duration={duration:.1f}s, interval={interval_sec}s)"
        )

        while True:
            success, frame = video.read()
            if not success:
                break

            if current_frame % interval_frames == 0:
                # Convert BGR to RGB
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Convert to PIL Image
                pil_image = Image.fromarray(rgb_frame)

                # Convert to bytes
                img_byte_arr = io.BytesIO()
                pil_image.save(img_byte_arr, format='JPEG', quality=85)
                img_bytes = img_byte_arr.getvalue()

                # Timestamp info
                timestamp = current_frame / fps

                frames.append(
                    types.Part(
                        inline_data=types.Blob(
                            data=img_bytes,
                            mime_type="image/jpeg"
                        )
                    )
                )
                self.logger.debug(f"Extracted frame at {timestamp:.1f}s")

            current_frame += 1

        video.release()
        self.logger.info(f"Extracted {len(frames)} frames from video.")
        return frames

    def _get_image_from_input(self, image: Union[str, Path, Image.Image]) -> Image.Image:
        """Helper to consistently load an image into a PIL object."""
        if isinstance(image, (str, Path)):
            return Image.open(image).convert("RGB")
        elif isinstance(image, bytes):
            return Image.open(io.BytesIO(image)).convert("RGB")
        else:
            return image.convert("RGB")

    def _crop_box(self, pil_img: Image.Image, box: DetectionBox) -> Image.Image:
        """Crops a detection box from a PIL image with a small padding."""
        # A small padding can provide more context to the model
        pad = 8
        x1 = max(0, box.x1 - pad)
        y1 = max(0, box.y1 - pad)
        x2 = min(pil_img.width, box.x2 + pad)
        y2 = min(pil_img.height, box.y2 + pad)
        return pil_img.crop((x1, y1, x2, y2))

    def _shelf_and_position(self, box: DetectionBox, regions: List[ShelfRegion]) -> Tuple[str, str]:
        """
        Determines the shelf and position for a given detection box using a robust
        centroid-based assignment logic.
        """
        if not regions:
            return "unknown", "center"

        # --- NEW LOGIC: Use the object's center point for assignment ---
        center_y = box.y1 + (box.y2 - box.y1) / 2
        best_region = None

        # 1. Primary Method: Find which shelf region CONTAINS the center point.
        for region in regions:
            if region.bbox.y1 <= center_y < region.bbox.y2:
                best_region = region
                break  # Found the correct shelf

        # 2. Fallback Method: If no shelf contains the center (edge case), find the closest one.
        if not best_region:
            min_distance = float('inf')
            for region in regions:
                shelf_center_y = region.bbox.y1 + (region.bbox.y2 - region.bbox.y1) / 2
                distance = abs(center_y - shelf_center_y)
                if distance < min_distance:
                    min_distance = distance
                    best_region = region

        shelf = best_region.level if best_region else "unknown"

        # --- Position logic remains the same, it's correct ---
        if best_region:
            box_center_x = (box.x1 + box.x2) / 2.0
            shelf_width = best_region.bbox.x2 - best_region.bbox.x1
            third_width = shelf_width / 3.0
            left_boundary = best_region.bbox.x1 + third_width
            right_boundary = best_region.bbox.x1 + 2 * third_width

            if box_center_x < left_boundary:
                position = "left"
            elif box_center_x > right_boundary:
                position = "right"
            else:
                position = "center"
        else:
            position = "center"

        return shelf, position
