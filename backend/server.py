from fastapi import FastAPI, APIRouter, HTTPException, Request, Header
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import hmac
import hashlib
import secrets
import string
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from urllib.parse import urlencode

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

SMM_API_URL_DEFAULT = "https://smmcost.com/api/v2"
SMM_API_KEY_DEFAULT = os.environ.get("SMM_API_KEY", "47b5c3b01e4b5ecd1e53b39baef31a6e")

ADMIN_USER = "Balkin99"
ADMIN_PASS = "Armin1234"
ADMIN_SESSIONS = set()  # in-mem session tokens

app = FastAPI()
api_router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


# ============ MODELS ============
class CheckoutRequest(BaseModel):
    service_id: int
    link: str
    quantity: int
    payment_method: str  # "coupon" | "coinpayments"
    coupon_code: Optional[str] = None
    customer_email: Optional[str] = None
    price_usd: float


class CouponCreate(BaseModel):
    amount: float
    note: Optional[str] = ""


class CoinPaymentsConfig(BaseModel):
    public_key: str
    private_key: str
    ipn_secret: str
    merchant_id: str


class SmmConfig(BaseModel):
    api_url: str
    api_key: str


class ServiceUpdate(BaseModel):
    custom_rate: Optional[float] = None
    enabled: Optional[bool] = None
    name: Optional[str] = None


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
            "name": s.get("name", ""),
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

    # ----- CoinPayments flow -----
    if req.payment_method == "coinpayments":
        cfg = await db.coinpayments_config.find_one({}, {"_id": 0})
        if not cfg or not cfg.get("public_key"):
            raise HTTPException(status_code=400, detail="CoinPayments is not configured. Use coupon code instead.")

        post_data = urlencode({
            "version": "1",
            "cmd": "create_transaction",
            "key": cfg["public_key"],
            "format": "json",
            "amount": f"{req.price_usd:.2f}",
            "currency1": "USD",
            "currency2": "BTC",
            "buyer_email": req.customer_email or "noreply@bettersocial.app",
            "item_name": f"Order {order_id[:8]}",
            "custom": order_id,
        })
        sig = hmac.new(cfg["private_key"].encode(), post_data.encode(), hashlib.sha512).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(
                    "https://www.coinpayments.net/api.php",
                    content=post_data,
                    headers={"HMAC": sig, "Content-Type": "application/x-www-form-urlencoded"},
                )
                cp = r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"CoinPayments error: {e}")

        if cp.get("error") != "ok":
            raise HTTPException(status_code=400, detail=f"CoinPayments: {cp.get('error')}")

        result = cp.get("result", {})
        base_doc.update({
            "status": "pending",
            "txn_id": result.get("txn_id"),
            "checkout_url": result.get("checkout_url"),
            "qrcode_url": result.get("qrcode_url"),
            "crypto_amount": result.get("amount"),
            "crypto_address": result.get("address"),
        })
        await db.orders.insert_one(base_doc.copy())
        return {
            "status": "pending",
            "order_id": order_id,
            "txn_id": result.get("txn_id"),
            "checkout_url": result.get("checkout_url"),
            "qrcode_url": result.get("qrcode_url"),
            "amount": result.get("amount"),
            "address": result.get("address"),
        }

    raise HTTPException(status_code=400, detail="Invalid payment method")


@api_router.post("/coinpayments/check")
async def check_coinpayments(req: CheckTxRequest):
    """Poll CoinPayments status; if complete, place SMM order and mark fulfilled."""
    order = await db.orders.find_one({"id": req.order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") == "completed":
        return {"status": "completed", "smm_order_id": order.get("smm_order_id")}
    if not order.get("txn_id"):
        raise HTTPException(status_code=400, detail="No transaction id")

    cfg = await db.coinpayments_config.find_one({}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=400, detail="CoinPayments not configured")

    post_data = urlencode({
        "version": "1",
        "cmd": "get_tx_info",
        "key": cfg["public_key"],
        "format": "json",
        "txid": order["txn_id"],
    })
    sig = hmac.new(cfg["private_key"].encode(), post_data.encode(), hashlib.sha512).hexdigest()
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(
            "https://www.coinpayments.net/api.php",
            content=post_data,
            headers={"HMAC": sig, "Content-Type": "application/x-www-form-urlencoded"},
        )
        cp = r.json()

    if cp.get("error") != "ok":
        return {"status": "pending", "detail": cp.get("error")}

    result = cp.get("result", {})
    cp_status = result.get("status", 0)
    # status >= 100 means complete
    if int(cp_status) >= 100:
        try:
            smm_resp = await place_smm_order(order["service_id"], order["link"], order["quantity"])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"SMM API error: {e}")
        await db.orders.update_one(
            {"id": req.order_id},
            {"$set": {"status": "completed", "smm_order_id": smm_resp.get("order"), "smm_response": smm_resp}},
        )
        return {"status": "completed", "smm_order_id": smm_resp.get("order")}
    return {"status": "pending", "cp_status": cp_status, "status_text": result.get("status_text")}


# ============ ADMIN ROUTES ============
@api_router.post("/admin/login")
async def admin_login(payload: AdminLogin):
    if payload.username != ADMIN_USER or payload.password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
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
    update_doc = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_doc:
        return {"updated": False}
    res = await db.curated_services.update_one({"service_id": service_id}, {"$set": update_doc})
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
