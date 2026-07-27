"""Iteration 41 focused tests: mobile-dashboard support APIs, bonuses, payments, Discord, and auth hardening."""
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import bcrypt
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
    content = CREDS_PATH.read_text(encoding="utf-8")
    section_match = re.search(rf"(?ims)^##\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^##\s|\Z)", content)
    if not section_match:
        pytest.fail(f"Credential section missing: {section_name}")
    section = section_match.group(1)
    username = re.search(r"(?im)^\s*-\s*Username:\s*(.+?)\s*$", section)
    password = re.search(r"(?im)^\s*-\s*Password:\s*(.+?)\s*$", section)
    if not username or not password:
        pytest.fail(f"Credentials missing: {section_name}")
    return {"username": username.group(1).strip(), "password": password.group(1).strip()}


def _admin_secret() -> str:
    content = CREDS_PATH.read_text(encoding="utf-8")
    match = re.search(r'POST /api/admin/login-secret with \{"secret": "([^"]+)"\}', content)
    if not match:
        pytest.fail("Admin secret missing")
    return match.group(1)


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data["question"])
    assert match, data
    left, op, right = int(match.group(1)), match.group(2), int(match.group(3))
    answer = {"+": left + right, "-": left - right, "*": left * right}[op]
    return data["id"], str(answer)


def _login(session: requests.Session, credentials: dict, password: str | None = None):
    captcha_id, answer = _solve_captcha(session)
    return session.post(
        f"{API}/auth/login",
        json={
            "identifier": credentials["username"],
            "password": password if password is not None else credentials["password"],
            "captcha_id": captcha_id,
            "captcha_answer": answer,
        },
        timeout=20,
    )


@pytest.fixture(scope="module")
def session():
    value = requests.Session()
    value.headers.update({"Content-Type": "application/json"})
    yield value
    value.close()


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(BACKEND_ENV["MONGO_URL"], serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    yield client[BACKEND_ENV["DB_NAME"]]
    client.close()


@pytest.fixture(scope="module")
def contexts(session, mongo_db):
    admin = session.post(f"{API}/admin/login-secret", json={"secret": _admin_secret()}, timeout=20)
    assert admin.status_code == 200, admin.text
    admin_token = admin.json().get("token")
    assert isinstance(admin_token, str) and admin_token

    credentials = _credentials("Regular test user")
    login = _login(session, credentials)
    assert login.status_code == 200, login.text
    data = login.json()
    assert data.get("user", {}).get("username") == credentials["username"]
    user_doc = mongo_db.users.find_one({"id": data["user"]["id"]}, {"_id": 0, "password_hash": 0})
    assert user_doc
    return {
        "admin_headers": {"X-Admin-Token": admin_token},
        "user_headers": {"Authorization": f"Bearer {data['token']}"},
        "user": user_doc,
        "credentials": credentials,
    }


def _balance(session, headers) -> float:
    response = session.get(f"{API}/client/balance", headers=headers, timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("balance"), (int, float))
    return float(data["balance"])


# Bonus create -> pending -> recent gifts -> claim -> balance/status persistence.
def test_bonus_full_claim_workflow_and_recent_gifts(session, contexts, mongo_db):
    before = _balance(session, contexts["user_headers"])
    create = session.post(
        f"{API}/admin/bonuses/create",
        headers=contexts["admin_headers"],
        json={"user_ids": [contexts["user"]["id"]], "amount": 15},
        timeout=20,
    )
    assert create.status_code == 200, create.text
    create_data = create.json()
    assert create_data["ok"] is True and create_data["created"] == 1
    bonus_id = create_data["bonuses"][0]["id"]
    try:
        pending = session.get(f"{API}/client/bonuses/pending", headers=contexts["user_headers"], timeout=20)
        assert pending.status_code == 200, pending.text
        bonus = next((b for b in pending.json()["bonuses"] if b["id"] == bonus_id), None)
        assert bonus and bonus["amount"] == 15 and bonus["status"] == "pending"

        gifts = session.get(f"{API}/client/gifts/recent", headers=contexts["user_headers"], timeout=20)
        assert gifts.status_code == 200, gifts.text
        gift = next((g for g in gifts.json()["gifts"] if g["id"] == bonus_id), None)
        assert gift == {
            "kind": "balance_bonus", "id": bonus_id, "amount": 15.0,
            "status": "pending", "created_at": gift["created_at"],
        }

        claim = session.post(f"{API}/client/bonuses/{bonus_id}/claim", headers=contexts["user_headers"], timeout=20)
        assert claim.status_code == 200, claim.text
        assert claim.json().get("claimed") == 15.0
        assert _balance(session, contexts["user_headers"]) == pytest.approx(before + 15.0)

        listed = session.get(f"{API}/admin/bonuses", headers=contexts["admin_headers"], timeout=20)
        assert listed.status_code == 200, listed.text
        persisted = next((b for b in listed.json()["bonuses"] if b["id"] == bonus_id), None)
        assert persisted and persisted["status"] == "claimed" and persisted["amount"] == 15.0
    finally:
        mongo_db.transactions.delete_many({"bonus_id": bonus_id})
        mongo_db.balance_bonuses.delete_many({"id": bonus_id})


# Admin bonus amount validation and pending-expire persistence.
def test_bonus_validation_and_expire(session, contexts, mongo_db):
    invalid = session.post(
        f"{API}/admin/bonuses/create", headers=contexts["admin_headers"],
        json={"user_ids": [contexts["user"]["id"]], "amount": 4.99}, timeout=20,
    )
    assert invalid.status_code == 400, invalid.text
    assert "between €5 and €1000" in invalid.json().get("detail", "")

    create = session.post(
        f"{API}/admin/bonuses/create", headers=contexts["admin_headers"],
        json={"user_ids": [contexts["user"]["id"]], "amount": 5}, timeout=20,
    )
    assert create.status_code == 200, create.text
    bonus_id = create.json()["bonuses"][0]["id"]
    try:
        expire = session.post(f"{API}/admin/bonuses/{bonus_id}/expire", headers=contexts["admin_headers"], timeout=20)
        assert expire.status_code == 200 and expire.json() == {"ok": True}
        doc = mongo_db.balance_bonuses.find_one({"id": bonus_id}, {"_id": 0})
        assert doc["status"] == "expired" and doc["expired_by"] == "admin"
    finally:
        mongo_db.balance_bonuses.delete_many({"id": bonus_id})


# PayPal admin test links must select the requested PayPal environment.
@pytest.mark.parametrize("mode,host", [("sandbox", "www.sandbox.paypal.com"), ("live", "www.paypal.com")])
def test_paypal_test_urls(session, contexts, mode, host):
    response = session.post(
        f"{API}/admin/paypal-test", headers=contexts["admin_headers"],
        json={"mode": mode, "amount": 1}, timeout=20,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == mode
    parsed = urlparse(data["checkout_url"])
    assert parsed.scheme == "https" and parsed.netloc == host


# User PayPal checkout creates a pending transaction and valid hosted URL.
def test_paypal_checkout(session, contexts, mongo_db):
    response = session.post(
        f"{API}/client/funds/paypal-checkout", headers=contexts["user_headers"],
        json={"amount": 5}, timeout=20,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    tx_id = data.get("tx_id")
    try:
        assert isinstance(tx_id, str) and tx_id
        parsed = urlparse(data["checkout_url"])
        assert parsed.scheme == "https" and parsed.netloc in {"www.sandbox.paypal.com", "www.paypal.com"}
        tx = mongo_db.transactions.find_one({"id": tx_id}, {"_id": 0})
        assert tx and tx["amount"] == 5.0 and tx["status"] == "pending" and tx["user_id"] == contexts["user"]["id"]
    finally:
        if tx_id:
            mongo_db.transactions.delete_many({"id": tx_id})


# PayPal settings save and readback while preserving preview configuration.
def test_paypal_config_save(session, contexts, mongo_db):
    original = mongo_db.paypal_config.find_one({"_id": "singleton"})
    try:
        saved = session.post(
            f"{API}/admin/paypal-config", headers=contexts["admin_headers"],
            json={"receiver_email": "owner-test@example.com", "mode": "sandbox", "bonus_pct": 17}, timeout=20,
        )
        assert saved.status_code == 200 and saved.json() == {"ok": True}
        fetched = session.get(f"{API}/admin/paypal-config", headers=contexts["admin_headers"], timeout=20)
        assert fetched.status_code == 200
        assert fetched.json() == {
            "configured": True, "receiver_email": "owner-test@example.com", "mode": "sandbox", "bonus_pct": 17,
        }
    finally:
        if original is None:
            mongo_db.paypal_config.delete_one({"_id": "singleton"})
        else:
            mongo_db.paypal_config.replace_one({"_id": "singleton"}, original, upsert=True)


# NOWPayments accepts email/password-only update when an API key already exists.
def test_nowpayments_email_password_only_save(session, contexts, mongo_db):
    original = mongo_db.nowpayments_config.find_one({"_id": "singleton"})
    assert original and original.get("api_key"), "Preview must already have an API key for this regression"
    try:
        response = session.post(
            f"{API}/admin/nowpayments-config", headers=contexts["admin_headers"],
            json={"email": "test-nowpayments@example.com", "password": "TEST_password_only_41"}, timeout=20,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"configured": True}
        fetched = session.get(f"{API}/admin/nowpayments-config", headers=contexts["admin_headers"], timeout=20)
        assert fetched.status_code == 200, fetched.text
        data = fetched.json()
        assert data["configured"] is True and data["email"] == "test-nowpayments@example.com" and data["password_set"] is True
    finally:
        mongo_db.nowpayments_config.replace_one({"_id": "singleton"}, original, upsert=True)


# Discord status contract, welcomer persistence, offline servers/mass-DM safeguards.
def test_discord_welcome_status_and_offline_actions(session, contexts, mongo_db):
    original = mongo_db.discord_config.find_one({})
    welcome = {"enabled": True, "message": "TEST Welcome {user} to {server}!", "channel": "test-welcome"}
    try:
        save = session.post(f"{API}/admin/discord/welcome", headers=contexts["admin_headers"], json=welcome, timeout=20)
        assert save.status_code == 200 and save.json() == {"ok": True}
        status = session.get(f"{API}/admin/discord/status", headers=contexts["admin_headers"], timeout=20)
        assert status.status_code == 200, status.text
        data = status.json()
        assert data["saved_welcome"] == welcome
        assert "mass_dm" in data
        assert data["status"] == "stopped"

        servers = session.get(f"{API}/admin/discord/servers", headers=contexts["admin_headers"], timeout=20)
        assert servers.status_code == 409 and "not running" in servers.json().get("detail", "").lower()
        mass_dm = session.post(
            f"{API}/admin/discord/mass-dm", headers=contexts["admin_headers"],
            json={"text": "TEST offline guard"}, timeout=20,
        )
        assert mass_dm.status_code == 409 and mass_dm.json().get("detail") == "Bot is not running — start it first"
    finally:
        if original is None:
            mongo_db.discord_config.delete_many({})
        else:
            mongo_db.discord_config.replace_one({"_id": original["_id"]}, original, upsert=True)


# Stored owner password uses bcrypt $2b$ and the documented credential validates.
def test_owner_bcrypt_hash(contexts, mongo_db):
    owner = _credentials("Owner")
    doc = mongo_db.users.find_one({"username": owner["username"]}, {"_id": 0, "password_hash": 1})
    assert doc and doc["password_hash"].startswith("$2b$")
    assert bcrypt.checkpw(owner["password"].encode(), doc["password_hash"].encode())


# Security requirement: successful login should issue an HttpOnly auth cookie.
def test_login_sets_httponly_cookie(session, contexts):
    response = _login(session, contexts["credentials"])
    assert response.status_code == 200, response.text
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and ("access_token=" in cookie or "session_token=" in cookie), cookie


# Security requirement: repeated bad passwords must lock or rate-limit the account/IP after five failures.
def test_login_bruteforce_lockout_after_five_failures(session, contexts):
    statuses = []
    for _ in range(6):
        response = _login(session, contexts["credentials"], password="TEST_definitely_wrong_password")
        statuses.append(response.status_code)
    assert any(code == 429 for code in statuses[4:]), f"No lockout/rate limit after 6 invalid attempts: {statuses}"


# Credentialed CORS must enumerate trusted origins instead of wildcarding Access-Control-Allow-Origin.
def test_cors_credentials_uses_explicit_origin(session):
    response = session.options(
        f"{API}/auth/me",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
        timeout=20,
    )
    assert response.status_code in (200, 204), response.text
    assert response.headers.get("Access-Control-Allow-Origin") != "*"
    assert response.headers.get("Access-Control-Allow-Origin") != "https://untrusted.example"
