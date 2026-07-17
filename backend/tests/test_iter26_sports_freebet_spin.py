"""Iteration 26 backend tests: sports endpoints, daily free-bet, and updated spin wheel."""
import os
import re
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def solve_captcha():
    r = requests.get(f"{API}/auth/captcha", timeout=15)
    d = r.json()
    m = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", d["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = {"+": a + b, "-": a - b, "*": a * b}[op]
    return d["id"], str(ans)


@pytest.fixture(scope="module")
def token():
    cid, ans = solve_captcha()
    r = requests.post(f"{API}/auth/login", json={
        "identifier": "testbugfix1", "password": "password1",
        "captcha_id": cid, "captcha_answer": ans,
    }, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Sports (public) ----------
class TestSports:
    def test_livescores(self):
        r = requests.get(f"{BASE_URL}/api/sports/livescores", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "matches" in data
        assert isinstance(data["matches"], list)

    def test_upcoming(self):
        r = requests.get(f"{BASE_URL}/api/sports/upcoming", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "matches" in data
        assert isinstance(data["matches"], list)
        # Note: upstream may occasionally return sports_source_unavailable — that's acceptable

    def test_leagues(self):
        r = requests.get(f"{BASE_URL}/api/sports/leagues", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "leagues" in data
        # NOTE: backend may unwrap RapidAPI response inconsistently — it can be a list or a dict with 'popular' key
        assert isinstance(data["leagues"], (list, dict))


# ---------- Free-bet ----------
class TestFreeBet:
    def test_status_shape(self, auth):
        r = requests.get(f"{BASE_URL}/api/free-bet/status", headers=auth, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert set(["can_claim", "hours_left", "amount"]).issubset(data.keys())
        assert data["amount"] == 0.80

    def test_claim_flow(self, auth):
        # Ensure clean state: attempt one claim; if already claimed we still test 429
        status_before = requests.get(f"{BASE_URL}/api/free-bet/status", headers=auth, timeout=15).json()
        bal_before = requests.get(f"{BASE_URL}/api/client/balance", headers=auth, timeout=15).json()
        bal0 = float(bal_before.get("balance") or bal_before.get("amount") or 0)

        r1 = requests.post(f"{BASE_URL}/api/free-bet/claim", headers=auth, timeout=15)
        if status_before.get("can_claim"):
            assert r1.status_code == 200, f"claim1 body: {r1.text}"
            body = r1.json()
            assert body.get("ok") is True
            assert body.get("amount") == 0.80
            bal_after = requests.get(f"{BASE_URL}/api/client/balance", headers=auth, timeout=15).json()
            bal1 = float(bal_after.get("balance") or bal_after.get("amount") or 0)
            assert round(bal1 - bal0, 2) >= 0.80, f"balance did not increase by 0.80: {bal0} -> {bal1}"
        else:
            assert r1.status_code == 429

        # Second immediate claim must be 429
        r2 = requests.post(f"{BASE_URL}/api/free-bet/claim", headers=auth, timeout=15)
        assert r2.status_code == 429
        detail = r2.json().get("detail", "")
        assert "h" in detail.lower() or "hour" in detail.lower() or "free bet" in detail.lower()


# ---------- Spin wheel (updated) ----------
class TestSpin:
    def test_spin_status_shape(self, auth):
        r = requests.get(f"{BASE_URL}/api/spin/status", headers=auth, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["cooldown_days"] == 14
        assert data["min_deposit"] == 100.0
        assert data["prizes"] == [0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0]

    def test_spin_spin_eligibility(self, auth):
        status = requests.get(f"{BASE_URL}/api/spin/status", headers=auth, timeout=15).json()
        r = requests.post(f"{BASE_URL}/api/spin/spin", headers=auth, timeout=15)
        if not status.get("eligible"):
            assert r.status_code == 403
            assert "100" in r.json().get("detail", "")
        else:
            if status.get("can_spin"):
                assert r.status_code == 200
                body = r.json()
                assert body.get("ok") is True
                assert body.get("prize") in [0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0]
                assert body["prize"] <= 5.00
                assert body.get("next_spin_days") == 14
            else:
                assert r.status_code == 429
