import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_and_chat import _can_request_username_change, _create_username_change_request

pytest_plugins = ("pytest_asyncio",)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, query=None, projection=None):
        if query is None:
            return None
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("Res", (), {"inserted_id": len(self.docs) - 1})()

    async def update_one(self, query, update):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$unset" in update:
                    for key in update["$unset"]:
                        doc.pop(key, None)
                return type("Res", (), {"matched_count": 1})()
        return type("Res", (), {"matched_count": 0})()

    async def find(self, query=None):
        class Cursor:
            def __init__(self, docs):
                self.docs = docs

            def sort(self, *args, **kwargs):
                return self

            async def to_list(self, limit=None):
                return list(self.docs)

        return Cursor([d for d in self.docs if query is None or all(d.get(k) == v for k, v in query.items())])


class FakeDB:
    def __init__(self):
        self.users = FakeCollection()
        self.username_change_requests = FakeCollection()


@pytest.mark.asyncio
async def test_username_change_request_is_blocked_within_one_month():
    db = FakeDB()
    user = {"id": "u1", "username": "Alice", "username_lower": "alice"}
    await db.users.insert_one(user)
    await db.username_change_requests.insert_one({
        "user_id": "u1",
        "status": "approved",
        "requested_username": "Alice2",
        "requested_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
    })

    ok, msg = await _can_request_username_change(user, db)
    assert ok is False
    assert "month" in msg.lower()


@pytest.mark.asyncio
async def test_username_change_request_is_created_when_allowed():
    db = FakeDB()
    user = {"id": "u1", "username": "Alice", "username_lower": "alice"}
    await db.users.insert_one(user)

    doc = await _create_username_change_request(db, user, "Alice2")

    assert doc["status"] == "pending"
    assert doc["requested_username"] == "Alice2"
    assert doc["user_id"] == "u1"
