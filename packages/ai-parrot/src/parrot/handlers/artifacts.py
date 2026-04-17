"""REST handler for artifact CRUD.

Provides endpoints for saving, loading, updating, and deleting
artifacts (charts, canvas tabs, infographics, dataframes, exports)
associated with a conversation thread.

FEAT-103: agent-artifact-persistency — Module 8.

Endpoints:
    GET    /api/v1/threads/{session_id}/artifacts               — list artifacts
    POST   /api/v1/threads/{session_id}/artifacts               — save artifact
    GET    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — get artifact
    PUT    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — update artifact
    DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}  — delete artifact
"""

from typing import Optional
from datetime import datetime, timezone

from aiohttp import web
from navigator.views import BaseView
from navigator_session import get_session
from navigator_auth.decorators import is_authenticated, user_session
from navigator_auth.conf import AUTH_SESSION_OBJECT

from ..storage.models import Artifact, ArtifactType, ArtifactCreator


@is_authenticated()
@user_session()
class ArtifactListView(BaseView):
    """List and create artifacts for a thread.

    GET  /api/v1/threads/{session_id}/artifacts      — list summaries
    POST /api/v1/threads/{session_id}/artifacts      — create artifact
    """

    _logger_name: str = "Parrot.ArtifactListView"

    def _get_artifact_store(self):
        """Retrieve ArtifactStore from the application context."""
        try:
            return self.request.app["artifact_store"]
        except KeyError:
            self.logger.error("artifact_store not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
        try:
            session = await get_session(self.request)
        except Exception:
            return None
        if session:
            userinfo = session.get(AUTH_SESSION_OBJECT, {})
            if isinstance(userinfo, dict):
                user_id = userinfo.get("user_id")
                if user_id:
                    return str(user_id)
            user_id = session.get("user_id")
            if user_id:
                return str(user_id)
        return None

    async def get(self) -> web.Response:
        """List all artifacts for a session as lightweight summaries.

        URL params:
            session_id: Conversation session identifier.
        Query params:
            agent_id (required): Agent/bot identifier.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "session_id is required in path"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")

        summaries = await store.list_artifacts(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )

        return self.json_response({
            "artifacts": [s.model_dump(mode="json") for s in summaries],
            "count": len(summaries),
        })

    async def post(self) -> web.Response:
        """Save a new artifact.

        URL params:
            session_id: Conversation session identifier.
        Body:
            artifact_id (required): Unique artifact identifier.
            artifact_type (required): One of chart, canvas, infographic, dataframe, export.
            title (required): Display title.
            agent_id (required): Agent/bot identifier.
            definition (optional): Artifact definition dict.
            source_turn_id (optional): Turn that generated this artifact.
            created_by (optional): "user", "agent", or "system" (default "user").
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "session_id is required in path"},
                status=400,
            )

        try:
            body = await self.json_data()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        # Validate required fields
        artifact_id = body.get("artifact_id")
        artifact_type = body.get("artifact_type")
        title = body.get("title")
        agent_id = body.get("agent_id")

        if not all([artifact_id, artifact_type, title, agent_id]):
            return self.error(
                response={"message": "artifact_id, artifact_type, title, and agent_id are required"},
                status=400,
            )

        # Validate artifact_type
        try:
            a_type = ArtifactType(artifact_type)
        except ValueError:
            return self.error(
                response={"message": f"Invalid artifact_type: {artifact_type}"},
                status=400,
            )

        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=a_type,
            title=title,
            created_at=now,
            updated_at=now,
            source_turn_id=body.get("source_turn_id"),
            created_by=body.get("created_by", ArtifactCreator.USER),
            definition=body.get("definition"),
        )

        await store.save_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact=artifact,
        )

        return self.json_response({
            "message": "Artifact saved",
            "artifact_id": artifact_id,
        }, status=201)


@is_authenticated()
@user_session()
class ArtifactDetailView(BaseView):
    """Detail operations on a single artifact.

    GET    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — get
    PUT    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — update
    DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}  — delete
    """

    _logger_name: str = "Parrot.ArtifactDetailView"

    def _get_artifact_store(self):
        """Retrieve ArtifactStore from the application context."""
        try:
            return self.request.app["artifact_store"]
        except KeyError:
            self.logger.error("artifact_store not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
        try:
            session = await get_session(self.request)
        except Exception:
            return None
        if session:
            userinfo = session.get(AUTH_SESSION_OBJECT, {})
            if isinstance(userinfo, dict):
                user_id = userinfo.get("user_id")
                if user_id:
                    return str(user_id)
            user_id = session.get("user_id")
            if user_id:
                return str(user_id)
        return None

    async def get(self) -> web.Response:
        """Get a single artifact with full definition resolved.

        URL params:
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        Query params:
            agent_id (required): Agent/bot identifier.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        artifact_id = self.request.match_info.get("artifact_id")
        if not session_id or not artifact_id:
            return self.error(
                response={"message": "session_id and artifact_id are required"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")

        artifact = await store.get_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )

        if artifact is None:
            return self.error(
                response={"message": f"Artifact {artifact_id} not found"},
                status=404,
            )

        return self.json_response({
            "artifact": artifact.model_dump(mode="json"),
        })

    async def put(self) -> web.Response:
        """Update an artifact's definition.

        URL params:
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        Body:
            agent_id (required): Agent/bot identifier.
            definition (required): New definition dict.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        artifact_id = self.request.match_info.get("artifact_id")
        if not session_id or not artifact_id:
            return self.error(
                response={"message": "session_id and artifact_id are required"},
                status=400,
            )

        try:
            body = await self.json_data()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        agent_id = body.get("agent_id")
        definition = body.get("definition")
        if not agent_id or definition is None:
            return self.error(
                response={"message": "agent_id and definition are required"},
                status=400,
            )

        await store.update_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
            definition=definition,
        )

        return self.json_response({
            "message": "Artifact updated",
            "artifact_id": artifact_id,
        })

    async def delete(self) -> web.Response:
        """Delete an artifact and clean up S3 data.

        URL params:
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        Query params:
            agent_id (required): Agent/bot identifier.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        artifact_id = self.request.match_info.get("artifact_id")
        if not session_id or not artifact_id:
            return self.error(
                response={"message": "session_id and artifact_id are required"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")

        deleted = await store.delete_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )

        if deleted:
            return self.json_response({
                "message": f"Artifact {artifact_id} deleted",
                "artifact_id": artifact_id,
            })
        return self.error(
            response={"message": f"Artifact {artifact_id} not found"},
            status=404,
        )
