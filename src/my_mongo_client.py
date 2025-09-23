import os
from pymongo import MongoClient
from contextlib import contextmanager

@contextmanager
def MyMongoClient():
    mongo_client = MongoClient(
        host="mongodb://localhost:27017/",
        port=27017,
        username=os.getenv("MONGO_INITDB_ROOT_USERNAME"),
        password=os.getenv("MONGO_INITDB_ROOT_PASSWORD"),
        authSource="admin",
    )
    yield mongo_client
    mongo_client.close()


if __name__ == "__main__":
    with MyMongoClient() as client:
        print(client)  #] Just to verify the connection is established
        db = client["news_hub"]
        collection = db["topics"]
        print(collection.find_one())  # Just to verify we can access