from fastapi import FastAPI, APIRouter, HTTPException, Request, Header, Depends, Body
from fastapi.responses import FileResponse
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
STAFF_PERMS = {
    "tickets", "ai_inbox", "orders", "discord", "withdrawals",
    # Extended perms (Feb 2026) — owner can grant each individually to any mod.
    "services", "providers", "users", "coupons", "giveaways",
    "payments", "deposits", "livesubs", "aiactions", "backups",
    "reports", "settings", "sim5", "games", "invoices", "audit",
}

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
    optional_current_user_dep,
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
    - Owner keeps a customisable nickname (via /admin/me/nickname).
    - Staff ALWAYS shows their login username to clients — no custom display name."""
    if not token:
        return "Support"
    if token in ADMIN_SESSIONS:
        # Owner — use persisted nickname (falls back to in-mem default)
        cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "owner_display_name": 1})
        return (cfg or {}).get("owner_display_name") or OWNER_DISPLAY_NAME or "Owner"
    s = STAFF_SESSIONS.get(token)
    if s:
        # Staff → always their login username (per product decision — no display_name)
        return s.get("username") or "Staff"
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

        # Guest / customer email confirmation (best-effort)
        try:
            from notification_service import notify_guest_order_placed
            backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
            asyncio.create_task(notify_guest_order_placed(db, req.customer_email or "", {**base_doc, "service_name": (svc or {}).get("name")}, backend_url))
        except Exception:
            pass

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
    totp_code: Optional[str] = None


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
    # 2FA gate — enforced on staff/owner just like the client login.
    if u.get("totp_enabled") and u.get("totp_secret"):
        import pyotp
        code = (getattr(payload, "totp_code", None) or "").strip()
        if not code:
            raise HTTPException(status_code=401, detail="TOTP_REQUIRED")
        totp = pyotp.TOTP(u["totp_secret"])
        recovery = code.upper().replace("-", "").replace(" ", "")
        if not totp.verify(code, valid_window=1):
            backups = u.get("totp_recovery", []) or []
            if recovery in backups:
                await db.users.update_one({"id": u["id"]}, {"$pull": {"totp_recovery": recovery}})
            else:
                raise HTTPException(status_code=401, detail="Invalid 2FA code")
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


# ============ Support shifts + online team roster ============
@api_router.get("/team/online")
async def team_online_public():
    """PUBLIC — returns team members currently on-shift so the AI/support
    widget can render an avatar stack ("Hi there — how can we help?")."""
    cursor = db.users.find(
        {"on_shift": True, "role": {"$in": ["owner", "admin", "moderator"]}, "banned": {"$ne": True}},
        {"_id": 0, "id": 1, "username": 1, "role": 1, "display_name": 1, "avatar_color": 1},
    ).limit(10)
    team = await cursor.to_list(10)
    if not team:
        # Always advertise at least the brand so the widget never looks empty
        team = [{"username": "BetterSocial", "role": "system", "display_name": "Better Social", "avatar_color": "emerald"}]
    return {"team": team}


class ShiftToggleReq(BaseModel):
    on_shift: bool


@api_router.post("/admin/shift/toggle")
async def admin_shift_toggle(payload: ShiftToggleReq, x_admin_token: Optional[str] = Header(None)):
    """Any team member (owner/admin/mod) flips their own on-shift status."""
    if x_admin_token not in ADMIN_SESSIONS and x_admin_token not in STAFF_SESSIONS:
        raise HTTPException(status_code=401, detail="Not authorized")
    now = datetime.now(timezone.utc).isoformat()
    sess = STAFF_SESSIONS.get(x_admin_token)
    if sess and sess.get("id"):
        await db.users.update_one(
            {"id": sess["id"]},
            {"$set": {"on_shift": bool(payload.on_shift), "last_shift_change": now}},
        )
        return {"ok": True, "on_shift": bool(payload.on_shift), "username": sess.get("username")}
    owner_username = os.environ.get("OWNER_USERNAME", "Balkin")
    await db.users.update_one(
        {"username": owner_username},
        {"$set": {"on_shift": bool(payload.on_shift), "last_shift_change": now}},
    )
    return {"ok": True, "on_shift": bool(payload.on_shift), "username": owner_username}


@api_router.get("/admin/shift/mine")
async def admin_shift_mine(x_admin_token: Optional[str] = Header(None)):
    """Return the caller's current on-shift flag so the toggle can hydrate."""
    if x_admin_token not in ADMIN_SESSIONS and x_admin_token not in STAFF_SESSIONS:
        raise HTTPException(status_code=401, detail="Not authorized")
    sess = STAFF_SESSIONS.get(x_admin_token)
    username = (sess or {}).get("username") if sess else os.environ.get("OWNER_USERNAME", "Balkin")
    u = await db.users.find_one({"username": username}, {"_id": 0, "on_shift": 1, "role": 1, "username": 1})
    return {"on_shift": bool((u or {}).get("on_shift")), "username": username, "role": (u or {}).get("role")}


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
        # Staff: display_name is locked to their login username — no custom nickname.
        return {
            "role": "staff",
            "username": s["username"],
            "display_name": s["username"],
            "perms": list(s["perms"]),
        }
    raise HTTPException(status_code=401, detail="Unauthorized")


class NicknameUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=40)


@api_router.post("/admin/me/nickname")
async def update_my_nickname(payload: NicknameUpdate, x_admin_token: Optional[str] = Header(None)):
    """Owner nickname setter. Staff members CANNOT customise a display name —
    they always show their login username to clients."""
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
    # Staff can't change their display name — return their username unchanged.
    raise HTTPException(status_code=403, detail="Staff cannot change display name — you always show your login username to clients.")


# ============ MAINTENANCE MODE ============
# Persisted in app_settings.maintenance = { enabled: bool, message: str }.
# Public endpoint (GET) returns current state so the frontend can gate access.
# Admin endpoint (PATCH) requires OWNER token to toggle.

@api_router.get("/maintenance")
async def get_maintenance():
    """Public — frontend polls this to know whether to render the maintenance screen."""
    cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "maintenance": 1}) or {}
    m = cfg.get("maintenance") or {}
    return {
        "enabled": bool(m.get("enabled")),
        "message": m.get("message") or "We're doing quick maintenance — we'll be back in a few minutes.",
        "updated_at": m.get("updated_at"),
    }


# ============ FEATURE TOGGLES ============
# Admin can hide entire dashboard sections (Sports, Numbers, Games, Add-ons,
# Live orders, etc.). Non-privileged users won't see the tab in the sidebar
# and the direct route becomes a friendly "not available" screen.

DEFAULT_FEATURES = {
    "numbers": True,
    "games": True,
    "addons": True,
    "live_orders": True,
    "coupons": True,
    "invoices": True,
    "messages": True,
    "tickets": True,
    "tos": True,
}


@api_router.get("/features")
async def get_features():
    """Public — returns the current feature-toggle map."""
    cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "features": 1}) or {}
    stored = cfg.get("features") or {}
    return {"features": {**DEFAULT_FEATURES, **stored}}


class FeaturesUpdate(BaseModel):
    features: dict


@api_router.patch("/admin/features")
async def admin_set_features(payload: FeaturesUpdate, x_admin_token: Optional[str] = Header(None)):
    """Owner-only — persist a feature-toggle map. Only known keys are stored."""
    check_owner(x_admin_token)
    clean = {}
    for k, v in (payload.features or {}).items():
        if k in DEFAULT_FEATURES:
            clean[k] = bool(v)
    if not clean:
        raise HTTPException(status_code=400, detail="No valid feature keys provided")
    await db.app_settings.update_one(
        {"_id": "singleton"},
        {"$set": {"features": {**DEFAULT_FEATURES, **clean}, "features_updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True, "features": {**DEFAULT_FEATURES, **clean}}


class MaintenanceUpdate(BaseModel):
    enabled: bool
    message: Optional[str] = None


@api_router.patch("/admin/maintenance")
async def admin_set_maintenance(payload: MaintenanceUpdate, x_admin_token: Optional[str] = Header(None)):
    """Owner-only — toggle maintenance mode + optional custom message."""
    check_owner(x_admin_token)
    upd = {
        "enabled": bool(payload.enabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.message is not None:
        upd["message"] = payload.message[:500]
    await db.app_settings.update_one(
        {"_id": "singleton"},
        {"$set": {"maintenance": upd}},
        upsert=True,
    )
    return {"ok": True, "maintenance": upd}




@api_router.get("/admin/orders")
async def admin_orders(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "orders")
    orders = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"orders": orders}


# ============ ADMIN BULK GIFT ORDERS ============
# Admin fires the same set of SMM services against a target URL for one or many
# users. Bypasses balance (this is a gift/marketing bump). Each (user × service)
# combo becomes its own order row so users see them in their own history.

class BulkGiftItem(BaseModel):
    service_id: int = Field(..., description="Curated service ID (matches int stored in DB)")
    quantity: int = Field(..., ge=1, le=1_000_000)


class BulkGiftRequest(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, max_length=200, description="One or many recipient user IDs")
    services: List[BulkGiftItem] = Field(..., min_length=1, max_length=20)
    link: str = Field(..., min_length=3, max_length=500, description="Target URL for every order in this bulk")
    comments: Optional[str] = Field(default="", max_length=8000)
    note: Optional[str] = Field(default="", max_length=200, description="Admin-only note stored on the order")


@api_router.post("/admin/bulk-order")
async def admin_bulk_order(payload: BulkGiftRequest, request: Request, x_admin_token: Optional[str] = Header(None)):
    """Fire one order per (user × service) — free gift, no balance deducted."""
    check_admin(x_admin_token, "orders")
    place_smm_order = request.app.state.place_smm_order
    now = datetime.now(timezone.utc).isoformat()
    link = payload.link.strip()
    comments = (payload.comments or "").strip() or None

    results = []
    ok_count = 0
    fail_count = 0

    for uid in payload.user_ids:
        user_doc = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "username": 1, "email": 1})
        if not user_doc:
            results.append({"user_id": uid, "ok": False, "error": "user_not_found"})
            fail_count += 1
            continue

        for item in payload.services:
            svc = await db.curated_services.find_one({"service_id": item.service_id, "enabled": True}, {"_id": 0})
            if not svc:
                results.append({"user_id": uid, "username": user_doc.get("username"), "service_id": item.service_id, "ok": False, "error": "service_not_available"})
                fail_count += 1
                continue

            is_manual = bool(svc.get("manual"))
            order_id = str(uuid.uuid4())

            if is_manual:
                order_doc = {
                    "id": order_id,
                    "smm_order_id": None,
                    "service_id": item.service_id,
                    "service_name": (svc.get("custom_name") or svc.get("name") or ""),
                    "link": link,
                    "quantity": int(item.quantity),
                    "charge": 0.0,
                    "customer_email": "",
                    "user_id": uid,
                    "username": user_doc.get("username"),
                    "payment_method": "admin_gift",
                    "source": "admin_bulk",
                    "status": "awaiting_manual_fulfillment",
                    "manual": True,
                    "delivery_minutes": svc.get("delivery_minutes"),
                    "created_at": now,
                    "comments": comments,
                    "provider_id": None,
                    "admin_note": payload.note or None,
                    "is_gift": True,
                }
                await db.orders.insert_one(order_doc.copy())
                ok_count += 1
                results.append({"user_id": uid, "username": user_doc.get("username"), "service_id": item.service_id, "ok": True, "order_id": order_id, "manual": True})
                continue

            try:
                smm_resp = await place_smm_order(
                    item.service_id, link, int(item.quantity),
                    comments=comments, provider_id=svc.get("provider_id"),
                )
            except HTTPException as he:
                results.append({"user_id": uid, "username": user_doc.get("username"), "service_id": item.service_id, "ok": False, "error": str(he.detail)})
                fail_count += 1
                continue
            except Exception as e:
                results.append({"user_id": uid, "username": user_doc.get("username"), "service_id": item.service_id, "ok": False, "error": f"provider_exception:{e}"})
                fail_count += 1
                continue

            smm_order_id = smm_resp.get("order")
            if not smm_order_id:
                results.append({"user_id": uid, "username": user_doc.get("username"), "service_id": item.service_id, "ok": False, "error": f"provider:{smm_resp.get('error') or smm_resp}"})
                fail_count += 1
                continue

            order_doc = {
                "id": order_id,
                "smm_order_id": smm_order_id,
                "service_id": item.service_id,
                "service_name": (svc.get("custom_name") or svc.get("name") or ""),
                "link": link,
                "quantity": int(item.quantity),
                "charge": 0.0,
                "customer_email": "",
                "user_id": uid,
                "username": user_doc.get("username"),
                "payment_method": "admin_gift",
                "source": "admin_bulk",
                "status": "Pending",
                "created_at": now,
                "comments": comments,
                "provider_id": svc.get("provider_id"),
                "admin_note": payload.note or None,
                "is_gift": True,
            }
            await db.orders.insert_one(order_doc.copy())
            ok_count += 1
            results.append({"user_id": uid, "username": user_doc.get("username"), "service_id": item.service_id, "ok": True, "order_id": order_id, "smm_order_id": smm_order_id})

    return {"ok": True, "sent": ok_count, "failed": fail_count, "results": results}


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
        if payload.role not in {"user", "admin", "moderator", "owner"}:
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


@api_router.post("/admin/paypal-config-legacy")
async def admin_set_paypal_config_legacy(payload: PaypalConfig, x_admin_token: Optional[str] = Header(None)):
    """LEGACY — kept for backwards compat with the old paypal.me URL flow. The new
    IPN auto-credit flow lives at POST /admin/paypal-config."""
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


# ============ Referral rewards ============
async def _referral_config() -> dict:
    cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "referral_config": 1}) or {}
    rc = cfg.get("referral_config") or {}
    return {
        "enabled": bool(rc.get("enabled", True)),
        "reward_usd": float(rc.get("reward_usd", 5.0)),
        "friend_bonus_pct": float(rc.get("friend_bonus_pct", 5.0)),
    }


async def _get_or_create_referral_code(user_id: str, username: str) -> str:
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "referral_code": 1})
    if u and u.get("referral_code"):
        return u["referral_code"]
    base = re.sub(r"[^A-Z0-9]", "", (username or "REF").upper())[:10] or "REF"
    for _ in range(6):
        code = f"{base}{uuid.uuid4().hex[:4].upper()}"
        if not await db.users.find_one({"referral_code": code}, {"_id": 0, "id": 1}):
            await db.users.update_one({"id": user_id}, {"$set": {"referral_code": code}})
            return code
    code = uuid.uuid4().hex[:10].upper()
    await db.users.update_one({"id": user_id}, {"$set": {"referral_code": code}})
    return code


async def _maybe_referral_rewards(user_id: str) -> None:
    """Called after any deposit credit. On the friend's FIRST approved deposit:
    referrer gets a fixed reward (balance + withdrawable), friend gets +N% bonus."""
    try:
        cfg = await _referral_config()
        if not cfg["enabled"]:
            return
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "referred_by": 1, "referral_rewarded": 1, "username": 1})
        if not u or not u.get("referred_by") or u.get("referral_rewarded"):
            return
        # Atomic claim so concurrent webhooks can't double-pay.
        r = await db.users.update_one(
            {"id": user_id, "referral_rewarded": {"$ne": True}},
            {"$set": {"referral_rewarded": True, "referral_rewarded_at": datetime.now(timezone.utc).isoformat()}},
        )
        if r.modified_count == 0:
            return
        first = await db.transactions.find_one(
            {"user_id": user_id, "type": "deposit", "status": "approved", "amount": {"$gt": 0}},
            {"_id": 0, "amount": 1, "id": 1},
            sort=[("approved_at", 1)],
        )
        if not first:
            await db.users.update_one({"id": user_id}, {"$unset": {"referral_rewarded": "", "referral_rewarded_at": ""}})
            return
        now = datetime.now(timezone.utc).isoformat()
        ref = await db.users.find_one({"id": u["referred_by"]}, {"_id": 0, "id": 1, "username": 1})
        reward = round(cfg["reward_usd"], 2)
        if ref and reward > 0:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": ref["id"], "username": ref.get("username"),
                "amount": reward, "method": "referral", "status": "approved",
                "type": "referral_reward",
                "note": f"Referral reward — @{u.get('username')} made their first deposit",
                "referred_user_id": user_id, "created_at": now, "approved_at": now,
            })
            # Also withdrawable, per product decision.
            await db.users.update_one({"id": ref["id"]}, {"$inc": {"withdrawable_balance": reward}})
        pct = cfg["friend_bonus_pct"]
        bonus = round(float(first["amount"]) * pct / 100.0, 2) if pct > 0 else 0.0
        if bonus > 0:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": user_id, "username": u.get("username"),
                "amount": bonus, "method": "bonus", "status": "approved",
                "type": "referral_friend_bonus",
                "note": f"+{pct:g}% referral welcome bonus on your first deposit",
                "linked_tx": first["id"], "created_at": now, "approved_at": now,
            })
        logger.info("[referral] paid referrer=%s $%.2f, friend=%s bonus=$%.2f", u.get("referred_by"), reward, user_id, bonus)
    except Exception as e:
        logger.warning("[referral] reward processing failed for user=%s: %s", user_id, e)


@client_router.get("/referrals")
async def client_referrals(user: CurrentUser = Depends(current_user_dep)):
    cfg = await _referral_config()
    code = await _get_or_create_referral_code(user.id, user.username)
    friends = await db.users.find(
        {"referred_by": user.id},
        {"_id": 0, "username": 1, "created_at": 1, "referral_rewarded": 1},
    ).sort("created_at", -1).to_list(200)
    rows = await db.transactions.find(
        {"user_id": user.id, "type": "referral_reward"}, {"_id": 0, "amount": 1},
    ).to_list(1000)

    def _mask(n):
        n = n or ""
        return (n[0] + "***" + n[-1]) if len(n) > 2 else "***"

    return {
        "code": code,
        "enabled": cfg["enabled"],
        "reward_usd": cfg["reward_usd"],
        "friend_bonus_pct": cfg["friend_bonus_pct"],
        "earned_total": round(sum(float(x["amount"]) for x in rows), 2),
        "invited": [
            {"username": _mask(f.get("username")), "joined_at": f.get("created_at"),
             "deposited": bool(f.get("referral_rewarded"))}
            for f in friends
        ],
    }


class ReferralCfgBody(BaseModel):
    enabled: bool = True
    reward_usd: float = Field(5.0, ge=0, le=1000)
    friend_bonus_pct: float = Field(5.0, ge=0, le=100)


@api_router.get("/admin/referral-config")
async def admin_referral_config_get(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    return await _referral_config()


@api_router.post("/admin/referral-config")
async def admin_referral_config_set(body: ReferralCfgBody, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    await db.app_settings.update_one(
        {"_id": "singleton"},
        {"$set": {"referral_config": {"enabled": body.enabled, "reward_usd": round(body.reward_usd, 2), "friend_bonus_pct": round(body.friend_bonus_pct, 2)}}},
        upsert=True,
    )
    return {"ok": True, **(await _referral_config())}


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
    await _maybe_referral_rewards(user.id)
    new_balance = await _get_user_balance(user.id)
    return {"ok": True, "amount": round(bal, 2), "bonus": bonus, "balance": new_balance, "code": code}


class BuyWithBalanceRequest(BaseModel):
    service_id: int
    link: str = Field(..., min_length=4, max_length=400)
    quantity: int = Field(..., gt=0)
    comments: Optional[str] = None  # Required for custom-text services


# ============ Discount keys (percent-off on services — NEVER addons) ============
class DiscountKeyCreate(BaseModel):
    percent: float = Field(..., gt=0, le=100)
    code: Optional[str] = None
    max_uses: Optional[int] = Field(default=None, ge=1)


@api_router.get("/admin/discount-keys")
async def admin_discount_keys_list(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    keys = await db.discount_keys.find({}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return {"keys": keys}


@api_router.post("/admin/discount-keys")
async def admin_discount_keys_create(body: DiscountKeyCreate, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    code = (body.code or "").strip().upper() or ("DISC-" + uuid.uuid4().hex[:8].upper())
    if await db.discount_keys.find_one({"code": code}):
        raise HTTPException(status_code=409, detail="Code already exists")
    doc = {
        "code": code, "percent": round(float(body.percent), 2),
        "max_uses": body.max_uses, "uses": 0, "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.discount_keys.insert_one(doc.copy())
    return {"ok": True, "key": doc}


@api_router.delete("/admin/discount-keys/{code}")
async def admin_discount_keys_delete(code: str, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    c = code.strip().upper()
    r = await db.discount_keys.delete_one({"code": c})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    await db.users.update_many({"discount_code": c}, {"$unset": {"discount_code": "", "discount_pct": ""}})
    return {"ok": True}


class DiscountRedeemBody(BaseModel):
    code: str = Field(..., min_length=3, max_length=40)


@client_router.post("/discount/redeem")
async def client_discount_redeem(body: DiscountRedeemBody, user: CurrentUser = Depends(current_user_dep)):
    code = body.code.strip().upper()
    key = await db.discount_keys.find_one({"code": code, "active": True}, {"_id": 0})
    if not key:
        raise HTTPException(status_code=404, detail="Invalid discount key")
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "discount_code": 1})
    if (u or {}).get("discount_code") != code:
        # Atomic use-count increment — refuses once max_uses is hit even under concurrency.
        r = await db.discount_keys.update_one(
            {"code": code, "active": True,
             "$or": [{"max_uses": None}, {"max_uses": {"$exists": False}},
                     {"$expr": {"$lt": [{"$ifNull": ["$uses", 0]}, "$max_uses"]}}]},
            {"$inc": {"uses": 1}},
        )
        if r.modified_count == 0:
            raise HTTPException(status_code=400, detail="This discount key has reached its usage limit")
    await db.users.update_one({"id": user.id}, {"$set": {"discount_code": code, "discount_pct": float(key["percent"])}})
    return {"ok": True, "percent": float(key["percent"]), "code": code}


@client_router.get("/discount")
async def client_discount_get(user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "discount_code": 1, "discount_pct": 1})
    pct = float((u or {}).get("discount_pct") or 0)
    code = (u or {}).get("discount_code")
    if code and pct > 0:
        key = await db.discount_keys.find_one({"code": code, "active": True})
        if not key:
            await db.users.update_one({"id": user.id}, {"$unset": {"discount_code": "", "discount_pct": ""}})
            return {"code": None, "percent": 0}
    return {"code": code, "percent": pct}


async def _apply_user_discount(user_id: str, charge: float) -> tuple:
    """Return (discounted_charge, pct). Applies the user's active discount key.
    Services only — addon purchases must never call this."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "discount_pct": 1, "discount_code": 1})
    pct = float((u or {}).get("discount_pct") or 0)
    if pct <= 0:
        return charge, 0.0
    key = await db.discount_keys.find_one({"code": (u or {}).get("discount_code"), "active": True})
    if not key:
        await db.users.update_one({"id": user_id}, {"$unset": {"discount_code": "", "discount_pct": ""}})
        return charge, 0.0
    return round(charge * (1 - pct / 100.0), 4), pct


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
    await _enforce_username_blacklist(user.id, body.link)
    charge, _disc_pct = await _apply_user_discount(user.id, charge)
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
        await _notify_discord_purchase(order_doc)
        new_balance = await _get_user_balance(user.id)
        return {
            "ok": True,
            "manual": True,
            "order_id": order_doc["id"],
            "smm_order_id": None,
            "charge": charge,
            "balance": new_balance,
        }

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
    await _notify_discord_purchase(order_doc)
    new_balance = await _get_user_balance(user.id)
    # Fire-and-forget order confirmation email
    try:
        from notification_service import notify_order_placed
        backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
        asyncio.create_task(notify_order_placed(db, user.id, order_doc, backend_url))
    except Exception as _e:
        logger.warning(f"[notify] order-placed email failed: {_e}")
    return {
        "ok": True,
        "order_id": order_doc["id"],
        "smm_order_id": smm_order_id,
        "charge": charge,
        "balance": new_balance,
    }


class MultiOrderItem(BaseModel):
    service_id: int
    quantity: int = Field(..., gt=0)
    comments: Optional[str] = None


class MultiOrderRequest(BaseModel):
    link: str = Field(..., min_length=4, max_length=400)
    items: List[MultiOrderItem] = Field(..., min_length=1, max_length=15)


@client_router.post("/orders/multi")
async def place_multi_order(body: MultiOrderRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Place N orders for the same target URL in one atomic call.

    Prices are calculated for every item first. If total > balance the whole
    request is rejected before any provider call. Balance is debited only for
    items that succeed; the response contains per-item results so the UI can
    show partial-success clearly.
    """
    db: AsyncIOMotorDatabase = request.app.state.db
    place_smm_order = request.app.state.place_smm_order
    link = body.link.strip()
    await _enforce_username_blacklist(user.id, link)

    # 1) Resolve all services + charges up-front
    priced = []  # list of (item, svc_doc, charge, is_manual, comments)
    for item in body.items:
        svc = await db.curated_services.find_one({"service_id": item.service_id, "enabled": True}, {"_id": 0})
        if not svc:
            raise HTTPException(status_code=404, detail=f"Service #{item.service_id} not available")
        is_manual = bool(svc.get("manual"))
        if is_manual:
            charge = round(float(svc.get("price_flat") or 0), 2)
            if charge <= 0:
                raise HTTPException(status_code=400, detail=f"Service #{item.service_id} price not set")
        else:
            rate = float(svc.get("custom_rate", 0))
            if rate <= 0:
                raise HTTPException(status_code=400, detail=f"Service #{item.service_id} price not set")
            mn = int(svc.get("min", 1) or 1)
            mx = int(svc.get("max", 100000) or 100000)
            if item.quantity < mn or item.quantity > mx:
                raise HTTPException(status_code=400, detail=f"Service #{item.service_id}: qty must be between {mn} and {mx}")
            charge = round((rate * item.quantity) / 1000.0, 4)
        needs_custom = bool(svc.get("needs_custom_text"))
        comments = (item.comments or "").strip() or None
        if needs_custom and not comments:
            raise HTTPException(status_code=400, detail=f"Service #{item.service_id} needs custom comments")
        charge, _dp = await _apply_user_discount(user.id, charge)
        priced.append((item, svc, charge, is_manual, comments))

    total_charge = round(sum(p[2] for p in priced), 4)
    balance = await _get_user_balance(user.id)
    if balance < total_charge:
        raise HTTPException(status_code=402, detail=f"Not enough balance — total ${total_charge:.2f}, you have ${balance:.2f}")

    # 2) Fire each order sequentially. Per-item failures don't abort the run.
    now = datetime.now(timezone.utc).isoformat()
    results = []
    debited = 0.0
    order_ids: List[str] = []

    for (item, svc, charge, is_manual, comments) in priced:
        order_id = str(uuid.uuid4())
        base_doc = {
            "id": order_id,
            "service_id": item.service_id,
            "service_name": (svc.get("custom_name") or svc.get("name") or ""),
            "link": link,
            "quantity": item.quantity,
            "charge": charge,
            "customer_email": "",
            "user_id": user.id,
            "username": user.username,
            "payment_method": "balance",
            "source": "dashboard_multi",
            "created_at": now,
            "comments": comments,
            "provider_id": svc.get("provider_id"),
            "multi_batch": True,
        }

        if is_manual:
            # Debit immediately for manual orders
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user.id,
                "username": user.username,
                "amount": -charge,
                "method": "balance",
                "status": "approved",
                "type": "order",
                "service_id": item.service_id,
                "created_at": now,
                "approved_at": now,
            })
            debited += charge
            order_doc = {
                **base_doc,
                "smm_order_id": None,
                "status": "awaiting_manual_fulfillment",
                "manual": True,
                "delivery_minutes": svc.get("delivery_minutes"),
            }
            await db.orders.insert_one(order_doc.copy())
            await _notify_discord_purchase(order_doc)
            order_ids.append(order_id)
            results.append({"service_id": item.service_id, "service_name": order_doc["service_name"], "ok": True, "order_id": order_id, "smm_order_id": None, "charge": charge, "manual": True})
            continue

        # Provider call
        try:
            smm_resp = await place_smm_order(item.service_id, link, item.quantity, comments=comments, provider_id=svc.get("provider_id"))
        except HTTPException as he:
            results.append({"service_id": item.service_id, "service_name": base_doc["service_name"], "ok": False, "error": str(he.detail), "charge": 0})
            continue
        except Exception as e:
            results.append({"service_id": item.service_id, "service_name": base_doc["service_name"], "ok": False, "error": f"provider_exception:{e}", "charge": 0})
            continue

        smm_order_id = smm_resp.get("order")
        if not smm_order_id:
            results.append({"service_id": item.service_id, "service_name": base_doc["service_name"], "ok": False, "error": f"provider:{smm_resp.get('error') or smm_resp}", "charge": 0})
            continue

        # Debit for successful order
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user.id,
            "username": user.username,
            "amount": -charge,
            "method": "balance",
            "status": "approved",
            "type": "order",
            "service_id": item.service_id,
            "smm_order_id": smm_order_id,
            "created_at": now,
            "approved_at": now,
        })
        debited += charge
        order_doc = {**base_doc, "smm_order_id": smm_order_id, "status": "Pending"}
        await db.orders.insert_one(order_doc.copy())
        await _notify_discord_purchase(order_doc)
        order_ids.append(order_id)
        results.append({"service_id": item.service_id, "service_name": base_doc["service_name"], "ok": True, "order_id": order_id, "smm_order_id": smm_order_id, "charge": charge})

    new_balance = await _get_user_balance(user.id)
    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count

    # Send a single roll-up email if at least one order succeeded.
    try:
        if ok_count > 0:
            from notification_service import notify_order_placed
            backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
            first_ok = next((r for r in results if r.get("ok")), None)
            if first_ok:
                summary_doc = {
                    "id": first_ok["order_id"],
                    "service_name": f"{ok_count} services (multi-order)",
                    "quantity": sum(p[0].quantity for i, p in enumerate(priced) if results[i].get("ok")),
                    "charge": round(debited, 4),
                    "link": link,
                    "created_at": now,
                }
                asyncio.create_task(notify_order_placed(db, user.id, summary_doc, backend_url))
    except Exception as _e:
        logger.warning(f"[notify] multi-order email failed: {_e}")

    return {
        "ok": True,
        "placed": ok_count,
        "failed": fail_count,
        "total_charged": round(debited, 4),
        "balance": new_balance,
        "order_ids": order_ids,
        "results": results,
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
        # One consolidated Discord notification for the whole bulk purchase.
        if order_docs:
            rollup = {
                "username": user.username,
                "service_name": svc_name,
                "quantity": f"{len(order_docs)} × {body.quantity}",
                "charge": charged,
            }
            await _notify_discord_purchase(rollup)

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
    {
        "id": "auto_live_week",
        "name": "Auto-Live · 1-Week Pass",
        "tagline": "One-tap 7-day Auto-Live boost — no strings",
        "description": "Unlocks Auto-Live for 7 days from purchase. Pick any target, we'll fire bursts each time they go live. Auto-expires after 7 days — no recurring charge.",
        "price": 80.0,
        "features": [
            "Auto-Live active for 7 full days",
            "Same automatic bursts every 10 min while live",
            "No renewal — expires cleanly after 7 days",
            "Balance-charged, one-time $80",
        ],
        "flag": "auto_live_expires_at",
        "grants_days": 7,
    },
    {
        "id": "username_blacklist",
        "name": "Username Blacklist (2 slots)",
        "tagline": "Block up to 2 TikTok usernames from ever being targeted",
        "description": "Prevents anyone (including you) from placing Auto-Live or bulk orders against the listed usernames. Perfect for protecting your own accounts or competitor handles you never want touched. 2 slots included per purchase — buy again to add more.",
        "price": 100.0,
        "features": [
            "Blocks Auto-Live provisioning on the listed handles",
            "Blocks manual bulk orders on those handles",
            "2 slots per purchase (buy again for more)",
            "Edit / remove entries any time",
        ],
        "flag": "blacklist_slots",
        "grants_slots": 2,
    },
    {
        "id": "id_finder",
        "name": "Find User By ID — Unlimited",
        "tagline": "Reverse-lookup any numeric TikTok user ID — unlimited finds, forever",
        "description": "Unlocks the User-ID reverse lookup on the TikTok Finder page. Paste any numeric TikTok user ID and get the @handle plus full profile stats (country, creation date, followers, likes, verification). One-time payment — unlimited checks forever.",
        "price": 200.0,
        "currency": "EUR",
        "features": [
            "Unlimited Finds — no caps, no cooldowns, ever",
            "If the user blocks you — still findable",
            "If they change their username — we find the new handle",
            "Full profile snapshot with every lookup (country, followers, likes, verified)",
            "Works on the public TikTok Finder page",
            "One-time €200 — permanent access",
        ],
        "flag": "id_finder",
    },
    {
        "id": "blacklist_package",
        "name": "BlackList Username Package",
        "tagline": "Protect a username on Kick · TikTok · Instagram · Snapchat · Telegram",
        "description": "Pick a platform and lock a username. Once blacklisted, no other user can place orders targeting that username. Short links like vm.tiktok are rejected on order forms, so live-stream orders must go through plain usernames — nothing can bypass your protection. 1 slot per purchase — buy again to stack more.",
        "price": 180.0,
        "currency": "EUR",
        "features": [
            "Choose platform: Kick · TikTok · Instagram · Snapchat · Telegram",
            "Blocks everyone else from ordering on the protected username",
            "vm.tiktok / short-link orders are rejected — only plain usernames for live streams",
            "Protection applies to Auto-Live, bulk and normal orders",
            "1 slot per purchase — stack as many as you need",
        ],
        "flag": "blacklist_slots",
        "grants_slots": 1,
        "platforms": ["tiktok", "kick", "instagram", "snapchat", "telegram"],
    },
]


_EURUSD_CACHE = {"rate": 1.09, "at": 0.0}


async def _eur_usd_rate() -> float:
    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts - _EURUSD_CACHE["at"] < 6 * 3600:
        return _EURUSD_CACHE["rate"]
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://open.er-api.com/v6/latest/EUR")
            v = float((r.json().get("rates") or {}).get("USD") or 0)
            if v > 0:
                _EURUSD_CACHE.update({"rate": v, "at": now_ts})
    except Exception:
        pass
    return _EURUSD_CACHE["rate"]


async def _addon_price_usd(addon: dict) -> float:
    """Wallet is USD — EUR-priced addons convert at the live EUR→USD rate."""
    price = float(addon["price"])
    if (addon.get("currency") or "USD").upper() == "EUR":
        return round(price * await _eur_usd_rate(), 2)
    return round(price, 2)


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
            {**a, "owned": bool(owned_flags.get(a["id"])), "price_usd": await _addon_price_usd(a)}
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
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1, "auto_live_expires_at": 1, "addons": 1, "blacklist_slots": 1})
    owned = ((u or {}).get("addons") or [])
    # `auto_live_week` and `username_blacklist` are stackable / repeatable — always allow re-purchase.
    if addon["id"] in owned and addon["id"] not in ("auto_live_week", "username_blacklist", "blacklist_package"):
        raise HTTPException(status_code=400, detail="You already own this addon.")
    if (u or {}).get("auto_live_enabled") and addon["id"] == "auto_live" and not (u or {}).get("auto_live_expires_at"):
        raise HTTPException(status_code=400, detail="You already own this addon.")
    price = await _addon_price_usd(addon)
    balance = await _get_user_balance(user.id)
    if balance < price:
        cur_note = f" ({addon['price']:.2f} EUR)" if (addon.get("currency") or "").upper() == "EUR" else ""
        raise HTTPException(status_code=402, detail=f"Not enough balance — needs ${price:.2f}{cur_note}, you have ${balance:.2f}")
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
    set_fields = {}
    inc_fields = {}
    if addon["id"] == "auto_live":
        set_fields["auto_live_enabled"] = True
    if addon["id"] == "auto_live_week":
        # Grant 7 days of Auto-Live — extend if user already has an unexpired pass.
        from datetime import timedelta as _td
        current = (u or {}).get("auto_live_expires_at")
        base = datetime.now(timezone.utc)
        if current:
            try:
                cur_dt = datetime.fromisoformat(current)
                if cur_dt.tzinfo is None:
                    cur_dt = cur_dt.replace(tzinfo=timezone.utc)
                if cur_dt > base:
                    base = cur_dt
            except (ValueError, TypeError):
                pass
        set_fields["auto_live_expires_at"] = (base + _td(days=int(addon.get("grants_days", 7)))).isoformat()
        set_fields["auto_live_enabled"] = True
        # The week pass is repeatable — never mark it as owned so the user can buy again to extend.
        update = {"$set": set_fields}
    elif addon["id"] in ("username_blacklist", "blacklist_package"):
        inc_fields["blacklist_slots"] = int(addon.get("grants_slots", 2))
        # Also repeatable — buying stacks another 2 slots.
        update = {"$inc": inc_fields}
    if set_fields and addon["id"] != "auto_live_week":
        update["$set"] = set_fields
    await db.users.update_one({"id": user.id}, update)
    new_balance = await _get_user_balance(user.id)
    return {"ok": True, "balance": new_balance, "addon": addon["id"]}


@client_router.get("/addons/mine")
async def addons_mine(user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1, "auto_live_expires_at": 1, "addons": 1, "blacklist_slots": 1})
    owned = set((u or {}).get("addons") or [])
    if (u or {}).get("auto_live_enabled"):
        owned.add("auto_live")
    return {
        "owned": sorted(owned),
        "auto_live_expires_at": (u or {}).get("auto_live_expires_at"),
        "blacklist_slots": int((u or {}).get("blacklist_slots") or 0),
    }


# ============ Username Blacklist addon ============
BLACKLIST_PLATFORMS = {"tiktok", "kick", "instagram", "snapchat", "telegram"}


class BlacklistEntryBody(BaseModel):
    tiktok_username: str
    platform: Optional[str] = "tiktok"
    reason: Optional[str] = None


@client_router.get("/addons/blacklist")
async def blacklist_list(user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "blacklist_slots": 1})
    entries = await db.username_blacklist.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    slots = int((u or {}).get("blacklist_slots") or 0)
    return {"entries": entries, "slots_total": slots, "slots_used": len(entries), "slots_free": max(0, slots - len(entries))}


@client_router.post("/addons/blacklist")
async def blacklist_add(body: BlacklistEntryBody, user: CurrentUser = Depends(current_user_dep)):
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "blacklist_slots": 1})
    slots = int((u or {}).get("blacklist_slots") or 0)
    used = await db.username_blacklist.count_documents({"user_id": user.id})
    if used >= slots:
        raise HTTPException(status_code=402, detail=f"No free blacklist slots — you have {slots}. Buy the Username Blacklist addon for +2 slots.")
    handle = (body.tiktok_username or "").strip().lstrip("@")
    if not handle:
        raise HTTPException(status_code=400, detail="Handle is required")
    platform = (body.platform or "tiktok").strip().lower()
    if platform not in BLACKLIST_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Platform must be one of: {', '.join(sorted(BLACKLIST_PLATFORMS))}")
    if await db.username_blacklist.find_one({"user_id": user.id, "tiktok_username": handle.lower(), "platform": platform}):
        raise HTTPException(status_code=409, detail="This handle is already on your blacklist")
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "tiktok_username": handle.lower(),
        "platform": platform,
        "reason": (body.reason or "").strip()[:200] or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.username_blacklist.insert_one(doc)
    return {"ok": True, "entry": {k: v for k, v in doc.items() if k != "_id"}}


@client_router.delete("/addons/blacklist/{entry_id}")
async def blacklist_remove(entry_id: str, user: CurrentUser = Depends(current_user_dep)):
    r = await db.username_blacklist.delete_one({"id": entry_id, "user_id": user.id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


async def _is_handle_blacklisted(user_id: str, handle: str) -> bool:
    """Return True if the given TikTok handle is on ANY user's blacklist
    (owner-scoped: we still block the requester if the handle is on their own list)."""
    h = (handle or "").strip().lstrip("@").lower()
    if not h:
        return False
    return bool(await db.username_blacklist.find_one({"tiktok_username": h}))


def _extract_handles_from_link(link: str) -> list:
    """Pull candidate usernames out of an order link or plain handle."""
    s = (link or "").strip().lower()
    out = set()
    for m in re.finditer(r"@([a-z0-9._-]{2,60})", s):
        out.add(m.group(1))
    m = re.search(r"(?:kick\.com|instagram\.com|snapchat\.com/add|t\.me|tiktok\.com)/@?([a-z0-9._-]{2,60})", s)
    if m:
        out.add(m.group(1))
    if re.fullmatch(r"@?[a-z0-9._-]{2,60}", s):
        out.add(s.lstrip("@"))
    return [h for h in out if h not in ("live", "add", "www")]


async def _enforce_username_blacklist(user_id: str, link: str) -> None:
    """Reject orders that target a username protected by another user's
    BlackList Package. Short links (vm.tiktok / vt.tiktok) are always rejected
    because they can hide a protected username."""
    s = (link or "").strip().lower()
    if "vm.tiktok.com" in s or "vt.tiktok.com" in s:
        raise HTTPException(status_code=400, detail="Short links (vm.tiktok) are not allowed — enter the plain @username or the full profile link instead.")
    for h in _extract_handles_from_link(link):
        entry = await db.username_blacklist.find_one({"tiktok_username": h})
        if entry and entry.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail=f"@{h} is protected by a BlackList Username Package — orders on this username are blocked.")


# ============ IP-based language auto-detect (Balkan-first) ============
# Maps country codes to the locale we serve. Balkans lean to Serbian by default;
# each specific country lands on its own language if we support it.
COUNTRY_TO_LANG = {
    "RS": "sr", "ME": "sr", "MK": "sr",           # Serbia, Montenegro, N. Macedonia → Serbian
    "BA": "bs",                                     # Bosnia → Bosnian
    "HR": "sr", "SI": "sr",                         # Croatia, Slovenia → Serbian (closest we have)
    "BG": "sr",                                     # Bulgaria → Serbian (closest Cyrillic-friendly)
    "AL": "sr", "XK": "sr",                         # Albania, Kosovo → Serbian
    "DE": "de", "AT": "de", "CH": "de", "LI": "de",
    "ES": "es",
    "PT": "pt", "BR": "pt",
}


@api_router.get("/geo/detect-language")
async def geo_detect_language(request: Request):
    """Return the visitor's country code (best-effort from IP headers) and the
    language we recommend. Client uses this on first load to auto-switch."""
    xff = request.headers.get("x-forwarded-for") or ""
    ip = (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")) or ""
    country = (request.headers.get("cf-ipcountry")
               or request.headers.get("x-vercel-ip-country")
               or request.headers.get("x-country")
               or "").upper().strip()
    # Fallback: hit a free geo-IP endpoint (ip-api.com allows 45 req/min anonymously).
    if not country and ip and not ip.startswith(("127.", "10.", "192.168.")):
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"http://ip-api.com/json/{ip}?fields=countryCode")
                if r.status_code == 200:
                    country = (r.json() or {}).get("countryCode") or ""
        except Exception:
            pass
    lang = COUNTRY_TO_LANG.get(country) or None
    return {"ip": ip, "country": country or None, "recommended_lang": lang}


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
TIKTOK_CHECK_INTERVAL_SEC = 45          # 45 seconds — how often we PING TikTok live-status
TIKTOK_ALLOWED_REPEAT_MINUTES = [2, 5, 10, 60]
LIVE_SUB_ALLOWED_DAYS = [7, 14, 30, 60, 90, 365]
# When mode=live_only AND target is LIVE: fire instantly on every offline→live
# transition, then one order per `repeat_every_minutes` while they stay live.
# If the target never goes live within 5 minutes of ordering → cancel + refund.


async def _tt_probe_apilive(handle: str, headers: dict) -> Optional[bool]:
    """Probe TikTok's api-live/user/room endpoint (the one the official web
    player uses). user.status == 2 means LIVE, 4 means offline/ended.
    Returns True/False when definitive, None when the probe couldn't decide.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            r = await c.get(
                "https://www.tiktok.com/api-live/user/room/",
                params={"aid": "1988", "sourceType": "54", "uniqueId": handle},
                headers=headers,
            )
    except Exception as e:
        logger.debug("[livesub] api-live probe network error for %s: %s", handle, e)
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    try:
        if int(data.get("statusCode") or 0) != 0:
            return None
    except (TypeError, ValueError):
        return None
    inner = (data or {}).get("data") or {}
    user = inner.get("user") or {}
    live_room = inner.get("liveRoom") or {}
    st = user.get("status") if isinstance(user, dict) else None
    if st is None and isinstance(live_room, dict):
        st = live_room.get("status")
    if st is None:
        return None
    try:
        return int(st) == 2
    except (TypeError, ValueError):
        return None



# ============ Free public TikTok lookup (no auth) ============
# Heuristic country resolver — no external API. Combines:
#   1) flag emoji in the bio (🇩🇪 🇷🇸 …)                — highest confidence
#   2) explicit country / city keywords in the bio       — high confidence
#   3) TikTok's own `region` field                       — high confidence when present
#   4) TikTok's `language` code hint                     — fallback

# ISO country → human name (short, US-English)
_COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany", "AT": "Austria",
    "CH": "Switzerland", "FR": "France", "IT": "Italy", "ES": "Spain", "PT": "Portugal",
    "NL": "Netherlands", "BE": "Belgium", "SE": "Sweden", "NO": "Norway", "FI": "Finland",
    "DK": "Denmark", "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia", "HU": "Hungary",
    "RO": "Romania", "BG": "Bulgaria", "GR": "Greece", "TR": "Turkey", "RU": "Russia",
    "UA": "Ukraine", "BY": "Belarus", "RS": "Serbia", "HR": "Croatia", "SI": "Slovenia",
    "BA": "Bosnia and Herzegovina", "ME": "Montenegro", "MK": "North Macedonia",
    "AL": "Albania", "XK": "Kosovo", "IE": "Ireland", "IS": "Iceland",
    "CA": "Canada", "MX": "Mexico", "BR": "Brazil", "AR": "Argentina", "CL": "Chile",
    "CO": "Colombia", "PE": "Peru", "VE": "Venezuela",
    "AU": "Australia", "NZ": "New Zealand", "JP": "Japan", "KR": "South Korea",
    "CN": "China", "TW": "Taiwan", "HK": "Hong Kong", "SG": "Singapore",
    "TH": "Thailand", "VN": "Vietnam", "PH": "Philippines", "ID": "Indonesia",
    "MY": "Malaysia", "IN": "India", "PK": "Pakistan", "BD": "Bangladesh",
    "SA": "Saudi Arabia", "AE": "UAE", "IL": "Israel", "EG": "Egypt", "MA": "Morocco",
    "DZ": "Algeria", "TN": "Tunisia", "ZA": "South Africa", "NG": "Nigeria",
}
# TikTok `language` code → default country when no other hint fires
_LANG_TO_COUNTRY = {
    "de": "DE", "sr": "RS", "hr": "HR", "bs": "BA", "sl": "SI", "mk": "MK",
    "sq": "AL", "bg": "BG", "ro": "RO", "hu": "HU", "cs": "CZ", "sk": "SK",
    "pl": "PL", "ru": "RU", "uk": "UA", "es": "ES", "pt": "PT", "fr": "FR",
    "it": "IT", "nl": "NL", "sv": "SE", "no": "NO", "da": "DK", "fi": "FI",
    "tr": "TR", "ar": "SA", "he": "IL", "el": "GR", "ja": "JP", "ko": "KR",
    "zh": "CN", "th": "TH", "vi": "VN", "id": "ID", "ms": "MY", "hi": "IN",
}
# Bio keyword → country. Case-insensitive, matched as whole word or substring.
# Includes big cities, countries in local language, and common shorthand.
_BIO_KEYWORDS = {
    "DE": ["deutschland", "germany", "berlin", "hamburg", "münchen", "munich", "köln", "cologne", "frankfurt", "leipzig", "dortmund", "stuttgart", "🇩🇪"],
    "AT": ["österreich", "austria", "wien", "vienna", "graz", "salzburg", "linz", "🇦🇹"],
    "CH": ["schweiz", "switzerland", "zürich", "zurich", "basel", "geneva", "genf", "bern", "lausanne", "🇨🇭"],
    "RS": ["serbia", "srbija", "beograd", "belgrade", "novi sad", "niš", "kragujevac", "🇷🇸"],
    "HR": ["croatia", "hrvatska", "zagreb", "split", "rijeka", "osijek", "dubrovnik", "🇭🇷"],
    "BA": ["bosnia", "bosna", "sarajevo", "banja luka", "mostar", "tuzla", "zenica", "🇧🇦"],
    "ME": ["montenegro", "crna gora", "podgorica", "budva", "kotor", "🇲🇪"],
    "MK": ["macedonia", "makedonija", "skopje", "bitola", "🇲🇰"],
    "SI": ["slovenia", "slovenija", "ljubljana", "maribor", "🇸🇮"],
    "AL": ["albania", "shqipëri", "shqiperia", "tirana", "durrës", "🇦🇱"],
    "BG": ["bulgaria", "българия", "sofia", "plovdiv", "varna", "🇧🇬"],
    "GR": ["greece", "hellas", "ελλάδα", "athens", "thessaloniki", "🇬🇷"],
    "TR": ["türkiye", "turkey", "istanbul", "ankara", "izmir", "antalya", "🇹🇷"],
    "PL": ["poland", "polska", "warsaw", "warszawa", "kraków", "cracow", "wrocław", "🇵🇱"],
    "RU": ["russia", "россия", "moscow", "москва", "st petersburg", "санкт-петербург", "🇷🇺"],
    "UA": ["ukraine", "україна", "kyiv", "kiev", "lviv", "odesa", "🇺🇦"],
    "GB": ["united kingdom", "england", "london", "manchester", "birmingham", "liverpool", "🇬🇧"],
    "US": ["usa", "united states", "america", "new york", "los angeles", "california", "texas", "florida", "chicago", "miami", "🇺🇸"],
    "CA": ["canada", "toronto", "vancouver", "montreal", "ottawa", "🇨🇦"],
    "AU": ["australia", "sydney", "melbourne", "brisbane", "perth", "🇦🇺"],
    "FR": ["france", "paris", "lyon", "marseille", "toulouse", "🇫🇷"],
    "IT": ["italy", "italia", "rome", "roma", "milan", "milano", "naples", "napoli", "🇮🇹"],
    "ES": ["spain", "españa", "madrid", "barcelona", "valencia", "sevilla", "🇪🇸"],
    "PT": ["portugal", "lisbon", "lisboa", "porto", "🇵🇹"],
    "NL": ["netherlands", "nederland", "amsterdam", "rotterdam", "🇳🇱"],
    "BR": ["brazil", "brasil", "são paulo", "rio de janeiro", "🇧🇷"],
    "MX": ["mexico", "méxico", "cdmx", "guadalajara", "monterrey", "🇲🇽"],
    "JP": ["japan", "日本", "tokyo", "osaka", "kyoto", "🇯🇵"],
    "KR": ["korea", "한국", "seoul", "busan", "🇰🇷"],
    "IN": ["india", "mumbai", "delhi", "bangalore", "bengaluru", "🇮🇳"],
    "SA": ["saudi arabia", "riyadh", "jeddah", "🇸🇦"],
    "AE": ["dubai", "abu dhabi", "united arab emirates", "uae", "🇦🇪"],
    "MA": ["morocco", "maroc", "casablanca", "rabat", "🇲🇦"],
    "EG": ["egypt", "مصر", "cairo", "🇪🇬"],
    "ID": ["indonesia", "jakarta", "bali", "🇮🇩"],
    "PH": ["philippines", "manila", "cebu", "🇵🇭"],
    "TH": ["thailand", "bangkok", "🇹🇭"],
    "VN": ["vietnam", "hanoi", "saigon", "🇻🇳"],
    "MY": ["malaysia", "kuala lumpur", "🇲🇾"],
}


def _flag_to_country(text: str) -> Optional[str]:
    """Detect a regional-indicator flag emoji (🇩🇪 = 0x1F1E9 0x1F1EA) in the bio.
    Each flag is two RI symbols encoding 'DE', 'RS', etc. Returns the ISO code
    of the first flag found or None."""
    if not text:
        return None
    ri_base = 0x1F1E6  # Regional Indicator Symbol Letter A → 'A'
    i = 0
    while i < len(text) - 1:
        a, b = ord(text[i]), ord(text[i + 1])
        if 0x1F1E6 <= a <= 0x1F1FF and 0x1F1E6 <= b <= 0x1F1FF:
            cc = chr(ord("A") + (a - ri_base)) + chr(ord("A") + (b - ri_base))
            if cc in _COUNTRY_NAMES:
                return cc
            i += 2
            continue
        i += 1
    return None


def _resolve_country(*, region: Optional[str], language: Optional[str], signature: Optional[str], nickname: Optional[str]) -> dict:
    """Best-effort country resolver from public profile data alone.
    Returns {country, name, source, confidence}. `source` explains which signal fired."""
    hay = " ".join([nickname or "", signature or ""]).lower()

    # 1) Flag emoji in bio — strongest signal.
    flag = _flag_to_country(f"{nickname or ''} {signature or ''}")
    if flag:
        return {"country": flag, "name": _COUNTRY_NAMES.get(flag, flag), "source": "bio_flag", "confidence": "high"}

    # 2) TikTok's own region field — trusted when it's a valid ISO code.
    if region and isinstance(region, str) and region.upper() in _COUNTRY_NAMES:
        cc = region.upper()
        return {"country": cc, "name": _COUNTRY_NAMES[cc], "source": "tiktok_region", "confidence": "high"}

    # 3) City / country keyword in bio.
    for cc, terms in _BIO_KEYWORDS.items():
        for term in terms:
            if term in hay:
                return {"country": cc, "name": _COUNTRY_NAMES.get(cc, cc), "source": f"bio_keyword:{term}", "confidence": "medium"}

    # 4) Language code fallback (weakest — e.g. many "en" users aren't US/UK).
    if language:
        lang = language.lower().split("-")[0]
        cc = _LANG_TO_COUNTRY.get(lang)
        if cc:
            return {"country": cc, "name": _COUNTRY_NAMES.get(cc, cc), "source": f"language:{lang}", "confidence": "low"}

    return {"country": None, "name": None, "source": "no_signal", "confidence": "none"}


async def _tiktok_public_lookup(handle: str) -> dict:
    """Scrape the public /@handle page for profile data — no API key required.
    Returns country, creation date, follower/likes/videos count, verified, bio, avatar."""
    """Scrape the public /@handle page for profile data — no API key required.
    Returns country, creation date, follower/likes/videos count, verified, bio, avatar."""
    import time as _t
    h = (handle or "").strip().lstrip("@").lower()
    if not h or not re.match(r"^[a-z0-9._]+$", h):
        raise HTTPException(status_code=400, detail="Invalid TikTok username")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    url = f"https://www.tiktok.com/@{h}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach TikTok: {e}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"@{h} not found on TikTok")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"TikTok returned {r.status_code}")
    html = r.text
    m = re.search(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
    user_module, stats = {}, {}
    if m:
        try:
            data = jsonlib.loads(m.group(1))
        except Exception:
            raise HTTPException(status_code=500, detail="TikTok payload could not be parsed")
        scope = ((data.get("__DEFAULT_SCOPE__") or {}).get("webapp.user-detail") or {})
        info = scope.get("userInfo") or {}
        user_module = info.get("user") or {}
        stats = info.get("stats") or {}
    else:
        m2 = re.search(r'<script[^>]*id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m2:
            raise HTTPException(status_code=404, detail=f"@{h} — profile hidden or blocked by TikTok")
        try:
            data = jsonlib.loads(m2.group(1))
        except Exception:
            raise HTTPException(status_code=500, detail="TikTok payload could not be parsed")
        user_module = (data.get("UserModule") or {}).get("users", {}).get(h) or {}
        stats = (data.get("UserModule") or {}).get("stats", {}).get(h) or {}
    if not user_module.get("uniqueId") and not user_module.get("id"):
        raise HTTPException(status_code=404, detail=f"@{h} not found")
    created_iso = None
    created_note = None
    try:
        uid = int(user_module.get("id") or 0)
        # TikTok snowflake IDs are ~19-digit numbers. Anything smaller (<= 10 digits)
        # is a legacy musical.ly migration ID and can't be decoded.
        if uid > 10_000_000_000:
            ts = (uid >> 32) + 1356998400
            if 1356998400 <= ts <= _t.time() + 86400:
                created_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        elif uid > 0:
            created_note = "Legacy Musical.ly account (created before Aug 2018) — exact date unknown"
    except Exception:
        pass
    resolved = _resolve_country(
        region=user_module.get("region"),
        language=user_module.get("language"),
        signature=user_module.get("signature"),
        nickname=user_module.get("nickname"),
    )
    result = {
        "handle": user_module.get("uniqueId") or h,
        "nickname": user_module.get("nickname"),
        "avatar": user_module.get("avatarLarger") or user_module.get("avatarMedium") or user_module.get("avatarThumb"),
        "verified": bool(user_module.get("verified")),
        "private": bool(user_module.get("privateAccount")),
        "signature": user_module.get("signature"),
        "region": user_module.get("region"),
        "language": user_module.get("language"),
        "user_id": str(user_module.get("id") or ""),
        "sec_uid": user_module.get("secUid"),
        "created_at": created_iso,
        "created_note": created_note,
        "followers": int(stats.get("followerCount") or 0),
        "following": int(stats.get("followingCount") or 0),
        "hearts": int(stats.get("heart") or stats.get("heartCount") or 0),
        "videos": int(stats.get("videoCount") or 0),
        "profile_url": f"https://www.tiktok.com/@{h}",
        "detected_country": resolved,
    }
    # Cache the successful lookup so reverse-by-user-id lookups can serve it.
    try:
        if result["user_id"]:
            await db.tiktok_lookup_cache.update_one(
                {"user_id": result["user_id"]},
                {"$set": {**result, "cached_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
    except Exception:
        pass
    return result


_TT_LOOKUP_BUCKET: dict = {}


@api_router.get("/tools/tiktok-lookup")
async def tiktok_lookup(username: str, request: Request):
    """Free public TikTok profile lookup — no login required.
    Rate-limited to 30 requests/minute per IP."""
    ip = ((request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
          or (request.client.host if request.client else "")) or "unknown"
    now = datetime.now(timezone.utc).timestamp()
    hits = [t for t in _TT_LOOKUP_BUCKET.get(ip, []) if t > now - 60]
    if len(hits) >= 30:
        raise HTTPException(status_code=429, detail="Too many lookups — try again in a minute")
    hits.append(now)
    _TT_LOOKUP_BUCKET[ip] = hits
    return await _tiktok_public_lookup(username)


async def _tiktok_reverse_by_id_live(uid: str) -> Optional[dict]:
    """Attempt a live user_id → @handle resolution using TikTok's public search web endpoint.
    Returns a full profile dict (from _tiktok_public_lookup) on success, else None.

    Strategy: TikTok's web search API accepts the numeric user_id as a keyword and
    routinely returns the exact account as the top user hit. Once we have the handle,
    we resolve it live via the standard profile scraper (which also caches by user_id
    for next time). No signing needed for this endpoint (public web search)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.tiktok.com/search/user?q={uid}",
    }
    # Try the JSON web search endpoint first
    url = f"https://www.tiktok.com/api/search/user/full/?keyword={uid}&cursor=0&web_search_code=&from_page=search"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
        if r.status_code == 200 and r.text.strip():
            try:
                j = r.json()
            except Exception:
                j = {}
            for item in (j.get("user_list") or []):
                info = (item or {}).get("user_info") or {}
                if str(info.get("uid") or "") == uid and info.get("unique_id"):
                    return await _tiktok_public_lookup(info["unique_id"])
    except Exception:
        pass
    # Fallback: parse the HTML search results page for a matching user card
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(f"https://www.tiktok.com/search/user?q={uid}", headers={**headers, "Accept": "text/html"})
        if r.status_code == 200:
            html = r.text
            m = re.search(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if m:
                try:
                    data = jsonlib.loads(m.group(1))
                except Exception:
                    data = {}
                scope = ((data.get("__DEFAULT_SCOPE__") or {}).get("webapp.search-detail") or {})
                for section in (scope.get("userInfoList") or []):
                    ui = (section or {}).get("user") or {}
                    if str(ui.get("id") or "") == uid and ui.get("uniqueId"):
                        return await _tiktok_public_lookup(ui["uniqueId"])
    except Exception:
        pass
    return None


@api_router.get("/tools/tiktok-lookup-by-id")
async def tiktok_lookup_by_id(user_id: str, request: Request, user: Optional[CurrentUser] = Depends(optional_current_user_dep)):
    """Find the @handle of a TikTok account by its numeric user_id.

    Public + free — same as the @username lookup. Rate-limited per IP.
    Signed-in users with the `id_finder` addon (or staff) get the higher
    rate limit; anonymous users are capped at 10/min.

    Strategy:
      1. Try our cache first (populated by every successful @handle scrape).
      2. If not cached, attempt a live TikTok web-search resolution.
      3. If still nothing, return a helpful 404.
    """
    uid = (user_id or "").strip().replace("@", "")
    if not uid.isdigit() or len(uid) < 6:
        raise HTTPException(status_code=400, detail="Enter a valid TikTok numeric user ID (e.g. 6656114453... )")
    # Rate limit — signed-in premium users get a bigger bucket
    is_premium = False
    if user and user.role in ("owner", "moderator"):
        is_premium = True
    elif user:
        u = await db.users.find_one({"id": user.id}, {"_id": 0, "addons": 1})
        if "id_finder" in ((u or {}).get("addons") or []):
            is_premium = True
    ip = ((request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
          or (request.client.host if request.client else "")) or "unknown"
    now = datetime.now(timezone.utc).timestamp()
    hits = [t for t in _TT_LOOKUP_BUCKET.get(ip, []) if t > now - 60]
    cap = 60 if is_premium else 10
    if len(hits) >= cap:
        raise HTTPException(status_code=429, detail="Too many lookups — try again in a minute")
    hits.append(now)
    _TT_LOOKUP_BUCKET[ip] = hits

    # 1. Cached path
    cached = await db.tiktok_lookup_cache.find_one({"user_id": uid}, {"_id": 0})
    if cached:
        handle = cached.get("handle")
        try:
            cached_at = cached.get("cached_at")
            stale = True
            if cached_at:
                dt = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00"))
                stale = (datetime.now(timezone.utc) - dt).total_seconds() > 24 * 3600
            if handle and stale:
                return await _tiktok_public_lookup(handle)
        except Exception:
            pass
        cached.pop("cached_at", None)
        return cached

    # 2. Live TikTok web-search resolution
    try:
        live = await _tiktok_reverse_by_id_live(uid)
        if live:
            return live
    except HTTPException:
        raise
    except Exception:
        pass

    # 3. Nothing found
    raise HTTPException(
        status_code=404,
        detail=(
            f"No TikTok account found for user_id {uid}. "
            "The account may be deleted, private or shadow-banned. "
            "Try the username tab if you know the @handle."
        ),
    )


# ==================== Extra public tools (batch: PFP/post downloaders, Instagram, Discord) ====================

_TOOLS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"


def _tools_rate_limit(request: Request, cap: int = 30):
    ip = ((request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
          or (request.client.host if request.client else "")) or "unknown"
    now = datetime.now(timezone.utc).timestamp()
    hits = [t for t in _TT_LOOKUP_BUCKET.get(ip, []) if t > now - 60]
    if len(hits) >= cap:
        raise HTTPException(status_code=429, detail="Too many lookups — try again in a minute")
    hits.append(now)
    _TT_LOOKUP_BUCKET[ip] = hits


@api_router.get("/tools/tiktok-post")
async def tiktok_post_download(url: str, request: Request):
    """Resolve a TikTok video/photo post URL and return download links + metadata.
    Accepts full URLs (`https://www.tiktok.com/@user/video/1234`) and short links (`vm.tiktok.com/xyz`).
    Returns: cover, author, description, no-watermark playAddr, watermarked downloadAddr, music."""
    _tools_rate_limit(request, cap=30)
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Paste the full TikTok URL (must start with https://)")
    headers = {
        "User-Agent": _TOOLS_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(u, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach TikTok: {e}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="TikTok post not found")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"TikTok returned {r.status_code}")
    html = r.text
    m = re.search(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        raise HTTPException(status_code=404, detail="Could not parse TikTok payload — link may be private or region-blocked")
    try:
        data = jsonlib.loads(m.group(1))
    except Exception:
        raise HTTPException(status_code=500, detail="TikTok payload could not be parsed")
    scope = data.get("__DEFAULT_SCOPE__") or {}
    item = ((scope.get("webapp.video-detail") or {}).get("itemInfo") or {}).get("itemStruct") or {}
    if not item:
        raise HTTPException(status_code=404, detail="Post not found (may be deleted or private)")
    author = item.get("author") or {}
    video = item.get("video") or {}
    music = item.get("music") or {}
    stats = item.get("stats") or {}
    # Photo carousels
    image_post = item.get("imagePost") or {}
    images = []
    for img in (image_post.get("images") or []):
        url_list = ((img.get("imageURL") or {}).get("urlList") or [])
        if url_list:
            images.append(url_list[0])
    return {
        "id": item.get("id"),
        "desc": item.get("desc"),
        "created_at": (
            datetime.fromtimestamp(int(item.get("createTime")), tz=timezone.utc).isoformat()
            if str(item.get("createTime") or "").isdigit() else None
        ),
        "author": {
            "handle": author.get("uniqueId"),
            "nickname": author.get("nickname"),
            "avatar": author.get("avatarLarger") or author.get("avatarMedium"),
            "verified": bool(author.get("verified")),
        },
        "video": {
            "cover": video.get("cover") or video.get("originCover"),
            "dynamic_cover": video.get("dynamicCover"),
            "play_url": video.get("playAddr"),
            "download_url": video.get("downloadAddr"),
            "duration": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
        } if video.get("playAddr") else None,
        "images": images or None,
        "music": {
            "title": music.get("title"),
            "author": music.get("authorName"),
            "url": music.get("playUrl"),
            "cover": music.get("coverLarge") or music.get("coverMedium"),
        } if music.get("playUrl") else None,
        "stats": {
            "plays": int(stats.get("playCount") or 0),
            "likes": int(stats.get("diggCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "shares": int(stats.get("shareCount") or 0),
        },
    }


async def _ig_fetch_profile(username: str) -> dict:
    """Fetch a public Instagram profile via the web app's undocumented (but keyless) JSON endpoint.
    Requires the standard `x-ig-app-id` header used by instagram.com itself. Returns raw user dict."""
    h = (username or "").strip().lstrip("@").lower()
    if not h or not re.match(r"^[a-z0-9._]+$", h):
        raise HTTPException(status_code=400, detail="Invalid Instagram username")
    headers = {
        "User-Agent": _TOOLS_UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "x-ig-app-id": "936619743392459",
        "Referer": f"https://www.instagram.com/{h}/",
    }
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={h}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Instagram: {e}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"@{h} not found on Instagram")
    if r.status_code == 401 or r.status_code == 403:
        raise HTTPException(status_code=502, detail="Instagram is rate-limiting anonymous lookups right now — try again in a minute")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Instagram returned {r.status_code}")
    try:
        j = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Instagram payload could not be parsed")
    user = ((j.get("data") or {}).get("user")) or {}
    if not user or not user.get("username"):
        raise HTTPException(status_code=404, detail=f"@{h} not found on Instagram")
    return user


@api_router.get("/tools/instagram-lookup")
async def instagram_lookup(username: str, request: Request):
    """Public Instagram user lookup — avatar, followers, verified, bio, best-effort country guess."""
    _tools_rate_limit(request, cap=20)
    user = await _ig_fetch_profile(username)
    biography = user.get("biography") or ""
    # Best-effort country: reuse the same signal-detector as TikTok (bio + nickname text)
    resolved = _resolve_country(
        region=None,
        language=None,
        signature=biography,
        nickname=user.get("full_name"),
    )
    return {
        "handle": user.get("username"),
        "full_name": user.get("full_name"),
        "avatar": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        "verified": bool(user.get("is_verified")),
        "private": bool(user.get("is_private")),
        "biography": biography,
        "external_url": user.get("external_url"),
        "category": user.get("category_name") or user.get("business_category_name"),
        "user_id": str(user.get("id") or ""),
        "followers": int(((user.get("edge_followed_by") or {}).get("count")) or 0),
        "following": int(((user.get("edge_follow") or {}).get("count")) or 0),
        "posts": int(((user.get("edge_owner_to_timeline_media") or {}).get("count")) or 0),
        "profile_url": f"https://www.instagram.com/{user.get('username')}/",
        "detected_country": resolved,
    }


@api_router.get("/tools/instagram-post")
async def instagram_post_download(url: str, request: Request):
    """Resolve an Instagram post/reel URL and return image/video download links + metadata.
    Accepts `/p/{shortcode}/` and `/reel/{shortcode}/`."""
    _tools_rate_limit(request, cap=20)
    u = (url or "").strip()
    m = re.search(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]{5,})", u)
    if not m:
        raise HTTPException(status_code=400, detail="Paste a full Instagram post/reel URL (e.g. https://www.instagram.com/p/XXXX/)")
    shortcode = m.group(1)
    headers = {
        "User-Agent": _TOOLS_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(f"https://www.instagram.com/p/{shortcode}/", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Instagram: {e}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Instagram post not found")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Instagram returned {r.status_code}")
    html = r.text
    # Pull the OG meta tags — these are exposed on the public post page for logged-out users.
    def _meta(prop: str) -> Optional[str]:
        mm = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']', html)
        if mm:
            return mm.group(1)
        mm = re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']', html)
        return mm.group(1) if mm else None
    img = _meta("og:image")
    vid = _meta("og:video") or _meta("og:video:secure_url")
    title = _meta("og:title") or ""
    desc = _meta("og:description") or ""
    if not img and not vid:
        raise HTTPException(status_code=404, detail="Post is private or Instagram blocked the request — try again shortly")
    return {
        "shortcode": shortcode,
        "url": f"https://www.instagram.com/p/{shortcode}/",
        "title": title,
        "description": desc,
        "image": img,
        "video": vid,
        "type": "reel" if "/reel/" in u else ("video" if vid else "image"),
    }


@api_router.get("/tools/discord-user")
async def discord_user_lookup(user_id: str, request: Request):
    """Fetch a Discord user's public profile via the site's own bot token.
    Discord's API requires the user's numeric snowflake ID — usernames alone can't
    be resolved without mutual-server access. If the site admin hasn't configured a
    Discord bot token yet, this endpoint returns a helpful error.
    Returns: username, global_name, avatar URL, banner, badges, account creation date."""
    _tools_rate_limit(request, cap=30)
    uid = (user_id or "").strip()
    if not uid.isdigit() or len(uid) < 17:
        raise HTTPException(status_code=400, detail="Paste a valid Discord user ID (17-20 digit snowflake). Usernames alone can't be looked up — Discord requires the numeric ID.")
    cfg = await db.discord_config.find_one({}, {"_id": 0, "bot_token": 1}) or {}
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Discord lookup is offline — the site admin hasn't configured a Discord bot token yet.")
    headers = {"Authorization": f"Bot {token}", "User-Agent": "BetterSocial (https://better-social.pro, 1.0)"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"https://discord.com/api/v10/users/{uid}", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Discord: {e}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"No Discord user with ID {uid}")
    if r.status_code == 401:
        raise HTTPException(status_code=502, detail="Discord bot token appears invalid — ask an admin to re-save it.")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Discord returned {r.status_code}")
    try:
        u = r.json() or {}
    except Exception:
        raise HTTPException(status_code=502, detail="Discord payload could not be parsed")
    # Snowflake creation time — Discord epoch = 2015-01-01T00:00:00Z (1420070400000 ms)
    created_iso = None
    try:
        created_ms = (int(u.get("id")) >> 22) + 1420070400000
        created_iso = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        pass
    avatar_hash = u.get("avatar")
    banner_hash = u.get("banner")
    disc = u.get("discriminator") or "0"
    default_index = (int(u["id"]) >> 22) % 6 if u.get("id") else 0
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{u['id']}/{avatar_hash}.{'gif' if str(avatar_hash).startswith('a_') else 'png'}?size=512"
        if avatar_hash else f"https://cdn.discordapp.com/embed/avatars/{default_index}.png"
    )
    banner_url = (
        f"https://cdn.discordapp.com/banners/{u['id']}/{banner_hash}.{'gif' if str(banner_hash).startswith('a_') else 'png'}?size=1024"
        if banner_hash else None
    )
    flags = int(u.get("public_flags") or 0)
    BADGES = {
        1 << 0: "Discord Employee", 1 << 1: "Partnered Server Owner", 1 << 2: "HypeSquad Events",
        1 << 3: "Bug Hunter Level 1", 1 << 6: "HypeSquad Bravery", 1 << 7: "HypeSquad Brilliance",
        1 << 8: "HypeSquad Balance", 1 << 9: "Early Supporter", 1 << 14: "Bug Hunter Level 2",
        1 << 16: "Verified Bot", 1 << 17: "Early Verified Bot Developer",
        1 << 18: "Discord Certified Moderator", 1 << 22: "Active Developer",
    }
    badges = [name for bit, name in BADGES.items() if flags & bit]
    return {
        "id": u.get("id"),
        "username": u.get("username"),
        "global_name": u.get("global_name"),
        "discriminator": disc,
        "display": f"{u.get('username')}#{disc}" if disc and disc != "0" else (u.get("global_name") or u.get("username")),
        "avatar_url": avatar_url,
        "banner_url": banner_url,
        "accent_color": u.get("accent_color"),
        "bot": bool(u.get("bot")),
        "system": bool(u.get("system")),
        "public_flags": flags,
        "badges": badges,
        "created_at": created_iso,
    }


async def _tt_probe_html(handle: str, headers: dict) -> Optional[bool]:
    """Probe /@handle/live HTML for the same signals. Returns True/False/None."""
    url = f"https://www.tiktok.com/@{handle}/live"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
    except Exception as e:
        logger.debug("[livesub] tiktok html check network error for %s: %s", handle, e)
        return None
    if r.status_code >= 400:
        return None
    html = r.text[:400_000]
    # Explicit off-signals — if present, definitively offline
    off_re = re.compile(r'"(userNotLive|userStatus":\s*1|isLive":\s*false|is_live":\s*false)"?', re.IGNORECASE)
    if off_re.search(html):
        return False
    # Positive signals — REQUIRE a non-zero liveRoomId value AND EITHER status:2 or isLive:true.
    room_id_re = re.compile(r'"liveRoomId"\s*:\s*"?([1-9]\d{6,})"?')
    room_id_hit = bool(room_id_re.search(html))
    status_two_re = re.compile(r'"status"\s*:\s*2(?!\d)')
    status_two_hit = bool(status_two_re.search(html))
    is_live_true_re = re.compile(r'"is[_]?[lL]ive"\s*:\s*true')
    is_live_hit = bool(is_live_true_re.search(html))
    if room_id_hit and (status_two_hit or is_live_hit):
        return True
    return False


async def _is_tiktok_user_live(tt_username: str) -> bool:
    """Robust check whether a TikTok user is currently broadcasting live.

    Primary signal: TikTok's api-live/user/room JSON endpoint (user.status
    2 = live, 4 = offline). This is what the web player itself uses and is
    authoritative. The old webcast/info_by_scene endpoint was retired by
    TikTok (now returns status_code 10013 "Url does not match") which caused
    every check to report OFFLINE. HTML scraping remains as fallback only
    when the JSON probe can't decide (network/blocked).
    """
    handle = tt_username.strip().lstrip("@")
    if not handle:
        return False
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    api_res, html_res = await asyncio.gather(
        _tt_probe_apilive(handle, headers),
        _tt_probe_html(handle, headers),
        return_exceptions=False,
    )
    if api_res is not None:
        return api_res
    if html_res is not None:
        return html_res
    # Both probes failed (network errors) — fail-closed as offline; the
    # live_only worker holds the previous known state on total failure.
    return False


@api_router.get("/debug/tiktok-live/{handle}")
async def debug_tiktok_live(handle: str, user: CurrentUser = Depends(current_user_dep)):
    """Debug probe — signed-in users can hit this to check whether the LIVE
    detector currently reports a given TikTok handle as broadcasting. Useful
    when validating Auto-Live subscription behaviour."""
    is_live = await _is_tiktok_user_live(handle)
    return {"handle": handle.lstrip("@"), "is_live": is_live}


class LiveSubCreate(BaseModel):
    service_id: int
    tiktok_username: str = Field(..., min_length=1, max_length=80)
    quantity_per_burst: int = Field(..., ge=1, le=1_000_000)
    duration_days: int
    repeat_every_minutes: int = Field(default=5, description="How often to fire a new order (2, 5, 10 or 60 minutes)")
    # Mode: "always" (default — fire on a strict timer) OR "live_only" (only when TikTok user is live).
    # Users kept complaining that "live_only" silently stopped after streams ended and never resumed,
    # so the default is now the dumb-simple strict timer. UI still exposes both.
    mode: str = Field(default="always", pattern="^(always|live_only)$")
    # For custom-comments services (TikTok / Kick custom comments etc.).
    # When the selected service has `needs_custom_text=true`, the user pastes one
    # comment per line. quantity_per_burst MUST equal the number of non-empty
    # lines — the frontend derives this automatically and the backend enforces it.
    comments: Optional[str] = Field(default=None, max_length=20000)


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
    # Auto-recurring is available for any live-stream service (TikTok Live, Kick Live, etc.).
    is_live_service = ("tiktok" in cat or "kick" in cat) and "live" in cat
    if not is_live_service:
        raise HTTPException(status_code=400, detail="Auto-recurring is only available for TikTok / Kick Live services.")
    smin, smax = int(svc.get("min", 1) or 1), int(svc.get("max", 1_000_000) or 1_000_000)
    # Custom-comments services: quantity is derived from the number of non-empty lines.
    needs_custom = bool(svc.get("needs_custom_text"))
    comments_raw = (body.comments or "").strip() or None
    if needs_custom:
        if not comments_raw:
            raise HTTPException(status_code=400, detail="This service requires custom comments — one per line.")
        lines = [ln.strip() for ln in comments_raw.split("\n") if ln.strip()]
        if not lines:
            raise HTTPException(status_code=400, detail="Enter at least one non-empty comment line.")
        # Force quantity to match the number of comment lines. Frontend already
        # derives quantity_per_burst from the line count, but we normalise here
        # so an out-of-sync client can't cheat the check.
        body.quantity_per_burst = len(lines)
        comments_raw = "\n".join(lines)
    if body.quantity_per_burst < smin or body.quantity_per_burst > smax:
        raise HTTPException(status_code=400, detail=f"Quantity must be between {smin} and {smax}")
    rate = float(svc.get("custom_rate", 0))
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Service price not set")
    charge_per_burst = round((rate * body.quantity_per_burst) / 1000.0, 4)
    charge_per_burst, _dp = await _apply_user_discount(user.id, charge_per_burst)
    balance = await _get_user_balance(user.id)
    if balance < charge_per_burst:
        raise HTTPException(status_code=402, detail=f"Need at least ${charge_per_burst:.2f} in balance to start.")
    now = datetime.now(timezone.utc)
    handle = body.tiktok_username.strip().lstrip("@")
    tiktok_user_id = None
    if handle.isdigit() and len(handle) >= 6:
        # User entered a numeric TikTok user ID — resolve it to the current handle.
        cached = await db.tiktok_lookup_cache.find_one({"user_id": handle}, {"_id": 0, "handle": 1})
        if not cached or not cached.get("handle"):
            raise HTTPException(status_code=404, detail="Couldn't resolve this user ID to a username yet — run it once through the TikTok Finder (username tab for that account), then order again.")
        tiktok_user_id = handle
        handle = cached["handle"].lstrip("@")
    else:
        c = await db.tiktok_lookup_cache.find_one({"handle": handle.lower()}, {"_id": 0, "user_id": 1})
        if c and c.get("user_id"):
            tiktok_user_id = str(c["user_id"])
    await _enforce_username_blacklist(user.id, handle)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user.id,
        "username": user.username,
        "tiktok_username": handle,
        "tiktok_user_id": tiktok_user_id,
        "service_id": body.service_id,
        "service_name": svc.get("custom_name") or svc.get("name") or "",
        "provider_id": svc.get("provider_id"),
        "quantity_per_burst": body.quantity_per_burst,
        "charge_per_burst": charge_per_burst,
        "duration_days": body.duration_days,
        "repeat_every_minutes": body.repeat_every_minutes,
        "mode": body.mode,
        "starts_at": now.isoformat(),
        "expires_at": (now + timedelta(days=body.duration_days)).isoformat(),
        "next_check_at": (now + timedelta(seconds=TIKTOK_CHECK_INTERVAL_SEC)).isoformat(),
        "last_check_at": now.isoformat(),
        "last_burst_at": None,
        "status": "active",
        "total_bursts": 0,
        "total_spent": 0.0,
        "ever_live": False,
        "last_live_state": None,
        "created_at": now.isoformat(),
        "comments": comments_raw,
        "needs_custom_text": needs_custom,
    }
    await db.live_subscriptions.insert_one(doc.copy())

    # Fire the FIRST order right away UNLESS mode=live_only AND target is offline.
    # This is the fix for "wasting balance when I subscribe while streamer is
    # not live". We log an initial check either way so history is populated
    # immediately for every subscription.
    first_order_id = None
    should_fire_initial = True
    if body.mode == "live_only":
        try:
            is_live_now = await _is_tiktok_user_live(handle)
        except Exception as e:
            logger.warning("[livesub] initial live-check failed for %s: %s — firing anyway", handle, e)
            is_live_now = True  # fail-open
        # Log this first check into the history collection
        try:
            await db.tiktok_live_checks.insert_one({
                "id": str(uuid.uuid4()),
                "sub_id": doc["id"],
                "user_id": user.id,
                "username": user.username,
                "tiktok_username": handle,
                "is_live": bool(is_live_now),
                "will_fire": bool(is_live_now),
                "checked_at": now.isoformat(),
                "mode": "live_only",
                "note": "initial check on create",
            })
        except Exception:
            pass
        if not is_live_now:
            should_fire_initial = False
            await db.live_subscriptions.update_one(
                {"id": doc["id"]},
                {"$set": {"status": "waiting_for_live", "waiting_since": now.isoformat(), "last_live_state": False}},
            )
            doc["status"] = "waiting_for_live"
        else:
            await db.live_subscriptions.update_one(
                {"id": doc["id"]}, {"$set": {"ever_live": True, "last_live_state": True}}
            )
            doc["ever_live"] = True
            doc["last_live_state"] = True

    if should_fire_initial:
        try:
            resp = await place_smm_order(
                body.service_id,
                f"https://www.tiktok.com/@{handle}/live",
                body.quantity_per_burst,
                comments=comments_raw,
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
                "comments": comments_raw,
            })
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
                "amount": -charge_per_burst, "method": "balance", "status": "approved",
                "type": "live_sub_burst", "note": f"Auto burst @{handle} — {body.quantity_per_burst} (initial)",
                "live_sub_id": doc["id"], "created_at": now.isoformat(), "approved_at": now.isoformat(),
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
    return {"ok": True, "subscription": doc, "first_order_id": first_order_id, "initial_skipped_offline": not should_fire_initial}


@client_router.get("/live-sub/my")
async def live_sub_my(user: CurrentUser = Depends(current_user_dep)):
    cur = db.live_subscriptions.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(50)
    subs = await cur.to_list(50)
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "auto_live_enabled": 1})
    return {"subscriptions": subs, "auto_live_enabled": bool((u or {}).get("auto_live_enabled"))}


class LiveSubUsernameBody(BaseModel):
    tiktok_username: str = Field(..., min_length=1, max_length=80)


@client_router.post("/live-sub/{sid}/username")
async def live_sub_change_username(sid: str, body: LiveSubUsernameBody, user: CurrentUser = Depends(current_user_dep)):
    """Change the target username on a running Auto-Live order. Accepts a plain
    handle or a numeric TikTok user ID (resolved from the lookup cache)."""
    sub = await db.live_subscriptions.find_one(
        {"id": sid, "user_id": user.id, "status": {"$in": ["active", "waiting_for_live", "on_hold", "paused"]}},
        {"_id": 0},
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found or already ended")
    handle = body.tiktok_username.strip().lstrip("@")
    new_user_id = None
    if handle.isdigit() and len(handle) >= 6:
        cached = await db.tiktok_lookup_cache.find_one({"user_id": handle}, {"_id": 0, "handle": 1})
        if not cached or not cached.get("handle"):
            raise HTTPException(status_code=404, detail="Couldn't resolve this user ID — run it once through the TikTok Finder first.")
        new_user_id = handle
        handle = cached["handle"].lstrip("@")
    else:
        c = await db.tiktok_lookup_cache.find_one({"handle": handle.lower()}, {"_id": 0, "user_id": 1})
        if c and c.get("user_id"):
            new_user_id = str(c["user_id"])
    await _enforce_username_blacklist(user.id, handle)
    old = sub["tiktok_username"]
    if handle.lower() == (old or "").lower():
        return {"ok": True, "tiktok_username": handle, "unchanged": True}
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.live_subscriptions.update_one(
        {"id": sid},
        {"$set": {"tiktok_username": handle, "tiktok_user_id": new_user_id,
                  "previous_username": old, "username_changed_at": now_iso}},
    )
    await _log_live_check({**sub, "tiktok_username": handle}, False,
                          note=f"username changed manually: @{old} → @{handle}", will_fire=False)
    return {"ok": True, "tiktok_username": handle, "previous_username": old}


@client_router.get("/live-sub/{sid}/checks")
async def live_sub_checks(sid: str, user: CurrentUser = Depends(current_user_dep)):
    """User can audit every live-status check on their own subscription."""
    sub = await db.live_subscriptions.find_one({"id": sid, "user_id": user.id}, {"_id": 0, "id": 1})
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    cur = db.tiktok_live_checks.find({"sub_id": sid}, {"_id": 0}).sort("checked_at", -1).limit(200)
    checks = await cur.to_list(200)
    # Also compute quick stats
    total = len(checks)
    live_count = sum(1 for c in checks if c.get("is_live"))
    return {
        "checks": checks,
        "stats": {"total_checks": total, "was_live": live_count, "was_offline": total - live_count},
    }


@api_router.get("/admin/live-sub-checks")
async def admin_live_sub_checks(
    x_admin_token: Optional[str] = Header(None),
    user_id: Optional[str] = None,
    sub_id: Optional[str] = None,
    limit: int = 500,
):
    """Owner/staff view of every TikTok live-status check across all subs.
    Filter by user_id OR sub_id. Returns most recent first."""
    check_admin(x_admin_token)
    q: dict = {}
    if user_id: q["user_id"] = user_id
    if sub_id:  q["sub_id"]  = sub_id
    limit = max(1, min(int(limit or 500), 2000))
    cur = db.tiktok_live_checks.find(q, {"_id": 0}).sort("checked_at", -1).limit(limit)
    return {"checks": await cur.to_list(limit)}


@api_router.get("/admin/user-activity/{user_id}")
async def admin_user_activity(user_id: str, x_admin_token: Optional[str] = Header(None), limit: int = 200):
    """Full activity dossier for one user — orders, deposits, virtual-number
    rentals, auto-live subs, and live-status checks. Admin panel renders this
    into a scrollable per-user history modal."""
    check_admin(x_admin_token)
    limit = max(1, min(int(limit or 200), 500))
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0}) or {}
    orders = await db.orders.find(
        {"user_id": user_id},
        {"_id": 0, "id": 1, "service_id": 1, "service_name": 1, "link": 1, "quantity": 1, "charge": 1, "price_usd": 1, "status": 1, "payment_method": 1, "source": 1, "smm_order_id": 1, "created_at": 1, "provider_id": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    txns = await db.transactions.find(
        {"user_id": user_id},
        {"_id": 0, "id": 1, "amount": 1, "method": 1, "status": 1, "type": 1, "note": 1, "created_at": 1, "approved_at": 1, "bonus_amount": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    numbers = await db.number_rentals.find(
        {"user_id": user_id},
        {"_id": 0, "id": 1, "operator": 1, "country": 1, "service": 1, "phone_number": 1, "price": 1, "status": 1, "created_at": 1, "expires_at": 1, "sms": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit) if "number_rentals" in await db.list_collection_names() else []
    subs = await db.live_subscriptions.find(
        {"user_id": user_id},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    live_checks = await db.tiktok_live_checks.find(
        {"user_id": user_id},
        {"_id": 0, "id": 1, "tiktok_username": 1, "is_live": 1, "will_fire": 1, "checked_at": 1, "sub_id": 1},
    ).sort("checked_at", -1).limit(100).to_list(100)
    # Quick totals
    total_spent = round(sum(float(o.get("charge") or o.get("price_usd") or 0) for o in orders), 2)
    total_deposited = round(sum(float(t.get("amount") or 0) for t in txns if (t.get("type") or "") in ("deposit",) and t.get("status") == "approved"), 2)
    return {
        "user": user,
        "totals": {
            "orders_count": len(orders),
            "orders_total_spent": total_spent,
            "deposits_total": total_deposited,
            "numbers_count": len(numbers),
            "auto_live_subs": len(subs),
        },
        "orders": orders,
        "transactions": txns,
        "number_rentals": numbers,
        "live_subscriptions": subs,
        "live_checks": live_checks,
    }


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
        {"id": sid, "user_id": user.id, "status": {"$in": ["active", "waiting_for_live", "paused", "on_hold"]}},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found or already cancelled")
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
            # Then: due for a burst — include both active and waiting_for_live
            due = await db.live_subscriptions.find(
                {"status": {"$in": ["active", "waiting_for_live", "on_hold", "paused"]}, "next_check_at": {"$lte": now.isoformat()}},
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


async def _log_live_check(sub: dict, is_live: bool, note: str = "", will_fire: Optional[bool] = None) -> None:
    """Append one live-status check row so users see red/green history."""
    try:
        await db.tiktok_live_checks.insert_one({
            "id": str(uuid.uuid4()),
            "sub_id": sub["id"],
            "user_id": sub["user_id"],
            "username": sub.get("username"),
            "tiktok_username": sub["tiktok_username"],
            "is_live": bool(is_live),
            "will_fire": bool(is_live) if will_fire is None else bool(will_fire),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "mode": sub.get("mode") or "always",
            "note": note or None,
        })
        # Trim the per-sub log to the latest 500 rows.
        n = await db.tiktok_live_checks.count_documents({"sub_id": sub["id"]})
        if n > 500:
            old = await db.tiktok_live_checks.find(
                {"sub_id": sub["id"]},
                {"_id": 0, "id": 1},
            ).sort("checked_at", 1).limit(n - 500).to_list(n - 500)
            if old:
                await db.tiktok_live_checks.delete_many({"id": {"$in": [o["id"] for o in old]}})
    except Exception as _e:
        logger.warning("[livesub] failed to log check for sub=%s: %s", sub.get("id"), _e)


LIVE_SUB_NEVER_LIVE_REFUND_SEC = 300     # cancel + refund if never live within 5 min of ordering


async def _refund_and_cancel_live_sub(sub: dict, reason: str) -> None:
    """Cancel a live_only sub, refund everything spent back to balance, email the user."""
    now_iso = datetime.now(timezone.utc).isoformat()
    spent = round(float(sub.get("total_spent") or 0), 4)
    if spent > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": sub["user_id"], "username": sub.get("username"),
            "amount": spent, "method": "balance", "status": "approved",
            "type": "live_sub_refund", "note": f"Auto-Live refund @{sub['tiktok_username']} — {reason}",
            "live_sub_id": sub["id"], "created_at": now_iso, "approved_at": now_iso,
        })
    await db.live_subscriptions.update_one(
        {"id": sub["id"]},
        {"$set": {"status": "refunded", "ended_at": now_iso, "refund_reason": reason, "refund_amount": spent}},
    )
    await _log_live_check(sub, False, note=f"cancelled & refunded ${spent:.2f} — {reason}", will_fire=False)
    logger.info("[livesub] sub %s cancelled+refunded $%.4f — %s", sub["id"], spent, reason)
    try:
        u = await db.users.find_one({"id": sub["user_id"]}, {"_id": 0, "email": 1, "username": 1})
        if u and u.get("email"):
            from email_service import send_email, _wrap
            amount_line = (
                f"<p><b>${spent:.2f}</b> has been refunded to your account balance.</p>"
                if spent > 0 else "<p>No balance was charged, so there is nothing to refund.</p>"
            )
            html = _wrap(
                f"<h2 style='margin-top:0;'>Auto-Live order refunded</h2>"
                f"<p>Hi {u.get('username') or ''},</p>"
                f"<p>Your Auto-Live order for <b>@{sub['tiktok_username']}</b> "
                f"({sub.get('service_name') or 'TikTok Live service'}) was cancelled.</p>"
                f"<p><b>Reason:</b> {reason}</p>"
                f"{amount_line}"
                f"<p>You can start a new Auto-Live order any time once the streamer is broadcasting.</p>"
            )
            await send_email(db, u["email"], "Better Social — Auto-Live order refunded", html)
    except Exception as e:
        logger.warning("[livesub] refund email failed for sub=%s: %s", sub["id"], e)


async def _fire_one_burst(sub: dict, link: str, tag: str = "burst") -> bool:
    """Fire one SMM order, debit balance, persist order row. Returns True on success."""
    charge = float(sub.get("charge_per_burst") or 0)
    balance = await _get_user_balance(sub["user_id"])
    if balance < charge:
        await db.live_subscriptions.update_one(
            {"id": sub["id"]}, {"$set": {"status": "on_hold", "hold_reason": "insufficient_balance", "held_at": datetime.now(timezone.utc).isoformat()}}
        )
        await _log_live_check(sub, False, note="ON HOLD — balance too low, will auto-resume once topped up", will_fire=False)
        logger.info("[livesub] sub %s ON HOLD — user balance too low ($%.4f < $%.4f)", sub["id"], balance, charge)
        return False
    try:
        resp = await place_smm_order(sub["service_id"], link, int(sub["quantity_per_burst"]), comments=sub.get("comments"), provider_id=sub.get("provider_id"))
    except Exception as e:
        logger.warning("[livesub] provider order failed for sub=%s (%s): %s", sub["id"], tag, e)
        return False
    if not resp.get("order"):
        logger.warning("[livesub] provider returned no order id for sub=%s (%s): %s", sub["id"], tag, str(resp)[:150])
        return False
    burst_iso = datetime.now(timezone.utc).isoformat()
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": sub["user_id"], "username": sub["username"],
        "amount": -charge, "method": "balance", "status": "approved",
        "type": "live_sub_burst", "note": f"Auto burst @{sub['tiktok_username']} — {sub['quantity_per_burst']} ({tag})",
        "live_sub_id": sub["id"], "created_at": burst_iso, "approved_at": burst_iso,
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
        "created_at": burst_iso,
        "provider_id": sub.get("provider_id"),
        "burst_tag": tag,
        "comments": sub.get("comments"),
    })
    await db.live_subscriptions.update_one(
        {"id": sub["id"]},
        {
            "$set": {"last_burst_at": burst_iso},
            "$inc": {"total_bursts": 1, "total_spent": charge},
        },
    )
    logger.info("[livesub] burst OK sub=%s @%s qty=%s order=%s tag=%s", sub["id"], sub["tiktok_username"], sub["quantity_per_burst"], resp.get("order"), tag)
    return True


async def _process_live_sub_burst(sub: dict):
    """Fire an SMM order burst per the subscription's schedule.

    Behaviour by mode:
      • mode="always"    — Strict timer. Fire ONE burst every `repeat_every_minutes`
                          regardless of live state.  Live status is still checked
                          + logged so history stays populated.
      • mode="live_only" — Check TikTok live status. OFFLINE → skip + log red
                          check (cancel+refund if never live within 5 min).
                          LIVE → instant order on every re-live transition,
                          then one order per repeat interval while live.
    """
    now = datetime.now(timezone.utc)
    default_next = (now + timedelta(seconds=TIKTOK_CHECK_INTERVAL_SEC)).isoformat()
    await db.live_subscriptions.update_one(
        {"id": sub["id"]},
        {"$set": {"last_check_at": now.isoformat(), "next_check_at": default_next}},
    )

    # Username-change tracking — if we know the numeric user id and the lookup
    # cache holds a newer handle, follow the rename automatically.
    if sub.get("tiktok_user_id"):
        try:
            c = await db.tiktok_lookup_cache.find_one({"user_id": str(sub["tiktok_user_id"])}, {"_id": 0, "handle": 1})
            new_h = ((c or {}).get("handle") or "").lstrip("@")
            if new_h and new_h.lower() != (sub.get("tiktok_username") or "").lower():
                old_h = sub.get("tiktok_username")
                await db.live_subscriptions.update_one(
                    {"id": sub["id"]},
                    {"$set": {"tiktok_username": new_h, "previous_username": old_h,
                              "username_changed_at": now.isoformat()}},
                )
                sub["tiktok_username"] = new_h
                await _log_live_check(sub, False, note=f"username changed: @{old_h} → @{new_h} — auto-following new handle", will_fire=False)
                logger.info("[livesub] sub %s followed rename @%s → @%s", sub["id"], old_h, new_h)
        except Exception:
            pass

    # ON HOLD auto-resume — the moment the user's balance covers a burst again.
    if sub.get("status") in ("on_hold", "paused"):
        bal = await _get_user_balance(sub["user_id"])
        if bal >= float(sub.get("charge_per_burst") or 0):
            await db.live_subscriptions.update_one(
                {"id": sub["id"]},
                {"$set": {"status": "active"}, "$unset": {"hold_reason": "", "paused_reason": "", "held_at": "", "paused_at": ""}},
            )
            sub["status"] = "active"
            await _log_live_check(sub, False, note="balance topped up — order auto-resumed from ON HOLD", will_fire=False)
            logger.info("[livesub] sub %s auto-resumed from ON HOLD", sub["id"])
        else:
            return

    mode = (sub.get("mode") or "always").lower()
    link = f"https://www.tiktok.com/@{sub['tiktok_username']}/live"

    # === ALWAYS mode ===================================================
    if mode == "always":
        # Log the live-state read anyway so history shows red/green markers.
        try:
            is_live_now = await _is_tiktok_user_live(sub["tiktok_username"])
        except Exception:
            is_live_now = True
        await _log_live_check(sub, is_live_now, note="always mode (fires anyway)")

        # Strict schedule gate: has enough time passed since last burst?
        repeat_every_sec = int(sub.get("repeat_every_minutes") or 5) * 60
        last_burst_iso = sub.get("last_burst_at")
        if last_burst_iso:
            try:
                last_burst = datetime.fromisoformat(last_burst_iso.replace("Z", "+00:00"))
                if (now - last_burst).total_seconds() < repeat_every_sec:
                    return  # not yet time
            except Exception:
                pass
        ok = await _fire_one_burst(sub, link, tag="always_timer")
        if ok:
            await db.live_subscriptions.update_one(
                {"id": sub["id"]},
                {"$set": {"next_check_at": (datetime.now(timezone.utc) + timedelta(seconds=repeat_every_sec)).isoformat()}},
            )
        return

    # === LIVE_ONLY mode ================================================
    # OFFLINE → never fire, log a red check. If the sub has NEVER been live
    #           and 5 minutes passed since ordering → cancel + refund + email.
    # LIVE    → fire immediately on every offline→live transition, then one
    #           order per `repeat_every_minutes` while they stay live.
    was_live = bool(sub.get("last_live_state"))
    try:
        is_live_now = await _is_tiktok_user_live(sub["tiktok_username"])
    except Exception as e:
        logger.warning("[livesub] live check failed for %s (%s) — holding previous state",
                       sub.get("tiktok_username"), e)
        is_live_now = was_live  # hold last known state, never fire blind

    if not is_live_now:
        await _log_live_check(sub, False, note="offline — no order sent", will_fire=False)
        updates = {"last_live_state": False}
        if sub.get("status") == "active":
            updates["status"] = "waiting_for_live"
            updates["waiting_since"] = now.isoformat()
        await db.live_subscriptions.update_one({"id": sub["id"]}, {"$set": updates})
        # 5-minute never-live refund window
        never_live = not sub.get("ever_live") and not sub.get("last_burst_at")
        if never_live:
            try:
                created = datetime.fromisoformat(str(sub.get("created_at")).replace("Z", "+00:00"))
            except Exception:
                created = now
            if (now - created).total_seconds() >= LIVE_SUB_NEVER_LIVE_REFUND_SEC:
                fresh = await db.live_subscriptions.find_one({"id": sub["id"]}, {"_id": 0})
                await _refund_and_cancel_live_sub(
                    fresh or sub,
                    reason="The TikTok account did not go live within 5 minutes of your order",
                )
        else:
            logger.info("[livesub] sub %s @%s is offline — waiting for re-live", sub["id"], sub.get("tiktok_username"))
        return

    # Streamer is LIVE.
    just_came_online = (not was_live) or sub.get("status") == "waiting_for_live"
    fire_tag = None
    if just_came_online:
        fire_tag = "re_live"
    else:
        repeat_every_sec = int(sub.get("repeat_every_minutes") or 5) * 60
        last_burst_iso = sub.get("last_burst_at")
        due = True
        if last_burst_iso:
            try:
                last_burst = datetime.fromisoformat(last_burst_iso.replace("Z", "+00:00"))
                due = (now - last_burst).total_seconds() >= repeat_every_sec
            except Exception:
                pass
        if due:
            fire_tag = "live_interval"

    note = (
        "LIVE (just came online) — order sent" if fire_tag == "re_live"
        else "LIVE — interval order sent" if fire_tag == "live_interval"
        else "LIVE — waiting for next interval"
    )
    await _log_live_check(sub, True, note=note, will_fire=bool(fire_tag))
    await db.live_subscriptions.update_one(
        {"id": sub["id"]},
        {"$set": {"status": "active", "last_live_state": True, "ever_live": True},
         "$unset": {"waiting_since": ""}},
    )
    if fire_tag:
        ok = await _fire_one_burst(sub, link, tag=fire_tag)
        if ok:
            logger.info("[livesub] sub %s @%s fired burst (%s)", sub["id"], sub.get("tiktok_username"), fire_tag)


@app.on_event("startup")
async def _start_live_sub_worker():
    # Fire-and-forget; the loop catches its own errors and reschedules.
    asyncio.create_task(_live_sub_worker_loop())
    # Sports goal watcher removed per owner request (Feb 2026).
    # NOWPayments auto-reconciler — auto-credits paid invoices if the webhook missed.
    asyncio.create_task(_nowpayments_reconciler_loop())
    # Monthly chat cleanup — hourly worker that trims public_chat, ai_chat_messages
    # and direct_messages older than 30 days.
    asyncio.create_task(_chat_retention_loop())
    # Auto-restart the Discord bot if it was running before the last reload.
    asyncio.create_task(_discord_bot_autostart())
    # DB backup worker — snapshot every 6 hours to /app/backups.
    asyncio.create_task(_db_backup_loop())
    # Fake chat "social proof" activity — populates the public chat when quiet.
    asyncio.create_task(_fake_chat_activity_loop())
    # Fake order activity — same on/off toggle.
    asyncio.create_task(_fake_order_activity_loop())


# ============ Fake social-proof chat activity (owner-toggleable) ============
FAKE_CHAT_PERSONAS = [
    {"username": "MilanBGD",     "level": 12, "avatar_url": None,                                 "lang": "sr"},
    {"username": "AnaN",         "level": 8,  "avatar_url": "https://i.pravatar.cc/60?img=32",     "lang": "sr"},
    {"username": "LukaViper",    "level": 24, "avatar_url": "https://i.pravatar.cc/60?img=15",     "lang": "sr"},
    {"username": "JovanaXO",     "level": 17, "avatar_url": None,                                 "lang": "sr"},
    {"username": "MikeFromDE",   "level": 5,  "avatar_url": "https://i.pravatar.cc/60?img=51",     "lang": "de"},
    {"username": "LenaB",        "level": 11, "avatar_url": None,                                 "lang": "de"},
    {"username": "FinnHH",       "level": 3,  "avatar_url": "https://i.pravatar.cc/60?img=68",     "lang": "de"},
    {"username": "ClaraKM",      "level": 19, "avatar_url": "https://i.pravatar.cc/60?img=44",     "lang": "de"},
    {"username": "SocialSean",   "level": 21, "avatar_url": None,                                 "lang": "en"},
    {"username": "TrapHouse99",  "level": 14, "avatar_url": "https://i.pravatar.cc/60?img=12",     "lang": "en"},
    {"username": "NadiaVibes",   "level": 9,  "avatar_url": "https://i.pravatar.cc/60?img=25",     "lang": "en"},
    {"username": "kevin__ny",    "level": 6,  "avatar_url": None,                                 "lang": "en"},
    {"username": "AlexisTikTok", "level": 28, "avatar_url": "https://i.pravatar.cc/60?img=47",     "lang": "en"},
    {"username": "TarikSMM",     "level": 15, "avatar_url": None,                                 "lang": "sr"},
    {"username": "PetraDE",      "level": 7,  "avatar_url": "https://i.pravatar.cc/60?img=36",     "lang": "de"},
]
FAKE_CHAT_LINES = {
    "sr": [
        "brate ovo je top, upravo mi je stigao order za 5 min",
        "@{mention} jel ide kupovina followera stvarno tako brzo?",
        "just bought 1000 tiktok views, works like magic",
        "auto-live je car, ne mogu da verujem",
        "@{mention} hvala za tip, refill mi je isao odmah",
        "kad su najbolje cene? uvek gledam popuste",
        "ljudi jel neko probao instagram likes od 5$?",
        "moj profil je porastao za 3k pratilaca za dan lol",
        "podrska je stvarno brza, 5* od mene",
    ],
    "en": [
        "yo just bought 500 likes, arrived in 2 minutes",
        "@{mention} does the tiktok live boost actually work?",
        "the auto-live feature is honestly next level",
        "bought a package yesterday, growth is real",
        "@{mention} how long did your order take to complete?",
        "10/10 recommend, been using this for months",
        "just topped up with crypto, super smooth",
        "anyone try the youtube subs? worth it?",
        "customer support replied in like 30 seconds wtf",
        "sold out on my listing thanks to the boost",
    ],
    "de": [
        "gerade 1000 follower gekauft, war in 5 minuten da",
        "@{mention} habt ihr das auto-live schon getestet?",
        "das ist echt der beste smm den ich benutzt habe",
        "support war mega schnell",
        "@{mention} lohnt sich das paket fuer 20$?",
        "bin richtig zufrieden, mein tiktok waechst wieder",
        "kryptozahlung hat auf anhieb geklappt",
        "die live-views sind unglaublich stabil, keine drops",
    ],
}


async def _fake_chat_activity_loop():
    import random
    await asyncio.sleep(20)
    while True:
        try:
            cfg = await db.app_settings.find_one({"_id": "singleton"}, {"fake_chat_enabled": 1})
            enabled = (cfg or {}).get("fake_chat_enabled", True)
            if not enabled:
                await asyncio.sleep(15); continue
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            recent_human = await db.public_chat.count_documents({
                "created_at": {"$gte": cutoff},
                "bot": {"$ne": True},
                "kind": {"$ne": "system"},
            })
            if recent_human >= 20:
                await asyncio.sleep(random.uniform(15, 25)); continue

            persona = random.choice(FAKE_CHAT_PERSONAS)
            lang = persona["lang"]
            template = random.choice(FAKE_CHAT_LINES[lang])
            mention_who = None
            if "{mention}" in template:
                other = random.choice([p for p in FAKE_CHAT_PERSONAS if p["username"] != persona["username"]])
                mention_who = other["username"]
                template = template.replace("{mention}", other["username"])
            await db.public_chat.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": f"fake:{persona['username']}",
                "username": persona["username"],
                "role": "user",
                "level": persona["level"],
                "avatar_url": persona.get("avatar_url"),
                "text": template,
                "bot": True,
                "lang": lang,
                "mentions": [mention_who] if mention_who else [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("[fake-chat] tick failed: %s", e)
        await asyncio.sleep(random.uniform(4, 8))


# ============ Fake orders (paired with fake chat toggle) ============
FAKE_ORDER_SERVICES = [
    ("Instagram Followers HQ",      500,   2.50),
    ("Instagram Followers HQ",      1000,  4.80),
    ("Instagram Likes",             250,   0.90),
    ("Instagram Likes",             1000,  3.20),
    ("Instagram Story Views",       500,   1.10),
    ("TikTok Followers",            500,   2.90),
    ("TikTok Followers",            1500,  8.20),
    ("TikTok Views",                5000,  1.50),
    ("TikTok Views",                25000, 6.40),
    ("TikTok Likes",                500,   1.20),
    ("TikTok Live Views",           300,   4.50),
    ("TikTok Live Comments (real)", 50,    5.90),
    ("YouTube Subscribers",         100,   3.80),
    ("YouTube Views",               1000,  1.90),
    ("YouTube Views",               10000, 12.40),
    ("YouTube Likes",               250,   1.00),
    ("Twitter/X Followers",         300,   4.20),
    ("Telegram Members",            500,   3.60),
    ("Auto-Live TikTok Boost",      250,   7.90),
]


async def _fake_order_activity_loop():
    """Paired with the fake chat toggle. Inserts a fake order into `db.orders`
    (bot=True) so the Latest Orders panels look busy and a masked purchase
    toast also fires via the public /orders/latest-global feed."""
    import random
    await asyncio.sleep(35)   # small offset so it doesn't collide with the chat worker
    while True:
        try:
            cfg = await db.app_settings.find_one({"_id": "singleton"}, {"fake_chat_enabled": 1})
            enabled = (cfg or {}).get("fake_chat_enabled", True)
            if not enabled:
                await asyncio.sleep(20); continue
            # Throttle when there's plenty of real-order flow so we don't drown it.
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            recent_real = await db.orders.count_documents({
                "created_at": {"$gte": cutoff},
                "bot": {"$ne": True},
            })
            if recent_real >= 15:
                await asyncio.sleep(random.uniform(40, 80)); continue

            persona = random.choice(FAKE_CHAT_PERSONAS)
            svc_name, qty, charge = random.choice(FAKE_ORDER_SERVICES)
            now = datetime.now(timezone.utc).isoformat()
            await db.orders.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": f"fake:{persona['username']}",
                "username": persona["username"],
                "service_name": svc_name,
                "service": svc_name,
                "quantity": qty,
                "charge": round(charge, 2),
                "total": round(charge, 2),
                "status": "Pending",
                "smm_order_id": None,
                "bot": True,
                "created_at": now,
            })
        except Exception as e:
            logger.warning("[fake-orders] tick failed: %s", e)
        # Slower cadence than chat — one order every 25-60 seconds.
        await asyncio.sleep(random.uniform(25, 60))


class FakeChatToggleBody(BaseModel):
    enabled: bool


@api_router.get("/admin/fake-chat/status")
async def admin_fake_chat_status(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "settings")
    cfg = await db.app_settings.find_one({"_id": "singleton"}, {"_id": 0, "fake_chat_enabled": 1}) or {}
    fake_count = await db.public_chat.count_documents({"bot": True})
    return {"enabled": cfg.get("fake_chat_enabled", True), "fake_message_count": fake_count}


@api_router.post("/admin/fake-chat/toggle")
async def admin_fake_chat_toggle(body: FakeChatToggleBody, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "settings")
    await db.app_settings.update_one({"_id": "singleton"}, {"$set": {"fake_chat_enabled": body.enabled}}, upsert=True)
    return {"ok": True, "enabled": body.enabled}


@api_router.post("/admin/fake-chat/purge")
async def admin_fake_chat_purge(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "settings")
    r = await db.public_chat.delete_many({"bot": True})
    return {"ok": True, "deleted": r.deleted_count}



async def _discord_bot_autostart():
    try:
        await asyncio.sleep(3)
        cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
        if cfg.get("auto_start") and (cfg.get("bot_token") or "").strip():
            from discord_bot import bot_manager as _bm
            words = [w.strip() for w in (cfg.get("banned_words") or "").split(",") if w.strip()]
            welcome = {"enabled": cfg.get("welcome_enabled"), "message": cfg.get("welcome_message"), "channel": cfg.get("welcome_channel")}
            await _bm.start(db, cfg["bot_token"].strip(), activity_text=cfg.get("activity_text") or "", banned_words=words, welcome=welcome)
            logger.info("[discord] auto-started bot after reload")
    except Exception as e:
        logger.warning("[discord] autostart failed: %s", e)


async def _chat_retention_loop():
    """Every 6 hours, purge chat messages older than 30 days across all chat collections.
    Keeps the DB lean and gives users a predictable retention window.
    Runs an immediate first purge on startup so old rows aren't held for 6h."""
    logger.info("[chat-retention] worker started (interval=6h, window=30 days)")
    first = True
    while True:
        try:
            if not first:
                await asyncio.sleep(6 * 60 * 60)  # every 6 hours after the initial run
            first = False
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            r1 = await db.public_chat.delete_many({"created_at": {"$lt": cutoff}})
            r2 = await db.ai_chat_messages.delete_many({"created_at": {"$lt": cutoff}})
            r3 = await db.direct_messages.delete_many({"created_at": {"$lt": cutoff}})
            logger.info(
                "[chat-retention] purged public=%s ai=%s dms=%s older than 30 days",
                r1.deleted_count, r2.deleted_count, r3.deleted_count,
            )
        except Exception as e:
            logger.error("[chat-retention] loop error: %s", e)
            await asyncio.sleep(300)


# ============ PAYPAL IPN (EMAIL-ONLY, NO API KEY) ============
# Admin sets their PayPal email in the panel. Any inbound payment to that
# receiver_email verified by PayPal's IPN validator will auto-credit the
# buyer's balance. Zero API keys required — this is PayPal's classic IPN
# protocol that they still support in 2026.
#
# Setup (admin does this ONCE in PayPal.com):
#   Profile → Settings → Merchant tools → Instant Payment Notifications →
#   Notify URL = https://<yourdomain>/api/paypal/ipn → Save.
# Then paste your receiver email in our Admin → Settings → PayPal.
# When users click "Deposit with PayPal" we generate a hosted payment URL
# with `custom={user_id}` so we know who to credit.

PAYPAL_IPN_VERIFY_URLS = {
    "live":    "https://ipnpb.paypal.com/cgi-bin/webscr",
    "sandbox": "https://ipnpb.sandbox.paypal.com/cgi-bin/webscr",
}


class PayPalConfig(BaseModel):
    receiver_email: str = Field(..., min_length=5, max_length=200)
    mode: str = Field(default="live", pattern="^(live|sandbox)$")
    bonus_pct: int = Field(default=0, ge=0, le=200)


@api_router.get("/admin/paypal-config")
async def admin_get_paypal_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.paypal_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    return {
        "configured": bool(cfg.get("receiver_email")),
        "receiver_email": cfg.get("receiver_email", ""),
        "mode": cfg.get("mode", "live"),
        "bonus_pct": int(cfg.get("bonus_pct", 0)),
    }


@api_router.post("/admin/paypal-config")
async def admin_set_paypal_config(payload: PayPalConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    await db.paypal_config.update_one(
        {"_id": "singleton"},
        {"$set": {
            "receiver_email": payload.receiver_email.strip().lower(),
            "mode": payload.mode,
            "bonus_pct": int(payload.bonus_pct),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True}


class PayPalDepositRequest(BaseModel):
    amount: float = Field(..., ge=1.0, le=10000.0)


def _paypal_checkout_url(cfg: dict, amount: float, item_name: str, custom: str, backend_url: str, mode: Optional[str] = None) -> str:
    base = "https://www.sandbox.paypal.com" if (mode or cfg.get("mode")) == "sandbox" else "https://www.paypal.com"
    params = {
        "cmd": "_xclick",
        "business": cfg["receiver_email"],
        "item_name": item_name,
        "amount": f"{amount:.2f}",
        "currency_code": "USD",
        "no_note": "1",
        "no_shipping": "1",
        "custom": custom,
        "notify_url": f"{backend_url}/api/paypal/ipn",
        "return":     f"{backend_url}/client/dashboard?paypal=success",
        "cancel_return": f"{backend_url}/client/dashboard?paypal=cancel",
    }
    return f"{base}/cgi-bin/webscr?{urlencode(params)}"


class PayPalTestReq(BaseModel):
    mode: str = Field(default="sandbox", pattern="^(live|sandbox)$")
    amount: float = Field(default=1.0, ge=0.01, le=100.0)


@api_router.post("/admin/paypal-test")
async def admin_paypal_test(body: PayPalTestReq, x_admin_token: Optional[str] = Header(None)):
    """Generate a test checkout URL (sandbox or live) so the admin can verify
    the PayPal flow end-to-end before going live."""
    check_admin(x_admin_token)
    cfg = await db.paypal_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    if not cfg.get("receiver_email"):
        raise HTTPException(status_code=400, detail="Save a receiver email first")
    backend_url = (os.environ.get("PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
    url = _paypal_checkout_url(cfg, body.amount, "Better Social — PayPal test payment",
                               f"paypaltest|{uuid.uuid4()}", backend_url, mode=body.mode)
    return {"checkout_url": url, "mode": body.mode}




@client_router.post("/funds/paypal-checkout")
async def paypal_checkout(body: PayPalDepositRequest, request: Request, user: CurrentUser = Depends(current_user_dep)):
    """Generate a hosted PayPal payment URL for the current user."""
    cfg = await db.paypal_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    if not cfg.get("receiver_email"):
        raise HTTPException(status_code=503, detail="PayPal deposits are not configured yet.")
    tx_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.transactions.insert_one({
        "id": tx_id, "user_id": user.id, "username": user.username,
        "amount": float(body.amount), "method": "paypal", "status": "pending",
        "type": "deposit", "created_at": now,
    })
    # Absolute public URL required so PayPal can call our IPN. Prefer explicit
    # env var, else construct from the incoming request headers.
    backend_url = (
        os.environ.get("PUBLIC_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL")
        or ""
    ).rstrip("/")
    if not backend_url:
        # Reconstruct scheme + host from request as a last resort
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        proto = request.headers.get("x-forwarded-proto") or "https"
        if host:
            backend_url = f"{proto}://{host}"
    if not backend_url:
        raise HTTPException(status_code=500, detail="PUBLIC_BACKEND_URL is not configured. Ask the admin to set it.")
    base = "https://www.sandbox.paypal.com" if cfg.get("mode") == "sandbox" else "https://www.paypal.com"
    params = {
        "cmd": "_xclick",
        "business": cfg["receiver_email"],
        "item_name": f"Better Social deposit — {user.username}",
        "amount": f"{body.amount:.2f}",
        "currency_code": "USD",
        "no_note": "1",
        "no_shipping": "1",
        "custom": f"{user.id}|{tx_id}",
        "notify_url": f"{backend_url}/api/paypal/ipn",
        "return":     f"{backend_url}/client/dashboard?paypal=success",
        "cancel_return": f"{backend_url}/client/dashboard?paypal=cancel",
    }
    return {"checkout_url": f"{base}/cgi-bin/webscr?{urlencode(params)}", "tx_id": tx_id}


@api_router.post("/paypal/ipn")
async def paypal_ipn(request: Request):
    """PayPal IPN endpoint. PayPal POSTs form-encoded data here after a
    payment completes. We MUST echo it back to PayPal to verify, then credit
    the user identified by the `custom` field.

    Never rejects with 4xx (PayPal will retry forever) — always 200, log details."""
    try:
        raw = await request.body()
        form = await request.form()
    except Exception as e:
        logger.warning("[paypal-ipn] failed to read body: %s", e)
        return {"ok": False, "error": "bad_body"}
    cfg = await db.paypal_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    verify_url = PAYPAL_IPN_VERIFY_URLS["sandbox" if cfg.get("mode") == "sandbox" else "live"]
    # Verification: echo the exact bytes back prefixed with cmd=_notify-validate
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(
                verify_url,
                content=b"cmd=_notify-validate&" + raw,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "BetterSocial-IPN"},
            )
        verified = r.text.strip() == "VERIFIED"
    except Exception as e:
        verified = False
        logger.warning("[paypal-ipn] verify failed: %s", e)

    payment_status = (form.get("payment_status") or "").strip()
    receiver = (form.get("receiver_email") or form.get("business") or "").strip().lower()
    txn_id = (form.get("txn_id") or "").strip()
    # Safe numeric parsing — malformed values must never 500 (PayPal retries forever on 5xx)
    try:
        gross = float(form.get("mc_gross") or 0)
    except (TypeError, ValueError):
        gross = 0.0
    currency = (form.get("mc_currency") or "USD").upper()
    custom = (form.get("custom") or "").strip()
    parts = (custom.split("|", 1) + [""])[:2]
    user_id, our_tx_id = parts[0], parts[1]

    try:
        await db.paypal_events.insert_one({
            "id": str(uuid.uuid4()),
            "verified": verified,
            "payment_status": payment_status,
            "receiver_email": receiver,
            "txn_id": txn_id,
            "gross": gross,
            "currency": currency,
            "custom": custom,
            "user_id": user_id,
            "our_tx_id": our_tx_id,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": {k: str(v) for k, v in form.items()},
        })
    except Exception as e:
        logger.warning("[paypal-ipn] event log failed: %s", e)

    # From here on, ALWAYS return 200 — PayPal retries indefinitely on 4xx/5xx
    try:
        if not verified:
            logger.warning("[paypal-ipn] NOT verified (status=%s receiver=%s)", payment_status, receiver)
            return {"ok": True}
        if payment_status != "Completed":
            logger.info("[paypal-ipn] ignored status=%s (waiting for Completed)", payment_status)
            return {"ok": True}
        expected_receiver = (cfg.get("receiver_email") or "").strip().lower()
        if not expected_receiver or receiver != expected_receiver:
            logger.warning("[paypal-ipn] receiver mismatch: got=%s expected=%s", receiver, expected_receiver)
            return {"ok": True}
        if currency != "USD" or gross <= 0:
            logger.warning("[paypal-ipn] bad amount/currency: %s %s", gross, currency)
            return {"ok": True}
        if not user_id or not our_tx_id:
            logger.warning("[paypal-ipn] no custom field — can't attribute")
            return {"ok": True}
        # Idempotency: if we've already credited this PayPal txn_id, skip
        if txn_id and await db.transactions.find_one({"paypal_txn_id": txn_id, "status": "approved"}, {"_id": 0, "id": 1}):
            logger.info("[paypal-ipn] duplicate — already credited %s", txn_id)
            return {"ok": True}

        now = datetime.now(timezone.utc).isoformat()
        bonus_pct = int(cfg.get("bonus_pct") or 0)
        bonus = round(gross * bonus_pct / 100.0, 2) if bonus_pct else 0.0

        # Atomic update — only credit if the pending tx actually exists for THIS user.
        # Prevents orphan credit when attacker sends fake custom=validUser|fakeTx.
        upd = await db.transactions.update_one(
            {"id": our_tx_id, "user_id": user_id, "method": "paypal", "status": "pending"},
            {"$set": {"status": "approved", "approved_at": now, "amount": gross, "paypal_txn_id": txn_id}},
        )
        if upd.matched_count == 0:
            logger.warning(
                "[paypal-ipn] refused — no pending tx=%s for user=%s (possible spoofed custom field)",
                our_tx_id, user_id,
            )
            return {"ok": True}
        # Now-and-only-now the deposit is confirmed → optional bonus + email
        if bonus > 0:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": user_id,
                "amount": bonus, "method": "paypal_bonus", "status": "approved",
                "type": "bonus", "note": f"+{bonus_pct}% PayPal deposit bonus",
                "linked_tx_id": our_tx_id, "created_at": now, "approved_at": now,
            })
        try:
            from notification_service import notify_deposit_credited
            backend_url = (os.environ.get("PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
            asyncio.create_task(notify_deposit_credited(db, user_id, gross, bonus, backend_url, method="paypal"))
        except Exception:
            pass
        logger.info("[paypal-ipn] CREDITED user=%s $%s (+$%s bonus) txn=%s", user_id, gross, bonus, txn_id)
        await _maybe_referral_rewards(user_id)
        return {"ok": True}
    except Exception as e:
        logger.exception("[paypal-ipn] handler failed: %s", e)
        return {"ok": True}


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
    api_key: Optional[str] = ""
    ipn_secret: Optional[str] = ""
    email: Optional[str] = ""
    password: Optional[str] = ""


@api_router.get("/admin/nowpayments-config")
async def admin_get_nowpayments_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.nowpayments_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    key = cfg.get("api_key", "")
    return {
        "configured": bool(key),
        "api_key_masked": ("*" * 6 + key[-6:]) if key else "",
        "ipn_secret_set": bool(cfg.get("ipn_secret")),
        "email": cfg.get("email", ""),
        "password_set": bool(cfg.get("password")),
    }


@api_router.post("/admin/nowpayments-config")
async def admin_set_nowpayments_config(payload: NowpaymentsConfig, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    existing = await db.nowpayments_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    upd = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if payload.api_key and payload.api_key.strip():
        upd["api_key"] = payload.api_key.strip()
    elif not existing.get("api_key"):
        raise HTTPException(status_code=400, detail="API key is required")
    if payload.ipn_secret:
        upd["ipn_secret"] = payload.ipn_secret.strip()
    if payload.email:
        upd["email"] = payload.email.strip().lower()
    if payload.password:
        upd["password"] = payload.password  # stored as-is; used only server-side for JWT exchange
    await db.nowpayments_config.update_one({"_id": "singleton"}, {"$set": upd}, upsert=True)
    return {"configured": True}


# ============ ADMIN ALERTS (underpaid deposits etc.) ============

@api_router.get("/admin/alerts")
async def admin_list_alerts(status: str = "open", x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    q = {"status": status} if status != "all" else {}
    cur = db.admin_alerts.find(q, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"alerts": await cur.to_list(100)}


@api_router.post("/admin/alerts/{aid}/dismiss")
async def admin_dismiss_alert(aid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    r = await db.admin_alerts.update_one(
        {"id": aid, "status": "open"},
        {"$set": {"status": "dismissed", "resolved_at": datetime.now(timezone.utc).isoformat()}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    return {"ok": True}


class PartialCreditReq(BaseModel):
    amount: Optional[float] = None  # defaults to the estimated paid USD


@api_router.post("/admin/deposits/{tx_id}/verify")
async def admin_verify_nowpayments_deposit(tx_id: str, x_admin_token: Optional[str] = Header(None)):
    """Manual safety net: fetch the latest status from NOWPayments for a
    pending crypto transaction and credit the user if the payment is
    'finished'/'confirmed'. Use this when the IPN webhook didn't arrive
    (blocked, rate-limited, or user closed the tab).

    Returns a detailed status object so the owner sees exactly what happened
    without having to read logs."""
    check_admin(x_admin_token)
    tx = await db.transactions.find_one({"id": tx_id})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.get("status") == "approved":
        return {"ok": True, "already_credited": True, "balance_delta": 0}
    invoice_id = tx.get("nowpayments_invoice_id")
    payment_id = tx.get("nowpayments_payment_id")
    if not invoice_id and not payment_id:
        raise HTTPException(status_code=400, detail="No NOWPayments invoice/payment ID stored on this transaction")
    try:
        payment = await _fetch_nowpayments_invoice_status(invoice_id or payment_id)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NOWPayments API error: {e}")
    if not payment:
        return {"ok": False, "status": "no_payment_yet", "message": "No payment record on NOWPayments yet. Buyer hasn't sent crypto."}
    pstatus = (payment.get("payment_status") or payment.get("status") or "").lower()
    if pstatus in NOWPAY_SUCCESS_STATUSES:
        # Save the payment_id if we didn't have it before
        if payment.get("payment_id") and not tx.get("nowpayments_payment_id"):
            await db.transactions.update_one({"id": tx_id}, {"$set": {"nowpayments_payment_id": payment["payment_id"]}})
            tx["nowpayments_payment_id"] = payment["payment_id"]
        result = await _credit_nowpayments_deposit(tx, payment)
        return {"ok": True, "credited": True, "status": pstatus, **(result or {})}
    if pstatus == "partially_paid":
        r = await _handle_nowpayments_underpaid(tx, payment)
        return {"ok": True, "partial": True, "status": pstatus, **(r or {})}
    return {
        "ok": True, "credited": False, "status": pstatus,
        "message": f"Payment status is '{pstatus}' — not yet finished. Try again in a few minutes.",
        "raw": {k: payment.get(k) for k in ("payment_status", "actually_paid", "price_amount", "pay_currency", "pay_amount")},
    }


@api_router.post("/admin/deposits/{tx_id}/credit-partial")
async def admin_credit_partial_deposit(tx_id: str, body: PartialCreditReq, x_admin_token: Optional[str] = Header(None)):
    """Credit an underpaid crypto deposit for the amount actually received
    (e.g. buyer paid $93 of a $100 invoice → credit $93). Applies the standard
    70% deposit bonus on the credited amount and resolves the admin alert."""
    check_admin(x_admin_token)
    tx = await db.transactions.find_one({"id": tx_id, "method": "nowpayments"})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.get("status") == "approved":
        return {"ok": True, "already_credited": True}
    credit = round(float(body.amount if body.amount is not None else (tx.get("paid_usd") or 0)), 2)
    if credit <= 0:
        raise HTTPException(status_code=400, detail="Credit amount must be > 0")
    invoice_amount = round(float(tx.get("amount") or 0), 2)
    bonus = round(credit * 0.70, 2)
    now = datetime.now(timezone.utc).isoformat()
    upd = await db.transactions.update_one(
        {"id": tx_id, "status": {"$ne": "approved"}},
        {"$set": {
            "status": "approved",
            "approved_at": now,
            "amount": credit,
            "original_invoice_amount": invoice_amount,
            "partial_credit": True,
            "bonus_applied": bonus,
            "note": f"Partial credit ${credit:.2f} of ${invoice_amount:.2f} invoice (admin approved)",
        }},
    )
    if upd.modified_count == 0:
        return {"ok": True, "already_credited": True}
    if bonus > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": tx["user_id"], "username": tx.get("username"),
            "amount": bonus, "method": "bonus", "status": "approved", "type": "deposit_bonus",
            "note": f"+70% crypto deposit bonus on ${credit:.2f} (partial payment)",
            "created_at": now, "approved_at": now, "linked_tx": tx_id,
        })
    await db.admin_alerts.update_many(
        {"tx_id": tx_id, "status": "open"},
        {"$set": {"status": "resolved", "resolved_at": now, "credited_amount": credit}},
    )
    logger.info(f"[nowpay] PARTIAL-CREDITED tx={tx_id} user={tx.get('username')} ${credit} of ${invoice_amount} bonus=${bonus}")
    try:
        from notification_service import notify_deposit_credited
        backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
        asyncio.create_task(notify_deposit_credited(db, tx["user_id"], credit, bonus, backend_url, method="crypto (partial)"))
    except Exception as e:
        logger.warning(f"[nowpay] partial-credit email failed: {e}")
    return {"ok": True, "credited": credit, "bonus": bonus, "invoice_amount": invoice_amount}


# ============ FREE BALANCE BONUSES (admin gift → user claims via popup) ============

class BonusCreateReq(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, max_length=500)
    amount: float


@api_router.post("/admin/bonuses/create")
async def admin_create_bonuses(body: BonusCreateReq, x_admin_token: Optional[str] = Header(None)):
    """Gift a free balance bonus (5–1000 €) to one or many users. Each user gets
    a claim popup on the purchase page and an email notification."""
    check_admin(x_admin_token)
    amount = round(float(body.amount), 2)
    if amount < 5 or amount > 1000:
        raise HTTPException(status_code=400, detail="Bonus amount must be between €5 and €1000")
    now = datetime.now(timezone.utc).isoformat()
    created, skipped = [], []
    backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
    for uid in body.user_ids:
        u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "username": 1, "email": 1})
        if not u:
            skipped.append(uid)
            continue
        bid = str(uuid.uuid4())
        await db.balance_bonuses.insert_one({
            "id": bid,
            "user_id": uid,
            "username": u.get("username"),
            "amount": amount,
            "status": "pending",
            "created_at": now,
        })
        created.append({"id": bid, "username": u.get("username")})
        try:
            from notification_service import notify_bonus_waiting
            asyncio.create_task(notify_bonus_waiting(db, uid, amount, backend_url))
        except Exception as e:
            logger.warning("[bonus] email failed for %s: %s", uid, e)
    logger.info("[bonus] admin gifted €%.2f to %s users (%s skipped)", amount, len(created), len(skipped))
    return {"ok": True, "created": len(created), "skipped": skipped, "bonuses": created}


@api_router.get("/admin/bonuses")
async def admin_list_bonuses(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cur = db.balance_bonuses.find({}, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"bonuses": await cur.to_list(100)}


@api_router.post("/admin/bonuses/{bid}/expire")
async def admin_expire_bonus(bid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    r = await db.balance_bonuses.update_one(
        {"id": bid, "status": "pending"},
        {"$set": {"status": "expired", "expired_at": datetime.now(timezone.utc).isoformat(), "expired_by": "admin"}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=404, detail="Bonus not found or not pending")
    return {"ok": True}


@client_router.get("/gifts/recent")
async def client_recent_gifts(user: CurrentUser = Depends(current_user_dep)):
    """Latest gifts received: free balance bonuses + admin-gifted orders."""
    bonuses = await db.balance_bonuses.find(
        {"user_id": user.id}, {"_id": 0, "id": 1, "amount": 1, "status": 1, "created_at": 1}
    ).sort("created_at", -1).limit(10).to_list(10)
    gift_orders = await db.orders.find(
        {"user_id": user.id, "is_gift": True},
        {"_id": 0, "id": 1, "service_name": 1, "quantity": 1, "status": 1, "created_at": 1},
    ).sort("created_at", -1).limit(10).to_list(10)
    items = [
        {"kind": "balance_bonus", "id": b["id"], "amount": b.get("amount"), "status": b.get("status"), "created_at": b.get("created_at")}
        for b in bonuses
    ] + [
        {"kind": "gift_order", "id": o["id"], "service_name": o.get("service_name"), "quantity": o.get("quantity"), "status": o.get("status"), "created_at": o.get("created_at")}
        for o in gift_orders
    ]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"gifts": items[:12]}


@client_router.get("/bonuses/pending")
async def client_pending_bonuses(user: CurrentUser = Depends(current_user_dep)):
    cur = db.balance_bonuses.find({"user_id": user.id, "status": "pending"}, {"_id": 0}).sort("created_at", -1).limit(10)
    return {"bonuses": await cur.to_list(10)}


@client_router.post("/bonuses/{bid}/claim")
async def client_claim_bonus(bid: str, user: CurrentUser = Depends(current_user_dep)):
    bonus = await db.balance_bonuses.find_one({"id": bid, "user_id": user.id})
    if not bonus:
        raise HTTPException(status_code=404, detail="Bonus not found")
    now = datetime.now(timezone.utc).isoformat()
    r = await db.balance_bonuses.update_one(
        {"id": bid, "status": "pending"},
        {"$set": {"status": "claimed", "claimed_at": now}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=409, detail="Bonus already claimed or expired")
    amount = round(float(bonus.get("amount") or 0), 2)
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
        "amount": amount, "method": "bonus", "status": "approved", "type": "balance_bonus",
        "note": f"Free balance bonus claimed (€{amount:.2f})",
        "bonus_id": bid, "created_at": now, "approved_at": now,
    })
    logger.info("[bonus] user %s claimed €%.2f (bonus=%s)", user.username, amount, bid)
    return {"ok": True, "claimed": amount}


@client_router.post("/bonuses/{bid}/decline")
async def client_decline_bonus(bid: str, user: CurrentUser = Depends(current_user_dep)):
    r = await db.balance_bonuses.update_one(
        {"id": bid, "user_id": user.id, "status": "pending"},
        {"$set": {"status": "expired", "expired_at": datetime.now(timezone.utc).isoformat(), "expired_by": "user"}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=404, detail="Bonus not found or not pending")
    return {"ok": True, "declined": True}


# ============ DB MANAGER (phpMyAdmin-style · OWNER ONLY · separate page) ============
from bson import ObjectId as _ObjectId  # noqa: E402


# Secret fields are never sent to the browser; the editor shows a placeholder
# and the update endpoint drops unchanged placeholders so they aren't clobbered.
DBADMIN_SECRET_KEYS = {
    "password_hash", "password", "api_key", "ipn_secret", "bot_token",
    "shared_secret", "smtp_password", "elastic_api_key", "payment_api_key",
    "jwt_secret", "secret",
}
DBADMIN_REDACTED = "•••REDACTED•••"


# Collections that can NEVER be dropped/emptied via the DB manager. Users can
# still edit individual documents, but no wipe. This preserves user balances /
# staff credentials even if the owner accidentally clicks "delete history".
DBADMIN_PROTECTED_COLLECTIONS = {
    "users", "admin_users", "smm_providers", "wallets",
    "app_settings", "nowpayments_config", "paypal_config",
    "coinpayments_config", "selly_config",
}
# Fields inside a `users` document that must never be touched from the DB
# manager. Balance changes happen through purchases/refunds only.
DBADMIN_PROTECTED_USER_FIELDS = {
    "balance", "withdrawable_balance", "role", "password_hash",
    "banned", "session_epoch",
}


def _dbadmin_redact(obj):
    if isinstance(obj, dict):
        return {
            k: (DBADMIN_REDACTED if k.lower() in DBADMIN_SECRET_KEYS and v not in (None, "") else _dbadmin_redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_dbadmin_redact(v) for v in obj]
    return obj


def _dbadmin_strip_redacted(obj):
    if isinstance(obj, dict):
        return {k: _dbadmin_strip_redacted(v) for k, v in obj.items() if v != DBADMIN_REDACTED}
    if isinstance(obj, list):
        return [_dbadmin_strip_redacted(v) for v in obj]
    return obj


def _dbadmin_sanitize(doc: dict) -> dict:
    return _dbadmin_redact(jsonlib.loads(jsonlib.dumps(doc, default=str)))


def _dbadmin_id_query(doc_id: str) -> dict:
    ors = [{"id": doc_id}, {"_id": doc_id}]
    try:
        ors.append({"_id": _ObjectId(doc_id)})
    except Exception:
        pass
    return {"$or": ors}


@api_router.get("/dbadmin/collections")
async def dbadmin_collections(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    names = await db.list_collection_names()
    out = []
    for n in sorted(names):
        out.append({"name": n, "count": await db[n].estimated_document_count()})
    return {"collections": out}


@api_router.get("/dbadmin/{coll}/docs")
async def dbadmin_list_docs(
    coll: str,
    skip: int = 0,
    limit: int = 25,
    q: str = "",
    filter_json: str = "",
    x_admin_token: Optional[str] = Header(None),
):
    check_owner(x_admin_token)
    limit = max(1, min(limit, 100))
    query: dict = {}
    if filter_json.strip():
        try:
            query = jsonlib.loads(filter_json)
        except Exception:
            raise HTTPException(status_code=400, detail="filter_json is not valid JSON")
    elif q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query = {"$or": [{"id": rx}, {"username": rx}, {"email": rx}, {"name": rx}, {"title": rx}, {"status": rx}, {"tiktok_username": rx}]}
    total = await db[coll].count_documents(query) if query else await db[coll].estimated_document_count()
    cur = db[coll].find(query).sort("_id", -1).skip(skip).limit(limit)
    docs = [_dbadmin_sanitize(d) for d in await cur.to_list(limit)]
    return {"docs": docs, "total": total, "skip": skip, "limit": limit}


class DbAdminDocBody(BaseModel):
    doc: dict


@api_router.post("/dbadmin/{coll}/doc")
async def dbadmin_insert_doc(coll: str, body: DbAdminDocBody, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    doc = dict(body.doc)
    doc.pop("_id", None)
    r = await db[coll].insert_one(doc)
    return {"ok": True, "inserted_id": str(r.inserted_id)}


async def _dbadmin_snapshot_balances_before_delete(coll: str, filter_query: dict) -> int:
    """Before deleting transaction rows, aggregate the net approved amount PER user
    from the doomed rows and insert a compensating 'carry_forward' transaction so
    every user's derived balance stays exactly the same after the deletion.

    Returns the number of carry-forward rows inserted (one per affected user).
    Only runs for the `transactions` collection — no-op for anything else.
    """
    if coll != "transactions":
        return 0
    match: dict = {"status": "approved"}
    if filter_query:
        match = {"$and": [match, filter_query]}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"user_id": "$user_id", "username": "$username"},
                     "net": {"$sum": "$amount"}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(None)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for r in rows:
        user_id = r["_id"].get("user_id")
        if not user_id or not r["net"]:
            continue
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "username": r["_id"].get("username"),
            "amount": float(r["net"]),
            "method": "balance",
            "status": "approved",
            "type": "carry_forward",
            "note": "Carry-forward preserving balance after history deletion from DB manager",
            "created_at": now,
            "approved_at": now,
            "protected": True,
        })
        inserted += 1
    return inserted


@api_router.put("/dbadmin/{coll}/doc/{doc_id}")
async def dbadmin_update_doc(coll: str, doc_id: str, body: DbAdminDocBody, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    doc = _dbadmin_strip_redacted(dict(body.doc))
    doc.pop("_id", None)
    if coll == "users":
        # Never let the DB manager overwrite money / role / auth fields on users.
        blocked = [f for f in DBADMIN_PROTECTED_USER_FIELDS if f in doc]
        for f in blocked:
            doc.pop(f, None)
        if blocked:
            logger.warning("[dbadmin] blocked protected user fields on update: %s", blocked)
    r = await db[coll].update_one(_dbadmin_id_query(doc_id), {"$set": doc})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True, "modified": r.modified_count}


@api_router.delete("/dbadmin/{coll}/doc/{doc_id}")
async def dbadmin_delete_doc(coll: str, doc_id: str, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    if coll in DBADMIN_PROTECTED_COLLECTIONS:
        raise HTTPException(status_code=403,
                            detail=f"Collection '{coll}' is protected and can't be deleted from the DB manager.")
    if coll == "transactions":
        # Never delete carry-forward or a single row without preserving balance.
        target = await db.transactions.find_one(_dbadmin_id_query(doc_id), {"_id": 0})
        if target and target.get("protected"):
            raise HTTPException(status_code=403, detail="This is a balance carry-forward row and can't be deleted.")
        if target and target.get("status") == "approved" and target.get("user_id") and target.get("amount"):
            await _dbadmin_snapshot_balances_before_delete(
                "transactions", {"id": target.get("id"), "user_id": target["user_id"]}
            )
    r = await db[coll].delete_one(_dbadmin_id_query(doc_id))
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


class DbAdminDeleteManyBody(BaseModel):
    filter: dict = {}
    confirm_all: bool = False


@api_router.post("/dbadmin/{coll}/delete-many")
async def dbadmin_delete_many(coll: str, body: DbAdminDeleteManyBody, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    if coll in DBADMIN_PROTECTED_COLLECTIONS:
        raise HTTPException(status_code=403,
                            detail=f"Collection '{coll}' is protected — mass-delete is disabled to preserve user balances / staff credentials.")
    if not body.filter and not body.confirm_all:
        raise HTTPException(status_code=400, detail="Empty filter deletes ALL documents — set confirm_all=true to proceed")
    carry = 0
    filt = dict(body.filter or {})
    if coll == "transactions":
        # Never touch carry-forward rows — they hold accumulated balance.
        filt.setdefault("protected", {"$ne": True})
        carry = await _dbadmin_snapshot_balances_before_delete("transactions", filt)
    r = await db[coll].delete_many(filt)
    logger.warning("[dbadmin] delete-many on %s filter=%s → deleted %s (carry-forwarded %s users)",
                   coll, filt, r.deleted_count, carry)
    return {"ok": True, "deleted": r.deleted_count, "carry_forwarded_users": carry}


# ============ DB BACKUPS (auto every 6 hours, owner-only) ============
DB_BACKUP_DIR = "/app/backups"
DB_BACKUP_INTERVAL_SEC = 6 * 60 * 60      # every 6 hours
DB_BACKUP_KEEP = 20                        # keep last 20 snapshots


async def _db_backup_run_once() -> dict:
    """Snapshot every collection to a single JSON file. Returns {name, path, size, collections, docs}."""
    import gzip
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"backup_{ts}.json.gz"
    path = os.path.join(DB_BACKUP_DIR, name)
    payload = {"created_at": datetime.now(timezone.utc).isoformat(), "collections": {}}
    total_docs = 0
    for coll in await db.list_collection_names():
        try:
            docs = await db[coll].find({}).to_list(None)
        except Exception as e:
            logger.warning("[db-backup] skip %s: %s", coll, e)
            continue
        payload["collections"][coll] = jsonlib.loads(jsonlib.dumps(docs, default=str))
        total_docs += len(docs)
    raw = jsonlib.dumps(payload, ensure_ascii=False).encode("utf-8")
    with gzip.open(path, "wb") as fh:
        fh.write(raw)
    size = os.path.getsize(path)
    # rotate — keep only DB_BACKUP_KEEP most recent
    files = sorted(
        [f for f in os.listdir(DB_BACKUP_DIR) if f.startswith("backup_") and f.endswith(".json.gz")],
        reverse=True,
    )
    for old in files[DB_BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(DB_BACKUP_DIR, old))
            await db.db_backups.delete_many({"name": old})
        except Exception:
            pass
    await db.db_backups.insert_one({
        "id": str(uuid.uuid4()), "name": name, "size": size,
        "collections": len(payload["collections"]), "docs": total_docs,
        "created_at": payload["created_at"],
    })
    logger.info("[db-backup] wrote %s (%.1f KB, %s docs)", name, size / 1024, total_docs)
    return {"name": name, "path": path, "size": size,
            "collections": len(payload["collections"]), "docs": total_docs}


async def _db_backup_loop():
    """Background worker — snapshot the DB every 6 hours forever."""
    # Small startup delay so we don't collide with other startup work.
    await asyncio.sleep(60)
    while True:
        try:
            await _db_backup_run_once()
        except Exception as e:
            logger.warning("[db-backup] scheduled run failed: %s", e)
        await asyncio.sleep(DB_BACKUP_INTERVAL_SEC)


@api_router.get("/admin/db-backups")
async def admin_list_db_backups(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    out = []
    for name in sorted(os.listdir(DB_BACKUP_DIR), reverse=True):
        if not (name.startswith("backup_") and name.endswith(".json.gz")):
            continue
        full = os.path.join(DB_BACKUP_DIR, name)
        try:
            st = os.stat(full)
        except Exception:
            continue
        out.append({
            "name": name, "size": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return {"backups": out, "next_run_hours": DB_BACKUP_INTERVAL_SEC / 3600, "keep": DB_BACKUP_KEEP}


@api_router.post("/admin/db-backups/run")
async def admin_run_db_backup(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    return await _db_backup_run_once()


@api_router.get("/admin/db-backups/{name}/download")
async def admin_download_db_backup(name: str, x_admin_token: Optional[str] = Header(None), t: Optional[str] = None):
    check_owner(x_admin_token or t)
    if not (name.startswith("backup_") and name.endswith(".json.gz")):
        raise HTTPException(status_code=400, detail="Invalid backup name")
    path = os.path.join(DB_BACKUP_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=name, media_type="application/gzip")


@api_router.delete("/admin/db-backups/{name}")
async def admin_delete_db_backup(name: str, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    if not (name.startswith("backup_") and name.endswith(".json.gz")):
        raise HTTPException(status_code=400, detail="Invalid backup name")
    path = os.path.join(DB_BACKUP_DIR, name)
    if os.path.exists(path):
        os.remove(path)
        await db.db_backups.delete_many({"name": name})
        return {"ok": True, "deleted": name}
    raise HTTPException(status_code=404, detail="Backup not found")


# ============ Live user activity feed (owner-only) ============
# The client pings /client/activity/heartbeat every ~5s with its current route +
# viewport + last user action. Owner can view /admin/activity/live to see every
# active user in real time (Option A — lightweight activity feed, no DOM replay).

class ActivityHeartbeatBody(BaseModel):
    route: Optional[str] = None
    viewport: Optional[str] = None
    action: Optional[str] = None  # last click / nav / form field name (no values)
    referrer: Optional[str] = None


@api_router.post("/client/activity/heartbeat")
async def client_activity_heartbeat(body: ActivityHeartbeatBody, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    now = datetime.now(timezone.utc)
    ip = (request.headers.get("x-forwarded-for") or request.client.host if request else "") or ""
    doc = {
        "user_id": user.id,
        "username": user.username,
        "route": (body.route or "")[:120],
        "viewport": (body.viewport or "")[:20],
        "last_action": (body.action or "")[:120],
        "referrer": (body.referrer or "")[:200],
        "ip": ip.split(",")[0].strip(),
        "user_agent": (request.headers.get("user-agent") or "")[:200] if request else "",
        "updated_at": now.isoformat(),
    }
    await db.activity_live.update_one({"user_id": user.id}, {"$set": doc, "$setOnInsert": {"started_at": now.isoformat()}}, upsert=True)
    # Also store the last 30 actions per user as a lightweight breadcrumb trail.
    if body.action:
        await db.activity_trail.insert_one({
            "user_id": user.id, "username": user.username,
            "route": body.route, "action": body.action,
            "created_at": now.isoformat(),
        })
    return {"ok": True}


@api_router.get("/admin/activity/live")
async def admin_activity_live(x_admin_token: Optional[str] = Header(None), stale_minutes: int = 5):
    check_admin(x_admin_token, "audit")
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
    rows = await db.activity_live.find({"updated_at": {"$gte": cutoff}}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return {"active_users": rows, "stale_minutes": stale_minutes}


@api_router.get("/admin/activity/user/{user_id}")
async def admin_activity_user(user_id: str, x_admin_token: Optional[str] = Header(None), limit: int = 50):
    check_admin(x_admin_token, "audit")
    live = await db.activity_live.find_one({"user_id": user_id}, {"_id": 0})
    trail = await db.activity_trail.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 200))
    return {"live": live, "trail": trail}


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
            # /clear         → delete every message in the room
            # /clear <N>     → delete the latest N messages only (1..1000)
            n_arg = parts[1] if len(parts) >= 2 else None
            if n_arg and n_arg.isdigit():
                n = max(1, min(1000, int(n_arg)))
                # Grab the ids of the last N messages ordered by created_at DESC
                ids = [d["id"] for d in await db.public_chat.find({}, {"_id": 0, "id": 1}).sort("created_at", -1).limit(n).to_list(n)]
                r = await db.public_chat.delete_many({"id": {"$in": ids}})
                label = f"last {r.deleted_count} messages"
            else:
                r = await db.public_chat.delete_many({})
                label = f"{r.deleted_count} messages"
            await db.public_chat.insert_one({
                "id": str(uuid.uuid4()), "user_id": user.id, "username": user.username,
                "role": role, "text": f"🧹 Chat cleared by @{user.username} ({label})",
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
    # Award chat XP so the level badge grows over time
    try:
        await _award_chat_xp(user.id, 3)
    except Exception as _e:
        logger.warning(f"[xp] award failed for {user.id}: {_e}")

    # ---- Auto-moderation reply bot ----
    # If the user's message hints at needing help / support / contact, drop a
    # friendly system reply pointing them at Live Chat + Ticket. Runs at most
    # once every 5 minutes per user so we don't spam the room.
    try:
        text_low = text.lower()
        HELP_KEYWORDS = ("help", "support", "contact", "how do i", "how can i", "problem", "issue", "not working", "stuck", "please help", "assistance", "@admin", "@owner", "@staff")
        if any(kw in text_low for kw in HELP_KEYWORDS):
            last_bot = await db.public_chat.find_one(
                {"kind": "bot_help", "reply_to_user_id": user.id},
                sort=[("created_at", -1)],
                projection={"created_at": 1},
            )
            fresh = True
            if last_bot and last_bot.get("created_at"):
                try:
                    gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last_bot["created_at"])).total_seconds()
                    if gap < 300:  # 5 minute cooldown per user
                        fresh = False
                except Exception:
                    pass
            if fresh:
                await db.public_chat.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": None,
                    "username": "BetterBot",
                    "role": "system",
                    "text": f"👋 Hey @{user.username} — need a hand? Reach us any time via the 💬 Live Chat widget (bottom-right) or open a 🎟️ Ticket from Help → Contact. A human staff member replies fast.",
                    "kind": "bot_help",
                    "reply_to_user_id": user.id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as _e:
        logger.warning(f"[bot_help] auto-reply failed: {_e}")

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
    # Enrich each message with the sender's chat rank + level + avatar
    rank_cache: dict = {}
    user_cache: dict = {}
    for m in msgs:
        uid = m.get("user_id")
        if uid and uid not in rank_cache:
            rank_cache[uid] = _rank_from_amount(await _user_deposits_total(uid))
            u = await db.users.find_one(
                {"id": uid},
                {"_id": 0, "avatar_url": 1, "chat_level": 1, "chat_xp": 1},
            ) or {}
            user_cache[uid] = u
        r = rank_cache.get(uid) or _rank_from_amount(0)
        u = user_cache.get(uid) or {}
        m["rank_name"] = r["name"]
        m["rank_text_class"] = r["text_class"]
        m["rank_border_class"] = r["border_class"]
        # Preserve the avatar/level already on the message (e.g. fake personas)
        # when the user lookup didn't find a real user for that id.
        if u:
            m["avatar_url"] = u.get("avatar_url") or m.get("avatar_url")
            m["level"] = int(u.get("chat_level") or _level_from_xp(u.get("chat_xp") or 0))
        else:
            m.setdefault("level", m.get("level") or 1)
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


def _level_from_xp(xp: float | int) -> int:
    """XP → chat level. Every level costs a growing amount of XP.
    Formula: level = floor(sqrt(xp / 25)) + 1 → L1 (0 xp), L2 (25 xp), L3 (100), L4 (225), L5 (400)…"""
    try:
        v = max(0, int(xp))
    except (TypeError, ValueError):
        v = 0
    import math as _math
    return int(_math.isqrt(v // 25)) + 1


async def _award_chat_xp(user_id: str, amount: int = 3) -> int:
    """Increment user's chat XP + recompute level. Returns new level."""
    await db.users.update_one({"id": user_id}, {"$inc": {"chat_xp": amount}})
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "chat_xp": 1})
    new_xp = int((doc or {}).get("chat_xp") or 0)
    new_level = _level_from_xp(new_xp)
    await db.users.update_one({"id": user_id}, {"$set": {"chat_level": new_level}})
    return new_level


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


# ============ Sports section REMOVED per owner request (Feb 2026) ============



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
    if backend_url.startswith("http://") and "localhost" not in backend_url:
        backend_url = "https://" + backend_url[len("http://"):]
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
    # Email the user that their deposit is pending (best-effort)
    tx_doc = await db.transactions.find_one({"id": tx_id}, {"_id": 0})
    if tx_doc:
        await _notify_deposit_status_once(tx_doc, "waiting")
    return {"id": tx_id, "checkout_url": invoice["invoice_url"]}


# Statuses that mean "the buyer has paid in full — credit them".
# NOTE: partially_paid is handled separately — it flags an admin alert instead
# of silently crediting the full invoice amount.
NOWPAY_SUCCESS_STATUSES = {"finished", "confirmed", "sending"}
NOWPAY_FAIL_STATUSES = {"failed", "expired", "refunded"}


def _estimate_paid_usd(tx: dict, payload: dict) -> float:
    """Best-effort USD value of what the buyer actually sent."""
    try:
        fiat = float(payload.get("actually_paid_at_fiat") or 0)
        if fiat > 0:
            return round(fiat, 2)
    except (TypeError, ValueError):
        pass
    try:
        price = float(payload.get("price_amount") or tx.get("amount") or 0)
        pay_amount = float(payload.get("pay_amount") or 0)
        actually = float(payload.get("actually_paid") or 0)
        if pay_amount > 0 and actually > 0:
            return round(price * actually / pay_amount, 2)
    except (TypeError, ValueError):
        pass
    return 0.0


async def _notify_deposit_status_once(tx: dict, status: str, paid_usd: float = 0.0, missing_usd: float = 0.0) -> None:
    """Email the user about a deposit status — at most once per distinct status per tx."""
    claim = await db.transactions.update_one(
        {"id": tx["id"], "notified_statuses": {"$ne": status}},
        {"$addToSet": {"notified_statuses": status}},
    )
    if claim.modified_count == 0:
        return  # already notified for this status
    try:
        from notification_service import notify_deposit_status
        backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
        asyncio.create_task(notify_deposit_status(
            db, tx["user_id"], status, float(tx.get("amount") or 0), backend_url,
            paid_usd=paid_usd, missing_usd=missing_usd,
        ))
    except Exception as e:
        logger.warning(f"[nowpay] status email failed tx={tx['id']} status={status}: {e}")


async def _handle_nowpayments_underpaid(tx: dict, payload: dict) -> dict:
    """Buyer paid less than the invoice. Flag tx as underpaid, raise an admin
    alert (popup in admin dashboard) and email the user. Never auto-credits."""
    tx_id = tx["id"]
    if tx.get("status") in ("approved", "underpaid"):
        return {"ok": True, "already_handled": True, "tx_id": tx_id}
    invoice_amount = round(float(tx.get("amount") or 0), 2)
    paid_usd = _estimate_paid_usd(tx, payload)
    missing_usd = max(0.0, round(invoice_amount - paid_usd, 2))
    now = datetime.now(timezone.utc).isoformat()
    upd = await db.transactions.update_one(
        {"id": tx_id, "status": {"$nin": ["approved", "underpaid"]}},
        {"$set": {
            "status": "underpaid",
            "underpaid_at": now,
            "paid_usd": paid_usd,
            "missing_usd": missing_usd,
            "nowpayments_payload": payload,
        }},
    )
    if upd.modified_count == 0:
        return {"ok": True, "already_handled": True, "tx_id": tx_id}
    existing = await db.admin_alerts.find_one({"tx_id": tx_id, "type": "underpaid_deposit", "status": "open"})
    if not existing:
        await db.admin_alerts.insert_one({
            "id": str(uuid.uuid4()),
            "type": "underpaid_deposit",
            "status": "open",
            "tx_id": tx_id,
            "user_id": tx["user_id"],
            "username": tx.get("username"),
            "invoice_amount": invoice_amount,
            "paid_usd": paid_usd,
            "missing_usd": missing_usd,
            "created_at": now,
        })
    logger.warning(f"[nowpay] UNDERPAID tx={tx_id} user={tx.get('username')} paid=${paid_usd} of ${invoice_amount} (missing ${missing_usd}) — admin alert raised")
    await _notify_deposit_status_once(tx, "partially_paid", paid_usd=paid_usd, missing_usd=missing_usd)
    return {"ok": True, "underpaid": tx_id, "paid_usd": paid_usd, "missing_usd": missing_usd}


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
    await _maybe_referral_rewards(tx["user_id"])
    # Notify the user by email (best-effort — never blocks the credit)
    try:
        from notification_service import notify_deposit_credited
        backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
        asyncio.create_task(notify_deposit_credited(db, tx["user_id"], amount, bonus, backend_url, method="crypto"))
    except Exception as _e:
        logger.warning(f"[nowpay] notify email failed: {_e}")
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
    if not order_id.startswith("funds_"):
        return {"ok": True, "ignored": True, "status": status, "order_id": order_id}
    tx_id = order_id.replace("funds_", "", 1)
    tx = await db.transactions.find_one({"id": tx_id})
    if not tx:
        logger.warning(f"[nowpay] unknown tx_id={tx_id}")
        return {"ok": True, "unknown_tx": tx_id}
    if status in NOWPAY_SUCCESS_STATUSES:
        return await _credit_nowpayments_deposit(tx, data)
    if status == "partially_paid":
        return await _handle_nowpayments_underpaid(tx, data)
    if status == "confirming":
        await _notify_deposit_status_once(tx, "confirming")
        return {"ok": True, "status": status}
    if status in NOWPAY_FAIL_STATUSES:
        if tx.get("status") == "pending":
            await db.transactions.update_one(
                {"id": tx_id, "status": "pending"},
                {"$set": {"status": "failed", "failed_status": status, "failed_at": datetime.now(timezone.utc).isoformat(), "nowpayments_payload": data}},
            )
            await _notify_deposit_status_once(tx, status)
        return {"ok": True, "status": status}
    return {"ok": True, "ignored": True, "status": status, "order_id": order_id}


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
                # JWT succeeded but no payments attached to this invoice → user
                # hasn't paid yet (or the on-chain tx hasn't been detected).
                # Return a "waiting" payment doc so upstream code shows a friendly
                # message instead of falling through to the retired /invoice/{id}.
                return {
                    "payment_status": "waiting",
                    "pay_amount": None,
                    "actually_paid": 0,
                    "invoice_id": invoice_id,
                    "_source": "empty_payments",
                }
            else:
                logger.warning("[nowpay] /payment/ list failed %s: %s", r.status_code, r.text[:200])
        # Fallback: /invoice/{id} (x-api-key auth) — NOWPayments removed this on
        # some plans, so surface an actionable error instead of a raw 404.
        r = await c.get(
            f"{NOWPAYMENTS_API_BASE}/invoice/{invoice_id}",
            headers={"x-api-key": cfg["api_key"]},
        )
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=(
                    "NOWPayments now requires your account login for payment lookups. "
                    "Please add the NOWPayments account EMAIL and PASSWORD in "
                    "Admin → Funds → NOWPayments — Verify deposit will work after that. "
                    "Auto-crediting via the webhook still works without email/password."
                ),
            )
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
    if pstatus == "partially_paid":
        return await _handle_nowpayments_underpaid(tx, payment)
    return {"ok": True, "credited": False, "status": pstatus or "unknown", "payment": payment}


@client_router.get("/funds/pending-deposits")
async def list_pending_deposits(user: CurrentUser = Depends(current_user_dep)):
    """Show the user their unfinished NOWPayments deposits so they can click 'Verify' from the UI."""
    cur = db.transactions.find(
        {"user_id": user.id, "method": "nowpayments", "status": "pending"},
        {"_id": 0, "id": 1, "amount": 1, "created_at": 1, "nowpayments_url": 1, "nowpayments_invoice_id": 1},
    ).sort("created_at", -1).limit(10)
    return {"pending": await cur.to_list(10)}


# ============ NOWPayments Auto-Reconciler ============
# Belt-and-suspenders: even if the webhook never fires (network glitch,
# firewall, IPN secret mismatch), this background task scans pending
# NOWPayments deposits from the last 48h every 90s and credits any that
# NOWPayments now reports as paid. Users no longer need to click "Verify"
# manually — the money lands automatically.

async def _nowpayments_reconciler_loop():
    """Poll pending NOWPayments deposits and credit ones that have been paid."""
    while True:
        try:
            await asyncio.sleep(90)
            # Skip if NOWPayments isn't configured
            cfg = await db.nowpayments_config.find_one({"_id": "singleton"}, {"_id": 0, "api_key": 1}) or {}
            if not cfg.get("api_key"):
                continue
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            pending_cur = db.transactions.find(
                {
                    "method": "nowpayments",
                    "status": "pending",
                    "created_at": {"$gt": cutoff},
                    "nowpayments_invoice_id": {"$exists": True, "$ne": None},
                },
                {"_id": 0},
            ).limit(50)
            pending = await pending_cur.to_list(50)
            if not pending:
                continue
            logger.info(f"[nowpay-reconciler] checking {len(pending)} pending deposits")
            for tx in pending:
                try:
                    invoice_id = tx.get("nowpayments_invoice_id")
                    if not invoice_id:
                        continue
                    payment = await _fetch_nowpayments_invoice_status(invoice_id)
                    pstatus = (payment.get("payment_status") or "").lower()
                    if pstatus in NOWPAY_SUCCESS_STATUSES:
                        result = await _credit_nowpayments_deposit(tx, payment)
                        logger.info(f"[nowpay-reconciler] auto-credited tx={tx['id']} user={tx.get('username')} status={pstatus} result={result}")
                    elif pstatus == "partially_paid":
                        result = await _handle_nowpayments_underpaid(tx, payment)
                        logger.info(f"[nowpay-reconciler] underpaid tx={tx['id']} user={tx.get('username')} result={result}")
                    elif pstatus == "confirming":
                        await _notify_deposit_status_once(tx, "confirming")
                except Exception as e:
                    logger.warning(f"[nowpay-reconciler] tx={tx.get('id')} failed: {e}")
        except Exception as e:
            logger.error(f"[nowpay-reconciler] loop error: {e}")
            await asyncio.sleep(30)



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
        if tx:
            await _maybe_referral_rewards(tx["user_id"])
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
    reply_to: Optional[str] = ""
    use_tls: bool = True
    mailersend_api_key: Optional[str] = ""
    elastic_api_key: Optional[str] = ""


@api_router.get("/admin/email-config")
async def admin_get_email_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.email_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}
    pw = cfg.get("smtp_password", "")
    ms_key = cfg.get("mailersend_api_key", "")
    ee_key = cfg.get("elastic_api_key", "")
    provider = "elastic_email" if ee_key else ("mailersend" if ms_key else ("smtp" if cfg.get("smtp_host") else ""))
    return {
        "configured": bool(ee_key or ms_key or (cfg.get("smtp_host") and cfg.get("smtp_user"))),
        "provider": provider,
        "smtp_host": cfg.get("smtp_host", ""),
        "smtp_port": cfg.get("smtp_port", 587),
        "smtp_user": cfg.get("smtp_user", ""),
        "password_set": bool(pw),
        "from_email": cfg.get("from_email", ""),
        "from_name": cfg.get("from_name", "Better Social"),
        "reply_to": cfg.get("reply_to", ""),
        "use_tls": cfg.get("use_tls", True),
        "mailersend_set": bool(ms_key),
        "mailersend_api_key_masked": ("*" * 8 + ms_key[-4:]) if ms_key else "",
        "elastic_set": bool(ee_key),
        "elastic_api_key_masked": ("*" * 8 + ee_key[-4:]) if ee_key else "",
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
        "reply_to": (payload.reply_to or "").strip(),
        "use_tls": bool(payload.use_tls),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Only update password if a new non-empty one is provided (preserve existing on edits)
    if payload.smtp_password:
        upd["smtp_password"] = payload.smtp_password
    if payload.mailersend_api_key:
        upd["mailersend_api_key"] = payload.mailersend_api_key.strip()
    if payload.elastic_api_key:
        upd["elastic_api_key"] = payload.elastic_api_key.strip()
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
    if res.get("type") == "deposit" and float(res.get("amount") or 0) > 0:
        await _maybe_referral_rewards(res["user_id"])
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
    asyncio.create_task(_ai_ticket_autoreply(ticket_id))
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
    asyncio.create_task(_ai_ticket_autoreply(ticket_id))
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
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
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
    # Fire-and-forget email notification to the ticket owner
    try:
        from notification_service import notify_ticket_reply
        backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
        if t.get("user_id"):
            asyncio.create_task(notify_ticket_reply(
                db, t["user_id"], ticket_id,
                t.get("subject") or "Support",
                author_name,
                body.message.strip(),
                backend_url,
            ))
    except Exception as _e:
        logger.warning(f"[notify] ticket-reply email failed: {_e}")
    return {"ok": True, "author_name": author_name}


@api_router.post("/admin/tickets/{ticket_id}/close")
async def admin_close_ticket(ticket_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "tickets")
    res = await db.tickets.update_one({"id": ticket_id}, {"$set": {"status": "closed"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}


# ============ AI SUPPORT ASSISTANT (ticket auto-reply + refunds) ============
AI_ASSISTANT_NAME = "BS Assistant (AI)"


async def _already_refunded(user_id: str, target_id: str) -> float:
    pipeline = [
        {"$match": {"user_id": user_id, "target_id": target_id,
                    "type": {"$in": ["ai_refund", "admin_refund", "live_sub_refund"]}, "status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(1)
    return round(float(rows[0]["total"]), 2) if rows else 0.0


async def _ai_refundable_items(user_id: str) -> list:
    """Cancelled/refunded live subs + cancelled orders with how much is still refundable."""
    items = []
    subs = await db.live_subscriptions.find(
        {"user_id": user_id, "status": {"$in": ["cancelled", "expired", "refunded"]}},
        {"_id": 0, "id": 1, "service_name": 1, "tiktok_username": 1, "status": 1, "total_spent": 1, "created_at": 1},
    ).sort("created_at", -1).limit(8).to_list(8)
    for s in subs:
        spent = round(float(s.get("total_spent") or 0), 2)
        done = await _already_refunded(user_id, s["id"])
        items.append({
            "target_id": s["id"], "kind": "live_subscription",
            "label": f"Auto-Live @{s.get('tiktok_username')} — {s.get('service_name') or ''}".strip(),
            "status": s.get("status"), "total_spent": spent,
            "already_refunded": done, "refundable": max(0.0, round(spent - done, 2)),
        })
    orders = await db.orders.find(
        {"user_id": user_id, "status": {"$in": ["canceled", "cancelled", "refunded", "partial"]}},
        {"_id": 0, "id": 1, "service_name": 1, "status": 1, "price": 1, "charge": 1, "amount": 1, "created_at": 1},
    ).sort("created_at", -1).limit(8).to_list(8)
    for o in orders:
        cost = round(float(o.get("charge") or o.get("price") or o.get("amount") or 0), 2)
        done = await _already_refunded(user_id, o["id"])
        items.append({
            "target_id": o["id"], "kind": "order",
            "label": f"Order {o.get('service_name') or o['id'][:8]}",
            "status": o.get("status"), "total_spent": cost,
            "already_refunded": done, "refundable": max(0.0, round(cost - done, 2)),
        })
    return items


async def _ai_apply_refund(user_id: str, username: str, target_id: str, amount: float,
                           reason: str, ticket_id: str, actor: str = "ai") -> Optional[float]:
    """Validate + credit a refund. Returns credited amount or None if rejected."""
    items = await _ai_refundable_items(user_id)
    match = next((i for i in items if i["target_id"] == target_id), None)
    if not match:
        return None
    credit = round(min(float(amount), match["refundable"]), 2)
    if credit <= 0:
        return None
    now = datetime.now(timezone.utc).isoformat()
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id, "username": username,
        "amount": credit, "method": "balance", "status": "approved",
        "type": "ai_refund" if actor == "ai" else "admin_refund",
        "target_id": target_id, "ticket_id": ticket_id,
        "note": f"Refund for {match['label']} — {reason}"[:300],
        "created_at": now, "approved_at": now,
    })
    await db.ai_actions.insert_one({
        "id": str(uuid.uuid4()), "kind": "refund", "actor": actor,
        "user_id": user_id, "username": username,
        "target_id": target_id, "target_label": match["label"],
        "amount": credit, "reason": reason[:300], "ticket_id": ticket_id,
        "created_at": now,
    })
    logger.info("[ai-support] %s refunded $%.2f to %s (target=%s)", actor, credit, username, target_id)
    return credit


async def _ai_ticket_autoreply(ticket_id: str):
    """AI support agent: reads the ticket, replies, and can refund cancelled
    orders/subscriptions to the user's balance (capped at what's refundable)."""
    try:
        t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
        if not t or t.get("status") == "closed" or t.get("ai_disabled"):
            return
        cfg = await db.ai_support_config.find_one({}, {"_id": 0}) or {}
        if cfg.get("enabled") is False:
            return
        msgs = await db.ticket_messages.find({"ticket_id": ticket_id}, {"_id": 0}).sort("created_at", 1).to_list(60)
        if msgs and msgs[-1].get("author_role") != "user":
            return  # only reply to the user's messages
        user_id = t.get("user_id")
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "username": 1, "email": 1}) or {}
        balance = await _get_user_balance(user_id)
        refundables = await _ai_refundable_items(user_id)

        from emergentintegrations.llm.chat import LlmChat, UserMessage
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            return
        system_msg = (
            "You are the AI support agent for Better Social, an SMM panel (TikTok live viewers, followers, etc.). "
            "Be short, friendly and helpful. You handle support tickets.\n"
            "You CAN issue refunds to the user's balance for CANCELLED orders/subscriptions — but ONLY up to the "
            "'refundable' amount listed in the CONTEXT. Never invent refunds for items not listed.\n"
            "ALWAYS answer with pure JSON (no markdown, no code fences) in this exact shape:\n"
            '{"reply": "<your message to the user>", "refund": null}\n'
            'or, when a refund is justified: {"reply": "...", "refund": {"target_id": "<id from context>", '
            '"amount": <number>, "reason": "<short reason>"}}\n'
            "Only refund when the user asks about a cancelled order/money back AND a refundable item exists. "
            "If nothing is refundable, explain why politely."
        )
        context = {
            "username": u.get("username"),
            "current_balance": balance,
            "ticket_subject": t.get("subject"),
            "refundable_items": refundables,
        }
        convo = "\n".join(
            f"{'USER' if m.get('author_role') == 'user' else 'STAFF'}: {m.get('message', '')[:800]}"
            for m in msgs[-12:]
        )
        prompt = f"CONTEXT:\n{jsonlib.dumps(context)}\n\nTICKET CONVERSATION:\n{convo}\n\nRespond now as JSON."
        chat = LlmChat(api_key=api_key, session_id=f"ticket-{ticket_id}", system_message=system_msg).with_model(
            "anthropic", "claude-sonnet-4-5-20250929"
        )
        raw = await chat.send_message(UserMessage(text=prompt))
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):raw.rfind("}") + 1]
        try:
            parsed = jsonlib.loads(raw)
        except Exception:
            parsed = {"reply": raw[:2000], "refund": None}
        reply_text = (parsed.get("reply") or "").strip()[:4000]
        refund = parsed.get("refund")
        credited = None
        if isinstance(refund, dict) and refund.get("target_id") and refund.get("amount"):
            credited = await _ai_apply_refund(
                user_id, u.get("username") or t.get("username") or "",
                str(refund["target_id"]), float(refund["amount"]),
                str(refund.get("reason") or "AI support refund"), ticket_id, actor="ai",
            )
            if credited:
                reply_text += f"\n\n✅ I've refunded ${credited:.2f} to your balance."
            elif refund:
                reply_text += "\n\n(Note: the refund couldn't be applied automatically — a staff member will review it.)"
        if not reply_text:
            return
        now = datetime.now(timezone.utc).isoformat()
        await db.ticket_messages.insert_one({
            "id": str(uuid.uuid4()), "ticket_id": ticket_id,
            "author_role": "staff", "author_name": AI_ASSISTANT_NAME,
            "message": reply_text, "created_at": now, "is_ai": True,
        })
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {"status": "answered", "updated_at": now, "last_reply_by": "staff",
                      "last_reply_author": AI_ASSISTANT_NAME, "client_unread": True}},
        )
        await db.ai_actions.insert_one({
            "id": str(uuid.uuid4()), "kind": "ticket_reply", "actor": "ai",
            "user_id": user_id, "username": u.get("username"),
            "ticket_id": ticket_id, "details": reply_text[:300],
            "refunded": credited or 0, "created_at": now,
        })
        try:
            from notification_service import notify_ticket_reply
            backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
            asyncio.create_task(notify_ticket_reply(db, user_id, ticket_id, t.get("subject") or "Support",
                                                    AI_ASSISTANT_NAME, reply_text, backend_url))
        except Exception:
            pass
    except Exception as e:
        logger.warning("[ai-support] autoreply failed for ticket %s: %s", ticket_id, e)


@api_router.get("/admin/ai-actions")
async def admin_ai_actions(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    rows = await db.ai_actions.find({}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"actions": rows}


# ============ ADMIN — MANAGE ALL LIVE SUBSCRIPTIONS ============

@api_router.get("/admin/live-subs")
async def admin_list_live_subs(status: Optional[str] = None, q: str = "", x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    query: dict = {}
    if status:
        query["status"] = status
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"username": rx}, {"tiktok_username": rx}, {"service_name": rx}]
    subs = await db.live_subscriptions.find(query, {"_id": 0}).sort("created_at", -1).limit(150).to_list(150)
    for s in subs:
        s["already_refunded"] = await _already_refunded(s.get("user_id") or "", s["id"])
    return {"subs": subs}


class AdminLiveSubCancelReq(BaseModel):
    refund_amount: float = 0.0
    reason: str = Field(default="Cancelled by admin", max_length=300)
    open_ticket: bool = True


@api_router.post("/admin/live-subs/{sid}/cancel")
async def admin_cancel_live_sub(sid: str, body: AdminLiveSubCancelReq, x_admin_token: Optional[str] = Header(None)):
    """Cancel any user's auto-live subscription, optionally refund part of what
    they spent, and auto-open a support ticket (the AI assistant handles follow-ups)."""
    check_admin(x_admin_token)
    sub = await db.live_subscriptions.find_one({"id": sid}, {"_id": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    now = datetime.now(timezone.utc).isoformat()
    if sub.get("status") not in ("cancelled", "refunded"):
        await db.live_subscriptions.update_one(
            {"id": sid},
            {"$set": {"status": "cancelled", "ended_at": now, "cancelled_by": "admin", "cancel_reason": body.reason}},
        )
    credited = 0.0
    if body.refund_amount and body.refund_amount > 0:
        # allow refund even right after cancel — recompute refundable now
        credited = await _ai_apply_refund(
            sub["user_id"], sub.get("username") or "", sid,
            float(body.refund_amount), body.reason, ticket_id="", actor="admin",
        ) or 0.0
    ticket_id = None
    if body.open_ticket and sub.get("user_id"):
        ticket_id = str(uuid.uuid4())
        subject = f"Auto-Live @{sub.get('tiktok_username')} cancelled by admin"
        await db.tickets.insert_one({
            "id": ticket_id, "user_id": sub["user_id"], "username": sub.get("username"),
            "subject": subject[:120], "status": "answered", "created_at": now, "updated_at": now,
            "last_reply_by": "staff", "last_reply_author": AI_ASSISTANT_NAME, "client_unread": True,
        })
        msg = (
            f"Hi {sub.get('username')}, your Auto-Live subscription for @{sub.get('tiktok_username')} "
            f"({sub.get('service_name') or ''}) was cancelled by our team.\n"
            f"Reason: {body.reason}\n"
            + (f"💰 ${credited:.2f} has been refunded to your balance.\n" if credited else "")
            + "Reply here if you have any questions — I can check what else is refundable for you."
        )
        await db.ticket_messages.insert_one({
            "id": str(uuid.uuid4()), "ticket_id": ticket_id, "author_role": "staff",
            "author_name": AI_ASSISTANT_NAME, "message": msg, "created_at": now, "is_ai": True,
        })
        await db.ai_actions.insert_one({
            "id": str(uuid.uuid4()), "kind": "admin_cancel_sub", "actor": "admin",
            "user_id": sub["user_id"], "username": sub.get("username"),
            "target_id": sid, "target_label": f"@{sub.get('tiktok_username')}",
            "amount": credited, "reason": body.reason, "ticket_id": ticket_id, "created_at": now,
        })
        try:
            from notification_service import notify_ticket_reply
            backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
            asyncio.create_task(notify_ticket_reply(db, sub["user_id"], ticket_id, subject, AI_ASSISTANT_NAME, msg, backend_url))
        except Exception:
            pass
    return {"ok": True, "cancelled": sid, "refunded": credited, "ticket_id": ticket_id}


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


# ===== In-process Discord moderation bot (managed from admin panel) =====
from discord_bot import bot_manager  # noqa: E402


# Default channel where "new purchase" notifications go. Can be overridden via
# discord_config.purchase_channel_id (admin panel) or DISCORD_PURCHASE_CHANNEL_ID env.
DISCORD_PURCHASE_CHANNEL_DEFAULT = os.environ.get("DISCORD_PURCHASE_CHANNEL_ID", "1477630409742221499")


# ============ Discord OAuth2 — "Login with Discord" + account linking ============
DISCORD_OAUTH_BASE = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"


async def _discord_oauth_config() -> dict:
    """Read Client ID / Client Secret / Redirect URI from discord_config.
    Owner sets them via Admin → Discord panel."""
    cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
    return {
        "client_id": cfg.get("oauth_client_id") or os.environ.get("DISCORD_CLIENT_ID", ""),
        "client_secret": cfg.get("oauth_client_secret") or os.environ.get("DISCORD_CLIENT_SECRET", ""),
        "redirect_uri": cfg.get("oauth_redirect_uri") or os.environ.get("DISCORD_REDIRECT_URI", ""),
    }


@api_router.get("/auth/discord/login-url")
async def discord_login_url(state: Optional[str] = None):
    """Return the Discord authorize URL the frontend should redirect to."""
    cfg = await _discord_oauth_config()
    if not cfg["client_id"] or not cfg["redirect_uri"]:
        raise HTTPException(status_code=503, detail="Discord OAuth not configured yet — ask the owner.")
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "identify email",
        "prompt": "consent",
    }
    if state:
        params["state"] = state
    from urllib.parse import urlencode
    return {"url": f"{DISCORD_OAUTH_BASE}?{urlencode(params)}"}


async def _discord_exchange_and_fetch(code: str) -> dict:
    """Exchange OAuth code for token, then fetch the Discord user profile."""
    cfg = await _discord_oauth_config()
    if not cfg["client_id"] or not cfg["client_secret"] or not cfg["redirect_uri"]:
        raise HTTPException(status_code=503, detail="Discord OAuth not configured")
    async with httpx.AsyncClient(timeout=15) as http:
        tok = await http.post(DISCORD_TOKEN_URL, data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg["redirect_uri"],
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if tok.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Discord token exchange failed: {tok.text[:200]}")
        access = tok.json().get("access_token")
        u = await http.get(DISCORD_USER_URL, headers={"Authorization": f"Bearer {access}"})
        if u.status_code != 200:
            raise HTTPException(status_code=502, detail="Discord /users/@me failed")
        return u.json()


class DiscordCallbackBody(BaseModel):
    code: str


@api_router.post("/auth/discord/callback")
async def discord_callback(body: DiscordCallbackBody, request: Request = None):
    """Login flow: exchange code → find OR create local user linked to that Discord id → return our own JWT."""
    from auth_and_chat import create_token, _user_public, hash_password
    d = await _discord_exchange_and_fetch(body.code)
    discord_id = str(d.get("id") or "")
    if not discord_id:
        raise HTTPException(status_code=400, detail="No Discord user id returned")
    email = (d.get("email") or "").lower()
    handle = d.get("username") or f"discord_{discord_id[-6:]}"
    # Prefer an existing local link, then match by email, else create.
    doc = await db.users.find_one({"discord_id": discord_id})
    if not doc and email:
        doc = await db.users.find_one({"email": email})
    if not doc:
        # Create fresh user with a random password (they'll only use Discord to log in).
        import secrets as _s
        base = "".join(c for c in handle if c.isalnum())[:24] or f"user{_s.token_hex(3)}"
        username = base
        n = 1
        while await db.users.find_one({"username_lower": username.lower()}):
            n += 1; username = f"{base}{n}"
        doc = {
            "id": str(uuid.uuid4()),
            "username": username,
            "username_lower": username.lower(),
            "email": email,
            "password_hash": hash_password(_s.token_urlsafe(20)),
            "role": "user",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "discord_id": discord_id,
            "discord_username": d.get("username"),
        }
        await db.users.insert_one(doc)
    else:
        await db.users.update_one({"id": doc["id"]}, {"$set": {
            "discord_id": discord_id,
            "discord_username": d.get("username"),
        }})
    token = create_token(doc["id"], doc["username"], doc.get("role", "user"))
    return {"token": token, "user": _user_public(doc)}


@api_router.post("/client/discord/link")
async def client_discord_link(body: DiscordCallbackBody, user: CurrentUser = Depends(current_user_dep)):
    """Signed-in user linking their existing account to a Discord id."""
    d = await _discord_exchange_and_fetch(body.code)
    discord_id = str(d.get("id") or "")
    if not discord_id:
        raise HTTPException(status_code=400, detail="No Discord user id returned")
    # Refuse to link if this Discord id is already linked to a different local account.
    other = await db.users.find_one({"discord_id": discord_id, "id": {"$ne": user.id}})
    if other:
        raise HTTPException(status_code=409, detail=f"This Discord account is already linked to @{other.get('username')}")
    await db.users.update_one({"id": user.id}, {"$set": {
        "discord_id": discord_id,
        "discord_username": d.get("username"),
    }})
    return {"ok": True, "discord_username": d.get("username")}


@api_router.post("/client/discord/unlink")
async def client_discord_unlink(user: CurrentUser = Depends(current_user_dep)):
    await db.users.update_one({"id": user.id}, {"$unset": {"discord_id": "", "discord_username": ""}})
    return {"ok": True}


# ============ Client Discord bot management (invite / welcomer / features) ============
@api_router.get("/discord/invite-url")
async def discord_invite_url():
    cfg = await db.discord_config.find_one({}, {"_id": 0, "oauth_client_id": 1, "application_id": 1}) or {}
    app_id = (cfg.get("application_id") or cfg.get("oauth_client_id") or "").strip()
    if not app_id:
        raise HTTPException(status_code=503, detail="Bot invite not configured yet — the site admin must save the Discord OAuth Client ID first.")
    perms = 1374926835718  # manage nicknames/channels/messages, kick, ban, timeout — for moderation features
    return {"url": f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions={perms}"}


DISCORD_GUILD_FEATURES = {"welcomer", "anti_raid", "moderation", "blacklist", "anti_nuke"}


class ClientGuildConfig(BaseModel):
    guild_id: str = Field(..., min_length=5, max_length=32)
    welcome_channel_id: Optional[str] = None
    welcome_text: Optional[str] = Field(default=None, max_length=1000)
    welcomer_enabled: bool = True
    bot_nickname: Optional[str] = Field(default=None, max_length=32)
    features: Optional[dict] = None


@client_router.get("/discord/guilds")
async def client_discord_guilds(user: CurrentUser = Depends(current_user_dep)):
    rows = await db.client_discord_guilds.find({"user_id": user.id}, {"_id": 0}).to_list(20)
    return {"guilds": rows}


@client_router.post("/discord/guilds")
async def client_discord_guild_save(body: ClientGuildConfig, user: CurrentUser = Depends(current_user_dep)):
    gid = body.guild_id.strip()
    if not gid.isdigit():
        raise HTTPException(status_code=400, detail="Server (Guild) ID must be numeric — right-click your server icon → Copy Server ID")
    existing = await db.client_discord_guilds.find_one({"guild_id": gid}, {"_id": 0, "user_id": 1})
    if existing and existing["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="This server is already managed by another Better Social account.")
    feats = {k: bool(v) for k, v in (body.features or {}).items() if k in DISCORD_GUILD_FEATURES}
    doc = {
        "guild_id": gid, "user_id": user.id, "username": user.username,
        "welcome_channel_id": (body.welcome_channel_id or "").strip() or None,
        "welcome_text": (body.welcome_text or "").strip() or None,
        "welcomer_enabled": bool(body.welcomer_enabled),
        "bot_nickname": (body.bot_nickname or "").strip() or None,
        "features": feats,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.client_discord_guilds.update_one({"guild_id": gid}, {"$set": doc}, upsert=True)
    return {"ok": True, "guild": doc}


@client_router.delete("/discord/guilds/{gid}")
async def client_discord_guild_delete(gid: str, user: CurrentUser = Depends(current_user_dep)):
    r = await db.client_discord_guilds.delete_one({"guild_id": gid, "user_id": user.id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


class DiscordOAuthCfg(BaseModel):
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_redirect_uri: Optional[str] = None


@api_router.get("/admin/discord/oauth-config")
async def admin_get_discord_oauth(x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
    return {
        "client_id_set": bool(cfg.get("oauth_client_id")),
        "client_secret_set": bool(cfg.get("oauth_client_secret")),
        "redirect_uri": cfg.get("oauth_redirect_uri") or "",
    }


@api_router.post("/admin/discord/oauth-config")
async def admin_set_discord_oauth(payload: DiscordOAuthCfg, x_admin_token: Optional[str] = Header(None)):
    check_owner(x_admin_token)
    doc = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not doc:
        raise HTTPException(status_code=400, detail="Nothing to save")
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.discord_config.update_one({}, {"$set": doc}, upsert=True)
    return {"ok": True}


class DiscordPurchaseCfg(BaseModel):
    purchase_channel_id: Optional[str] = None
    purchase_guild_id: Optional[str] = None
    purchase_notify_enabled: Optional[bool] = None


@api_router.get("/admin/discord-purchase-config")
async def get_discord_purchase_config(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
    return {
        "purchase_channel_id": cfg.get("purchase_channel_id") or DISCORD_PURCHASE_CHANNEL_DEFAULT,
        "purchase_guild_id": cfg.get("purchase_guild_id") or "",
        "purchase_notify_enabled": cfg.get("purchase_notify_enabled", True),
        "default_channel_id": DISCORD_PURCHASE_CHANNEL_DEFAULT,
    }


@api_router.post("/admin/discord-purchase-config")
async def set_discord_purchase_config(payload: DiscordPurchaseCfg, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    doc = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not doc:
        raise HTTPException(status_code=400, detail="Nothing to update")
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.discord_config.update_one({}, {"$set": doc}, upsert=True)
    return {"ok": True, **doc}


@api_router.post("/admin/discord-purchase-config/test")
async def test_discord_purchase_notification(x_admin_token: Optional[str] = Header(None)):
    """Fire a fake purchase notification so the owner can confirm the channel wiring."""
    check_admin(x_admin_token)
    fake = {"username": "testuser", "service_name": "Test service", "quantity": 100, "charge": 9.99}
    await _notify_discord_purchase(fake)
    return {"ok": True, "sent": True}


async def _notify_discord_purchase(order_doc: dict) -> None:
    """Fire-and-forget: post a masked purchase notification to the configured
    Discord channel. Never raises — a Discord outage must NEVER break a real
    purchase. Every attempt is logged to `discord_notify_log` so the owner can
    debug even when the bot is currently stopped."""
    log_entry = {
        "id": str(uuid.uuid4()),
        "kind": "purchase",
        "username": order_doc.get("username"),
        "service_name": order_doc.get("service_name"),
        "quantity": order_doc.get("quantity"),
        "charge": order_doc.get("charge"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
        if cfg.get("purchase_notify_enabled") is False:
            log_entry.update({"status": "skipped", "reason": "purchase_notify_enabled=False"})
            await db.discord_notify_log.insert_one(log_entry); return
        channel_id = str(cfg.get("purchase_channel_id") or DISCORD_PURCHASE_CHANNEL_DEFAULT).strip()
        guild_id = str(cfg.get("purchase_guild_id") or "").strip() or None
        if not channel_id:
            log_entry.update({"status": "skipped", "reason": "no channel configured"})
            await db.discord_notify_log.insert_one(log_entry); return
        if bot_manager.status != "running":
            log_entry.update({"status": "skipped", "reason": f"bot {bot_manager.status} — start it in Admin → Discord Bot", "channel_id": channel_id})
            await db.discord_notify_log.insert_one(log_entry); return
        masked = bot_manager.mask_username(order_doc.get("username") or "user")
        service = order_doc.get("service_name") or f"#{order_doc.get('service_id', '?')}"
        qty = order_doc.get("quantity") or ""
        charge = order_doc.get("charge") or 0
        try:
            charge_str = f"${float(charge):.2f}"
        except Exception:
            charge_str = ""
        line = f"🛒 **New client bought!** `{masked}` just ordered **{service}**"
        if qty:
            line += f" × **{qty}**"
        if charge_str:
            line += f" — {charge_str}"

        async def _send_and_log():
            r = await bot_manager.send_channel_message(channel_id, line, guild_id=guild_id)
            log_entry.update({
                "status": "sent" if r.get("ok") else "failed",
                "reason": r.get("reason") or "",
                "channel_id": channel_id,
                "guild_id": guild_id,
                "message": line,
            })
            try:
                await db.discord_notify_log.insert_one(log_entry)
            except Exception:
                pass
        asyncio.create_task(_send_and_log())
    except Exception as e:
        log_entry.update({"status": "failed", "reason": f"{type(e).__name__}: {e}"})
        try:
            await db.discord_notify_log.insert_one(log_entry)
        except Exception:
            pass
        logger.warning("[discord] purchase notify failed: %s", e)


@api_router.get("/admin/discord-notify-log")
async def get_discord_notify_log(x_admin_token: Optional[str] = Header(None), limit: int = 30):
    check_admin(x_admin_token)
    rows = await db.discord_notify_log.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 200))
    return {"log": rows}


async def _discord_bot_start_from_config() -> dict:
    cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="No bot token saved — enter it in the Discord tab first")
    words = [w.strip() for w in (cfg.get("banned_words") or "").split(",") if w.strip()]
    welcome = {
        "enabled": cfg.get("welcome_enabled"),
        "message": cfg.get("welcome_message"),
        "channel": cfg.get("welcome_channel"),
    }
    return await bot_manager.start(db, token, activity_text=cfg.get("activity_text") or "", banned_words=words, welcome=welcome)


@api_router.get("/admin/discord/status")
async def discord_bot_status(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    cfg = await db.discord_config.find_one({}, {"_id": 0}) or {}
    info = bot_manager.info()
    info["token_saved"] = bool(cfg.get("bot_token"))
    info["banned_words"] = cfg.get("banned_words") or ""
    info["saved_activity_text"] = cfg.get("activity_text") or ""
    info["saved_welcome"] = {
        "enabled": bool(cfg.get("welcome_enabled")),
        "message": cfg.get("welcome_message") or "Welcome {user} to {server}! 🎉",
        "channel": cfg.get("welcome_channel") or "",
    }
    return info


@api_router.post("/admin/discord/start")
async def discord_bot_start(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    res = await _discord_bot_start_from_config()
    await db.discord_config.update_one({}, {"$set": {"auto_start": True}}, upsert=True)
    return res


@api_router.post("/admin/discord/stop")
async def discord_bot_stop(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    await db.discord_config.update_one({}, {"$set": {"auto_start": False}}, upsert=True)
    return await bot_manager.stop()


class DiscordActivityReq(BaseModel):
    text: str = Field(default="", max_length=128)


@api_router.post("/admin/discord/activity")
async def discord_bot_activity(body: DiscordActivityReq, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    await db.discord_config.update_one({}, {"$set": {"activity_text": body.text}}, upsert=True)
    try:
        return await bot_manager.set_activity(body.text)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


class DiscordAvatarReq(BaseModel):
    image_base64: str


@api_router.post("/admin/discord/avatar")
async def discord_bot_avatar(body: DiscordAvatarReq, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    raw = body.image_base64
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        img = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")
    if len(img) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 8MB)")
    try:
        return await bot_manager.set_avatar(img)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Discord rejected avatar: {str(e)[:200]}")


class DiscordModWordsReq(BaseModel):
    banned_words: str = Field(default="", max_length=2000)


@api_router.post("/admin/discord/mod-words")
async def discord_bot_mod_words(body: DiscordModWordsReq, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    await db.discord_config.update_one({}, {"$set": {"banned_words": body.banned_words}}, upsert=True)
    bot_manager.banned_words = [w.strip().lower() for w in body.banned_words.split(",") if w.strip()]
    return {"ok": True}


@api_router.get("/admin/discord/dms")
async def discord_bot_dm_conversations(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$discord_user_id",
            "discord_username": {"$first": "$discord_username"},
            "last_text": {"$first": "$text"},
            "last_direction": {"$first": "$direction"},
            "last_at": {"$first": "$created_at"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": 100},
    ]
    convos = await db.discord_dms.aggregate(pipeline).to_list(100)
    return {"conversations": [
        {"discord_user_id": c["_id"], "discord_username": c.get("discord_username"),
         "last_text": c.get("last_text"), "last_direction": c.get("last_direction"),
         "last_at": c.get("last_at"), "count": c.get("count", 0)}
        for c in convos
    ]}


@api_router.get("/admin/discord/dms/{duid}")
async def discord_bot_dm_thread(duid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    cur = db.discord_dms.find({"discord_user_id": duid}, {"_id": 0}).sort("created_at", -1).limit(200)
    msgs = await cur.to_list(200)
    msgs.reverse()
    return {"messages": msgs}


class DiscordDmSendReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@api_router.post("/admin/discord/dms/{duid}/send")
async def discord_bot_dm_send(duid: str, body: DiscordDmSendReq, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    try:
        return await bot_manager.send_dm(duid, body.text)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DM failed: {str(e)[:200]}")


class DiscordWelcomeReq(BaseModel):
    enabled: bool = False
    message: str = Field(default="Welcome {user} to {server}! 🎉", max_length=1000)
    channel: str = Field(default="", max_length=100)


@api_router.post("/admin/discord/welcome")
async def discord_bot_welcome_config(body: DiscordWelcomeReq, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    await db.discord_config.update_one({}, {"$set": {
        "welcome_enabled": body.enabled,
        "welcome_message": body.message,
        "welcome_channel": body.channel.strip(),
    }}, upsert=True)
    bot_manager.welcome_enabled = body.enabled
    bot_manager.welcome_message = body.message
    bot_manager.welcome_channel = body.channel.strip()
    return {"ok": True}


@api_router.get("/admin/discord/servers")
async def discord_bot_servers(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    try:
        return {"servers": bot_manager.list_servers()}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@api_router.post("/admin/discord/servers/{gid}/leave")
async def discord_bot_leave_server(gid: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token, "discord")
    try:
        return await bot_manager.leave_server(gid)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Leave failed: {str(e)[:200]}")


class DiscordMassDmReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@api_router.post("/admin/discord/mass-dm")
async def discord_bot_mass_dm(body: DiscordMassDmReq, x_admin_token: Optional[str] = Header(None)):
    """Send a custom DM to every unique (non-bot) member across all servers the
    bot is in. Runs in the background with rate limiting; progress shows in status."""
    check_admin(x_admin_token, "discord")
    try:
        return bot_manager.start_mass_dm(body.text)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


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

# ============================================================================
# ============ SMM-PANEL STYLE PUBLIC API (JustAnotherPanel compatible) ======
# ============================================================================
# Users can generate a personal API key from the dashboard and drive orders
# from their own site / bot / script. Same balance / validation rules as the
# dashboard. Two endpoints:
#
#   POST /api/v2   (form-urlencoded OR JSON, JAP style)
#   GET  /api/v2   (query params — for quick tests)
#
# Actions supported (mirrors JAP): balance, services, add, status, multi_status,
# refill, cancel. Every request needs `key` + `action`.
# ============================================================================
from fastapi import Form

async def _api_v2_user_from_key(api_key: str) -> dict:
    """Look up the user document from an API key. Raises 401 on unknown."""
    if not api_key or len(api_key) < 16:
        raise HTTPException(status_code=401, detail="Invalid API key")
    u = await db.users.find_one({"api_key": api_key}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if u.get("banned"):
        raise HTTPException(status_code=403, detail="Account suspended")
    return u


def _gen_api_key() -> str:
    return secrets.token_hex(24)  # 48-char hex


@client_router.get("/api-key")
async def client_api_key_get(user: CurrentUser = Depends(current_user_dep)):
    """Return the caller's API key. Lazily generates one on first request."""
    u = await db.users.find_one({"id": user.id}, {"_id": 0, "api_key": 1})
    key = (u or {}).get("api_key")
    if not key:
        key = _gen_api_key()
        await db.users.update_one({"id": user.id}, {"$set": {"api_key": key, "api_key_created_at": datetime.now(timezone.utc).isoformat()}})
    return {"api_key": key, "endpoint": "/api/v2"}


@client_router.post("/api-key/regenerate")
async def client_api_key_regenerate(user: CurrentUser = Depends(current_user_dep)):
    """Rotate the API key. Any script using the old key stops working immediately."""
    key = _gen_api_key()
    await db.users.update_one(
        {"id": user.id},
        {"$set": {"api_key": key, "api_key_created_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"api_key": key, "endpoint": "/api/v2"}


async def _api_v2_dispatch(params: dict) -> dict:
    """Core dispatcher. `params` already parsed from either form or JSON body."""
    key = (params.get("key") or "").strip()
    action = (params.get("action") or "").strip().lower()
    if not action:
        raise HTTPException(status_code=400, detail={"error": "action is required"})
    u = await _api_v2_user_from_key(key)

    # ---- balance --------------------------------------------------------
    if action == "balance":
        bal = await _get_user_balance(u["id"])
        return {"balance": f"{bal:.4f}", "currency": "USD"}

    # ---- services -------------------------------------------------------
    if action == "services":
        cur = db.curated_services.find({"enabled": True}, {"_id": 0})
        out = []
        async for s in cur:
            rate = float(s.get("custom_rate", 0) or 0)
            out.append({
                "service": int(s.get("service_id")),
                "name": s.get("custom_name") or s.get("name") or "",
                "type": "Default",
                "category": s.get("category") or "",
                "rate": f"{rate:.4f}",
                "min": str(int(s.get("min", 1) or 1)),
                "max": str(int(s.get("max", 100000) or 100000)),
                "refill": bool(s.get("refill", False)),
                "cancel": bool(s.get("cancel", False)),
                "dripfeed": bool(s.get("dripfeed", False)),
                "needs_custom_text": bool(s.get("needs_custom_text", False)),
            })
        return out

    # ---- add ------------------------------------------------------------
    if action == "add":
        try:
            service_id = int(params.get("service"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail={"error": "service is required (integer)"})
        link = (params.get("link") or "").strip()
        if not link or len(link) < 4:
            raise HTTPException(status_code=400, detail={"error": "link is required"})
        # comments-only services: quantity derived from comment lines
        svc = await db.curated_services.find_one({"service_id": service_id, "enabled": True}, {"_id": 0})
        if not svc:
            raise HTTPException(status_code=404, detail={"error": "service not available"})
        needs_custom = bool(svc.get("needs_custom_text"))
        comments = (params.get("comments") or "").strip() or None
        try:
            quantity = int(params.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        if needs_custom:
            if not comments:
                raise HTTPException(status_code=400, detail={"error": "comments required — one per line"})
            lines = [ln.strip() for ln in comments.split("\n") if ln.strip()]
            if not lines:
                raise HTTPException(status_code=400, detail={"error": "at least one non-empty comment line required"})
            comments = "\n".join(lines)
            quantity = len(lines)  # line count IS the quantity
        if quantity <= 0:
            raise HTTPException(status_code=400, detail={"error": "quantity must be > 0"})

        is_manual = bool(svc.get("manual"))
        if is_manual:
            charge = round(float(svc.get("price_flat") or 0), 2)
            if charge <= 0:
                raise HTTPException(status_code=400, detail={"error": "service price not set"})
        else:
            rate = float(svc.get("custom_rate", 0) or 0)
            if rate <= 0:
                raise HTTPException(status_code=400, detail={"error": "service price not set"})
            smin, smax = int(svc.get("min", 1) or 1), int(svc.get("max", 100000) or 100000)
            if quantity < smin or quantity > smax:
                raise HTTPException(status_code=400, detail={"error": f"quantity must be between {smin} and {smax}"})
            charge = round((rate * quantity) / 1000.0, 4)

        bal = await _get_user_balance(u["id"])
        if bal < charge:
            raise HTTPException(status_code=402, detail={"error": f"not enough balance — need ${charge:.4f}, have ${bal:.4f}"})

        now_iso = datetime.now(timezone.utc).isoformat()
        order_uuid = str(uuid.uuid4())

        if is_manual:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": u["id"], "username": u.get("username"),
                "amount": -charge, "method": "balance", "status": "approved",
                "type": "order", "service_id": service_id,
                "created_at": now_iso, "approved_at": now_iso,
            })
            await db.orders.insert_one({
                "id": order_uuid, "smm_order_id": None,
                "service_id": service_id, "service_name": svc.get("custom_name") or svc.get("name") or "",
                "link": link, "quantity": quantity, "charge": charge,
                "customer_email": "", "user_id": u["id"], "username": u.get("username"),
                "payment_method": "balance", "source": "api",
                "status": "awaiting_manual_fulfillment", "manual": True,
                "created_at": now_iso, "comments": comments, "provider_id": None,
            })
            return {"order": order_uuid, "manual": True, "charge": f"{charge:.4f}"}

        try:
            smm_resp = await place_smm_order(service_id, link, quantity, comments=comments, provider_id=svc.get("provider_id"))
        except Exception as e:
            raise HTTPException(status_code=502, detail={"error": f"provider error: {e}"})
        smm_order_id = smm_resp.get("order")
        if not smm_order_id:
            raise HTTPException(status_code=502, detail={"error": f"provider error: {smm_resp.get('error') or smm_resp}"})

        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": u["id"], "username": u.get("username"),
            "amount": -charge, "method": "balance", "status": "approved",
            "type": "order", "service_id": service_id,
            "created_at": now_iso, "approved_at": now_iso,
        })
        await db.orders.insert_one({
            "id": order_uuid, "smm_order_id": smm_order_id,
            "service_id": service_id, "service_name": svc.get("custom_name") or svc.get("name") or "",
            "link": link, "quantity": quantity, "charge": charge,
            "customer_email": "", "user_id": u["id"], "username": u.get("username"),
            "payment_method": "balance", "source": "api",
            "status": "Pending",
            "created_at": now_iso, "comments": comments,
            "provider_id": svc.get("provider_id"),
        })
        return {"order": smm_order_id, "charge": f"{charge:.4f}"}

    # ---- status / multi_status -----------------------------------------
    if action in ("status", "multi_status"):
        ids_raw = params.get("orders") or params.get("order")
        if not ids_raw:
            raise HTTPException(status_code=400, detail={"error": "order(s) is required"})
        ids = [x.strip() for x in str(ids_raw).replace("|", ",").split(",") if x.strip()]
        results = {}
        for oid in ids:
            # Look up by internal uuid OR by smm_order_id
            row = await db.orders.find_one(
                {"$or": [{"id": oid}, {"smm_order_id": oid}, {"smm_order_id": int(oid) if oid.isdigit() else oid}], "user_id": u["id"]},
                {"_id": 0, "id": 1, "smm_order_id": 1, "status": 1, "charge": 1, "quantity": 1, "provider_id": 1, "service_id": 1},
            )
            if not row:
                results[oid] = {"error": "not found"}
                continue
            # If we have a real provider order id, query the provider for a fresh status.
            fresh_status = row.get("status") or "Pending"
            remains = None
            if row.get("smm_order_id"):
                try:
                    r = await smm_request({"action": "status", "order": row["smm_order_id"]}, provider_id=row.get("provider_id"))
                    if isinstance(r, dict):
                        if r.get("status"):
                            fresh_status = r.get("status")
                        if r.get("remains") is not None:
                            remains = r.get("remains")
                except Exception:
                    pass
            results[oid] = {
                "charge": f"{float(row.get('charge') or 0):.4f}",
                "start_count": None,
                "status": fresh_status,
                "remains": remains,
                "currency": "USD",
                "order": row.get("smm_order_id") or row.get("id"),
            }
        if action == "status" and len(ids) == 1:
            return results[ids[0]]
        return results

    # ---- cancel / refill -----------------------------------------------
    if action in ("cancel", "refill"):
        ids_raw = params.get("orders") or params.get("order")
        if not ids_raw:
            raise HTTPException(status_code=400, detail={"error": "order(s) is required"})
        ids = [x.strip() for x in str(ids_raw).replace("|", ",").split(",") if x.strip()]
        out = {}
        for oid in ids:
            row = await db.orders.find_one(
                {"$or": [{"id": oid}, {"smm_order_id": oid}], "user_id": u["id"]},
                {"_id": 0, "smm_order_id": 1, "provider_id": 1},
            )
            if not row or not row.get("smm_order_id"):
                out[oid] = {"error": "not found"}
                continue
            try:
                r = await smm_request({"action": action, "order": row["smm_order_id"]}, provider_id=row.get("provider_id"))
                out[oid] = r
            except Exception as e:
                out[oid] = {"error": str(e)[:120]}
        if len(ids) == 1:
            return out[ids[0]]
        return out

    raise HTTPException(status_code=400, detail={"error": f"unknown action '{action}'"})


@app.post("/api/v2")
async def api_v2_post(request: Request):
    """JAP-style endpoint. Accepts form-urlencoded OR JSON body."""
    ctype = (request.headers.get("content-type") or "").lower()
    params: dict = {}
    if "application/json" in ctype:
        try:
            params = await request.json() or {}
        except Exception:
            params = {}
    else:
        form = await request.form()
        params = {k: (v if isinstance(v, str) else str(v)) for k, v in form.items()}
    # Fallback: also accept query params
    for k, v in request.query_params.items():
        params.setdefault(k, v)
    return await _api_v2_dispatch(params)


@app.get("/api/v2")
async def api_v2_get(request: Request):
    """Convenience: GET /api/v2?key=...&action=balance for quick tests."""
    params = {k: v for k, v in request.query_params.items()}
    return await _api_v2_dispatch(params)




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
withdrawable = _get_user_withdrawable


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
