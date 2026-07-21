"""Iteration 27 backend tests — Auto-Live TikTok detector rewrite + worker verification.

Covers the bug fix where `_is_tiktok_user_live()` always returned False due to
stale SSR marker scraping. Tests:
- New /api/debug/tiktok-live/{handle} debug endpoint (contract only).
- Regression: /api/client/live-sub/create validation (repeat/duration).
- Regression: /api/client/live-sub/my exposes repeat_every_minutes.
- Regression: /api/client/live-sub/{sid}/cancel — 200 then 404.
- Log check: [livesub] worker started and no _is_tiktok_user_live crashes.
- Worker liveness: synthetic due sub gets `last_check_at` bumped within 40s.
"""
import os
import re
import time
import uuid
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"

TEST_USER = "testbugfix1"
TEST_PASS = "password1"

MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("DB_NAME") or "test_database"


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
def mongo_db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


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


@pytest.fixture(scope="module", autouse=True)
def enable_auto_live_and_topup(adm_token, test_user_id):
    """Ensure testbugfix1 has auto_live_enabled and some balance for create tests."""
    requests.post(f"{API}/admin/users/{test_user_id}/auto-live",
                  json={"enabled": True}, headers=ath(adm_token), timeout=15)
    requests.post(f"{API}/admin/users/{test_user_id}/adjust-balance",
                  json={"amount": 50.0, "reason": "iter27 test"},
                  headers=ath(adm_token), timeout=15)
    yield


# ---------------- 1. Debug endpoint contract ----------------
class TestDebugTiktokLiveEndpoint:
    def test_debug_endpoint_requires_auth(self):
        r = requests.get(f"{API}/debug/tiktok-live/tiktok", timeout=20)
        assert r.status_code in (401, 403), f"expected auth-required, got {r.status_code}"

    def test_debug_official_tiktok_handle(self, user_token):
        r = requests.get(f"{API}/debug/tiktok-live/tiktok",
                         headers=ah(user_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        d = r.json()
        assert d.get("handle") == "tiktok"
        assert isinstance(d.get("is_live"), bool)

    def test_debug_at_prefix_stripped(self, user_token):
        r = requests.get(f"{API}/debug/tiktok-live/@tiktok",
                         headers=ah(user_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("handle") == "tiktok"
        assert isinstance(d.get("is_live"), bool)

    def test_debug_nonexistent_handle_no_500(self, user_token):
        r = requests.get(
            f"{API}/debug/tiktok-live/_this_is_definitely_not_a_real_handle_xyz123_",
            headers=ah(user_token), timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        d = r.json()
        assert d.get("is_live") is False


# ---------------- 2. Live-Sub create validation (regression) ----------------
class TestLiveSubValidationRegression:
    def test_repeat_2_accepted_service_id_missing_returns_404(self, user_token):
        # repeat_every_minutes=2 must NOT be rejected at validation layer.
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 7,
            "repeat_every_minutes": 2,
        }, headers=ah(user_token), timeout=15)
        # Should pass validation → fall through to service lookup 404 (not 400)
        assert r.status_code != 400, f"repeat=2 wrongly rejected: {r.text}"
        assert r.status_code == 404, r.text

    def test_repeat_5_accepted(self, user_token):
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 7,
            "repeat_every_minutes": 5,
        }, headers=ah(user_token), timeout=15)
        assert r.status_code != 400, r.text

    def test_repeat_invalid_value_400(self, user_token):
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 7,
            "repeat_every_minutes": 7,
        }, headers=ah(user_token), timeout=15)
        assert r.status_code == 400, r.text
        assert "epeat" in r.text

    def test_duration_invalid_400(self, user_token):
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": -9999, "tiktok_username": "x",
            "quantity_per_burst": 1, "duration_days": 5,
            "repeat_every_minutes": 5,
        }, headers=ah(user_token), timeout=15)
        assert r.status_code == 400, r.text
        assert "uration" in r.text


# ---------------- 3. /my subs + cancel regression via direct mongo insert ----------------
class TestLiveSubMyAndCancel:
    def test_my_lists_and_repeat_field_present(self, user_token, test_user_id, mongo_db):
        # Insert a synthetic active sub directly.
        sid = f"TEST-iter27-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        doc = {
            "id": sid,
            "user_id": test_user_id,
            "service_id": -9999,
            "tiktok_username": "tiktok",
            "quantity_per_burst": 1,
            "duration_days": 7,
            "repeat_every_minutes": 5,
            "charge_per_burst": 0.01,
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "next_check_at": (now + timedelta(minutes=10)).isoformat(),
            "provider_id": None,
        }
        mongo_db.live_subscriptions.insert_one(dict(doc))
        try:
            r = requests.get(f"{API}/client/live-sub/my",
                             headers=ah(user_token), timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "subscriptions" in body
            match = next((s for s in body["subscriptions"] if s.get("id") == sid), None)
            assert match, f"inserted sub not returned in /my"
            assert match.get("repeat_every_minutes") == 5
            # ---- cancel ----
            c1 = requests.post(f"{API}/client/live-sub/{sid}/cancel",
                               headers=ah(user_token), timeout=15)
            assert c1.status_code == 200, c1.text
            assert c1.json().get("ok") is True
            # second cancel → 404
            c2 = requests.post(f"{API}/client/live-sub/{sid}/cancel",
                               headers=ah(user_token), timeout=15)
            assert c2.status_code == 404, c2.text
        finally:
            mongo_db.live_subscriptions.delete_one({"id": sid})


# ---------------- 4. Worker log verification ----------------
class TestWorkerLogHealth:
    def test_worker_started_line_present(self):
        # grep supervisor logs for the startup marker.
        out = subprocess.run(
            "grep -h 'livesub' /var/log/supervisor/backend*.log | tail -50",
            shell=True, capture_output=True, text=True,
        )
        combined = out.stdout
        assert "background worker started (interval=60s)" in combined, \
            f"worker startup line missing:\n{combined}"

    def test_no_is_tiktok_user_live_crash(self):
        out = subprocess.run(
            "grep -h '_is_tiktok_user_live' /var/log/supervisor/backend*.log | tail -50",
            shell=True, capture_output=True, text=True,
        )
        text = out.stdout.lower()
        # It's OK for the function name to appear in DEBUG log lines. Fail only if
        # it's associated with Traceback / Error.
        for line in text.splitlines():
            assert "traceback" not in line and "error" not in line, \
                f"detector traceback found: {line}"


# ---------------- 5. Worker liveness — synthetic due sub gets polled ----------------
class TestWorkerLoopPicksUpDueSub:
    def test_worker_updates_last_check_at(self, test_user_id, mongo_db):
        sid = f"TEST-iter27-worker-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        past = (now - timedelta(minutes=5)).isoformat()
        doc = {
            "id": sid,
            "user_id": test_user_id,
            "service_id": -9999,
            "tiktok_username": "tiktok",
            "quantity_per_burst": 1,
            "duration_days": 7,
            "repeat_every_minutes": 2,
            "charge_per_burst": 0.0,   # zero so any burst attempt is cheap; won't fire since service_id -9999
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "next_check_at": past,      # already due
            "last_check_at": None,
            "provider_id": None,
        }
        mongo_db.live_subscriptions.insert_one(dict(doc))
        try:
            deadline = time.time() + 60
            picked_up = False
            while time.time() < deadline:
                cur = mongo_db.live_subscriptions.find_one({"id": sid})
                if cur and cur.get("last_check_at"):
                    picked_up = True
                    break
                time.sleep(3)
            assert picked_up, "worker did not update last_check_at within 60s"
        finally:
            mongo_db.live_subscriptions.delete_one({"id": sid})
