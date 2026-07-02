"""User-to-user direct messaging and WebRTC signaling for voice/video calls.
Uses polling (no websockets) — simple + reliable behind proxies.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_and_chat import current_user_dep, CurrentUser


msg_router = APIRouter(prefix="/messages")
calls_router = APIRouter(prefix="/calls")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pair_key(a: str, b: str) -> str:
    """Deterministic thread key for a pair of user ids."""
    return "::".join(sorted([a, b]))


# ============ Search users ============

@msg_router.get("/search")
async def search_users(q: str, request: Request, user: CurrentUser = Depends(current_user_dep)):
    if not q or len(q.strip()) < 1:
        return {"users": []}
    q_norm = q.strip().lower()
    db = request.app.state.db
    import re
    cursor = db.users.find(
        {
            "username": {"$regex": f"^{re.escape(q_norm)}", "$options": "i"},
            "id": {"$ne": user.id},
        },
        {"_id": 0, "id": 1, "username": 1, "role": 1},
    ).limit(20)
    return {"users": await cursor.to_list(20)}


@msg_router.get("/user/{username}")
async def get_user_by_username(username: str, request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    uname = username.strip().lower()
    u = await db.users.find_one(
        {"username": uname},
        {"_id": 0, "id": 1, "username": 1, "role": 1},
    )
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u["id"] == user.id:
        raise HTTPException(status_code=400, detail="Can't message yourself")
    return u


# ============ Threads ============

@msg_router.get("/threads")
async def list_threads(request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    pipeline = [
        {"$match": {"$or": [{"from_id": user.id}, {"to_id": user.id}]}},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$thread_key",
            "last": {"$first": "$$ROOT"},
            "unread_count": {
                "$sum": {"$cond": [
                    {"$and": [{"$eq": ["$to_id", user.id]}, {"$eq": ["$read", False]}]},
                    1, 0
                ]}
            },
        }},
        {"$sort": {"last.created_at": -1}},
        {"$limit": 100},
    ]
    threads = []
    async for row in db.direct_messages.aggregate(pipeline):
        last = row["last"]
        other_id = last["to_id"] if last["from_id"] == user.id else last["from_id"]
        other_name = last["to_username"] if last["from_id"] == user.id else last["from_username"]
        threads.append({
            "other_id": other_id,
            "other_username": other_name,
            "last_text": last.get("text", "")[:200],
            "last_at": last.get("created_at"),
            "last_from_me": last["from_id"] == user.id,
            "unread": row["unread_count"],
        })
    return {"threads": threads}


@msg_router.get("/thread/{other_id}")
async def get_thread(other_id: str, request: Request, user: CurrentUser = Depends(current_user_dep), since: Optional[str] = None):
    db = request.app.state.db
    key = _pair_key(user.id, other_id)
    q: dict = {"thread_key": key}
    if since:
        q["created_at"] = {"$gt": since}
    cursor = db.direct_messages.find(q, {"_id": 0}).sort("created_at", 1).limit(500)
    msgs = await cursor.to_list(500)
    await db.direct_messages.update_many(
        {"thread_key": key, "to_id": user.id, "read": False},
        {"$set": {"read": True, "read_at": _now()}},
    )
    return {"messages": msgs}


class SendMessage(BaseModel):
    to_id: str
    text: str = Field(..., min_length=1, max_length=4000)


@msg_router.post("/send")
async def send_message(payload: SendMessage, request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    if payload.to_id == user.id:
        raise HTTPException(status_code=400, detail="Can't message yourself")
    other = await db.users.find_one({"id": payload.to_id}, {"_id": 0, "id": 1, "username": 1})
    if not other:
        raise HTTPException(status_code=404, detail="Recipient not found")
    doc = {
        "id": str(uuid.uuid4()),
        "thread_key": _pair_key(user.id, payload.to_id),
        "from_id": user.id,
        "from_username": user.username,
        "to_id": payload.to_id,
        "to_username": other["username"],
        "text": payload.text.strip()[:4000],
        "created_at": _now(),
        "read": False,
    }
    await db.direct_messages.insert_one(doc.copy())
    return doc


@msg_router.get("/unread-count")
async def unread_count(request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    n = await db.direct_messages.count_documents({"to_id": user.id, "read": False})
    return {"unread": n}


# ============ WebRTC call signaling ============

class CallSignal(BaseModel):
    call_id: str
    to_id: str
    kind: str = Field(..., pattern=r"^(offer|answer|ice|end|ring)$")
    payload: Optional[dict] = None


@calls_router.post("/signal")
async def send_signal(payload: CallSignal, request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    doc = {
        "id": str(uuid.uuid4()),
        "call_id": payload.call_id,
        "from_id": user.id,
        "from_username": user.username,
        "to_id": payload.to_id,
        "kind": payload.kind,
        "payload": payload.payload or {},
        "created_at": _now(),
        "consumed": False,
    }
    await db.call_signals.insert_one(doc.copy())
    return {"ok": True}


@calls_router.get("/poll")
async def poll_signals(request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    cursor = db.call_signals.find(
        {"to_id": user.id, "consumed": False},
        {"_id": 0},
    ).sort("created_at", 1).limit(50)
    signals = await cursor.to_list(50)
    if signals:
        ids = [s["id"] for s in signals]
        await db.call_signals.update_many(
            {"id": {"$in": ids}},
            {"$set": {"consumed": True, "consumed_at": _now()}},
        )
    return {"signals": signals}
