"""Auth, chat, AI buy routes for Better Social."""
import os
import re
import uuid
import bcrypt
import jwt
import httpx
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
ACCESS_TTL = timedelta(days=7)

auth_router = APIRouter(prefix="/api/auth")
chat_router = APIRouter(prefix="/api/chat")
client_router = APIRouter(prefix="/api/client")
ai_router = APIRouter(prefix="/api/ai")

# ================= MODELS =================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=24, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    captcha_token: Optional[str] = None


class LoginRequest(BaseModel):
    identifier: str  # username OR email
    password: str


class ChatSendRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


class AIMessage(BaseModel):
    role: str
    text: str


class AIChatRequest(BaseModel):
    messages: List[AIMessage]
    session_id: Optional[str] = None


# ================= HELPERS =================

def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + ACCESS_TTL,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _get_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("access_token")


async def verify_hcaptcha(token: Optional[str]) -> bool:
    if not token:
        return False
    secret = os.environ.get("HCAPTCHA_SECRET", "")
    # Test secret always passes
    if secret.startswith("0x0000000000000000000000000000000000000000"):
        return True
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(
            "https://api.hcaptcha.com/siteverify",
            data={"response": token, "secret": secret},
        )
        data = r.json()
        return bool(data.get("success"))


def half_username(u: str) -> str:
    if not u:
        return ""
    half = max(1, len(u) // 2)
    return u[:half] + "•" * (len(u) - half)


def _user_public(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "username": doc["username"],
        "email": doc["email"],
        "role": doc.get("role", "user"),
        "created_at": doc.get("created_at"),
    }


# ================= DEPENDENCY =================

class CurrentUser(BaseModel):
    id: str
    username: str
    role: str


async def current_user_dep(request: Request) -> CurrentUser:
    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    db: AsyncIOMotorDatabase = request.app.state.db
    doc = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not doc:
        raise HTTPException(status_code=401, detail="User not found")
    # Heartbeat: mark online
    await db.users.update_one(
        {"id": doc["id"]},
        {"$set": {"last_seen": datetime.now(timezone.utc).isoformat()}},
    )
    return CurrentUser(id=doc["id"], username=doc["username"], role=doc.get("role", "user"))


def require_staff(user: CurrentUser = Depends(current_user_dep)) -> CurrentUser:
    if user.role not in ("owner", "moderator"):
        raise HTTPException(status_code=403, detail="Staff only")
    return user


# ================= STARTUP =================

async def seed_owner(db: AsyncIOMotorDatabase):
    await db.users.create_index("username", unique=True)
    await db.users.create_index("email", unique=True)
    await db.chat_messages.create_index([("created_at", -1)])
    username = os.environ.get("OWNER_USERNAME", "Balkin")
    email = os.environ.get("OWNER_EMAIL", "eliascord8@gmail.com")
    password = os.environ.get("OWNER_PASSWORD", "Dennis123.@@")
    existing = await db.users.find_one({"username": username})
    if existing is None:
        doc = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email.lower(),
            "password_hash": hash_password(password),
            "role": "owner",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "muted_until": None,
        }
        await db.users.insert_one(doc.copy())
        logger.info(f"Owner seeded: {username}")
    elif not verify_password(password, existing.get("password_hash", "")):
        await db.users.update_one(
            {"username": username},
            {"$set": {"password_hash": hash_password(password), "role": "owner", "email": email.lower()}},
        )
        logger.info(f"Owner password/role synced: {username}")


# ================= AUTH ROUTES =================

@auth_router.post("/register")
async def register(req: RegisterRequest, request: Request):
    db: AsyncIOMotorDatabase = request.app.state.db

    # hCaptcha (test keys always pass)
    if not await verify_hcaptcha(req.captcha_token):
        raise HTTPException(status_code=400, detail="Captcha failed")

    email = req.email.lower()
    if await db.users.find_one({"username": req.username}):
        raise HTTPException(status_code=400, detail="Username already taken")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "username": req.username,
        "email": email,
        "password_hash": hash_password(req.password),
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "muted_until": None,
    }
    await db.users.insert_one(doc.copy())
    token = create_token(user_id, req.username, "user")
    return {"token": token, "user": _user_public(doc)}


@auth_router.post("/login")
async def login(req: LoginRequest, request: Request):
    db: AsyncIOMotorDatabase = request.app.state.db
    ident = req.identifier.strip()
    query = {"email": ident.lower()} if "@" in ident else {"username": ident}
    doc = await db.users.find_one(query)
    if not doc or not verify_password(req.password, doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(doc["id"], doc["username"], doc.get("role", "user"))
    return {"token": token, "user": _user_public(doc)}


@auth_router.get("/me")
async def me(user: CurrentUser = Depends(current_user_dep), request: Request = None):
    db: AsyncIOMotorDatabase = request.app.state.db
    doc = await db.users.find_one({"id": user.id}, {"_id": 0, "password_hash": 0})
    return {"user": _user_public(doc)}


@auth_router.get("/hcaptcha-site-key")
async def hcaptcha_site_key():
    return {"site_key": os.environ.get("HCAPTCHA_SITEKEY", "")}


# ================= CLIENT DASHBOARD =================

@client_router.get("/dashboard")
async def dashboard(user: CurrentUser = Depends(current_user_dep), request: Request = None):
    db: AsyncIOMotorDatabase = request.app.state.db
    me_doc = await db.users.find_one({"id": user.id}, {"_id": 0, "password_hash": 0})

    # Balance = sum of coupons bound to this user's email/username note OR just 0 (no wallet yet)
    # For simplicity: sum of coupons whose note contains the username
    coupon_balance = 0.0
    async for c in db.coupons.find({"note": {"$regex": f"^@{re.escape(user.username)}$"}}, {"_id": 0, "balance": 1}):
        coupon_balance += float(c.get("balance", 0) or 0)

    # Online users (active in last 2 minutes)
    threshold = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    online = await db.users.count_documents({"last_seen": {"$gte": threshold}})

    total_orders = await db.orders.count_documents({})
    registered = await db.users.count_documents({})

    return {
        "user": _user_public(me_doc),
        "balance": round(coupon_balance, 2),
        "online_users": online,
        "total_orders": total_orders,
        "registered_users": registered,
    }


# ================= CHAT =================

MUTE_RE = re.compile(r"^/mute\s+@?(\w+)\s+(\d+)([mhd])\s*$", re.IGNORECASE)


@chat_router.get("/messages")
async def chat_messages(request: Request, since: Optional[str] = None):
    db: AsyncIOMotorDatabase = request.app.state.db
    query = {}
    if since:
        query["created_at"] = {"$gt": since}
    cursor = db.chat_messages.find(query, {"_id": 0}).sort("created_at", -1).limit(100)
    items = await cursor.to_list(100)
    items.reverse()
    return {"messages": items}


@chat_router.post("/send")
async def chat_send(
    body: ChatSendRequest,
    user: CurrentUser = Depends(current_user_dep),
    request: Request = None,
):
    db: AsyncIOMotorDatabase = request.app.state.db
    me_doc = await db.users.find_one({"id": user.id}, {"_id": 0})
    if not me_doc:
        raise HTTPException(status_code=401, detail="User not found")

    # Check mute
    mu = me_doc.get("muted_until")
    if mu:
        try:
            if datetime.fromisoformat(mu) > datetime.now(timezone.utc):
                raise HTTPException(status_code=403, detail=f"You are muted until {mu}")
        except (ValueError, TypeError):
            pass

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")

    # Staff-only: /mute command
    m = MUTE_RE.match(text)
    if m:
        if user.role not in ("owner", "moderator"):
            raise HTTPException(status_code=403, detail="Only staff can mute")
        target, amount, unit = m.group(1), int(m.group(2)), m.group(3).lower()
        delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
        until = (datetime.now(timezone.utc) + delta).isoformat()
        tgt = await db.users.find_one({"username": target})
        if not tgt:
            raise HTTPException(status_code=404, detail=f"User {target} not found")
        if tgt.get("role") == "owner":
            raise HTTPException(status_code=403, detail="Cannot mute the owner")
        await db.users.update_one({"id": tgt["id"]}, {"$set": {"muted_until": until}})
        # System notice
        sys_msg = {
            "id": str(uuid.uuid4()),
            "user_id": "system",
            "username": "system",
            "username_display": "system",
            "role": "system",
            "text": f"@{target} has been muted for {amount}{unit} by @{user.username}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.chat_messages.insert_one(sys_msg.copy())
        return {"ok": True, "muted": target, "until": until}

    msg = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "username_display": half_username(user.username) if user.role == "user" else user.username,
        "role": user.role,
        "text": text[:500],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_messages.insert_one(msg.copy())
    return {"message": {k: v for k, v in msg.items() if k != "_id"}}


# ================= AI BUY =================

AI_SYSTEM = """You are "Better Social AI", a friendly ordering assistant for a TikTok SMM service.

Your job: help the user place exactly ONE order via structured conversation.

Rules:
1. DETECT the user's language from their first message and respond in THAT language for the whole conversation.
2. Ask for, in order: (a) what service — TikTok Live Likes, Live Views, or Live Comments; (b) the TikTok link / username; (c) quantity; (d) their Better Social coupon code.
3. When you have all 4 pieces of info, output EXACTLY this JSON on a single line and nothing else:
READY_TO_ORDER: {"service_type":"likes|views|comments","link":"...","quantity":123,"coupon_code":"BS-..."}
4. Before READY_TO_ORDER, chat naturally — confirm details, ask one thing at a time.
5. Keep messages short (1-2 sentences). Be warm but efficient.
6. If the user asks anything off-topic, politely redirect them to the order flow.
"""

# Map service types to actual service IDs (configurable in admin later)
SERVICE_TYPE_MAP = {
    "likes": 0,   # admin must set
    "views": 0,
    "comments": 0,
}


async def get_ai_service_map(db) -> dict:
    cfg = await db.ai_service_map.find_one({}, {"_id": 0})
    if not cfg:
        return {"likes": 0, "views": 0, "comments": 0}
    return {
        "likes": int(cfg.get("likes", 0) or 0),
        "views": int(cfg.get("views", 0) or 0),
        "comments": int(cfg.get("comments", 0) or 0),
    }


@ai_router.post("/chat")
async def ai_chat(
    req: AIChatRequest,
    user: CurrentUser = Depends(current_user_dep),
    request: Request = None,
):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="LLM not configured")
    session_id = req.session_id or f"ai-{user.id}-{uuid.uuid4().hex[:8]}"
    chat = LlmChat(api_key=api_key, session_id=session_id, system_message=AI_SYSTEM).with_model(
        "anthropic", "claude-sonnet-4-5-20250929"
    )

    # Replay history so context is preserved on each call
    last_user = None
    for m in req.messages:
        if m.role == "user":
            last_user = m.text
    if not last_user:
        raise HTTPException(status_code=400, detail="No user message")

    # For multi-turn, we re-send full history via repeated send_message calls
    # LlmChat keeps its own state; we simulate by sending only the latest user msg + history context prefix
    # Simpler: build one condensed message
    history_text = ""
    for m in req.messages[:-1]:
        prefix = "USER" if m.role == "user" else "ASSISTANT"
        history_text += f"{prefix}: {m.text}\n"
    prompt = (history_text + f"USER: {last_user}\nASSISTANT:").strip()

    try:
        reply = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        raise HTTPException(status_code=502, detail=f"AI error: {e}")

    reply_text = str(reply).strip()
    return {"reply": reply_text, "session_id": session_id}


class AIConfirmRequest(BaseModel):
    service_type: str  # likes|views|comments
    link: str
    quantity: int
    coupon_code: str


@ai_router.post("/confirm-order")
async def ai_confirm_order(
    body: AIConfirmRequest,
    user: CurrentUser = Depends(current_user_dep),
    request: Request = None,
):
    """Called by frontend after AI emits READY_TO_ORDER. Deducts coupon, places SMM order, logs."""
    db: AsyncIOMotorDatabase = request.app.state.db

    service_map = await get_ai_service_map(db)
    sid = service_map.get(body.service_type.lower())
    if not sid:
        raise HTTPException(
            status_code=400,
            detail=f"Admin has not mapped '{body.service_type}' to a service ID yet. Contact support.",
        )

    # Look up curated service for price
    svc = await db.curated_services.find_one({"service_id": sid, "enabled": True}, {"_id": 0})
    if not svc:
        raise HTTPException(status_code=400, detail="Mapped service is not enabled")
    rate = float(svc.get("custom_rate", 0))
    price = round((rate * body.quantity) / 1000.0, 4)
    if body.quantity < int(svc.get("min", 1)) or body.quantity > int(svc.get("max", 10**9)):
        raise HTTPException(
            status_code=400,
            detail=f"Quantity must be {svc.get('min')}–{svc.get('max')}",
        )

    code = body.coupon_code.strip().upper()
    # Atomic deduct
    deducted = await db.coupons.find_one_and_update(
        {"code": code, "balance": {"$gte": price}},
        {"$inc": {"balance": -price}},
        return_document=False,
    )
    if not deducted:
        exists = await db.coupons.find_one({"code": code})
        if not exists:
            raise HTTPException(status_code=404, detail="Invalid coupon")
        raise HTTPException(status_code=400, detail=f"Insufficient balance (${exists['balance']:.2f})")

    # Place SMM order via app state helper
    place_smm = request.app.state.place_smm_order
    try:
        smm_resp = await place_smm(sid, body.link, body.quantity)
    except Exception as e:
        await db.coupons.update_one({"code": code}, {"$inc": {"balance": price}})
        raise HTTPException(status_code=502, detail=f"SMM error: {e}")
    if "error" in smm_resp:
        await db.coupons.update_one({"code": code}, {"$inc": {"balance": price}})
        raise HTTPException(status_code=400, detail=f"SMM error: {smm_resp['error']}")

    order_id = str(uuid.uuid4())
    order_doc = {
        "id": order_id,
        "service_id": sid,
        "link": body.link,
        "quantity": body.quantity,
        "price_usd": price,
        "payment_method": "coupon",
        "coupon_code": code,
        "customer_email": "",
        "ip": "ai",
        "user_id": user.id,
        "username": user.username,
        "source": "ai",
        "status": "completed",
        "smm_order_id": smm_resp.get("order"),
        "smm_response": smm_resp,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc.copy())

    # Delete coupon if drained
    remaining = await db.coupons.find_one({"code": code}, {"_id": 0, "balance": 1})
    if remaining and remaining.get("balance", 0) <= 0.005:
        await db.coupons.delete_one({"code": code})

    return {
        "status": "completed",
        "order_id": order_id,
        "smm_order_id": smm_resp.get("order"),
        "price": price,
        "service": svc.get("name"),
    }


@ai_router.get("/admin/orders")
async def ai_orders(request: Request):
    db: AsyncIOMotorDatabase = request.app.state.db
    items = await db.orders.find({"source": "ai"}, {"_id": 0, "smm_response": 0}).sort("created_at", -1).to_list(500)
    return {"orders": items}


class AIServiceMapBody(BaseModel):
    likes: int = 0
    views: int = 0
    comments: int = 0


@ai_router.post("/admin/service-map")
async def ai_set_map(body: AIServiceMapBody, request: Request):
    db: AsyncIOMotorDatabase = request.app.state.db
    doc = body.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.ai_service_map.update_one({}, {"$set": doc}, upsert=True)
    return {"ok": True}


@ai_router.get("/admin/service-map")
async def ai_get_map(request: Request):
    db: AsyncIOMotorDatabase = request.app.state.db
    m = await get_ai_service_map(db)
    return m
