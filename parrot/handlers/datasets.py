"""
HTTP handler for managing user's DatasetManager.

Provides REST endpoints for dataset operations:
- GET: List datasets with optional EDA metadata
- PATCH: Activate/deactivate datasets
- PUT: Upload Excel/CSV files
- POST: Add SQL queries or query slugs
- DELETE: Remove datasets
- GET /datasets/{agent_id}/{dataset_id}: Describe a single dataset
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from io import BytesIO
import pandas as pd
from aiohttp import web
from pydantic import ValidationError
from navigator_session import get_session
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
from .user_objects import UserObjectsHandler
from ..models.datasets import (
    DatasetAction,
    DatasetPatchRequest,
    DatasetQueryRequest,
    DatasetListResponse,
    DatasetUploadResponse,
    DatasetDeleteResponse,
)
from ..tools.dataset_manager import DatasetManager

if TYPE_CHECKING:
    pass


# Maximum file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None:
    """Clone an agent's DatasetManager into a fresh user-scoped instance.

    Copies both loaded DataFrames and query-slug-based datasets so the
    user starts with the full catalog the agent was configured with.

    Args:
        agent: The agent instance (must expose ``_dataset_manager``).
        logger: Logger used for per-entry warnings.

    Returns:
        A new DatasetManager seeded with the agent's datasets, or
        ``None`` if the agent has no DatasetManager or it is empty.
    """
    agent_dm: DatasetManager | None = getattr(agent, "_dataset_manager", None)
    if not agent_dm or not agent_dm._datasets:
        return None

    user_dm = DatasetManager()
    for name, entry in agent_dm._datasets.items():
        try:
            if entry.loaded and entry.df is not None:
                user_dm.add_dataframe(
                    name=name,
                    df=entry.df,
                    metadata=entry.metadata,
                    is_active=entry.is_active,
                )
            elif entry.query_slug:
                user_dm.add_query(
                    name=name,
                    query_slug=entry.query_slug,
                    metadata=entry.metadata,
                )
                if not entry.is_active:
                    user_dm.deactivate(name)
        except Exception as exc:
            logger.warning("Failed to clone dataset '%s' from agent: %s", name, exc)

    logger.debug("Cloned %d datasets from agent into user DatasetManager", len(user_dm._datasets))
    return user_dm


async def _resolve_dataset_manager(
    request: web.Request,
    agent_id: str,
    session_key: str,
    logger: object,
) -> DatasetManager:
    """Get or create a session-scoped DatasetManager, seeding from the agent if empty.

    Args:
        request: The current aiohttp request.
        agent_id: Agent identifier to look up in BotManager.
        session_key: Session key under which the DM is stored.
        logger: Logger for warnings/debug output.

    Returns:
        The user's DatasetManager.

    Raises:
        KeyError: If the agent is not registered in BotManager and there is
            no existing session DatasetManager to fall back to.
    """
    request_session = await get_session(request)

    dm = request_session.get(session_key)
    if dm is not None and isinstance(dm, DatasetManager) and dm._datasets:
        return dm

    bot_manager = request.app.get("bot_manager")
    agent = bot_manager._bots.get(agent_id) if bot_manager else None
    if agent is None:
        raise KeyError(agent_id)

    dm = _clone_agent_dm(agent, logger) or DatasetManager()
    request_session[session_key] = dm
    return dm


@is_authenticated()
@user_session()
class DatasetManagerHandler(BaseView):
    """
    HTTP handler for managing user's DatasetManager via REST API.

    Endpoints:
        GET    /api/v1/agents/datasets/{agent_id} - List datasets
        PATCH  /api/v1/agents/datasets/{agent_id} - Activate/deactivate dataset
        PUT    /api/v1/agents/datasets/{agent_id} - Upload file as dataset
        POST   /api/v1/agents/datasets/{agent_id} - Add query as dataset
        DELETE /api/v1/agents/datasets/{agent_id} - Delete dataset
    """

    _user_objects_handler: UserObjectsHandler = None

    @property
    def user_objects_handler(self) -> UserObjectsHandler:
        """Lazy-initialized UserObjectsHandler instance."""
        if self._user_objects_handler is None:
            self._user_objects_handler = UserObjectsHandler(logger=self.logger)
        return self._user_objects_handler

    async def _get_dataset_manager(self, agent_id: str) -> DatasetManager:
        """Get or create user's DatasetManager from session.

        Raises:
            KeyError: If the agent is not found in BotManager and there is
                no existing session DatasetManager for this agent_id.
        """
        session_key = self.user_objects_handler.get_session_key(
            agent_id, "dataset_manager"
        )
        return await _resolve_dataset_manager(
            self.request, agent_id, session_key, self.logger
        )

    async def get(self) -> web.Response:
        """
        List all datasets in user's DatasetManager.

        Query params:
            eda: bool - Include EDA metadata (default: false)

        Returns:
            DatasetListResponse with dataset information
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        include_eda = self.request.query.get('eda', '').lower() == 'true'

        try:
            dm = await self._get_dataset_manager(agent_id)
            # list_available() is async and returns all datasets
            datasets_info = await dm.list_available()

            datasets = []
            for info in datasets_info:
                dataset_dict = {
                    "name": info.get("name", ""),
                    "description": info.get("description", ""),
                    "shape": info.get("shape", (0, 0)),
                    "is_active": info.get("is_active", True),
                    "loaded": info.get("loaded", False),
                }

                if include_eda and info.get("loaded"):
                    try:
                        name = info.get("name")
                        metadata = await dm.get_metadata(name, include_eda=True)
                        dataset_dict["metadata"] = metadata
                    except Exception as e:
                        self.logger.warning(f"Failed to get EDA for {name}: {e}")

                datasets.append(dataset_dict)

            response = DatasetListResponse(
                datasets=datasets,
                total=len(datasets),
                active_count=sum(1 for d in datasets if d.get("is_active", True))
            )
            return self.json_response(response.model_dump())

        except KeyError:
            return self.json_response(
                {"error": f"Agent '{agent_id}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error listing datasets: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def patch(self) -> web.Response:
        """
        Activate or deactivate a dataset.

        Body: DatasetPatchRequest
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        try:
            data = await self.request.json()
            request_body = DatasetPatchRequest(**data)
        except ValidationError as e:
            return self.json_response(
                {"error": "Invalid request", "detail": str(e)},
                status=400
            )
        except Exception as e:
            return self.json_response(
                {"error": f"Invalid JSON: {e}"},
                status=400
            )

        try:
            dm = await self._get_dataset_manager(agent_id)

            if request_body.action == DatasetAction.ACTIVATE:
                result = dm.activate(request_body.dataset_name)
                if not result:
                    return self.json_response(
                        {"error": f"Dataset '{request_body.dataset_name}' not found"},
                        status=404
                    )
                message = f"Dataset '{request_body.dataset_name}' activated"
            else:
                result = dm.deactivate(request_body.dataset_name)
                if not result:
                    return self.json_response(
                        {"error": f"Dataset '{request_body.dataset_name}' not found"},
                        status=404
                    )
                message = f"Dataset '{request_body.dataset_name}' deactivated"

            return self.json_response({
                "name": request_body.dataset_name,
                "action": request_body.action,
                "message": message
            })
        except KeyError:
            return self.json_response(
                {"error": f"Agent '{agent_id}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error patching dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def put(self) -> web.Response:
        """
        Upload an Excel/CSV file as a new dataset.

        Accepts multipart/form-data with:
            file: The file to upload
            name: Optional dataset name (defaults to filename)
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        try:
            reader = await self.request.multipart()
            dataset_name = None
            df = None
            filename = None

            async for field in reader:
                if field.name == 'name':
                    dataset_name = (await field.read()).decode('utf-8')
                elif field.name == 'file':
                    filename = field.filename
                    data = await field.read()

                    if len(data) > MAX_FILE_SIZE:
                        return self.json_response(
                            {"error": f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"},
                            status=400
                        )

                    # Determine format from extension
                    if filename.endswith(('.xlsx', '.xls')):
                        df = pd.read_excel(BytesIO(data))
                    elif filename.endswith('.csv'):
                        df = pd.read_csv(BytesIO(data))
                    else:
                        return self.json_response(
                            {"error": "Unsupported file format. Use .xlsx, .xls, or .csv"},
                            status=400
                        )

            if df is None:
                return self.json_response(
                    {"error": "No file provided"},
                    status=400
                )

            # Use filename without extension as default name
            if not dataset_name:
                dataset_name = filename.rsplit('.', 1)[0] if filename else "uploaded_dataset"

            dm = await self._get_dataset_manager(agent_id)
            dm.add_dataframe(dataset_name, df)

            response = DatasetUploadResponse(
                name=dataset_name,
                rows=len(df),
                columns=len(df.columns),
                columns_list=list(df.columns)
            )
            return self.json_response(response.model_dump(), status=201)

        except KeyError:
            return self.json_response(
                {"error": f"Agent '{agent_id}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error uploading dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def post(self) -> web.Response:
        """
        Add a query slug as a new dataset.

        Body: DatasetQueryRequest

        Note: Raw SQL queries are not directly supported. Use query_slug
        to reference pre-configured queries in QuerySource.
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        try:
            data = await self.request.json()
            request_body = DatasetQueryRequest(**data)
            request_body.validate_query_source()
        except ValidationError as e:
            return self.json_response(
                {"error": "Invalid request", "detail": str(e)},
                status=400
            )
        except ValueError as e:
            return self.json_response(
                {"error": str(e)},
                status=400
            )
        except Exception as e:
            return self.json_response(
                {"error": f"Invalid JSON: {e}"},
                status=400
            )

        try:
            dm = await self._get_dataset_manager(agent_id)

            # DatasetManager.add_query() accepts query_slug for lazy loading
            # Raw SQL is stored as metadata but loaded via query_slug
            if request_body.query_slug:
                dm.add_query(
                    name=request_body.name,
                    query_slug=request_body.query_slug,
                    metadata={"description": request_body.description or ""}
                )
                query_type = "query_slug"
            elif request_body.query:
                # Store raw SQL in metadata; requires query loader to handle
                dm.add_query(
                    name=request_body.name,
                    query_slug=request_body.name,  # Use name as slug placeholder
                    metadata={
                        "description": request_body.description or "",
                        "raw_sql": request_body.query
                    }
                )
                query_type = "query"
            else:
                return self.json_response(
                    {"error": "Either 'query' or 'query_slug' must be provided"},
                    status=400
                )

            return self.json_response({
                "name": request_body.name,
                "type": query_type,
                "message": f"Query dataset '{request_body.name}' added successfully"
            }, status=201)

        except KeyError:
            return self.json_response(
                {"error": f"Agent '{agent_id}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error adding query dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )

    async def delete(self) -> web.Response:
        """
        Delete a dataset from the DatasetManager.

        Query params:
            name: str - Dataset name to delete
        """
        agent_id = self.request.match_info.get('agent_id')
        if not agent_id:
            return self.json_response(
                {"error": "agent_id is required"},
                status=400
            )

        dataset_name = self.request.query.get('name')
        if not dataset_name:
            return self.json_response(
                {"error": "Query parameter 'name' is required"},
                status=400
            )

        try:
            dm = await self._get_dataset_manager(agent_id)
            dm.remove(dataset_name)

            response = DatasetDeleteResponse(name=dataset_name)
            return self.json_response(response.model_dump())

        except KeyError:
            return self.json_response(
                {"error": f"Agent '{agent_id}' not found"},
                status=404
            )
        except ValueError:
            # remove() raises ValueError for not found
            return self.json_response(
                {"error": f"Dataset '{dataset_name}' not found"},
                status=404
            )
        except Exception as e:
            self.logger.error(f"Error deleting dataset: {e}")
            return self.json_response(
                {"error": str(e)},
                status=500
            )


@is_authenticated()
@user_session()
class DatasetDetailHandler(BaseView):
    """
    HTTP handler for describing a single dataset.

    Endpoint:
        GET /api/v1/agents/datasets/{agent_id}/{dataset_id}

    Query params:
        eda: bool             - Include EDA summary (default: false)
        samples: bool         - Include sample rows (default: false)
        column_stats: bool    - Include per-column statistics (default: false)
        metrics_guide: bool   - Include metrics guide (default: false)
        column: str           - Describe a single column only (optional)
    """

    _user_objects_handler: UserObjectsHandler = None

    @property
    def user_objects_handler(self) -> UserObjectsHandler:
        """Lazy-initialized UserObjectsHandler instance."""
        if self._user_objects_handler is None:
            self._user_objects_handler = UserObjectsHandler(logger=self.logger)
        return self._user_objects_handler

    async def get(self) -> web.Response:
        """Return full metadata / describe for a single dataset."""
        agent_id = self.request.match_info.get("agent_id")
        dataset_id = self.request.match_info.get("dataset_id")

        if not agent_id or not dataset_id:
            return self.json_response(
                {"error": "agent_id and dataset_id are required"},
                status=400,
            )

        q = self.request.query
        include_eda = q.get("eda", "").lower() == "true"
        include_samples = q.get("samples", "").lower() == "true"
        include_column_stats = q.get("column_stats", "").lower() == "true"
        include_metrics_guide = q.get("metrics_guide", "").lower() == "true"
        column = q.get("column") or None

        try:
            dm = await self._get_dataset_manager(agent_id)
        except KeyError:
            return self.json_response(
                {"error": f"Agent '{agent_id}' not found"},
                status=404,
            )

        try:
            metadata = await dm.get_metadata(
                name=dataset_id,
                include_eda=include_eda,
                include_samples=include_samples,
                include_column_stats=include_column_stats,
                include_metrics_guide=include_metrics_guide,
                column=column,
            )
            return self.json_response(metadata)

        except KeyError:
            return self.json_response(
                {"error": f"Dataset '{dataset_id}' not found"},
                status=404,
            )
        except Exception as e:
            self.logger.error("Error describing dataset '%s': %s", dataset_id, e)
            return self.json_response({"error": str(e)}, status=500)

    async def _get_dataset_manager(self, agent_id: str) -> DatasetManager:
        """Get the user's DatasetManager from session, seeding from the agent if empty.

        Raises:
            KeyError: If the agent is not found in BotManager and there is no
                existing session DatasetManager for this agent_id.
        """
        session_key = self.user_objects_handler.get_session_key(
            agent_id, "dataset_manager"
        )
        return await _resolve_dataset_manager(
            self.request, agent_id, session_key, self.logger
        )
