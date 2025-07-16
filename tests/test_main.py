# redirect_service/tests/test_main.py
import hashlib
import os
from unittest.mock import patch

import pytest
import pytest_asyncio  # 確保已安裝 uv add pytest-asyncio --group dev
import redis  # 導入 redis 模組
from cache import get_redis_db
from database import close_mongo_connection, connect_to_mongo
from httpx import ASGITransport, AsyncClient
from main import app
from models import Link

# Use a test database name
TEST_MONGO_DB = "test_links_db"
TEST_REDIS_DB = 1


# Override environment variables for testing
@pytest.fixture(autouse=True)
def set_test_env_vars():
    # 儲存原始環境變數
    original_mongo_db = os.environ.get("MONGO_DB")
    original_redis_db = os.environ.get("REDIS_DB")
    original_rabbitmq_host = os.environ.get("RABBITMQ_HOST")
    original_django_frontend_url = os.environ.get("DJANGO_FRONTEND_URL")

    # 設定測試環境變數
    os.environ["MONGO_DB"] = TEST_MONGO_DB
    os.environ["REDIS_DB"] = str(TEST_REDIS_DB)
    os.environ["RABBITMQ_HOST"] = "mock_rabbitmq_host"  # 模擬 RabbitMQ 主機
    os.environ["DJANGO_FRONTEND_URL"] = "http://test-django.com"  # 模擬 Django 前端 URL

    yield  # 執行測試

    # 還原原始環境變數
    if original_mongo_db is None:
        if "MONGO_DB" in os.environ:
            del os.environ["MONGO_DB"]
    else:
        os.environ["MONGO_DB"] = original_mongo_db
    if original_redis_db is None:
        if "REDIS_DB" in os.environ:
            del os.environ["REDIS_DB"]
    else:
        os.environ["REDIS_DB"] = original_redis_db
    if original_rabbitmq_host is None:
        if "RABBITMQ_HOST" in os.environ:
            del os.environ["RABBITMQ_HOST"]
    else:
        os.environ["RABBITMQ_HOST"] = original_rabbitmq_host
    if original_django_frontend_url is None:
        if "DJANGO_FRONTEND_URL" in os.environ:
            del os.environ["DJANGO_FRONTEND_URL"]
    else:
        os.environ["DJANGO_FRONTEND_URL"] = original_django_frontend_url


# Fixture for MongoDB test client (function scope to ensure clean state per test)
@pytest_asyncio.fixture(scope="function")  # 使用 pytest_asyncio.fixture
async def mongo_test_client():
    # 連接到測試 MongoDB 實例
    client, db = await connect_to_mongo()
    yield db  # 將資料庫物件提供給測試
    # 測試結束後清理測試資料庫
    await client.drop_database(TEST_MONGO_DB)
    await close_mongo_connection(client)


# Fixture for Redis test client (function scope to ensure clean state per test)
@pytest.fixture(scope="function")  # 這是同步 fixture
def redis_test_client():
    # 直接建立 Redis 客戶端實例，確保 decode_responses=True
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=TEST_REDIS_DB, decode_responses=True
    )

    client.flushdb()  # 在每個測試前清空測試資料庫
    yield client  # 提供 Redis 客戶端
    client.flushdb()  # 在每個測試後清空測試資料庫
    client.close()


# Override the get_redis_db dependency (autouse to apply to all tests)
@pytest_asyncio.fixture(
    scope="function", autouse=True
)  # 使用 pytest_asyncio.fixture 並自動應用
async def override_get_redis_db_fixture(redis_test_client):  # 依賴 redis_test_client
    # 這個非同步生成器將是實際的依賴覆寫
    async def _override_get_redis_db_callable():
        yield redis_test_client  # 這裡 yield 的是實際的 Redis 客戶端實例

    app.dependency_overrides[get_redis_db] = _override_get_redis_db_callable
    yield  # 執行測試
    app.dependency_overrides.clear()  # 測試結束後清除覆寫


# Fixture for FastAPI test client
@pytest_asyncio.fixture(scope="function")  # 使用 pytest_asyncio.fixture
async def client():
    # 確保 lifespan 在應用程式啟動/關閉時被呼叫
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# Mock the publish_click_event to prevent actual RabbitMQ calls during tests
@pytest.fixture(autouse=True)
def mock_publish_click_event():
    # 模擬 main.py 中使用的 publish_click_event 函式
    with patch("main.publish_click_event") as mock_func:
        yield mock_func


# Helper to create a link with hash
async def create_test_link(
    original_url: str, slug: str, is_active: bool = True, password: str = None
):
    original_url_hash = hashlib.sha256(original_url.encode()).hexdigest()
    link = Link(
        original_url=original_url,
        original_url_hash=original_url_hash,
        slug=slug,
        is_active=is_active,
        password=password,
    )
    await link.insert()
    return link


# --- Test Cases ---


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "Redirect Service is running!",
    }


@pytest.mark.asyncio
async def test_redirect_link_not_found(
    client: AsyncClient, mongo_test_client, redis_test_client
):
    response = await client.get("/r/nonexistent")
    assert response.status_code == 404
    assert response.json()["detail"] == "Short link not found."
    assert redis_test_client.get("link_data:nonexistent") == "NULL"


@pytest.mark.asyncio
async def test_redirect_link_inactive(
    client: AsyncClient, mongo_test_client, redis_test_client
):
    await create_test_link(
        original_url="http://inactive.com", slug="inactive", is_active=False
    )
    response = await client.get("/r/inactive")
    assert response.status_code == 403
    assert response.json()["detail"] == "Short link is inactive."
    cached_data = redis_test_client.hgetall("link_data:inactive")
    assert cached_data.get("is_active") == "False"  # 修正為使用 .get()


@pytest.mark.asyncio
async def test_redirect_link_success_db_hit(
    client: AsyncClient, mongo_test_client, redis_test_client, mock_publish_click_event
):
    redis_test_client.flushdb()
    await create_test_link(
        original_url="http://active.com", slug="active", is_active=True
    )
    response = await client.get("/r/active", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "http://active.com"
    cached_data = redis_test_client.hgetall("link_data:active")
    assert cached_data.get("original_url") == "http://active.com"  # 修正為使用 .get()
    assert cached_data.get("is_active") == "True"
    mock_publish_click_event.assert_called_once_with("active")


@pytest.mark.asyncio
async def test_redirect_link_success_cache_hit(
    client: AsyncClient, mongo_test_client, redis_test_client, mock_publish_click_event
):
    redis_test_client.hmset(
        "link_data:cached",
        {
            "original_url": "http://cached.com",
            "is_active": "True",  # 確保是字串 "True"
            "password": "",
        },
    )
    redis_test_client.expire("link_data:cached", 3600 * 24 * 7)
    response = await client.get("/r/cached", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "http://cached.com"
    mock_publish_click_event.assert_called_once_with("cached")


@pytest.mark.asyncio
async def test_redirect_password_protected_link_db_hit(
    client: AsyncClient, mongo_test_client, redis_test_client
):
    await create_test_link(
        original_url="http://protected.com",
        slug="protected",
        password="hashed_password",
        is_active=True,
    )
    response = await client.get("/r/protected", follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["detail"] == "Password required or incorrect password."
    cached_data = redis_test_client.hgetall("link_data:protected")
    assert cached_data.get("original_url") == "http://protected.com"
    assert cached_data.get("is_active") == "True"
    assert cached_data.get("password") == "hashed_password"


@pytest.mark.asyncio
async def test_redirect_password_protected_link_cache_hit(
    client: AsyncClient, mongo_test_client, redis_test_client
):
    redis_test_client.hmset(
        "link_data:cached_protected",
        {
            "original_url": "http://cached-protected.com",
            "is_active": "True",  # 確保是字串 "True"
            "password": "another_hashed_password",
        },
    )
    redis_test_client.expire("link_data:cached_protected", 3600 * 24 * 7)
    response = await client.get("/r/cached_protected", follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["detail"] == "Password required or incorrect password."


@pytest.mark.asyncio
async def test_redirect_password_protected_link_with_correct_password_db_hit(
    client: AsyncClient, mongo_test_client, redis_test_client, mock_publish_click_event
):
    # 使用 main.py 中的 pwd_context 來雜湊密碼
    from main import pwd_context

    test_password = "correct_password"
    hashed_test_password = pwd_context.hash(test_password)

    await create_test_link(
        original_url="http://protected-correct.com",
        slug="protected-correct",
        password=hashed_test_password,
        is_active=True,
    )
    response = await client.get(
        "/r/protected-correct",
        params={"password": test_password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://protected-correct.com"
    mock_publish_click_event.assert_called_once_with("protected-correct")


@pytest.mark.asyncio
async def test_redirect_password_protected_link_with_correct_password_cache_hit(
    client: AsyncClient, mongo_test_client, redis_test_client, mock_publish_click_event
):
    # 使用 main.py 中的 pwd_context 來雜湊密碼
    from main import pwd_context

    test_password = "another_correct_password"
    hashed_test_password = pwd_context.hash(test_password)

    redis_test_client.hmset(
        "link_data:cached_protected_correct",
        {
            "original_url": "http://cached-protected-correct.com",
            "is_active": "True",
            "password": hashed_test_password,
        },
    )
    redis_test_client.expire("link_data:cached_protected_correct", 3600 * 24 * 7)
    response = await client.get(
        "/r/cached_protected_correct",
        params={"password": test_password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://cached-protected-correct.com"
    mock_publish_click_event.assert_called_once_with("cached_protected_correct")
