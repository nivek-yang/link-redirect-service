# redirect-service/main.py
from contextlib import asynccontextmanager
from typing import Optional

import redis
from cache import get_redis_db
from database import close_mongo_connection, connect_to_mongo
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from messaging import publish_click_event
from models import Link
from passlib.context import CryptContext  # 導入密碼雜湊工具
from starlette.middleware.cors import CORSMiddleware  # 導入 CORSMiddleware

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允許所有來源，開發環境使用
    allow_credentials=True,
    allow_methods=["*"],  # 允許所有 HTTP 方法
    allow_headers=["*"],  # 允許所有標頭
)


@app.get("/health", tags=["Health Check"])
async def health_check():
    """
    Health check endpoint to verify service status.
    """
    return {"status": "ok", "message": "Redirect Service is running!"}


@app.get("/r/{slug}", tags=["Redirect"])
async def redirect_to_original_url(
    slug: str,
    request: Request,  # 導入 Request 以獲取查詢參數
    redis_client: redis.Redis = Depends(get_redis_db),
    password: Optional[str] = Query(
        None, description="Password for protected short links"
    ),
):
    """
    Redirects to the original URL based on the provided slug.
    """
    # 1. Try to get from Redis cache
    cached_link_data = redis_client.hgetall(f"link_data:{slug}")

    if cached_link_data:
        print(f"Cache hit for slug: {slug}, data: {cached_link_data}")
        is_active = cached_link_data.get("is_active") == "True"
        password_hash = (
            cached_link_data.get("password")
            if cached_link_data.get("password")
            else None
        )
        original_url = cached_link_data.get("original_url")

        if not is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Short link is inactive.",
            )

        # Handle password protected links (from cache)
        if password_hash:
            provided_password = request.query_params.get("password")
            if not provided_password or not pwd_context.verify(
                provided_password, password_hash
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Password required or incorrect password.",
                )
            # 如果密碼正確，則繼續重導向
            publish_click_event(slug)
            return RedirectResponse(url=original_url, status_code=status.HTTP_302_FOUND)

        publish_click_event(slug)  # 只有在成功重導向時才發布事件
        return RedirectResponse(url=original_url, status_code=status.HTTP_302_FOUND)

    # Check for NULL marker if hash is empty or key type is string
    cached_string_value = redis_client.get(f"link_data:{slug}")
    if cached_string_value == "NULL":
        print(f"Cache hit for slug: {slug} (NULL marker)")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found."
        )

    # 2. If not in cache (or was NULL marker/empty hash), query MongoDB
    link = await Link.find_one(Link.slug == slug)

    if not link:
        # Cache a "not found" value to prevent cache penetration
        # 儲存為字串，而不是 Hash，以區分
        redis_client.set(f"link_data:{slug}", "NULL", ex=60)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found."
        )

    # 3. Store in Redis cache for future requests (moved up)
    redis_client.hmset(
        f"link_data:{slug}",
        {
            "original_url": link.original_url,
            "is_active": str(link.is_active),
            "password": link.password if link.password else "",
        },
    )
    redis_client.expire(f"link_data:{slug}", 3600 * 24 * 7)
    print(f"Cache miss for slug: {slug}, fetched from DB and cached.")

    if not link.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Short link is inactive.",
        )

    # Handle password protected links (from DB)
    if link.password:
        provided_password = request.query_params.get("password")
        if not provided_password or not pwd_context.verify(
            provided_password, link.password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password required or incorrect password.",
            )
        # 如果密碼正確，則繼續重導向
        publish_click_event(slug)
        return RedirectResponse(
            url=link.original_url, status_code=status.HTTP_302_FOUND
        )

    publish_click_event(slug)  # 只有在成功重導向時才發布事件
    return RedirectResponse(url=link.original_url, status_code=status.HTTP_302_FOUND)
