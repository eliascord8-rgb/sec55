"""SMTP email service — sends transactional emails (welcome, password reset, etc.).
All SMTP credentials are stored in the `email_config` Mongo collection (set via admin UI).
"""
from __future__ import annotations

import logging
import ssl
from email.message import EmailMessage
from typing import Optional

import aiosmtplib
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("email_service")


async def get_email_config(db: AsyncIOMotorDatabase) -> Optional[dict]:
    cfg = await db.email_config.find_one({"_id": "singleton"}, {"_id": 0})
    if not cfg or not cfg.get("smtp_host") or not cfg.get("smtp_user"):
        return None
    return cfg


async def send_email(
    db: AsyncIOMotorDatabase,
    to_email: str,
    subject: str,
    html: str,
    text_alt: Optional[str] = None,
) -> dict:
    """Send a transactional email. Prefers MailerSend API if configured, else falls back to SMTP.
    Returns {ok: bool, error?: str}."""
    cfg = await db.email_config.find_one({"_id": "singleton"}, {"_id": 0}) or {}

    # ---- Elastic Email API path (NO KYC — preferred) ----
    ee_key = (cfg.get("elastic_api_key") or "").strip()
    if ee_key:
        from_email = (cfg.get("from_email") or "").strip()
        from_name = (cfg.get("from_name") or "Better Social").strip()
        if not from_email:
            return {"ok": False, "error": "Elastic Email: from_email is required (must be on a verified domain)"}
        import httpx
        payload = {
            "Recipients": {"To": [to_email]},
            "Content": {
                "Body": [{"ContentType": "HTML", "Content": html, "Charset": "utf-8"}],
                "From": f"{from_name} <{from_email}>",
                "Subject": subject,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.post(
                    "https://api.elasticemail.com/v4/emails/transactional",
                    json=payload,
                    headers={
                        "X-ElasticEmail-ApiKey": ee_key,
                        "Content-Type": "application/json",
                    },
                )
            if r.status_code in (200, 201, 202):
                return {"ok": True, "provider": "elastic_email"}
            return {"ok": False, "error": f"Elastic {r.status_code}: {r.text[:300]}"}
        except Exception as e:
            logger.exception("Elastic Email send failed: %s", e)
            return {"ok": False, "error": f"Elastic Email: {str(e)[:200]}"}

    # ---- MailerSend API path (fallback) ----
    ms_key = cfg.get("mailersend_api_key", "").strip()
    if ms_key:
        from_email = (cfg.get("from_email") or "").strip()
        from_name = (cfg.get("from_name") or "Better Social").strip()
        if not from_email:
            return {"ok": False, "error": "MailerSend: from_email is required (must be on a verified domain)"}
        import httpx
        payload = {
            "from": {"email": from_email, "name": from_name},
            "to": [{"email": to_email}],
            "subject": subject,
            "html": html,
            "text": text_alt or _html_to_text(html),
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(
                    "https://api.mailersend.com/v1/email",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {ms_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
            if r.status_code in (200, 201, 202):
                return {"ok": True, "provider": "mailersend"}
            return {"ok": False, "error": f"MailerSend {r.status_code}: {r.text[:300]}"}
        except Exception as e:
            logger.exception("MailerSend send failed: %s", e)
            return {"ok": False, "error": f"MailerSend: {str(e)[:200]}"}

    # ---- SMTP fallback ----
    if not cfg.get("smtp_host") or not cfg.get("smtp_user"):
        return {"ok": False, "error": "Email not configured (no MailerSend key and no SMTP host)"}

    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port", 587))
    user = cfg["smtp_user"]
    password = cfg.get("smtp_password", "")
    from_email = (cfg.get("from_email") or user).strip()
    from_name = (cfg.get("from_name") or "Better Social").strip()
    use_tls = bool(cfg.get("use_tls", True))

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_alt or _html_to_text(html))
    msg.add_alternative(html, subtype="html")

    try:
        if port == 465:
            await aiosmtplib.send(msg, hostname=host, port=port, username=user, password=password, use_tls=True, timeout=15)
        else:
            await aiosmtplib.send(msg, hostname=host, port=port, username=user, password=password, start_tls=use_tls, timeout=15)
        return {"ok": True, "provider": "smtp"}
    except Exception as e:
        logger.exception("send_email failed: %s", e)
        return {"ok": False, "error": str(e)[:200]}


def _html_to_text(html: str) -> str:
    """Very rough HTML→text fallback for clients that don't render HTML."""
    import re

    txt = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    txt = re.sub(r"<\s*/?p[^>]*>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    return txt.strip()


# ============== Email Templates ==============

def _wrap(content: str, brand: str = "Better Social") -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{brand}</title></head>
<body style="margin:0;padding:0;background:#0d0a14;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#eeeeee;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#0d0a14;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width:560px;background:#1a1525;border:1px solid #2a2235;border-radius:6px;overflow:hidden;">
        <tr><td style="padding:24px 28px;border-bottom:1px solid #2a2235;background:linear-gradient(90deg,#FF007F,#7B2CBF);">
          <h1 style="margin:0;font-size:20px;font-weight:900;color:#fff;letter-spacing:-0.5px;">{brand}</h1>
        </td></tr>
        <tr><td style="padding:28px;color:#eaeaea;line-height:1.55;font-size:15px;">
          {content}
        </td></tr>
        <tr><td style="padding:18px 28px;border-top:1px solid #2a2235;font-size:11px;color:#777;background:#15101e;">
          You received this email because an account exists with this address at {brand}.<br>
          If this wasn&#39;t you, you can safely ignore it.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def welcome_email_html(username: str, brand: str = "Better Social") -> str:
    body = f"""
    <h2 style="margin:0 0 12px;font-size:22px;color:#fff;">Welcome, @{username} 👋</h2>
    <p style="margin:0 0 16px;">Your account is live. You can now log in, top up your balance and place orders directly from your dashboard.</p>
    <p style="margin:0 0 24px;">
      <a href="https://better-social.pro/client/login" style="display:inline-block;background:linear-gradient(90deg,#FF007F,#7B2CBF);color:#fff;text-decoration:none;padding:12px 22px;border-radius:4px;font-weight:700;font-size:13px;letter-spacing:0.5px;text-transform:uppercase;">Open Dashboard</a>
    </p>
    <p style="margin:0;color:#999;font-size:13px;">Need help? Just reply to this email or open the live chat on our website — our team typically replies within minutes.</p>
    """
    return _wrap(body, brand)


def reset_email_html(reset_url: str, brand: str = "Better Social") -> str:
    body = f"""
    <h2 style="margin:0 0 12px;font-size:22px;color:#fff;">Reset your password</h2>
    <p style="margin:0 0 16px;">We received a request to reset the password for your {brand} account. Click the button below to choose a new password. This link expires in <strong>30 minutes</strong>.</p>
    <p style="margin:0 0 24px;">
      <a href="{reset_url}" style="display:inline-block;background:linear-gradient(90deg,#FF007F,#7B2CBF);color:#fff;text-decoration:none;padding:12px 22px;border-radius:4px;font-weight:700;font-size:13px;letter-spacing:0.5px;text-transform:uppercase;">Reset Password</a>
    </p>
    <p style="margin:0 0 8px;color:#999;font-size:12px;">Or copy &amp; paste this link into your browser:</p>
    <p style="margin:0;color:#FF007F;font-size:12px;word-break:break-all;">{reset_url}</p>
    """
    return _wrap(body, brand)
