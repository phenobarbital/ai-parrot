from rq import Queue
from redis import Redis
from aiohttp import web
from ...conf import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
)
from .job import JobManager


def configure_redis_queue(app: web.Application) -> Queue:
    """
    Configure and return an RQ Queue connected to Redis.
    """
    redis_conn = Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    job_queue = Queue(connection=redis_conn)
    app['job_queue'] = job_queue
    print("✅ RQ Queue configured")
    return job_queue

def configure_job_manager(app: web.Application):
    """Configure and start job manager."""
    app['job_manager'] = JobManager()
    async def start_job_manager(app: web.Application):
        """Start job manager on app startup."""
        await app['job_manager'].start()
        print("✅ Job manager started")

    # Register startup hook
    app.on_startup.append(start_job_manager)
