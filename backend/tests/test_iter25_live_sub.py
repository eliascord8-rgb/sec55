"""Iteration 25 backend tests — Auto-Live subscription rewrite + AI sessions endpoints."""
import os
import re
import uuid
import pytest
import requests

BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"

TEST_USER = "testbugfix1"
TEST_PASS = "password1"


# ---------------- helpers ----------------
def solve_captcha():
    r = requests.get(f"{API}/auth/captcha", timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    m = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", d["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = {"+": a + b, "-": a - b, "*": a * b}[op]
    return d["id"], str(ans)


def login(identifier=TEST_USER, password=TEST_PASS):
    cid, ans = solve_captcha()
    r = requests.post(f"{API}/auth/login", json={
        "identifier": identifier, "password": password,
        "captcha_id": cid, "captcha_answer": ans,
    }, timeout=15)
    assert r.status_code == 200, f"login: {r.status_code} {r.text}"
    return r.json()["token"]


def admin_token():
    r = requests.post(f"{API}/admin/login-secret", json={"secret": "haha123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def ah(t): return {"Authorization": f"Bearer {t}"}
def ath(t): return {"X-Admin-Token": t}


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def user_token():
    return login()


@pytest.fixture(scope="module")
def adm_token():
    return admin_token()


@pytest.fixture(scope="module")
def test_user_id(adm_token):
    r = requests.get(f"{API}/admin/users", headers=ath(adm_token), timeout=15)
    assert r.status_code == 200, r.text
    users = r.json().get("users") or r.json().get("items") or []
    tgt = next((u for u in users if u.get("username", "").lower() == TEST_USER.lower()), None)
    assert tgt, "test user not found"
    return tgt["id"]


@pytest.fixture(scope="module")
def tiktok_live_service(adm_token):
    """Seed a TikTok Live service with rate>0. /admin/services/manual creates a
    manual service with custom_rate=0, so we PATCH custom_rate afterwards."""
    payload = {
        "name": "TikTok Live Views TEST",
        "category": "TikTok Live",
        "price_usd": 1.0,
        "description": "iter25 test",
    }
    r = requests.post(f"{API}/admin/services/manual", json=payload,
                      headers=ath(adm_token), timeout=15)
    assert r.status_code == 200, r.text
    sid = r.json()["service_id"]
    # PATCH custom_rate to 1.0 so live_sub_create's rate>0 check passes
    r2 = requests.patch(f"{API}/admin/services/{sid}",
                        json={"custom_rate": 1.0}, headers=ath(adm_token), timeout=15)
    assert r2.status_code == 200, r2.text
    # Also expand max via direct mongo — but no PATCH field for min/max exposed.
    # Manual services default min=1,max=1. quantity_per_burst must fit. Use 1.
    yield sid
    # cleanup
    requests.delete(f"{API}/admin/services/{sid}", headers=ath(adm_token), timeout=15)


# ---------------- Live-Sub creation validation ----------------
class TestLiveSubValidation:
    def test_invalid_repeat_interval_400(self, user_token):
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 7,
            "repeat_every_minutes": 7,
        }, headers=ah(user_token), timeout=15)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
        assert "Repeat" in r.text or "repeat" in r.text

    def test_invalid_duration_400(self, user_token):
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 5,
            "repeat_every_minutes": 5,
        }, headers=ah(user_token), timeout=15)
        assert r.status_code == 400, r.text
        assert "Duration" in r.text or "duration" in r.text

    def test_no_auto_live_flag_403(self, user_token, adm_token, test_user_id):
        # Force flag off first
        requests.post(f"{API}/admin/users/{test_user_id}/auto-live",
                      json={"enabled": False}, headers=ath(adm_token), timeout=15)
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 7,
            "repeat_every_minutes": 5,
        }, headers=ah(user_token), timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"


# ---------------- Full flow: enable auto-live + create + cancel ----------------
class TestLiveSubFullFlow:
    def test_enable_auto_live_and_create(self, user_token, adm_token, test_user_id, tiktok_live_service):
        # 1) enable auto_live for user
        r = requests.post(f"{API}/admin/users/{test_user_id}/auto-live",
                          json={"enabled": True}, headers=ath(adm_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("auto_live_enabled") is True

        # 2) top up balance sufficiently
        r = requests.post(f"{API}/admin/users/{test_user_id}/adjust-balance",
                          json={"amount": 50.0, "reason": "iter25 test"},
                          headers=ath(adm_token), timeout=15)
        assert r.status_code in (200, 201), r.text

        # 3) create the subscription
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": tiktok_live_service,
            "tiktok_username": "iter25tester",
            "quantity_per_burst": 1,
            "duration_days": 7,
            "repeat_every_minutes": 5,
        }, headers=ah(user_token), timeout=30)
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        d = r.json()
        assert d.get("ok") is True
        sub = d.get("subscription")
        assert sub and sub.get("id")
        assert sub.get("repeat_every_minutes") == 5
        assert sub.get("duration_days") == 7
        assert sub.get("status") == "active"
        # first_order_id may be None if provider unreachable - fine
        # store for later
        pytest.iter25_sub_id = sub["id"]

    def test_list_my_subs_has_new_one(self, user_token):
        r = requests.get(f"{API}/client/live-sub/my", headers=ah(user_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "subscriptions" in d
        sid = getattr(pytest, "iter25_sub_id", None)
        assert sid, "prior create test did not set sub id"
        match = next((s for s in d["subscriptions"] if s.get("id") == sid), None)
        assert match is not None, "created sub not in /my"
        assert match["repeat_every_minutes"] == 5

    def test_cancel_sub(self, user_token):
        sid = getattr(pytest, "iter25_sub_id", None)
        assert sid
        r = requests.post(f"{API}/client/live-sub/{sid}/cancel",
                          headers=ah(user_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # verify status became cancelled
        r2 = requests.get(f"{API}/client/live-sub/my", headers=ah(user_token), timeout=15)
        assert r2.status_code == 200
        match = next((s for s in r2.json()["subscriptions"] if s.get("id") == sid), None)
        assert match and match.get("status") == "cancelled"

    def test_second_cancel_404(self, user_token):
        sid = getattr(pytest, "iter25_sub_id", None)
        assert sid
        r = requests.post(f"{API}/client/live-sub/{sid}/cancel",
                          headers=ah(user_token), timeout=15)
        assert r.status_code == 404


# ---------------- Addons still shows auto_live @ 250 ----------------
class TestAddonsUnchanged:
    def test_auto_live_price(self, adm_token):
        r = requests.get(f"{API}/admin/addons", headers=ath(adm_token), timeout=15)
        assert r.status_code == 200
        al = next((a for a in r.json()["addons"] if a.get("id") == "auto_live"), None)
        assert al is not None
        assert float(al["price"]) == 250.0


# ---------------- AI sessions endpoints ----------------
class TestAiSessions:
    def test_my_sessions_200(self, user_token):
        r = requests.get(f"{API}/ai/my-sessions", headers=ah(user_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "sessions" in d
        assert isinstance(d["sessions"], list)

    def test_nonexistent_session_messages_404(self, user_token):
        r = requests.get(f"{API}/ai/session/nonexistent-session-id-iter25/messages",
                         headers=ah(user_token), timeout=15)
        assert r.status_code in (404, 403), f"expected 404/403 got {r.status_code}: {r.text}"

    def test_request_handover_with_session_id(self):
        sid = "iter25-test"
        r = requests.post(f"{API}/ai/request-handover",
                          json={"session_id": sid}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("session_id") == sid
