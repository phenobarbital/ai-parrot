# syntax=docker/dockerfile:1.7

# Redis 8 (Open Source) bundles the Redis Query Engine (RediSearch), JSON,
# TimeSeries and probabilistic data types. AI-Parrot needs:
#   - Redis >= 6.2  -> GETDEL (channel links, A2UI deep links, passkeys)
#   - Streams / Pub-Sub -> autonomous jobs, structured-output transport
#   - RediSearch (FT.CREATE / FT.SEARCH with VECTOR fields)
#                   -> parrot.memory.episodic.backends.redis_vector
FROM redis:8.2.2

LABEL org.opencontainers.image.title="ai-parrot-redis" \
      org.opencontainers.image.description="Local Redis (with Query Engine) for AI-Parrot development" \
      org.opencontainers.image.source="https://github.com/phenobarbital/ai-parrot"

COPY --chown=redis:redis redis.conf /usr/local/etc/redis/redis.conf

VOLUME ["/data"]
EXPOSE 6379

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD redis-cli -p 6379 ping | grep -q PONG || exit 1

CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]
