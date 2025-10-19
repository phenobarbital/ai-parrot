from rq import Queue
from redis import Redis
from aiohttp import web
from ...conf import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
)


def configure_redis_queue(app: web.Application) -> Queue:
    """
    Configure and return an RQ Queue connected to Redis.
    """
    redis_conn = Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    job_queue = Queue(connection=redis_conn)
    app['job_queue'] = job_queue
    return job_queue
