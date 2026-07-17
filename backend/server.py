from fastapi import FastAPI, APIRouter, HTTPException, Request, Header, Depends, Body
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import os
import re
import asyncio
import logging
import uuid
import base64
import json as jsonlib
import hmac
import hashlib
import secrets
import string
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

SMM_API_URL_DEFAULT = "https://smmcost.com/api/v2"
SMM_API_KEY_DEFAULT = os.environ.get("SMM_API_KEY", "47b5c3b01e4b5ecd1e53b39baef31a6e")

ADMIN_USER = os.environ.get("ADMIN_USER", "Balkin99")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Armin1234")
ADMIN_URL_SECRET = os.environ.get("ADMIN_URL_SECRET", "")  # set in .env for secret URL login
ADMIN_SESSIONS = set()  # in-mem session tokens (owner)
# Owner display nickname (configurable via /admin/me/nickname)
OWNER_DISPLAY_NAME = ADMIN_USER  # in-mem, persisted in DB
# Staff tokens map: token -> {id, username, display_name, perms}
STAFF_SESSIONS = {}

# Permission scopes a staff role can have
STAFF_PERMS = {"tickets", "ai_inbox", "orders", "discord", "withdrawals"}

app = FastAPI()
api_router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


# Import auth deps so we can build authenticated routes below
from auth_and_chat import (  # noqa: E402
    auth_router,
    chat_router,
    client_router,
    ai_router,
    seed_owner,
    current_user_dep,
    CurrentUser,
)


# ============ MODELS ============
class CheckoutRequest(BaseModel):
    service_id: int
    link: str
    quantity: int
    payment_method: str  # "coupon" | "cryptomus"
    coupon_code: Optional[str] = None
    customer_email: str = Field(..., min_length=3)
    price_usd: float
    comments: Optional[str] = None  # For custom-comments services — newline-separated list


class CouponCreate(BaseModel):
    amount: float
    note: Optional[str] = ""


class CoinPaymentsConfig(BaseModel):
    public_key: str
    private_key: str
    ipn_secret: str
    merchant_id: str


class CryptomusConfig(BaseModel):
    merchant_uuid: str
    payment_api_key: str


class DiscordConfig(BaseModel):
    bot_token: Optional[str] = None
    developer_role_name: str = "Developer"
    shared_secret: str


class SmmConfig(BaseModel):
    api_url: str
    api_key: str


class ServiceUpdate(BaseModel):
    custom_rate: Optional[float] = None
    enabled: Optional[bool] = None
    name: Optional[str] = None
    custom_name: Optional[str] = None
    needs_custom_text: Optional[bool] = None
    provider_id: Optional[str] = None
    description: Optional[str] = None
    delivery_minutes: Optional[int] = None


class ManualServiceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = ""
    category: Optional[str] = "Custom"
    price_usd: float = Field(..., gt=0, le=100000)
    delivery_minutes: Optional[int] = Field(60, ge=0, le=100000)


class AdminLogin(BaseModel):
    username: str
    password: str


class CheckTxRequest(BaseModel):
    order_id: str


# ============ HELPERS ============
def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_admin(token: Optional[str], perm: Optional[str] = None) -> None:
    """Accept owner token OR staff token (if staff has the required perm)."""
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if token in ADMIN_SESSIONS:
        return  # owner — full access
    staff = STAFF_SESSIONS.get(token)
    if staff:
        if perm is None or perm in staff.get("perms", set()):
            return
        raise HTTPException(status_code=403, detail=f"Staff lacks '{perm}' permission")
    raise HTTPException(status_code=401, detail="Unauthorized")


def check_owner(token: Optional[str]) -> None:
    """Owner-only routes — reject staff tokens."""
    if not token or token not in ADMIN_SESSIONS:
        raise HTTPException(status_code=403, detail="Owner only")


async def get_actor_display_name(token: Optional[str]) -> str:
    """Return the display nickname for whoever is making the request (owner or staff).
    Used to attribute replies in tickets / AI chat to the right person."""
    if not token:
        return "Support"
    if token in ADMIN_SESSIONS:
        # Owner — use persisted nickname (falls back to in-mem default)
        cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "owner_display_name": 1})
        return (cfg or {}).get("owner_display_name") or OWNER_DISPLAY_NAME or "Owner"
    s = STAFF_SESSIONS.get(token)
    if s:
        return s.get("display_name") or s.get("username") or "Staff"
    return "Support"


def gen_coupon_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "BS-" + "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(3))


async def get_smm_config() -> dict:
    """Legacy single-config — kept for backwards compat (Settings tab still uses it)."""
    cfg = await db.smm_config.find_one({}, {"_id": 0})
    if cfg and cfg.get("api_url") and cfg.get("api_key"):
        return cfg
    return {"api_url": SMM_API_URL_DEFAULT, "api_key": SMM_API_KEY_DEFAULT}


async def get_provider(provider_id: Optional[str] = None) -> dict:
    """Return the SMM provider. If provider_id given, look it up; else first enabled provider; else legacy config."""
    if provider_id:
        p = await db.smm_providers.find_one({"id": provider_id, "enabled": True}, {"_id": 0})
        if p:
            return p
        raise HTTPException(status_code=502, detail=f"Provider {provider_id} not found or disabled")
    # First enabled
    p = await db.smm_providers.find_one({"enabled": True}, {"_id": 0})
    if p:
        return p
    # Fallback to legacy smm_config
    cfg = await get_smm_config()
    return {"id": "_legacy", "name": "Default", "api_url": cfg["api_url"], "api_key": cfg["api_key"]}


async def smm_request(payload: dict, provider_id: Optional[str] = None) -> dict:
    p = await get_provider(provider_id)
    payload["key"] = p["api_key"]
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(p["api_url"], data=payload)
        r.raise_for_status()
        return r.json()


async def place_smm_order(service_id: int, link: str, quantity: int, comments: Optional[str] = None, provider_id: Optional[str] = None) -> dict:
    payload = {"action": "add", "service": service_id, "link": link, "quantity": quantity}
    if comments:
        payload["comments"] = comments
    return await smm_request(payload, provider_id=provider_id)


# ============ PUBLIC ROUTES ============
@api_router.get("/")
async def root():
    return {"app": "Better Social", "status": "ok"}


def _parse_delivery_minutes(text: str) -> Optional[int]:
    """Try to extract a delivery time (in minutes) from a free-form description.
    Looks for patterns like 'Start time: 0-1H', 'Speed: 1k/24h', '5 min start', '~2 hours' etc.
    Returns None if nothing parseable found."""
    if not text:
        return None
    import re as _re
    t = text.lower()
    # Direct: "30 minute(s)" / "2 hour(s)" / "1 day"
    m = _re.search(r"(\d+)\s*(min|minute|hour|hr|day|d)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("min"):
            return n
        if unit.startswith("hr") or unit.startswith("hour"):
            return n * 60
        if unit.startswith("d"):
            return n * 60 * 24
    # Range like "0-1h" or "1-6 hours"
    m = _re.search(r"(\d+)\s*-\s*(\d+)\s*(h|hour|m|min|d|day)", t)
    if m:
        hi = int(m.group(2))
        unit = m.group(3)
        if unit.startswith("h"):
            return hi * 60
        if unit.startswith("m"):
            return hi
        if unit.startswith("d"):
            return hi * 60 * 24
    return None


@api_router.get("/services")
async def list_services():
    """Public catalog: only curated enabled services with admin's custom price."""
    items = await db.curated_services.find({"enabled": True}, {"_id": 0}).to_list(2000)
    services = [
        {
            "service": s["service_id"],
            "name": (s.get("custom_name") or s.get("name") or ""),
            "category": s.get("category", "Other"),
            "rate": s.get("custom_rate", 0),
            "min": s.get("min", 1),
            "max": s.get("max", 1000000),
            "type": s.get("type", "Default"),
            "needs_custom_text": bool(s.get("needs_custom_text", False)),
            "provider_id": s.get("provider_id"),
            "provider_name": s.get("provider_name", ""),
            "description": s.get("description", "") or "",
            "delivery_minutes": s.get("delivery_minutes"),
            "manual": bool(s.get("manual", False)),
            "price_flat": s.get("price_flat"),  # for manual services, total price (not per 1k)
        }
        for s in items
    ]
    return {"services": services}


@api_router.post("/coupon/check")
async def check_coupon(payload: dict):
    code = (payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")
    coupon = await db.coupons.find_one({"code": code}, {"_id": 0})
    if not coupon:
        raise HTTPException(status_code=404, detail="Invalid coupon")
    return {"code": coupon["code"], "balance": coupon["balance"]}


@api_router.post("/checkout")
async def checkout(req: CheckoutRequest, request: Request):
    ip = get_client_ip(request)
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Look up service to get provider_id and check comment requirement
    svc = await db.curated_services.find_one(
        {"service_id": req.service_id, "enabled": True},
        {"_id": 0, "provider_id": 1, "needs_custom_text": 1, "name": 1, "manual": 1},
    )
    provider_id = svc.get("provider_id") if svc else None
    is_manual = bool(svc.get("manual")) if svc else False
    needs_custom = bool(svc.get("needs_custom_text")) if svc else False
    comments = (req.comments or "").strip() or None
    if needs_custom and not comments:
        raise HTTPException(
            status_code=400,
            detail="This service requires custom comments — please enter your comment text.",
        )

    base_doc = {
        "id": order_id,
        "service_id": req.service_id,
        "link": req.link,
        "quantity": req.quantity,
        "price_usd": req.price_usd,
        "payment_method": req.payment_method,
        "customer_email": req.customer_email or "",
        "ip": ip,
        "created_at": now,
        "smm_order_id": None,
        "smm_response": None,
        "comments": comments,
        "provider_id": provider_id,
        "manual": is_manual,
    }

    # ----- Coupon flow -----
    if req.payment_method == "coupon":
        code = (req.coupon_code or "").strip().upper()
        # Atomic deduct: only if balance is sufficient
        deducted = await db.coupons.find_one_and_update(
            {"code": code, "balance": {"$gte": req.price_usd}},
            {"$inc": {"balance": -req.price_usd}},
            return_document=False,
        )
        if not deducted:
            existing = await db.coupons.find_one({"code": code})
            if not existing:
                raise HTTPException(status_code=404, detail="Invalid coupon code")
            raise HTTPException(status_code=400, detail=f"Insufficient coupon balance (${existing['balance']:.2f})")

        # Manual service → don't call provider API; mark as awaiting manual fulfillment
        if is_manual:
            base_doc.update({
                "status": "awaiting_manual_fulfillment",
                "coupon_code": code,
            })
            await db.orders.insert_one(base_doc.copy())
            remaining = await db.coupons.find_one({"code": code}, {"_id": 0, "balance": 1})
            if remaining and remaining.get("balance", 0) <= 0.005:
                await db.coupons.delete_one({"code": code})
            return {"status": "success", "order_id": order_id, "manual": True}

        # Place provider order; refund on failure
        try:
            smm_resp = await place_smm_order(req.service_id, req.link, req.quantity, comments=comments, provider_id=provider_id)
        except Exception as e:
            await db.coupons.update_one({"code": code}, {"$inc": {"balance": req.price_usd}})
            raise HTTPException(status_code=502, detail=f"Provider API error: {e}")

        if "error" in smm_resp:
            await db.coupons.update_one({"code": code}, {"$inc": {"balance": req.price_usd}})
            raise HTTPException(status_code=400, detail=f"Provider error: {smm_resp['error']}")

        base_doc.update({
            "status": "completed",
            "coupon_code": code,
            "smm_order_id": smm_resp.get("order"),
            "smm_response": smm_resp,
        })
        await db.orders.insert_one(base_doc.copy())

        # Auto-delete coupon when balance hits zero (or rounds to zero)
        remaining = await db.coupons.find_one({"code": code}, {"_id": 0, "balance": 1})
        if remaining and remaining.get("balance", 0) <= 0.005:
            await db.coupons.delete_one({"code": code})

        return {"status": "success", "order_id": order_id, "smm_order_id": smm_resp.get("order")}

    # ----- Cryptomus flow -----
    if req.payment_method == "cryptomus":
        cfg = await db.cryptomus_config.find_one({}, {"_id": 0})
        if not cfg or not cfg.get("merchant_uuid") or not cfg.get("payment_api_key"):
            raise HTTPException(status_code=400, detail="Cryptomus is not configured. Use coupon code instead.")

        # Build backend origin (for callback) from request
        origin = str(request.base_url).rstrip("/")
        body = {
            "amount": f"{req.price_usd:.2f}",
            "currency": "USD",
            "order_id": order_id,
            "url_callback": f"{origin}/api/cryptomus/webhook",
            "url_success": f"{origin}/status/{order_id}",
            "url_return": f"{origin}/status/{order_id}",
            "lifetime": 3600,
        }
        body_json = jsonlib.dumps(body, separators=(",", ":"), ensure_ascii=False)
        b64 = base64.b64encode(body_json.encode("utf-8")).decode("utf-8")
        sign = hashlib.md5((b64 + cfg["payment_api_key"]).encode("utf-8")).hexdigest()

        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(
                    "https://api.cryptomus.com/v1/payment",
                    content=body_json.encode("utf-8"),
                    headers={
                        "merchant": cfg["merchant_uuid"],
                        "sign": sign,
                        "Content-Type": "application/json",
                    },
                )
                cp = r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Cryptomus error: {e}")

        if cp.get("state") != 0 or not cp.get("result"):
            errors = cp.get("errors") or cp.get("message") or "Unknown Cryptomus error"
            raise HTTPException(status_code=400, detail=f"Cryptomus: {errors}")

        result = cp["result"]
        base_doc.update({
            "status": "pending",
            "txn_id": result.get("uuid"),
            "checkout_url": result.get("url"),
            "crypto_amount": result.get("amount"),
            "crypto_address": result.get("address"),
        })
        await db.orders.insert_one(base_doc.copy())
        return {
            "status": "pending",
            "order_id": order_id,
            "txn_id": result.get("uuid"),
            "checkout_url": result.get("url"),
            "amount": result.get("amount"),
            "currency": result.get("currency"),
            "address": result.get("address"),
        }

    raise HTTPException(status_code=400, detail="Invalid payment method")


@api_router.get("/order-status/{order_id}")
async def public_order_status(order_id: str):
    """Public endpoint for the status page to poll order state."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "smm_response": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "status": order.get("status", "pending"),
        "smm_order_id": order.get("smm_order_id"),
        "failure_reason": order.get("failure_reason"),
        "payment_method": order.get("payment_method"),
        "checkout_url": order.get("checkout_url"),
        "price_usd": order.get("price_usd"),
    }


async def _cryptomus_sign(api_key: str, body: dict) -> tuple[str, str]:
    body_json = jsonlib.dumps(body, separators=(",", ":"), ensure_ascii=False)
    b64 = base64.b64encode(body_json.encode("utf-8")).decode("utf-8")
    sig = hashlib.md5((b64 + api_key).encode("utf-8")).hexdigest()
    return body_json, sig


async def _finalize_order(order_id: str) -> dict:
    """Place SMM order for a pending order; mark completed or failed."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return {"status": "not_found"}
    if order.get("status") == "completed":
        return {"status": "completed", "smm_order_id": order.get("smm_order_id")}
    try:
        smm_resp = await place_smm_order(
            order["service_id"],
            order["link"],
            order["quantity"],
            comments=order.get("comments"),
            provider_id=order.get("provider_id"),
        )
    except Exception as e:
        await db.orders.update_one({"id": order_id}, {"$set": {"status": "failed", "failure_reason": str(e)}})
        return {"status": "failed", "reason": str(e)}
    if "error" in smm_resp:
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"status": "failed", "failure_reason": smm_resp["error"], "smm_response": smm_resp}},
        )
        return {"status": "failed", "reason": smm_resp["error"]}
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": "completed", "smm_order_id": smm_resp.get("order"), "smm_response": smm_resp}},
    )
    return {"status": "completed", "smm_order_id": smm_resp.get("order")}


@api_router.post("/cryptomus/check")
async def check_cryptomus(req: CheckTxRequest):
    """Poll Cryptomus status; if paid, place SMM order and mark fulfilled."""
    order = await db.orders.find_one({"id": req.order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") == "completed":
        return {"status": "completed", "smm_order_id": order.get("smm_order_id")}
    if order.get("status") == "failed":
        return {"status": "failed", "reason": order.get("failure_reason")}

    cfg = await db.cryptomus_config.find_one({}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=400, detail="Cryptomus not configured")

    body = {"order_id": req.order_id}
    body_json, sig = await _cryptomus_sign(cfg["payment_api_key"], body)
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(
            "https://api.cryptomus.com/v1/payment/info",
            content=body_json.encode("utf-8"),
            headers={"merchant": cfg["merchant_uuid"], "sign": sig, "Content-Type": "application/json"},
        )
        cp = r.json()

    if cp.get("state") != 0:
        return {"status": "pending", "detail": cp.get("message")}

    result = cp.get("result", {})
    pay_status = (result.get("status") or "").lower()
    if pay_status in ("paid", "paid_over"):
        return await _finalize_order(req.order_id)
    if pay_status in ("fail", "cancel", "system_fail", "wrong_amount"):
        await db.orders.update_one(
            {"id": req.order_id},
            {"$set": {"status": "failed", "failure_reason": f"Payment {pay_status}"}},
        )
        return {"status": "failed", "reason": f"Payment {pay_status}"}
    return {"status": "pending", "cp_status": pay_status}


@api_router.post("/cryptomus/webhook")
async def cryptomus_webhook(request: Request):
    """Receive Cryptomus IPN. Verify sign, then place SMM order on paid."""
    cfg = await db.cryptomus_config.find_one({}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=503, detail="Cryptomus not configured")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    provided_sign = payload.get("sign")
    if not provided_sign:
        raise HTTPException(status_code=400, detail="Missing sign")

    verify_body = {k: v for k, v in payload.items() if k != "sign"}
    body_json = jsonlib.dumps(verify_body, separators=(",", ":"), ensure_ascii=False)
    b64 = base64.b64encode(body_json.encode("utf-8")).decode("utf-8")
    expected = hashlib.md5((b64 + cfg["payment_api_key"]).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, provided_sign):
        logger.warning(f"Cryptomus webhook sign mismatch for order {payload.get('order_id')}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    order_id = payload.get("order_id")
    pay_status = (payload.get("status") or "").lower()
    if not order_id:
        return {"ok": True}

    if pay_status in ("paid", "paid_over"):
        await _finalize_order(order_id)
    elif pay_status in ("fail", "cancel", "system_fail", "wrong_amount"):
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"status": "failed", "failure_reason": f"Payment {pay_status}"}},
        )
    return {"ok": True}


# ============ ADMIN ROUTES ============

# Per-IP failed-login tracker for brute-force protection
# {ip: {"fails": int, "locked_until": iso_datetime or None}}
_ADMIN_LOGIN_ATTEMPTS: dict = {}
MAX_ADMIN_LOGIN_FAILS = 5
LOCKOUT_MINUTES = 15


def _check_admin_login_rate(request: Request) -> None:
    """Raise 429 if this IP is currently locked out from too many failed admin logins."""
    ip = get_client_ip(request)
    rec = _ADMIN_LOGIN_ATTEMPTS.get(ip)
    if not rec:
        return
    locked = rec.get("locked_until")
    if locked:
        try:
            when = datetime.fromisoformat(locked.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < when:
                secs = int((when - datetime.now(timezone.utc)).total_seconds())
                raise HTTPException(status_code=429, detail=f"Too many failed attempts. Locked for {secs}s.")
            # Lock expired — reset
            _ADMIN_LOGIN_ATTEMPTS.pop(ip, None)
        except ValueError:
            _ADMIN_LOGIN_ATTEMPTS.pop(ip, None)


def _record_admin_login_fail(request: Request) -> None:
    ip = get_client_ip(request)
    rec = _ADMIN_LOGIN_ATTEMPTS.setdefault(ip, {"fails": 0, "locked_until": None})
    rec["fails"] += 1
    if rec["fails"] >= MAX_ADMIN_LOGIN_FAILS:
        rec["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()


def _clear_admin_login_fails(request: Request) -> None:
    _ADMIN_LOGIN_ATTEMPTS.pop(get_client_ip(request), None)


@api_router.post("/admin/login")
async def admin_login(payload: AdminLogin, request: Request):
    _check_admin_login_rate(request)
    # Case-insensitive username + strip whitespace to forgive typos
    if (payload.username or "").strip().lower() != ADMIN_USER.lower() or \
       (payload.password or "") != ADMIN_PASS:
        _record_admin_login_fail(request)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_admin_login_fails(request)
    token = secrets.token_urlsafe(24)
    ADMIN_SESSIONS.add(token)
    return {"token": token}


class AdminSecretLogin(BaseModel):
    secret: str


@api_router.post("/admin/login-secret")
async def admin_login_secret(payload: AdminSecretLogin, request: Request):
    """Bypass username/password by providing a pre-shared URL secret.
    Configure by setting ADMIN_URL_SECRET in backend/.env."""
    _check_admin_login_rate(request)
    if not ADMIN_URL_SECRET:
        raise HTTPException(status_code=404, detail="Not configured")
    if not secrets.compare_digest((payload.secret or "").strip(), ADMIN_URL_SECRET):
        _record_admin_login_fail(request)
        raise HTTPException(status_code=401, detail="Invalid secret")
    _clear_admin_login_fails(request)
    token = secrets.token_urlsafe(24)
    ADMIN_SESSIONS.add(token)
    return {"token": token}


@api_router.post("/admin/session-from-user")
async def admin_session_from_user(user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Auto-elevate any client-logged-in team member (owner / admin / moderator)
    to an admin panel session. Owners get full access. Admins/mods get a
    staff-style session gated by their per-user `admin_perms` (default: only
    ai_inbox + tickets)."""
    if user.role not in ("owner", "admin", "moderator"):
        raise HTTPException(status_code=403, detail="Team access only")
    u = await request.app.state.db.users.find_one({"id": user.id}, {"_id": 0})
    perms = _team_perms_from_user(u or {})
    token = secrets.token_urlsafe(24)
    if user.role == "owner":
        ADMIN_SESSIONS.add(token)
        return {"token": token, "role": "owner", "username": user.username, "perms": perms}
    STAFF_SESSIONS[token] = {
        "id": user.id,
        "username": user.username,
        "display_name": (u or {}).get("display_name") or user.username,
        "perms": set(perms),
    }
    return {"token": token, "role": user.role, "username": user.username, "perms": perms}


# ============ Admin login using regular DASHBOARD credentials ============
# Owners get full admin. Admins/mods (role stored in the users collection)
# come in as staff-style sessions whose perms are per-user configurable via
# `admin_perms` in the users doc. Existing admin/mod accounts default to
# ai_inbox + tickets only.
DEFAULT_TEAM_PERMS = ["ai_inbox", "tickets"]


def _team_perms_from_user(user_doc: dict) -> List[str]:
    role = (user_doc or {}).get("role")
    if role == "owner":
        return list(STAFF_PERMS) + ["all"]
    if role in ("admin", "moderator"):
        raw = (user_doc or {}).get("admin_perms")
        if isinstance(raw, list):
            # Only respect known perms so a fat-fingered value can't sneak by
            good = [p for p in raw if p in STAFF_PERMS]
            return good or list(DEFAULT_TEAM_PERMS)
        return list(DEFAULT_TEAM_PERMS)
    return []


class AdminAccountLogin(BaseModel):
    identifier: str
    password: str
    captcha_id: Optional[str] = None
    captcha_answer: Optional[str] = None


@api_router.post("/admin/login-with-account")
async def admin_login_with_account(payload: AdminAccountLogin, request: Request):
    """Allow ANY user with role in {owner, admin, moderator} to sign into the
    admin panel using their normal dashboard credentials. Returns:
      • Owner → full ADMIN_SESSIONS token (behaves exactly like /admin/login).
      • Admin/moderator → STAFF_SESSIONS token with per-user perms (default
        limited to ai_inbox + tickets; owner can widen via /admin/users/{uid}/admin-perms).
    """
    _check_admin_login_rate(request)
    # Reuse the dashboard login pipeline so captcha, hashing and lockouts stay
    # in a single place — we just need the user record back.
    from auth_and_chat import verify_login_credentials  # local import to avoid top-level circular
    try:
        u = await verify_login_credentials(payload.identifier, payload.password, payload.captcha_id, payload.captcha_answer, request)
    except HTTPException as e:
        _record_admin_login_fail(request)
        raise e
    role = (u or {}).get("role")
    if role not in ("owner", "admin", "moderator"):
        _record_admin_login_fail(request)
        raise HTTPException(status_code=403, detail="Your account has no admin access")
    _clear_admin_login_fails(request)
    perms = _team_perms_from_user(u)
    if role == "owner":
        token = secrets.token_urlsafe(24)
        ADMIN_SESSIONS.add(token)
        return {"token": token, "role": "owner", "username": u["username"], "perms": perms}
    # admin / moderator — issue a staff-style session so check_admin() honours perms
    token = secrets.token_urlsafe(24)
    STAFF_SESSIONS[token] = {
        "id": u["id"],
        "username": u["username"],
        "display_name": u.get("display_name") or u["username"],
        "perms": set(perms),
    }
    return {"token": token, "role": role, "username": u["username"], "perms": perms}


class TeamPermsUpdate(BaseModel):
    perms: List[str] = Field(default_factory=list)


@api_router.patch("/admin/users/{uid}/admin-perms")
async def admin_update_user_admin_perms(
    uid: str,
    payload: TeamPermsUpdate,
    x_admin_token: Optional[str] = Header(None),
):
    """Owner-only: set which admin-panel features a team member can access.
    `perms` is validated against STAFF_PERMS."""
    check_owner(x_admin_token)
    clean = [p for p in payload.perms if p in STAFF_PERMS]
    r = await db.users.update_one({"id": uid, "role": {"$in": ["admin", "moderator"]}}, {"$set": {"admin_perms": clean}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Team member not found (must have role admin or moderator)")
    # Live-refresh any active staff sessions for this user
    for t, s in STAFF_SESSIONS.items():
        if s.get("id") == uid:
            s["perms"] = set(clean or DEFAULT_TEAM_PERMS)
    return {"ok": True, "perms": clean}


@api_router.get("/admin/users/team")
async def admin_list_team(x_admin_token: Optional[str] = Header(None)):
    """Owner-only: list all users whose role is admin or moderator, with their
    per-user `admin_perms` so the UI can render a permissions grid."""
    check_owner(x_admin_token)
    cursor = db.users.find(
        {"role": {"$in": ["admin", "moderator"]}},
        {"_id": 0, "id": 1, "username": 1, "role": 1, "admin_perms": 1, "email": 1, "display_name": 1, "banned": 1},
    ).sort("username", 1)
    items = await cursor.to_list(200)
    for it in items:
        if "admin_perms" not in it:
            it["admin_perms"] = list(DEFAULT_TEAM_PERMS)
    return {"team": items, "available_perms": sorted(STAFF_PERMS)}


# ============ STAFF ACCOUNTS ============

from auth_and_chat import hash_password as _hash_password, verify_password as _verify_password  # noqa: E402

class StaffCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(..., min_length=8, max_length=120)
    display_name: Optional[str] = None
    perms: List[str] = Field(default_factory=lambda: ["tickets", "ai_inbox", "orders", "discord", "withdrawals"])


class StaffLogin(BaseModel):
    username: str
    password: str


@api_router.post("/admin/staff")
async def create_staff(payload: StaffCreate, x_admin_token: Optional[str] = Header(None)):
    """Owner-only: create a staff account."""
    check_owner(x_admin_token)
    perms = [p for p in payload.perms if p in STAFF_PERMS]
    if not perms:
        raise HTTPException(status_code=400, detail="At least one permission required")
    if await db.staff_users.find_one({"username": payload.username.lower()}):
        raise HTTPException(status_code=400, detail="Username already taken")
    doc = {
        "id": str(uuid.uuid4()),
        "username": payload.username.lower(),
        "display_name": (payload.display_name or payload.username).strip()[:40],
        "password_hash": _hash_password(payload.password),
        "perms": perms,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    await db.staff_users.insert_one(doc.copy())
    return {"id": doc["id"], "username": doc["username"], "display_name": doc["display_name"], "perms": perms}


@api_router.get("/admin/staff")
async def list_staff(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    items = await db.staff_users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(50)
    return {"staff": items}


@api_router.delete("/admin/staff/{staff_id}")
async def delete_staff(staff_id: str, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    res = await db.staff_users.delete_one({"id": staff_id})
    # Invalidate any active token for this staff
    for t, s in list(STAFF_SESSIONS.items()):
        if s.get("id") == staff_id:
            STAFF_SESSIONS.pop(t, None)
    return {"deleted": res.deleted_count}


class StaffUpdate(BaseModel):
    perms: Optional[List[str]] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8, max_length=120)
    display_name: Optional[str] = Field(None, min_length=1, max_length=40)


@api_router.patch("/admin/staff/{staff_id}")
async def update_staff(staff_id: str, payload: StaffUpdate, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    upd = {}
    if payload.perms is not None:
        upd["perms"] = [p for p in payload.perms if p in STAFF_PERMS]
    if payload.active is not None:
        upd["active"] = payload.active
    if payload.password:
        upd["password_hash"] = _hash_password(payload.password)
    if payload.display_name is not None:
        upd["display_name"] = payload.display_name.strip()[:40]
    if not upd:
        return {"updated": False}
    res = await db.staff_users.update_one({"id": staff_id}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    # Refresh existing tokens' perms / display name
    for t, s in STAFF_SESSIONS.items():
        if s.get("id") == staff_id:
            if "perms" in upd:
                s["perms"] = set(upd["perms"])
            if "display_name" in upd:
                s["display_name"] = upd["display_name"]
    return {"updated": True}


@api_router.post("/admin/staff/login")
async def staff_login(payload: StaffLogin, request: Request):
    """Staff login — returns a token they use with x-admin-token header (subset of admin perms)."""
    _check_admin_login_rate(request)
    user = await db.staff_users.find_one({"username": payload.username.strip().lower(), "active": True})
    if not user or not _verify_password(payload.password, user["password_hash"]):
        _record_admin_login_fail(request)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_admin_login_fails(request)
    token = secrets.token_urlsafe(24)
    STAFF_SESSIONS[token] = {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "perms": set(user.get("perms", [])),
    }
    return {
        "token": token,
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "perms": list(user.get("perms", [])),
        "role": "staff",
    }


@api_router.get("/admin/me")
async def admin_me(x_admin_token: Optional[str] = Header(None)):
    """Tell the admin frontend which role + perms + display name the current token has."""
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if x_admin_token in ADMIN_SESSIONS:
        cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "owner_display_name": 1}) or {}
        return {
            "role": "owner",
            "username": ADMIN_USER,
            "display_name": cfg.get("owner_display_name") or OWNER_DISPLAY_NAME,
            "perms": list(STAFF_PERMS) + ["all"],
        }
    s = STAFF_SESSIONS.get(x_admin_token)
    if s:
        return {
            "role": "staff",
            "username": s["username"],
            "display_name": s.get("display_name") or s["username"],
            "perms": list(s["perms"]),
        }
    raise HTTPException(status_code=401, detail="Unauthorized")


class NicknameUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=40)


@api_router.post("/admin/me/nickname")
async def update_my_nickname(payload: NicknameUpdate, x_admin_token: Optional[str] = Header(None)):
    """Owner or staff updates their own display nickname (shown to clients in chats/tickets)."""
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    new_name = payload.display_name.strip()[:40]
    if x_admin_token in ADMIN_SESSIONS:
        global OWNER_DISPLAY_NAME
        OWNER_DISPLAY_NAME = new_name
        await db.app_settings.update_one(
            {"_id": "singleton"},
            {"$set": {"owner_display_name": new_name}},
            upsert=True,
        )
        return {"display_name": new_name, "role": "owner"}
    s = STAFF_SESSIONS.get(x_admin_token)
    if not s:
        raise HTTPException(status_code=401, detail="Unauthorized")
    await db.staff_users.update_one({"id": s["id"]}, {"$set": {"display_name": new_name}})
    s["display_name"] = new_name
    return {"display_name": new_name, "role": "staff"}




@api_router.get("/admin/orders")
async def admin_orders(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "orders")
    orders = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"orders": orders}


@client_router.get("/orders")
async def my_orders(user: CurrentUser = Depends(current_user_dep), limit: int = 20):
    """The current user's recent orders — used by the classic dashboard."""
    cur = db.orders.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(min(int(limit or 20), 100))
    return {"orders": await cur.to_list(100)}


def _mask_username(name: str) -> str:
    """Half-mask a username with hashtags for the public feed.
    'testbugfix1' -> 'te#####x1' (first 2 + hashes + last 2)."""
    if not name:
        return "###"
    n = len(name)
    if n <= 3:
        return name[0] + "#" * (n - 1) if n > 1 else "#"
    head = 2 if n <= 6 else 3
    tail = 1 if n <= 5 else 2
    mid = max(3, n - head - tail)
    return f"{name[:head]}{'#' * mid}{name[-tail:]}"


@api_router.get("/orders/latest-global")
async def orders_latest_global(limit: int = 20):
    """PUBLIC feed of the latest orders across all users (usernames half-masked).
    Powers the new dashboard's LEFT panel — social proof that the shop is active."""
    cur = db.orders.find(
        {"username": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "username": 1, "service_name": 1, "service": 1,
         "status": 1, "total": 1, "charge": 1, "created_at": 1, "quantity": 1},
    ).sort("created_at", -1).limit(min(int(limit or 20), 50))
    out = []
    async for o in cur:
        o["username"] = _mask_username(o.get("username") or "")
        out.append(o)
    return {"orders": out}




@api_router.get("/admin/coupons")
async def admin_coupons(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    coupons = await db.coupons.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"coupons": coupons}


@api_router.post("/admin/coupons")
async def admin_create_coupon(payload: CouponCreate, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    code = gen_coupon_code()
    doc = {
        "code": code,
        "amount": payload.amount,
        "balance": payload.amount,
        "note": payload.note or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.coupons.insert_one(doc.copy())
    return {"code": code, "amount": payload.amount, "balance": payload.amount}


@api_router.delete("/admin/coupons/{code}")
async def admin_delete_coupon(code: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    res = await db.coupons.delete_one({"code": code.upper()})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return {"deleted": True}


class CouponBalanceUpdate(BaseModel):
    balance: float


@api_router.put("/admin/coupons/{code}/balance")
async def admin_update_coupon_balance(
    code: str,
    payload: CouponBalanceUpdate,
    x_admin_token: Optional[str] = Header(None),
):
    check_admin(x_admin_token)
    if payload.balance < 0:
        raise HTTPException(status_code=400, detail="Balance must be ≥ 0")
    res = await db.coupons.find_one_and_update(
        {"code": code.upper()},
        {"$set": {"balance": round(payload.balance, 4)}},
        return_document=True,
        projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return {"code": res["code"], "balance": res["balance"]}


@api_router.get("/orders/recent-feed")
async def public_orders_feed():
    """Public ticker feed — masked email + service name. Last 30 completed orders."""
    cursor = (
        db.orders.find(
            {"smm_order_id": {"$ne": None}},
            {"_id": 0, "service_id": 1, "quantity": 1, "customer_email": 1, "created_at": 1, "source": 1},
        )
        .sort("created_at", -1)
        .limit(30)
    )
    items = await cursor.to_list(30)

    # Resolve service names (cache in dict to avoid N+1)
    svc_ids = list({i.get("service_id") for i in items if i.get("service_id")})
    svc_map = {}
    if svc_ids:
        async for s in db.curated_services.find({"service_id": {"$in": svc_ids}}, {"_id": 0, "service_id": 1, "name": 1}):
            svc_map[s["service_id"]] = s.get("name") or "Service"

    def mask(email: str) -> str:
        e = (email or "").strip()
        if not e or "@" not in e:
            return "gu**"
        local = e.split("@")[0]
        if len(local) <= 2:
            return local + "**"
        return local[:2] + "*" * (max(2, len(local) - 2))

    feed = []
    for o in items:
        feed.append({
            "user": mask(o.get("customer_email", "")),
            "service": svc_map.get(o.get("service_id"), "an SMM service"),
            "quantity": o.get("quantity"),
            "created_at": o.get("created_at"),
        })
    return {"feed": feed}


# ============ ADMIN USER MANAGEMENT ============

@api_router.get("/admin/users")
async def admin_list_users(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    items = await db.users.find(
        {},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1).to_list(500)
    # Enrich each user with current wallet balance + withdrawable
    for u in items:
        try:
            u["balance"] = await _get_user_balance(u["id"])
            u["withdrawable"] = await _get_user_withdrawable(u["id"])
        except Exception:
            u["balance"] = 0
            u["withdrawable"] = 0
    return {"users": items, "count": len(items)}


class AdminBalanceAdjust(BaseModel):
    amount: float = Field(..., ge=-100000, le=100000)  # positive = add, negative = subtract
    reason: Optional[str] = "admin_adjustment"
    note: Optional[str] = ""


@api_router.post("/admin/users/{user_id}/adjust-balance")
async def admin_adjust_user_balance(
    user_id: str,
    payload: AdminBalanceAdjust,
    x_admin_token: Optional[str] = Header(None),
):
    """Owner/staff (with admin perms) credits or debits a user's wallet balance.
    Persists as a transaction so it shows in their history."""
    check_admin(x_admin_token)
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "username": 1})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.amount == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero")
    actor = await get_actor_display_name(x_admin_token)
    now = datetime.now(timezone.utc).isoformat()
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "username": u["username"],
        "amount": round(float(payload.amount), 2),
        "method": "admin",
        "status": "approved",
        "type": payload.reason or "admin_adjustment",
        "note": (payload.note or f"by {actor}")[:200],
        "actor": actor,
        "created_at": now,
        "approved_at": now,
    })
    new_balance = await _get_user_balance(user_id)
    return {"ok": True, "new_balance": new_balance, "actor": actor}


class AdminUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = None  # 'user' | 'admin' | 'owner'
    muted_until: Optional[str] = None
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


@api_router.put("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    payload: AdminUserUpdate,
    x_admin_token: Optional[str] = Header(None),
):
    check_admin(x_admin_token)
    update = {}
    if payload.email is not None:
        # uniqueness check
        existing = await db.users.find_one(
            {"email": payload.email.lower(), "id": {"$ne": user_id}},
            {"_id": 0, "id": 1},
        )
        if existing:
            raise HTTPException(status_code=400, detail="Email already used by another user")
        update["email"] = payload.email.lower()
    if payload.role is not None:
        if payload.role not in {"user", "admin", "owner"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        update["role"] = payload.role
    if payload.muted_until is not None:
        update["muted_until"] = payload.muted_until or None
    if payload.new_password:
        from auth_and_chat import hash_password
        update["password_hash"] = hash_password(payload.new_password)
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.users.find_one_and_update(
        {"id": user_id},
        {"$set": update},
        return_document=True,
        projection={"_id": 0, "password_hash": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": res}


@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1, "username": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    if doc.get("role") == "owner":
        raise HTTPException(status_code=400, detail="Cannot delete owner account")
    await db.users.delete_one({"id": user_id})
    return {"deleted": True, "username": doc.get("username")}


# ============ MASS MAIL ============

class MassMailRequest(BaseModel):
    subject: str = Field(..., min_length=2, max_length=200)
    body_html: str = Field(..., min_length=2, max_length=50000)
    only_role: Optional[str] = None  # None = all users, "user" / "admin" etc to filter


@api_router.post("/admin/mass-mail")
async def admin_mass_mail(payload: MassMailRequest, x_admin_token: Optional[str] = Header(None)):
    """Send a custom email to every registered user (or a subset by role).
    Uses the configured email provider (MailerSend or SMTP)."""
    check_admin(x_admin_token)
    from email_service import send_email, _wrap
    q = {}
    if payload.only_role:
        q["role"] = payload.only_role
    users = await db.users.find(q, {"_id": 0, "email": 1, "username": 1}).to_list(10000)
    if not users:
        raise HTTPException(status_code=400, detail="No recipients")
    sent = 0
    failed = 0
    errors = []
    wrapped = _wrap(payload.body_html)
    for u in users:
        em = (u.get("email") or "").strip()
        if not em or "@" not in em:
            continue
        res = await send_email(db, em, payload.subject, wrapped)
        if res.get("ok"):
            sent += 1
        else:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{em}: {res.get('error')}")
    # Log this campaign
    await db.mass_mail_log.insert_one({
        "id": str(uuid.uuid4()),
        "subject": payload.subject,
        "recipients_total": len(users),
        "sent": sent,
        "failed": failed,
        "actor": await get_actor_display_name(x_admin_token),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"sent": sent, "failed": failed, "total": len(users), "errors": errors}


# ============ SLOT MACHINE (Casino) ============

# Fruit pool with weighted rarity (higher weight = more common = harder to win big matches)
SLOT_ICONS = [
    {"id": "cherry", "emoji": "🍒", "weight": 30},
    {"id": "lemon", "emoji": "🍋", "weight": 28},
    {"id": "grape", "emoji": "🍇", "weight": 22},
    {"id": "watermelon", "emoji": "🍉", "weight": 15},
    {"id": "bell", "emoji": "🔔", "weight": 8},
    {"id": "diamond", "emoji": "💎", "weight": 3},
    {"id": "seven", "emoji": "7️⃣", "weight": 1},
    {"id": "wild", "emoji": "⭐", "weight": 2},  # X / Wild — substitutes for any icon
]

SLOT_ROWS = 4
SLOT_COLS = 6  # 4×6 = 24 boxes

# Payouts per matched-count in ANY single row (looking left-to-right runs of same icon)
# Very stingy: 3 in a row pays back only 0.5x the bet, 4 = 1.5x, 5 = 4x, 6 = 40x
SLOT_RUN_PAYOUTS = {3: 0.5, 4: 1.5, 5: 4.0, 6: 40.0}

# Special multiplier: rare icons multiply their run's payout
SLOT_ICON_MULT = {"diamond": 2.0, "seven": 5.0}


def _evaluate_slot_grid(grid: list, bet: float) -> tuple:
    """Return (payout_usd, winning_cells_list). Only pays for horizontal runs of 3+.
    Wild (⭐) substitutes for any icon — a run of any icon + wilds counts as that icon."""
    payout = 0.0
    winning_cells = []
    for r, row in enumerate(grid):
        c = 0
        while c < len(row):
            # Start of a potential run: skip if starting on pure wild (still valid, use next)
            base = row[c] if row[c] != "wild" else None
            run_end = c
            for k in range(c + 1, len(row)):
                cell = row[k]
                if cell == "wild":
                    run_end = k
                    continue
                if base is None:
                    base = cell
                    run_end = k
                    continue
                if cell == base:
                    run_end = k
                    continue
                break
            run_len = run_end - c + 1
            if run_len >= 3 and base is not None:
                base_mult = SLOT_RUN_PAYOUTS.get(min(run_len, 6), 0)
                icon_bonus = SLOT_ICON_MULT.get(base, 1.0)
                # Any wild in the run adds an extra ×2 boost
                if any(row[x] == "wild" for x in range(c, run_end + 1)):
                    icon_bonus *= 2.0
                run_pay = bet * base_mult * icon_bonus
                payout += run_pay
                winning_cells.extend([[r, x] for x in range(c, run_end + 1)])
            c = run_end + 1
    return round(payout, 2), winning_cells


class SlotSpinRequest(BaseModel):
    bet: float = Field(..., ge=0.05, le=100.0)


def _slot_random_icon() -> str:
    """Pick a weighted random icon."""
    import random
    total = sum(i["weight"] for i in SLOT_ICONS)
    r = random.uniform(0, total)
    acc = 0
    for icon in SLOT_ICONS:
        acc += icon["weight"]
        if r <= acc:
            return icon["id"]
    return SLOT_ICONS[0]["id"]


@client_router.get("/slots/config")
async def slots_config(user: CurrentUser = Depends(current_user_dep)):
    """Return the icon pool and rules so the client can render the machine."""
    return {
        "icons": SLOT_ICONS,
        "rows": SLOT_ROWS,
        "cols": SLOT_COLS,
        "min_bet": 0.05,
        "max_bet": 100.0,
        "payouts": SLOT_RUN_PAYOUTS,
        "special_multipliers": SLOT_ICON_MULT,
    }


@client_router.post("/slots/spin")
async def slots_spin(body: SlotSpinRequest, user: CurrentUser = Depends(current_user_dep)):
    """Deduct bet from user balance, roll the grid, and credit any winnings.
    Payouts go to withdrawable_balance (like the old Try Chance) so users can cash out."""
    bet = round(float(body.bet), 2)
    if bet < 0.05 or bet > 100.0:
        raise HTTPException(status_code=400, detail="Bet must be between $0.05 and $100")

    balance = await _get_user_balance(user.id)
    if balance < bet:
        raise HTTPException(status_code=402, detail=f"Not enough balance — you have ${balance:.2f}")

    # Deduct bet
    now = datetime.now(timezone.utc).isoformat()
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": -bet,
        "method": "balance",
        "status": "approved",
        "type": "slot_bet",
        "created_at": now,
        "approved_at": now,
    })

    # Generate grid
    grid = [[_slot_random_icon() for _ in range(SLOT_COLS)] for _ in range(SLOT_ROWS)]
    payout, winning_cells = _evaluate_slot_grid(grid, bet)

    # Credit winnings to withdrawable_balance
    if payout > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "username": user.username,
            "amount": payout,
            "method": "casino_win",
            "status": "approved",
            "type": "slot_win",
            "withdrawable": True,
            "created_at": now,
            "approved_at": now,
        })

    new_balance = await _get_user_balance(user.id)
    new_withdrawable = await _get_user_withdrawable(user.id)

    return {
        "grid": grid,
        "bet": bet,
        "payout": payout,
        "net": round(payout - bet, 2),
        "winning_cells": winning_cells,
        "balance": new_balance,
        "withdrawable_balance": new_withdrawable,
    }


class MuteRequest(BaseModel):
    minutes: int = Field(default=60, ge=1, le=43200)  # 1 min to 30 days


@api_router.post("/admin/users/{user_id}/mute")
async def admin_mute_user(
    user_id: str,
    body: MuteRequest,
    x_admin_token: Optional[str] = Header(None),
):
    check_admin(x_admin_token)
    until = (datetime.now(timezone.utc) + timedelta(minutes=body.minutes)).isoformat()
    res = await db.users.update_one({"id": user_id}, {"$set": {"muted_until": until}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "muted_until": until}


@api_router.post("/admin/users/{user_id}/unmute")
async def admin_unmute_user(user_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    res = await db.users.update_one({"id": user_id}, {"$set": {"muted_until": None}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


# ============ PAYPAL CONFIG + ADD FUNDS ============

class PaypalConfig(BaseModel):
    paypal_email: str = Field(default="", max_length=120)
    paypal_me_url: str = Field(default="", max_length=200)


@api_router.get("/paypal-config")
async def public_paypal_config():
    """Public — frontend reads paypal.me URL to redirect users to."""
    cfg = await db.paypal_config.find_one({}, {"_id": 0}) or {}
    return {
        "paypal_email": cfg.get("paypal_email", ""),
        "paypal_me_url": cfg.get("paypal_me_url", ""),
        "configured": bool(cfg.get("paypal_me_url") or cfg.get("paypal_email")),
    }


@api_router.post("/admin/paypal-config")
async def admin_set_paypal_config(payload: PaypalConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    await db.paypal_config.update_one(
        {},
        {"$set": {
            "paypal_email": payload.paypal_email.strip(),
            "paypal_me_url": payload.paypal_me_url.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True}


async def _get_user_balance(user_id: str) -> float:
    """Total balance = approved txns + pending withdrawal reservations (which are negative)."""
    cur = db.transactions.aggregate([
        {"$match": {
            "user_id": user_id,
            "$or": [
                {"status": "approved"},
                {"status": "pending", "type": "withdrawal"},
            ],
        }},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ])
    async for doc in cur:
        return round(float(doc.get("total", 0)), 2)
    return 0.0


async def _get_user_withdrawable(user_id: str) -> float:
    """Withdrawable = lifetime casino wins − (pending + approved withdrawals)."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "withdrawable_balance": 1})
    return round(float((u or {}).get("withdrawable_balance", 0)), 2)


@client_router.get("/balance")
async def get_my_balance(user: CurrentUser = Depends(current_user_dep)):
    balance = await _get_user_balance(user.id)
    withdrawable = await _get_user_withdrawable(user.id)
    return {"balance": balance, "withdrawable": withdrawable}


class RedeemCouponRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=40)


@client_router.post("/redeem-coupon")
async def redeem_coupon(body: RedeemCouponRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """User enters a coupon code → its full balance is added to their wallet, coupon deleted."""
    db: AsyncIOMotorDatabase = request.app.state.db
    code = body.code.strip().upper()
    coupon = await db.coupons.find_one({"code": code}, {"_id": 0})
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    bal = float(coupon.get("balance", 0))
    if bal <= 0:
        raise HTTPException(status_code=400, detail="Coupon is empty")
    # Credit the user
    now = datetime.now(timezone.utc).isoformat()
    tx = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": round(bal, 2),
        "method": "coupon",
        "status": "approved",  # auto-approved
        "type": "deposit",
        "coupon_code": code,
        "created_at": now,
        "approved_at": now,
    }
    await db.transactions.insert_one(tx.copy())

    # 40% bonus on coupons of $100 or more
    bonus = 0.0
    if bal >= 100:
        bonus = round(bal * 0.40, 2)
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "username": user.username,
            "amount": bonus,
            "method": "bonus",
            "status": "approved",
            "type": "coupon_bonus",
            "note": f"+40% bonus for redeeming a ${bal:.2f} coupon",
            "coupon_code": code,
            "created_at": now,
            "approved_at": now,
        })
    await db.coupons.delete_one({"code": code})
    new_balance = await _get_user_balance(user.id)
    return {"ok": True, "amount": round(bal, 2), "bonus": bonus, "balance": new_balance, "code": code}


class BuyWithBalanceRequest(BaseModel):
    service_id: int
    link: str = Field(..., min_length=4, max_length=400)
    quantity: int = Field(..., gt=0)
    comments: Optional[str] = None  # Required for custom-text services


@client_router.post("/order-with-balance")
async def order_with_balance(body: BuyWithBalanceRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Place an order paying with the user's account balance."""
    db: AsyncIOMotorDatabase = request.app.state.db
    # Look up curated service
    svc = await db.curated_services.find_one({"service_id": body.service_id, "enabled": True}, {"_id": 0})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not available")
    is_manual = bool(svc.get("manual"))
    if is_manual:
        # Manual services use a flat price (price_flat), not per-1k rate
        charge = round(float(svc.get("price_flat") or 0), 2)
        if charge <= 0:
            raise HTTPException(status_code=400, detail="Service price not set")
    else:
        rate = float(svc.get("custom_rate", 0))
        if rate <= 0:
            raise HTTPException(status_code=400, detail="Service price not set")
        if body.quantity < int(svc.get("min", 1) or 1) or body.quantity > int(svc.get("max", 100000) or 100000):
            raise HTTPException(status_code=400, detail=f"Quantity must be between {svc.get('min')} and {svc.get('max')}")
        charge = round((rate * body.quantity) / 1000.0, 4)
    needs_custom = bool(svc.get("needs_custom_text"))
    comments = (body.comments or "").strip() or None
    if needs_custom and not comments:
        raise HTTPException(status_code=400, detail="This service requires custom comments — please enter them.")
    balance = await _get_user_balance(user.id)
    if balance < charge:
        raise HTTPException(status_code=402, detail=f"Not enough balance — needs ${charge:.2f}, you have ${balance:.2f}")

    now = datetime.now(timezone.utc).isoformat()

    if is_manual:
        # Skip provider API — admin will fulfill manually
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "username": user.username,
            "amount": -charge,
            "method": "balance",
            "status": "approved",
            "type": "order",
            "service_id": body.service_id,
            "created_at": now,
            "approved_at": now,
        })
        order_doc = {
            "id": str(uuid.uuid4()),
            "smm_order_id": None,
            "service_id": body.service_id,
            "service_name": (svc.get("custom_name") or svc.get("name") or ""),
            "link": body.link,
            "quantity": body.quantity,
            "charge": charge,
            "customer_email": "",
            "user_id": user.id,
            "username": user.username,
            "payment_method": "balance",
            "source": "dashboard",
            "status": "awaiting_manual_fulfillment",
            "manual": True,
            "delivery_minutes": svc.get("delivery_minutes"),
            "created_at": now,
            "comments": comments,
            "provider_id": None,
        }
        await db.orders.insert_one(order_doc.copy())
        new_balance = await _get_user_balance(user.id)
        return {"ok": True, "manual": True, "charge": charge, "balance": new_balance}

    # Place order via SMM provider through the helper exposed on app.state
    place_smm_order = request.app.state.place_smm_order
    try:
        smm_resp = await place_smm_order(
            body.service_id,
            body.link,
            body.quantity,
            comments=comments,
            provider_id=svc.get("provider_id"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Order failed: {e}")

    smm_order_id = smm_resp.get("order")
    if not smm_order_id:
        raise HTTPException(status_code=502, detail=f"Provider error: {smm_resp.get('error') or smm_resp}")

    # Debit balance via negative transaction
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": -charge,
        "method": "balance",
        "status": "approved",
        "type": "order",
        "service_id": body.service_id,
        "smm_order_id": smm_order_id,
        "created_at": now,
        "approved_at": now,
    })
    # Save order record (same collection as guest orders, but tagged)
    order_doc = {
        "id": str(uuid.uuid4()),
        "smm_order_id": smm_order_id,
        "service_id": body.service_id,
        "service_name": (svc.get("custom_name") or svc.get("name") or ""),
        "link": body.link,
        "quantity": body.quantity,
        "charge": charge,
        "customer_email": "",
        "user_id": user.id,
        "username": user.username,
        "payment_method": "balance",
        "source": "dashboard",
        "status": "Pending",
        "created_at": now,
        "comments": comments,
        "provider_id": svc.get("provider_id"),
    }
    await db.orders.insert_one(order_doc.copy())
    new_balance = await _get_user_balance(user.id)
    return {
        "ok": True,
        "order_id": order_doc["id"],
        "smm_order_id": smm_order_id,
        "charge": charge,
        "balance": new_balance,
    }


class BulkOrderRequest(BaseModel):
    service_id: int
    quantity: int = Field(..., ge=1, le=1000000)
    targets: List[str] = Field(..., min_items=1, max_items=200)  # links or usernames
    comments: Optional[str] = None


@client_router.post("/order-bulk")
async def order_bulk(body: BulkOrderRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Bulk-order the SAME service to many different profiles/streams at once.
    Skips duplicates, calculates total charge, deducts from balance atomically, then
    fires all provider calls in parallel and returns per-target results."""
    db_local: AsyncIOMotorDatabase = request.app.state.db
    svc = await db_local.curated_services.find_one({"service_id": body.service_id, "enabled": True}, {"_id": 0})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not available")
    if bool(svc.get("manual")):
        raise HTTPException(status_code=400, detail="Manual services can't be bulk-ordered — place them one at a time.")
    if bool(svc.get("needs_custom_text")) and not (body.comments or "").strip():
        raise HTTPException(status_code=400, detail="This service needs custom text — bulk not supported without comments.")
    rate = float(svc.get("custom_rate", 0))
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Service price not set")
    smin = int(svc.get("min", 1) or 1)
    smax = int(svc.get("max", 100000) or 100000)
    if body.quantity < smin or body.quantity > smax:
        raise HTTPException(status_code=400, detail=f"Quantity must be between {smin} and {smax}")

    # Normalize targets: dedupe (case-insensitive), strip whitespace, filter empties
    seen = set()
    targets = []
    for t in body.targets:
        v = (t or "").strip()
        if not v:
            continue
        k = v.lower()
        if k in seen:
            continue
        seen.add(k)
        targets.append(v)
    if not targets:
        raise HTTPException(status_code=400, detail="No valid targets")

    per_charge = round((rate * body.quantity) / 1000.0, 4)
    total_charge = round(per_charge * len(targets), 2)
    balance = await _get_user_balance(user.id)
    if balance < total_charge:
        raise HTTPException(status_code=402, detail=f"Not enough balance — needs ${total_charge:.2f} for {len(targets)} orders, you have ${balance:.2f}")

    place_smm_order = request.app.state.place_smm_order
    comments = (body.comments or "").strip() or None
    provider_id = svc.get("provider_id")
    svc_name = svc.get("custom_name") or svc.get("name") or ""

    import asyncio
    async def _one(link_or_user: str):
        try:
            resp = await place_smm_order(body.service_id, link_or_user, body.quantity, comments=comments, provider_id=provider_id)
            return {"target": link_or_user, "ok": True, "smm_order_id": resp.get("order"), "response": resp} if resp.get("order") else {"target": link_or_user, "ok": False, "error": resp.get("error") or str(resp)}
        except Exception as e:
            return {"target": link_or_user, "ok": False, "error": str(e)[:200]}

    results = await asyncio.gather(*[_one(t) for t in targets])
    now = datetime.now(timezone.utc).isoformat()
    successes = [r for r in results if r["ok"]]
    failures = [r for r in results if not r["ok"]]

    # Charge only for successful orders
    charged = round(per_charge * len(successes), 2)
    if charged > 0:
        await db_local.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id, "username": user.username,
            "amount": -charged, "method": "balance", "status": "approved",
            "type": "bulk_order",
            "service_id": body.service_id, "bulk_count": len(successes),
            "created_at": now, "approved_at": now,
        })

    # Persist one order per successful target so they show up in /client/orders
    order_docs = []
    for r in successes:
        order_docs.append({
            "id": str(uuid.uuid4()),
            "smm_order_id": r.get("smm_order_id"),
            "service_id": body.service_id,
            "service_name": svc_name,
            "link": r["target"],
            "quantity": body.quantity,
            "charge": per_charge,
            "user_id": user.id, "username": user.username,
            "payment_method": "balance", "source": "bulk",
            "status": "Pending", "created_at": now,
            "comments": comments, "provider_id": provider_id,
        })
    if order_docs:
        await db_local.orders.insert_many(order_docs)

    new_balance = await _get_user_balance(user.id)
    return {
        "ok": True,
        "total_targets": len(targets),
        "successes": len(successes),
        "failures": len(failures),
        "charged": charged,
        "results": results,
        "balance": new_balance,
    }


# ============ Repeat previous order — one-click re-buy of the same params ============
@client_router.post("/orders/{oid}/repeat")
async def repeat_order(oid: str, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Re-run an order the user already placed (same service, link, quantity, comments).
    Charges balance again and returns the new order id."""
    db_local: AsyncIOMotorDatabase = request.app.state.db
    prev = await db_local.orders.find_one({"id": oid, "user_id": user.id}, {"_id": 0})
    if not prev:
        raise HTTPException(status_code=404, detail="Order not found")
    body = BuyWithBalanceRequest(
        service_id=int(prev.get("service_id")),
        link=prev.get("link") or "",
        quantity=int(prev.get("quantity") or 0),
        comments=prev.get("comments") or None,
    )
    return await order_with_balance(body, user=user, request=request)


# ============ Saved bulk-target lists (per-user favorites) ============
class BulkListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    targets: List[str] = Field(..., min_items=1, max_items=500)


@client_router.get("/bulk-lists")
async def bulk_lists_mine(user: CurrentUser = Depends(current_user_dep)):
    cur = db.bulk_lists.find({"user_id": user.id}, {"_id": 0}).sort("updated_at", -1).limit(50)
    return {"lists": await cur.to_list(50)}


@client_router.post("/bulk-lists")
async def bulk_lists_create(body: BulkListCreate, user: CurrentUser = Depends(current_user_dep)):
    # Dedupe + trim so what we store matches what we render
    seen = set()
    targets = []
    for t in body.targets:
        v = (t or "").strip()
        if not v:
            continue
        k = v.lower()
        if k in seen:
            continue
        seen.add(k)
        targets.append(v)
    if not targets:
        raise HTTPException(status_code=400, detail="No valid targets")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "name": body.name.strip()[:60],
        "targets": targets,
        "created_at": now,
        "updated_at": now,
    }
    await db.bulk_lists.insert_one(doc.copy())
    doc.pop("_id", None)
    return {"ok": True, "list": doc}


@client_router.delete("/bulk-lists/{lid}")
async def bulk_lists_delete(lid: str, user: CurrentUser = Depends(current_user_dep)):
    r = await db.bulk_lists.delete_one({"id": lid, "user_id": user.id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ============ Addons store — one-time-purchase feature unlocks ============
ADDONS_CATALOG_DEFAULTS = [
    {
        "id": "auto_live",
        "name": "Auto-Live TikTok Automation",
        "tagline": "Fire recurring SMM bursts every time your target goes live",
        "description": "Unlocks the Live-orders panel. Set a TikTok username, pick a service (likes / comments / views), and we automatically place an order the moment they go live — repeating every 10 minutes while the stream stays up. Runs for the duration you pick.",
        "price": 250.0,
        "features": [
            "Poll TikTok every 5 minutes for live status",
            "Automatic burst every 10 min while live",
            "Live orders dashboard with 1-click cancel",
            "Balance-charged (no upfront lockup)",
            "7 / 14 / 30 / 60 / 90 / 365 day durations",
        ],
        "flag": "auto_live_enabled",
    },
]


async def _load_addons_catalog() -> list:
    """Merge defaults with any per-addon overrides stored in `app_settings.addon_overrides`.
    Only `price` is editable today, but structured so `name`/`description` can be added later."""
    cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "addon_overrides": 1}) or {}
    overrides = (cfg.get("addon_overrides") or {}) if isinstance(cfg.get("addon_overrides"), dict) else {}
    out = []
    for base in ADDONS_CATALOG_DEFAULTS:
        merged = dict(base)
        ov = overrides.get(base["id"]) or {}
        if "price" in ov:
            try:
                merged["price"] = float(ov["price"])
            except (TypeError, ValueError):
                pass
        out.append(merged)
    return out


@client_router.get("/addons/catalog")
async def addons_catalog(user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1, "addons": 1})
    owned_flags = {a: True for a in ((u or {}).get("addons") or []) if a}
    if (u or {}).get("auto_live_enabled"):
        owned_flags["auto_live"] = True
    catalog = await _load_addons_catalog()
    return {
        "addons": [
            {**a, "owned": bool(owned_flags.get(a["id"]))}
            for a in catalog
        ],
    }


class AddonPurchase(BaseModel):
    addon_id: str


@client_router.post("/addons/purchase")
async def addons_purchase(body: AddonPurchase, user: CurrentUser = Depends(current_user_dep)):
    catalog = await _load_addons_catalog()
    addon = next((a for a in catalog if a["id"] == body.addon_id), None)
    if not addon:
        raise HTTPException(status_code=404, detail="Addon not found")
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1, "addons": 1})
    owned = ((u or {}).get("addons") or [])
    if addon["id"] in owned or ((u or {}).get("auto_live_enabled") and addon["id"] == "auto_live"):
        raise HTTPException(status_code=400, detail="You already own this addon.")
    price = float(addon["price"])
    balance = await _get_user_balance(user.id)
    if balance < price:
        raise HTTPException(status_code=402, detail=f"Not enough balance — needs ${price:.2f}, you have ${balance:.2f}")
    now = datetime.now(timezone.utc).isoformat()
    # Debit + record + unlock in one shot
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id, "username": user.username,
        "amount": -price, "method": "balance", "status": "approved",
        "type": "addon_purchase", "note": f"Addon: {addon['name']}",
        "addon_id": addon["id"],
        "created_at": now, "approved_at": now,
    })
    update = {"$addToSet": {"addons": addon["id"]}}
    if addon["id"] == "auto_live":
        update.setdefault("$set", {})["auto_live_enabled"] = True
    await db.users.update_one({"id": user.id}, update)
    new_balance = await _get_user_balance(user.id)
    return {"ok": True, "balance": new_balance, "addon": addon["id"]}


@client_router.get("/addons/mine")
async def addons_mine(user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1, "addons": 1})
    owned = set((u or {}).get("addons") or [])
    if (u or {}).get("auto_live_enabled"):
        owned.add("auto_live")
    return {"owned": sorted(owned)}


# ============ Admin — edit addon prices ============
@api_router.get("/admin/addons")
async def admin_list_addons(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    return {"addons": await _load_addons_catalog()}


class AdminAddonUpdate(BaseModel):
    price: Optional[float] = Field(None, ge=0, le=1_000_000)


@api_router.patch("/admin/addons/{addon_id}")
async def admin_update_addon(
    addon_id: str,
    payload: AdminAddonUpdate,
    x_admin_token: Optional[str] = Header(None),
):
    check_admin(x_admin_token)
    if not any(a["id"] == addon_id for a in ADDONS_CATALOG_DEFAULTS):
        raise HTTPException(status_code=404, detail="Unknown addon")
    ov_updates = {}
    if payload.price is not None:
        ov_updates[f"addon_overrides.{addon_id}.price"] = float(payload.price)
    if not ov_updates:
        return {"updated": False}
    await db.app_settings.update_one({"_id": "singleton"}, {"$set": ov_updates}, upsert=True)
    return {"updated": True, "addon": (await _load_addons_catalog())}


@client_router.get("/transactions")
async def get_my_transactions(user: CurrentUser = Depends(current_user_dep)):
    items = await db.transactions.find(
        {"user_id": user.id},
        {"_id": 0},
    ).sort("created_at", -1).limit(100).to_list(100)
    return {"transactions": items}


@client_router.get("/invoices")
async def get_my_invoices(user: CurrentUser = Depends(current_user_dep)):
    """User-facing invoice list — deposits & withdrawals with paid/unpaid/cancelled status."""
    cur = db.transactions.find(
        {
            "user_id": user.id,
            "type": {"$in": ["deposit", "withdrawal"]},
        },
        {"_id": 0},
    ).sort("created_at", -1).limit(200)
    items = await cur.to_list(200)
    out = []
    for it in items:
        out.append({
            "id": it.get("id"),
            "amount": it.get("amount"),
            "status": it.get("status", "pending"),
            "method": it.get("method"),
            "type": it.get("type"),
            "created_at": it.get("created_at"),
            "approved_at": it.get("approved_at"),
            "checkout_url": it.get("nowpayments_url") or it.get("selly_url"),
        })
    return {"invoices": out}


@client_router.get("/invoices-unpaid-count")
async def unpaid_invoices_count(user: CurrentUser = Depends(current_user_dep)):
    n = await db.transactions.count_documents({
        "user_id": user.id,
        "type": "deposit",
        "status": "pending",
    })
    return {"unpaid": n}


# ============ Account settings (self-service) ============

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=120)


@client_router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, user: CurrentUser = Depends(current_user_dep)):
    from auth_and_chat import hash_password, verify_password
    doc = await db.users.find_one({"id": user.id}, {"_id": 0, "password_hash": 1})
    if not doc or not verify_password(payload.current_password, doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is wrong")
    await db.users.update_one({"id": user.id}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    return {"ok": True}


class ChangeEmailRequest(BaseModel):
    email: EmailStr
    current_password: str = Field(..., min_length=1, max_length=200)


@client_router.post("/change-email")
async def change_email(payload: ChangeEmailRequest, user: CurrentUser = Depends(current_user_dep)):
    from auth_and_chat import verify_password
    doc = await db.users.find_one({"id": user.id}, {"_id": 0, "password_hash": 1})
    if not doc or not verify_password(payload.current_password, doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Password is wrong")
    email = payload.email.strip().lower()
    # Uniqueness
    if await db.users.find_one({"email": email, "id": {"$ne": user.id}}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=409, detail="Email already in use")
    await db.users.update_one({"id": user.id}, {"$set": {"email": email}})
    return {"ok": True, "email": email}


class ThemePrefRequest(BaseModel):
    theme: str = Field(..., pattern=r"^[a-z0-9\-]{2,32}$")


@client_router.post("/theme-pref")
async def set_theme_pref(payload: ThemePrefRequest, user: CurrentUser = Depends(current_user_dep)):
    await db.users.update_one({"id": user.id}, {"$set": {"theme_pref": payload.theme}})
    return {"ok": True, "theme": payload.theme}


@client_router.get("/theme-pref")
async def get_theme_pref(user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "theme_pref": 1})
    return {"theme": (u or {}).get("theme_pref", "green")}


# ============ Recurring TikTok-Live auto-order subscription ============
# Users pick a TikTok Live service, a TikTok username, a duration (7-365 days),
# and how much of the service to send every time the target goes live.
# A background worker polls every 5 minutes; when TikTok reports the user is live,
# it places an order using the buyer's balance. When offline / balance depleted,
# it skips silently.

# Fixed poll cadence — we check TikTok every 60s so a re-broadcast is picked
# up quickly. The user picks how often to actually place an order.
TIKTOK_CHECK_INTERVAL_SEC = 60          # 1 minute — how often we PING TikTok live-status
TIKTOK_ALLOWED_REPEAT_MINUTES = [2, 5, 10, 60]
LIVE_SUB_ALLOWED_DAYS = [7, 14, 30, 60, 90, 365]


async def _is_tiktok_user_live(tt_username: str) -> bool:
    """Best-effort HTTP check — GET the user's /live page and detect the
    "isLive" JSON marker embedded by TikTok's SSR. Returns False on any error
    (network, blocked, ratelimit). No external service required."""
    handle = tt_username.strip().lstrip("@")
    if not handle:
        return False
    url = f"https://www.tiktok.com/@{handle}/live"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
    except Exception as e:
        logger.debug("[livesub] tiktok check network error for %s: %s", handle, e)
        return False
    if r.status_code >= 400:
        return False
    html = r.text[:200_000]  # cap to guard against very-large responses
    # SSR JSON payload contains liveRoomUserInfo → status: 2 means broadcasting
    if '"status":2' in html and '"liveRoom' in html:
        return True
    # Fallback: presence of an active roomId + isLive-ish signals
    if '"roomId":"' in html and '"userNotLive"' not in html:
        return True
    return False


class LiveSubCreate(BaseModel):
    service_id: int
    tiktok_username: str = Field(..., min_length=1, max_length=80)
    quantity_per_burst: int = Field(..., ge=1, le=1_000_000)
    duration_days: int
    repeat_every_minutes: int = Field(default=5, description="How often to place a new order while the target is live (2, 5, 10 or 60 minutes)")


@client_router.post("/live-sub/create")
async def live_sub_create(body: LiveSubCreate, user: CurrentUser = Depends(current_user_dep)):
    if body.duration_days not in LIVE_SUB_ALLOWED_DAYS:
        raise HTTPException(status_code=400, detail=f"Duration must be one of {LIVE_SUB_ALLOWED_DAYS}")
    if body.repeat_every_minutes not in TIKTOK_ALLOWED_REPEAT_MINUTES:
        raise HTTPException(status_code=400, detail=f"Repeat interval must be one of {TIKTOK_ALLOWED_REPEAT_MINUTES} minutes")
    # Auto-live is gated per-account — an admin has to flip it on before use.
    user_doc = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1})
    if not (user_doc or {}).get("auto_live_enabled"):
        raise HTTPException(status_code=403, detail="Auto-Live subscriptions are disabled for your account. Contact an admin to enable this feature.")
    svc = await db.curated_services.find_one({"service_id": body.service_id, "enabled": True}, {"_id": 0})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not available")
    cat = ((svc.get("category") or "") + " " + (svc.get("name") or "")).lower()
    if "tiktok" not in cat or "live" not in cat:
        raise HTTPException(status_code=400, detail="Auto-recurring is only available for TikTok Live services.")
    smin, smax = int(svc.get("min", 1) or 1), int(svc.get("max", 1_000_000) or 1_000_000)
    if body.quantity_per_burst < smin or body.quantity_per_burst > smax:
        raise HTTPException(status_code=400, detail=f"Quantity must be between {smin} and {smax}")
    rate = float(svc.get("custom_rate", 0))
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Service price not set")
    charge_per_burst = round((rate * body.quantity_per_burst) / 1000.0, 4)
    balance = await _get_user_balance(user.id)
    if balance < charge_per_burst:
        raise HTTPException(status_code=402, detail=f"Need at least ${charge_per_burst:.2f} in balance to start.")
    now = datetime.now(timezone.utc)
    handle = body.tiktok_username.strip().lstrip("@")
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "tiktok_username": handle,
        "service_id": body.service_id,
        "service_name": svc.get("custom_name") or svc.get("name") or "",
        "provider_id": svc.get("provider_id"),
        "quantity_per_burst": body.quantity_per_burst,
        "charge_per_burst": charge_per_burst,
        "duration_days": body.duration_days,
        "repeat_every_minutes": body.repeat_every_minutes,
        "starts_at": now.isoformat(),
        "expires_at": (now + timedelta(days=body.duration_days)).isoformat(),
        "next_check_at": (now + timedelta(seconds=TIKTOK_CHECK_INTERVAL_SEC)).isoformat(),
        "last_check_at": now.isoformat(),
        "last_burst_at": None,
        "status": "active",
        "total_bursts": 0,
        "total_spent": 0.0,
        "created_at": now.isoformat(),
    }
    await db.live_subscriptions.insert_one(doc.copy())

    # Fire the FIRST order immediately (regardless of live status) so the user
    # gets a concrete confirmation the subscription is working. The recurring
    # gate kicks in after this initial burst.
    try:
        resp = await place_smm_order(
            body.service_id,
            f"https://www.tiktok.com/@{handle}/live",
            body.quantity_per_burst,
            provider_id=svc.get("provider_id"),
        )
        smm_order_id = resp.get("order")
        await db.orders.insert_one({
            "id": str(uuid.uuid4()),
            "smm_order_id": smm_order_id,
            "service_id": body.service_id,
            "service_name": svc.get("custom_name") or svc.get("name") or "",
            "link": f"https://www.tiktok.com/@{handle}/live",
            "quantity": body.quantity_per_burst,
            "charge": charge_per_burst,
            "customer_email": "",
            "user_id": user.id,
            "username": user.username,
            "payment_method": "balance",
            "source": "auto_live",
            "status": "Pending",
            "created_at": now.isoformat(),
            "provider_id": svc.get("provider_id"),
            "subscription_id": doc["id"],
        })
        await db.live_subscriptions.update_one(
            {"id": doc["id"]},
            {
                "$set": {"last_burst_at": now.isoformat()},
                "$inc": {"total_bursts": 1, "total_spent": charge_per_burst},
            },
        )
        doc["last_burst_at"] = now.isoformat()
        doc["total_bursts"] = 1
        doc["total_spent"] = charge_per_burst
        first_order_id = smm_order_id
    except Exception as e:
        logger.warning("[livesub] initial burst failed for sub=%s: %s", doc["id"], e)
        first_order_id = None

    doc.pop("_id", None)
    return {"ok": True, "subscription": doc, "first_order_id": first_order_id}


@client_router.get("/live-sub/my")
async def live_sub_my(user: CurrentUser = Depends(current_user_dep)):
    cur = db.live_subscriptions.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(50)
    subs = await cur.to_list(50)
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1})
    return {"subscriptions": subs, "auto_live_enabled": bool((u or {}).get("auto_live_enabled"))}


class AutoLiveToggleReq(BaseModel):
    enabled: bool


@api_router.post("/admin/users/{uid}/auto-live")
async def admin_toggle_auto_live(uid: str, body: AutoLiveToggleReq, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "users")
    r = await db.users.update_one({"id": uid}, {"$set": {"auto_live_enabled": bool(body.enabled)}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "auto_live_enabled": bool(body.enabled)}


@client_router.post("/live-sub/{sid}/cancel")
async def live_sub_cancel(sid: str, user: CurrentUser = Depends(current_user_dep)):
    r = await db.live_subscriptions.update_one(
        {"id": sid, "user_id": user.id, "status": "active"},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found or not active")
    return {"ok": True}


async def _live_sub_worker_loop():
    """Runs forever — picks up active subs whose `next_check_at` has passed,
    checks TikTok, and fires an SMM order burst if the target is live."""
    logger.info("[livesub] background worker started (interval=%ss)", TIKTOK_CHECK_INTERVAL_SEC)
    while True:
        try:
            now = datetime.now(timezone.utc)
            # First: expire subs past their end date
            await db.live_subscriptions.update_many(
                {"status": "active", "expires_at": {"$lt": now.isoformat()}},
                {"$set": {"status": "expired", "ended_at": now.isoformat()}},
            )
            # Then: due for a burst
            due = await db.live_subscriptions.find(
                {"status": "active", "next_check_at": {"$lte": now.isoformat()}},
                {"_id": 0},
            ).limit(100).to_list(100)
            for sub in due:
                try:
                    await _process_live_sub_burst(sub)
                except Exception as e:
                    logger.exception("[livesub] burst failed for sub=%s: %s", sub.get("id"), e)
        except Exception as e:
            logger.exception("[livesub] worker loop error: %s", e)
        await asyncio.sleep(30)  # loop wakes every 30s; per-sub gate is `next_check_at` (default 60s)


async def _process_live_sub_burst(sub: dict):
    """Called every 60s while the sub is active. Ping TikTok; if the target
    is currently live AND at least `repeat_every_minutes` have passed since the
    last burst, fire one order. Otherwise reschedule the next check for
    another 60 seconds."""
    now = datetime.now(timezone.utc)
    # Always record this check + schedule the NEXT poll 60s from now. The
    # scheduling happens up-front so no matter what path we take below, the
    # sub always advances forward.
    default_next = (now + timedelta(seconds=TIKTOK_CHECK_INTERVAL_SEC)).isoformat()
    await db.live_subscriptions.update_one(
        {"id": sub["id"]},
        {"$set": {"last_check_at": now.isoformat(), "next_check_at": default_next}},
    )
    repeat_every_sec = int(sub.get("repeat_every_minutes") or 5) * 60
    is_live = await _is_tiktok_user_live(sub["tiktok_username"])
    if not is_live:
        # Offline — nothing to do. Next tick in 60s. If they restart, we pick up automatically.
        return
    # Live — respect the user-selected repeat gate so we don't spam
    last_burst_iso = sub.get("last_burst_at")
    if last_burst_iso:
        try:
            last_burst = datetime.fromisoformat(last_burst_iso.replace("Z", "+00:00"))
            elapsed = (now - last_burst).total_seconds()
        except Exception:
            elapsed = repeat_every_sec + 1
        if elapsed < repeat_every_sec:
            logger.info(
                "[livesub] sub %s live, %ss/%ss since last burst — waiting",
                sub["id"], int(elapsed), repeat_every_sec,
            )
            return
    # Cleared the repeat gate. Fire an order.
    balance = await _get_user_balance(sub["user_id"])
    charge = float(sub.get("charge_per_burst") or 0)
    if balance < charge:
        # Pause the sub — user will re-fund and can resume by creating a new one
        await db.live_subscriptions.update_one(
            {"id": sub["id"]}, {"$set": {"status": "paused", "paused_reason": "insufficient_balance", "paused_at": now.isoformat()}}
        )
        logger.info("[livesub] sub %s paused — user balance too low", sub["id"])
        return
    link = f"https://www.tiktok.com/@{sub['tiktok_username']}/live"
    try:
        resp = await place_smm_order(sub["service_id"], link, int(sub["quantity_per_burst"]), provider_id=sub.get("provider_id"))
    except Exception as e:
        logger.warning("[livesub] provider order failed for sub=%s: %s", sub["id"], e)
        return
    if not resp.get("order"):
        logger.warning("[livesub] provider returned no order id for sub=%s: %s", sub["id"], str(resp)[:150])
        return
    # Charge the buyer + persist an order row so their history is accurate
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": sub["user_id"], "username": sub["username"],
        "amount": -charge, "method": "balance", "status": "approved",
        "type": "live_sub_burst", "note": f"Live burst @{sub['tiktok_username']} — {sub['quantity_per_burst']}",
        "live_sub_id": sub["id"], "created_at": now.isoformat(), "approved_at": now.isoformat(),
    })
    await db.orders.insert_one({
        "id": str(uuid.uuid4()),
        "smm_order_id": resp.get("order"),
        "service_id": sub["service_id"],
        "service_name": sub.get("service_name"),
        "link": link,
        "quantity": int(sub["quantity_per_burst"]),
        "charge": charge,
        "user_id": sub["user_id"],
        "username": sub["username"],
        "payment_method": "balance",
        "source": "live_sub",
        "live_sub_id": sub["id"],
        "status": "Pending",
        "created_at": now.isoformat(),
        "provider_id": sub.get("provider_id"),
    })
    await db.live_subscriptions.update_one(
        {"id": sub["id"]},
        {
            "$set": {
                "last_burst_at": now.isoformat(),
                # Next poll happens in 60 seconds regardless — the per-sub
                # repeat gate above guards the actual ordering cadence.
                "next_check_at": (now + timedelta(seconds=TIKTOK_CHECK_INTERVAL_SEC)).isoformat(),
            },
            "$inc": {"total_bursts": 1, "total_spent": charge},
        },
    )
    # Announce to the public chat as a discreet system message (username masked,
    # never reveals the buyer). The dashboard polls public-chat, so all users
    # see a small live indicator on the sidebar — cheap social-proof signal.
    # We announce on the FIRST worker-triggered burst per sub (i.e. the first
    # time the target has been detected live after the sub was created).
    try:
        masked_buyer = _mask_username(sub.get("username") or "")
        # `sub` was fetched BEFORE this burst's increment. total_bursts == 1
        # means the create-time initial burst has already happened but this
        # is the first live-detected refill.
        already_announced = bool(sub.get("live_notified"))
        if not already_announced:
            await db.public_chat.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": None,
                "username": "BetterSocial",
                "role": "system",
                "text": f"🔴 A creator just went live — @{masked_buyer} boosted them automatically",
                "kind": "live_notify",
                "created_at": now.isoformat(),
            })
            await db.live_subscriptions.update_one({"id": sub["id"]}, {"$set": {"live_notified": True}})
    except Exception:
        pass
    logger.info("[livesub] burst OK sub=%s @%s qty=%s order=%s", sub["id"], sub["tiktok_username"], sub["quantity_per_burst"], resp.get("order"))


@app.on_event("startup")
async def _start_live_sub_worker():
    # Fire-and-forget; the loop catches its own errors and reschedules.
    asyncio.create_task(_live_sub_worker_loop())
    # Sports goal watcher — polls the RapidAPI livescore feed and emits events.
    asyncio.create_task(_sports_watcher_loop())


# ============ Realtime user commands ============
# Client polls this every ~3s; picks up admin commands (kick / redirect).
@client_router.get("/live-poll")
async def client_live_poll(user: CurrentUser = Depends(current_user_dep)):
    # Fetch the most-recent unconsumed command for this user (if any)
    cmd = await db.live_commands.find_one(
        {"user_id": user.id, "consumed_at": None},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if cmd:
        await db.live_commands.update_one(
            {"id": cmd["id"]},
            {"$set": {"consumed_at": datetime.now(timezone.utc).isoformat()}},
        )
    return {"command": cmd, "banned": False}


# ============ Admin user actions (kick / ban / redirect / drill-down) ============

class RedirectRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=200)


async def _push_live_cmd(user_id: str, cmd: str, payload: dict | None = None) -> None:
    await db.live_commands.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "cmd": cmd,
        "payload": payload or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "consumed_at": None,
    })


@api_router.post("/admin/users/{uid}/kick")
async def admin_kick_user(uid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "users")
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "username": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    import time as _t
    await db.users.update_one({"id": uid}, {"$set": {"session_epoch": int(_t.time())}})
    await _push_live_cmd(uid, "kick", {"reason": "logged out by admin"})
    return {"ok": True, "username": doc["username"]}


@api_router.post("/admin/users/{uid}/ban")
async def admin_ban_user(uid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "users")
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "username": 1, "role": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    if doc.get("role") == "owner":
        raise HTTPException(status_code=400, detail="Cannot ban the owner")
    import time as _t
    await db.users.update_one(
        {"id": uid},
        {"$set": {"banned": True, "banned_at": datetime.now(timezone.utc).isoformat(), "session_epoch": int(_t.time())}},
    )
    await _push_live_cmd(uid, "ban", {"reason": "banned by admin"})
    return {"ok": True, "username": doc["username"]}


@api_router.post("/admin/users/{uid}/unban")
async def admin_unban_user(uid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "users")
    r = await db.users.update_one({"id": uid}, {"$set": {"banned": False}, "$unset": {"banned_at": ""}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@api_router.post("/admin/users/{uid}/redirect")
async def admin_redirect_user(uid: str, payload: RedirectRequest, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "users")
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "username": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    await _push_live_cmd(uid, "redirect", {"path": payload.path.strip()})
    return {"ok": True, "path": payload.path, "username": doc["username"]}


@api_router.post("/admin/broadcast/redirect")
async def admin_redirect_all(payload: RedirectRequest, x_admin_token: Optional[str] = Header(None)):
    """Push a redirect command to EVERY non-owner user online. Great for launches."""
    check_admin(x_admin_token, "users")
    threshold = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    users = await db.users.find(
        {"role": {"$nin": ["owner", "system"]}, "last_seen": {"$gte": threshold}},
        {"_id": 0, "id": 1},
    ).to_list(None)
    docs = [{
        "id": str(uuid.uuid4()),
        "user_id": u["id"],
        "cmd": "redirect",
        "payload": {"path": payload.path.strip()},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "consumed_at": None,
    } for u in users]
    if docs:
        await db.live_commands.insert_many(docs)
    return {"ok": True, "sent": len(docs)}


@api_router.get("/admin/users/{uid}/orders")
async def admin_user_orders(uid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "orders")
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "username": 1, "email": 1, "role": 1, "banned": 1, "created_at": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    orders = await db.orders.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    txns = await db.transactions.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    # Aggregate status counts
    status_counts = {}
    for o in orders:
        s = str(o.get("status", "Pending"))
        status_counts[s] = status_counts.get(s, 0) + 1
    return {
        "user": doc,
        "orders": orders,
        "transactions": txns,
        "status_counts": status_counts,
        "total_spent": round(sum(-t["amount"] for t in txns if float(t.get("amount", 0)) < 0 and t.get("type") in ("order", "bulk_order", "slot_bet", "stairs_stake", "aviator_stake", "spin_stake")), 2),
        "total_deposits": round(sum(t["amount"] for t in txns if t.get("type") == "deposit" and t.get("status") == "approved"), 2),
    }


class CasinoSpinRequest(BaseModel):
    stake: float = Field(..., ge=1, le=100)


# Multiplier weight table (weight is per 100,000 rolls)
# Total weight = 100,000. RTP ≈ 91% (9% house edge).
CASINO_TABLE = [
    (0.0, 92000),     # 92.000% — lose
    (0.5, 4000),      #  4.000% — half back
    (2.0, 2500),      #  2.500%
    (5.0, 900),       #  0.900%
    (10.0, 400),      #  0.400%
    (50.0, 150),      #  0.150%
    (100.0, 30),      #  0.030%
    (1000.0, 15),     #  0.015%
    (10000.0, 5),     #  0.005% — JACKPOT
]
CASINO_TOTAL_WEIGHT = sum(w for _, w in CASINO_TABLE)


def _roll_multiplier() -> float:
    """Cryptographically secure RNG drawing from CASINO_TABLE."""
    pick = secrets.randbelow(CASINO_TOTAL_WEIGHT)
    cum = 0
    for mult, w in CASINO_TABLE:
        cum += w
        if pick < cum:
            return mult
    return 0.0


@client_router.post("/casino/spin")
async def casino_spin(body: CasinoSpinRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Try Chance — bet 1-100 USD from balance, win up to 10,000x."""
    db_: AsyncIOMotorDatabase = request.app.state.db
    stake = round(float(body.stake), 2)
    balance = await _get_user_balance(user.id)
    if balance < stake:
        raise HTTPException(status_code=402, detail=f"Not enough balance — need ${stake:.2f}, you have ${balance:.2f}")

    roll_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    multiplier = _roll_multiplier()
    win_amount = round(stake * multiplier, 4)

    # Debit stake
    await db_.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": -stake,
        "method": "casino",
        "status": "approved",
        "type": "casino_bet",
        "roll_id": roll_id,
        "multiplier": multiplier,
        "created_at": now,
        "approved_at": now,
    })
    # Credit win (if any)
    if win_amount > 0:
        await db_.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "username": user.username,
            "amount": win_amount,
            "method": "casino",
            "status": "approved",
            "type": "casino_win",
            "roll_id": roll_id,
            "multiplier": multiplier,
            "created_at": now,
            "approved_at": now,
        })
        # Add to withdrawable bucket
        await db_.users.update_one(
            {"id": user.id},
            {"$inc": {"withdrawable_balance": win_amount}},
        )

    # Log into casino_rolls for admin / history
    await db_.casino_rolls.insert_one({
        "id": roll_id,
        "user_id": user.id,
        "username": user.username,
        "stake": stake,
        "multiplier": multiplier,
        "win": win_amount,
        "net": round(win_amount - stake, 4),
        "created_at": now,
    })

    new_balance = await _get_user_balance(user.id)
    new_withdrawable = await _get_user_withdrawable(user.id)
    return {
        "roll_id": roll_id,
        "multiplier": multiplier,
        "stake": stake,
        "win": win_amount,
        "net": round(win_amount - stake, 4),
        "balance": new_balance,
        "withdrawable": new_withdrawable,
    }


@client_router.get("/casino/history")
async def casino_history(user: CurrentUser = Depends(current_user_dep), request: Request = None):
    db_: AsyncIOMotorDatabase = request.app.state.db
    items = await db_.casino_rolls.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(30).to_list(30)
    return {"rolls": items}


# ============ WITHDRAWALS ============

class WithdrawRequest(BaseModel):
    amount: float = Field(..., ge=10, le=100000)
    currency: str = Field(..., pattern=r"^(BTC|USDT|USDT_TRC20|USDT_ERC20)$")
    address: str = Field(..., min_length=10, max_length=200)


@client_router.post("/withdraw")
async def request_withdrawal(body: WithdrawRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Create a pending withdrawal. Reserves the amount from withdrawable + balance immediately."""
    db_: AsyncIOMotorDatabase = request.app.state.db
    amount = round(float(body.amount), 2)

    # Check withdrawable bucket
    withdrawable = await _get_user_withdrawable(user.id)
    if amount > withdrawable:
        raise HTTPException(
            status_code=400,
            detail=f"You can only withdraw winnings (${withdrawable:.2f} available). Deposited funds cannot be withdrawn.",
        )
    # Sanity: ensure total balance can cover it
    balance = await _get_user_balance(user.id)
    if amount > balance:
        raise HTTPException(status_code=400, detail=f"Insufficient total balance (${balance:.2f}).")

    # Decrement withdrawable bucket immediately
    res = await db_.users.update_one(
        {"id": user.id, "withdrawable_balance": {"$gte": amount}},
        {"$inc": {"withdrawable_balance": -amount}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Withdrawable balance changed — try again.")

    now = datetime.now(timezone.utc).isoformat()
    wid = str(uuid.uuid4())
    # Pending transaction (negative — reserves the balance)
    await db_.transactions.insert_one({
        "id": wid,
        "user_id": user.id,
        "username": user.username,
        "amount": -amount,
        "method": "withdrawal",
        "status": "pending",
        "type": "withdrawal",
        "currency": body.currency,
        "address": body.address.strip(),
        "created_at": now,
    })
    return {"ok": True, "id": wid, "amount": amount, "status": "pending"}


@client_router.get("/withdrawals")
async def list_my_withdrawals(user: CurrentUser = Depends(current_user_dep), request: Request = None):
    db_: AsyncIOMotorDatabase = request.app.state.db
    items = await db_.transactions.find(
        {"user_id": user.id, "type": "withdrawal"},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return {"withdrawals": items}


@api_router.get("/admin/withdrawals")
async def admin_list_withdrawals(x_admin_token: Optional[str] = Header(None), status: Optional[str] = None):
    check_admin(x_admin_token, "withdrawals")
    q = {"type": "withdrawal"}
    if status:
        q["status"] = status
    items = await db.transactions.find(q, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    return {"withdrawals": items}


class WithdrawDecision(BaseModel):
    tx_hash: Optional[str] = None
    note: Optional[str] = None


@api_router.post("/admin/withdrawals/{tx_id}/approve")
async def admin_approve_withdrawal(tx_id: str, body: WithdrawDecision, x_admin_token: Optional[str] = Header(None)):
    """Mark withdrawal as approved. Money already reserved; this finalises the debit."""
    check_admin(x_admin_token, "withdrawals")
    now = datetime.now(timezone.utc).isoformat()
    res = await db.transactions.find_one_and_update(
        {"id": tx_id, "type": "withdrawal", "status": "pending"},
        {"$set": {
            "status": "approved",
            "approved_at": now,
            "tx_hash": (body.tx_hash or "").strip() or None,
            "admin_note": body.note,
        }},
        return_document=True,
    )
    if not res:
        raise HTTPException(status_code=404, detail="Pending withdrawal not found")
    return {"ok": True}


@api_router.post("/admin/withdrawals/{tx_id}/reject")
async def admin_reject_withdrawal(tx_id: str, body: WithdrawDecision, x_admin_token: Optional[str] = Header(None)):
    """Reject withdrawal. Refunds withdrawable bucket."""
    check_admin(x_admin_token, "withdrawals")
    now = datetime.now(timezone.utc).isoformat()
    tx = await db.transactions.find_one_and_update(
        {"id": tx_id, "type": "withdrawal", "status": "pending"},
        {"$set": {
            "status": "rejected",
            "rejected_at": now,
            "admin_note": body.note,
        }},
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Pending withdrawal not found")
    # Refund withdrawable bucket
    refund_amount = abs(float(tx.get("amount", 0)))
    if refund_amount > 0 and tx.get("user_id"):
        await db.users.update_one(
            {"id": tx["user_id"]},
            {"$inc": {"withdrawable_balance": refund_amount}},
        )
    return {"ok": True, "refunded": refund_amount}


class FundRequest(BaseModel):
    amount: float = Field(..., gt=0, le=10000)
    method: str = Field(default="paypal")  # paypal | crypto


@client_router.post("/funds/request")
async def request_funds(body: FundRequest, user: CurrentUser = Depends(current_user_dep)):
    """User claims they've sent payment. Admin must approve."""
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": round(float(body.amount), 2),
        "method": body.method,
        "status": "pending",  # pending | approved | rejected
        "type": "deposit",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.transactions.insert_one(doc.copy())
    return {"ok": True, "id": doc["id"], "status": "pending"}


# ============ NOWPAYMENTS (Crypto — no KYC) ============

NOWPAYMENTS_API_BASE = "https://api.nowpayments.io/v1"


async def _get_nowpayments_config() -> dict:
    cfg = await db.nowpayments_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    if not cfg.get("api_key"):
        raise HTTPException(status_code=503, detail="NOWPayments not configured — admin must add API key in Settings")
    return cfg


async def _create_nowpayments_invoice(amount_usd: float, order_id: str, description: str, ipn_url: str, success_url: str, cancel_url: str) -> dict:
    """Create a hosted NOWPayments invoice and return {invoice_id, invoice_url}."""
    cfg = await _get_nowpayments_config()
    payload = {
        "price_amount": round(float(amount_usd), 2),
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": description[:200],
        "ipn_callback_url": ipn_url,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            f"{NOWPAYMENTS_API_BASE}/invoice",
            json=payload,
            headers={"x-api-key": cfg["api_key"], "Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"NOWPayments {r.status_code}: {r.text[:300]}")
        data = r.json()
    if not data.get("invoice_url"):
        raise HTTPException(status_code=502, detail=f"NOWPayments — no invoice_url: {str(data)[:200]}")
    return {"invoice_id": str(data.get("id")), "invoice_url": data["invoice_url"]}


def _verify_nowpayments_signature(body_bytes: bytes, ipn_secret: str, signature: str) -> bool:
    """HMAC-SHA512 verification of NOWPayments webhook.
    NOWPayments sorts the JSON body keys alphabetically before signing."""
    import hmac, hashlib
    try:
        data = jsonlib.loads(body_bytes.decode("utf-8"))
        sorted_json = jsonlib.dumps(data, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(ipn_secret.encode(), sorted_json.encode(), hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, (signature or "").lower())
    except Exception:
        return False


class NowpaymentsConfig(BaseModel):
    api_key: str = Field(..., min_length=10, max_length=200)
    ipn_secret: Optional[str] = ""


@api_router.get("/admin/nowpayments-config")
async def admin_get_nowpayments_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.nowpayments_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    key = cfg.get("api_key", "")
    return {
        "configured": bool(key),
        "api_key_masked": ("*" * 6 + key[-6:]) if key else "",
        "ipn_secret_set": bool(cfg.get("ipn_secret")),
    }


@api_router.post("/admin/nowpayments-config")
async def admin_set_nowpayments_config(payload: NowpaymentsConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    upd = {"api_key": payload.api_key.strip(), "updated_at": datetime.now(timezone.utc).isoformat()}
    if payload.ipn_secret:
        upd["ipn_secret"] = payload.ipn_secret.strip()
    await db.nowpayments_config.update_one({"_id": "singleton"}, {"$set": upd}, upsert=True)
    return {"configured": True}


# ============ Public group chat (shoutbox) ============

class PublicChatMessage(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


@api_router.post("/public-chat/send")
async def public_chat_send(payload: PublicChatMessage, user: CurrentUser = Depends(current_user_dep)):
    """Post a message to the public shoutbox. Rate-limited to 1 msg / 3 s per user.
    Also supports admin/owner slash commands (/ban, /mute, /unmute, /unban, /clear)."""
    text = payload.text.strip()[:500]

    # ---- Mute enforcement (skip system messages / commands) ----
    user_doc = await db.users.find_one({"id": user.id}, {"_id": 0, "muted_until": 1, "role": 1})
    muted_until_raw = (user_doc or {}).get("muted_until")
    if muted_until_raw:
        try:
            mu = datetime.fromisoformat(muted_until_raw)
            if mu.tzinfo is None:
                mu = mu.replace(tzinfo=timezone.utc)
            if mu > datetime.now(timezone.utc):
                remaining = int((mu - datetime.now(timezone.utc)).total_seconds())
                raise HTTPException(status_code=403, detail=f"You're muted — {remaining}s remaining.")
        except HTTPException:
            raise
        except Exception:
            pass

    # ---- Slash commands (owner/admin only) ----
    role = (user_doc or {}).get("role", user.role or "user")
    if text.startswith("/") and role in ("owner", "admin"):
        parts = text.split(maxsplit=3)
        cmd = parts[0].lower()

        async def _find_target(uname: str):
            return await db.users.find_one(
                {"$or": [
                    {"username_lower": uname.lower()},
                    {"username": {"$regex": f"^{re.escape(uname)}$", "$options": "i"}},
                ]},
                {"_id": 0, "id": 1, "username": 1, "role": 1},
            )

        if cmd == "/clear":
            r = await db.public_chat.delete_many({})
            await db.public_chat.insert_one({
                "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
                "role": role, "text": f"🧹 Chat cleared by @{user.username} ({r.deleted_count} messages)",
                "kind": "system", "created_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"ok": True, "command": "clear", "deleted": r.deleted_count}

        if cmd in ("/ban", "/unban", "/mute", "/unmute"):
            if len(parts) < 2:
                raise HTTPException(status_code=400, detail=f"Usage: {cmd} <username>")
            uname = parts[1].lstrip("@")
            target = await _find_target(uname)
            if not target:
                raise HTTPException(status_code=404, detail=f"User @{uname} not found")
            if target.get("role") == "owner":
                raise HTTPException(status_code=400, detail="Can't moderate the owner")
            tid = target["id"]
            now_iso = datetime.now(timezone.utc).isoformat()

            if cmd == "/ban":
                import time as _t
                await db.users.update_one({"id": tid}, {"$set": {"banned": True, "banned_at": now_iso, "session_epoch": int(_t.time())}})
                await db.public_chat.delete_many({"user_id": tid})
                await db.live_commands.insert_one({"id": str(uuid.uuid4()), "user_id": tid, "cmd": "ban", "payload": {"reason": "perma ban"}, "created_at": now_iso, "consumed_at": None})
                await db.public_chat.insert_one({"id": str(uuid.uuid4()), "user_id": user.id, "username": user.username, "role": role, "text": f"🔨 @{target['username']} — perma ban", "kind": "system", "created_at": now_iso})
                return {"ok": True, "command": "ban", "target": target["username"]}
            if cmd == "/unban":
                await db.users.update_one({"id": tid}, {"$set": {"banned": False}, "$unset": {"banned_at": ""}})
                await db.public_chat.insert_one({"id": str(uuid.uuid4()), "user_id": user.id, "username": user.username, "role": role, "text": f"✅ @{target['username']} un-banned", "kind": "system", "created_at": now_iso})
                return {"ok": True, "command": "unban", "target": target["username"]}
            if cmd == "/unmute":
                await db.users.update_one({"id": tid}, {"$set": {"muted_until": None}})
                await db.public_chat.insert_one({"id": str(uuid.uuid4()), "user_id": user.id, "username": user.username, "role": role, "text": f"🔊 @{target['username']} un-muted", "kind": "system", "created_at": now_iso})
                return {"ok": True, "command": "unmute", "target": target["username"]}
            # /mute <user> <duration> [reason]
            if len(parts) < 3:
                raise HTTPException(status_code=400, detail="Usage: /mute <username> <1min|1h|1d> [reason]")
            dur = parts[2].lower().strip()
            reason = parts[3] if len(parts) >= 4 else ""
            secs_map = {"1min": 60, "5min": 300, "10min": 600, "30min": 1800, "1h": 3600, "6h": 21600, "12h": 43200, "1d": 86400, "7d": 604800}
            if dur not in secs_map:
                raise HTTPException(status_code=400, detail=f"Duration must be one of {list(secs_map)}")
            secs = secs_map[dur]
            until = datetime.now(timezone.utc) + timedelta(seconds=secs)
            await db.users.update_one({"id": tid}, {"$set": {"muted_until": until.isoformat()}})
            await db.public_chat.insert_one({
                "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username, "role": role,
                "text": f"🔇 @{target['username']} muted for {dur}" + (f" — {reason}" if reason else ""),
                "kind": "system", "created_at": now_iso,
            })
            return {"ok": True, "command": "mute", "target": target["username"], "duration": dur, "expires": until.isoformat()}
        # Unknown command starting with / — let it fall through and post as a normal msg

    # ---- Normal rate-limit + insert ----
    last = await db.public_chat.find_one(
        {"user_id": user.id, "kind": {"$ne": "tip"}},
        sort=[("created_at", -1)],
        projection={"created_at": 1},
    )
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < 3:
                raise HTTPException(status_code=429, detail="Slow down — you can post again in a moment.")
        except HTTPException:
            raise
        except Exception:
            pass
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "role": role,
        "text": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.public_chat.insert_one(doc.copy())
    if (await db.public_chat.estimated_document_count()) > 600:
        cutoff = await db.public_chat.find({}, {"_id": 0, "created_at": 1}).sort("created_at", -1).skip(500).limit(1).to_list(1)
        if cutoff:
            await db.public_chat.delete_many({"created_at": {"$lt": cutoff[0]["created_at"]}})
    return {"ok": True, "id": doc["id"], "created_at": doc["created_at"]}


@api_router.get("/public-chat/messages")
async def public_chat_list(since: Optional[str] = None, limit: int = 50):
    """List latest N messages of the public shoutbox, or messages since <ts> for polling.
    No auth required — anyone with a browser can read the room."""
    q: dict = {}
    if since:
        q["created_at"] = {"$gt": since}
    cursor = db.public_chat.find(q, {"_id": 0}).sort("created_at", -1 if not since else 1).limit(min(int(limit or 50), 200))
    msgs = await cursor.to_list(200)
    if not since:
        msgs.reverse()  # oldest first for initial paint
    # Enrich each message with the sender's chat rank (cached per user for this call)
    rank_cache: dict = {}
    for m in msgs:
        uid = m.get("user_id")
        if uid and uid not in rank_cache:
            rank_cache[uid] = _rank_from_amount(await _user_deposits_total(uid))
        r = rank_cache.get(uid) or _rank_from_amount(0)
        m["rank_name"] = r["name"]
        m["rank_text_class"] = r["text_class"]
        m["rank_border_class"] = r["border_class"]
    return {"messages": msgs}


@api_router.get("/orders/global")
async def orders_global_feed(limit: int = 20):
    """Public live-orders ticker — recent orders with the username masked.
    No auth required — anyone can see activity."""
    cursor = db.orders.find(
        {},
        {"_id": 0, "id": 1, "service_name": 1, "quantity": 1, "charge": 1, "username": 1, "created_at": 1, "status": 1},
    ).sort("created_at", -1).limit(min(int(limit or 20), 50))
    orders = await cursor.to_list(50)
    for o in orders:
        u = str(o.get("username", "") or "")
        # Mask username: first 2 chars + ***
        if u:
            o["masked_username"] = (u[:2] + "***") if len(u) > 2 else "u***"
        o.pop("username", None)
    return {"orders": orders}



# ============ Chat ranks (based on lifetime approved deposits) ============

RANK_TIERS = [
    (0,     "Rookie",  "text-white/70",       "border-white/20 bg-white/5"),
    (10,    "Regular", "text-sky-300",        "border-sky-500/30 bg-sky-500/10"),
    (50,    "VIP",     "text-emerald-300",    "border-emerald-500/40 bg-emerald-500/15"),
    (200,   "Elite",   "text-purple-300",     "border-purple-500/40 bg-purple-500/15"),
    (500,   "Legend",  "text-amber-300",      "border-amber-500/40 bg-amber-500/15"),
]


async def _user_deposits_total(user_id: str) -> float:
    """Sum of approved deposit amounts (real deposits — funds + bonuses)."""
    cur = db.transactions.aggregate([
        {"$match": {"user_id": user_id, "status": "approved",
                    "type": {"$in": ["deposit", "deposit_bonus", "coupon"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ])
    doc = await cur.to_list(1)
    return float(doc[0]["total"]) if doc else 0.0


def _rank_from_amount(amount: float) -> dict:
    tier = RANK_TIERS[0]
    for t in RANK_TIERS:
        if amount >= t[0]:
            tier = t
    return {"name": tier[1], "text_class": tier[2], "border_class": tier[3], "min_deposit": tier[0]}


async def _get_user_rank(user_id: str) -> dict:
    return _rank_from_amount(await _user_deposits_total(user_id))


# Attach rank + total to each public-chat message so the frontend can render badges.
# Also expose /api/me/rank so users can see their own rank + next-tier progress.

@api_router.get("/me/rank")
async def get_my_rank(user: CurrentUser = Depends(current_user_dep)):
    total = await _user_deposits_total(user.id)
    rank = _rank_from_amount(total)
    # Next tier
    nxt = next((t for t in RANK_TIERS if t[0] > total), None)
    return {
        "rank": rank["name"],
        "text_class": rank["text_class"],
        "border_class": rank["border_class"],
        "total_deposits": round(total, 2),
        "next_tier": {"name": nxt[1], "min_deposit": nxt[0]} if nxt else None,
    }


# ============ Tips (in-chat user-to-user tips) ============

class TipRequest(BaseModel):
    to_user_id: str
    amount: float = Field(..., ge=0.5, le=500)
    note: Optional[str] = None


@api_router.post("/tips/send")
async def send_tip(payload: TipRequest, user: CurrentUser = Depends(current_user_dep)):
    """Send a tip to another user. Announces publicly in the shoutbox."""
    if payload.to_user_id == user.id:
        raise HTTPException(status_code=400, detail="Can't tip yourself")
    recipient = await db.users.find_one({"id": payload.to_user_id}, {"_id": 0, "id": 1, "username": 1})
    if not recipient:
        raise HTTPException(status_code=404, detail="User not found")
    amount = round(float(payload.amount), 2)
    sender_balance = await _get_user_balance(user.id)
    if sender_balance < amount:
        raise HTTPException(status_code=400, detail=f"Not enough balance — you have ${sender_balance:.2f}")
    now = datetime.now(timezone.utc).isoformat()
    tip_id = str(uuid.uuid4())
    # Sender debit
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": -amount,
        "method": "tip",
        "status": "approved",
        "type": "tip_out",
        "note": f"Tip to @{recipient['username']}",
        "linked_user_id": recipient["id"],
        "tip_id": tip_id,
        "created_at": now,
    })
    # Recipient credit
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": recipient["id"],
        "username": recipient["username"],
        "amount": amount,
        "method": "tip",
        "status": "approved",
        "type": "tip_in",
        "note": f"Tip from @{user.username}",
        "linked_user_id": user.id,
        "tip_id": tip_id,
        "created_at": now,
    })
    # Public announcement in shoutbox
    announce_text = f"tipped @{recipient['username']} ${amount:.2f}"
    if payload.note:
        announce_text += f" — “{payload.note[:120]}”"
    await db.public_chat.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "role": user.role or "user",
        "text": announce_text,
        "kind": "tip",
        "tip_amount": amount,
        "tip_to_username": recipient["username"],
        "created_at": now,
    })
    # System DM to recipient from "BetterSocial" so they get a Messages inbox ping.
    system_bot = await _get_or_create_system_bot()
    dm_text = f"🎁 Gift from user @{user.username} : ${amount:.2f}"
    if payload.note:
        dm_text += f"\nNote: “{payload.note[:120]}”"
    from messaging import _pair_key  # local import — messaging is already loaded at this point
    await db.direct_messages.insert_one({
        "id": str(uuid.uuid4()),
        "thread_key": _pair_key(system_bot["id"], recipient["id"]),
        "from_id": system_bot["id"],
        "from_username": system_bot["username"],
        "to_id": recipient["id"],
        "text": dm_text,
        "kind": "tip_notification",
        "tip_id": tip_id,
        "created_at": now,
        "read": False,
    })
    return {"ok": True, "amount": amount, "recipient": recipient["username"], "tip_id": tip_id}


async def _get_or_create_system_bot() -> dict:
    """Return the BetterSocial system user, creating a lightweight placeholder if it doesn't exist.
    Used as the sender for automated DMs (tip notifications, welcome messages, etc.)."""
    bot = await db.users.find_one({"username": "BetterSocial"}, {"_id": 0, "id": 1, "username": 1})
    if bot:
        return bot
    bot_doc = {
        "id": str(uuid.uuid4()),
        "username": "BetterSocial",
        "email": "system@bettersocial.local",
        "role": "system",
        "password_hash": "!disabled",  # cannot log in
        "created_at": datetime.now(timezone.utc).isoformat(),
        "balance": 0.0,
        "display_name": "BetterSocial",
        "is_system": True,
    }
    await db.users.insert_one(bot_doc.copy())
    return {"id": bot_doc["id"], "username": "BetterSocial"}


# ============ Admin — DM any user from BetterSocial ============

class AdminDmRequest(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=4000)


@api_router.post("/admin/messages/send")
async def admin_send_dm(payload: AdminDmRequest, x_admin_token: Optional[str] = Header(None)):
    """Send a DM from the BetterSocial system account to any user.
    The recipient sees it as a normal DM in their Friends inbox, from @BetterSocial."""
    check_admin(x_admin_token, "users")
    if not payload.user_id and not payload.username:
        raise HTTPException(status_code=400, detail="Provide user_id or username")
    q = {"id": payload.user_id} if payload.user_id else {"username_lower": (payload.username or "").strip().lower()}
    recipient = await db.users.find_one(q, {"_id": 0, "id": 1, "username": 1})
    if not recipient:
        # Fallback: case-insensitive username scan
        if payload.username:
            recipient = await db.users.find_one(
                {"username": {"$regex": f"^{re.escape(payload.username.strip())}$", "$options": "i"}},
                {"_id": 0, "id": 1, "username": 1},
            )
    if not recipient:
        raise HTTPException(status_code=404, detail="User not found")
    if recipient.get("role") == "system" or recipient["username"] == "BetterSocial":
        raise HTTPException(status_code=400, detail="Can't message the system account")
    bot = await _get_or_create_system_bot()
    from messaging import _pair_key  # local import to avoid circular
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "thread_key": _pair_key(bot["id"], recipient["id"]),
        "from_id": bot["id"],
        "from_username": bot["username"],
        "to_id": recipient["id"],
        "to_username": recipient["username"],
        "text": payload.text.strip()[:4000],
        "kind": "admin_broadcast",
        "created_at": now,
        "read": False,
    }
    await db.direct_messages.insert_one(doc.copy())
    return {"ok": True, "recipient": recipient["username"], "message_id": doc["id"]}


@api_router.post("/admin/messages/send-bulk")
async def admin_send_dm_bulk(
    payload: dict = Body(...),
    x_admin_token: Optional[str] = Header(None),
):
    """Broadcast to many users at once. Body: { user_ids: [...], text: '...' } or
    { all: true, text: '...' } to hit every non-system user."""
    check_admin(x_admin_token, "users")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="Text too long (max 4000 chars)")
    if payload.get("all"):
        cursor = db.users.find(
            {"role": {"$ne": "system"}, "username": {"$ne": "BetterSocial"}},
            {"_id": 0, "id": 1, "username": 1},
        )
        recipients = await cursor.to_list(None)
    else:
        ids = payload.get("user_ids") or []
        if not isinstance(ids, list) or not ids:
            raise HTTPException(status_code=400, detail="Provide user_ids or set all=true")
        cursor = db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "username": 1, "role": 1})
        recipients = [r for r in await cursor.to_list(None) if r.get("role") != "system"]
    bot = await _get_or_create_system_bot()
    from messaging import _pair_key
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for r in recipients:
        docs.append({
            "id": str(uuid.uuid4()),
            "thread_key": _pair_key(bot["id"], r["id"]),
            "from_id": bot["id"],
            "from_username": bot["username"],
            "to_id": r["id"],
            "to_username": r["username"],
            "text": text[:4000],
            "kind": "admin_broadcast",
            "created_at": now,
            "read": False,
        })
    if docs:
        await db.direct_messages.insert_many(docs)
    return {"ok": True, "sent": len(docs)}



# ============ Bi-weekly Spin Wheel ============

SPIN_MIN_DEPOSIT = 100.0  # user must have at least $100 lifetime deposits to spin
SPIN_COOLDOWN_DAYS = 14
# Weighted prizes: (amount, weight). Higher weight = more likely.
# Odds engineered so the expected payout is very low — well below cost floor.
# Jackpots are rare and small so users cannot farm winnings.
SPIN_PRIZES = [
    (0.10, 500),   # 50.00%
    (0.25, 250),   # 25.00%
    (0.50, 150),   # 15.00%
    (1.00,  70),   #  7.00%
    (2.00,  25),   #  2.50%
    (3.00,   4),   #  0.40%
    (5.00,   1),   #  0.10% jackpot (1 in 1000)
]


@api_router.get("/spin/status")
async def spin_status(user: CurrentUser = Depends(current_user_dep)):
    """Returns eligibility + when the user last spun.
    Eligible = lifetime approved deposits >= $100 AND hasn't spun in the last 14 days."""
    total = await _user_deposits_total(user.id)
    eligible = total >= SPIN_MIN_DEPOSIT
    last = await db.spin_wheel.find_one({"user_id": user.id}, sort=[("created_at", -1)], projection={"_id": 0})
    can_spin = eligible
    days_left = 0
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < SPIN_COOLDOWN_DAYS * 24 * 3600:
                can_spin = False
                days_left = max(0, SPIN_COOLDOWN_DAYS - int(gap / 86400))
        except Exception:
            pass
    return {
        "eligible": eligible,
        "can_spin": can_spin,
        "days_left": days_left,
        "last_spin": last,
        "prizes": [p[0] for p in SPIN_PRIZES],
        "min_deposit": SPIN_MIN_DEPOSIT,
        "cooldown_days": SPIN_COOLDOWN_DAYS,
        "total_deposits": round(total, 2),
        "amount_needed": max(0, round(SPIN_MIN_DEPOSIT - total, 2)),
    }


@api_router.post("/spin/spin")
async def spin_wheel(user: CurrentUser = Depends(current_user_dep)):
    """One free spin every 14 days. Weighted RNG toward tiny prizes.
    Only users with lifetime deposits >= $100 can spin — this cannot be a way
    for users to farm money for free."""
    total = await _user_deposits_total(user.id)
    if total < SPIN_MIN_DEPOSIT:
        raise HTTPException(status_code=403, detail=f"You need at least ${SPIN_MIN_DEPOSIT:.0f} lifetime deposits to spin. You have ${total:.2f}.")
    last = await db.spin_wheel.find_one({"user_id": user.id}, sort=[("created_at", -1)])
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < SPIN_COOLDOWN_DAYS * 24 * 3600:
                days_left = max(1, SPIN_COOLDOWN_DAYS - int(gap / 86400))
                raise HTTPException(status_code=429, detail=f"Come back in {days_left} day(s) for your next spin.")
        except HTTPException:
            raise
        except Exception:
            pass
    # Weighted random using secrets for fairness
    import secrets
    total_weight = sum(w for _, w in SPIN_PRIZES)
    roll = secrets.randbelow(total_weight)
    acc = 0
    prize = 1
    for amount, weight in SPIN_PRIZES:
        acc += weight
        if roll < acc:
            prize = amount
            break
    now = datetime.now(timezone.utc).isoformat()
    spin_id = str(uuid.uuid4())
    is_jackpot = prize >= 40
    await db.spin_wheel.insert_one({
        "id": spin_id, "user_id": user.id, "username": user.username,
        "prize": prize, "jackpot": is_jackpot, "created_at": now,
    })
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id, "username": user.username,
        "amount": float(prize), "method": "spin", "status": "approved",
        "type": "spin_prize",
        "note": ("🎰 JACKPOT — " if is_jackpot else "Weekly Spin — ") + f"won ${prize}",
        "spin_id": spin_id, "created_at": now, "approved_at": now,
    })
    # Announce jackpots publicly (small hype-boost for the shop)
    if is_jackpot:
        await db.public_chat.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id, "username": user.username, "role": user.role or "user",
            "text": f"🎰 JACKPOT — just won ${prize:.2f} on the spin wheel!",
            "kind": "jackpot",
            "created_at": now,
        })
    return {"ok": True, "prize": prize, "jackpot": is_jackpot, "spin_id": spin_id, "next_spin_days": SPIN_COOLDOWN_DAYS}


# ============ Daily free bet — $0.80 from house, once per 24h ============
DAILY_FREE_BET_AMOUNT = 0.80


@api_router.get("/free-bet/status")
async def free_bet_status(user: CurrentUser = Depends(current_user_dep)):
    """Whether the user can claim today's free $0.80 bet credit."""
    last = await db.free_bets.find_one({"user_id": user.id}, sort=[("created_at", -1)], projection={"_id": 0})
    can_claim = True
    hours_left = 0
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < 24 * 3600:
                can_claim = False
                hours_left = max(1, 24 - int(gap / 3600))
        except Exception:
            pass
    return {"can_claim": can_claim, "hours_left": hours_left, "amount": DAILY_FREE_BET_AMOUNT, "last_claim": last}


@api_router.post("/free-bet/claim")
async def free_bet_claim(user: CurrentUser = Depends(current_user_dep)):
    """Credit the user with $0.80 free-bet balance, once per 24h. This is house
    money — recorded separately so we can audit spending. It goes into normal
    balance so users can immediately bet/order with it."""
    last = await db.free_bets.find_one({"user_id": user.id}, sort=[("created_at", -1)])
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < 24 * 3600:
                hours_left = max(1, 24 - int(gap / 3600))
                raise HTTPException(status_code=429, detail=f"Come back in {hours_left}h for your next free bet.")
        except HTTPException:
            raise
        except Exception:
            pass
    now = datetime.now(timezone.utc).isoformat()
    claim_id = str(uuid.uuid4())
    await db.free_bets.insert_one({
        "id": claim_id, "user_id": user.id, "username": user.username,
        "amount": DAILY_FREE_BET_AMOUNT, "created_at": now,
    })
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id, "username": user.username,
        "amount": DAILY_FREE_BET_AMOUNT, "method": "house",
        "status": "approved", "type": "free_bet",
        "note": "Daily free bet — house-funded",
        "created_at": now, "approved_at": now,
    })
    new_balance = await _get_user_balance(user.id)
    return {"ok": True, "amount": DAILY_FREE_BET_AMOUNT, "balance": new_balance, "claim_id": claim_id}


# ============ Sports (RapidAPI live football data) ============
# Uses the user-provided RapidAPI key for free-api-live-football-data.  A
# non-fatal timeout returns an empty payload so the UI can degrade gracefully.
SPORTS_RAPID_KEY = os.environ.get("SPORTS_RAPID_KEY", "31215e25a5msh485e5613d28cd76p15b417jsna5b7f50de8ee")
SPORTS_RAPID_HOST = "free-api-live-football-data.p.rapidapi.com"


async def _rapid_get(path: str, params: dict = None):
    url = f"https://{SPORTS_RAPID_HOST}{path}"
    headers = {
        "x-rapidapi-key": SPORTS_RAPID_KEY,
        "x-rapidapi-host": SPORTS_RAPID_HOST,
    }
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers=headers, params=params or {})
        r.raise_for_status()
        return r.json()


@api_router.get("/sports/livescores")
async def sports_livescores():
    """Currently-live football matches."""
    try:
        data = await _rapid_get("/football-current-live")
    except Exception as e:
        logger.warning("[sports] livescores failed: %s", e)
        return {"matches": [], "error": "sports_source_unavailable"}
    resp = data.get("response") if isinstance(data, dict) else None
    # The RapidAPI endpoint wraps live matches under `response.live`, not `.matches`
    matches = (
        (resp or {}).get("live")
        or (resp or {}).get("matches")
        if isinstance(resp, dict)
        else (resp or [])
    )
    return {"matches": matches or []}


@api_router.get("/sports/upcoming")
async def sports_upcoming():
    """Football matches scheduled for tomorrow (upcoming fixtures)."""
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d")
    try:
        data = await _rapid_get("/football-get-matches-by-date", {"date": tomorrow})
    except Exception as e:
        logger.warning("[sports] upcoming failed: %s", e)
        return {"matches": [], "error": "sports_source_unavailable"}
    resp = data.get("response") if isinstance(data, dict) else None
    matches = (resp or {}).get("matches") if isinstance(resp, dict) else (resp or [])
    return {"matches": matches or []}


@api_router.get("/sports/leagues")
async def sports_leagues():
    """Popular football leagues (for browsing)."""
    try:
        data = await _rapid_get("/football-popular-leagues")
    except Exception as e:
        logger.warning("[sports] leagues failed: %s", e)
        return {"leagues": [], "error": "sports_source_unavailable"}
    return {"leagues": (data.get("response") or data.get("leagues") or data) or []}


# ============ Sports goal watcher — polls the livescore feed and emits events ============
# The free-tier RapidAPI feed doesn't ship per-event data (offside review,
# penalty awarded, etc.), so we derive events from successive livescore
# snapshots. A score delta becomes a `goal` event. Half-time / full-time
# and match cancellation are detected from the status object.
SPORTS_WATCH_INTERVAL_SEC = 20  # how often the watcher polls the feed


@api_router.get("/sports/events")
async def sports_events(since: Optional[str] = None, limit: int = 50):
    """Recently-emitted sports events. Frontend polls this to draw goal
    notifications and play a sound."""
    q = {}
    if since:
        q = {"created_at": {"$gt": since}}
    cursor = db.sports_events.find(q, {"_id": 0}).sort("created_at", -1).limit(min(int(limit or 50), 100))
    events = await cursor.to_list(limit)
    return {"events": list(reversed(events))}


async def _sports_watcher_loop():
    """Background task: polls livescores every 20s, diffs scores + status
    against the last snapshot, writes any changes to `sports_events`."""
    logger.info("[sports] goal watcher started (interval=%ss)", SPORTS_WATCH_INTERVAL_SEC)
    while True:
        try:
            data = await _rapid_get("/football-current-live")
            resp = data.get("response") if isinstance(data, dict) else None
            matches = (resp or {}).get("live") or (resp or {}).get("matches") or []
        except Exception as e:
            logger.warning("[sports] watcher poll failed: %s", e)
            await asyncio.sleep(SPORTS_WATCH_INTERVAL_SEC)
            continue

        now = datetime.now(timezone.utc).isoformat()
        for m in matches:
            try:
                mid = m.get("id")
                if mid is None:
                    continue
                home = m.get("home") or {}
                away = m.get("away") or {}
                home_score = int(home.get("score") or 0)
                away_score = int(away.get("score") or 0)
                status = m.get("status") or {}
                minute = ((status.get("liveTime") or {}).get("short") or "").strip()
                league_id = m.get("leagueId")

                prev = await db.sports_match_state.find_one({"match_id": mid}, {"_id": 0})
                new_state = {
                    "match_id": mid,
                    "home_id": home.get("id"),
                    "away_id": away.get("id"),
                    "home_name": home.get("name") or home.get("longName") or "Home",
                    "away_name": away.get("name") or away.get("longName") or "Away",
                    "home_score": home_score,
                    "away_score": away_score,
                    "status_id": m.get("statusId"),
                    "minute": minute,
                    "league_id": league_id,
                    "updated_at": now,
                }
                # First time seeing this match — just record state, no event.
                if not prev:
                    new_state["created_at"] = now
                    await db.sports_match_state.insert_one(new_state)
                    continue

                events_to_emit = []
                # Goal detection: any score increase
                if home_score > int(prev.get("home_score") or 0):
                    events_to_emit.append({
                        "type": "goal",
                        "team": new_state["home_name"],
                        "opponent": new_state["away_name"],
                        "score": f"{home_score} - {away_score}",
                        "minute": minute or "—",
                        "match_id": mid,
                        "league_id": league_id,
                    })
                if away_score > int(prev.get("away_score") or 0):
                    events_to_emit.append({
                        "type": "goal",
                        "team": new_state["away_name"],
                        "opponent": new_state["home_name"],
                        "score": f"{home_score} - {away_score}",
                        "minute": minute or "—",
                        "match_id": mid,
                        "league_id": league_id,
                    })
                # Goal reversal (VAR / offside): any score decrease
                if home_score < int(prev.get("home_score") or 0):
                    events_to_emit.append({
                        "type": "goal_disallowed",
                        "team": new_state["home_name"],
                        "opponent": new_state["away_name"],
                        "score": f"{home_score} - {away_score}",
                        "minute": minute or "—",
                        "match_id": mid,
                        "reason": "VAR / offside",
                    })
                if away_score < int(prev.get("away_score") or 0):
                    events_to_emit.append({
                        "type": "goal_disallowed",
                        "team": new_state["away_name"],
                        "opponent": new_state["home_name"],
                        "score": f"{home_score} - {away_score}",
                        "minute": minute or "—",
                        "match_id": mid,
                        "reason": "VAR / offside",
                    })
                # Kickoff, halftime, fulltime derived from statusId
                new_status_id = m.get("statusId")
                if new_status_id != prev.get("status_id"):
                    label = None
                    if new_status_id == 2:  # started (some feeds)
                        label = "kickoff"
                    elif new_status_id == 3:  # halftime
                        label = "halftime"
                    elif new_status_id in (100, 6, 7):  # finished
                        label = "fulltime"
                    if label:
                        events_to_emit.append({
                            "type": label,
                            "team": new_state["home_name"],
                            "opponent": new_state["away_name"],
                            "score": f"{home_score} - {away_score}",
                            "minute": minute or "—",
                            "match_id": mid,
                        })

                # Write events + update snapshot
                for ev in events_to_emit:
                    ev["id"] = str(uuid.uuid4())
                    ev["created_at"] = now
                    await db.sports_events.insert_one(ev.copy())
                    logger.info("[sports] %s — %s @ %s (%s)", ev["type"], ev["team"], ev.get("minute"), ev.get("score"))
                await db.sports_match_state.update_one({"match_id": mid}, {"$set": new_state})
            except Exception as e:  # never break the loop over a single match
                logger.exception("[sports] failed to process match: %s", e)

        # Trim old state (matches that haven't ticked in >12h) so memory doesn't grow
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
            await db.sports_match_state.delete_many({"updated_at": {"$lt": cutoff}})
        except Exception:
            pass

        await asyncio.sleep(SPORTS_WATCH_INTERVAL_SEC)



# ============ Slot Machine (Wild-Hot-style) ============
# 5 reels × 4 rows on display. Bet $0.20–$5. Easier win frequency, WILDs with
# multipliers, and 3+ SCATTER (FREE SPIN) symbols anywhere award free spins.
SLOT_SYMBOLS = [
    # (id, name, weight-per-reel, payout_multiplier[3,4,5])
    ("cherry",  "Cherry",       40, [0.5, 1.0, 3.0]),
    ("lemon",   "Lemon",        34, [0.6, 1.5, 4.0]),
    ("orange",  "Orange",       28, [1.0, 2.5, 6.0]),
    ("plum",    "Plum",         22, [1.5, 4.0, 12.0]),
    ("grape",   "Grape",        16, [3.0, 8.0, 25.0]),
    ("melon",   "Watermelon",   10, [6.0, 18.0, 60.0]),
    ("seven",   "Lucky Seven",   6, [15.0, 60.0, 250.0]),
    ("wild",    "Wild",          4, [0.0, 0.0, 0.0]),  # substitutes anything, no line win alone
    ("scatter", "Free Spins",    4, [0.0, 0.0, 0.0]),  # 3+ anywhere triggers free spins
]
_SLOT_TOTAL_W = sum(w for _, _, w, _ in SLOT_SYMBOLS)
SLOT_WILD_MULTS = [1, 1, 1, 2, 2, 3, 5]  # random pick per wild (skewed to low)
SLOT_FREE_SPINS_TABLE = {3: 5, 4: 10, 5: 15}


def _slot_spin_reel() -> str:
    import secrets as _s
    r = _s.randbelow(_SLOT_TOTAL_W)
    acc = 0
    for sid, _, w, _p in SLOT_SYMBOLS:
        acc += w
        if r < acc:
            return sid
    return SLOT_SYMBOLS[0][0]


def _slot_evaluate(grid: list, wild_mults: dict) -> list:
    """grid = 5 reels × N rows. Returns wins list with wild substitution + multipliers.
    wild_mults maps (reel,row) → multiplier when the wild lands there.
    Scatters are counted separately — they don't participate in payline wins."""
    payouts = {s[0]: s[3] for s in SLOT_SYMBOLS if s[0] not in ("wild", "scatter")}
    wins = []
    rows = len(grid[0])
    for row in range(rows):
        # Find leftmost non-wild anchor symbol
        anchor = None
        anchor_reel = 0
        for reel in range(5):
            sym = grid[reel][row]
            if sym == "scatter":
                break  # scatter breaks the payline
            if sym != "wild":
                anchor = sym
                anchor_reel = reel
                break
            # wild counted separately below
        # If ALL 5 were wild (very rare) → treat as top-symbol payout
        if anchor is None:
            # check no scatter in row
            if any(grid[r][row] == "scatter" for r in range(5)):
                continue
            anchor = "seven"
            anchor_reel = 0
        # Count contiguous match from reel 0, treating wild as match
        count = 0
        wilds_used = []
        for reel in range(5):
            sym = grid[reel][row]
            if sym == anchor or sym == "wild":
                count += 1
                if sym == "wild":
                    wilds_used.append((reel, row))
            else:
                break
        if count < 3 or anchor not in payouts:
            continue
        base = payouts[anchor][count - 3]
        # Combine any wild-tile multipliers in the winning stretch
        total_wild_mult = 1
        for pos in wilds_used:
            total_wild_mult *= wild_mults.get(pos, 1)
        wins.append({
            "row": row,
            "symbol": anchor,
            "matches": count,
            "mult": base * total_wild_mult,
            "wild_mult": total_wild_mult,
            "wilds": wilds_used,
        })
    return wins


class SlotSpinRequest(BaseModel):
    bet: float = Field(..., ge=0.20, le=5.00)
    free_spin: bool = False  # server ignores if user has no free spins remaining


@api_router.post("/games/slot/spin")
async def slot_spin(payload: SlotSpinRequest, user: CurrentUser = Depends(current_user_dep)):
    bet = round(float(payload.bet), 2)
    if bet < 0.20 or bet > 5.00:
        raise HTTPException(status_code=400, detail="Bet must be between $0.20 and $5.00")
    # Free-spin bookkeeping
    state = await db.slot_state.find_one({"user_id": user.id}, {"_id": 0}) or {}
    free_spins_left = int(state.get("free_spins", 0))
    use_free = bool(payload.free_spin) and free_spins_left > 0
    if not use_free:
        balance = await _get_user_balance(user.id)
        if balance < bet:
            raise HTTPException(status_code=400, detail=f"Not enough balance — need ${bet:.2f}, you have ${balance:.2f}")
    # Roll grid + place 0-5 wilds with multipliers
    import secrets as _s
    grid = [[_slot_spin_reel() for _ in range(4)] for _ in range(5)]
    # Sprinkle extra wilds after the base roll — this makes wins much more frequent
    # without touching the raw reel odds.  0-5 wilds, weighted toward 1-2.
    extra_wild_bag = [0, 0, 1, 1, 1, 2, 2, 3, 4, 5]
    extras = extra_wild_bag[_s.randbelow(len(extra_wild_bag))]
    wild_mults = {}
    placed = 0
    tries = 0
    while placed < extras and tries < 40:
        r = _s.randbelow(5)
        c = _s.randbelow(4)
        tries += 1
        if grid[r][c] in ("wild", "scatter"):
            continue
        grid[r][c] = "wild"
        wild_mults[(r, c)] = SLOT_WILD_MULTS[_s.randbelow(len(SLOT_WILD_MULTS))]
        placed += 1
    # Evaluate
    wins = _slot_evaluate(grid, wild_mults)
    total_mult = sum(w["mult"] for w in wins)
    payout = round(bet * total_mult, 2)
    # Count scatters — 3+ anywhere → free spins
    scatter_count = sum(1 for reel in grid for cell in reel if cell == "scatter")
    free_spins_awarded = SLOT_FREE_SPINS_TABLE.get(scatter_count, 0)

    now = datetime.now(timezone.utc).isoformat()
    if use_free:
        # deduct one free spin, no balance charge
        await db.slot_state.update_one(
            {"user_id": user.id},
            {"$inc": {"free_spins": -1}, "$set": {"updated_at": now}},
            upsert=True,
        )
    else:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
            "amount": -bet, "method": "slot", "status": "approved",
            "type": "slot_bet", "note": f"Slot bet ${bet:.2f}",
            "created_at": now, "approved_at": now,
        })
    if payout > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
            "amount": payout, "method": "slot", "status": "approved",
            "type": "slot_win", "note": f"Slot win ${payout:.2f} ({total_mult:.1f}× bet)",
            "created_at": now, "approved_at": now,
        })
        await db.users.update_one({"id": user.id}, {"$inc": {"withdrawable_balance": payout}})
    if free_spins_awarded > 0:
        await db.slot_state.update_one(
            {"user_id": user.id},
            {"$inc": {"free_spins": free_spins_awarded}, "$set": {"updated_at": now}},
            upsert=True,
        )
    new_state = await db.slot_state.find_one({"user_id": user.id}, {"_id": 0}) or {}
    new_balance = await _get_user_balance(user.id)
    # Convert wild_mults keys (tuple) → list for JSON
    wilds_out = [{"reel": r, "row": c, "mult": m} for (r, c), m in wild_mults.items()]
    return {
        "ok": True, "bet": bet, "grid": grid, "wins": wins,
        "wilds": wilds_out,
        "scatter_count": scatter_count,
        "free_spins_awarded": free_spins_awarded,
        "free_spins_remaining": int(new_state.get("free_spins", 0)),
        "used_free_spin": use_free,
        "total_mult": round(total_mult, 2),
        "payout": payout,
        "balance": new_balance,
    }


@api_router.get("/games/slot/state")
async def slot_state(user: CurrentUser = Depends(current_user_dep)):
    s = await db.slot_state.find_one({"user_id": user.id}, {"_id": 0}) or {}
    return {"free_spins": int(s.get("free_spins", 0))}


# ============ Aviator (daily crash game) ============
# Player bets any amount, plane multiplier climbs from 1.00× exponentially.
# Server pre-rolls a crash multiplier (heavy-tailed with a 3% instant-crash chance
# for house edge). Cashout pays bet × current mult if game hasn't crashed yet.
import math as _math
AVIATOR_GROWTH_K = 0.35  # multiplier growth rate per second (~e^(0.35t))
AVIATOR_MAX_MULT = 100.0
AVIATOR_INSTANT_CRASH_RATE = 0.03  # 3% chance of instant crash → house edge


def _roll_aviator_crash() -> float:
    import secrets as _s
    u = _s.randbelow(10_000_000) / 10_000_000.0  # [0, 1)
    if u < AVIATOR_INSTANT_CRASH_RATE:
        return 1.00
    # crash = 0.99 / (1 - u)  → median ~ 2×, capped
    crash = min(AVIATOR_MAX_MULT, 0.99 / max(0.0001, 1.0 - u))
    return round(max(1.01, crash), 2)


class AviatorStartRequest(BaseModel):
    bet: float = Field(..., ge=0.20, le=100.00)


@api_router.get("/games/aviator/status")
async def aviator_status(user: CurrentUser = Depends(current_user_dep)):
    today = datetime.now(timezone.utc).date().isoformat()
    played_today = await db.aviator_games.find_one(
        {"user_id": user.id, "day": today},
        {"_id": 0, "id": 1, "status": 1, "bet": 1, "start_time": 1, "cashout_mult": 1},
    )
    active = played_today and played_today.get("status") == "active"
    return {
        "played_today": bool(played_today and played_today.get("status") != "active"),
        "active_game": played_today if active else None,
        "can_play": played_today is None or active,
        "growth_k": AVIATOR_GROWTH_K,
    }


@api_router.post("/games/aviator/start")
async def aviator_start(payload: AviatorStartRequest, user: CurrentUser = Depends(current_user_dep)):
    today = datetime.now(timezone.utc).date().isoformat()
    existing = await db.aviator_games.find_one({"user_id": user.id, "day": today})
    if existing:
        if existing.get("status") == "active":
            return {"ok": True, "game_id": existing["id"], "bet": existing["bet"], "start_time": existing["start_time"], "already_active": True}
        raise HTTPException(status_code=429, detail="You already played Aviator today. Come back tomorrow!")
    bet = round(float(payload.bet), 2)
    balance = await _get_user_balance(user.id)
    if balance < bet:
        raise HTTPException(status_code=400, detail=f"Not enough balance — need ${bet:.2f}, you have ${balance:.2f}")
    game_id = str(uuid.uuid4())
    crash_mult = _roll_aviator_crash()
    start_ts = datetime.now(timezone.utc)
    # Reserve the stake immediately
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
        "amount": -bet, "method": "aviator", "status": "approved",
        "type": "aviator_stake", "note": f"Aviator stake ${bet:.2f}",
        "aviator_game_id": game_id, "created_at": start_ts.isoformat(),
        "approved_at": start_ts.isoformat(),
    })
    await db.aviator_games.insert_one({
        "id": game_id, "user_id": user.id, "username": user.username,
        "day": today, "bet": bet, "crash_mult": crash_mult,
        "start_time": start_ts.isoformat(), "start_ts_epoch": start_ts.timestamp(),
        "status": "active", "created_at": start_ts.isoformat(),
    })
    return {"ok": True, "game_id": game_id, "bet": bet, "start_time": start_ts.isoformat(), "growth_k": AVIATOR_GROWTH_K}


class AviatorCashoutRequest(BaseModel):
    game_id: str


@api_router.post("/games/aviator/cashout")
async def aviator_cashout(payload: AviatorCashoutRequest, user: CurrentUser = Depends(current_user_dep)):
    game = await db.aviator_games.find_one({"id": payload.game_id, "user_id": user.id})
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.get("status") != "active":
        raise HTTPException(status_code=400, detail="Game already ended")
    now = datetime.now(timezone.utc)
    elapsed = now.timestamp() - float(game["start_ts_epoch"])
    current_mult = round(min(AVIATOR_MAX_MULT, _math.exp(AVIATOR_GROWTH_K * max(0.0, elapsed))), 2)
    crash_mult = float(game.get("crash_mult", 1.0))
    if current_mult >= crash_mult:
        # Crashed before user cashed out
        await db.aviator_games.update_one(
            {"id": game["id"]},
            {"$set": {"status": "crashed", "cashout_mult": crash_mult, "ended_at": now.isoformat()}},
        )
        return {"ok": True, "result": "crashed", "crash_mult": crash_mult, "current_mult": crash_mult, "payout": 0}
    # Successful cashout
    payout = round(float(game["bet"]) * current_mult, 2)
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
        "amount": payout, "method": "aviator", "status": "approved",
        "type": "aviator_win", "note": f"Aviator cashout {current_mult:.2f}× — ${payout:.2f}",
        "aviator_game_id": game["id"], "created_at": now.isoformat(),
        "approved_at": now.isoformat(),
    })
    await db.users.update_one({"id": user.id}, {"$inc": {"withdrawable_balance": payout}})
    await db.aviator_games.update_one(
        {"id": game["id"]},
        {"$set": {"status": "cashed", "cashout_mult": current_mult, "payout": payout, "ended_at": now.isoformat()}},
    )
    return {"ok": True, "result": "cashed", "mult": current_mult, "payout": payout, "crash_mult": crash_mult}


# ============ Daily Stairs Game ============
# Fixed stake $0.80. 10 steps. Each step user picks left/right — one is safe, other is bomb.
# Multipliers grow per step. User can cash out any time; bomb loses stake.
# Eligibility: lifetime approved deposits >= $50; playable once per day.
STAIRS_STAKE = 0.80
STAIRS_MIN_DEPOSIT = 50.0
STAIRS_MULTS = [1.20, 1.50, 2.00, 2.50, 3.00, 5.00, 8.00, 12.00, 20.00, 40.00]


@api_router.get("/games/stairs/status")
async def stairs_status(user: CurrentUser = Depends(current_user_dep)):
    total = await _user_deposits_total(user.id)
    eligible = total >= STAIRS_MIN_DEPOSIT
    today = datetime.now(timezone.utc).date().isoformat()
    played_today = await db.stairs_games.find_one(
        {"user_id": user.id, "day": today},
        {"_id": 0, "status": 1, "step": 1, "path": 1, "cashed_out_at": 1, "id": 1},
    )
    active = played_today and played_today.get("status") == "active"
    return {
        "eligible": eligible,
        "lifetime_deposits": total,
        "can_play": eligible and (played_today is None or active),
        "played_today": bool(played_today and played_today.get("status") != "active"),
        "active_game": played_today if active else None,
        "stake": STAIRS_STAKE,
        "multipliers": STAIRS_MULTS,
    }


@api_router.post("/games/stairs/start")
async def stairs_start(user: CurrentUser = Depends(current_user_dep)):
    total = await _user_deposits_total(user.id)
    if total < STAIRS_MIN_DEPOSIT:
        raise HTTPException(status_code=403, detail=f"Need at least ${STAIRS_MIN_DEPOSIT:.0f} in lifetime deposits to play.")
    today = datetime.now(timezone.utc).date().isoformat()
    existing = await db.stairs_games.find_one({"user_id": user.id, "day": today})
    if existing:
        if existing.get("status") == "active":
            return {"ok": True, "game_id": existing["id"], "step": existing["step"], "path": existing.get("path", []), "already_active": True}
        raise HTTPException(status_code=429, detail="You already played today. Come back tomorrow!")
    balance = await _get_user_balance(user.id)
    if balance < STAIRS_STAKE:
        raise HTTPException(status_code=400, detail=f"Need ${STAIRS_STAKE:.2f} in balance to play.")
    # Pre-roll all 10 bomb positions (0 = left is bomb, 1 = right is bomb) with a random seed.
    import secrets as _s
    bombs = [_s.randbelow(2) for _ in range(10)]
    now = datetime.now(timezone.utc).isoformat()
    game_id = str(uuid.uuid4())
    # Reserve the stake
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
        "amount": -STAIRS_STAKE, "method": "stairs", "status": "approved",
        "type": "stairs_stake", "note": "Daily stairs — stake",
        "stairs_game_id": game_id, "created_at": now, "approved_at": now,
    })
    await db.stairs_games.insert_one({
        "id": game_id, "user_id": user.id, "username": user.username,
        "day": today, "bombs": bombs, "path": [], "step": 0,
        "status": "active", "stake": STAIRS_STAKE, "created_at": now,
    })
    return {"ok": True, "game_id": game_id, "step": 0, "path": [], "multipliers": STAIRS_MULTS}


class StairsStepRequest(BaseModel):
    game_id: str
    choice: int  # 0 = left, 1 = right


@api_router.post("/games/stairs/step")
async def stairs_step(payload: StairsStepRequest, user: CurrentUser = Depends(current_user_dep)):
    game = await db.stairs_games.find_one({"id": payload.game_id, "user_id": user.id})
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.get("status") != "active":
        raise HTTPException(status_code=400, detail="Game already ended")
    step = int(game.get("step", 0))
    if step >= len(STAIRS_MULTS):
        raise HTTPException(status_code=400, detail="Max reached — cash out")
    choice = 0 if int(payload.choice) == 0 else 1
    bombs = game.get("bombs") or []
    bomb_side = int(bombs[step]) if step < len(bombs) else 0
    hit_bomb = choice == bomb_side
    path = list(game.get("path", []))
    path.append({"step": step, "choice": choice, "bomb": bomb_side, "hit": hit_bomb})
    now = datetime.now(timezone.utc).isoformat()
    if hit_bomb:
        await db.stairs_games.update_one({"id": game["id"]}, {"$set": {"status": "lost", "path": path, "ended_at": now}})
        return {"ok": True, "hit_bomb": True, "step": step, "bomb_side": bomb_side, "status": "lost"}
    new_step = step + 1
    upd = {"path": path, "step": new_step}
    if new_step >= len(STAIRS_MULTS):
        # Auto cash out at max
        mult = STAIRS_MULTS[-1]
        payout = round(STAIRS_STAKE * mult, 2)
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
            "amount": payout, "method": "stairs", "status": "approved",
            "type": "stairs_win", "note": f"Stairs max reached — ${payout:.2f}",
            "stairs_game_id": game["id"], "created_at": now, "approved_at": now,
        })
        await db.users.update_one({"id": user.id}, {"$inc": {"withdrawable_balance": payout}})
        upd.update({"status": "won", "cashed_out_at": now, "payout": payout, "final_mult": mult})
    await db.stairs_games.update_one({"id": game["id"]}, {"$set": upd})
    return {
        "ok": True, "hit_bomb": False, "step": new_step, "current_mult": STAIRS_MULTS[step],
        "next_mult": STAIRS_MULTS[new_step] if new_step < len(STAIRS_MULTS) else None,
        "status": upd.get("status", "active"), "payout": upd.get("payout"),
    }


class StairsCashoutRequest(BaseModel):
    game_id: str


@api_router.post("/games/stairs/cashout")
async def stairs_cashout(payload: StairsCashoutRequest, user: CurrentUser = Depends(current_user_dep)):
    game = await db.stairs_games.find_one({"id": payload.game_id, "user_id": user.id})
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.get("status") != "active":
        raise HTTPException(status_code=400, detail="Game already ended")
    step = int(game.get("step", 0))
    if step == 0:
        raise HTTPException(status_code=400, detail="Take at least one step before cashing out.")
    mult = STAIRS_MULTS[step - 1]
    payout = round(STAIRS_STAKE * mult, 2)
    now = datetime.now(timezone.utc).isoformat()
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
        "amount": payout, "method": "stairs", "status": "approved",
        "type": "stairs_win", "note": f"Stairs cashout {mult:.1f}× — ${payout:.2f}",
        "stairs_game_id": game["id"], "created_at": now, "approved_at": now,
    })
    await db.users.update_one({"id": user.id}, {"$inc": {"withdrawable_balance": payout}})
    await db.stairs_games.update_one({"id": game["id"]}, {"$set": {"status": "won", "cashed_out_at": now, "payout": payout, "final_mult": mult}})
    return {"ok": True, "payout": payout, "mult": mult, "step": step}


# ============ News modal (one-time popup per user) ============

class NewsConfig(BaseModel):
    enabled: bool = True
    title: str = Field("", max_length=120)
    body: str = Field("", max_length=4000)


@api_router.get("/news")
async def get_public_news():
    """Public read — client shows this in a one-time modal (client remembers dismissal via localStorage keyed on news_id)."""
    cfg = await db.news_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    if not cfg.get("enabled"):
        return {"enabled": False}
    return {
        "enabled": True,
        "id": cfg.get("id", "n1"),
        "title": cfg.get("title", ""),
        "body": cfg.get("body", ""),
    }


@api_router.get("/admin/news")
async def admin_get_news(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.news_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "title": cfg.get("title", ""),
        "body": cfg.get("body", ""),
        "id": cfg.get("id", ""),
    }


@api_router.post("/admin/news")
async def admin_set_news(payload: NewsConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    news_id = str(uuid.uuid4())[:8]  # new id → forces the modal to show again for every user
    await db.news_config.update_one(
        {"_id": "singleton"},
        {"$set": {
            "enabled": bool(payload.enabled),
            "title": payload.title.strip()[:120],
            "body": payload.body.strip()[:4000],
            "id": news_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True, "id": news_id}



# ============ 5sim.net phone-number rental integration ============

SIM5_BASE = "https://5sim.net/v1"
SIM5_PRODUCTS = ["whatsapp", "signal", "viber", "tiktok", "telegram"]


async def _get_sim5_config() -> dict:
    cfg = await db.sim5_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {
        "api_key": cfg.get("api_key", ""),
        "prices": cfg.get("prices", {p: 2.0 for p in SIM5_PRODUCTS}),
        "default_country": cfg.get("default_country", "any"),
        "default_operator": cfg.get("default_operator", "any"),
    }


async def _sim5_call(method: str, path: str, api_key: str) -> tuple[int, dict | str]:
    async with httpx.AsyncClient(timeout=25.0) as c:
        r = await c.request(method, f"{SIM5_BASE}{path}", headers={
            "Authorization": f"Bearer {api_key}", "Accept": "application/json"
        })
        ctype = (r.headers.get("content-type") or "").lower()
        return r.status_code, (r.json() if "json" in ctype else r.text)


class Sim5ConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    prices: Optional[dict] = None  # {"whatsapp": 2.00, ...}
    default_country: Optional[str] = None
    default_operator: Optional[str] = None


@api_router.get("/admin/5sim/config")
async def admin_sim5_config_get(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await _get_sim5_config()
    # Mask the key server-side so it doesn't leak into browser dev tools
    if cfg["api_key"]:
        cfg["api_key_preview"] = cfg["api_key"][:8] + "…" + cfg["api_key"][-6:]
    cfg["api_key"] = "***" if cfg["api_key"] else ""
    cfg["products"] = SIM5_PRODUCTS
    return cfg


@api_router.post("/admin/5sim/config")
async def admin_sim5_config_set(payload: Sim5ConfigUpdate, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    upd: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if payload.api_key and payload.api_key != "***":
        upd["api_key"] = payload.api_key.strip()
    if payload.prices is not None:
        # Only accept whitelisted products
        clean = {k: round(float(v), 2) for k, v in payload.prices.items() if k in SIM5_PRODUCTS and float(v) > 0}
        upd["prices"] = clean
    if payload.default_country is not None:
        upd["default_country"] = payload.default_country.strip() or "any"
    if payload.default_operator is not None:
        upd["default_operator"] = payload.default_operator.strip() or "any"
    await db.sim5_config.update_one({"_id": "singleton"}, {"$set": upd}, upsert=True)
    return {"ok": True}


@api_router.get("/admin/5sim/balance")
async def admin_sim5_balance(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await _get_sim5_config()
    if not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="5sim API key not configured")
    status, data = await _sim5_call("GET", "/user/profile", cfg["api_key"])
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"5sim: {data}")
    return {"balance": data.get("balance"), "rating": data.get("rating"), "email": data.get("email"), "raw": data}


# ---- Public / client ----

@api_router.get("/5sim/services")
@api_router.get("/numbers/services")
async def sim5_services_list():
    """Public — list available services with their retail prices."""
    cfg = await _get_sim5_config()
    return {
        "products": [
            {
                "id": p,
                "name": p.capitalize(),
                "price": float(cfg["prices"].get(p, 2.0)),
                "icon": {
                    "whatsapp": "💬", "signal": "🔒", "viber": "📞",
                    "tiktok": "🎵", "telegram": "✈️",
                }.get(p, "📱"),
            }
            for p in SIM5_PRODUCTS
        ],
        "default_country": cfg["default_country"],
        "default_operator": cfg["default_operator"],
    }


class Sim5BuyRequest(BaseModel):
    product: str
    country: Optional[str] = None
    operator: Optional[str] = None


@api_router.post("/5sim/buy")
@api_router.post("/numbers/buy")
async def sim5_buy(payload: Sim5BuyRequest, user: CurrentUser = Depends(current_user_dep)):
    if payload.product not in SIM5_PRODUCTS:
        raise HTTPException(status_code=400, detail=f"Unsupported service. Choose one of: {', '.join(SIM5_PRODUCTS)}")
    cfg = await _get_sim5_config()
    if not cfg["api_key"]:
        raise HTTPException(status_code=503, detail="Phone-number service is under maintenance. Please try again later.")
    retail = float(cfg["prices"].get(payload.product, 0))
    if retail <= 0:
        raise HTTPException(status_code=503, detail="This service is temporarily unavailable.")
    balance = await _get_user_balance(user.id)
    if balance < retail:
        raise HTTPException(status_code=400, detail=f"Not enough balance — need ${retail:.2f}, you have ${balance:.2f}")
    country = (payload.country or cfg["default_country"] or "any").strip().lower()
    operator = (payload.operator or cfg["default_operator"] or "any").strip().lower()
    status, data = await _sim5_call("GET", f"/user/buy/activation/{country}/{operator}/{payload.product}", cfg["api_key"])
    if status >= 400:
        # Log the underlying reason for the admin, but show a neutral message to the user.
        raw = data if isinstance(data, str) else (data.get("detail") or str(data))
        logger.warning("Number-purchase upstream error for user=%s product=%s country=%s: %s",
                       user.username, payload.product, country, raw[:200] if isinstance(raw, str) else raw)
        raise HTTPException(
            status_code=503,
            detail="This number is temporarily out of stock — please try another country or come back in a few minutes.",
        )
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": order_id,
        "user_id": user.id,
        "username": user.username,
        "product": payload.product,
        "country": country,
        "operator": operator,
        "sim5_id": data.get("id"),
        "phone": data.get("phone"),
        "sim5_cost": data.get("price"),
        "cost_paid_by_user": retail,
        "expires_at": data.get("expires"),
        "status": "waiting",
        "sms": [],
        "created_at": now,
    }
    await db.sim5_orders.insert_one(doc.copy())
    # Deduct retail from user balance immediately (approved deduction)
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "amount": -retail,
        "method": "5sim",
        "status": "approved",
        "type": "5sim_purchase",
        "note": f"5sim {payload.product} number: {data.get('phone')}",
        "sim5_order_id": order_id,
        "created_at": now,
        "approved_at": now,
    })
    return {"ok": True, "order_id": order_id, "phone": doc["phone"], "expires_at": doc["expires_at"], "price": retail}


async def _sim5_refresh_order(order: dict) -> dict:
    """Poll 5sim for latest SMS list and status; persist back to Mongo."""
    cfg = await _get_sim5_config()
    if not cfg["api_key"] or not order.get("sim5_id"):
        return order
    status, data = await _sim5_call("GET", f"/user/check/{order['sim5_id']}", cfg["api_key"])
    if status >= 400 or not isinstance(data, dict):
        return order
    sms = data.get("sms") or []
    new_status = (data.get("status") or "").upper() or order.get("status")
    upd = {"sms": sms, "status": new_status, "last_polled": datetime.now(timezone.utc).isoformat()}
    await db.sim5_orders.update_one({"id": order["id"]}, {"$set": upd})
    order.update(upd)
    return order


@api_router.get("/5sim/orders/my")
@api_router.get("/numbers/orders/my")
async def sim5_my_orders(user: CurrentUser = Depends(current_user_dep)):
    cur = db.sim5_orders.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(20)
    orders = await cur.to_list(20)
    # Auto-refresh active orders so newly-received SMS codes show up without the
    # user having to open the detail view.
    active_statuses = {"", "WAITING", "PENDING", "RECEIVED"}
    for i, o in enumerate(orders):
        if str(o.get("status", "")).upper() in active_statuses:
            try:
                orders[i] = await _sim5_refresh_order(o)
            except Exception as e:
                logger.warning("Refresh order %s failed: %s", o.get("id"), e)
    return {"orders": orders}


@api_router.get("/5sim/orders/{oid}")
@api_router.get("/numbers/orders/{oid}")
async def sim5_order_detail(oid: str, user: CurrentUser = Depends(current_user_dep)):
    order = await db.sim5_orders.find_one({"id": oid, "user_id": user.id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Auto-refresh (poll 5sim) if still waiting/receiving
    if str(order.get("status", "")).upper() in ("WAITING", "PENDING", "RECEIVED", ""):
        order = await _sim5_refresh_order(order)
    return order


async def _sim5_finalize(oid: str, user: CurrentUser, action: str) -> dict:
    """action: 'finish' or 'cancel'. cancel triggers a refund of the retail price."""
    order = await db.sim5_orders.find_one({"id": oid, "user_id": user.id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status", "").upper() in ("FINISHED", "CANCELED", "CANCELLED", "BANNED"):
        return {"ok": True, "already": order["status"]}
    cfg = await _get_sim5_config()
    if not cfg["api_key"]:
        raise HTTPException(status_code=503, detail="Service is under maintenance. Please try again later.")
    endpoint = "finish" if action == "finish" else "cancel"
    status, data = await _sim5_call("GET", f"/user/{endpoint}/{order['sim5_id']}", cfg["api_key"])
    if status >= 400:
        logger.warning("Number order finalize (%s) upstream error for oid=%s: %s", action, oid, data)
        raise HTTPException(status_code=503, detail="Could not update this rental right now — please try again in a moment.")
    new_status = "FINISHED" if action == "finish" else "CANCELED"
    now = datetime.now(timezone.utc).isoformat()
    await db.sim5_orders.update_one({"id": oid}, {"$set": {"status": new_status, "closed_at": now}})
    # Refund on cancel
    if action == "cancel":
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "username": user.username,
            "amount": float(order.get("cost_paid_by_user", 0)),
            "method": "5sim",
            "status": "approved",
            "type": "5sim_refund",
            "note": f"Refund — cancelled {order.get('product')} number",
            "sim5_order_id": oid,
            "created_at": now,
            "approved_at": now,
        })
    return {"ok": True, "status": new_status}


@api_router.post("/5sim/orders/{oid}/finish")
@api_router.post("/numbers/orders/{oid}/finish")
async def sim5_finish_order(oid: str, user: CurrentUser = Depends(current_user_dep)):
    return await _sim5_finalize(oid, user, "finish")


@api_router.post("/5sim/orders/{oid}/cancel")
@api_router.post("/numbers/orders/{oid}/cancel")
async def sim5_cancel_order(oid: str, user: CurrentUser = Depends(current_user_dep)):
    return await _sim5_finalize(oid, user, "cancel")




class UIConfig(BaseModel):
    use_new_home_layout: bool = True


@api_router.get("/ui-config")
async def get_public_ui_config():
    """Public read — client-side dashboards fetch this to pick which layout to render.
    Default is the Green Theme (True) unless the admin explicitly disables it."""
    cfg = await db.ui_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {"use_new_home_layout": bool(cfg.get("use_new_home_layout", True))}


@api_router.get("/admin/ui-config")
async def admin_get_ui_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.ui_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {"use_new_home_layout": bool(cfg.get("use_new_home_layout", True))}


@api_router.post("/admin/ui-config")
async def admin_set_ui_config(payload: UIConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    await db.ui_config.update_one(
        {"_id": "singleton"},
        {"$set": {"use_new_home_layout": bool(payload.use_new_home_layout), "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True, "use_new_home_layout": bool(payload.use_new_home_layout)}


# ============ Fake online-users toggle ============

class FakeOnlineConfig(BaseModel):
    enabled: bool


@api_router.get("/admin/fake-online")
async def admin_get_fake_online(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.settings.find_one({"_id": "fake_online"}, {"_id": 0}) or {}
    return {"enabled": bool(cfg.get("enabled", True))}


@api_router.post("/admin/fake-online")
async def admin_set_fake_online(payload: FakeOnlineConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    await db.settings.update_one(
        {"_id": "fake_online"},
        {"$set": {"enabled": bool(payload.enabled), "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True, "enabled": bool(payload.enabled)}



class NowpaymentsFundsRequest(BaseModel):
    amount: float = Field(..., ge=0.10, le=10000)


@client_router.post("/funds/nowpayments-create")
async def nowpayments_create_funds(body: NowpaymentsFundsRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    tx_id = str(uuid.uuid4())
    amount = round(float(body.amount), 2)
    # Derive the PUBLIC base URL. Priority:
    #   1. BACKEND_URL env var (most reliable — set this on production)
    #   2. FastAPI's request.base_url (works when accessed via public URL)
    #   3. `origin`/`referer` headers as last resort
    backend_url = (
        (os.environ.get("BACKEND_URL") or "").rstrip("/")
        or str(request.base_url).rstrip("/")
        or (request.headers.get("origin") or "").rstrip("/")
    )
    frontend_url = (
        (request.headers.get("origin") or "").rstrip("/")
        or (request.headers.get("referer") or "").split("/api")[0].rstrip("/")
        or backend_url
    )
    await db.transactions.insert_one({
        "id": tx_id,
        "user_id": user.id,
        "username": user.username,
        "amount": amount,
        "method": "nowpayments",
        "status": "pending",
        "type": "deposit",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    invoice = await _create_nowpayments_invoice(
        amount_usd=amount,
        order_id=f"funds_{tx_id}",
        description=f"Better Social — Add ${amount:.2f} for @{user.username}",
        ipn_url=f"{backend_url}/api/nowpayments/webhook",
        success_url=f"{frontend_url}/client/dashboard?nowpay=1&tx={tx_id}",
        cancel_url=f"{frontend_url}/client/dashboard?nowpay=cancel",
    )
    await db.transactions.update_one(
        {"id": tx_id},
        {"$set": {"nowpayments_invoice_id": invoice["invoice_id"], "nowpayments_url": invoice["invoice_url"]}},
    )
    logger.info(f"[nowpay] Created invoice {invoice['invoice_id']} for tx={tx_id} amount=${amount} ipn_url={backend_url}/api/nowpayments/webhook")
    return {"id": tx_id, "checkout_url": invoice["invoice_url"]}


# Statuses that mean "the buyer has paid — credit them".
NOWPAY_SUCCESS_STATUSES = {"finished", "confirmed", "sending", "partially_paid"}


async def _credit_nowpayments_deposit(tx: dict, payload: dict) -> dict:
    """Idempotent: mark tx approved + insert 70% bonus + persist payload.
    Called from BOTH the webhook and the manual /verify endpoint so we never double-credit."""
    tx_id = tx["id"]
    if tx.get("status") == "approved":
        return {"ok": True, "already_credited": True, "tx_id": tx_id}
    amount = float(tx.get("amount", 0))
    bonus = round(amount * 0.70, 2)  # 70% deposit bonus
    now = datetime.now(timezone.utc).isoformat()
    upd = await db.transactions.update_one(
        {"id": tx_id, "status": {"$ne": "approved"}},  # extra concurrency guard
        {"$set": {
            "status": "approved",
            "approved_at": now,
            "nowpayments_payload": payload,
            "bonus_applied": bonus,
        }},
    )
    if upd.modified_count == 0:
        return {"ok": True, "already_credited": True, "tx_id": tx_id}
    if bonus > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": tx["user_id"],
            "username": tx.get("username"),
            "amount": bonus,
            "method": "bonus",
            "status": "approved",
            "type": "deposit_bonus",
            "note": f"+70% crypto deposit bonus on ${amount:.2f}",
            "created_at": now,
            "approved_at": now,
            "linked_tx": tx_id,
        })
    logger.info(f"[nowpay] CREDITED tx={tx_id} user={tx.get('username')} amount=${amount} bonus=${bonus}")
    return {"ok": True, "credited": tx_id, "amount": amount, "bonus": bonus}


@api_router.post("/nowpayments/webhook")
async def nowpayments_webhook(request: Request):
    """Called by NOWPayments when payment status changes. Credits balance on success statuses."""
    body = await request.body()
    signature = request.headers.get("x-nowpayments-sig", "")
    cfg = await db.nowpayments_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    ipn_secret = cfg.get("ipn_secret", "")
    sig_ok = True
    if ipn_secret:
        sig_ok = _verify_nowpayments_signature(body, ipn_secret, signature)
    try:
        data = jsonlib.loads(body.decode("utf-8"))
    except Exception:
        data = {"_raw": body.decode("utf-8", errors="replace")[:1000]}
    # ALWAYS log the event so we can debug missing credits later
    await db.nowpayments_events.insert_one({
        "id": str(uuid.uuid4()),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "signature_ok": sig_ok,
        "signature_header": signature[:200],
        "payload": data,
    })
    if not sig_ok:
        logger.warning(f"[nowpay] webhook signature INVALID for payload={str(data)[:300]}")
        raise HTTPException(status_code=401, detail="Invalid signature")
    order_id = str(data.get("order_id", ""))
    status = (data.get("payment_status") or "").lower()
    logger.info(f"[nowpay] webhook: order={order_id} status={status} amount={data.get('actually_paid')}")
    if not order_id.startswith("funds_") or status not in NOWPAY_SUCCESS_STATUSES:
        return {"ok": True, "ignored": True, "status": status, "order_id": order_id}
    tx_id = order_id.replace("funds_", "", 1)
    tx = await db.transactions.find_one({"id": tx_id})
    if not tx:
        logger.warning(f"[nowpay] unknown tx_id={tx_id}")
        return {"ok": True, "unknown_tx": tx_id}
    return await _credit_nowpayments_deposit(tx, data)


async def _get_nowpayments_jwt(cfg: dict) -> str | None:
    """NOWPayments' /payment/ (list-payments) endpoint requires a JWT Bearer,
    NOT the x-api-key.  If the admin saved email+password, exchange them for a
    JWT via /v1/auth. Returns None if credentials aren't set (caller falls back)."""
    email = (cfg or {}).get("email", "").strip()
    password = (cfg or {}).get("password", "")
    if not email or not password:
        return None
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            f"{NOWPAYMENTS_API_BASE}/auth",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            logger.warning("[nowpay] JWT auth failed %s: %s", r.status_code, r.text[:200])
            return None
        return (r.json() or {}).get("token")


async def _fetch_nowpayments_invoice_status(invoice_id: str) -> dict:
    """Poll NOWPayments for the status of an invoice's payments. Returns the best-status payment doc.
    Uses JWT Bearer auth if the admin saved email+password (required for /payment/), otherwise
    falls back to /invoice/{id} which works with x-api-key."""
    cfg = await _get_nowpayments_config()
    jwt = await _get_nowpayments_jwt(cfg)
    async with httpx.AsyncClient(timeout=20.0) as c:
        if jwt:
            r = await c.get(
                f"{NOWPAYMENTS_API_BASE}/payment/?invoiceId={invoice_id}&limit=10",
                headers={"Authorization": f"Bearer {jwt}"},
            )
            if r.status_code < 400:
                js = r.json()
                payments = js.get("data") or js.get("payments") or ([] if not isinstance(js, list) else js)
                if payments:
                    order = {s: i for i, s in enumerate(["finished", "confirmed", "sending", "partially_paid", "confirming", "waiting", "expired", "failed"])}
                    payments.sort(key=lambda p: order.get((p.get("payment_status") or "").lower(), 99))
                    return payments[0]
            else:
                logger.warning("[nowpay] /payment/ list failed %s: %s", r.status_code, r.text[:200])
        # Fallback: /invoice/{id} (x-api-key auth) — gives us the invoice status
        r = await c.get(
            f"{NOWPAYMENTS_API_BASE}/invoice/{invoice_id}",
            headers={"x-api-key": cfg["api_key"]},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"NOWPayments invoice lookup {r.status_code}: {r.text[:200]}")
        inv = r.json()
    # Normalise invoice → payment-shaped dict so downstream credit logic works
    return {
        "payment_status": (inv.get("payment_status") or inv.get("status") or "").lower(),
        "pay_amount": inv.get("pay_amount"),
        "pay_currency": inv.get("pay_currency"),
        "actually_paid": inv.get("actually_paid") or inv.get("price_amount"),
        "invoice_id": invoice_id,
        "order_id": inv.get("order_id"),
        "_source": "invoice",
    }


@client_router.post("/funds/nowpayments-verify/{tx_id}")
async def nowpayments_verify(tx_id: str, user: CurrentUser = Depends(current_user_dep)):
    """User-triggered fallback if the webhook never fired (network issue / iframe / mobile close).
    Polls NOWPayments API for the invoice's payments; credits the deposit if paid."""
    tx = await db.transactions.find_one({"id": tx_id, "user_id": user.id, "method": "nowpayments"})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.get("status") == "approved":
        return {"ok": True, "already_credited": True, "status": "approved"}
    invoice_id = tx.get("nowpayments_invoice_id")
    if not invoice_id:
        raise HTTPException(status_code=400, detail="No invoice linked to this transaction")
    payment = await _fetch_nowpayments_invoice_status(invoice_id)
    pstatus = (payment.get("payment_status") or "").lower()
    logger.info(f"[nowpay] manual verify tx={tx_id} invoice={invoice_id} status={pstatus}")
    if pstatus in NOWPAY_SUCCESS_STATUSES:
        return await _credit_nowpayments_deposit(tx, payment)
    return {"ok": True, "credited": False, "status": pstatus or "unknown", "payment": payment}


@client_router.get("/funds/pending-deposits")
async def list_pending_deposits(user: CurrentUser = Depends(current_user_dep)):
    """Show the user their unfinished NOWPayments deposits so they can click 'Verify' from the UI."""
    cur = db.transactions.find(
        {"user_id": user.id, "method": "nowpayments", "status": "pending"},
        {"_id": 0, "id": 1, "amount": 1, "created_at": 1, "nowpayments_url": 1, "nowpayments_invoice_id": 1},
    ).sort("created_at", -1).limit(10)
    return {"pending": await cur.to_list(10)}



# ============ SELLY.IO PAYMENTS ============

SELLY_API_BASE = "https://selly.io/api/v2"


async def _get_selly_creds() -> tuple:
    """Fetch the admin-configured Selly API credentials (email, api_key) from DB."""
    cfg = await db.selly_config.find_one({}, {"_id": 0})
    key = (cfg or {}).get("api_key", "").strip()
    email = (cfg or {}).get("email", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="Selly is not configured — admin must set the API key in the Settings tab")
    return email, key


SELLY_VALID_GATEWAYS = {
    "bitcoin", "ethereum", "litecoin", "bitcoin_cash", "dogecoin", "bnb",
    "polygon", "perfect_money", "skrill", "paypal", "stripe", "cashapp",
}


async def _create_selly_invoice(amount_usd: float, title: str, metadata: dict, return_url: str, payment_gateway: str = "bitcoin") -> dict:
    """Create a hosted Selly Payment Request and return {id, url}."""
    email, api_key = await _get_selly_creds()
    gateway = (payment_gateway or "bitcoin").lower().strip()
    if gateway not in SELLY_VALID_GATEWAYS:
        gateway = "bitcoin"
    payload = {
        "title": title[:200],
        "currency": "USD",
        "value": f"{round(float(amount_usd), 2):.2f}",
        "payment_gateway": gateway,
        "return_url": return_url,
        "metadata": metadata,
    }
    # Selly's primary auth = HTTP Basic Auth (email:api_key). Use that if email provided,
    # otherwise fall back to Bearer (some Selly accounts accept token-only).
    auth = (email, api_key) if email else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if not email:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            f"{SELLY_API_BASE}/payment_requests",
            json=payload,
            auth=auth,
            headers=headers,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Selly error {r.status_code}: {r.text[:300]}")
        data = r.json()
    pr = data.get("payment_request") or data
    url = pr.get("url") or pr.get("payment_url") or data.get("url")
    pid = pr.get("id") or data.get("id")
    if not url:
        raise HTTPException(status_code=502, detail=f"Selly did not return checkout URL: {str(data)[:300]}")
    return {"id": pid, "url": url}


async def _verify_selly_payment(payment_id: str) -> dict:
    """Call Selly back to verify payment status. Returns the order/payment_request body."""
    email, api_key = await _get_selly_creds()
    auth = (email, api_key) if email else None
    headers = {"Accept": "application/json"}
    if not email:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=15.0) as c:
        # Try payment_requests first, then orders
        for path in (f"/payment_requests/{payment_id}", f"/orders/{payment_id}"):
            try:
                r = await c.get(
                    f"{SELLY_API_BASE}{path}",
                    auth=auth,
                    headers=headers,
                )
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
    return {}


class SellyFundsRequest(BaseModel):
    amount: float = Field(..., ge=5, le=10000)
    gateway: Optional[str] = "bitcoin"


@client_router.post("/funds/selly-create")
async def selly_create_funds(body: SellyFundsRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Create a Selly payment request to top up user balance."""
    tx_id = str(uuid.uuid4())
    amount = round(float(body.amount), 2)
    origin = request.headers.get("origin", "").rstrip("/") or request.headers.get("referer", "").split("/api")[0]
    # Pre-create a pending deposit row
    await db.transactions.insert_one({
        "id": tx_id,
        "user_id": user.id,
        "username": user.username,
        "amount": amount,
        "method": "selly",
        "status": "pending",
        "type": "deposit",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    invoice = await _create_selly_invoice(
        amount_usd=amount,
        title=f"Better Social — Add ${amount:.2f} for @{user.username}",
        metadata={"kind": "funds", "tx_id": tx_id, "user_id": user.id, "username": user.username, "amount": amount},
        return_url=f"{origin}/client/dashboard?selly_funds=1&tx={tx_id}",
        payment_gateway=body.gateway or "bitcoin",
    )
    await db.transactions.update_one(
        {"id": tx_id},
        {"$set": {"selly_payment_id": invoice["id"], "selly_url": invoice["url"]}},
    )
    return {"id": tx_id, "checkout_url": invoice["url"]}


class SellyCheckoutRequest(BaseModel):
    service_id: int
    link: str
    quantity: int
    customer_email: str
    price_usd: float
    comments: Optional[str] = None
    gateway: Optional[str] = "bitcoin"


@api_router.post("/checkout/selly-create")
async def selly_create_checkout(body: SellyCheckoutRequest, request: Request):
    """Public — Landing-page Selly checkout for one-off service purchase."""
    svc = await db.curated_services.find_one(
        {"service_id": body.service_id, "enabled": True}, {"_id": 0},
    )
    if not svc:
        raise HTTPException(status_code=404, detail="Service not available")
    needs_custom = bool(svc.get("needs_custom_text"))
    comments = (body.comments or "").strip() or None
    if needs_custom and not comments:
        raise HTTPException(status_code=400, detail="This service requires custom comments.")
    order_id = str(uuid.uuid4())
    origin = request.headers.get("origin", "").rstrip("/") or request.headers.get("referer", "").split("/api")[0]
    await db.orders.insert_one({
        "id": order_id,
        "service_id": body.service_id,
        "link": body.link,
        "quantity": body.quantity,
        "price_usd": round(float(body.price_usd), 4),
        "payment_method": "selly",
        "customer_email": body.customer_email or "",
        "ip": get_client_ip(request),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PENDING_PAYMENT",
        "smm_order_id": None,
        "smm_response": None,
        "comments": comments,
        "provider_id": svc.get("provider_id"),
    })
    invoice = await _create_selly_invoice(
        amount_usd=body.price_usd,
        title=f"Better Social — {svc.get('name','order')[:80]}",
        metadata={"kind": "order", "order_id": order_id, "service_id": body.service_id},
        return_url=f"{origin}/?selly_order=1&order={order_id}",
        payment_gateway=body.gateway or "bitcoin",
    )
    await db.orders.update_one({"id": order_id}, {"$set": {"selly_payment_id": invoice["id"]}})
    return {"id": order_id, "checkout_url": invoice["url"]}


def _is_selly_paid_event(event: str, payload: dict) -> bool:
    e = (event or "").lower()
    status = (
        payload.get("status")
        or (payload.get("order") or {}).get("status")
        or (payload.get("payment_request") or {}).get("status")
        or ""
    ).lower()
    return (
        e.endswith(":paid")
        or e.endswith(":completed")
        or e == "order:updated"  # often the "paid" transition fires as updated
        or status in ("paid", "completed")
    )


@api_router.post("/selly/webhook")
async def selly_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad JSON")
    if not isinstance(payload, dict):
        payload = {}
    event = request.headers.get("X-Selly-Event") or request.headers.get("x-selly-event") or ""

    # Extract metadata + payment id
    inner = payload.get("order") or payload.get("payment_request") or payload
    meta = payload.get("metadata") or inner.get("metadata") or {}
    payment_id = (inner.get("id") or payload.get("id") or "").strip() if isinstance(inner, dict) else ""

    # Filter: only process payments that look paid
    if not _is_selly_paid_event(event, payload):
        return {"ok": True, "ignored": event or "unknown"}

    # Callback verification — re-fetch from Selly API to confirm the order is genuinely paid
    if payment_id:
        try:
            verified = await _verify_selly_payment(payment_id)
            v_inner = verified.get("order") or verified.get("payment_request") or verified
            v_status = (v_inner.get("status") or verified.get("status") or "").lower()
            if v_status and v_status not in ("paid", "completed"):
                return {"ok": True, "rejected": f"Selly status is {v_status}"}
            # Use verified metadata if local was empty
            if not meta:
                meta = verified.get("metadata") or v_inner.get("metadata") or {}
        except HTTPException:
            # If we cannot verify (e.g. no API key yet), still process by metadata for resilience
            pass

    kind = meta.get("kind")

    if kind == "funds":
        tx_id = meta.get("tx_id")
        if not tx_id:
            return {"ok": True, "warn": "no tx_id in metadata"}
        tx = await db.transactions.find_one_and_update(
            {"id": tx_id, "status": "pending"},
            {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat(), "selly_event": event}},
        )
        return {"ok": True, "credited": bool(tx)}

    if kind == "order":
        order_id = meta.get("order_id")
        if not order_id:
            return {"ok": True, "warn": "no order_id in metadata"}
        order = await db.orders.find_one({"id": order_id})
        if not order or order.get("smm_order_id"):
            return {"ok": True, "already": True}
        try:
            smm_resp = await place_smm_order(
                order["service_id"], order["link"], order["quantity"],
                comments=order.get("comments"), provider_id=order.get("provider_id"),
            )
            await db.orders.update_one(
                {"id": order_id},
                {"$set": {
                    "status": "Completed",
                    "smm_order_id": smm_resp.get("order"),
                    "smm_response": smm_resp,
                    "paid_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
        except Exception as e:
            await db.orders.update_one(
                {"id": order_id},
                {"$set": {"status": "PAID_SMM_FAILED", "smm_error": str(e)[:300]}},
            )
        return {"ok": True}

    return {"ok": True, "kind": kind or "unknown"}


class EmailConfig(BaseModel):
    smtp_host: Optional[str] = ""
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    from_email: Optional[str] = ""
    from_name: Optional[str] = "Better Social"
    use_tls: bool = True
    mailersend_api_key: Optional[str] = ""


@api_router.get("/admin/email-config")
async def admin_get_email_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.email_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    pw = cfg.get("smtp_password", "")
    ms_key = cfg.get("mailersend_api_key", "")
    return {
        "configured": bool(ms_key or (cfg.get("smtp_host") and cfg.get("smtp_user"))),
        "provider": "mailersend" if ms_key else ("smtp" if cfg.get("smtp_host") else ""),
        "smtp_host": cfg.get("smtp_host", ""),
        "smtp_port": cfg.get("smtp_port", 587),
        "smtp_user": cfg.get("smtp_user", ""),
        "password_set": bool(pw),
        "from_email": cfg.get("from_email", ""),
        "from_name": cfg.get("from_name", "Better Social"),
        "use_tls": cfg.get("use_tls", True),
        "mailersend_set": bool(ms_key),
        "mailersend_api_key_masked": ("*" * 8 + ms_key[-4:]) if ms_key else "",
    }


@api_router.post("/admin/email-config")
async def admin_set_email_config(payload: EmailConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    upd = {
        "smtp_host": (payload.smtp_host or "").strip(),
        "smtp_port": int(payload.smtp_port),
        "smtp_user": (payload.smtp_user or "").strip(),
        "from_email": (payload.from_email or payload.smtp_user or "").strip(),
        "from_name": (payload.from_name or "Better Social").strip(),
        "use_tls": bool(payload.use_tls),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Only update password if a new non-empty one is provided (preserve existing on edits)
    if payload.smtp_password:
        upd["smtp_password"] = payload.smtp_password
    if payload.mailersend_api_key:
        upd["mailersend_api_key"] = payload.mailersend_api_key.strip()
    await db.email_config.update_one(
        {"_id": "singleton"},
        {"$set": upd},
        upsert=True,
    )
    return {"ok": True, "configured": True}


class TestEmailRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=200)


@api_router.post("/admin/email-config/test")
async def admin_send_test_email(payload: TestEmailRequest, x_admin_token: Optional[str] = Header(None)):
    """Send a test email so admin can verify SMTP works without registering a fake user."""
    check_admin(x_admin_token)
    from email_service import send_email, _wrap
    body = _wrap("<h2 style='margin:0 0 12px;color:#fff;'>SMTP test ✅</h2><p>Your SMTP configuration is working. You can safely close this email.</p>")
    res = await send_email(db, payload.to.strip(), "Better Social — SMTP test", body)
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail=res.get("error") or "SMTP send failed")
    return {"ok": True, "to": payload.to.strip()}


class SellyConfig(BaseModel):
    api_key: str = Field(..., min_length=10, max_length=300)
    email: Optional[str] = ""


@api_router.get("/admin/selly-config")
async def admin_get_selly_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.selly_config.find_one({}, {"_id": 0}) or {}
    key = cfg.get("api_key", "")
    return {
        "configured": bool(key),
        "api_key_masked": ("*" * 8 + key[-4:]) if key else "",
        "email": cfg.get("email", ""),
        "webhook_url_hint": "/api/selly/webhook",
    }


@api_router.post("/admin/selly-config")
async def admin_set_selly_config(payload: SellyConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    await db.selly_config.update_one(
        {},
        {"$set": {
            "api_key": payload.api_key.strip(),
            "email": (payload.email or "").strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"configured": True}





@api_router.get("/admin/transactions")
async def admin_list_transactions(
    x_admin_token: Optional[str] = Header(None),
    status: Optional[str] = None,
):
    check_admin(x_admin_token)
    q = {}
    if status:
        q["status"] = status
    items = await db.transactions.find(q, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    return {"transactions": items}


class TxDecision(BaseModel):
    note: Optional[str] = None


@api_router.post("/admin/transactions/{tx_id}/approve")
async def admin_approve_tx(tx_id: str, body: TxDecision, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    res = await db.transactions.find_one_and_update(
        {"id": tx_id, "status": "pending"},
        {"$set": {
            "status": "approved",
            "admin_note": (body.note or "").strip()[:300],
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }},
        return_document=True,
        projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Not a pending transaction")
    return {"ok": True, "transaction": res}


@api_router.post("/admin/transactions/{tx_id}/reject")
async def admin_reject_tx(tx_id: str, body: TxDecision, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    res = await db.transactions.find_one_and_update(
        {"id": tx_id, "status": "pending"},
        {"$set": {
            "status": "rejected",
            "admin_note": (body.note or "").strip()[:300],
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        }},
        return_document=True,
        projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Not a pending transaction")
    return {"ok": True, "transaction": res}


# ============ SUPPORT TICKETS ============

class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=2, max_length=120)
    message: str = Field(..., min_length=2, max_length=4000)


class TicketReply(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


@client_router.post("/tickets")
async def create_ticket(body: TicketCreate, user: CurrentUser = Depends(current_user_dep)):
    now = datetime.now(timezone.utc).isoformat()
    ticket_id = str(uuid.uuid4())
    doc = {
        "id": ticket_id,
        "user_id": user.id,
        "username": user.username,
        "subject": body.subject.strip()[:120],
        "status": "open",  # open | answered | closed
        "created_at": now,
        "updated_at": now,
        "last_reply_by": "user",
    }
    await db.tickets.insert_one(doc.copy())
    await db.ticket_messages.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "author_role": "user",
        "author_name": user.username,
        "message": body.message.strip()[:4000],
        "created_at": now,
    })
    return {"ok": True, "id": ticket_id}


@client_router.get("/tickets")
async def list_my_tickets(user: CurrentUser = Depends(current_user_dep)):
    items = await db.tickets.find(
        {"user_id": user.id},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(100)
    return {"tickets": items}


@client_router.get("/tickets-unread-count")
async def my_tickets_unread_count(user: CurrentUser = Depends(current_user_dep)):
    n = await db.tickets.count_documents({"user_id": user.id, "client_unread": True})
    return {"unread": n}


@client_router.get("/tickets/{ticket_id}")
async def get_my_ticket(ticket_id: str, user: CurrentUser = Depends(current_user_dep)):
    t = await db.tickets.find_one({"id": ticket_id, "user_id": user.id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    msgs = await db.ticket_messages.find(
        {"ticket_id": ticket_id},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    # Mark as read since the client just opened it
    if t.get("client_unread"):
        await db.tickets.update_one({"id": ticket_id}, {"$set": {"client_unread": False}})
    return {"ticket": t, "messages": msgs}


@client_router.post("/tickets/{ticket_id}/reply")
async def reply_my_ticket(ticket_id: str, body: TicketReply, user: CurrentUser = Depends(current_user_dep)):
    t = await db.tickets.find_one({"id": ticket_id, "user_id": user.id}, {"_id": 0, "status": 1})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if t.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Ticket is closed")
    now = datetime.now(timezone.utc).isoformat()
    await db.ticket_messages.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "author_role": "user",
        "author_name": user.username,
        "message": body.message.strip()[:4000],
        "created_at": now,
    })
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"status": "open", "updated_at": now, "last_reply_by": "user", "client_unread": False}},
    )
    return {"ok": True}


# ----- Admin ticket endpoints -----

@api_router.get("/admin/tickets")
async def admin_list_tickets(x_admin_token: Optional[str] = Header(None), status: Optional[str] = None):
    check_admin(x_admin_token, "tickets")
    q = {}
    if status:
        q["status"] = status
    items = await db.tickets.find(q, {"_id": 0}).sort("updated_at", -1).limit(200).to_list(200)
    # waiting = tickets where last reply was by user
    waiting = sum(1 for t in items if t.get("last_reply_by") == "user" and t.get("status") == "open")
    return {"tickets": items, "waiting": waiting}


@api_router.get("/admin/tickets/{ticket_id}")
async def admin_get_ticket(ticket_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "tickets")
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    msgs = await db.ticket_messages.find(
        {"ticket_id": ticket_id},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return {"ticket": t, "messages": msgs}


class AdminTicketReply(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    staff_name: Optional[str] = None  # ignored — author is auto-derived from token


@api_router.post("/admin/tickets/{ticket_id}/reply")
async def admin_reply_ticket(ticket_id: str, body: AdminTicketReply, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "tickets")
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0, "id": 1})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    now = datetime.now(timezone.utc).isoformat()
    author_name = await get_actor_display_name(x_admin_token)
    await db.ticket_messages.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "author_role": "staff",
        "author_name": author_name,
        "message": body.message.strip()[:4000],
        "created_at": now,
    })
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"status": "answered", "updated_at": now, "last_reply_by": "staff", "last_reply_author": author_name, "client_unread": True}},
    )
    return {"ok": True, "author_name": author_name}


@api_router.post("/admin/tickets/{ticket_id}/close")
async def admin_close_ticket(ticket_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "tickets")
    res = await db.tickets.update_one({"id": ticket_id}, {"$set": {"status": "closed"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}


@api_router.delete("/admin/tickets/{ticket_id}")
async def admin_delete_ticket(ticket_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "tickets")
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    await db.ticket_messages.delete_many({"ticket_id": ticket_id})
    await db.tickets.delete_one({"id": ticket_id})
    return {"ok": True, "deleted": ticket_id}


@api_router.get("/admin/cryptomus-config")
async def get_cryptomus_admin_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.cryptomus_config.find_one({}, {"_id": 0})
    if not cfg:
        return {"configured": False}
    return {
        "configured": True,
        "merchant_uuid": cfg.get("merchant_uuid", ""),
        "payment_api_key_masked": ("*" * 8 + cfg.get("payment_api_key", "")[-4:]) if cfg.get("payment_api_key") else "",
    }


# ===== Discord Bot Integration =====
@api_router.get("/admin/discord-config")
async def get_discord_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.discord_config.find_one({}, {"_id": 0})
    if not cfg:
        return {"configured": False, "developer_role_name": "Developer"}
    return {
        "configured": bool(cfg.get("bot_token")),
        "developer_role_name": cfg.get("developer_role_name", "Developer"),
        "bot_token_masked": ("*" * 12 + cfg.get("bot_token", "")[-6:]) if cfg.get("bot_token") else "",
        "shared_secret_masked": ("*" * 8 + cfg.get("shared_secret", "")[-4:]) if cfg.get("shared_secret") else "",
    }


@api_router.post("/admin/discord-config")
async def set_discord_config(payload: DiscordConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = payload.model_dump(exclude_none=True)
    if not doc.get("shared_secret"):
        raise HTTPException(status_code=400, detail="Shared secret is required")
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.discord_config.update_one({}, {"$set": doc}, upsert=True)
    return {"configured": True}


class DiscordOrderRequest(BaseModel):
    service_type: str  # likes|views|comments
    link: str
    quantity: int
    coupon_code: Optional[str] = None
    is_developer: bool = False
    discord_user_id: str
    discord_username: str


@api_router.post("/discord/order")
async def discord_order(
    body: DiscordOrderRequest,
    x_bot_secret: Optional[str] = Header(None),
    request: Request = None,
):
    """Called by the Discord bot. Requires the shared secret."""
    cfg = await db.discord_config.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("shared_secret"):
        raise HTTPException(status_code=503, detail="Discord bot not configured")
    if not x_bot_secret or not hmac.compare_digest(x_bot_secret, cfg["shared_secret"]):
        raise HTTPException(status_code=401, detail="Invalid bot secret")

    # Look up service map
    ai_map = await db.ai_service_map.find_one({}, {"_id": 0}) or {}
    stype = body.service_type.lower()
    if stype not in ("likes", "views", "comments"):
        raise HTTPException(status_code=400, detail="service_type must be likes/views/comments")
    sid = int(ai_map.get(stype, 0) or 0)
    if not sid:
        raise HTTPException(status_code=400, detail=f"Admin hasn't mapped '{stype}' yet.")

    svc = await db.curated_services.find_one({"service_id": sid, "enabled": True}, {"_id": 0})
    if not svc:
        raise HTTPException(status_code=400, detail="Mapped service is not enabled")
    rate = float(svc.get("custom_rate", 0))
    price = round((rate * body.quantity) / 1000.0, 4)
    if body.quantity < int(svc.get("min", 1)) or body.quantity > int(svc.get("max", 10**9)):
        raise HTTPException(status_code=400, detail=f"Quantity must be {svc.get('min')}–{svc.get('max')}")

    coupon_used = None
    # Non-developers MUST provide a valid coupon and pay from it
    if not body.is_developer:
        if not body.coupon_code:
            raise HTTPException(status_code=400, detail="Coupon required for non-developers")
        code = body.coupon_code.strip().upper()
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
        coupon_used = code

    # Place SMM order
    try:
        smm_resp = await place_smm_order(sid, body.link, body.quantity)
    except Exception as e:
        if coupon_used:
            await db.coupons.update_one({"code": coupon_used}, {"$inc": {"balance": price}})
        raise HTTPException(status_code=502, detail=f"SMM error: {e}")
    if "error" in smm_resp:
        if coupon_used:
            await db.coupons.update_one({"code": coupon_used}, {"$inc": {"balance": price}})
        raise HTTPException(status_code=400, detail=f"SMM error: {smm_resp['error']}")

    order_id = str(uuid.uuid4())
    order_doc = {
        "id": order_id,
        "service_id": sid,
        "service_name": svc.get("name"),
        "service_type": stype,
        "link": body.link,
        "quantity": body.quantity,
        "price_usd": price,
        "payment_method": "developer" if body.is_developer else "coupon",
        "coupon_code": coupon_used,
        "customer_email": "",
        "ip": "discord",
        "discord_user_id": body.discord_user_id,
        "discord_username": body.discord_username,
        "is_developer": body.is_developer,
        "source": "discord",
        "status": "completed",
        "smm_order_id": smm_resp.get("order"),
        "smm_response": smm_resp,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc.copy())

    if coupon_used:
        remaining = await db.coupons.find_one({"code": coupon_used}, {"_id": 0, "balance": 1})
        if remaining and remaining.get("balance", 0) <= 0.005:
            await db.coupons.delete_one({"code": coupon_used})

    return {
        "status": "completed",
        "order_id": order_id,
        "smm_order_id": smm_resp.get("order"),
        "price": price,
        "service": svc.get("name"),
    }


@api_router.get("/admin/discord/orders")
async def admin_discord_orders(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    items = await db.orders.find(
        {"source": "discord"},
        {"_id": 0, "smm_response": 0},
    ).sort("created_at", -1).to_list(500)
    return {"orders": items}


@api_router.post("/admin/cryptomus-config")
async def set_cryptomus_admin_config(payload: CryptomusConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = payload.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.cryptomus_config.update_one({}, {"$set": doc}, upsert=True)
    return {"configured": True}


@api_router.get("/admin/coinpayments-config")
async def get_cp_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.coinpayments_config.find_one({}, {"_id": 0})
    if not cfg:
        return {"configured": False}
    # mask private key
    return {
        "configured": True,
        "public_key": cfg.get("public_key", ""),
        "merchant_id": cfg.get("merchant_id", ""),
        "private_key_masked": ("*" * 8 + cfg.get("private_key", "")[-4:]) if cfg.get("private_key") else "",
        "ipn_secret_masked": ("*" * 8 + cfg.get("ipn_secret", "")[-4:]) if cfg.get("ipn_secret") else "",
    }


@api_router.post("/admin/coinpayments-config")
async def set_cp_config(payload: CoinPaymentsConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = payload.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.coinpayments_config.update_one({}, {"$set": doc}, upsert=True)
    return {"configured": True}


# ===== SMM API config =====
@api_router.get("/admin/smm-config")
async def get_smm_admin_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.smm_config.find_one({}, {"_id": 0})
    if not cfg:
        return {
            "configured": False,
            "api_url": SMM_API_URL_DEFAULT,
            "api_key_masked": "*" * 8 + SMM_API_KEY_DEFAULT[-4:],
        }
    return {
        "configured": True,
        "api_url": cfg.get("api_url", ""),
        "api_key_masked": ("*" * 8 + cfg.get("api_key", "")[-4:]) if cfg.get("api_key") else "",
    }


@api_router.post("/admin/smm-config")
async def set_smm_admin_config(payload: SmmConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = payload.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.smm_config.update_one({}, {"$set": doc}, upsert=True)
    return {"configured": True}


# ===== Multiple SMM Providers =====

class SmmProviderCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    api_url: str = Field(..., min_length=10, max_length=300)
    api_key: str = Field(..., min_length=4, max_length=200)
    enabled: bool = True


class SmmProviderUpdate(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None


def _mask_key(k: str) -> str:
    return ("*" * 8 + k[-4:]) if k else ""


@api_router.get("/admin/smm-providers")
async def list_providers(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    items = await db.smm_providers.find({}, {"_id": 0}).sort("created_at", 1).to_list(50)
    # Mask keys in the listing
    for it in items:
        it["api_key_masked"] = _mask_key(it.get("api_key", ""))
        it.pop("api_key", None)
    return {"providers": items}


@api_router.post("/admin/smm-providers")
async def create_provider(payload: SmmProviderCreate, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "api_url": payload.api_url.strip(),
        "api_key": payload.api_key.strip(),
        "enabled": payload.enabled,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.smm_providers.insert_one(doc.copy())
    return {"id": doc["id"], "name": doc["name"]}


@api_router.patch("/admin/smm-providers/{pid}")
async def update_provider(pid: str, payload: SmmProviderUpdate, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    upd = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not upd:
        return {"updated": False}
    res = await db.smm_providers.update_one({"id": pid}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"updated": True}


@api_router.delete("/admin/smm-providers/{pid}")
async def delete_provider(pid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    used = await db.curated_services.count_documents({"provider_id": pid})
    if used > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {used} services still use this provider. Reassign or delete them first.",
        )
    res = await db.smm_providers.delete_one({"id": pid})
    return {"deleted": res.deleted_count}


@api_router.post("/admin/smm-providers/{pid}/sync")
async def sync_provider_services(pid: str, x_admin_token: Optional[str] = Header(None)):
    """Pull catalog from this specific provider and upsert into curated_services tagged with provider_id."""
    check_admin(x_admin_token)
    p = await db.smm_providers.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        data = await smm_request({"action": "services"}, provider_id=pid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from {p['name']}: {e}")
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Provider returned unexpected format")

    added = 0
    updated = 0
    for s in data:
        try:
            sid = int(s.get("service"))
        except (TypeError, ValueError):
            continue
        provider_rate = float(s.get("rate") or 0)
        name_lower = (s.get("name") or "").lower()
        # Auto-detect "needs custom text" (custom comments / mentions etc.)
        # Heuristic: contains "custom" AND NOT "random" / "emoji"
        needs_custom = ("custom" in name_lower) and ("random" not in name_lower) and ("emoji" not in name_lower)
        # Try to capture provider description & parse delivery time
        api_desc = str(s.get("description") or "").strip()
        # Common alternate fields some providers use
        speed_hint = str(s.get("average_time") or s.get("speed") or s.get("delivery") or "").strip()
        combined_hint = " · ".join(x for x in [api_desc, speed_hint] if x)
        parsed_delivery = _parse_delivery_minutes(combined_hint)
        # Composite key: (provider_id, service_id) — but since service_ids can collide across providers we namespace
        existing = await db.curated_services.find_one({"provider_id": pid, "service_id": sid})
        update_doc = {
            "provider_id": pid,
            "provider_name": p["name"],
            "name": s.get("name", ""),
            "category": s.get("category", "Other"),
            "provider_rate": provider_rate,
            "min": int(s.get("min", 1)),
            "max": int(s.get("max", 1000000)),
            "type": s.get("type", "Default"),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if api_desc:
            update_doc["api_description"] = api_desc[:2000]
        if not existing:
            new_doc = {
                "service_id": sid,
                "enabled": False,
                "manual": False,
                "custom_rate": provider_rate,
                "needs_custom_text": needs_custom,
                "description": api_desc[:2000],
                "delivery_minutes": parsed_delivery,
                **update_doc,
            }
            await db.curated_services.insert_one(new_doc.copy())
            added += 1
        else:
            # Only auto-set needs_custom_text on first sync — admin can override later
            if "needs_custom_text" not in existing:
                update_doc["needs_custom_text"] = needs_custom
            # Only auto-set description / delivery on first sync, don't overwrite admin's edits
            if not existing.get("description") and api_desc:
                update_doc["description"] = api_desc[:2000]
            if existing.get("delivery_minutes") is None and parsed_delivery is not None:
                update_doc["delivery_minutes"] = parsed_delivery
            await db.curated_services.update_one(
                {"provider_id": pid, "service_id": sid},
                {"$set": update_doc},
            )
            updated += 1
    return {"added": added, "updated": updated, "provider": p["name"]}


# ===== Curated services =====
@api_router.post("/admin/services/add-by-id")
async def add_service_by_id(payload: dict, x_admin_token: Optional[str] = Header(None)):
    """Body: {service_id: int}. Fetches the single service from provider and upserts it."""
    check_admin(x_admin_token)
    try:
        sid = int(payload.get("service_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="service_id must be an integer")

    try:
        data = await smm_request({"action": "services"})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from provider: {e}")
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Provider returned unexpected format")

    match = None
    for s in data:
        try:
            if int(s.get("service")) == sid:
                match = s
                break
        except (TypeError, ValueError):
            continue
    if not match:
        raise HTTPException(status_code=404, detail=f"Service #{sid} not found at provider")

    provider_rate = float(match.get("rate") or 0)
    base = {
        "name": match.get("name", ""),
        "category": match.get("category", "Other"),
        "provider_rate": provider_rate,
        "min": int(match.get("min", 1)),
        "max": int(match.get("max", 1000000)),
        "type": match.get("type", "Default"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    existing = await db.curated_services.find_one({"service_id": sid})
    if existing:
        await db.curated_services.update_one({"service_id": sid}, {"$set": base})
        return {"action": "updated", "service_id": sid, "name": base["name"], "enabled": existing.get("enabled", False)}
    new_doc = {"service_id": sid, "enabled": False, "custom_rate": provider_rate, **base}
    await db.curated_services.insert_one(new_doc.copy())
    return {"action": "added", "service_id": sid, "name": base["name"], "enabled": False}


@api_router.post("/admin/services/sync")
async def sync_services(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    try:
        data = await smm_request({"action": "services"})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from provider: {e}")
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Provider returned unexpected format")

    added = 0
    updated = 0
    for s in data:
        try:
            sid = int(s.get("service"))
        except (TypeError, ValueError):
            continue
        provider_rate = float(s.get("rate") or 0)
        existing = await db.curated_services.find_one({"service_id": sid})
        update_doc = {
            "name": s.get("name", ""),
            "category": s.get("category", "Other"),
            "provider_rate": provider_rate,
            "min": int(s.get("min", 1)),
            "max": int(s.get("max", 1000000)),
            "type": s.get("type", "Default"),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if not existing:
            new_doc = {
                "service_id": sid,
                "enabled": False,
                "custom_rate": provider_rate,
                **update_doc,
            }
            await db.curated_services.insert_one(new_doc.copy())
            added += 1
        else:
            await db.curated_services.update_one({"service_id": sid}, {"$set": update_doc})
            updated += 1
    total = await db.curated_services.count_documents({})
    return {"added": added, "updated": updated, "total": total}


@api_router.get("/admin/services")
async def list_curated(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    items = await db.curated_services.find({}, {"_id": 0}).sort("service_id", 1).to_list(5000)
    return {"services": items}


@api_router.post("/admin/services/manual")
async def create_manual_service(payload: ManualServiceCreate, x_admin_token: Optional[str] = Header(None)):
    """Create a custom/manual service that isn't tied to any SMM API provider.
    Admin manually fulfills the order after payment confirms."""
    check_admin(x_admin_token)
    # Pick a unique negative service_id (so it never collides with provider IDs which are positive)
    last = await db.curated_services.find_one(
        {"manual": True}, {"_id": 0, "service_id": 1}, sort=[("service_id", 1)]
    )
    next_sid = -1
    if last and isinstance(last.get("service_id"), int):
        next_sid = min(-1, int(last["service_id"]) - 1)
    doc = {
        "service_id": next_sid,
        "manual": True,
        "enabled": True,
        "name": payload.name.strip()[:200],
        "custom_name": "",
        "description": (payload.description or "").strip()[:2000],
        "category": (payload.category or "Custom").strip()[:60],
        "price_flat": round(float(payload.price_usd), 2),
        "custom_rate": 0,
        "provider_rate": 0,
        "delivery_minutes": int(payload.delivery_minutes or 60),
        "min": 1,
        "max": 1,
        "type": "manual",
        "needs_custom_text": False,
        "provider_id": None,
        "provider_name": "Manual",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.curated_services.insert_one(doc.copy())
    return {"service_id": next_sid, "name": doc["name"]}


@api_router.delete("/admin/services/{service_id}")
async def delete_service(service_id: int, x_admin_token: Optional[str] = Header(None)):
    """Delete any service (manual or API) from the catalog."""
    check_admin(x_admin_token)
    res = await db.curated_services.delete_one({"service_id": service_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"deleted": True}


@api_router.patch("/admin/services/{service_id}")
async def update_curated(service_id: int, payload: ServiceUpdate, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    raw = payload.model_dump(exclude_unset=True)
    update_doc = {}
    unset_doc = {}
    for k, v in raw.items():
        if k == "custom_name":
            # empty string => clear the override
            if v is None or str(v).strip() == "":
                unset_doc["custom_name"] = ""
            else:
                update_doc["custom_name"] = str(v).strip()[:200]
        elif v is not None:
            update_doc[k] = v
    if not update_doc and not unset_doc:
        return {"updated": False}
    ops = {}
    if update_doc:
        ops["$set"] = update_doc
    if unset_doc:
        ops["$unset"] = unset_doc
    res = await db.curated_services.update_one({"service_id": service_id}, ops)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"updated": True}


@api_router.post("/admin/services/{service_id}/rename-id")
async def rename_service_id(service_id: int, payload: dict, x_admin_token: Optional[str] = Header(None)):
    """Change the numeric `service_id` of an existing service. Fails if the new id
    is already used. Rewrites the id in-place in `curated_services` only — historical
    orders keep their original service_id snapshot so past data stays consistent."""
    check_admin(x_admin_token)
    try:
        new_id = int(payload.get("new_service_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="new_service_id must be an integer")
    if new_id <= 0:
        raise HTTPException(status_code=400, detail="new_service_id must be positive")
    if new_id == service_id:
        return {"updated": False, "reason": "same id"}
    if await db.curated_services.find_one({"service_id": new_id}, {"_id": 0, "service_id": 1}):
        raise HTTPException(status_code=409, detail=f"Service ID {new_id} is already in use")
    r = await db.curated_services.update_one({"service_id": service_id}, {"$set": {"service_id": new_id}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    logger.info("[admin] service_id %s renamed to %s", service_id, new_id)
    return {"updated": True, "old_service_id": service_id, "new_service_id": new_id}


@api_router.post("/admin/services/bulk")
async def bulk_update(payload: dict, x_admin_token: Optional[str] = Header(None)):
    """Body: {action: 'enable_all'|'disable_all'|'apply_markup', percent?: 30}"""
    check_admin(x_admin_token)
    action = payload.get("action")
    if action == "enable_all":
        r = await db.curated_services.update_many({}, {"$set": {"enabled": True}})
        return {"modified": r.modified_count}
    if action == "disable_all":
        r = await db.curated_services.update_many({}, {"$set": {"enabled": False}})
        return {"modified": r.modified_count}
    if action == "delete_all":
        r = await db.curated_services.delete_many({})
        return {"deleted": r.deleted_count}
    if action == "apply_markup":
        try:
            pct = float(payload.get("percent", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid percent")
        items = await db.curated_services.find({}, {"_id": 0, "service_id": 1, "provider_rate": 1}).to_list(5000)
        modified = 0
        for it in items:
            new_rate = round(float(it.get("provider_rate", 0)) * (1 + pct / 100.0), 6)
            await db.curated_services.update_one(
                {"service_id": it["service_id"]}, {"$set": {"custom_rate": new_rate}}
            )
            modified += 1
        return {"modified": modified, "percent": pct}
    raise HTTPException(status_code=400, detail="Unknown action")


app.include_router(api_router)

# Auth/chat/client/ai routers were imported at the top
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(client_router)
app.include_router(ai_router)

# Direct messaging + WebRTC call signaling
from messaging import msg_router, calls_router, admin_msg_router, admin_calls_router  # noqa: E402
app.include_router(msg_router, prefix="/api")
app.include_router(calls_router, prefix="/api")
app.include_router(admin_msg_router, prefix="/api")
app.include_router(admin_calls_router, prefix="/api")

app.state.db = db
app.state.place_smm_order = place_smm_order
app.state.check_admin = check_admin
app.state.get_actor_display_name = get_actor_display_name
app.state.get_user_balance = _get_user_balance
app.state.get_user_withdrawable = _get_user_withdrawable


@app.on_event("startup")
async def _startup():
    await seed_owner(db)
    # Restore owner display nickname from DB
    global OWNER_DISPLAY_NAME
    cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "owner_display_name": 1})
    if cfg and cfg.get("owner_display_name"):
        OWNER_DISPLAY_NAME = cfg["owner_display_name"]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
