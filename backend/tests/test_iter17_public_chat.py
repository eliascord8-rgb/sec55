"""Iteration 17 — Public shoutbox backend tests.
- POST /api/public-chat/send (auth-required, 3s rate limit)
- GET  /api/public-chat/messages (no auth required)
"""
import os
import re
import time
import uuid
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://smm-direct-order.preview.emergentagent.com").rstrip("/")


def _solve(q):
    m = re.search(r"(\d+)\s*([+\-])\s*(\d+)", q)
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    return a + b if op == "+" else a - b


def _login(username, password):
    c = requests.get(f"{BASE}/api/auth/captcha", timeout=15).json()
    ans = _solve(c["question"])
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"identifier": username, "password": password, "captcha_id": c["id"], "captcha_answer": str(ans)},
        timeout=15,
    )
    assert r.status_code == 200, f"login {username}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def tok_user():
    return _login("testbugfix1", "password1")


@pytest.fixture(scope="module")
def tok_owner():
    return _login("Balkin", "Dennis123.@@")


class TestPublicChat:
    def test_get_messages_no_auth(self):
        """GET /public-chat/messages should be public."""
        r = requests.get(f"{BASE}/api/public-chat/messages", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "messages" in data and isinstance(data["messages"], list)

    def test_send_requires_auth(self):
        r = requests.post(f"{BASE}/api/public-chat/send", json={"text": "no-auth"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_send_and_appear(self, tok_user):
        # Wait past any pre-existing rate limit window
        time.sleep(4)
        marker = f"pytest-iter17-{uuid.uuid4().hex[:8]}"
        r = requests.post(
            f"{BASE}/api/public-chat/send",
            headers={"Authorization": f"Bearer {tok_user}"},
            json={"text": marker},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True and body.get("id")
        # Verify list contains it
        time.sleep(0.5)
        r2 = requests.get(f"{BASE}/api/public-chat/messages?limit=50", timeout=15)
        assert r2.status_code == 200
        msgs = r2.json()["messages"]
        found = [m for m in msgs if m.get("text") == marker]
        assert found, f"posted marker {marker} not in feed"
        m = found[-1]
        assert m["username"] == "testbugfix1"
        assert "_id" not in m  # Mongo _id must be excluded
        assert "id" in m and "role" in m and "created_at" in m

    def test_rate_limit_3s(self, tok_user):
        time.sleep(4)
        h = {"Authorization": f"Bearer {tok_user}"}
        r1 = requests.post(f"{BASE}/api/public-chat/send", headers=h, json={"text": "rl-a"}, timeout=15)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE}/api/public-chat/send", headers=h, json={"text": "rl-b"}, timeout=15)
        assert r2.status_code == 429
        assert "slow" in r2.json().get("detail", "").lower()
        # After 3.5s should work again
        time.sleep(3.6)
        r3 = requests.post(f"{BASE}/api/public-chat/send", headers=h, json={"text": "rl-c"}, timeout=15)
        assert r3.status_code == 200

    def test_since_polling_filter(self, tok_user):
        # First get current latest ts
        r0 = requests.get(f"{BASE}/api/public-chat/messages?limit=1", timeout=15).json()
        latest_ts = r0["messages"][-1]["created_at"] if r0["messages"] else "1970-01-01T00:00:00+00:00"
        time.sleep(4)
        marker = f"since-{uuid.uuid4().hex[:6]}"
        requests.post(
            f"{BASE}/api/public-chat/send",
            headers={"Authorization": f"Bearer {tok_user}"},
            json={"text": marker},
            timeout=15,
        )
        time.sleep(0.4)
        r = requests.get(f"{BASE}/api/public-chat/messages?since={latest_ts}", timeout=15)
        assert r.status_code == 200
        msgs = r.json()["messages"]
        assert any(m["text"] == marker for m in msgs)
        # All returned messages must have created_at >= since (server uses $gt but timestamps may collide at ms precision)
        for m in msgs:
            assert m["created_at"] >= latest_ts

    def test_owner_role_present(self, tok_owner):
        time.sleep(4)
        marker = f"owner-{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{BASE}/api/public-chat/send",
            headers={"Authorization": f"Bearer {tok_owner}"},
            json={"text": marker},
            timeout=15,
        )
        assert r.status_code == 200
        time.sleep(0.3)
        msgs = requests.get(f"{BASE}/api/public-chat/messages?limit=20", timeout=15).json()["messages"]
        mine = [m for m in msgs if m["text"] == marker]
        assert mine, "Owner message not in feed"
        assert mine[-1]["role"] == "owner", f"Balkin role should be 'owner', got {mine[-1]['role']}"
        assert mine[-1]["username"] == "Balkin"

    def test_input_length_limit(self, tok_user):
        time.sleep(4)
        r = requests.post(
            f"{BASE}/api/public-chat/send",
            headers={"Authorization": f"Bearer {tok_user}"},
            json={"text": "x" * 1000},
            timeout=15,
        )
        # Pydantic should reject >500 with 422
        assert r.status_code in (422, 400)
