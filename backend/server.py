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
ADMIN_SESSIONS = set()  # in-mem session tokens

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


def check_admin(token: Optional[str]) -> None:
    if not token or token not in ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="Unauthorized")


def gen_coupon_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "BS-" + "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(3))


async def get_smm_config() -> dict:
    cfg = await db.smm_config.find_one({}, {"_id": 0})
    if cfg and cfg.get("api_url") and cfg.get("api_key"):
        return cfg
    return {"api_url": SMM_API_URL_DEFAULT, "api_key": SMM_API_KEY_DEFAULT}


async def smm_request(payload: dict) -> dict:
    cfg = await get_smm_config()
    payload["key"] = cfg["api_key"]
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(cfg["api_url"], data=payload)
        r.raise_for_status()
        return r.json()


async def place_smm_order(service_id: int, link: str, quantity: int) -> dict:
    return await smm_request({"action": "add", "service": service_id, "link": link, "quantity": quantity})


# ============ PUBLIC ROUTES ============
@api_router.get("/")
async def root():
    return {"app": "Better Social", "status": "ok"}


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

        # Place SMM order; refund on failure
        try:
            smm_resp = await place_smm_order(req.service_id, req.link, req.quantity)
        except Exception as e:
            await db.coupons.update_one({"code": code}, {"$inc": {"balance": req.price_usd}})
            raise HTTPException(status_code=502, detail=f"SMM API error: {e}")

        if "error" in smm_resp:
            await db.coupons.update_one({"code": code}, {"$inc": {"balance": req.price_usd}})
            raise HTTPException(status_code=400, detail=f"SMM error: {smm_resp['error']}")

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
        smm_resp = await place_smm_order(order["service_id"], order["link"], order["quantity"])
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
@api_router.post("/admin/login")
async def admin_login(payload: AdminLogin):
    # Case-insensitive username + strip whitespace to forgive typos
    if (payload.username or "").strip().lower() != ADMIN_USER.lower() or \
       (payload.password or "") != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(24)
    ADMIN_SESSIONS.add(token)
    return {"token": token}


class AdminSecretLogin(BaseModel):
    secret: str


@api_router.post("/admin/login-secret")
async def admin_login_secret(payload: AdminSecretLogin):
    """Bypass username/password by providing a pre-shared URL secret.
    Configure by setting ADMIN_URL_SECRET in backend/.env."""
    if not ADMIN_URL_SECRET:
        raise HTTPException(status_code=404, detail="Not configured")
    if not secrets.compare_digest((payload.secret or "").strip(), ADMIN_URL_SECRET):
        raise HTTPException(status_code=401, detail="Invalid secret")
    token = secrets.token_urlsafe(24)
    ADMIN_SESSIONS.add(token)
    return {"token": token}


@api_router.get("/admin/orders")
async def admin_orders(x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    orders = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"orders": orders}


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
    return {"users": items, "count": len(items)}


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
    cur = db.transactions.aggregate([
        {"$match": {"user_id": user_id, "status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ])
    async for doc in cur:
        return round(float(doc.get("total", 0)), 2)
    return 0.0


@client_router.get("/balance")
async def get_my_balance(user: CurrentUser = Depends(current_user_dep)):
    balance = await _get_user_balance(user.id)
    return {"balance": balance}


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
    await db.coupons.delete_one({"code": code})
    new_balance = await _get_user_balance(user.id)
    return {"ok": True, "amount": round(bal, 2), "balance": new_balance, "code": code}


class BuyWithBalanceRequest(BaseModel):
    service_id: int
    link: str = Field(..., min_length=4, max_length=400)
    quantity: int = Field(..., gt=0)


@client_router.post("/order-with-balance")
async def order_with_balance(body: BuyWithBalanceRequest, user: CurrentUser = Depends(current_user_dep), request: Request = None):
    """Place an SMM order paying with the user's account balance."""
    db: AsyncIOMotorDatabase = request.app.state.db
    # Look up curated service
    svc = await db.curated_services.find_one({"service_id": body.service_id, "enabled": True}, {"_id": 0})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not available")
    rate = float(svc.get("custom_rate", 0))
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Service price not set")
    if body.quantity < int(svc.get("min", 1) or 1) or body.quantity > int(svc.get("max", 100000) or 100000):
        raise HTTPException(status_code=400, detail=f"Quantity must be between {svc.get('min')} and {svc.get('max')}")
    charge = round((rate * body.quantity) / 1000.0, 4)
    balance = await _get_user_balance(user.id)
    if balance < charge:
        raise HTTPException(status_code=402, detail=f"Not enough balance — needs ${charge:.2f}, you have ${balance:.2f}")

    # Place order via SMM provider through the helper exposed on app.state
    place_smm_order = request.app.state.place_smm_order
    try:
        smm_resp = await place_smm_order(body.service_id, body.link, body.quantity)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Order failed: {e}")

    smm_order_id = smm_resp.get("order")
    if not smm_order_id:
        raise HTTPException(status_code=502, detail=f"Provider error: {smm_resp.get('error') or smm_resp}")

    now = datetime.now(timezone.utc).isoformat()
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
    return {
        "roll_id": roll_id,
        "multiplier": multiplier,
        "stake": stake,
        "win": win_amount,
        "net": round(win_amount - stake, 4),
        "balance": new_balance,
    }


@client_router.get("/casino/history")
async def casino_history(user: CurrentUser = Depends(current_user_dep), request: Request = None):
    db_: AsyncIOMotorDatabase = request.app.state.db
    items = await db_.casino_rolls.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).limit(30).to_list(30)
    return {"rolls": items}


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


@client_router.get("/tickets/{ticket_id}")
async def get_my_ticket(ticket_id: str, user: CurrentUser = Depends(current_user_dep)):
    t = await db.tickets.find_one({"id": ticket_id, "user_id": user.id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    msgs = await db.ticket_messages.find(
        {"ticket_id": ticket_id},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
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
        {"$set": {"status": "open", "updated_at": now, "last_reply_by": "user"}},
    )
    return {"ok": True}


# ----- Admin ticket endpoints -----

@api_router.get("/admin/tickets")
async def admin_list_tickets(x_admin_token: Optional[str] = Header(None), status: Optional[str] = None):
    check_admin(x_admin_token)
    q = {}
    if status:
        q["status"] = status
    items = await db.tickets.find(q, {"_id": 0}).sort("updated_at", -1).limit(200).to_list(200)
    # waiting = tickets where last reply was by user
    waiting = sum(1 for t in items if t.get("last_reply_by") == "user" and t.get("status") == "open")
    return {"tickets": items, "waiting": waiting}


@api_router.get("/admin/tickets/{ticket_id}")
async def admin_get_ticket(ticket_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
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
    staff_name: Optional[str] = "Support"


@api_router.post("/admin/tickets/{ticket_id}/reply")
async def admin_reply_ticket(ticket_id: str, body: AdminTicketReply, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0, "id": 1})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.ticket_messages.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "author_role": "staff",
        "author_name": (body.staff_name or "Support").strip()[:40],
        "message": body.message.strip()[:4000],
        "created_at": now,
    })
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"status": "answered", "updated_at": now, "last_reply_by": "staff"}},
    )
    return {"ok": True}


@api_router.post("/admin/tickets/{ticket_id}/close")
async def admin_close_ticket(ticket_id: str, x_admin_token: Optional[str] = Header(None)):
    check_admin(x_admin_token)
    res = await db.tickets.update_one({"id": ticket_id}, {"$set": {"status": "closed"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}


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

app.state.db = db
app.state.place_smm_order = place_smm_order
app.state.check_admin = check_admin


@app.on_event("startup")
async def _startup():
    await seed_owner(db)

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
