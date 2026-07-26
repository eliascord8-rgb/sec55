"""Iteration 38: focused multi-service order API and single-order regression tests."""
import os
import re
import time
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
CREDENTIALS_PATH = Path("/app/memory/test_credentials.md")
VALID_LINK = "https://www.tiktok.com/@tiktok/live"
AUTOMATED_SERVICE_ID = 7242
AUTOMATED_QUANTITY = 50
MANUAL_SERVICE_ID = -1


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


def _admin_secret() -> str:
    content = CREDENTIALS_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?m)^- Or POST /api/admin/login-secret with \{\"secret\": \"([^\"]+)\"\}", content)
    if not match:
        pytest.fail("Admin secret missing from test credentials")
    return match.group(1)


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data["question"])
    assert match, data
    left, operator, right = int(match.group(1)), match.group(2), int(match.group(3))
    return data["id"], str({"+": left + right, "-": left - right, "*": left * right}[operator])


def _login(session: requests.Session) -> dict:
    credentials = _credentials_for("Regular test user")
    captcha_id, captcha_answer = _solve_captcha(session)
    response = session.post(
        f"{API}/auth/login",
        json={
            "identifier": credentials["username"],
            "password": credentials["password"],
            "captcha_id": captcha_id,
            "captcha_answer": captcha_answer,
        },
        timeout=20,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("token"), str) and data["token"]
    assert data.get("user", {}).get("username", "").lower() == credentials["username"].lower()
    return data


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
def user_auth(http_session):
    data = _login(http_session)
    return {
        "headers": {"Authorization": f"Bearer {data['token']}"},
        "user": data["user"],
    }


@pytest.fixture(scope="module")
def admin_headers(http_session):
    response = http_session.post(
        f"{API}/admin/login-secret", json={"secret": _admin_secret()}, timeout=20
    )
    assert response.status_code == 200, response.text
    return {"X-Admin-Token": response.json()["token"]}


@pytest.fixture(scope="module")
def test_context(http_session, mongo_db, user_auth, admin_headers):
    uid = user_auth["user"]["id"]
    marker = f"TEST_iter38_{uuid.uuid4().hex[:10]}"
    existing_tx_ids = {
        tx["id"] for tx in mongo_db.transactions.find({"user_id": uid, "id": {"$exists": True}}, {"id": 1})
    }
    existing_order_ids = {
        order["id"] for order in mongo_db.orders.find({"user_id": uid, "id": {"$exists": True}}, {"id": 1})
    }
    balance_response = http_session.get(f"{API}/client/balance", headers=user_auth["headers"], timeout=20)
    assert balance_response.status_code == 200, balance_response.text
    balance = float(balance_response.json()["balance"])
    if balance < 40:
        credit = http_session.post(
            f"{API}/admin/users/{uid}/adjust-balance",
            headers=admin_headers,
            json={"amount": round(40 - balance, 2), "reason": "TEST_iter38_credit", "note": marker},
            timeout=20,
        )
        assert credit.status_code == 200, credit.text

    context = {
        "marker": marker,
        "uid": uid,
        "existing_tx_ids": existing_tx_ids,
        "existing_order_ids": existing_order_ids,
    }
    yield context

    mongo_db.orders.delete_many({
        "user_id": uid,
        "id": {"$nin": list(existing_order_ids)},
        "$or": [
            {"source": "dashboard_multi"},
            {"link": {"$regex": marker}},
        ],
    })
    mongo_db.transactions.delete_many({
        "user_id": uid,
        "id": {"$nin": list(existing_tx_ids)},
        "$or": [
            {"type": "order", "service_id": {"$in": [AUTOMATED_SERVICE_ID, MANUAL_SERVICE_ID]}},
            {"type": "TEST_iter38_credit"},
            {"note": marker},
        ],
    })
    mongo_db.curated_services.delete_many({"test_marker": marker})


# Multi-order request validation and preflight rejection must not charge or create orders.
class TestMultiOrderValidation:
    def test_zero_items_returns_422(self, http_session, user_auth):
        response = http_session.post(
            f"{API}/client/orders/multi",
            headers=user_auth["headers"],
            json={"link": VALID_LINK, "items": []},
            timeout=20,
        )
        assert response.status_code == 422, response.text
        assert isinstance(response.json().get("detail"), list)

    def test_twenty_items_returns_422(self, http_session, user_auth):
        response = http_session.post(
            f"{API}/client/orders/multi",
            headers=user_auth["headers"],
            json={
                "link": VALID_LINK,
                "items": [{"service_id": MANUAL_SERVICE_ID, "quantity": 1}] * 20,
            },
            timeout=20,
        )
        assert response.status_code == 422, response.text
        assert isinstance(response.json().get("detail"), list)

    def test_unknown_service_rejects_whole_request_without_charge(
        self, http_session, mongo_db, user_auth, test_context
    ):
        uid = test_context["uid"]
        unknown_id = 2_000_000_000
        tx_before = mongo_db.transactions.count_documents({"user_id": uid})
        orders_before = mongo_db.orders.count_documents({"user_id": uid})
        balance_before = http_session.get(
            f"{API}/client/balance", headers=user_auth["headers"], timeout=20
        ).json()["balance"]
        response = http_session.post(
            f"{API}/client/orders/multi",
            headers=user_auth["headers"],
            json={
                "link": VALID_LINK,
                "items": [
                    {"service_id": MANUAL_SERVICE_ID, "quantity": 1},
                    {"service_id": unknown_id, "quantity": 1},
                ],
            },
            timeout=20,
        )
        assert response.status_code == 404, response.text
        assert response.json().get("detail") == f"Service #{unknown_id} not available"
        assert mongo_db.transactions.count_documents({"user_id": uid}) == tx_before
        assert mongo_db.orders.count_documents({"user_id": uid}) == orders_before
        balance_after = http_session.get(
            f"{API}/client/balance", headers=user_auth["headers"], timeout=20
        ).json()["balance"]
        assert balance_after == pytest.approx(balance_before)

    def test_insufficient_balance_returns_402_without_charge(
        self, http_session, mongo_db, user_auth, test_context
    ):
        uid = test_context["uid"]
        marker = test_context["marker"]
        balance_before = http_session.get(
            f"{API}/client/balance", headers=user_auth["headers"], timeout=20
        ).json()["balance"]
        expensive_id = -int(time.time())
        mongo_db.curated_services.insert_one({
            "service_id": expensive_id,
            "name": "TEST Iter38 Expensive Manual",
            "custom_name": "TEST Iter38 Expensive Manual",
            "category": "TEST",
            "enabled": True,
            "manual": True,
            "price_flat": round(float(balance_before) + 10, 2),
            "min": 1,
            "max": 1,
            "test_marker": marker,
        })
        tx_before = mongo_db.transactions.count_documents({"user_id": uid})
        orders_before = mongo_db.orders.count_documents({"user_id": uid})
        response = http_session.post(
            f"{API}/client/orders/multi",
            headers=user_auth["headers"],
            json={"link": VALID_LINK, "items": [{"service_id": expensive_id, "quantity": 1}]},
            timeout=20,
        )
        assert response.status_code == 402, response.text
        assert "Not enough balance" in response.json().get("detail", "")
        assert mongo_db.transactions.count_documents({"user_id": uid}) == tx_before
        assert mongo_db.orders.count_documents({"user_id": uid}) == orders_before

    def test_custom_text_service_requires_comments(
        self, http_session, mongo_db, user_auth, test_context
    ):
        marker = test_context["marker"]
        custom_id = -int(time.time()) - 1
        mongo_db.curated_services.insert_one({
            "service_id": custom_id,
            "name": "TEST Iter38 Custom Text",
            "custom_name": "TEST Iter38 Custom Text",
            "category": "TEST",
            "enabled": True,
            "manual": True,
            "price_flat": 0.01,
            "min": 1,
            "max": 1,
            "needs_custom_text": True,
            "test_marker": marker,
        })
        response = http_session.post(
            f"{API}/client/orders/multi",
            headers=user_auth["headers"],
            json={
                "link": VALID_LINK,
                "items": [{"service_id": custom_id, "quantity": 1, "comments": "   "}],
            },
            timeout=20,
        )
        assert response.status_code == 400, response.text
        assert "needs custom comments" in response.json().get("detail", "")


# A successful two-service dispatch persists two tagged orders and two matching debits.
class TestMultiOrderPlacement:
    def test_automated_plus_manual_order_success(
        self, http_session, mongo_db, user_auth, test_context
    ):
        uid = test_context["uid"]
        marker_link = f"{VALID_LINK}?ref={test_context['marker']}"
        before_tx_ids = {
            tx["id"] for tx in mongo_db.transactions.find({"user_id": uid, "id": {"$exists": True}}, {"id": 1})
        }
        response = http_session.post(
            f"{API}/client/orders/multi",
            headers=user_auth["headers"],
            json={
                "link": marker_link,
                "items": [
                    {"service_id": AUTOMATED_SERVICE_ID, "quantity": AUTOMATED_QUANTITY},
                    {"service_id": MANUAL_SERVICE_ID, "quantity": 1},
                ],
            },
            timeout=60,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("ok") is True
        assert data.get("placed") == 2 and data.get("failed") == 0
        assert isinstance(data.get("total_charged"), (int, float)) and data["total_charged"] > 0
        assert isinstance(data.get("balance"), (int, float))
        assert isinstance(data.get("order_ids"), list) and len(data["order_ids"]) == 2
        assert isinstance(data.get("results"), list) and len(data["results"]) == 2
        assert all(result.get("ok") is True for result in data["results"])

        orders = list(mongo_db.orders.find(
            {"id": {"$in": data["order_ids"]}}, {"_id": 0}
        ))
        assert len(orders) == 2
        assert all(order.get("source") == "dashboard_multi" for order in orders)
        assert all(order.get("multi_batch") is True for order in orders)
        assert {order["service_id"] for order in orders} == {AUTOMATED_SERVICE_ID, MANUAL_SERVICE_ID}
        assert all(order.get("user_id") == uid for order in orders)

        debits = list(mongo_db.transactions.find(
            {
                "user_id": uid,
                "id": {"$nin": list(before_tx_ids)},
                "type": "order",
                "amount": {"$lt": 0},
            },
            {"_id": 0},
        ))
        assert len(debits) == 2
        assert {tx["service_id"] for tx in debits} == {AUTOMATED_SERVICE_ID, MANUAL_SERVICE_ID}
        assert sum(-float(tx["amount"]) for tx in debits) == pytest.approx(data["total_charged"])


# Existing single-service balance checkout remains functional.
class TestSingleOrderRegression:
    def test_single_manual_order_still_works(
        self, http_session, mongo_db, user_auth, test_context
    ):
        marker_link = f"https://example.test/{test_context['marker']}_single"
        response = http_session.post(
            f"{API}/client/order-with-balance",
            headers=user_auth["headers"],
            json={"service_id": MANUAL_SERVICE_ID, "link": marker_link, "quantity": 1},
            timeout=30,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("ok") is True and data.get("manual") is True
        assert data.get("charge") == pytest.approx(15.99)
        order = mongo_db.orders.find_one({"user_id": test_context["uid"], "link": marker_link}, {"_id": 0})
        assert order and order.get("source") == "dashboard"
        assert order.get("status") == "awaiting_manual_fulfillment"
