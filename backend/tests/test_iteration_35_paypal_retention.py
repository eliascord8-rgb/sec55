"""Iteration 35: PayPal IPN/config/checkout and chat-retention backend tests."""
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
CREDENTIALS_PATH = Path("/app/memory/test_credentials.md")
MONGO_URL = BACKEND_ENV.get("MONGO_URL")
DB_NAME = BACKEND_ENV.get("DB_NAME")


def _credentials_for(section_name: str) -> dict:
    content = CREDENTIALS_PATH.read_text(encoding="utf-8")
    section_match = re.search(
        rf"(?ims)^##\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^##\s|\Z)", content
    )
    if not section_match:
        pytest.fail(f"Credential section not found: {section_name}")
    section = section_match.group(1)
    username = re.search(r"(?im)^\s*-\s*Username:\s*(.+?)\s*$", section)
    password = re.search(r"(?im)^\s*-\s*Password:\s*(.+?)\s*$", section)
    if not username or not password:
        pytest.fail(f"Username/password missing in credential section: {section_name}")
    return {"username": username.group(1).strip(), "password": password.group(1).strip()}


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data["question"])
    assert match, data
    left, operator, right = int(match.group(1)), match.group(2), int(match.group(3))
    answer = {"+": left + right, "-": left - right, "*": left * right}[operator]
    return data["id"], str(answer)


def _login(session: requests.Session, credentials: dict) -> requests.Response:
    captcha_id, captcha_answer = _solve_captcha(session)
    return session.post(
        f"{API}/auth/login",
        json={
            "identifier": credentials["username"],
            "password": credentials["password"],
            "captcha_id": captcha_id,
            "captcha_answer": captcha_answer,
        },
        timeout=20,
    )


@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="session")
def http_session():
    session = requests.Session()
    yield session
    session.close()


@pytest.fixture(scope="session")
def owner_credentials():
    return _credentials_for("Owner")


@pytest.fixture(scope="session")
def regular_credentials():
    return _credentials_for("Regular test user")


@pytest.fixture(scope="session")
def owner_auth(http_session, owner_credentials):
    login_response = _login(http_session, owner_credentials)
    assert login_response.status_code == 200, login_response.text
    login_data = login_response.json()
    assert login_data.get("user", {}).get("role") == "owner"
    assert isinstance(login_data.get("token"), str) and login_data["token"]
    exchange = http_session.post(
        f"{API}/admin/session-from-user",
        headers={"Authorization": f"Bearer {login_data['token']}"},
        timeout=20,
    )
    assert exchange.status_code == 200, exchange.text
    exchange_data = exchange.json()
    assert exchange_data.get("role") == "owner"
    assert isinstance(exchange_data.get("token"), str) and exchange_data["token"]
    return {
        "admin_headers": {"X-Admin-Token": exchange_data["token"]},
        "login_response": login_response,
    }


@pytest.fixture(scope="session")
def user_auth(http_session, regular_credentials, mongo_db):
    response = _login(http_session, regular_credentials)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("user", {}).get("username", "").lower() == regular_credentials["username"].lower()
    assert isinstance(data.get("token"), str) and data["token"]
    user = mongo_db.users.find_one(
        {"username": {"$regex": f"^{re.escape(regular_credentials['username'])}$", "$options": "i"}},
        {"_id": 0, "id": 1},
    )
    assert user and user.get("id")
    return {"headers": {"Authorization": f"Bearer {data['token']}"}, "user_id": user["id"]}


@pytest.fixture(scope="session", autouse=True)
def paypal_config_guard(mongo_db):
    original = mongo_db.paypal_config.find_one({"_id": "singleton"})
    mongo_db.paypal_config.update_one(
        {"_id": "singleton"},
        {"$set": {"receiver_email": "test@example.com", "mode": "sandbox", "bonus_pct": 10}},
        upsert=True,
    )
    yield
    if original is None:
        mongo_db.paypal_config.delete_one({"_id": "singleton"})
    else:
        replacement = dict(original)
        mongo_db.paypal_config.replace_one({"_id": "singleton"}, replacement, upsert=True)


# Admin PayPal config and duplicate-route regression.
class TestPayPalConfig:
    def test_get_and_post_config_persist(self, http_session, owner_auth):
        headers = owner_auth["admin_headers"]
        initial = http_session.get(f"{API}/admin/paypal-config", headers=headers, timeout=20)
        assert initial.status_code == 200, initial.text
        assert set(initial.json()) == {"configured", "receiver_email", "mode", "bonus_pct"}

        saved = http_session.post(
            f"{API}/admin/paypal-config",
            headers=headers,
            json={"receiver_email": "test@example.com", "mode": "sandbox", "bonus_pct": 10},
            timeout=20,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"ok": True}

        fetched = http_session.get(f"{API}/admin/paypal-config", headers=headers, timeout=20)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json() == {
            "configured": True,
            "receiver_email": "test@example.com",
            "mode": "sandbox",
            "bonus_pct": 10,
        }

    def test_new_admin_config_route_registered_once_per_method(self):
        sys.path.insert(0, "/app/backend")
        import server

        matches = [(route.path, tuple(sorted(route.methods or []))) for route in server.app.routes if route.path == "/api/admin/paypal-config"]
        assert len(matches) == 2, matches
        assert sorted(methods for _, methods in matches) == [("GET",), ("POST",)]


# Authenticated hosted PayPal checkout URL and unconfigured behavior.
class TestPayPalCheckout:
    def test_checkout_url_and_pending_transaction(self, http_session, user_auth, mongo_db):
        response = http_session.post(
            f"{API}/client/funds/paypal-checkout",
            headers=user_auth["headers"],
            json={"amount": 10},
            timeout=20,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data.get("tx_id"), str) and data["tx_id"]
        tx_id = data["tx_id"]
        try:
            assert data["checkout_url"].startswith("https://www.sandbox.paypal.com/cgi-bin/webscr?")
            query = parse_qs(urlparse(data["checkout_url"]).query)
            assert query["business"] == ["test@example.com"]
            assert query["amount"] == ["10.00"]
            assert query["custom"] == [f"{user_auth['user_id']}|{tx_id}"]
            assert query["notify_url"] == [f"{BASE_URL}/api/paypal/ipn"]
            tx = mongo_db.transactions.find_one({"id": tx_id}, {"_id": 0})
            assert tx is not None
            assert tx["user_id"] == user_auth["user_id"]
            assert tx["method"] == "paypal" and tx["status"] == "pending" and tx["amount"] == 10.0
        finally:
            mongo_db.transactions.delete_one({"id": tx_id})

    def test_checkout_returns_503_when_not_configured(self, http_session, user_auth, mongo_db):
        mongo_db.paypal_config.update_one({"_id": "singleton"}, {"$set": {"receiver_email": ""}})
        try:
            response = http_session.post(
                f"{API}/client/funds/paypal-checkout",
                headers=user_auth["headers"],
                json={"amount": 10},
                timeout=20,
            )
            assert response.status_code == 503, response.text
            assert response.json().get("detail") == "PayPal deposits are not configured yet."
        finally:
            mongo_db.paypal_config.update_one(
                {"_id": "singleton"},
                {"$set": {"receiver_email": "test@example.com", "mode": "sandbox", "bonus_pct": 10}},
            )


# Public IPN must acknowledge invalid payloads and persist verification results.
class TestPayPalIPN:
    def test_unverified_ipn_returns_200_and_writes_event(self, http_session, user_auth, mongo_db):
        paypal_txn = f"TEST_INVALID_{uuid.uuid4()}"
        payload = {
            "payment_status": "Completed",
            "receiver_email": "test@example.com",
            "txn_id": paypal_txn,
            "mc_gross": "10.00",
            "mc_currency": "USD",
            "custom": f"{user_auth['user_id']}|TEST_missing_tx",
        }
        response = http_session.post(f"{API}/paypal/ipn", data=payload, timeout=30)
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True}
        event = mongo_db.paypal_events.find_one({"txn_id": paypal_txn}, {"_id": 0})
        assert event is not None
        assert event["verified"] is False
        assert event["payment_status"] == "Completed"
        assert event["receiver_email"] == "test@example.com"
        mongo_db.paypal_events.delete_many({"txn_id": paypal_txn})

    def test_malformed_unverified_gross_still_returns_200(self, http_session, mongo_db):
        paypal_txn = f"TEST_BAD_GROSS_{uuid.uuid4()}"
        response = http_session.post(
            f"{API}/paypal/ipn",
            data={"payment_status": "Completed", "txn_id": paypal_txn, "mc_gross": "not-a-number"},
            timeout=30,
        )
        try:
            assert response.status_code == 200, response.text
            assert response.json().get("ok") is True
        finally:
            mongo_db.paypal_events.delete_many({"txn_id": paypal_txn})

    def test_verified_wrong_receiver_does_not_credit(self, user_auth, mongo_db, monkeypatch):
        sys.path.insert(0, "/app/backend")
        import server

        server.client = server.AsyncIOMotorClient(MONGO_URL)
        server.db = server.client[DB_NAME]
        server.app.state.db = server.db
        our_tx_id = f"TEST_WRONG_RECEIVER_{uuid.uuid4()}"
        paypal_txn = f"TEST_PAYPAL_{uuid.uuid4()}"
        mongo_db.transactions.insert_one({
            "id": our_tx_id,
            "user_id": user_auth["user_id"],
            "username": "testbugfix1",
            "amount": 10.0,
            "method": "paypal",
            "status": "pending",
            "type": "deposit",
            "created_at": "2026-07-25T00:00:00+00:00",
        })
        form = {
            "payment_status": "Completed",
            "receiver_email": "wrong@example.com",
            "txn_id": paypal_txn,
            "mc_gross": "10.00",
            "mc_currency": "USD",
            "custom": f"{user_auth['user_id']}|{our_tx_id}",
        }

        class FakeRequest:
            async def body(self):
                return b"payment_status=Completed"

            async def form(self):
                return form

        class FakeResponse:
            text = "VERIFIED"

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
        result = asyncio.run(server.paypal_ipn(FakeRequest()))
        try:
            assert result == {"ok": True}
            tx = mongo_db.transactions.find_one({"id": our_tx_id}, {"_id": 0})
            assert tx["status"] == "pending"
            assert "paypal_txn_id" not in tx
            event = mongo_db.paypal_events.find_one({"txn_id": paypal_txn}, {"_id": 0})
            assert event is not None and event["verified"] is True
            assert not mongo_db.transactions.find_one({"linked_tx_id": our_tx_id})
        finally:
            mongo_db.transactions.delete_many({"$or": [{"id": our_tx_id}, {"linked_tx_id": our_tx_id}]})
            mongo_db.paypal_events.delete_many({"txn_id": paypal_txn})

    def test_verified_unknown_pending_transaction_must_not_create_bonus(self, user_auth, mongo_db, monkeypatch):
        sys.path.insert(0, "/app/backend")
        import server

        server.client = server.AsyncIOMotorClient(MONGO_URL)
        server.db = server.client[DB_NAME]
        server.app.state.db = server.db
        missing_tx_id = f"TEST_MISSING_{uuid.uuid4()}"
        paypal_txn = f"TEST_ORPHAN_{uuid.uuid4()}"
        form = {
            "payment_status": "Completed",
            "receiver_email": "test@example.com",
            "txn_id": paypal_txn,
            "mc_gross": "10.00",
            "mc_currency": "USD",
            "custom": f"{user_auth['user_id']}|{missing_tx_id}",
        }

        class FakeRequest:
            async def body(self):
                return b"payment_status=Completed"

            async def form(self):
                return form

        class FakeResponse:
            text = "VERIFIED"

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
        result = asyncio.run(server.paypal_ipn(FakeRequest()))
        try:
            bonus = mongo_db.transactions.find_one({"linked_tx_id": missing_tx_id}, {"_id": 0})
            assert result == {"ok": True}
            assert bonus is None, f"Orphan bonus was credited without a matching pending deposit: {bonus}"
        finally:
            mongo_db.transactions.delete_many({"linked_tx_id": missing_tx_id})
            mongo_db.paypal_events.delete_many({"txn_id": paypal_txn})


# Retention loop behavior and startup worker registration/import smoke.
class TestRetentionAndStartup:
    def test_retention_loop_deletes_only_messages_older_than_30_days(self, mongo_db, monkeypatch):
        sys.path.insert(0, "/app/backend")
        import server

        server.client = server.AsyncIOMotorClient(MONGO_URL)
        server.db = server.client[DB_NAME]
        server.app.state.db = server.db
        marker = f"TEST_RETENTION_{uuid.uuid4()}"
        old_time = "2026-01-01T00:00:00+00:00"
        recent_time = "2999-01-01T00:00:00+00:00"
        collections = [mongo_db.public_chat, mongo_db.ai_chat_messages, mongo_db.direct_messages]
        for collection in collections:
            collection.insert_many([
                {"id": f"{marker}_old", "created_at": old_time},
                {"id": f"{marker}_recent", "created_at": recent_time},
            ])

        calls = 0

        async def run_once_sleep(_seconds):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(server.asyncio, "sleep", run_once_sleep)
        try:
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(server._chat_retention_loop())
            for collection in collections:
                assert collection.find_one({"id": f"{marker}_old"}) is None
                assert collection.find_one({"id": f"{marker}_recent"}) is not None
        finally:
            for collection in collections:
                collection.delete_many({"id": {"$regex": f"^{marker}"}})

    def test_startup_workers_registered_and_notification_imports(self):
        sys.path.insert(0, "/app/backend")
        import notification_service
        import server

        assert callable(notification_service.notify_deposit_credited)
        source = Path("/app/backend/server.py").read_text(encoding="utf-8")
        for worker_call in (
            "asyncio.create_task(_live_sub_worker_loop())",
            "asyncio.create_task(_sports_watcher_loop())",
            "asyncio.create_task(_nowpayments_reconciler_loop())",
            "asyncio.create_task(_chat_retention_loop())",
        ):
            assert worker_call in source
        assert any(getattr(route, "path", None) == "/api/" for route in server.app.routes)

    def test_owner_hash_and_seed_sync_requirement(self, owner_credentials, mongo_db):
        owner = mongo_db.users.find_one(
            {"username": owner_credentials["username"]}, {"_id": 0, "password_hash": 1}
        )
        assert owner and owner["password_hash"].startswith("$2b$")
        assert bcrypt.checkpw(owner_credentials["password"].encode(), owner["password_hash"].encode())
        source = Path("/app/backend/auth_and_chat.py").read_text(encoding="utf-8")
        assert "elif not verify_password(password, existing.get(\"password_hash\", \"\")):" in source
        assert '"$set": {"password_hash": hash_password(password)' in source
