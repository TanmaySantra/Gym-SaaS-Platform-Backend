"""
Redis client used for caching / rate-limiting / ad-hoc key-value needs
outside of Celery's own broker connection (Celery manages its own connection
pool internally via CELERY_BROKER_URL).
"""
from functools import lru_cache

import redis

from app.core.config import settings


@lru_cache
def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
