from fastapi import FastAPI, APIRouter, HTTPException, Request, Header, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import os
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
        "smm_order_id": smm_order_id,
        "charge": charge,
        "balance": new_balance,
    }


@client_router.get("/transactions")
async def get_my_transactions(user: CurrentUser = Depends(current_user_dep)):
    items = await db.transactions.find(
        {"user_id": user.id},
        {"_id": 0},
    ).sort("created_at", -1).limit(100).to_list(100)
    return {"transactions": items}


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
    Tip announcements (kind='tip') don't count toward the rate window — otherwise a user
    would be locked out of normal chat for 3s right after tipping."""
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
        "role": user.role or "user",
        "text": payload.text.strip()[:500],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.public_chat.insert_one(doc.copy())
    # Keep only the last 500 messages to bound the collection
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
    return {"ok": True, "amount": amount, "recipient": recipient["username"], "tip_id": tip_id}


# ============ Weekly Spin Wheel ============

SPIN_MIN_DEPOSIT = 50.0  # user must have at least $50 lifetime deposits to spin
# Weighted prizes: (amount, weight). Higher weight = more likely.
# Odds engineered so the expected payout is ~$1.70 per spin (well below cost floor).
SPIN_PRIZES = [
    (1,  450),   # 45.00%
    (2,  250),   # 25.00%
    (3,  150),   # 15.00%
    (4,   80),   #  8.00%
    (5,   40),   #  4.00%
    (6,   25),   #  2.50%
    (40,   5),   #  0.50% JACKPOT (1 in 200)
]


@api_router.get("/spin/status")
async def spin_status(user: CurrentUser = Depends(current_user_dep)):
    """Returns eligibility + when the user last spun.
    Eligible = lifetime approved deposits >= $50 AND hasn't spun in the last 7 days."""
    total = await _user_deposits_total(user.id)
    eligible = total >= SPIN_MIN_DEPOSIT
    last = await db.spin_wheel.find_one({"user_id": user.id}, sort=[("created_at", -1)], projection={"_id": 0})
    can_spin = eligible
    days_left = 0
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < 7 * 24 * 3600:
                can_spin = False
                days_left = max(0, 7 - int(gap / 86400))
        except Exception:
            pass
    return {
        "eligible": eligible,
        "can_spin": can_spin,
        "days_left": days_left,
        "last_spin": last,
        "prizes": [p[0] for p in SPIN_PRIZES],
        "min_deposit": SPIN_MIN_DEPOSIT,
        "total_deposits": round(total, 2),
        "amount_needed": max(0, round(SPIN_MIN_DEPOSIT - total, 2)),
    }


@api_router.post("/spin/spin")
async def spin_wheel(user: CurrentUser = Depends(current_user_dep)):
    """One free spin per week. Weighted RNG toward low prizes + rare $40 jackpot.
    Only users with lifetime deposits >= $50 can spin."""
    total = await _user_deposits_total(user.id)
    if total < SPIN_MIN_DEPOSIT:
        raise HTTPException(status_code=403, detail=f"You need at least ${SPIN_MIN_DEPOSIT:.0f} lifetime deposits to spin. You have ${total:.2f}.")
    last = await db.spin_wheel.find_one({"user_id": user.id}, sort=[("created_at", -1)])
    if last and last.get("created_at"):
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds()
            if gap < 7 * 24 * 3600:
                days_left = max(1, 7 - int(gap / 86400))
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
            "text": f"🎰 JACKPOT — just won ${prize} on the weekly spin!",
            "kind": "jackpot",
            "created_at": now,
        })
    return {"ok": True, "prize": prize, "jackpot": is_jackpot, "spin_id": spin_id, "next_spin_days": 7}



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
async def sim5_buy(payload: Sim5BuyRequest, user: CurrentUser = Depends(current_user_dep)):
    if payload.product not in SIM5_PRODUCTS:
        raise HTTPException(status_code=400, detail=f"Unsupported service. Choose one of: {', '.join(SIM5_PRODUCTS)}")
    cfg = await _get_sim5_config()
    if not cfg["api_key"]:
        raise HTTPException(status_code=503, detail="Phone-number service is not configured yet.")
    retail = float(cfg["prices"].get(payload.product, 0))
    if retail <= 0:
        raise HTTPException(status_code=503, detail="This service is not for sale right now.")
    balance = await _get_user_balance(user.id)
    if balance < retail:
        raise HTTPException(status_code=400, detail=f"Not enough balance — need ${retail:.2f}, you have ${balance:.2f}")
    country = (payload.country or cfg["default_country"] or "any").strip().lower()
    operator = (payload.operator or cfg["default_operator"] or "any").strip().lower()
    status, data = await _sim5_call("GET", f"/user/buy/activation/{country}/{operator}/{payload.product}", cfg["api_key"])
    if status >= 400:
        # Common 5sim errors: no free phones, order booked etc.
        msg = data if isinstance(data, str) else data.get("detail") or str(data)
        raise HTTPException(status_code=502, detail=f"5sim: {msg[:200]}")
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
async def sim5_my_orders(user: CurrentUser = Depends(current_user_dep)):
    cur = db.sim5_orders.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(20)
    return {"orders": await cur.to_list(20)}


@api_router.get("/5sim/orders/{oid}")
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
        raise HTTPException(status_code=503, detail="5sim not configured")
    endpoint = "finish" if action == "finish" else "cancel"
    status, data = await _sim5_call("GET", f"/user/{endpoint}/{order['sim5_id']}", cfg["api_key"])
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"5sim: {data}")
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
async def sim5_finish_order(oid: str, user: CurrentUser = Depends(current_user_dep)):
    return await _sim5_finalize(oid, user, "finish")


@api_router.post("/5sim/orders/{oid}/cancel")
async def sim5_cancel_order(oid: str, user: CurrentUser = Depends(current_user_dep)):
    return await _sim5_finalize(oid, user, "cancel")




class UIConfig(BaseModel):
    use_new_home_layout: bool = False


@api_router.get("/ui-config")
async def get_public_ui_config():
    """Public read — client-side dashboards fetch this to pick which layout to render."""
    cfg = await db.ui_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {"use_new_home_layout": bool(cfg.get("use_new_home_layout", False))}


@api_router.get("/admin/ui-config")
async def admin_get_ui_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.ui_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {"use_new_home_layout": bool(cfg.get("use_new_home_layout", False))}


@api_router.post("/admin/ui-config")
async def admin_set_ui_config(payload: UIConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    await db.ui_config.update_one(
        {"_id": "singleton"},
        {"$set": {"use_new_home_layout": bool(payload.use_new_home_layout), "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True, "use_new_home_layout": bool(payload.use_new_home_layout)}



class NowpaymentsFundsRequest(BaseModel):
    amount: float = Field(..., ge=1, le=10000)


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


async def _fetch_nowpayments_invoice_status(invoice_id: str) -> dict:
    """Poll NOWPayments for the status of an invoice's payments. Returns the best-status payment doc."""
    cfg = await _get_nowpayments_config()
    async with httpx.AsyncClient(timeout=20.0) as c:
        # First: get payments linked to this invoice
        r = await c.get(
            f"{NOWPAYMENTS_API_BASE}/payment/?invoice_id={invoice_id}&limit=10",
            headers={"x-api-key": cfg["api_key"]},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"NOWPayments payments lookup {r.status_code}: {r.text[:200]}")
        js = r.json()
    payments = js.get("data") or js.get("payments") or ([] if not isinstance(js, list) else js)
    if not payments:
        return {}
    # Prefer the payment with a success status; else return the most recent one
    order = {s: i for i, s in enumerate(["finished", "confirmed", "sending", "partially_paid", "confirming", "waiting", "expired", "failed"])}
    payments.sort(key=lambda p: order.get((p.get("payment_status") or "").lower(), 99))
    return payments[0]


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
