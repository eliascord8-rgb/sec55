"""Iteration 18 backend tests: /me/rank, /tips/send, /spin/status, /spin/spin."""
import os
import re
import time
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://smm-direct-order.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

CAPTCHA_RE = re.compile(r"(\d+)\s*([+\-])\s*(\d+)")


def _solve_captcha():
    r = requests.get(f"{API}/auth/captcha", timeout=10)
    r.raise_for_status()
    j = r.json()
    m = CAPTCHA_RE.search(j["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = a + b if op == "+" else a - b
    return j["id"], str(ans)


def _login(username, password):
    cid, cans = _solve_captcha()
    r = requests.post(f"{API}/auth/login", json={
        "identifier": username, "password": password,
        "captcha_id": cid, "captcha_answer": cans,
    }, timeout=10)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _register(username, password, email):
    cid, cans = _solve_captcha()
    r = requests.post(f"{API}/auth/register", json={
        "username": username, "password": password, "email": email,
        "captcha_id": cid, "captcha_answer": cans,
    }, timeout=10)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def testuser_token():
    tok, u = _login("testbugfix1", "password1")
    return tok, u


@pytest.fixture(scope="module")
def balkin_token():
    tok, u = _login("Balkin", "Dennis123.@@")
    return tok, u


class TestRank:
    def test_me_rank_testbugfix1(self, testuser_token):
        tok, _ = testuser_token
        r = requests.get(f"{API}/me/rank", headers=_auth(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["rank"] in ("Rookie", "Regular", "VIP", "Elite", "Legend")
        # Per problem statement testbugfix1 should have $10.50 → Regular
        assert data["rank"] == "Regular", f"expected Regular, got {data}"
        assert data["total_deposits"] >= 10.0
        assert data["next_tier"] and data["next_tier"]["name"] == "VIP"
        assert data["next_tier"]["min_deposit"] == 50

    def test_me_rank_unauth(self):
        r = requests.get(f"{API}/me/rank", timeout=10)
        assert r.status_code in (401, 403)


class TestSpin:
    def test_spin_status_testbugfix1_cooldown(self, testuser_token):
        tok, _ = testuser_token
        r = requests.get(f"{API}/spin/status", headers=_auth(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["eligible"] is True
        assert data["can_spin"] is False, f"expected cooldown, got {data}"
        assert data["prizes"] == [1, 2, 3, 4, 5, 6]

    def test_spin_spin_blocked_cooldown(self, testuser_token):
        tok, _ = testuser_token
        r = requests.post(f"{API}/spin/spin", headers=_auth(tok), timeout=10)
        assert r.status_code == 429, r.text
        assert "Come back" in r.json().get("detail", "")

    def test_spin_blocked_when_no_deposit(self):
        """A brand-new user without deposits must be blocked."""
        rand = uuid.uuid4().hex[:8]
        tok, _ = _register(f"nodep_{rand}", "password1", f"nodep_{rand}@x.com")
        r_status = requests.get(f"{API}/spin/status", headers=_auth(tok), timeout=10)
        assert r_status.status_code == 200
        assert r_status.json()["eligible"] is False
        assert r_status.json()["can_spin"] is False
        r = requests.post(f"{API}/spin/spin", headers=_auth(tok), timeout=10)
        assert r.status_code == 403


class TestTips:
    def test_tip_self_blocked(self, testuser_token):
        tok, u = testuser_token
        r = requests.post(f"{API}/tips/send", headers=_auth(tok),
                          json={"to_user_id": u["id"], "amount": 1.0}, timeout=10)
        assert r.status_code == 400
        assert "yourself" in r.json().get("detail", "").lower()

    def test_tip_invalid_recipient(self, testuser_token):
        tok, _ = testuser_token
        r = requests.post(f"{API}/tips/send", headers=_auth(tok),
                          json={"to_user_id": "nonexistent-" + uuid.uuid4().hex, "amount": 1.0}, timeout=10)
        assert r.status_code == 404

    def test_tip_below_min_amount(self, testuser_token, balkin_token):
        tok, _ = testuser_token
        _, brc = balkin_token
        r = requests.post(f"{API}/tips/send", headers=_auth(tok),
                          json={"to_user_id": brc["id"], "amount": 0.1}, timeout=10)
        assert r.status_code == 422  # Pydantic Field ge=0.5

    def test_tip_insufficient_balance_no_deposit_user(self, balkin_token):
        # Fresh user with 0 balance
        rand = uuid.uuid4().hex[:8]
        tok, _ = _register(f"pooruser_{rand}", "password1", f"pooruser_{rand}@x.com")
        _, brc = balkin_token
        r = requests.post(f"{API}/tips/send", headers=_auth(tok),
                          json={"to_user_id": brc["id"], "amount": 1.0}, timeout=10)
        assert r.status_code == 400
        assert "balance" in r.json().get("detail", "").lower()


class TestPublicChatRankEnrichment:
    def test_public_messages_have_rank_fields(self):
        r = requests.get(f"{API}/public-chat/messages", timeout=10)
        assert r.status_code == 200
        msgs = r.json().get("messages", [])
        if not msgs:
            pytest.skip("No public chat messages present")
        m = msgs[0]
        for key in ("rank_name", "rank_text_class", "rank_border_class"):
            assert key in m, f"missing {key} in message: {m}"
