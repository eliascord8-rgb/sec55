"""Iteration 37: admin bulk/activity, PayPal, sports, and focused regression API tests."""
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
CREDENTIALS_PATH = Path("/app/memory/test_credentials.md")


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
    return data["id"], str({"+": left + right, "-": left - right, "*": left * right}[operator])


def _login(session: requests.Session, credentials: dict) -> dict:
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


@pytest.fixture(scope="session")
def http_session():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()


@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient(BACKEND_ENV["MONGO_URL"], serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    yield client[BACKEND_ENV["DB_NAME"]]
    client.close()


@pytest.fixture(scope="session")
def admin_headers(http_session):
    response = http_session.post(
        f"{API}/admin/login-secret", json={"secret": "haha123"}, timeout=20
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("token"), str) and data["token"]
    return {"X-Admin-Token": data["token"]}


@pytest.fixture(scope="session")
def user_auth(http_session):
    data = _login(http_session, _credentials_for("Regular test user"))
    return {
        "headers": {"Authorization": f"Bearer {data['token']}"},
        "user": data["user"],
    }


@pytest.fixture(scope="session")
def cleanup_tracker():
    return {
        "order_ids": [], "bet_ids": [], "paypal_tx_ids": [], "coupon_codes": [],
        "ticket_ids": [], "chat_ids": [], "transaction_ids": [],
    }


@pytest.fixture(scope="session", autouse=True)
def cleanup_created_records(mongo_db, cleanup_tracker):
    yield
    mongo_db.orders.delete_many({"id": {"$in": cleanup_tracker["order_ids"]}})
    mongo_db.bets.delete_many({"id": {"$in": cleanup_tracker["bet_ids"]}})
    mongo_db.transactions.delete_many({
        "$or": [
            {"id": {"$in": cleanup_tracker["transaction_ids"]}},
            {"bet_id": {"$in": cleanup_tracker["bet_ids"]}},
            {"id": {"$in": cleanup_tracker["paypal_tx_ids"]}},
            {"coupon_code": {"$in": cleanup_tracker["coupon_codes"]}},
            {"order_id": {"$in": cleanup_tracker["order_ids"]}},
        ]
    })
    mongo_db.coupons.delete_many({"code": {"$in": cleanup_tracker["coupon_codes"]}})
    mongo_db.tickets.delete_many({"id": {"$in": cleanup_tracker["ticket_ids"]}})
    mongo_db.ticket_messages.delete_many({"ticket_id": {"$in": cleanup_tracker["ticket_ids"]}})
    mongo_db.public_chat.delete_many({"id": {"$in": cleanup_tracker["chat_ids"]}})


# Admin order logs, full user dossier, and free manual bulk-gift dispatch.
class TestAdminOrderFeatures:
    def test_admin_orders_mixed_schema_is_usable(self, http_session, admin_headers):
        response = http_session.get(f"{API}/admin/orders", headers=admin_headers, timeout=30)
        assert response.status_code == 200, response.text
        data = response.json()
        assert "orders" in data and isinstance(data["orders"], list)
        assert data["orders"], "Expected seeded order records"
        assert all("_id" not in order for order in data["orders"])
        assert any(order.get("username") or order.get("ip") for order in data["orders"])
        assert any(
            order.get("service_name") or order.get("service_id") is not None
            for order in data["orders"]
        )
        assert any(
            any(order.get(field) is not None for field in ("total", "charge", "price_usd"))
            for order in data["orders"]
        )

    def test_user_activity_full_dossier(self, http_session, admin_headers, user_auth):
        user_id = user_auth["user"]["id"]
        response = http_session.get(
            f"{API}/admin/user-activity/{user_id}", headers=admin_headers, timeout=30
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert {
            "user", "totals", "orders", "transactions", "number_rentals",
            "live_subscriptions", "live_checks",
        }.issubset(data)
        assert data["user"]["id"] == user_id
        assert {"deposits_total", "orders_total_spent"}.issubset(data["totals"])
        assert isinstance(data["totals"]["deposits_total"], (int, float))
        assert isinstance(data["totals"]["orders_total_spent"], (int, float))
        for key in ("orders", "transactions", "number_rentals", "live_subscriptions", "live_checks"):
            assert isinstance(data[key], list)

    def test_bulk_manual_gift_and_missing_user_result(
        self, http_session, admin_headers, user_auth, cleanup_tracker
    ):
        payload = {
            "user_ids": [user_auth["user"]["id"], f"TEST_missing_{uuid.uuid4().hex}"],
            "services": [{"service_id": -1, "quantity": 1}],
            "link": "https://example.test/TEST_iter37_bulk",
            "note": "TEST_iter37 manual gift",
        }
        response = http_session.post(
            f"{API}/admin/bulk-order", headers=admin_headers, json=payload, timeout=30
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("ok") is True
        assert data.get("sent") == 1 and data.get("failed") == 1
        assert isinstance(data.get("results"), list) and len(data["results"]) == 2
        success = next(result for result in data["results"] if result.get("ok") is True)
        failure = next(result for result in data["results"] if result.get("ok") is False)
        assert success.get("manual") is True
        assert isinstance(success.get("order_id"), str) and success["order_id"]
        assert failure.get("error") == "user_not_found"
        cleanup_tracker["order_ids"].append(success["order_id"])

        fetched = http_session.get(f"{API}/admin/orders", headers=admin_headers, timeout=30)
        persisted = next(o for o in fetched.json()["orders"] if o.get("id") == success["order_id"])
        assert persisted["payment_method"] == "admin_gift"
        assert persisted["source"] == "admin_bulk"
        assert persisted["charge"] == 0.0 and persisted["user_id"] == user_auth["user"]["id"]

    def test_bulk_order_requires_admin_token(self, http_session, user_auth):
        response = http_session.post(
            f"{API}/admin/bulk-order",
            json={
                "user_ids": [user_auth["user"]["id"]],
                "services": [{"service_id": -1, "quantity": 1}],
                "link": "https://example.test/no-auth",
            },
            timeout=20,
        )
        assert response.status_code == 401
        assert "detail" in response.json()


# Hosted PayPal checkout supports either configured success or explicit 503.
class TestPayPalCheckout:
    def test_authenticated_checkout_contract(self, http_session, user_auth, cleanup_tracker):
        response = http_session.post(
            f"{API}/client/funds/paypal-checkout",
            headers=user_auth["headers"], json={"amount": 10}, timeout=20,
        )
        if response.status_code == 503:
            assert response.json().get("detail") == "PayPal deposits are not configured yet."
            return
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data.get("checkout_url"), str) and data["checkout_url"].startswith("https://www.paypal.com/")
        assert isinstance(data.get("tx_id"), str) and data["tx_id"]
        cleanup_tracker["paypal_tx_ids"].append(data["tx_id"])


# Public sports JSON and authenticated bet/cashout balance lifecycle.
class TestSportsFeatures:
    @pytest.mark.parametrize("path", ["livescores", "upcoming"])
    def test_public_match_feeds(self, http_session, path):
        response = http_session.get(f"{API}/sports/{path}", timeout=45)
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data, dict) and isinstance(data.get("matches"), list)

    def test_odds_contract(self, http_session):
        match_id = "TEST-iter37-match"
        response = http_session.get(f"{API}/sports/odds/{match_id}", timeout=20)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("match_id") == match_id
        assert {"home", "draw", "away"}.issubset(data.get("markets", {}).get("1X2", {}))

    def test_place_and_cashout_deducts_then_refunds_85_percent(
        self, http_session, user_auth, cleanup_tracker
    ):
        balance_before = http_session.get(
            f"{API}/client/balance", headers=user_auth["headers"], timeout=20
        ).json()["balance"]
        payload = {
            "stake": 0.10,
            "selections": [{
                "match_id": "TEST-iter37-match",
                "match_label": "TEST Home vs TEST Away",
                "market": "1X2",
                "selection": "home",
                "odds": 2.10,
            }],
        }
        placed = http_session.post(
            f"{API}/client/sports/bet", headers=user_auth["headers"], json=payload, timeout=20
        )
        assert placed.status_code == 200, placed.text
        bet = placed.json()["bet"]
        cleanup_tracker["bet_ids"].append(bet["id"])
        assert bet["stake"] == pytest.approx(0.10) and bet["status"] == "open"
        assert placed.json()["new_balance"] == pytest.approx(balance_before - 0.10)

        after_place = http_session.get(
            f"{API}/client/balance", headers=user_auth["headers"], timeout=20
        ).json()["balance"]
        assert after_place == pytest.approx(balance_before - 0.10)

        cashed = http_session.post(
            f"{API}/client/sports/bet/{bet['id']}/cashout", headers=user_auth["headers"], timeout=20
        )
        assert cashed.status_code == 200, cashed.text
        assert cashed.json()["rate"] == pytest.approx(0.85)
        assert cashed.json()["refund"] == pytest.approx(0.09)
        after_cashout = http_session.get(
            f"{API}/client/balance", headers=user_auth["headers"], timeout=20
        ).json()["balance"]
        assert after_cashout == pytest.approx(balance_before - 0.01)


# Focused regression checks for transaction history, coupon, order, live chat, and tickets.
class TestFocusedRegressions:
    def test_transactions_list(self, http_session, user_auth):
        response = http_session.get(
            f"{API}/client/transactions", headers=user_auth["headers"], timeout=20
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json().get("transactions"), list)

    def test_coupon_redemption(self, http_session, admin_headers, user_auth, cleanup_tracker):
        created = http_session.post(
            f"{API}/admin/coupons", headers=admin_headers,
            json={"amount": 0.11, "note": "TEST_iter37 regression"}, timeout=20,
        )
        assert created.status_code == 200, created.text
        code = created.json()["code"]
        cleanup_tracker["coupon_codes"].append(code)
        redeemed = http_session.post(
            f"{API}/client/redeem-coupon", headers=user_auth["headers"],
            json={"code": code}, timeout=20,
        )
        assert redeemed.status_code == 200, redeemed.text
        assert redeemed.json().get("ok") is True and redeemed.json().get("amount") == pytest.approx(0.11)

    def test_manual_order_placement(
        self, http_session, user_auth, cleanup_tracker, mongo_db
    ):
        marker = "https://example.test/TEST_iter37_order"
        before_tx_ids = {
            tx["id"] for tx in mongo_db.transactions.find(
                {"user_id": user_auth["user"]["id"]}, {"_id": 0, "id": 1}
            )
        }
        response = http_session.post(
            f"{API}/client/order-with-balance", headers=user_auth["headers"],
            json={
                "service_id": -1,
                "link": marker,
                "quantity": 1,
            }, timeout=30,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("ok") is True and data.get("manual") is True
        listed = http_session.get(f"{API}/client/orders", headers=user_auth["headers"], timeout=20)
        assert listed.status_code == 200, listed.text
        order = next(
            item for item in listed.json().get("orders", [])
            if item.get("link") == marker and item.get("service_id") == -1
        )
        assert isinstance(order.get("id"), str) and order["id"]
        assert order.get("status") == "awaiting_manual_fulfillment"
        cleanup_tracker["order_ids"].append(order["id"])
        after_txs = list(mongo_db.transactions.find(
            {"user_id": user_auth["user"]["id"], "id": {"$nin": list(before_tx_ids)}},
            {"_id": 0, "id": 1},
        ))
        cleanup_tracker["transaction_ids"].extend(tx["id"] for tx in after_txs)

    def test_requested_post_client_orders_route_exists(self, http_session, user_auth):
        response = http_session.post(
            f"{API}/client/orders", headers=user_auth["headers"],
            json={
                "service_id": -1,
                "link": "https://example.test/TEST_iter37_post_orders",
                "quantity": 1,
            }, timeout=20,
        )
        assert response.status_code != 405, "POST /api/client/orders is not registered"

    def test_live_chat_send(self, http_session, user_auth, cleanup_tracker, mongo_db):
        marker = f"TEST_iter37_chat_{uuid.uuid4().hex[:10]}"
        response = http_session.post(
            f"{API}/public-chat/send", headers=user_auth["headers"], json={"text": marker}, timeout=20
        )
        assert response.status_code == 200, response.text
        assert response.json().get("ok") is True
        record = mongo_db.public_chat.find_one({"text": marker}, {"_id": 0})
        assert record and record.get("user_id") == user_auth["user"]["id"]
        cleanup_tracker["chat_ids"].append(record["id"])

    def test_ticket_create_and_list(self, http_session, user_auth, cleanup_tracker):
        marker = f"TEST_iter37_ticket_{uuid.uuid4().hex[:10]}"
        response = http_session.post(
            f"{API}/client/tickets", headers=user_auth["headers"],
            json={"subject": marker, "message": "TEST iteration 37 support flow"}, timeout=20,
        )
        assert response.status_code == 200, response.text
        ticket_id = response.json().get("id")
        assert response.json().get("ok") is True and isinstance(ticket_id, str)
        cleanup_tracker["ticket_ids"].append(ticket_id)
        listed = http_session.get(f"{API}/client/tickets", headers=user_auth["headers"], timeout=20)
        assert listed.status_code == 200, listed.text
        assert any(ticket.get("id") == ticket_id for ticket in listed.json().get("tickets", []))
