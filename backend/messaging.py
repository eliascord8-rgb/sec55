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
    """PRIVACY: only reveal users if the caller enters an EXACT username match.
    Partial / random typing returns an empty list so nobody can enumerate users.
    Case-insensitive so users can DM owner/staff regardless of capitalization."""
    if not q or len(q.strip()) < 3:
        return {"users": []}
    q_norm = q.strip()
    db = request.app.state.db
    # Case-insensitive EXACT match on username (anchored regex so no partial matches)
    import re
    pattern = f"^{re.escape(q_norm)}$"
    u = await db.users.find_one(
        {"username": {"$regex": pattern, "$options": "i"}, "id": {"$ne": user.id}},
        {"_id": 0, "id": 1, "username": 1, "role": 1, "last_seen": 1},
    )
    # Filter out users who blocked me
    if u:
        blocked = await db.user_blocks.find_one({"user_id": u["id"], "blocked_id": user.id})
        if blocked:
            return {"users": []}
    return {"users": [u] if u else []}


@msg_router.get("/user/{username}")
async def get_user_by_username(username: str, request: Request, user: CurrentUser = Depends(current_user_dep)):
    """Look up a single user by exact username (case-insensitive so owner/staff are reachable).
    Also exposes last_seen and role.
    Returns 404 if user has blocked the caller."""
    db = request.app.state.db
    uname = username.strip()
    import re
    pattern = f"^{re.escape(uname)}$"
    u = await db.users.find_one(
        {"username": {"$regex": pattern, "$options": "i"}},
        {"_id": 0, "id": 1, "username": 1, "role": 1, "last_seen": 1},
    )
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u["id"] == user.id:
        raise HTTPException(status_code=400, detail="Can't message yourself")
    # If the other user blocked me, pretend they don't exist
    blocked = await db.user_blocks.find_one({"user_id": u["id"], "blocked_id": user.id})
    if blocked:
        raise HTTPException(status_code=404, detail="User not found")
    # Have I blocked them?
    i_blocked = await db.user_blocks.find_one({"user_id": user.id, "blocked_id": u["id"]})
    u["i_blocked"] = bool(i_blocked)
    return u


class BlockRequest(BaseModel):
    user_id: str


@msg_router.post("/block")
async def block_user(payload: BlockRequest, request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    if payload.user_id == user.id:
        raise HTTPException(status_code=400, detail="Can't block yourself")
    await db.user_blocks.update_one(
        {"user_id": user.id, "blocked_id": payload.user_id},
        {"$set": {"user_id": user.id, "blocked_id": payload.user_id, "created_at": _now()}},
        upsert=True,
    )
    return {"blocked": True}


@msg_router.post("/unblock")
async def unblock_user(payload: BlockRequest, request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    await db.user_blocks.delete_one({"user_id": user.id, "blocked_id": payload.user_id})
    return {"unblocked": True}


@msg_router.get("/blocks")
async def list_blocks(request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    cursor = db.user_blocks.find({"user_id": user.id}, {"_id": 0, "blocked_id": 1})
    ids = [r["blocked_id"] async for r in cursor]
    return {"blocked_ids": ids}


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
    text: Optional[str] = ""
    # attachment metadata (populated by /messages/upload)
    attachment_url: Optional[str] = None
    attachment_kind: Optional[str] = None  # "voice" | "image" | "file"
    attachment_name: Optional[str] = None
    attachment_size: Optional[int] = None


@msg_router.post("/send")
async def send_message(payload: SendMessage, request: Request, user: CurrentUser = Depends(current_user_dep)):
    db = request.app.state.db
    if payload.to_id == user.id:
        raise HTTPException(status_code=400, detail="Can't message yourself")
    other = await db.users.find_one({"id": payload.to_id}, {"_id": 0, "id": 1, "username": 1})
    if not other:
        raise HTTPException(status_code=404, detail="Recipient not found")
    # Blocked either direction?
    if await db.user_blocks.find_one({"user_id": payload.to_id, "blocked_id": user.id}):
        raise HTTPException(status_code=403, detail="This user isn't accepting messages from you.")
    if await db.user_blocks.find_one({"user_id": user.id, "blocked_id": payload.to_id}):
        raise HTTPException(status_code=403, detail="You've blocked this user — unblock them first.")
    if not (payload.text or "").strip() and not payload.attachment_url:
        raise HTTPException(status_code=400, detail="Empty message")
    doc = {
        "id": str(uuid.uuid4()),
        "thread_key": _pair_key(user.id, payload.to_id),
        "from_id": user.id,
        "from_username": user.username,
        "to_id": payload.to_id,
        "to_username": other["username"],
        "text": (payload.text or "").strip()[:4000],
        "attachment_url": payload.attachment_url,
        "attachment_kind": payload.attachment_kind,
        "attachment_name": payload.attachment_name,
        "attachment_size": payload.attachment_size,
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


# ============ File / voice attachment upload ============
import os as _os
from fastapi import UploadFile, File, Form

UPLOAD_DIR = _os.environ.get("UPLOAD_DIR", "/app/backend/uploads")
_os.makedirs(UPLOAD_DIR, exist_ok=True)


@msg_router.post("/upload")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("file"),
    user: CurrentUser = Depends(current_user_dep),
):
    """Upload a voice-note, image, or generic file. Returns URL + metadata to attach to a message."""
    if kind not in ("voice", "image", "file"):
        kind = "file"
    # Read + size-limit (20MB)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    ext = _os.path.splitext(file.filename or "")[1][:8].lower() or (".webm" if kind == "voice" else ".bin")
    fname = f"{uuid.uuid4().hex}{ext}"
    fpath = _os.path.join(UPLOAD_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(data)
    url = f"/api/messages/file/{fname}"
    return {
        "url": url,
        "kind": kind,
        "name": (file.filename or fname)[:120],
        "size": len(data),
        "content_type": file.content_type,
    }


@msg_router.get("/file/{fname}")
async def get_attachment(fname: str):
    """Serve an uploaded file."""
    from fastapi.responses import FileResponse
    # Sanitize filename — no path traversal
    safe = _os.path.basename(fname)
    fpath = _os.path.join(UPLOAD_DIR, safe)
    if not _os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fpath)
