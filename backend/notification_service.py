"""Centralized user notification helper.

Every user-facing event on the site (order placed, deposit credited, ticket
reply, incoming DM, account closed) routes through here. This gives us:

  • One place to compose branded HTML emails
  • Rate-limiting per user + per event-type (prevents email flooding on
    heavy chat activity)
  • Per-user opt-out preferences (user_settings.email_prefs)
  • Consistent subject-line prefix so users can filter in Gmail

Uses `email_service.send_email()` under the hood so it picks up whichever
provider (Elastic → MailerSend → SMTP) the admin has configured.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorDatabase

from email_service import send_email

logger = logging.getLogger("notify")

BRAND_NAME = "Better Social"
BRAND_COLOR = "#10b981"  # emerald-500
DEFAULT_SITE_URL = "https://better-social.pro"

# Default rate-limit windows per event type. Chat/DM events cluster fast so
# they get a longer cooldown; billing events fire on every occurrence.
RATE_LIMIT_SEC = {
    "order":     0,      # every order → email (money moved, user cares)
    "deposit":   0,      # every deposit → email
    "ticket":    0,      # every staff reply → email
    "dm":        120,    # 2 min between DM emails (batch bursts of msgs)
    "voice":     60,     # 1 min between voice-msg emails
    "account_close": 0,
    "generic":   300,    # 5 min default
}

# Which events users can toggle in their settings (opt-out).
# `account_close` and `deposit` are non-toggleable (billing/security).
EVENT_TOGGLE_KEYS = {
    "order":   "email_orders",
    "ticket":  "email_tickets",
    "dm":      "email_dms",
    "voice":   "email_voice",
    "generic": "email_generic",
}


def _sanitize_site_url(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if any(token in parsed.netloc.lower() for token in ("your-domain", "example", "placeholder", "localhost")):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_app_url(path: str, raw_base: Optional[str] = None) -> str:
    if not path:
        return DEFAULT_SITE_URL
    if path.startswith("http://") or path.startswith("https://"):
        return path

    candidates = []
    if raw_base:
        candidates.append(raw_base)
    for env_key in ("FRONTEND_URL", "REACT_APP_FRONTEND_URL", "APP_URL", "REACT_APP_BACKEND_URL", "BACKEND_URL"):
        value = os.environ.get(env_key)
        if value:
            candidates.append(value)
    for candidate in candidates:
        base = _sanitize_site_url(candidate)
        if base:
            return f"{base}{path if path.startswith('/') else '/' + path}"
    return f"{DEFAULT_SITE_URL}{path if path.startswith('/') else '/' + path}"


async def _get_user_email_prefs(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "email_prefs": 1, "email": 1})
    return {
        "email": (doc or {}).get("email"),
        "prefs": (doc or {}).get("email_prefs") or {},
    }


async def _rate_ok(db: AsyncIOMotorDatabase, user_id: str, event: str) -> bool:
    """Returns True if we're allowed to send this event to this user right now."""
    cooldown = RATE_LIMIT_SEC.get(event, RATE_LIMIT_SEC["generic"])
    if cooldown <= 0:
        return True
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=cooldown)).isoformat()
    recent = await db.email_notifications.find_one(
        {"user_id": user_id, "event": event, "sent_at": {"$gt": cutoff}},
        {"_id": 0, "id": 1},
    )
    return not recent


async def _log_sent(db: AsyncIOMotorDatabase, user_id: str, event: str, subject: str, ok: bool, err: Optional[str] = None):
    await db.email_notifications.insert_one({
        "user_id": user_id,
        "event": event,
        "subject": subject[:200],
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "ok": bool(ok),
        "error": (err or "")[:300],
    })


def _wrap_html(inner: str, cta_url: Optional[str] = None, cta_label: Optional[str] = None) -> str:
    cta_block = ""
    if cta_url and cta_label:
        cta_block = (
            f'<div style="margin:32px 0 8px;text-align:center">'
            f'<a href="{cta_url}" style="display:inline-block;background:{BRAND_COLOR};color:#000;'
            f'padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:800;'
            f'font-family:Helvetica,Arial,sans-serif;font-size:14px;letter-spacing:0.5px">'
            f'{cta_label}</a></div>'
        )
    return f"""
<!doctype html><html><body style="margin:0;background:#050505;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:40px 24px;color:#e5e7eb">
  <div style="text-align:center;padding-bottom:20px;border-bottom:1px solid #1f2937;">
    <div style="display:inline-block;font-weight:900;font-size:22px;letter-spacing:-0.02em;color:#fff">
      Better<span style="color:{BRAND_COLOR}">Social</span>
    </div>
  </div>
  <div style="padding:32px 4px;line-height:1.55;font-size:15px;color:#e5e7eb">
    {inner}
    {cta_block}
  </div>
  <div style="padding-top:20px;border-top:1px solid #1f2937;text-align:center;font-size:11px;color:#6b7280;line-height:1.6">
    You're getting this because you have a Better Social account.<br/>
    Manage notification preferences in <a href="#" style="color:{BRAND_COLOR};text-decoration:none">Settings → Notifications</a>.<br/>
    © {datetime.now().year} BetterSocial
  </div>
</div>
</body></html>
"""


async def notify_user(
    db: AsyncIOMotorDatabase,
    user_id: str,
    event: str,
    subject: str,
    body_html: str,
    cta_url: Optional[str] = None,
    cta_label: Optional[str] = None,
) -> dict:
    """Send an email notification to `user_id` for `event`.

    Silently no-ops (with a debug log) when:
      • The user has opted out of this event type
      • The user has no email address
      • The rate-limit window hasn't elapsed
      • The email provider isn't configured yet

    Never raises — a failed notification should never break the trigger flow.
    """
    try:
        pu = await _get_user_email_prefs(db, user_id)
        email = pu["email"]
        if not email:
            return {"ok": False, "skipped": "no_email"}
        prefs = pu["prefs"]
        toggle_key = EVENT_TOGGLE_KEYS.get(event)
        if toggle_key and prefs.get(toggle_key) is False:
            return {"ok": False, "skipped": "opted_out"}
        if not await _rate_ok(db, user_id, event):
            return {"ok": False, "skipped": "rate_limited"}
        safe_cta = _sanitize_site_url(cta_url) if cta_url and cta_url.startswith(("http://", "https://")) else cta_url
        html = _wrap_html(body_html, safe_cta, cta_label)
        subj = f"[Better Social] {subject}"
        res = await send_email(db, email, subj, html)
        await _log_sent(db, user_id, event, subj, res.get("ok", False), res.get("error"))
        return res
    except Exception as e:
        logger.exception("notify_user failed: %s", e)
        return {"ok": False, "error": str(e)}


# ---- Ready-made composers ----

async def notify_order_placed(db, user_id: str, order: dict, backend_url: str):
    charge = float(order.get("charge") or 0)
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">🛒 Your order is confirmed</h2>
<p>Thanks for your purchase — we've queued it with our provider network.</p>
<div style="background:#0f2a15;border:1px solid #10b98133;border-radius:8px;padding:16px;margin:16px 0">
  <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Order summary</div>
  <div style="font-size:14px;line-height:1.9">
    <div><strong style="color:#fff">Service:</strong> {order.get('service_name') or order.get('service') or 'SMM'}</div>
    <div><strong style="color:#fff">Quantity:</strong> {order.get('quantity')}</div>
    <div><strong style="color:#fff">Amount charged:</strong> <span style="color:{BRAND_COLOR};font-weight:700">${charge:.2f}</span></div>
    <div><strong style="color:#fff">Order ID:</strong> <code style="color:#fbbf24">{order.get('id','?')[:12]}</code></div>
  </div>
</div>
<p style="color:#9ca3af;font-size:13px">We'll drop the target link into the provider queue in ~30s. You can watch progress from your dashboard.</p>
"""
    return await notify_user(db, user_id, "order",
        subject=f"Order confirmed — ${charge:.2f}",
        body_html=body,
        cta_url=_build_app_url("/client/dashboard?tab=invoices", backend_url),
        cta_label="View order")


async def notify_deposit_credited(db, user_id: str, amount: float, bonus: float, backend_url: str, method: str = "crypto"):
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">💰 Deposit received</h2>
<p>Great news — your ${amount:.2f} {method} deposit just landed in your balance.</p>
<div style="background:#0f2a15;border:1px solid #10b98133;border-radius:8px;padding:16px;margin:16px 0">
  <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Deposit summary</div>
  <div style="font-size:14px;line-height:1.9">
    <div><strong style="color:#fff">Amount paid:</strong> <span style="color:{BRAND_COLOR};font-weight:700">${amount:.2f}</span></div>
    {"<div><strong style='color:#fff'>Bonus applied:</strong> <span style='color:#fbbf24;font-weight:700'>+$" + f"{bonus:.2f}" + "</span></div>" if bonus > 0 else ""}
    <div><strong style="color:#fff">Total credited:</strong> <span style="color:{BRAND_COLOR};font-weight:800">${(amount + bonus):.2f}</span></div>
    <div><strong style="color:#fff">Method:</strong> {method.upper()}</div>
  </div>
</div>
<p style="color:#9ca3af;font-size:13px">Your balance is ready to use — head over to the buy page to place an order.</p>
"""
    return await notify_user(db, user_id, "deposit",
        subject=f"Deposit credited — ${amount + bonus:.2f}",
        body_html=body,
        cta_url=_build_app_url("/client/dashboard?tab=buy", backend_url),
        cta_label="Place an order")


async def notify_deposit_status(db, user_id: str, status: str, amount: float, backend_url: str,
                                paid_usd: float = 0.0, missing_usd: float = 0.0):
    """Email the user about a crypto deposit status change (pending/confirming/partial/failed)."""
    titles = {
        "waiting": ("⏳ Deposit pending", f"We created your ${amount:.2f} crypto deposit. Complete the payment in the checkout window — your balance will be credited automatically once the network confirms it."),
        "confirming": ("🔍 Payment detected", f"We detected your crypto payment for the ${amount:.2f} deposit. It's now confirming on the blockchain — this usually takes a few minutes."),
        "partially_paid": ("⚠️ Partial payment received", f"We received <b>${paid_usd:.2f}</b> of your <b>${amount:.2f}</b> deposit — <b>${missing_usd:.2f}</b> is still missing. Our team has been notified and will review it shortly. You may be credited for the amount you actually paid."),
        "failed": ("❌ Deposit failed", f"Your ${amount:.2f} crypto deposit failed. No funds were credited. If you believe this is an error, contact support."),
        "expired": ("⌛ Deposit expired", f"Your ${amount:.2f} crypto deposit invoice expired before payment completed. You can start a new deposit any time."),
        "refunded": ("↩️ Deposit refunded", f"Your ${amount:.2f} crypto deposit was refunded by the payment provider."),
    }
    title, msg = titles.get(status, (f"Deposit update: {status}", f"Your ${amount:.2f} crypto deposit status changed to <b>{status}</b>."))
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">{title}</h2>
<p>{msg}</p>
<div style="background:#0f2a15;border:1px solid #10b98133;border-radius:8px;padding:16px;margin:16px 0">
  <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Deposit details</div>
  <div style="font-size:14px;line-height:1.9">
    <div><strong style="color:#fff">Invoice amount:</strong> <span style="color:{BRAND_COLOR};font-weight:700">${amount:.2f}</span></div>
    {f"<div><strong style='color:#fff'>Received so far:</strong> <span style='color:#fbbf24;font-weight:700'>${paid_usd:.2f}</span></div><div><strong style='color:#fff'>Missing:</strong> <span style='color:#f87171;font-weight:700'>${missing_usd:.2f}</span></div>" if status == "partially_paid" else ""}
    <div><strong style="color:#fff">Status:</strong> {status.replace("_", " ").upper()}</div>
  </div>
</div>
"""
    return await notify_user(db, user_id, "deposit",
        subject=f"{title.split(' ', 1)[1] if ' ' in title else title} — ${amount:.2f} deposit",
        body_html=body,
        cta_url=_build_app_url("/client/dashboard?tab=wallet", backend_url),
        cta_label="View wallet")


async def notify_bonus_waiting(db, user_id: str, amount: float, backend_url: str):
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">🎁 Balance Bonus Free to your account waiting</h2>
<p>Great news — a <b>free balance bonus of €{amount:.2f}</b> has been gifted to your account!</p>
<div style="background:#0f2a15;border:1px solid #10b98133;border-radius:8px;padding:16px;margin:16px 0;text-align:center">
  <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Your free bonus</div>
  <div style="font-size:32px;font-weight:900;color:{BRAND_COLOR}">€{amount:.2f}</div>
</div>
<p>Open the purchase page and the claim popup will appear — hit <b>Claim</b> and the funds land in your balance instantly. You can also decline it if you don't want it.</p>
"""
    return await notify_user(db, user_id, "deposit",
        subject=f"Balance Bonus Free to your account waiting — €{amount:.2f}",
        body_html=body,
        cta_url=_build_app_url("/client/dashboard?tab=buy", backend_url),
        cta_label="Claim your bonus")


async def notify_ticket_reply(db, user_id: str, ticket_id: str, subject: str, staff_name: str, message: str, backend_url: str):
    preview = (message or "")[:280]
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">🎫 Support replied to your ticket</h2>
<p><strong style="color:#fff">{staff_name}</strong> just replied to your ticket "<em>{subject}</em>".</p>
<div style="background:#0f2a15;border-left:3px solid {BRAND_COLOR};padding:14px 16px;margin:16px 0;font-size:14px;line-height:1.6;color:#d1d5db;border-radius:0 8px 8px 0">
  {preview}{"…" if len(message or "") > 280 else ""}
</div>
"""
    return await notify_user(db, user_id, "ticket",
        subject=f"Support reply: {subject[:40]}",
        body_html=body,
        cta_url=_build_app_url("/client/dashboard?tab=tickets", backend_url),
        cta_label="Open ticket")


async def notify_dm_received(db, user_id: str, from_username: str, preview: str, backend_url: str, kind: str = "text"):
    kind_emoji = "🎤" if kind == "voice" else "💬"
    kind_label = "voice message" if kind == "voice" else "message"
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">{kind_emoji} New {kind_label} from @{from_username}</h2>
<p>You have a new {kind_label} in your inbox.</p>
{"<div style='background:#0f2a15;border-left:3px solid " + BRAND_COLOR + ";padding:14px 16px;margin:16px 0;font-size:14px;line-height:1.6;color:#d1d5db;border-radius:0 8px 8px 0'>" + preview[:280] + "</div>" if kind != "voice" and preview else ""}
<p style="color:#9ca3af;font-size:13px">You'll only get one of these emails every {RATE_LIMIT_SEC['dm'] // 60} minutes even if new messages keep arriving — so we don't spam you.</p>
"""
    return await notify_user(db, user_id, "voice" if kind == "voice" else "dm",
        subject=f"@{from_username} sent you a {kind_label}",
        body_html=body,
        cta_url=_build_app_url("/client/dashboard?tab=messages", backend_url),
        cta_label="Open messages")


async def notify_guest_order_placed(db: AsyncIOMotorDatabase, to_email: str, order: dict, backend_url: str) -> dict:
    """Send an order-confirmation email to a GUEST (no user_id) who paid via coupon/crypto on the landing page."""
    if not to_email or "@" not in to_email:
        return {"ok": False, "skipped": "no_email"}
    charge = float(order.get("price_usd") or order.get("charge") or 0)
    status_url = _build_app_url(f"/status/{order.get('id','')}", backend_url)
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">🛒 Your order is confirmed</h2>
<p>Thanks for your purchase — we've queued it with our provider network.</p>
<div style="background:#0f2a15;border:1px solid #10b98133;border-radius:8px;padding:16px;margin:16px 0">
  <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Order summary</div>
  <div style="font-size:14px;line-height:1.9">
    <div><strong style="color:#fff">Service:</strong> {order.get('service_name') or 'SMM'}</div>
    <div><strong style="color:#fff">Link:</strong> <span style="word-break:break-all;color:#9ca3af">{order.get('link') or ''}</span></div>
    <div><strong style="color:#fff">Quantity:</strong> {order.get('quantity')}</div>
    <div><strong style="color:#fff">Amount:</strong> <span style="color:{BRAND_COLOR};font-weight:700">${charge:.2f}</span></div>
    <div><strong style="color:#fff">Order ID:</strong> <code style="color:#fbbf24">{order.get('id','?')[:12]}</code></div>
  </div>
</div>
<p style="color:#9ca3af;font-size:13px">Track your order at <a href="{status_url}" style="color:{BRAND_COLOR}">this link</a>. Create an account for future orders + a wallet balance.</p>
"""
    html = _wrap_html(body, cta_url=status_url, cta_label="Track order")
    subj = f"[Better Social] Order confirmed — ${charge:.2f}"
    return await send_email(db, to_email, subj, html)


async def notify_account_closed(db, user_id: str, reason: str = ""):
    body = f"""
<h2 style="color:#fff;font-size:20px;margin:0 0 8px">Your account has been closed</h2>
<p>This is your confirmation that your Better Social account has been permanently closed.</p>
{"<p style='color:#9ca3af'><strong style='color:#fff'>Reason:</strong> " + reason + "</p>" if reason else ""}
<p>If this wasn't you, or you'd like to appeal, reply to this email within 30 days.</p>
"""
    return await notify_user(db, user_id, "account_close",
        subject="Account closed",
        body_html=body)
