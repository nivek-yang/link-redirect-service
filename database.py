# redirect-service/database.py
import os

from beanie import init_beanie
from models import Link
from motor.motor_asyncio import AsyncIOMotorClient


async def connect_to_mongo():
    MONGO_HOST = os.environ.get("MONGO_HOST", "localhost")
    MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))
    MONGO_DB = os.environ.get("MONGO_DB", "links_db")

    client = AsyncIOMotorClient(f"mongodb://{MONGO_HOST}:{MONGO_PORT}")
    database = client[MONGO_DB]

    try:
        await database.command("ping")
        print(f"Connected to MongoDB: {MONGO_DB} on {MONGO_HOST}:{MONGO_PORT}")
        await init_beanie(database=database, document_models=[Link])
        print("Beanie ODM initialized.")
        return client, database
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
        raise


async def close_mongo_connection(client: AsyncIOMotorClient):
    client.close()
    print("Disconnected from MongoDB.")
