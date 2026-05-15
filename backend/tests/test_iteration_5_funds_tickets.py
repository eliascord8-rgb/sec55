"""Iteration 5: PayPal config + Add Funds (deposit requests) + Support tickets."""
import os
import uuid
import time
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_USER = "Balkin99"
ADMIN_PASS = "Armin1234"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"x-admin-token": admin_token}


def _captcha():
    r = requests.get(f"{BASE}/api/auth/captcha", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _solve_q(question: str) -> int:
    # "What is A op B?"
    body = question.replace("What is", "").replace("?", "").strip()
    parts = body.split()
    a, op, b = int(parts[0]), parts[1], int(parts[2])
    return a + b if op == "+" else a - b


@pytest.fixture(scope="module")
def user_token():
    cap = _captcha()
    ans = _solve_q(cap["question"])
    uname = "tu_" + uuid.uuid4().hex[:8]
    payload = {
        "username": uname,
        "email": f"{uname}@test.example",
        "password": "Passw0rd!xyz",
        "captcha_id": cap["id"],
        "captcha_answer": str(ans),
    }
    r = requests.post(f"{BASE}/api/auth/register", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["token"], "username": uname, "id": data["user"]["id"]}


@pytest.fixture(scope="module")
def user_headers(user_token):
    return {"Authorization": f"Bearer {user_token['token']}"}


# ---------------- Captcha ----------------
class TestCaptcha:
    def test_captcha_endpoint(self):
        r = requests.get(f"{BASE}/api/auth/captcha", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("id", "question", "expires_in"):
            assert k in d
        assert "What is" in d["question"]

    def test_register_wrong_captcha(self):
        cap = _captcha()
        uname = "bad_" + uuid.uuid4().hex[:6]
        r = requests.post(f"{BASE}/api/auth/register", json={
            "username": uname, "email": f"{uname}@e.com", "password": "Passw0rd!xyz",
            "captcha_id": cap["id"], "captcha_answer": "999999",
        }, timeout=15)
        assert r.status_code == 400
        assert "captcha" in r.json().get("detail", "").lower()


# ---------------- PayPal config ----------------
class TestPaypalConfig:
    def test_public_get(self):
        r = requests.get(f"{BASE}/api/paypal-config", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "paypal_email" in d and "paypal_me_url" in d and "configured" in d

    def test_admin_set_requires_token(self):
        r = requests.post(f"{BASE}/api/admin/paypal-config", json={"paypal_email": "x@y.com", "paypal_me_url": "https://paypal.me/x"}, timeout=15)
        assert r.status_code == 401

    def test_admin_set_and_reflect(self, admin_headers):
        new_email = f"pp_{uuid.uuid4().hex[:6]}@test.com"
        new_url = f"https://paypal.me/test{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE}/api/admin/paypal-config", json={"paypal_email": new_email, "paypal_me_url": new_url}, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # Public reflects
        r2 = requests.get(f"{BASE}/api/paypal-config", timeout=15)
        d = r2.json()
        assert d["paypal_email"] == new_email
        assert d["paypal_me_url"] == new_url
        assert d["configured"] is True


# ---------------- Balance + Transactions ----------------
class TestBalanceAndTransactions:
    def test_initial_balance_zero(self, user_headers):
        r = requests.get(f"{BASE}/api/client/balance", headers=user_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("balance") == 0 or r.json().get("balance") == 0.0

    def test_balance_requires_auth(self):
        r = requests.get(f"{BASE}/api/client/balance", timeout=15)
        assert r.status_code == 401

    def test_transactions_initially_empty(self, user_headers):
        r = requests.get(f"{BASE}/api/client/transactions", headers=user_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("transactions") == []

    def test_funds_request_validation(self, user_headers):
        # negative
        r = requests.post(f"{BASE}/api/client/funds/request", json={"amount": -1, "method": "paypal"}, headers=user_headers, timeout=15)
        assert r.status_code == 422
        # zero
        r2 = requests.post(f"{BASE}/api/client/funds/request", json={"amount": 0, "method": "paypal"}, headers=user_headers, timeout=15)
        assert r2.status_code == 422
        # too large
        r3 = requests.post(f"{BASE}/api/client/funds/request", json={"amount": 99999, "method": "paypal"}, headers=user_headers, timeout=15)
        assert r3.status_code == 422

    def test_funds_request_creates_pending(self, user_headers):
        r = requests.post(f"{BASE}/api/client/funds/request", json={"amount": 25.50, "method": "paypal"}, headers=user_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["status"] == "pending"
        # Verify in transactions list
        r2 = requests.get(f"{BASE}/api/client/transactions", headers=user_headers, timeout=15)
        txs = r2.json()["transactions"]
        assert any(t["id"] == d["id"] and t["status"] == "pending" and t["amount"] == 25.50 for t in txs)

    def test_approve_credits_balance(self, user_headers, admin_headers):
        # Create new pending
        r = requests.post(f"{BASE}/api/client/funds/request", json={"amount": 10.00, "method": "paypal"}, headers=user_headers, timeout=15)
        tx_id = r.json()["id"]
        # Balance before
        b_before = requests.get(f"{BASE}/api/client/balance", headers=user_headers, timeout=15).json()["balance"]
        # Approve
        ar = requests.post(f"{BASE}/api/admin/transactions/{tx_id}/approve", json={"note": "ok"}, headers=admin_headers, timeout=15)
        assert ar.status_code == 200
        assert ar.json()["transaction"]["status"] == "approved"
        # Balance after
        b_after = requests.get(f"{BASE}/api/client/balance", headers=user_headers, timeout=15).json()["balance"]
        assert round(b_after - b_before, 2) == 10.00

    def test_reject_no_credit(self, user_headers, admin_headers):
        r = requests.post(f"{BASE}/api/client/funds/request", json={"amount": 7.00, "method": "paypal"}, headers=user_headers, timeout=15)
        tx_id = r.json()["id"]
        b_before = requests.get(f"{BASE}/api/client/balance", headers=user_headers, timeout=15).json()["balance"]
        rj = requests.post(f"{BASE}/api/admin/transactions/{tx_id}/reject", json={"note": "fake"}, headers=admin_headers, timeout=15)
        assert rj.status_code == 200
        assert rj.json()["transaction"]["status"] == "rejected"
        b_after = requests.get(f"{BASE}/api/client/balance", headers=user_headers, timeout=15).json()["balance"]
        assert b_before == b_after

    def test_double_approve_fails(self, user_headers, admin_headers):
        r = requests.post(f"{BASE}/api/client/funds/request", json={"amount": 3.00, "method": "paypal"}, headers=user_headers, timeout=15)
        tx_id = r.json()["id"]
        requests.post(f"{BASE}/api/admin/transactions/{tx_id}/approve", json={}, headers=admin_headers, timeout=15)
        r2 = requests.post(f"{BASE}/api/admin/transactions/{tx_id}/approve", json={}, headers=admin_headers, timeout=15)
        assert r2.status_code == 404

    def test_admin_list_filter(self, admin_headers):
        r = requests.get(f"{BASE}/api/admin/transactions?status=pending", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        for t in r.json()["transactions"]:
            assert t["status"] == "pending"

    def test_admin_transactions_requires_token(self):
        r = requests.get(f"{BASE}/api/admin/transactions", timeout=15)
        assert r.status_code == 401


# ---------------- Tickets ----------------
class TestTickets:
    def test_create_ticket(self, user_headers):
        r = requests.post(f"{BASE}/api/client/tickets", json={"subject": "TEST_help", "message": "I need help"}, headers=user_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert "id" in d
        pytest.tid = d["id"]

    def test_list_user_tickets(self, user_headers):
        r = requests.get(f"{BASE}/api/client/tickets", headers=user_headers, timeout=15)
        assert r.status_code == 200
        ts = r.json()["tickets"]
        assert any(t["id"] == pytest.tid for t in ts)

    def test_get_ticket_thread_has_first_msg(self, user_headers):
        r = requests.get(f"{BASE}/api/client/tickets/{pytest.tid}", headers=user_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ticket"]["id"] == pytest.tid
        assert len(d["messages"]) == 1
        assert d["messages"][0]["author_role"] == "user"
        assert d["messages"][0]["message"] == "I need help"

    def test_other_user_cannot_see_ticket(self):
        # Register another user
        cap = _captcha()
        uname = "ou_" + uuid.uuid4().hex[:6]
        rr = requests.post(f"{BASE}/api/auth/register", json={
            "username": uname, "email": f"{uname}@e.com", "password": "Passw0rd!xyz",
            "captcha_id": cap["id"], "captcha_answer": str(_solve_q(cap["question"])),
        }, timeout=15)
        assert rr.status_code == 200
        other_token = rr.json()["token"]
        g = requests.get(f"{BASE}/api/client/tickets/{pytest.tid}", headers={"Authorization": f"Bearer {other_token}"}, timeout=15)
        assert g.status_code == 404

    def test_user_reply_appends(self, user_headers):
        time.sleep(0.05)
        r = requests.post(f"{BASE}/api/client/tickets/{pytest.tid}/reply", json={"message": "thanks!"}, headers=user_headers, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{BASE}/api/client/tickets/{pytest.tid}", headers=user_headers, timeout=15).json()
        assert len(g["messages"]) == 2
        assert g["ticket"]["last_reply_by"] == "user"

    def test_admin_can_see_any_ticket(self, admin_headers):
        r = requests.get(f"{BASE}/api/admin/tickets/{pytest.tid}", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["ticket"]["id"] == pytest.tid

    def test_admin_list_has_waiting(self, admin_headers):
        r = requests.get(f"{BASE}/api/admin/tickets", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["tickets"], list)
        assert isinstance(d["waiting"], int)
        assert d["waiting"] >= 1  # our ticket is open with user as last reply

    def test_admin_reply_sets_answered(self, admin_headers, user_headers):
        r = requests.post(f"{BASE}/api/admin/tickets/{pytest.tid}/reply", json={"message": "help on the way", "staff_name": "Support"}, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{BASE}/api/client/tickets/{pytest.tid}", headers=user_headers, timeout=15).json()
        assert g["ticket"]["status"] == "answered"
        assert g["ticket"]["last_reply_by"] == "staff"
        assert g["messages"][-1]["author_role"] == "staff"

    def test_admin_close_blocks_user_reply(self, admin_headers, user_headers):
        c = requests.post(f"{BASE}/api/admin/tickets/{pytest.tid}/close", headers=admin_headers, timeout=15)
        assert c.status_code == 200
        # User cannot reply now
        r = requests.post(f"{BASE}/api/client/tickets/{pytest.tid}/reply", json={"message": "again"}, headers=user_headers, timeout=15)
        assert r.status_code == 400

    def test_admin_endpoints_require_token(self):
        for p in ["/api/admin/tickets", f"/api/admin/tickets/{pytest.tid}"]:
            assert requests.get(f"{BASE}{p}", timeout=15).status_code == 401
        assert requests.post(f"{BASE}/api/admin/tickets/{pytest.tid}/reply", json={"message": "x"}, timeout=15).status_code == 401
        assert requests.post(f"{BASE}/api/admin/tickets/{pytest.tid}/close", timeout=15).status_code == 401
