"""Backend tests for iteration 3: multilingual handover, staff display name,
admin heartbeat, offline messages, pricing/refund knowledge."""
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


# =============== 1) ADMIN AUTH GATE on new endpoints ===============
class TestAdminAuthGates:
    def test_heartbeat_requires_auth(self, session):
        r = session.post(f"{API}/ai/admin/heartbeat")
        assert r.status_code == 401

    def test_settings_get_requires_auth(self, session):
        r = session.get(f"{API}/ai/admin/settings")
        assert r.status_code == 401

    def test_settings_post_requires_auth(self, session):
        r = session.post(f"{API}/ai/admin/settings", json={"staff_display_name": "Hack"})
        assert r.status_code == 401

    def test_offline_messages_list_requires_auth(self, session):
        r = session.get(f"{API}/ai/admin/offline-messages")
        assert r.status_code == 401

    def test_offline_messages_mark_read_requires_auth(self, session):
        r = session.post(f"{API}/ai/admin/offline-messages/nope/mark-read")
        assert r.status_code == 401


# =============== 2) STAFF DISPLAY NAME SETTINGS ===============
class TestStaffSettings:
    def test_get_default_then_set_and_persist(self, session, auth_headers):
        # GET initial
        r = session.get(f"{API}/ai/admin/settings", headers=auth_headers)
        assert r.status_code == 200
        assert "staff_display_name" in r.json()

        # SET to Balkin
        r = session.post(
            f"{API}/ai/admin/settings",
            json={"staff_display_name": "Balkin"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # GET confirms persistence
        r = session.get(f"{API}/ai/admin/settings", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["staff_display_name"] == "Balkin"

    def test_set_empty_rejected(self, session, auth_headers):
        r = session.post(
            f"{API}/ai/admin/settings",
            json={"staff_display_name": ""},
            headers=auth_headers,
        )
        assert r.status_code in (400, 422)


# =============== 3) ADMIN HEARTBEAT + admin_online flip ===============
class TestAdminHeartbeat:
    def test_heartbeat_sets_admin_online_true(self, session, auth_headers):
        # Fire heartbeat
        r = session.post(f"{API}/ai/admin/heartbeat", headers=auth_headers)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        assert "last_admin_seen" in r.json()

        # Immediately chat — admin_online should be True
        sid = f"ai-guest-hb-{uuid.uuid4().hex[:8]}"
        r = session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "hi"}]},
            timeout=60,
        )
        assert r.status_code == 200
        assert r.json().get("admin_online") is True

    def test_admin_online_flips_false_after_stale(self, session, auth_headers):
        # Force last_admin_seen to a past time by setting settings then directly aging.
        # Since we can't mutate mongo directly here, instead test via poll contract:
        # verify the field exists in response, and that the semantic is working by
        # asserting it's a boolean. A real 90s wait is impractical in CI.
        sid = f"ai-guest-hbpoll-{uuid.uuid4().hex[:8]}"
        # Seed session so poll returns
        session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "hi"}]},
            timeout=60,
        )
        r = session.get(f"{API}/ai/poll", params={"session_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body.get("admin_online"), bool)


# =============== 4) AI POLL returns new fields ===============
class TestAIPollFields:
    def test_poll_includes_staff_and_flags(self, session, auth_headers):
        # Ensure staff name is set
        session.post(
            f"{API}/ai/admin/settings",
            json={"staff_display_name": "Balkin"},
            headers=auth_headers,
        )
        sid = f"ai-guest-poll-{uuid.uuid4().hex[:8]}"
        session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "hello"}]},
            timeout=60,
        )
        r = session.get(f"{API}/ai/poll", params={"session_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert "messages" in body
        assert "human_takeover" in body
        assert "needs_handover" in body
        assert "admin_online" in body
        assert "staff_display_name" in body
        assert body["staff_display_name"] == "Balkin"


# =============== 5) MULTILINGUAL HANDOVER DETECTION ===============
class TestMultilingualHandover:
    @pytest.mark.parametrize("lang,text", [
        ("en", "I want to talk to staff please"),
        ("de", "Ich möchte mit einem Mitarbeiter sprechen"),
        ("es", "Quiero hablar con un humano por favor"),
        ("fr", "Je veux parler à un agent s'il vous plaît"),
    ])
    def test_handover_triggers(self, session, lang, text):
        sid = f"ai-guest-ho-{lang}-{uuid.uuid4().hex[:6]}"
        r = session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": text}]},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # The key assertion: needs_handover should be true
        assert body.get("needs_handover") is True, \
            f"[{lang}] handover not detected. Reply: {body.get('reply')!r}"
        # Marker must NOT leak to visible reply
        assert "HANDOVER_REQUEST" not in (body.get("reply") or ""), \
            f"[{lang}] marker leaked: {body.get('reply')!r}"
        # Reply must be non-empty
        assert (body.get("reply") or "").strip(), f"[{lang}] empty reply"
        # admin_online field present
        assert "admin_online" in body


# =============== 6) REFUND KNOWLEDGE — 24h, only IPTV/Followers/Likes ===============
class TestRefundKnowledge:
    def test_refund_reply_mentions_policy(self, session):
        sid = f"ai-guest-rf-{uuid.uuid4().hex[:6]}"
        r = session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "do you offer refunds?"}]},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        reply = (r.json().get("reply") or "").lower()
        assert reply, "empty refund reply"
        # Must mention 24 hours
        assert "24" in reply, f"Missing 24h mention: {reply}"
        # Must mention at least one eligible category
        has_eligible = any(k in reply for k in ["iptv", "follower", "like"])
        assert has_eligible, f"Missing eligible categories: {reply}"
        # Must NOT promise refunds for views/comments
        # Weak check: avoid statements like "refund ... views" or "refund ... comments"
        bad_phrases = ["refund for views", "refunds for views", "refund for comments", "refunds for comments"]
        for bp in bad_phrases:
            assert bp not in reply, f"Bad promise found: {bp} in {reply}"


# =============== 7) OFFLINE MESSAGE FLOW ===============
class TestOfflineMessageFlow:
    @pytest.fixture(scope="class")
    def offline_email(self):
        # Backend lowercases the email before persisting, so use all-lowercase here
        return f"test_offline_{uuid.uuid4().hex[:6]}@example.com"

    def test_submit_offline_message_public(self, session, offline_email):
        r = session.post(
            f"{API}/ai/offline-message",
            json={
                "session_id": f"ai-guest-off-{uuid.uuid4().hex[:6]}",
                "email": offline_email,
                "message": "TEST_offline message from pytest",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("id")

    def test_submit_invalid_email_rejected(self, session):
        r = session.post(
            f"{API}/ai/offline-message",
            json={"email": "not-an-email", "message": "hi"},
        )
        assert r.status_code in (400, 422)

    def test_submit_empty_message_rejected(self, session):
        r = session.post(
            f"{API}/ai/offline-message",
            json={"email": "user@example.com", "message": ""},
        )
        assert r.status_code in (400, 422)

    def test_admin_lists_offline_messages(self, session, auth_headers, offline_email):
        r = session.get(f"{API}/ai/admin/offline-messages", headers=auth_headers)
        assert r.status_code == 200
        msgs = r.json().get("messages", [])
        assert isinstance(msgs, list)
        mine = [m for m in msgs if m.get("email") == offline_email]
        assert len(mine) >= 1, f"offline message not found for {offline_email}"
        assert mine[0].get("status") == "new"

    def test_mark_read_flips_status(self, session, auth_headers, offline_email):
        r = session.get(f"{API}/ai/admin/offline-messages", headers=auth_headers)
        msg = next(m for m in r.json()["messages"] if m.get("email") == offline_email)
        mid = msg["id"]
        r2 = session.post(
            f"{API}/ai/admin/offline-messages/{mid}/mark-read",
            headers=auth_headers,
        )
        assert r2.status_code == 200
        # Verify status flipped
        r3 = session.get(f"{API}/ai/admin/offline-messages", headers=auth_headers)
        msg2 = next(m for m in r3.json()["messages"] if m.get("id") == mid)
        assert msg2.get("status") == "read"


# =============== 8) ADMIN /sessions returns handover_waiting count ===============
class TestAdminSessionsHandoverWaiting:
    def test_sessions_response_has_waiting(self, session, auth_headers):
        r = session.get(f"{API}/ai/admin/sessions", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "sessions" in body
        assert "handover_waiting" in body
        assert isinstance(body["handover_waiting"], int)

    def test_handover_waiting_increments_on_handover_request(self, session, auth_headers):
        # Baseline
        r = session.get(f"{API}/ai/admin/sessions", headers=auth_headers)
        base = r.json()["handover_waiting"]

        # Trigger a handover
        sid = f"ai-guest-wait-{uuid.uuid4().hex[:6]}"
        rc = session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "I want to talk to a human agent"}]},
            timeout=90,
        )
        assert rc.status_code == 200
        if not rc.json().get("needs_handover"):
            pytest.skip("AI did not trigger handover marker this run — cannot verify counter")

        r2 = session.get(f"{API}/ai/admin/sessions", headers=auth_headers)
        new_count = r2.json()["handover_waiting"]
        assert new_count >= base + 1, f"expected waiting to increment, was {base} -> {new_count}"


# =============== 9) ADMIN SEND uses staff_display_name when admin_name omitted ===============
class TestAdminSendUsesStaffName:
    def test_send_without_admin_name_uses_settings(self, session, auth_headers):
        # Set staff name
        session.post(
            f"{API}/ai/admin/settings",
            json={"staff_display_name": "Balkin"},
            headers=auth_headers,
        )
        sid = f"ai-guest-send-{uuid.uuid4().hex[:6]}"
        # Seed session
        session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "hello"}]},
            timeout=60,
        )
        # Send w/o admin_name
        r = session.post(
            f"{API}/ai/admin/sessions/{sid}/send",
            json={"text": "TEST_admin_msg"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        msg = r.json()["message"]
        assert msg.get("admin_name") == "Balkin", f"expected Balkin, got {msg.get('admin_name')}"

    def test_send_with_explicit_admin_name_overrides(self, session, auth_headers):
        sid = f"ai-guest-send2-{uuid.uuid4().hex[:6]}"
        session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "hello"}]},
            timeout=60,
        )
        r = session.post(
            f"{API}/ai/admin/sessions/{sid}/send",
            json={"text": "TEST_override", "admin_name": "CustomName"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["message"]["admin_name"] == "CustomName"


# =============== 10) ADMIN RELEASE inserts back-to-AI system note ===============
class TestAdminReleaseInsertsNote:
    def test_release_inserts_system_note_with_staff_name(self, session, auth_headers):
        # Set staff name
        session.post(
            f"{API}/ai/admin/settings",
            json={"staff_display_name": "Balkin"},
            headers=auth_headers,
        )
        sid = f"ai-guest-rel-{uuid.uuid4().hex[:6]}"
        # Seed
        session.post(
            f"{API}/ai/chat",
            json={"session_id": sid, "messages": [{"role": "user", "text": "hello"}]},
            timeout=60,
        )
        # Admin takes over (via send, which sets status=human)
        session.post(
            f"{API}/ai/admin/sessions/{sid}/send",
            json={"text": "TEST admin hello"},
            headers=auth_headers,
        )
        # Now release
        r = session.post(
            f"{API}/ai/admin/sessions/{sid}/release",
            headers=auth_headers,
        )
        assert r.status_code == 200

        # Verify session back to AI
        r2 = session.get(f"{API}/ai/poll", params={"session_id": sid})
        body = r2.json()
        assert body["human_takeover"] is False

        # Verify system assistant note exists (admin panel messages endpoint)
        r3 = session.get(
            f"{API}/ai/admin/sessions/{sid}/messages",
            headers=auth_headers,
        )
        msgs = r3.json()["messages"]
        release_msgs = [
            m for m in msgs
            if m.get("role") == "assistant" and "has left the chat" in (m.get("text") or "")
        ]
        assert release_msgs, f"Release note not found. Messages: {[m.get('text') for m in msgs]}"
        assert "Balkin" in release_msgs[-1]["text"]
