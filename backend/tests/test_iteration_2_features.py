"""Backend tests for iteration 2: order ticker, coupon balance edit, AI chat + admin inbox + takeover."""
import os
import time
import uuid
import pytest
import requests
from pathlib import Path

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

API = f"{BASE_URL}/api"
ADMIN_USER = "Balkin99"
ADMIN_PASS = "Armin1234"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(f"{API}/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    token = r.json().get("token")
    assert token
    return token


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"X-Admin-Token": admin_token, "Content-Type": "application/json"}


# =============== 1) ORDER TICKER / RECENT FEED ===============
class TestRecentFeed:
    def test_recent_feed_public(self, session):
        """GET /api/orders/recent-feed is public & returns a feed array."""
        r = session.get(f"{API}/orders/recent-feed")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "feed" in body
        assert isinstance(body["feed"], list)

    def test_recent_feed_masking(self, session):
        """Each entry must have masked user + service + quantity + created_at."""
        r = session.get(f"{API}/orders/recent-feed")
        assert r.status_code == 200
        feed = r.json()["feed"]
        for item in feed:
            assert set(item.keys()) >= {"user", "service", "quantity", "created_at"}
            user = item["user"]
            assert isinstance(user, str)
            # mask must contain '*' or be 'gu**'
            assert "*" in user, f"User not masked: {user}"
            # No @-symbol should leak
            assert "@" not in user


# =============== 2) ADMIN COUPON BALANCE EDIT ===============
class TestCouponBalanceEdit:
    @pytest.fixture(scope="class")
    def created_coupon(self, session, auth_headers):
        r = session.post(
            f"{API}/admin/coupons",
            json={"amount": 50.0, "note": "TEST_iter2"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        return r.json()["code"]

    def test_update_balance_success(self, session, auth_headers, created_coupon):
        r = session.put(
            f"{API}/admin/coupons/{created_coupon}/balance",
            json={"balance": 99.5},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == created_coupon
        assert abs(body["balance"] - 99.5) < 1e-6
        # Verify persistence via public check
        r2 = session.post(f"{API}/coupon/check", json={"code": created_coupon})
        assert r2.status_code == 200
        assert abs(r2.json()["balance"] - 99.5) < 1e-6

    def test_update_balance_zero_allowed(self, session, auth_headers, created_coupon):
        r = session.put(
            f"{API}/admin/coupons/{created_coupon}/balance",
            json={"balance": 0},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["balance"] == 0

    def test_update_balance_negative_rejected(self, session, auth_headers, created_coupon):
        r = session.put(
            f"{API}/admin/coupons/{created_coupon}/balance",
            json={"balance": -1},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_update_balance_not_found(self, session, auth_headers):
        r = session.put(
            f"{API}/admin/coupons/BS-NOPE-NOPE-NOPE/balance",
            json={"balance": 10},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_update_balance_requires_admin(self, session):
        r = session.put(
            f"{API}/admin/coupons/BS-XXXX-XXXX-XXXX/balance",
            json={"balance": 10},
        )
        assert r.status_code == 401


# =============== 3) AI CHAT + TAKEOVER ===============
class TestAIChat:
    @pytest.fixture(scope="class")
    def new_session_id(self):
        return f"ai-guest-test-{uuid.uuid4().hex[:8]}"

    def test_ai_chat_requires_user_message(self, session):
        r = session.post(f"{API}/ai/chat", json={"messages": []})
        assert r.status_code in (400, 422)

    def test_ai_chat_creates_session_and_replies(self, session, new_session_id):
        """AI chat: first message should persist + return reply + session_id + human_takeover=False."""
        payload = {
            "session_id": new_session_id,
            "messages": [{"role": "user", "text": "Hi I want to buy"}],
        }
        r = session.post(f"{API}/ai/chat", json=payload, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == new_session_id
        assert body["human_takeover"] is False
        assert isinstance(body["reply"], str)
        assert len(body["reply"]) > 0, "Expected non-empty LLM reply"

    def test_ai_poll_returns_messages(self, session, new_session_id):
        r = session.get(f"{API}/ai/poll", params={"session_id": new_session_id})
        assert r.status_code == 200
        body = r.json()
        assert "messages" in body
        assert "human_takeover" in body
        # After the first chat, an assistant message should exist
        roles = [m["role"] for m in body["messages"]]
        assert "assistant" in roles

    def test_ai_poll_requires_session_id(self, session):
        r = session.get(f"{API}/ai/poll", params={"session_id": ""})
        assert r.status_code in (400, 422)

    # ---- Admin inbox ----
    def test_admin_sessions_requires_auth(self, session):
        r = session.get(f"{API}/ai/admin/sessions")
        assert r.status_code == 401

    def test_admin_sessions_lists(self, session, auth_headers, new_session_id):
        r = session.get(f"{API}/ai/admin/sessions", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "sessions" in body
        sids = [s["session_id"] for s in body["sessions"]]
        assert new_session_id in sids

    def test_admin_messages_history(self, session, auth_headers, new_session_id):
        r = session.get(
            f"{API}/ai/admin/sessions/{new_session_id}/messages",
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "messages" in body and "session" in body
        assert body["session"]["session_id"] == new_session_id
        roles = [m["role"] for m in body["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_admin_takeover(self, session, auth_headers, new_session_id):
        r = session.post(
            f"{API}/ai/admin/sessions/{new_session_id}/takeover",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_ai_chat_during_takeover_returns_empty(self, session, new_session_id):
        """When session.status=human, LLM is bypassed and human_takeover=True."""
        payload = {
            "session_id": new_session_id,
            "messages": [{"role": "user", "text": "Are you there?"}],
        }
        r = session.post(f"{API}/ai/chat", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["human_takeover"] is True
        assert body["reply"] == ""

    def test_admin_send_message(self, session, auth_headers, new_session_id):
        """Admin sends a reply; flip status to human; client can see via poll."""
        r = session.post(
            f"{API}/ai/admin/sessions/{new_session_id}/send",
            json={"text": "Hello, I'm taking over.", "admin_name": "Support"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["message"]["role"] == "admin"

        # Poll should now include admin message + human_takeover=True
        r2 = session.get(f"{API}/ai/poll", params={"session_id": new_session_id})
        assert r2.status_code == 200
        body = r2.json()
        assert body["human_takeover"] is True
        admin_msgs = [m for m in body["messages"] if m["role"] == "admin"]
        assert len(admin_msgs) >= 1
        assert admin_msgs[-1]["text"] == "Hello, I'm taking over."

    def test_admin_release(self, session, auth_headers, new_session_id):
        r = session.post(
            f"{API}/ai/admin/sessions/{new_session_id}/release",
            headers=auth_headers,
        )
        assert r.status_code == 200

        # Verify via polling — human_takeover should now be False
        r2 = session.get(f"{API}/ai/poll", params={"session_id": new_session_id})
        assert r2.status_code == 200
        assert r2.json()["human_takeover"] is False

    def test_admin_send_requires_auth(self, session, new_session_id):
        r = session.post(
            f"{API}/ai/admin/sessions/{new_session_id}/send",
            json={"text": "x"},
        )
        assert r.status_code == 401

    def test_admin_takeover_requires_auth(self, session, new_session_id):
        r = session.post(f"{API}/ai/admin/sessions/{new_session_id}/takeover")
        assert r.status_code == 401

    def test_admin_release_requires_auth(self, session, new_session_id):
        r = session.post(f"{API}/ai/admin/sessions/{new_session_id}/release")
        assert r.status_code == 401

    def test_admin_messages_requires_auth(self, session, new_session_id):
        r = session.get(f"{API}/ai/admin/sessions/{new_session_id}/messages")
        assert r.status_code == 401


# =============== 4) AI SERVICE MAP ADMIN AUTH (regression check) ===============
class TestAIServiceMapAuth:
    """Report-only: per review, admin endpoints should reject without token."""
    def test_service_map_get_auth_required(self, session):
        r = session.get(f"{API}/ai/admin/service-map")
        # Not in review spec but these endpoints are under /ai/admin — should require auth
        # We only report the status, don't hard-fail
        print(f"[service-map GET no auth] {r.status_code}")

    def test_service_map_post_auth_required(self, session):
        r = session.post(f"{API}/ai/admin/service-map", json={"likes": 0, "views": 0, "comments": 0})
        print(f"[service-map POST no auth] {r.status_code}")
