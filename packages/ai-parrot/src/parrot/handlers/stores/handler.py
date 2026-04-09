"""Vector Store Handler — REST API for vector store lifecycle management."""
import importlib
import uuid
from collections import OrderedDict
from typing import Any, Optional

from aiohttp import web
from datamodel.parsers.json import json_encoder
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

from parrot.conf import async_default_dsn, VECTOR_HANDLER_MAX_FILE_SIZE
from parrot.handlers.jobs import JobManager, JobStatus
from parrot.handlers.stores.helpers import VectorStoreHelper
from parrot.interfaces.file.tmp import TempFileManager
from parrot.stores import AbstractStore, supported_stores
from parrot.stores.models import StoreConfig, SearchResult, Document

# App-context keys (follow ScrapingHandler pattern)
_JOB_MANAGER_KEY = "vectorstore_job_manager"
_TEMP_FILE_KEY = "vectorstore_temp_files"
_STORE_CACHE_KEY = "vectorstore_cache"
_STORE_CACHE_MAX = 10

# File-extension categories
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}

DEFAULT_IMAGE_PROMPT = "Describe this image in detail for use as a searchable document."
DEFAULT_VIDEO_PROMPT = "Analyze and describe the content of this video in detail for use as a searchable document."


@is_authenticated()
@user_session()
class VectorStoreHandler(BaseView):
    """REST API for vector store lifecycle management.

    Endpoints:
        POST  /api/v1/ai/stores             — create/prepare collection
        PUT   /api/v1/ai/stores             — load data into collection
        PATCH /api/v1/ai/stores             — test search
        GET   /api/v1/ai/stores             — metadata (unauthenticated delegate)
        GET   /api/v1/ai/stores/jobs/{job_id} — job status
    """

    _logger_name: str = "Parrot.VectorStoreHandler"

    def post_init(self, *args, **kwargs):
        """Initialise logger on handler construction."""
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    @classmethod
    def setup(cls, app: web.Application) -> None:
        """Register routes and lifecycle hooks.

        Args:
            app: The aiohttp Application instance.
        """
        app.router.add_view("/api/v1/ai/stores", cls)
        app.router.add_view("/api/v1/ai/stores/jobs/{job_id}", cls)
        app.on_startup.append(cls._on_startup)
        app.on_cleanup.append(cls._on_cleanup)

    @staticmethod
    async def _on_startup(app: web.Application) -> None:
        """Create JobManager, TempFileManager and empty store cache on startup.

        Args:
            app: The aiohttp Application instance.
        """
        job_manager = JobManager(id="vectorstore")
        await job_manager.start()
        app[_JOB_MANAGER_KEY] = job_manager

        temp_file_manager = TempFileManager(
            prefix="parrot_vectorstore_",
            cleanup_on_exit=True,
        )
        app[_TEMP_FILE_KEY] = temp_file_manager

        app[_STORE_CACHE_KEY] = OrderedDict()

    @staticmethod
    async def _on_cleanup(app: web.Application) -> None:
        """Disconnect all cached stores, stop JobManager, cleanup TempFileManager.

        Args:
            app: The aiohttp Application instance.
        """
        cache: OrderedDict = app.get(_STORE_CACHE_KEY, OrderedDict())
        for key, store in list(cache.items()):
            try:
                await store.disconnect()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("Parrot.VectorStoreHandler").warning(
                    "Error disconnecting store %s during cleanup: %s", key, exc
                )
        cache.clear()

        if jm := app.get(_JOB_MANAGER_KEY):
            await jm.stop()

        if tfm := app.get(_TEMP_FILE_KEY):
            tfm.cleanup()

    # ------------------------------------------------------------------ #
    # Store connection cache                                               #
    # ------------------------------------------------------------------ #

    async def _get_store(self, config: StoreConfig) -> AbstractStore:
        """Return a connected store, using the handler-level connection cache.

        Cache key is (vector_store, dsn or "default").  On a cache miss the
        store is instantiated and connected.  When the cache is full, the
        oldest entry is evicted and disconnected.

        Args:
            config: StoreConfig describing the desired store.

        Returns:
            A connected AbstractStore instance.

        Raises:
            ValueError: When the requested vector_store is not supported.
        """
        store_type = config.vector_store
        if store_type not in supported_stores:
            raise ValueError(f"Unsupported vector_store: {store_type!r}")

        # DSN fallback for postgres
        dsn = config.dsn
        if store_type == "postgres" and not dsn:
            dsn = async_default_dsn

        cache_key = (store_type, dsn or "default")
        cache: OrderedDict = self.request.app.get(_STORE_CACHE_KEY, OrderedDict())

        if cache_key in cache:
            store = cache[cache_key]
            if not store._connected:
                await store.connection()
            return store

        # Cache miss — instantiate
        cls_name = supported_stores[store_type]
        module_path = f"parrot.stores.{store_type}"
        module = importlib.import_module(module_path)
        store_cls = getattr(module, cls_name)

        # Build kwargs from StoreConfig
        kwargs: dict[str, Any] = {
            "embedding_model": config.embedding_model,
            "dimension": config.dimension,
            "distance_strategy": config.distance_strategy,
            "metric_type": config.metric_type,
            "index_type": config.index_type,
        }
        if dsn:
            kwargs["dsn"] = dsn

        # BigQuery maps schema → dataset
        if store_type == "bigquery":
            kwargs["dataset"] = config.schema
        else:
            kwargs["schema"] = config.schema

        if config.extra:
            kwargs.update(config.extra)

        store = store_cls(**kwargs)
        await store.connection()

        # Evict oldest if cache is full
        if len(cache) >= _STORE_CACHE_MAX:
            _, evicted = cache.popitem(last=False)
            try:
                await evicted.disconnect()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Error disconnecting evicted store: %s", exc)

        cache[cache_key] = store
        return store

    # ------------------------------------------------------------------ #
    # HTTP methods                                                         #
    # ------------------------------------------------------------------ #

    async def get(self) -> web.Response:
        """Handle GET requests.

        Two patterns:
          - /api/v1/ai/stores/jobs/{job_id}  → return job status
          - /api/v1/ai/stores?resource=<name>  → delegate to VectorStoreHelper

        Returns:
            JSON response with requested data.
        """
        # Job status route
        job_id = self.request.match_info.get("job_id")
        if job_id:
            return await self._get_job_status(job_id)

        # Metadata delegate
        resource = self.request.rel_url.query.get("resource")
        helper_map = {
            "stores": VectorStoreHelper.supported_stores,
            "embeddings": VectorStoreHelper.supported_embeddings,
            "loaders": VectorStoreHelper.supported_loaders,
            "index_types": VectorStoreHelper.supported_index_types,
            "use_cases": VectorStoreHelper.supported_use_cases,
        }
        if resource and resource in helper_map:
            data = helper_map[resource]()
            return web.Response(
                content_type="application/json",
                body=json_encoder(data),
            )

        # embedding_models supports optional provider and use_case filters
        if resource == "embedding_models":
            provider = self.request.rel_url.query.get("provider")
            use_case = self.request.rel_url.query.get("use_case")
            data = VectorStoreHelper.supported_embedding_models(
                provider=provider, use_case=use_case,
            )
            return web.Response(
                content_type="application/json",
                body=json_encoder(data),
            )

        # Return all metadata if no resource specified
        all_meta = {
            "stores": VectorStoreHelper.supported_stores(),
            "embeddings": VectorStoreHelper.supported_embeddings(),
            "embedding_models": VectorStoreHelper.supported_embedding_models(),
            "use_cases": VectorStoreHelper.supported_use_cases(),
            "loaders": VectorStoreHelper.supported_loaders(),
            "index_types": VectorStoreHelper.supported_index_types(),
        }
        return web.Response(
            content_type="application/json",
            body=json_encoder(all_meta),
        )

    async def _get_job_status(self, job_id: str) -> web.Response:
        """Return status of a background job.

        Args:
            job_id: The job identifier.

        Returns:
            JSON response with job status fields.
        """
        jm: Optional[JobManager] = self.request.app.get(_JOB_MANAGER_KEY)
        if not jm:
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": "Job manager not available"}),
                status=503,
            )

        job = jm.get_job(job_id)
        if not job:
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": f"Job {job_id!r} not found"}),
                status=404,
            )

        payload: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        }
        if job.result is not None:
            payload["result"] = job.result
        if job.error:
            payload["error"] = job.error
        elapsed = job.elapsed_time
        if elapsed is not None:
            payload["elapsed_time"] = elapsed

        return web.Response(
            content_type="application/json",
            body=json_encoder(payload),
        )

    async def post(self) -> web.Response:
        """Create or prepare a vector store collection.

        Returns:
            JSON response with creation status.
        """
        try:
            body = await self.request.json()
            table = body.get("table")
            schema = body.get("schema", "public")
            no_drop_table = body.get("no_drop_table", False)
            store_type = body.get("vector_store", "postgres")

            if not table:
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({"error": "Missing required field: table"}),
                    status=400,
                )
            if store_type not in supported_stores:
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({"error": f"Unsupported vector_store: {store_type!r}"}),
                    status=400,
                )

            config = StoreConfig(
                vector_store=store_type,
                table=table,
                schema=schema,
                embedding_model=body.get("embedding_model", {"model": "thenlper/gte-base", "model_type": "huggingface"}),
                dimension=body.get("dimension", 768),
                dsn=body.get("dsn"),
                distance_strategy=body.get("distance_strategy", "COSINE"),
                metric_type=body.get("metric_type", "COSINE"),
                index_type=body.get("index_type", "IVF_FLAT"),
                extra=body.get("extra", {}),
            )

            store = await self._get_store(config)

            exists = await store.collection_exists(table=table, schema=schema)
            if exists and not no_drop_table:
                await store.delete_collection(table=table, schema=schema)
                await store.create_collection(
                    table=table,
                    schema=schema,
                    dimension=config.dimension,
                    index_type=config.index_type,
                    metric_type=config.metric_type,
                )
                await store.prepare_embedding_table(
                    table=table,
                    schema=schema,
                    dimension=config.dimension,
                )
            elif exists and no_drop_table:
                await store.prepare_embedding_table(
                    table=table,
                    schema=schema,
                    dimension=config.dimension,
                )
            else:
                await store.create_collection(
                    table=table,
                    schema=schema,
                    dimension=config.dimension,
                    index_type=config.index_type,
                    metric_type=config.metric_type,
                )
                await store.prepare_embedding_table(
                    table=table,
                    schema=schema,
                    dimension=config.dimension,
                )

            return web.Response(
                content_type="application/json",
                body=json_encoder({
                    "status": "created",
                    "table": table,
                    "schema": schema,
                    "vector_store": store_type,
                }),
            )
        except Exception as err:
            self.logger.error("POST error: %s", err, exc_info=True)
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": str(err)}),
                status=500,
            )

    async def patch(self) -> web.Response:
        """Test search against a vector store collection.

        Returns:
            JSON response with query results.
        """
        try:
            body = await self.request.json()
            query = body.get("query")
            if not query:
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({"error": "Missing required field: query"}),
                    status=400,
                )

            table = body.get("table")
            schema = body.get("schema", "public")
            method = body.get("method", "similarity")
            k = body.get("k", 5)
            store_type = body.get("vector_store", "postgres")

            if method not in ("similarity", "mmr", "both"):
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({"error": f"Invalid method: {method!r}. Must be 'similarity', 'mmr', or 'both'"}),
                    status=400,
                )

            config = StoreConfig(
                vector_store=store_type,
                table=table,
                schema=schema,
                embedding_model=body.get("embedding_model", {"model": "thenlper/gte-base", "model_type": "huggingface"}),
                dimension=body.get("dimension", 768),
                dsn=body.get("dsn"),
            )

            store = await self._get_store(config)

            if not await store.collection_exists(table=table, schema=schema):
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({"error": f"Collection '{schema}.{table}' not found"}),
                    status=404,
                )

            results: list[SearchResult] = []
            if method in ("similarity", "both"):
                sim_results = await store.similarity_search(
                    query=query, table=table, schema=schema, k=k
                )
                results.extend(sim_results)
            if method in ("mmr", "both"):
                mmr_results = await store.mmr_search(
                    query=query, table=table, schema=schema, k=k
                )
                if method == "mmr":
                    results = mmr_results
                else:
                    results.extend(mmr_results)

            serialized = [r.model_dump() for r in results]

            return web.Response(
                content_type="application/json",
                body=json_encoder({
                    "query": query,
                    "method": method,
                    "count": len(serialized),
                    "results": serialized,
                }),
            )
        except Exception as err:
            self.logger.error("PATCH error: %s", err, exc_info=True)
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": str(err)}),
                status=500,
            )

    async def put(self) -> web.Response:
        """Load data into a vector store collection.

        Supports file uploads (multipart), inline JSON content, and URL lists.
        Long-running operations (images, videos, URLs) are dispatched as
        background jobs.

        Returns:
            JSON response with job_id (background) or document count (immediate).
        """
        try:
            content_type = self.request.content_type or ""
            jm: Optional[JobManager] = self.request.app.get(_JOB_MANAGER_KEY)
            tfm: Optional[TempFileManager] = self.request.app.get(_TEMP_FILE_KEY)

            if "multipart" in content_type:
                return await self._put_file_upload(jm, tfm)
            else:
                return await self._put_json_body(jm)
        except Exception as err:
            self.logger.error("PUT error: %s", err, exc_info=True)
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": str(err)}),
                status=500,
            )

    # ------------------------------------------------------------------ #
    # PUT helpers                                                          #
    # ------------------------------------------------------------------ #

    async def _put_file_upload(
        self,
        jm: Optional[JobManager],
        tfm: Optional[TempFileManager],
    ) -> web.Response:
        """Handle multipart file upload path.

        Args:
            jm: JobManager instance.
            tfm: TempFileManager instance.

        Returns:
            Immediate or background-job JSON response.
        """
        from pathlib import Path

        files_dict, form_fields = await self.handle_upload(
            request=self.request,
            preserve_filenames=True,
        )

        # Build StoreConfig from form fields
        store_type = form_fields.get("vector_store", "postgres")
        table = form_fields.get("table")
        if not table:
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": "Missing required field: table"}),
                status=400,
            )
        schema = form_fields.get("schema", "public")
        prompt = form_fields.get("prompt")

        # Flatten all uploaded files first (so size check happens before store connection)
        all_files: list[dict] = []
        for file_list in files_dict.values():
            all_files.extend(file_list)

        if not all_files:
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": "No files received"}),
                status=400,
            )

        # Check file sizes BEFORE connecting to the store
        for file_info in all_files:
            file_path = Path(file_info["file_path"])
            if file_path.exists() and file_path.stat().st_size > VECTOR_HANDLER_MAX_FILE_SIZE:
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({
                        "error": f"File {file_info['file_name']} exceeds maximum allowed size"
                    }),
                    status=413,
                )

        config = StoreConfig(
            vector_store=store_type,
            table=table,
            schema=schema,
            embedding_model=form_fields.get("embedding_model", {"model": "thenlper/gte-base", "model_type": "huggingface"}),
            dimension=int(form_fields.get("dimension", 768)),
            dsn=form_fields.get("dsn"),
        )
        store = await self._get_store(config)

        # Determine if any files need background processing
        needs_background = any(
            Path(fi["file_name"]).suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
            for fi in all_files
        )

        if needs_background and jm:
            job_id = uuid.uuid4().hex
            jm.create_job(
                job_id=job_id,
                obj_id="vectorstore",
                query={"files": [fi["file_name"] for fi in all_files], "table": table},
            )

            async def _bg():
                try:
                    docs = []
                    for fi in all_files:
                        docs.extend(await self._load_file(store, fi, config, prompt))
                    if docs:
                        await store.add_documents(documents=docs, table=table, schema=schema)
                    return {"status": "loaded", "documents": len(docs)}
                finally:
                    if tfm:
                        for fi in all_files:
                            try:
                                await tfm.delete_file(str(fi["file_path"]))
                            except Exception:  # noqa: BLE001
                                pass

            await jm.execute_job(job_id, _bg)
            return web.Response(
                content_type="application/json",
                body=json_encoder({
                    "job_id": job_id,
                    "status": "pending",
                    "message": "Data loading started in background",
                }),
            )

        # Immediate path
        docs: list[Document] = []
        try:
            for fi in all_files:
                docs.extend(await self._load_file(store, fi, config, prompt))
            if docs:
                await store.add_documents(documents=docs, table=table, schema=schema)
        finally:
            if tfm:
                for fi in all_files:
                    try:
                        await tfm.delete_file(str(fi["file_path"]))
                    except Exception:  # noqa: BLE001
                        pass

        return web.Response(
            content_type="application/json",
            body=json_encoder({"status": "loaded", "documents": len(docs)}),
        )

    async def _put_json_body(self, jm: Optional[JobManager]) -> web.Response:
        """Handle JSON body PUT (inline content or URL list).

        Args:
            jm: JobManager instance.

        Returns:
            Immediate or background-job JSON response.
        """
        body = await self.request.json()
        store_type = body.get("vector_store", "postgres")
        table = body.get("table")
        if not table:
            return web.Response(
                content_type="application/json",
                body=json_encoder({"error": "Missing required field: table"}),
                status=400,
            )
        schema = body.get("schema", "public")
        config = StoreConfig(
            vector_store=store_type,
            table=table,
            schema=schema,
            embedding_model=body.get("embedding_model", {"model": "thenlper/gte-base", "model_type": "huggingface"}),
            dimension=body.get("dimension", 768),
            dsn=body.get("dsn"),
        )
        store = await self._get_store(config)

        # Inline content
        if "content" in body:
            doc = Document(
                page_content=body["content"],
                metadata=body.get("metadata", {}),
            )
            await store.add_documents(documents=[doc], table=table, schema=schema)
            return web.Response(
                content_type="application/json",
                body=json_encoder({"status": "loaded", "documents": 1}),
            )

        # URL list
        if "url" in body:
            urls = body["url"] if isinstance(body["url"], list) else [body["url"]]
            crawl_entire_site = body.get("crawl_entire_site", False)
            prompt = body.get("prompt")
            content_extraction = body.get("content_extraction", "auto")

            if not jm:
                return web.Response(
                    content_type="application/json",
                    body=json_encoder({"error": "Job manager not available"}),
                    status=503,
                )

            job_id = uuid.uuid4().hex
            jm.create_job(
                job_id=job_id,
                obj_id="vectorstore",
                query={"urls": urls, "table": table},
            )

            async def _url_bg():
                docs = await self._load_urls(
                    store, urls, config, crawl_entire_site, prompt,
                    content_extraction=content_extraction,
                )
                if docs:
                    await store.add_documents(documents=docs, table=table, schema=schema)
                return {"status": "loaded", "documents": len(docs)}

            await jm.execute_job(job_id, _url_bg)
            return web.Response(
                content_type="application/json",
                body=json_encoder({
                    "job_id": job_id,
                    "status": "pending",
                    "message": "Data loading started in background",
                }),
            )

        return web.Response(
            content_type="application/json",
            body=json_encoder({"error": "Request must include 'content' or 'url' field"}),
            status=400,
        )

    async def _load_file(
        self,
        store: AbstractStore,
        file_info: dict,
        config: StoreConfig,
        prompt: Optional[str],
    ) -> list[Document]:
        """Load documents from a single uploaded file.

        Args:
            store: Connected store instance (not used directly here).
            file_info: Dict with 'file_path' and 'file_name' keys.
            config: StoreConfig for context.
            prompt: Optional prompt for image/video loaders.

        Returns:
            List of Document objects.
        """
        from pathlib import Path
        from parrot_loaders.factory import get_loader_class, LOADER_MAPPING
        from parrot_loaders.extractors.json_source import JSONDataSource

        file_path = str(file_info["file_path"])
        file_name = file_info.get("file_name", file_path)
        ext = Path(file_name).suffix.lower()

        if ext == ".json":
            source = JSONDataSource(source=file_path)
            result = await source.extract()
            # Convert extraction result to Document list
            if hasattr(result, "records"):
                return [Document(page_content=str(r), metadata={}) for r in result.records]
            return [Document(page_content=str(result), metadata={})]

        if ext in IMAGE_EXTENSIONS:
            from parrot_loaders.imageunderstanding import ImageUnderstandingLoader
            loader = ImageUnderstandingLoader(
                source=file_path,
                prompt=prompt or DEFAULT_IMAGE_PROMPT,
            )
            return await loader.load()

        if ext in VIDEO_EXTENSIONS:
            from parrot_loaders.videounderstanding import VideoUnderstandingLoader
            loader = VideoUnderstandingLoader(
                source=file_path,
                prompt=prompt or DEFAULT_VIDEO_PROMPT,
            )
            return await loader.load()

        loader_cls = get_loader_class(ext)
        loader = loader_cls(source=file_path)
        return await loader.load()

    async def _load_urls(
        self,
        store: AbstractStore,
        urls: list[str],
        config: StoreConfig,
        crawl_entire_site: bool = False,
        prompt: Optional[str] = None,
        content_extraction: str = "auto",
    ) -> list[Document]:
        """Load documents from a list of URLs.

        Delegates to WebScrapingLoader for content extraction, with
        trafilatura-based content isolation and intelligent fallback.

        Args:
            store: Connected store instance (not used directly here).
            urls: List of URLs to fetch.
            config: StoreConfig for context.
            crawl_entire_site: If True, crawl the entire site (depth=2).
            prompt: Optional prompt (unused for URL loading).
            content_extraction: Content extraction strategy passed to
                WebScrapingLoader. One of ``"auto"``, ``"trafilatura"``,
                ``"markdown"``, ``"text"``. Defaults to ``"auto"``.

        Returns:
            List of Document objects.
        """
        docs: list[Document] = []
        youtube_urls = [u for u in urls if self._is_youtube_url(u)]
        other_urls = [u for u in urls if not self._is_youtube_url(u)]

        if youtube_urls:
            from parrot_loaders.youtube import YoutubeLoader
            for url in youtube_urls:
                loader = YoutubeLoader(source=url)
                docs.extend(await loader.load())

        if other_urls:
            from parrot_loaders.webscraping import WebScrapingLoader
            loader = WebScrapingLoader(
                source=other_urls,
                crawl=crawl_entire_site,
                depth=2 if crawl_entire_site else 1,
                content_extraction=content_extraction,
            )
            docs.extend(await loader.load())

        return docs

    @staticmethod
    def _is_youtube_url(url: str) -> bool:
        """Check if a URL points to YouTube.

        Args:
            url: URL string to test.

        Returns:
            True if the URL is a YouTube URL.
        """
        return any(domain in url.lower() for domain in ("youtube.com", "youtu.be"))
