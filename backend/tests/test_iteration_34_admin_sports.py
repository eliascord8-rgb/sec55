"""Iteration 34: admin order/activity, sports betting, and owner auth smoke tests."""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
    a, operation, b = int(match.group(1)), match.group(2), int(match.group(3))
    answer = {"+": a + b, "-": a - b, "*": a * b}[operation]
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
def http_session():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


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
    assert isinstance(login_data.get("token"), str) and login_data["token"]
    assert login_data.get("user", {}).get("role") == "owner"
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
        "user_token": login_data["token"],
        "admin_token": exchange_data["token"],
        "exchange": exchange_data,
        "login_response": login_response,
    }


@pytest.fixture(scope="session")
def user_auth(http_session, regular_credentials):
    response = _login(http_session, regular_credentials)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("user", {}).get("username", "").lower() == regular_credentials["username"].lower()
    assert isinstance(data.get("token"), str) and data["token"]
    return {"Authorization": f"Bearer {data['token']}"}


@pytest.fixture(scope="session")
def admin_headers(owner_auth):
    return {"X-Admin-Token": owner_auth["admin_token"]}


@pytest.fixture(scope="session")
def admin_users(http_session, admin_headers):
    response = http_session.get(f"{API}/admin/users", headers=admin_headers, timeout=30)
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("users"), list) and data["users"], data
    assert data.get("count") == len(data["users"])
    return data["users"]


# Owner login and owner-to-admin token exchange.
class TestAdminAuthFlow:
    def test_owner_session_exchange(self, owner_auth, owner_credentials):
        data = owner_auth["exchange"]
        assert data["role"] == "owner"
        assert data["username"].lower() == owner_credentials["username"].lower()
        assert "all" in data.get("perms", [])

    def test_owner_password_hash_is_bcrypt_2b(self, owner_credentials):
        mongo_url = BACKEND_ENV.get("MONGO_URL")
        db_name = BACKEND_ENV.get("DB_NAME")
        assert mongo_url and db_name
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        try:
            user = client[db_name].users.find_one(
                {"username": owner_credentials["username"]}, {"password_hash": 1}
            )
            assert user and isinstance(user.get("password_hash"), str)
            assert user["password_hash"].startswith("$2b$")
            assert bcrypt.checkpw(
                owner_credentials["password"].encode(), user["password_hash"].encode()
            )
        finally:
            client.close()


# Admin order log and per-user activity dossier.
class TestAdminHistory:
    def test_admin_orders_record_structure(self, http_session, admin_headers):
        response = http_session.get(f"{API}/admin/orders", headers=admin_headers, timeout=30)
        assert response.status_code == 200, response.text
        orders = response.json().get("orders")
        assert isinstance(orders, list) and orders, "Expected at least one admin order record"
        assert all("_id" not in order for order in orders)
        qualifying = [
            order
            for order in orders
            if order.get("user_id")
            and (order.get("service_name") is not None or order.get("service_id") is not None)
            and any(order.get(field) is not None for field in ("total", "charge", "price_usd"))
        ]
        assert qualifying, f"No user order has the required structure; sample={orders[0]}"
        order = qualifying[0]
        for field in ("id", "user_id", "quantity", "status", "created_at"):
            assert field in order and order[field] is not None, f"Missing {field}: {order}"
        assert isinstance(order["id"], str) and order["id"]
        assert isinstance(order["user_id"], str) and order["user_id"]
        assert isinstance(order["quantity"], (int, float))

    def test_user_activity_complete_shape(self, http_session, admin_headers, admin_users, regular_credentials):
        selected = next(
            (u for u in admin_users if u.get("username", "").lower() == regular_credentials["username"].lower()),
            admin_users[0],
        )
        response = http_session.get(
            f"{API}/admin/user-activity/{selected['id']}", headers=admin_headers, timeout=30
        )
        assert response.status_code == 200, response.text
        data = response.json()
        expected_top_level = {
            "user", "totals", "orders", "transactions", "number_rentals",
            "live_subscriptions", "live_checks",
        }
        assert expected_top_level.issubset(data)
        assert data["user"].get("id") == selected["id"]
        expected_totals = {
            "orders_count", "orders_total_spent", "deposits_total",
            "numbers_count", "auto_live_subs",
        }
        assert expected_totals.issubset(data["totals"])
        for key in ("orders", "transactions", "number_rentals", "live_subscriptions", "live_checks"):
            assert isinstance(data[key], list), f"{key} must be an array"
        assert data["totals"]["orders_count"] == len(data["orders"])
        assert data["totals"]["numbers_count"] == len(data["number_rentals"])
        assert data["totals"]["auto_live_subs"] == len(data["live_subscriptions"])


# Public sports feed and odds board.
class TestSportsPublic:
    def test_livescores_shape_and_source(self, http_session):
        response = http_session.get(f"{API}/sports/livescores", timeout=30)
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data.get("matches"), list)
        assert data.get("source") in {"rapidapi", "sofascore"}

    def test_odds_full_market_board(self, http_session):
        response = http_session.get(f"{API}/sports/odds/anything", timeout=20)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("match_id") == "anything"
        assert {"1X2", "over_0_5", "over_1_5", "over_2_5", "btts"}.issubset(data.get("markets", {}))


# Authenticated single-bet and combo-bet lifecycle.
class TestSportsBetting:
    def test_single_and_combo_bet_end_to_end(self, http_session, user_auth):
        single_payload = {
            "selections": [{
                "match_id": "sofa-test-1",
                "match_label": "Home vs Away",
                "market": "1X2",
                "selection": "home",
                "odds": 2.10,
            }],
            "stake": 0.10,
        }
        single_response = http_session.post(
            f"{API}/client/sports/bet", json=single_payload, headers=user_auth, timeout=20
        )
        assert single_response.status_code == 200, single_response.text
        single_data = single_response.json()
        assert single_data.get("ok") is True
        single_bet = single_data.get("bet", {})
        single_id = single_bet.get("id")
        assert isinstance(single_id, str) and single_id
        assert single_bet.get("combined_odds") == pytest.approx(2.10)
        assert single_bet.get("stake") == pytest.approx(0.10)
        assert single_bet.get("status") == "open"
        assert single_bet.get("is_combo") is False

        list_response = http_session.get(
            f"{API}/client/sports/my-bets", headers=user_auth, timeout=20
        )
        assert list_response.status_code == 200, list_response.text
        bets = list_response.json().get("bets")
        assert isinstance(bets, list)
        assert any(bet.get("id") == single_id for bet in bets)

        cashout = http_session.post(
            f"{API}/client/sports/bet/{single_id}/cashout", headers=user_auth, timeout=20
        )
        assert cashout.status_code == 200, cashout.text
        cashout_data = cashout.json()
        assert cashout_data.get("ok") is True
        assert cashout_data.get("rate") == pytest.approx(0.85)
        assert cashout_data.get("refund") == pytest.approx(0.09)

        repeat_cashout = http_session.post(
            f"{API}/client/sports/bet/{single_id}/cashout", headers=user_auth, timeout=20
        )
        assert repeat_cashout.status_code == 400, repeat_cashout.text

        combo_payload = {
            "selections": [
                {
                    "match_id": "sofa-test-combo-1",
                    "match_label": "Alpha vs Beta",
                    "market": "1X2",
                    "selection": "home",
                    "odds": 2.10,
                },
                {
                    "match_id": "sofa-test-combo-2",
                    "match_label": "Gamma vs Delta",
                    "market": "over_1_5",
                    "selection": "over",
                    "odds": 1.50,
                },
            ],
            "stake": 0.10,
        }
        combo_response = http_session.post(
            f"{API}/client/sports/bet", json=combo_payload, headers=user_auth, timeout=20
        )
        assert combo_response.status_code == 200, combo_response.text
        combo_data = combo_response.json()
        assert combo_data.get("ok") is True
        combo_bet = combo_data.get("bet", {})
        combo_id = combo_bet.get("id")
        assert isinstance(combo_id, str) and combo_id
        assert combo_bet.get("is_combo") is True
        assert len(combo_bet.get("selections", [])) == 2
        assert combo_bet.get("combined_odds") == pytest.approx(3.15)
        assert combo_bet.get("potential_win") == pytest.approx(0.32)

        combo_list = http_session.get(
            f"{API}/client/sports/my-bets", headers=user_auth, timeout=20
        )
        assert combo_list.status_code == 200, combo_list.text
        assert any(bet.get("id") == combo_id for bet in combo_list.json().get("bets", []))

        combo_cleanup = http_session.post(
            f"{API}/client/sports/bet/{combo_id}/cashout", headers=user_auth, timeout=20
        )
        assert combo_cleanup.status_code == 200, combo_cleanup.text
        assert combo_cleanup.json().get("ok") is True

    def test_concurrent_cashout_only_refunds_once(self, http_session, user_auth):
        payload = {
            "selections": [{
                "match_id": "sofa-test-concurrent-cashout",
                "match_label": "Concurrency Home vs Away",
                "market": "1X2",
                "selection": "home",
                "odds": 2.10,
            }],
            "stake": 0.10,
        }
        placed = http_session.post(
            f"{API}/client/sports/bet", json=payload, headers=user_auth, timeout=20
        )
        assert placed.status_code == 200, placed.text
        bet_id = placed.json()["bet"]["id"]

        def cashout_once():
            return requests.post(
                f"{API}/client/sports/bet/{bet_id}/cashout", headers=user_auth, timeout=20
            )

        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(lambda _: cashout_once(), range(5)))
        statuses = [response.status_code for response in responses]
        assert statuses.count(200) == 1, [
            {"status": response.status_code, "body": response.text} for response in responses
        ]
        assert statuses.count(400) == 4, statuses


# Startup import and requested authentication hardening checks.
class TestStartupAndAuthSecurity:
    def test_notification_service_imports(self):
        sys.path.insert(0, "/app/backend")
        import notification_service  # noqa: F401

    def test_login_sets_httponly_access_cookie(self, owner_auth):
        set_cookie = owner_auth["login_response"].headers.get("set-cookie", "")
        assert re.search(r"(?i)access_token=[^;]+;[^\r\n]*httponly", set_cookie), set_cookie

    def test_cors_uses_explicit_origin_with_credentials(self, http_session):
        evil_origin = "https://example-evil.test"
        response = http_session.options(
            f"{API}/auth/login",
            headers={"Origin": evil_origin, "Access-Control-Request-Method": "POST"},
            timeout=20,
        )
        assert response.status_code in (200, 204)
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin not in ("*", evil_origin), response.headers

    def test_brute_force_lockout_after_five_failures(self, http_session):
        identifier = "TEST_iter34_nonexistent_lockout_user"
        statuses = []
        for _ in range(6):
            captcha_id, captcha_answer = _solve_captcha(http_session)
            response = http_session.post(
                f"{API}/auth/login",
                json={
                    "identifier": identifier,
                    "password": "TEST_invalid_password",
                    "captcha_id": captcha_id,
                    "captcha_answer": captcha_answer,
                },
                timeout=20,
            )
            statuses.append(response.status_code)
        assert statuses[-1] == 429, f"Expected lockout on sixth attempt, got {statuses}"
