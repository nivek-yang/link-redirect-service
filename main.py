import os
from contextlib import asynccontextmanager

import redis
from cache import get_redis_db
from database import close_mongo_connection, connect_to_mongo
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from messaging import publish_click_event
from models import Link

# Global variables for MongoDB client (仍然需要，因為Beanie初始化需要)
mongo_client = None
mongodb = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, mongodb
    # Connect to MongoDB
    mongo_client, mongodb = await connect_to_mongo()
    # Redis connection will be handled by dependency injection per request
    yield
    # Close MongoDB connection on shutdown
    await close_mongo_connection(mongo_client)
    # Redis connection is closed by the dependency's finally block


app = FastAPI(
    title="Redirect Service",
    description="Service for handling short link redirections.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["Health Check"])
async def health_check():
    """
    Health check endpoint to verify service status.
    """
    return {"status": "ok", "message": "Redirect Service is running!"}


@app.get("/r/{slug}", tags=["Redirect"])
async def redirect_to_original_url(
    slug: str, redis_client: redis.Redis = Depends(get_redis_db)
):
    """
    Redirects to the original URL based on the provided slug.
    """
    # 1. Try to get from Redis cache
    cached_link_data = redis_client.hgetall(
        f"link_data:{slug}"
    )  # 使用 HGETALL 獲取所有欄位
    if cached_link_data:
        print(f"Cache hit for slug: {slug}")
        # 將 bytes 轉換為 Python 類型
        is_active = (
            cached_link_data.get("is_active") == b"True"
        )  # 注意這裡從 bytes 比較
        password = (
            cached_link_data.get("password").decode("utf-8")
            if cached_link_data.get("password")
            else None
        )
        original_url = cached_link_data.get("original_url").decode("utf-8")

        if not is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,  # 403 Forbidden for inactive links
                detail="Short link is inactive.",
            )

        if password:
            # Redirect to Django's password entry page (original short URL path)
            django_frontend_url = os.environ.get(
                "DJANGO_FRONTEND_URL", "http://localhost:8000"
            )
            return RedirectResponse(
                url=f"{django_frontend_url}/{slug}", status_code=status.HTTP_302_FOUND
            )

        # Publish click event asynchronously
        publish_click_event(slug)
        return RedirectResponse(url=original_url, status_code=status.HTTP_302_FOUND)

    # 2. If not in cache, query MongoDB
    link = await Link.find_one(Link.slug == slug)

    if not link:
        # Cache a "not found" value to prevent cache penetration
        redis_client.set(
            f"link_data:{slug}", "NULL", ex=60
        )  # Cache "NULL" for 60 seconds
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found."
        )

    if not link.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,  # 403 Forbidden for inactive links
            detail="Short link is inactive.",
        )

    # Handle password protected links
    if link.password:
        # Redirect to Django's password entry page (original short URL path)
        django_frontend_url = os.environ.get(
            "DJANGO_FRONTEND_URL", "http://localhost:8000"
        )
        return RedirectResponse(
            url=f"{django_frontend_url}/{slug}", status_code=status.HTTP_302_FOUND
        )

    # 3. Store in Redis cache for future requests
    # 使用 HSET 儲存多個欄位
    redis_client.hmset(
        f"link_data:{slug}",
        {
            "original_url": link.original_url,
            "is_active": str(link.is_active),  # Convert boolean to string for Redis
            "password": link.password if link.password else "",
        },
    )
    redis_client.expire(f"link_data:{slug}", 3600 * 24 * 7)  # Cache for 7 days
    print(f"Cache miss for slug: {slug}, fetched from DB and cached.")

    # 4. Publish click event asynchronously
    publish_click_event(slug)

    return RedirectResponse(url=link.original_url, status_code=status.HTTP_302_FOUND)
