"""TASK-3333: owner-checked job polling and artifact delivery tests.

Exercises ``VideoReelHandler``'s session-derived job ownership (§8 Q7 —
never trust a body-supplied ``user_id`` as ownership), ``_resolve_job_id``'s
route/query conflict handling, ``_get_artifact``'s local streaming and
cloud signed-URL redirect delivery, and ``_get_job_status``'s refreshed
cloud signed URLs and ``CANCELLED``-state handling.

Mocks the provider-facing surface (``JobManager``, session resolution,
``FileManagerInterface``) while the REAL ``VideoReelHandler`` authorization/
routing logic runs end to end. No default test performs a paid provider
call or touches the network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.handlers.jobs import JobStatus

# Fixed test identities: `_OWNER_ID` is who `handler`'s session resolves to
# by default; `_OTHER_USER_ID` is used wherever a test needs "logged in,
# but not the owner".
_OWNER_ID = "owner-user-1"
_OTHER_USER_ID = "other-user-2"


def _make_response(body, status=200, content_type="application/json"):
    """Build a lightweight fake web.Response-like object."""
    resp = MagicMock()
    resp.status = status
    resp.body = body
    resp.content_type = content_type
    return resp


def _make_job(
    job_id="job-abc",
    status_value="completed",
    result=None,
    error=None,
    elapsed_time=None,
    started_at=None,
    completed_at=None,
    user_id=_OWNER_ID,
):
    """Create a lightweight mock Job, owned by `_OWNER_ID` by default."""
    job = MagicMock()
    job.job_id = job_id
    job.status = JobStatus(status_value)
    job.result = result
    job.error = error
    job.elapsed_time = elapsed_time
    job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job.started_at = started_at
    job.completed_at = completed_at
    job.user_id = user_id
    return job


@pytest.fixture
def handler():
    """VideoReelHandler with mocked internals, authenticated as `_OWNER_ID` by default."""
    from parrot.handlers.video_reel import VideoReelHandler

    h = VideoReelHandler.__new__(VideoReelHandler)
    h.logger = MagicMock()
    # Real BaseView-compatible construction (mirrors test_video_reel_handler.py's
    # `handler` fixture): set the backing `_request` attribute directly since
    # `request` is a read-only property.
    h._request = MagicMock()

    mock_jm = MagicMock()
    mock_jm.get_job_async = AsyncMock(return_value=None)
    mock_jm.create_job = MagicMock()
    mock_jm.execute_job = AsyncMock()
    h.request.app = {"job_manager": mock_jm}
    h.request.content_type = "application/json"
    h.request.match_info = {}
    h.request.query = {}

    h.error = MagicMock(
        side_effect=lambda *a, **kw: _make_response(
            body=kw.get("response", a[0] if a else "error"),
            status=kw.get("status", 400),
        )
    )
    h.json_response = MagicMock(side_effect=lambda data, **kw: _make_response(body=data, status=kw.get("status", 200)))
    # Bypass real navigator-auth session machinery — fixed to a known
    # identity, matching `_make_job()`'s default owner.
    h._get_session_user_id = AsyncMock(return_value=_OWNER_ID)
    return h


class TestJobIdResolution:
    """`_resolve_job_id`: route match_info vs ?job_id= query (spec §3 M8)."""

    def test_route_only(self, handler):
        handler.request.match_info = {"job_id": "job-1"}
        assert handler._resolve_job_id() == "job-1"

    def test_query_only(self, handler):
        handler.request.query = {"job_id": "job-1"}
        assert handler._resolve_job_id() == "job-1"

    def test_route_and_query_agree(self, handler):
        handler.request.match_info = {"job_id": "job-1"}
        handler.request.query = {"job_id": "job-1"}
        assert handler._resolve_job_id() == "job-1"

    def test_route_and_query_conflict_raises_400(self, handler):
        handler.request.match_info = {"job_id": "job-1"}
        handler.request.query = {"job_id": "job-2"}
        with pytest.raises(web.HTTPBadRequest):
            handler._resolve_job_id()

    def test_neither_given_returns_none(self, handler):
        assert handler._resolve_job_id() is None


class TestJobOwnership:
    """`_authorize_job`: session identity must own the job; else non-disclosing 404."""

    async def test_owner_allowed(self, handler):
        job = _make_job(user_id=_OWNER_ID)
        await handler._authorize_job(job)  # must not raise

    async def test_other_user_denied_non_disclosing_404(self, handler):
        handler._get_session_user_id = AsyncMock(return_value=_OTHER_USER_ID)
        job = _make_job(user_id=_OWNER_ID)
        with pytest.raises(web.HTTPNotFound):
            await handler._authorize_job(job)

    async def test_missing_and_unauthorized_jobs_are_indistinguishable(self, handler):
        """A nonexistent job and one owned by someone else both surface as
        404 on the wire — a caller cannot tell "doesn't exist" from
        "exists but isn't yours". (The "missing" path returns via the
        real ``BaseView.error()``, which itself raises ``HTTPNotFound`` in
        production — this fixture mocks it to return the 404 response
        object instead, matching test_video_reel_handler.py's convention;
        the "unauthorized" path raises directly from ``_authorize_job``.
        Both are compared by their wire-visible status, which is what
        non-disclosure actually means to the caller.)
        """
        handler.job_manager.get_job_async = AsyncMock(return_value=None)
        missing_response = await handler._get_job_status("does-not-exist")
        assert missing_response.status == 404

        handler._get_session_user_id = AsyncMock(return_value=_OTHER_USER_ID)
        job = _make_job(job_id="exists-but-not-yours", user_id=_OWNER_ID)
        handler.job_manager.get_job_async = AsyncMock(return_value=job)
        with pytest.raises(web.HTTPNotFound) as unauthorized_exc:
            await handler._get_job_status("exists-but-not-yours")

        assert unauthorized_exc.value.status == missing_response.status == 404

    async def test_job_with_no_recorded_owner_denied_to_everyone(self, handler):
        """A legacy/anonymous job (user_id=None) is fail-closed, not fail-open."""
        job = _make_job(user_id=None)
        with pytest.raises(web.HTTPNotFound):
            await handler._authorize_job(job)

    async def test_unauthenticated_caller_denied(self, handler):
        handler._get_session_user_id = AsyncMock(return_value=None)
        job = _make_job(user_id=_OWNER_ID)
        with pytest.raises(web.HTTPNotFound):
            await handler._authorize_job(job)


class TestSpoofedBodyIdentityIgnored:
    """post(): a body-supplied `user_id` is never trusted as ownership (§8 Q7)."""

    async def test_post_never_uses_body_user_id_for_ownership(self, handler):
        """A caller claiming to be someone else in the body is ignored for ownership."""
        created_job = _make_job(user_id=_OWNER_ID)
        handler.job_manager.create_job = MagicMock(return_value=created_job)
        handler.request.json = AsyncMock(
            return_value={
                "prompt": "a reel",
                "user_id": _OTHER_USER_ID,  # spoofed claim
            }
        )

        await handler.post()

        create_kwargs = handler.job_manager.create_job.call_args.kwargs
        assert create_kwargs["user_id"] == _OWNER_ID
        assert create_kwargs["user_id"] != _OTHER_USER_ID

    async def test_post_rejects_unauthenticated_submission(self, handler):
        handler._get_session_user_id = AsyncMock(return_value=None)
        handler.request.json = AsyncMock(return_value={"prompt": "a reel"})

        with pytest.raises(web.HTTPUnauthorized):
            await handler.post()


class TestCancelledJobState:
    """`_get_job_status` handles CANCELLED consistently with JobManager's own semantics."""

    async def test_cancelled_status_surfaces_error_and_completed_at(self, handler):
        completed = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
        job = _make_job(status_value="cancelled", error="Job was cancelled", completed_at=completed)
        handler.request.match_info = {"job_id": "job-abc"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        result = await handler.get()

        assert result.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert response_data["status"] == "cancelled"
        assert response_data["error"] == "Job was cancelled"
        assert response_data["completed_at"] == completed.isoformat()


class TestSignedUrlRefreshOnPoll:
    """`_get_job_status` refreshes cloud signed URLs from stable storage keys."""

    async def test_cloud_artifact_download_url_refreshed_on_poll(self, handler):
        result = {
            "artifacts": [
                {
                    "artifact_id": "art-1",
                    "storage_backend": "s3",
                    "storage_key": "reels/job-abc/final/final_reel.mp4",
                    "mime_type": "video/mp4",
                    "download_url": "https://stale-signed-url?exp=1",
                }
            ],
            "metadata": {
                "video_reel": {
                    "final_artifact": {
                        "artifact_id": "art-1",
                        "download_url": "https://stale-signed-url?exp=1",
                    }
                }
            },
        }
        job = _make_job(status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        fresh_fm = AsyncMock()
        fresh_fm.get_file_url = AsyncMock(return_value="https://fresh-signed-url?exp=2&sig=abc")
        handler._create_file_manager = MagicMock(return_value=fresh_fm)

        response = await handler.get()

        assert response.status == 200
        response_data = handler.json_response.call_args[0][0]
        refreshed = response_data["result"]["artifacts"][0]["download_url"]
        assert refreshed == "https://fresh-signed-url?exp=2&sig=abc"
        # AC10: both serialized copies of the artifact stay consistent.
        assert response_data["result"]["metadata"]["video_reel"]["final_artifact"]["download_url"] == refreshed
        fresh_fm.get_file_url.assert_awaited_once_with("reels/job-abc/final/final_reel.mp4")

    async def test_local_artifact_download_url_never_refreshed(self, handler):
        result = {
            "artifacts": [
                {
                    "artifact_id": "art-1",
                    "storage_backend": "fs",
                    "storage_key": "reels/job-abc/final/final_reel.mp4",
                    "download_url": "file:///data/reels/job-abc/final/final_reel.mp4",
                }
            ],
        }
        job = _make_job(status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)
        handler._create_file_manager = MagicMock(side_effect=AssertionError("must not be called for fs"))

        response = await handler.get()

        assert response.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert (
            response_data["result"]["artifacts"][0]["download_url"] == "file:///data/reels/job-abc/final/final_reel.mp4"
        )

    async def test_refresh_failure_preserves_stale_url_and_does_not_fail_poll(self, handler):
        result = {
            "artifacts": [
                {
                    "artifact_id": "art-1",
                    "storage_backend": "gcs",
                    "storage_key": "reels/job-abc/final/final_reel.mp4",
                    "download_url": "https://stale-signed-url",
                }
            ],
        }
        job = _make_job(status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)
        handler._create_file_manager = MagicMock(side_effect=RuntimeError("bucket unreachable"))

        response = await handler.get()

        assert response.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert response_data["result"]["artifacts"][0]["download_url"] == "https://stale-signed-url"


class TestArtifactDelivery:
    """`_get_artifact`: resolves ReelResult.final_artifact by id; never a raw path."""

    async def test_local_artifact_streams_bytes(self, handler, tmp_path):
        local_file = tmp_path / "final_reel.mp4"
        local_file.write_bytes(b"FAKEVIDEOBYTES")
        result = {
            "artifacts": [
                {"artifact_id": "art-1", "storage_backend": "fs", "storage_key": "k", "mime_type": "video/mp4"},
            ],
            "files": [str(local_file)],
        }
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        stream_mock = MagicMock()
        handler._stream_file = AsyncMock(return_value=stream_mock)

        response = await handler.get()

        assert response is stream_mock
        handler._stream_file.assert_awaited_once()
        called_path, called_type = handler._stream_file.call_args.args
        assert called_path == local_file
        assert called_type == "video/mp4"

    async def test_temp_backend_artifact_streams_bytes(self, handler, tmp_path):
        local_file = tmp_path / "final_reel.mp4"
        local_file.write_bytes(b"FAKEVIDEOBYTES")
        result = {
            "artifacts": [{"artifact_id": "art-1", "storage_backend": "temp", "storage_key": "k"}],
            "files": [str(local_file)],
        }
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        stream_mock = MagicMock()
        handler._stream_file = AsyncMock(return_value=stream_mock)

        response = await handler.get()

        assert response is stream_mock

    async def test_missing_local_file_returns_404(self, handler, tmp_path):
        missing = tmp_path / "gone.mp4"
        result = {
            "artifacts": [{"artifact_id": "art-1", "storage_backend": "fs", "storage_key": "k"}],
            "files": [str(missing)],
        }
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()

    async def test_unknown_artifact_id_returns_404(self, handler):
        result = {"artifacts": [{"artifact_id": "art-1", "storage_backend": "fs"}], "files": ["/x"]}
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "does-not-exist"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()

    async def test_traversal_shaped_artifact_id_never_touches_filesystem(self, handler):
        """`artifact_id` is only ever compared by string equality against
        recorded artifacts — never interpolated into a path — so a
        traversal-shaped id simply fails to match (404); the filesystem is
        never touched with attacker-influenced input."""
        result = {"artifacts": [{"artifact_id": "art-1", "storage_backend": "fs"}], "files": ["/x"]}
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "../../../etc/passwd"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()

    async def test_incomplete_job_artifact_request_returns_404(self, handler):
        job = _make_job(job_id="job-abc", status_value="running", result=None)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()

    async def test_cloud_artifact_redirects_to_freshly_signed_url_preserving_query(self, handler):
        result = {
            "artifacts": [
                {
                    "artifact_id": "art-1",
                    "storage_backend": "s3",
                    "storage_key": "reels/job-abc/final/final_reel.mp4",
                    "mime_type": "video/mp4",
                }
            ],
        }
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)

        fresh_fm = AsyncMock()
        fresh_fm.get_file_url = AsyncMock(return_value="https://fresh-signed-url?sig=xyz&exp=123")
        handler._create_file_manager = MagicMock(return_value=fresh_fm)

        with pytest.raises(web.HTTPFound) as exc_info:
            await handler.get()

        assert exc_info.value.location == "https://fresh-signed-url?sig=xyz&exp=123"
        fresh_fm.get_file_url.assert_awaited_once_with("reels/job-abc/final/final_reel.mp4")

    async def test_cloud_backend_not_configured_returns_404(self, handler):
        result = {
            "artifacts": [{"artifact_id": "art-1", "storage_backend": "gcs", "storage_key": "k"}],
        }
        job = _make_job(job_id="job-abc", status_value="completed", result=result)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)
        handler._create_file_manager = MagicMock(return_value=None)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()

    async def test_artifact_route_enforces_ownership(self, handler):
        """`_artifact_route_owner_only` (spec §4 M8 test list)."""
        result = {"artifacts": [{"artifact_id": "art-1", "storage_backend": "fs"}], "files": ["/x"]}
        job = _make_job(job_id="job-abc", status_value="completed", result=result, user_id=_OWNER_ID)
        handler.request.match_info = {"job_id": "job-abc", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=job)
        handler._get_session_user_id = AsyncMock(return_value=_OTHER_USER_ID)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()

    async def test_artifact_route_missing_job_returns_404(self, handler):
        handler.request.match_info = {"job_id": "does-not-exist", "artifact_id": "art-1"}
        handler.job_manager.get_job_async = AsyncMock(return_value=None)

        with pytest.raises(web.HTTPNotFound):
            await handler.get()
