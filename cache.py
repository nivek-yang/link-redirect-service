# redirect-service/cache.py
import os
from typing import Generator

import redis


def get_redis_client_instance() -> redis.Redis:
    """
    Returns a new Redis client instance.
    This function is intended to be called once during application startup
    or for testing purposes.
    """
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True
    )  # 返回 python 字串
    try:
        client.ping()
        print(f"Connected to Redis: {REDIS_HOST}:{REDIS_PORT}")
    except redis.exceptions.ConnectionError as e:
        print(f"Redis connection failed: {e}")
        raise
    return client


def get_redis_db() -> Generator[redis.Redis, None, None]:
    """
    Dependency that provides a Redis client and handles its closing.
    """
    redis_client = get_redis_client_instance()
    try:
        yield redis_client
    finally:
        if redis_client:
            redis_client.close()
            print("Disconnected from Redis.")
