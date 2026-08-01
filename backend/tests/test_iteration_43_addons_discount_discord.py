"""Iteration 43: add-ons, discounts, blacklist, Auto-Live, Discord guilds, roles and auth hardening."""
import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

FRONTEND_ENV = dotenv_values("/app/frontend/.env")
BACKEND_ENV = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FRONTEND_ENV.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing")
API = f"{BASE_URL}/api"
CREDS_PATH = Path("/app/memory/test_credentials.md")


def _credentials(section_name: str) -> dict:
    if not CREDS_PATH.exists():
        pytest.skip("Missing /app/memory/test_credentials.md")
    content = CREDS_PATH.read_text(encoding="utf-8")
    match = re.search(rf"(?ims)^##\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^##\s|\Z)", content)
    if not match:
        pytest.skip(f"Credential section missing: {section_name}")
    section = match.group(1)
    username = re.search(r"(?im)^\s*-\s*Username:\s*(.+?)\s*$", section)
    password = re.search(r"(?im)^\s*-\s*Password:\s*(.+?)\s*$", section)
    if not username or not password:
        pytest.skip(f"Credentials missing: {section_name}")
    return {"username": username.group(1).strip(), "password": password.group(1).strip()}


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("id"), str) and data["id"]
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data.get("question", ""))
    assert match, data
    left, operator, right = int(match.group(1)), match.group(2), int(match.group(3))
    answer = {"+": left + right, "-": left - right, "*": left * right}[operator]
    return data["id"], str(answer)


def _login(session: requests.Session, section_name: str) -> tuple[dict, requests.Response]:
    creds = _credentials(section_name)
    captcha_id, captcha_answer = _solve_captcha(session)
    response = session.post(
        f"{API}/auth/login",
        json={
            "identifier": creds["username"],
            "password": creds["password"],
            "captcha_id": captcha_id,
            "captcha_answer": captcha_answer,
        },
        timeout=30,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("token"), str) and data["token"]
    assert data.get("user", {}).get("username", "").lower() == creds["username"].lower()
    return data, response


@pytest.fixture(scope="module")
def http_session():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(BACKEND_ENV["MONGO_URL"], serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    yield client[BACKEND_ENV["DB_NAME"]]
    client.close()


@pytest.fixture(scope="module")
def context(http_session):
    regular, regular_response = _login(http_session, "Regular test user")
    owner, owner_response = _login(http_session, "Owner")
    secret = http_session.post(f"{API}/admin/login-secret", json={"secret": "haha123"}, timeout=30)
    assert secret.status_code == 200, secret.text
    admin_token = secret.json().get("token")
    assert isinstance(admin_token, str) and admin_token
    return {
        "regular": regular,
        "regular_response": regular_response,
        "regular_headers": {"Authorization": f"Bearer {regular['token']}"},
        "owner": owner,
        "owner_response": owner_response,
        "owner_headers": {"Authorization": f"Bearer {owner['token']}"},
        "admin_headers": {"X-Admin-Token": admin_token},
    }


# Authenticated catalog must expose the full five-addon contract.
def test_addons_catalog_contract(http_session, context):
    response = http_session.get(f"{API}/client/addons/catalog", headers=context["regular_headers"], timeout=30)
    assert response.status_code == 200, response.text
    addons = response.json().get("addons")
    assert isinstance(addons, list) and len(addons) == 5
    by_id = {item["id"]: item for item in addons}
    assert set(by_id) == {"auto_live", "auto_live_week", "username_blacklist", "id_finder", "blacklist_package"}
    package = by_id["blacklist_package"]
    assert package["price"] == pytest.approx(180)
    assert package.get("currency") == "EUR"
    assert package.get("grants_slots") == 1
    assert package.get("platforms") == ["tiktok", "kick", "instagram", "snapchat", "telegram"]
    finder = by_id["id_finder"]
    assert finder["price"] == pytest.approx(200)
    assert finder.get("currency") == "EUR"
    assert isinstance(finder.get("features"), list) and len(finder["features"]) == 6
    assert by_id["auto_live_week"]["price"] == pytest.approx(80)


# Admin create/list, client redeem, discounted insufficient-balance quote and delete/reset lifecycle.
def test_discount_key_full_lifecycle_and_discounted_quote(http_session, context, mongo_db):
    code = f"QAT1{uuid.uuid4().hex[:8].upper()}"
    owner_id = context["owner"]["user"]["id"]
    original_user = mongo_db.users.find_one({"id": owner_id}, {"discount_code": 1, "discount_pct": 1}) or {}
    try:
        created = http_session.post(
            f"{API}/admin/discount-keys",
            headers=context["admin_headers"],
            json={"percent": 30, "code": code, "max_uses": 2},
            timeout=30,
        )
        assert created.status_code == 200, created.text
        key = created.json().get("key", {})
        assert key.get("code") == code and key.get("percent") == pytest.approx(30)
        assert key.get("max_uses") == 2 and key.get("uses") == 0

        listed = http_session.get(f"{API}/admin/discount-keys", headers=context["admin_headers"], timeout=30)
        assert listed.status_code == 200, listed.text
        assert any(row.get("code") == code and row.get("percent") == 30 for row in listed.json().get("keys", []))

        redeemed = http_session.post(
            f"{API}/client/discount/redeem",
            headers=context["owner_headers"],
            json={"code": code.lower()},
            timeout=30,
        )
        assert redeemed.status_code == 200, redeemed.text
        assert redeemed.json().get("code") == code and redeemed.json().get("percent") == pytest.approx(30)
        active = http_session.get(f"{API}/client/discount", headers=context["owner_headers"], timeout=20)
        assert active.status_code == 200 and active.json() == {"code": code, "percent": 30.0}

        catalog = http_session.get(f"{API}/client/addons/catalog", headers=context["owner_headers"], timeout=20).json()["addons"]
        assert next(row for row in catalog if row["id"] == "blacklist_package")["price"] == pytest.approx(180)
        addon_quote = http_session.post(
            f"{API}/client/addons/purchase",
            headers=context["owner_headers"],
            json={"addon_id": "blacklist_package"},
            timeout=30,
        )
        assert addon_quote.status_code == 402, addon_quote.text
        assert "needs $180.00" in addon_quote.json().get("detail", ""), addon_quote.text

        services_response = http_session.get(f"{API}/services", timeout=30)
        assert services_response.status_code == 200, services_response.text
        service = next((row for row in services_response.json().get("services", []) if row.get("service") == 7242), None)
        assert service, "Service 7242 is not available"
        balance_response = http_session.get(f"{API}/client/balance", headers=context["owner_headers"], timeout=20)
        assert balance_response.status_code == 200, balance_response.text
        balance = float(balance_response.json()["balance"])
        quantity = int(service["max"])
        base_charge = float(service["rate"]) * quantity / 1000
        discounted = round(base_charge * 0.70, 4)
        assert discounted > balance, "Chosen quote could place a real provider order; aborting safely"
        quote = http_session.post(
            f"{API}/client/order-with-balance",
            headers=context["owner_headers"],
            json={"service_id": 7242, "link": "https://instagram.com/qa_discount_quote", "quantity": quantity},
            timeout=30,
        )
        assert quote.status_code == 402, quote.text
        detail = quote.json().get("detail", "")
        amount_match = re.search(r"needs \$(\d+(?:\.\d+)?)", detail)
        assert amount_match, detail
        assert float(amount_match.group(1)) == pytest.approx(discounted, abs=0.011)
        assert discounted == pytest.approx(base_charge * 0.70, rel=0.001)

        deleted = http_session.delete(f"{API}/admin/discount-keys/{code}", headers=context["admin_headers"], timeout=30)
        assert deleted.status_code == 200 and deleted.json().get("ok") is True
        inactive = http_session.get(f"{API}/client/discount", headers=context["owner_headers"], timeout=20)
        assert inactive.status_code == 200 and inactive.json() == {"code": None, "percent": 0}
    finally:
        mongo_db.discount_keys.delete_many({"code": code})
        restore = {}
        unset = {}
        for field in ("discount_code", "discount_pct"):
            if field in original_user:
                restore[field] = original_user[field]
            else:
                unset[field] = ""
        update = {}
        if restore:
            update["$set"] = restore
        if unset:
            update["$unset"] = unset
        if update:
            mongo_db.users.update_one({"id": owner_id}, update)


# Blacklist entry must protect the handle from another user and short TikTok URLs are always rejected.
def test_blacklist_cross_user_enforcement_and_short_link_rejection(http_session, context, mongo_db):
    marker = "qaprotected1"
    regular_id = context["regular"]["user"]["id"]
    mongo_db.username_blacklist.delete_many({"user_id": regular_id, "tiktok_username": marker, "platform": "instagram"})
    entry_id = None
    try:
        before = http_session.get(f"{API}/client/addons/blacklist", headers=context["regular_headers"], timeout=20)
        assert before.status_code == 200, before.text
        assert before.json().get("slots_free", 0) >= 1, before.text
        added = http_session.post(
            f"{API}/client/addons/blacklist",
            headers=context["regular_headers"],
            json={"tiktok_username": marker, "platform": "instagram", "reason": "TEST_iter43"},
            timeout=30,
        )
        assert added.status_code == 200, added.text
        entry = added.json().get("entry", {})
        entry_id = entry.get("id")
        assert entry_id and entry.get("tiktok_username") == marker and entry.get("platform") == "instagram"

        blocked = http_session.post(
            f"{API}/client/order-with-balance",
            headers=context["owner_headers"],
            json={"service_id": 7242, "link": f"https://instagram.com/{marker}", "quantity": 100},
            timeout=30,
        )
        assert blocked.status_code == 403, blocked.text
        assert "protected by a BlackList" in blocked.json().get("detail", "")

        short = http_session.post(
            f"{API}/client/order-with-balance",
            headers=context["owner_headers"],
            json={"service_id": 7242, "link": "https://vm.tiktok.com/ZMabc/", "quantity": 100},
            timeout=30,
        )
        assert short.status_code == 400, short.text
        assert "Short links" in short.json().get("detail", "") and "vm.tiktok" in short.json().get("detail", "")
    finally:
        if entry_id:
            cleanup = http_session.delete(
                f"{API}/client/addons/blacklist/{entry_id}", headers=context["regular_headers"], timeout=30
            )
            assert cleanup.status_code in (200, 404), cleanup.text
        mongo_db.username_blacklist.delete_many({"user_id": regular_id, "tiktok_username": marker, "platform": "instagram"})


# Numeric TikTok IDs absent from cache must fail with actionable Finder guidance.
def test_live_sub_numeric_uncached_id_guidance(http_session, context):
    response = http_session.post(
        f"{API}/client/live-sub/create",
        headers=context["regular_headers"],
        json={
            "service_id": 7242,
            "tiktok_username": "999999999999",
            "quantity_per_burst": 100,
            "duration_days": 7,
            "repeat_every_minutes": 5,
            "mode": "always",
        },
        timeout=30,
    )
    assert response.status_code == 404, response.text
    detail = response.json().get("detail", "")
    assert "resolve this user ID" in detail and "TikTok Finder" in detail


# API key regeneration must rotate and persist a new 48-character key.
def test_api_key_regeneration(http_session, context):
    old = http_session.get(f"{API}/client/api-key", headers=context["regular_headers"], timeout=20)
    assert old.status_code == 200, old.text
    old_key = old.json().get("api_key")
    rotated = http_session.post(f"{API}/client/api-key/regenerate", headers=context["regular_headers"], timeout=20)
    assert rotated.status_code == 200, rotated.text
    new_key = rotated.json().get("api_key")
    assert isinstance(new_key, str) and len(new_key) == 48 and new_key != old_key
    persisted = http_session.get(f"{API}/client/api-key", headers=context["regular_headers"], timeout=20)
    assert persisted.status_code == 200 and persisted.json().get("api_key") == new_key


# Guild configuration is owner-scoped; a second account cannot claim the same guild.
def test_discord_guild_ownership_crud_and_expected_invite_503(http_session, context, mongo_db):
    gid = str(100000000000000000 + int(uuid.uuid4().hex[:12], 16) % 899999999999999999)
    try:
        saved = http_session.post(
            f"{API}/client/discord/guilds",
            headers=context["regular_headers"],
            json={
                "guild_id": gid,
                "welcome_text": "Hi {user}",
                "welcomer_enabled": True,
                "bot_nickname": "QABot",
                "features": {"moderation": True, "unknown_feature": True},
            },
            timeout=30,
        )
        assert saved.status_code == 200, saved.text
        guild = saved.json().get("guild", {})
        assert guild.get("guild_id") == gid and guild.get("user_id") == context["regular"]["user"]["id"]
        assert guild.get("welcome_text") == "Hi {user}" and guild.get("bot_nickname") == "QABot"
        assert guild.get("features") == {"moderation": True}

        listed = http_session.get(f"{API}/client/discord/guilds", headers=context["regular_headers"], timeout=20)
        assert listed.status_code == 200, listed.text
        assert any(row.get("guild_id") == gid and row.get("bot_nickname") == "QABot" for row in listed.json().get("guilds", []))

        stolen = http_session.post(
            f"{API}/client/discord/guilds",
            headers=context["owner_headers"],
            json={"guild_id": gid, "welcome_text": "stolen", "welcomer_enabled": False, "features": {}},
            timeout=30,
        )
        assert stolen.status_code == 403, stolen.text
        assert "already managed by another" in stolen.json().get("detail", "")

        invite = http_session.get(f"{API}/discord/invite-url", timeout=20)
        assert invite.status_code == 503, invite.text
        assert "invite not configured" in invite.json().get("detail", "")

        deleted = http_session.delete(f"{API}/client/discord/guilds/{gid}", headers=context["regular_headers"], timeout=20)
        assert deleted.status_code == 200 and deleted.json().get("ok") is True
        after = http_session.get(f"{API}/client/discord/guilds", headers=context["regular_headers"], timeout=20)
        assert not any(row.get("guild_id") == gid for row in after.json().get("guilds", []))
    finally:
        mongo_db.client_discord_guilds.delete_many({"guild_id": gid})


# Admin role update must accept moderator, persist, and be restored to user.
def test_admin_moderator_role_round_trip(http_session, context, mongo_db):
    uid = context["regular"]["user"]["id"]
    original = mongo_db.users.find_one({"id": uid}, {"role": 1}) or {"role": "user"}
    try:
        changed = http_session.put(
            f"{API}/admin/users/{uid}", headers=context["admin_headers"], json={"role": "moderator"}, timeout=30
        )
        assert changed.status_code == 200, changed.text
        assert changed.json().get("user", {}).get("role") == "moderator"
        listed = http_session.get(f"{API}/admin/users", headers=context["admin_headers"], timeout=30)
        assert listed.status_code == 200, listed.text
        row = next(item for item in listed.json().get("users", []) if item.get("id") == uid)
        assert row.get("role") == "moderator"
        restored = http_session.put(
            f"{API}/admin/users/{uid}", headers=context["admin_headers"], json={"role": "user"}, timeout=30
        )
        assert restored.status_code == 200 and restored.json().get("user", {}).get("role") == "user"
    finally:
        mongo_db.users.update_one({"id": uid}, {"$set": {"role": original.get("role", "user")}})


# Discounts are owner-only in the Admin UI and must also be owner-only at the API boundary.
def test_discount_admin_api_rejects_moderator(http_session, context, mongo_db):
    uid = context["regular"]["user"]["id"]
    original = mongo_db.users.find_one({"id": uid}, {"role": 1}) or {"role": "user"}
    try:
        promoted = http_session.put(
            f"{API}/admin/users/{uid}", headers=context["admin_headers"], json={"role": "moderator"}, timeout=30
        )
        assert promoted.status_code == 200, promoted.text
        elevated = http_session.post(
            f"{API}/admin/session-from-user", headers=context["regular_headers"], timeout=30
        )
        assert elevated.status_code == 200, elevated.text
        assert elevated.json().get("role") == "moderator"
        moderator_headers = {"X-Admin-Token": elevated.json()["token"]}
        response = http_session.get(f"{API}/admin/discount-keys", headers=moderator_headers, timeout=30)
        assert response.status_code == 403, (
            f"Moderator accessed owner-only discount keys: {response.status_code} {response.text[:300]}"
        )
    finally:
        mongo_db.users.update_one({"id": uid}, {"$set": {"role": original.get("role", "user")}})


# Stored password hashes must use bcrypt 2b format.
def test_auth_password_hash_format(http_session, context, mongo_db):
    for key in ("regular", "owner"):
        uid = context[key]["user"]["id"]
        user = mongo_db.users.find_one({"id": uid}, {"password_hash": 1})
        assert user and isinstance(user.get("password_hash"), str)
        assert user["password_hash"].startswith("$2b$")


# Successful password login must issue an HttpOnly cookie, not JSON-only auth.
def test_auth_login_sets_httponly_cookie(context):
    for key in ("regular_response", "owner_response"):
        response = context[key]
        set_cookie = response.headers.get("Set-Cookie", "")
        assert set_cookie and "HttpOnly" in set_cookie and "access_token=" in set_cookie


# Credentialed CORS must reject an arbitrary origin instead of reflecting/wildcarding it.
def test_auth_cors_uses_explicit_trusted_origins(http_session):
    response = http_session.options(
        f"{API}/auth/me",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
        timeout=20,
    )
    allow_origin = response.headers.get("Access-Control-Allow-Origin")
    assert allow_origin not in ("*", "https://untrusted.example"), response.headers


# Five failed password attempts should lock further login attempts even with fresh valid captchas.
def test_auth_bruteforce_lockout_after_five_failures(http_session):
    statuses = []
    for _ in range(6):
        captcha_id, captcha_answer = _solve_captcha(http_session)
        response = http_session.post(
            f"{API}/auth/login",
            json={
                "identifier": "TEST_iter43_nonexistent_user",
                "password": "definitely-wrong-password",
                "captcha_id": captcha_id,
                "captcha_answer": captcha_answer,
            },
            timeout=30,
        )
        statuses.append(response.status_code)
    assert statuses[:4] == [401, 401, 401, 401], statuses
    assert 429 in statuses[4:], f"No lockout after five failures: {statuses}"
