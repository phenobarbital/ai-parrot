"""NovaGeneration — Nova Canvas image + Nova Reel video generation (FEAT-315).

Capability mixin composed into
:class:`~parrot.clients.nova.client.NovaClient` alongside
``BedrockConverseBase`` and ``NovaAudio`` (spec ``novaclient-amazon-aws``
§2/§3 Module 4), with method names mirroring
:class:`~parrot.clients.google.generation.GoogleGeneration`
(``generate_image``, ``video_generation``) so callers can swap providers.
Scope is minimal parity (spec §8 resolved U4): no batch variants, no reel
assembly, no speech.

AWS facts (verified 2026-07-17, spec §6 "Verified AWS Facts"):

- Nova Canvas (``amazon.nova-canvas-v1:0``): synchronous ``invoke_model``,
  ``taskType: "TEXT_IMAGE"``, base64 images in the response body.
- Nova Reel (``amazon.nova-reel-v1:0``): ``start_async_invoke`` →
  ``get_async_invoke`` polling ONLY (no synchronous API). Requires
  ``outputDataConfig.s3OutputDataConfig.s3Uri``.

See ``sdd/specs/novaclient-amazon-aws.spec.md`` (§3 Module 4) for the full
design.
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

import aiofiles

from ...conf import AWS_CREDENTIALS
from ...exceptions import InvokeError
from ...models.basic import CompletionUsage
from ...models.bedrock_models import translate as translate_bedrock_model
from ...models.responses import AIMessage, AIMessageFactory


class NovaGeneration:
    """Nova Canvas (image) + Nova Reel (video) generation mixin.

    Plain mixin — defines NO ``__init__`` (MRO constraint, spec §7) and
    reads the following attributes from the composed client (set by
    :class:`~parrot.clients.nova.client.NovaClient` / inherited from
    ``BedrockConverseBase``): ``self._translate_model(model)``,
    ``self._ensure_client()`` (per-loop cached ``aioboto3`` Bedrock Runtime
    client), ``self._aws_id``, ``self._aws_access_key``,
    ``self._aws_secret_key``, ``self._aws_session_token``, ``self._region``,
    ``self._profile``, ``self.logger``.
    """

    _default_image_model: str = "nova-canvas"
    _default_video_model: str = "nova-reel"

    @staticmethod
    def _translate_in_region_model(model: str) -> str:
        """Resolve a Canvas/Reel model ID WITHOUT a region-prefix.

        Code-review fix (FEAT-315): Nova Canvas and Nova Reel are
        **in-region only** — they have no cross-region inference profiles
        (spec §6 "Verified AWS Facts") — so, unlike the text/Converse path
        (``self._translate_model``, which applies ``self._region_prefix``
        unconditionally), generation model IDs must NEVER be prefixed even
        when the composed client defaults ``region_prefix="us"`` (as
        :class:`~parrot.clients.nova.client.NovaClient` does, for the
        unrelated Nova 2 Lite/Premier text models). Calls
        :func:`~parrot.models.bedrock_models.translate` directly with
        ``region_prefix=None``, bypassing ``self._region_prefix`` entirely.
        """
        return translate_bedrock_model(model, region_prefix=None)

    # ------------------------------------------------------------------
    # Nova Canvas — synchronous image generation
    # ------------------------------------------------------------------

    async def generate_image(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        number_of_images: int = 1,
        width: int = 1024,
        height: int = 1024,
        seed: Optional[int] = None,
        output_directory: Optional[Union[str, Path]] = None,
        as_base64: bool = False,
        **kwargs: Any,
    ) -> AIMessage:
        """Generate image(s) via Amazon Nova Canvas.

        Args:
            prompt: Text prompt describing the image.
            model: Model override. Defaults to ``"nova-canvas"``.
            negative_prompt: Optional text describing what to avoid.
            number_of_images: Number of candidate images to request.
            width: Output image width in pixels.
            height: Output image height in pixels.
            seed: Optional generation seed for reproducibility.
            output_directory: When given, decoded images are saved here as
                PNG files (async write via ``aiofiles``).
            as_base64: When ``True``, ``AIMessage.output`` carries the raw
                base64 strings instead of saved file paths.
            **kwargs: Reserved for future Canvas parameters.

        Returns:
            :class:`AIMessage` with ``images`` (saved file paths, if
            ``output_directory`` was given) and ``output`` (base64 strings
            or file paths per ``as_base64``).
        """
        resolved_model = self._translate_in_region_model(model or self._default_image_model)

        image_generation_config: Dict[str, Any] = {
            "numberOfImages": number_of_images,
            "height": height,
            "width": width,
        }
        if seed is not None:
            image_generation_config["seed"] = seed

        text_to_image_params: Dict[str, Any] = {"text": prompt}
        if negative_prompt:
            text_to_image_params["negativeText"] = negative_prompt

        payload: Dict[str, Any] = {
            "taskType": "TEXT_IMAGE",
            "textToImageParams": text_to_image_params,
            "imageGenerationConfig": image_generation_config,
        }

        client = await self._ensure_client()
        response = await client.invoke_model(
            modelId=resolved_model,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        response_body = await response["body"].read()
        result = json.loads(response_body)
        images_b64 = result.get("images", [])

        saved_paths: list = []
        if output_directory:
            out_dir = Path(output_directory)
            out_dir.mkdir(parents=True, exist_ok=True)
            for idx, image_b64 in enumerate(images_b64):
                image_bytes = base64.b64decode(image_b64)
                file_path = out_dir / f"nova-canvas-{uuid.uuid4().hex}-{idx}.png"
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(image_bytes)
                saved_paths.append(file_path)
                self.logger.info("Nova Canvas image saved to %s", file_path)

        output: Any = images_b64 if as_base64 else (saved_paths or images_b64)

        return AIMessageFactory.from_imagen(
            output=output,
            images=saved_paths,
            input=prompt,
            model=resolved_model,
            provider="nova-canvas",
            usage=CompletionUsage(),
            raw_response=result,
        )

    # ------------------------------------------------------------------
    # Nova Reel — async video generation (StartAsyncInvoke/GetAsyncInvoke only)
    # ------------------------------------------------------------------

    def _resolve_s3_output_uri(self, s3_output_uri: Optional[str]) -> str:
        """Resolve the mandatory Nova Reel S3 output location.

        Resolution order: explicit kwarg → ``AWS_CREDENTIALS[self._aws_id
        or 'default']["bucket_name"]``.

        Raises:
            ValueError: When neither an explicit ``s3_output_uri`` nor a
                ``bucket_name`` on the resolved credentials profile is
                available — actionable message names both.
        """
        if s3_output_uri:
            return s3_output_uri

        profile_name = getattr(self, "_aws_id", None) or "default"
        profile = AWS_CREDENTIALS.get(profile_name, {}) or {}
        bucket_name = profile.get("bucket_name")
        if bucket_name:
            return f"s3://{bucket_name}/nova-reel-output/"

        raise ValueError(
            "video_generation() requires an S3 output location for Nova "
            "Reel (StartAsyncInvoke has no synchronous API). Pass "
            "s3_output_uri=..., or configure bucket_name in the "
            f"AWS_CREDENTIALS[{profile_name!r}] profile."
        )

    @staticmethod
    def _parse_s3_uri(s3_uri: str) -> tuple:
        """Split an ``s3://bucket/prefix`` URI into ``(bucket, prefix)``."""
        without_scheme = s3_uri.removeprefix("s3://")
        bucket, _, prefix = without_scheme.partition("/")
        return bucket, prefix

    async def video_generation(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        reference_image: Optional[Union[str, Path]] = None,
        duration: int = 6,
        output_directory: Optional[Union[str, Path]] = None,
        s3_output_uri: Optional[str] = None,
        poll_interval: float = 10.0,
        timeout: float = 900.0,
        **kwargs: Any,
    ) -> AIMessage:
        """Generate a video via Amazon Nova Reel.

        Runs the mandatory ``start_async_invoke`` → ``get_async_invoke``
        polling cycle (Nova Reel has NO synchronous API) and downloads the
        finished MP4 from S3 into *output_directory*.

        Args:
            prompt: Text prompt describing the video.
            model: Model override. Defaults to ``"nova-reel"``.
            reference_image: Optional path to a starting-frame image.
            duration: Video duration in seconds.
            output_directory: Directory the finished MP4 is downloaded to.
                Defaults to the current working directory.
            s3_output_uri: Mandatory S3 output location override. Falls
                back to ``AWS_CREDENTIALS[self._aws_id]["bucket_name"]``.
            poll_interval: Seconds between ``get_async_invoke`` polls.
            timeout: Maximum seconds to wait for job completion.
            **kwargs: Reserved for future Reel parameters.

        Returns:
            :class:`AIMessage` whose ``output``/``images`` (well, the local
            MP4 path is exposed via ``output``) point at the downloaded
            video file.

        Raises:
            ValueError: When no S3 output location can be resolved.
            InvokeError: When the Reel job reaches ``Failed`` status or
                does not complete within *timeout*.
        """
        resolved_model = self._translate_in_region_model(model or self._default_video_model)
        resolved_s3_output_uri = self._resolve_s3_output_uri(s3_output_uri)

        video_generation_config: Dict[str, Any] = {"durationSeconds": duration}
        text_to_video_params: Dict[str, Any] = {"text": prompt}
        if reference_image:
            async with aiofiles.open(reference_image, "rb") as f:
                image_bytes = await f.read()
            text_to_video_params["images"] = [
                {"format": "png", "source": {"bytes": base64.b64encode(image_bytes).decode("ascii")}}
            ]

        model_input: Dict[str, Any] = {
            "taskType": "TEXT_VIDEO",
            "textToVideoParams": text_to_video_params,
            "videoGenerationConfig": video_generation_config,
        }

        client = await self._ensure_client()
        start_response = await client.start_async_invoke(
            modelId=resolved_model,
            modelInput=model_input,
            outputDataConfig={"s3OutputDataConfig": {"s3Uri": resolved_s3_output_uri}},
        )
        invocation_arn = start_response["invocationArn"]
        self.logger.info(
            "Nova Reel job started: %s (model=%s)", invocation_arn, resolved_model,
        )

        elapsed = 0.0
        status_response: Dict[str, Any] = {}
        while True:
            status_response = await client.get_async_invoke(invocationArn=invocation_arn)
            status = status_response.get("status")
            if status == "Completed":
                break
            if status == "Failed":
                raise InvokeError(
                    f"Nova Reel job {invocation_arn} failed: "
                    f"{status_response.get('failureMessage', 'unknown error')}"
                )
            if elapsed >= timeout:
                raise InvokeError(
                    f"Nova Reel job {invocation_arn} did not complete within "
                    f"{timeout}s (last status: {status!r})."
                )
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        output_s3_uri = (
            status_response.get("outputDataConfig", {})
            .get("s3OutputDataConfig", {})
            .get("s3Uri", resolved_s3_output_uri)
        )
        local_path = await self._download_reel_video(
            output_s3_uri, output_directory, invocation_arn,
        )

        return AIMessageFactory.from_video(
            output=str(local_path),
            images=None,
            input=prompt,
            model=resolved_model,
            provider="nova-reel",
            usage=CompletionUsage(),
            raw_response=status_response,
        )

    async def _download_reel_video(
        self,
        output_s3_uri: str,
        output_directory: Optional[Union[str, Path]],
        invocation_arn: str,
    ) -> Path:
        """Download the finished Nova Reel MP4 from S3 to *output_directory*.

        Nova Reel writes the finished asset to ``<s3Uri>/output.mp4``. Uses
        the SAME resolved credentials as the runtime client (S3 housekeeping
        default: keep the S3 object after download — spec §8 resolved).

        Args:
            output_s3_uri: The ``s3://bucket/prefix`` job output location.
            output_directory: Local directory to download into. Defaults
                to the current working directory.
            invocation_arn: The Reel job ARN, used to build a unique local
                filename.

        Returns:
            The local path of the downloaded MP4 file.
        """
        import aioboto3

        bucket, prefix = self._parse_s3_uri(output_s3_uri)
        key = f"{prefix.rstrip('/')}/output.mp4" if prefix else "output.mp4"

        out_dir = Path(output_directory) if output_directory else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        job_id = invocation_arn.rsplit("/", 1)[-1]
        local_path = out_dir / f"nova-reel-{job_id}.mp4"

        session = (
            aioboto3.Session(profile_name=self._profile)
            if getattr(self, "_profile", None) else aioboto3.Session()
        )
        client_kwargs: Dict[str, Any] = {"region_name": self._region}
        if self._aws_access_key and self._aws_secret_key:
            client_kwargs["aws_access_key_id"] = self._aws_access_key
            client_kwargs["aws_secret_access_key"] = self._aws_secret_key
            if self._aws_session_token:
                client_kwargs["aws_session_token"] = self._aws_session_token

        async with session.client("s3", **client_kwargs) as s3_client:
            response = await s3_client.get_object(Bucket=bucket, Key=key)
            body_bytes = await response["Body"].read()

        async with aiofiles.open(local_path, "wb") as f:
            await f.write(body_bytes)

        self.logger.info("Nova Reel video downloaded to %s", local_path)
        return local_path
