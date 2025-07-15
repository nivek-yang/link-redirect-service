# redirect-service/cache.py
import os

import redis

redis_client: redis.Redis = None


def get_redis_client():
    global redis_client
    if redis_client is None:
        REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
        REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
        redis_client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True
        )
        try:
            redis_client.ping()
            print(f"Connected to Redis: {REDIS_HOST}:{REDIS_PORT}")
        except redis.exceptions.ConnectionError as e:
            print(f"Redis connection failed: {e}")
            redis_client = None  # Reset to None if connection fails
            raise
    return redis_client


def close_redis_connection():
    global redis_client
    if redis_client:
        redis_client.close()
        print("Disconnected from Redis.")
        redis_client = None
