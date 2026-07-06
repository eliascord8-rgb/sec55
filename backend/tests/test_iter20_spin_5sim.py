"""Iter20 tests — spin wheel (min-deposit + weighted RNG) and 5sim integration."""
import os
import re
import time
import uuid
import random
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

CAPTCHA_Q_RE = re.compile(r"(\d+)\s*([+\-])\s*(\d+)")


def _solve_captcha():
    r = requests.get(f"{BASE_URL}/api/auth/captcha", timeout=15)
    r.raise_for_status()
    j = r.json()
    m = CAPTCHA_Q_RE.search(j["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = a + b if op == "+" else a - b
    return j["id"], str(ans)


def _login(identifier, password):
    cid, ca = _solve_captcha()
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"identifier": identifier, "password": password, "captcha_id": cid, "captcha_answer": ca},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


def _register(username, email, password):
    cid, ca = _solve_captcha()
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "username": username, "email": email, "password": password,
            "captcha_id": cid, "captcha_answer": ca,
        },
        timeout=15,
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()


def _admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login-secret", json={"secret": "haha123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ================= SPIN =================

@pytest.fixture(scope="module")
def nospin_user():
    """Fresh user with only $10 deposit — should be blocked from spinning."""
    suffix = f"{random.randint(1000,9999)}{int(time.time()) % 10000}"
    username = f"nospintest_{suffix}"
    email = f"nospintest_{suffix}@example.com"
    reg = _register(username, email, "password1")
    uid = reg["user"]["id"]
    # Insert an approved $10 deposit directly in mongo
    db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "amount": 10.0,
        "status": "approved",
        "type": "deposit",
        "method": "test-seed",
        "created_at": "2025-01-01T00:00:00+00:00",
        "approved_at": "2025-01-01T00:00:00+00:00",
    })
    token = _login(username, "password1")
    yield {"id": uid, "username": username, "token": token}
    # cleanup
    db.users.delete_many({"id": uid})
    db.transactions.delete_many({"user_id": uid})
    db.spin_wheel.delete_many({"user_id": uid})


def test_spin_status_under50_user_blocked(nospin_user):
    r = requests.get(
        f"{BASE_URL}/api/spin/status",
        headers={"Authorization": f"Bearer {nospin_user['token']}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["eligible"] is False
    assert j["min_deposit"] == 50.0 or j["min_deposit"] == 50
    assert j["total_deposits"] == 10.0
    assert j["amount_needed"] == 40.0
    assert j["prizes"] == [1, 2, 3, 4, 5, 6, 40]


def test_spin_post_under50_user_returns_403(nospin_user):
    r = requests.post(
        f"{BASE_URL}/api/spin/spin",
        headers={"Authorization": f"Bearer {nospin_user['token']}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    assert "need at least $50" in r.json().get("detail", "").lower() or \
           "need at least $50" in r.json().get("detail", "")


@pytest.fixture(scope="module")
def testbugfix1_token():
    return _login("testbugfix1", "password1")


@pytest.fixture(scope="module")
def testbugfix1_uid(testbugfix1_token):
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {testbugfix1_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    return (j.get("user") or j).get("id")


def test_spin_eligible_user_can_spin(testbugfix1_token, testbugfix1_uid):
    # Ensure they can spin: clear history first
    db.spin_wheel.delete_many({"user_id": testbugfix1_uid})
    db.transactions.delete_many({"user_id": testbugfix1_uid, "type": "spin_prize"})

    # verify eligibility
    r = requests.get(
        f"{BASE_URL}/api/spin/status",
        headers={"Authorization": f"Bearer {testbugfix1_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    assert j["eligible"] is True, f"testbugfix1 should be eligible: {j}"
    assert j["can_spin"] is True, f"testbugfix1 should be able to spin (history was cleared): {j}"
    assert j["prizes"] == [1, 2, 3, 4, 5, 6, 40]

    # spin
    r = requests.post(
        f"{BASE_URL}/api/spin/spin",
        headers={"Authorization": f"Bearer {testbugfix1_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["prize"] in [1, 2, 3, 4, 5, 6, 40]
    assert isinstance(j["jackpot"], bool)
    assert (j["prize"] == 40) == j["jackpot"]  # jackpot iff prize=40
    assert "spin_id" in j
    assert j["next_spin_days"] == 7


def test_spin_cooldown_second_spin_429(testbugfix1_token):
    # Immediately try again
    r = requests.post(
        f"{BASE_URL}/api/spin/spin",
        headers={"Authorization": f"Bearer {testbugfix1_token}"},
        timeout=15,
    )
    assert r.status_code == 429, r.text
    assert "day" in r.json().get("detail", "").lower()

    r2 = requests.get(
        f"{BASE_URL}/api/spin/status",
        headers={"Authorization": f"Bearer {testbugfix1_token}"},
        timeout=15,
    )
    j = r2.json()
    assert j["can_spin"] is False
    assert j["days_left"] >= 1


# ================= 5SIM =================

def test_5sim_public_services_no_auth():
    r = requests.get(f"{BASE_URL}/api/5sim/services", timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "products" in j
    ids = [p["id"] for p in j["products"]]
    assert ids == ["whatsapp", "signal", "viber", "tiktok", "telegram"]
    for p in j["products"]:
        assert "name" in p and "price" in p and "icon" in p
        assert isinstance(p["price"], (int, float))
    assert "default_country" in j
    assert "default_operator" in j


def test_5sim_admin_config_set_and_get_masks_key():
    tok = _admin_token()
    prices = {"whatsapp": 3.5, "signal": 2.99, "viber": 1.99, "tiktok": 2.5, "telegram": 1.5}
    r = requests.post(
        f"{BASE_URL}/api/admin/5sim/config",
        headers={"X-Admin-Token": tok},
        json={"api_key": "test_jwt", "prices": prices},
        timeout=15,
    )
    assert r.status_code == 200, r.text

    r = requests.get(
        f"{BASE_URL}/api/admin/5sim/config",
        headers={"X-Admin-Token": tok},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["api_key"] == "***"
    assert "…" in j.get("api_key_preview", "")
    for k, v in prices.items():
        assert float(j["prices"][k]) == float(v)

    # Public /5sim/services reflects prices
    r = requests.get(f"{BASE_URL}/api/5sim/services", timeout=15)
    j2 = r.json()
    price_map = {p["id"]: p["price"] for p in j2["products"]}
    for k, v in prices.items():
        assert float(price_map[k]) == float(v)


def test_5sim_buy_unsupported_product_400(testbugfix1_token):
    r = requests.post(
        f"{BASE_URL}/api/5sim/buy",
        headers={"Authorization": f"Bearer {testbugfix1_token}"},
        json={"product": "amazon"},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "whatsapp" in detail and "telegram" in detail


def test_5sim_buy_insufficient_balance_400(nospin_user):
    """nospin_user has $10 deposit but no orders — balance well below $3.5 whatsapp is likely
    still enough if $10 balance. Use a huge price via admin config to force 400. So instead,
    push whatsapp price above nospin user's balance first."""
    # Use admin to set whatsapp to a very high retail price
    tok = _admin_token()
    r = requests.post(
        f"{BASE_URL}/api/admin/5sim/config",
        headers={"X-Admin-Token": tok},
        json={"api_key": "test_jwt", "prices": {
            "whatsapp": 9999.99, "signal": 2.99, "viber": 1.99, "tiktok": 2.5, "telegram": 1.5
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    try:
        r = requests.post(
            f"{BASE_URL}/api/5sim/buy",
            headers={"Authorization": f"Bearer {nospin_user['token']}"},
            json={"product": "whatsapp"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "Not enough balance" in r.json().get("detail", "")
    finally:
        # restore normal price
        requests.post(
            f"{BASE_URL}/api/admin/5sim/config",
            headers={"X-Admin-Token": tok},
            json={"prices": {
                "whatsapp": 3.5, "signal": 2.99, "viber": 1.99, "tiktok": 2.5, "telegram": 1.5
            }},
            timeout=15,
        )


# ============ REGRESSION: public-chat tip rate-limit bypass ============

def test_regression_public_chat_tip_bypasses_rate_limit(testbugfix1_token):
    """From iter19 — /api/chat/tip should not be blocked by public-chat rate limiter.
    We just check the endpoint doesn't blanket 429 when called twice quickly with a
    valid-shaped body. If auth/user constraints reject with 400/404/403, that's not
    a rate-limit failure. We only fail if we see 429."""
    for _ in range(3):
        r = requests.post(
            f"{BASE_URL}/api/chat/tip",
            headers={"Authorization": f"Bearer {testbugfix1_token}"},
            json={"recipient_username": "Balkin", "amount": 0.01, "message_id": "nonexistent"},
            timeout=15,
        )
        # 429 would indicate the rate-limit is (incorrectly) applying to tips
        assert r.status_code != 429, f"tip endpoint hit rate-limit (regression): {r.text}"
