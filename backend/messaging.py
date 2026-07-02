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
import subprocess as _sp
from fastapi import UploadFile, File, Form

UPLOAD_DIR = _os.environ.get("UPLOAD_DIR", "/app/backend/uploads")
_os.makedirs(UPLOAD_DIR, exist_ok=True)


def _transcode_to_mp3(src_path: str) -> Optional[str]:
    """Transcode any audio file to mp3 (universally playable on iOS/Android/Safari/Chrome/Firefox).
    Returns the new .mp3 path on success, None if ffmpeg fails or is missing."""
    out_path = _os.path.splitext(src_path)[0] + ".mp3"
    try:
        _sp.run(
            ["ffmpeg", "-y", "-i", src_path, "-vn", "-acodec", "libmp3lame", "-b:a", "64k", out_path],
            check=True, capture_output=True, timeout=30,
        )
        return out_path if _os.path.exists(out_path) else None
    except Exception:
        return None


@msg_router.post("/upload")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("file"),
    user: CurrentUser = Depends(current_user_dep),
):
    """Upload a voice-note, image, or generic file. Returns URL + metadata to attach to a message.
    Voice notes are transcoded to mp3 so iOS Safari and Android Chrome can both play them."""
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
    # Cross-platform voice notes: transcode to mp3 (iOS Safari can't play webm/opus)
    if kind == "voice":
        mp3_path = _transcode_to_mp3(fpath)
        if mp3_path:
            try:
                _os.remove(fpath)
            except Exception:
                pass
            fname = _os.path.basename(mp3_path)
    url = f"/api/messages/file/{fname}"
    return {
        "url": url,
        "kind": kind,
        "name": (file.filename or fname)[:120],
        "size": _os.path.getsize(_os.path.join(UPLOAD_DIR, fname)),
        "content_type": "audio/mpeg" if fname.endswith(".mp3") else file.content_type,
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
    # Content-type hint for the browser
    ct = None
    if safe.endswith(".mp3"):
        ct = "audio/mpeg"
    elif safe.endswith(".webm"):
        ct = "audio/webm"
    elif safe.endswith(".m4a") or safe.endswith(".mp4"):
        ct = "audio/mp4"
    return FileResponse(fpath, media_type=ct)


# ============ Typing indicator ============

class TypingSignal(BaseModel):
    to_id: str
    typing: bool = True


@msg_router.post("/typing")
async def set_typing(payload: TypingSignal, request: Request, user: CurrentUser = Depends(current_user_dep)):
    """Called every ~2s while the user is typing. TTL of 5s in the DB."""
    db = request.app.state.db
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=5 if payload.typing else 0)
    key = _pair_key(user.id, payload.to_id)
    await db.typing_state.update_one(
        {"thread_key": key, "from_id": user.id, "to_id": payload.to_id},
        {"$set": {
            "thread_key": key,
            "from_id": user.id,
            "to_id": payload.to_id,
            "expires_at": expires_at.isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True}


@msg_router.get("/typing/{other_id}")
async def get_typing(other_id: str, request: Request, user: CurrentUser = Depends(current_user_dep)):
    """Is `other_id` currently typing to me?"""
    db = request.app.state.db
    doc = await db.typing_state.find_one(
        {"from_id": other_id, "to_id": user.id},
        {"_id": 0, "expires_at": 1},
    )
    if not doc:
        return {"typing": False}
    try:
        exp = datetime.fromisoformat(doc["expires_at"])
    except Exception:
        return {"typing": False}
    return {"typing": exp > datetime.now(timezone.utc)}


# ============ Report chat ============

class ReportRequest(BaseModel):
    reported_user_id: str
    reason: Optional[str] = ""


@msg_router.post("/report")
async def report_chat(payload: ReportRequest, request: Request, user: CurrentUser = Depends(current_user_dep)):
    """User reports another user's chat. Admin can then inspect that specific thread."""
    db = request.app.state.db
    if payload.reported_user_id == user.id:
        raise HTTPException(status_code=400, detail="Can't report yourself")
    other = await db.users.find_one({"id": payload.reported_user_id}, {"_id": 0, "id": 1, "username": 1})
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    key = _pair_key(user.id, payload.reported_user_id)
    doc = {
        "id": str(uuid.uuid4()),
        "reporter_id": user.id,
        "reporter_username": user.username,
        "reported_id": payload.reported_user_id,
        "reported_username": other["username"],
        "thread_key": key,
        "reason": (payload.reason or "").strip()[:1000],
        "status": "open",
        "created_at": _now(),
    }
    await db.chat_reports.insert_one(doc.copy())
    return {"ok": True, "id": doc["id"]}


# ============ Admin endpoints (reports + call config) ============

async def _admin_dep(request: Request) -> CurrentUser:
    """Admin auth for /admin/messages/* and /admin/calls/*.
    Accepts EITHER the panel's X-Admin-Token (owner/staff session) OR a JWT for role owner/admin/staff.
    This bridges the two auth systems used across the app (JWT for users, ADMIN_SESSIONS for the admin UI)."""
    # 1) Admin panel session header (used by /app/frontend/src/lib/api.js -> adminApi)
    x_admin = request.headers.get("X-Admin-Token") or request.headers.get("x-admin-token")
    if x_admin:
        ADMIN_SESSIONS: set = set()
        STAFF_SESSIONS: dict = {}
        owner_name = "owner"
        try:
            import server as _srv  # local import avoids cycles
            ADMIN_SESSIONS = getattr(_srv, "ADMIN_SESSIONS", set())
            STAFF_SESSIONS = getattr(_srv, "STAFF_SESSIONS", {})
            owner_name = getattr(_srv, "ADMIN_USER", None) or getattr(_srv, "OWNER_USERNAME", "owner")
        except Exception:
            pass
        if x_admin in ADMIN_SESSIONS:
            return CurrentUser(id="__owner__", username=owner_name, role="owner")
        staff = STAFF_SESSIONS.get(x_admin)
        if staff:
            return CurrentUser(id=staff.get("id", "__staff__"), username=staff.get("username", "staff"), role="staff")
    # 2) JWT fallback (Authorization: Bearer <jwt> OR access_token cookie)
    try:
        user = await current_user_dep(request)
        if user.role in ("owner", "admin", "staff", "moderator"):
            return user
    except HTTPException:
        pass
    raise HTTPException(status_code=401, detail="Admin auth required")


admin_msg_router = APIRouter(prefix="/admin/messages")


@admin_msg_router.get("/reports")
async def admin_list_reports(request: Request, admin: CurrentUser = Depends(_admin_dep)):
    db = request.app.state.db
    cursor = db.chat_reports.find({}, {"_id": 0}).sort("created_at", -1).limit(200)
    reports = await cursor.to_list(200)
    return {"reports": reports}


@admin_msg_router.get("/reports/{report_id}/thread")
async def admin_view_reported_thread(report_id: str, request: Request, admin: CurrentUser = Depends(_admin_dep)):
    """Admin can only read chats that have been reported."""
    db = request.app.state.db
    report = await db.chat_reports.find_one({"id": report_id}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    cursor = db.direct_messages.find(
        {"thread_key": report["thread_key"]},
        {"_id": 0},
    ).sort("created_at", 1).limit(2000)
    msgs = await cursor.to_list(2000)
    return {"report": report, "messages": msgs}


class ReportStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(open|reviewed|closed)$")


@admin_msg_router.post("/reports/{report_id}/status")
async def admin_update_report_status(report_id: str, payload: ReportStatusUpdate, request: Request, admin: CurrentUser = Depends(_admin_dep)):
    db = request.app.state.db
    r = await db.chat_reports.update_one(
        {"id": report_id},
        {"$set": {"status": payload.status, "reviewed_at": _now(), "reviewed_by": admin.username}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"ok": True}


# ============ TURN / ICE config (admin-configurable) ============

class TurnConfig(BaseModel):
    urls: str  # comma-separated
    username: Optional[str] = ""
    credential: Optional[str] = ""


@calls_router.get("/ice-config")
async def get_ice_config(request: Request, user: CurrentUser = Depends(current_user_dep)):
    """Return ICE servers (STUN + TURN) for the client. Falls back to public defaults if the admin
    hasn't configured a private TURN server."""
    db = request.app.state.db
    cfg = await db.turn_config.find_one({"_id": "singleton"}, {"_id": 0})
    servers = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]
    if cfg and cfg.get("urls"):
        for u in [x.strip() for x in cfg["urls"].split(",") if x.strip()]:
            servers.append({
                "urls": u,
                **({"username": cfg["username"]} if cfg.get("username") else {}),
                **({"credential": cfg["credential"]} if cfg.get("credential") else {}),
            })
    else:
        # Public fallback (OpenRelay)
        servers += [
            {"urls": "turn:openrelay.metered.ca:80", "username": "openrelayproject", "credential": "openrelayproject"},
            {"urls": "turn:openrelay.metered.ca:443", "username": "openrelayproject", "credential": "openrelayproject"},
            {"urls": "turn:openrelay.metered.ca:443?transport=tcp", "username": "openrelayproject", "credential": "openrelayproject"},
        ]
    return {"iceServers": servers}


admin_calls_router = APIRouter(prefix="/admin/calls")


@admin_calls_router.get("/turn-config")
async def admin_get_turn(request: Request, admin: CurrentUser = Depends(_admin_dep)):
    db = request.app.state.db
    cfg = await db.turn_config.find_one({"_id": "singleton"}, {"_id": 0})
    return cfg or {"urls": "", "username": "", "credential": ""}


@admin_calls_router.post("/turn-config")
async def admin_set_turn(payload: TurnConfig, request: Request, admin: CurrentUser = Depends(_admin_dep)):
    db = request.app.state.db
    await db.turn_config.update_one(
        {"_id": "singleton"},
        {"$set": {"urls": payload.urls, "username": payload.username or "", "credential": payload.credential or ""}},
        upsert=True,
    )
    return {"ok": True}

