"""Backend tests for iteration 9: typing indicator, report chat, admin reports, TURN, voice transcode."""
import os
import time
import subprocess
import tempfile
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://smm-direct-order.preview.emergentagent.com").rstrip("/")

OWNER_ID = "4dd02b7a-f869-4642-9304-35e9e66402fc"
USER_ID = "37a72bb9-3687-4fa6-848e-3e4265237636"


def _login(identifier: str, password: str) -> str:
    c = requests.get(f"{BASE}/api/auth/captcha", timeout=15).json()
    ans = str(eval(c["question"].replace("What is ", "").replace("?", "")))
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"identifier": identifier, "password": password, "captcha_id": c["id"], "captcha_answer": ans},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def user_token():
    return _login("testbugfix1", "password1")


@pytest.fixture(scope="module")
def owner_token():
    return _login("Balkin", "Dennis123.@@")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ============ Typing indicator ============
class TestTypingIndicator:
    def test_typing_post_and_get_roundtrip(self, user_token, owner_token):
        # user signals typing to owner
        r = requests.post(f"{BASE}/api/messages/typing", json={"to_id": OWNER_ID, "typing": True}, headers=_h(user_token), timeout=10)
        assert r.status_code == 200 and r.json().get("ok") is True

        # owner polls: should see user typing
        r2 = requests.get(f"{BASE}/api/messages/typing/{USER_ID}", headers=_h(owner_token), timeout=10)
        assert r2.status_code == 200
        assert r2.json().get("typing") is True

    def test_typing_expires_after_5s(self, user_token, owner_token):
        requests.post(f"{BASE}/api/messages/typing", json={"to_id": OWNER_ID, "typing": True}, headers=_h(user_token))
        time.sleep(6)
        r = requests.get(f"{BASE}/api/messages/typing/{USER_ID}", headers=_h(owner_token))
        assert r.json().get("typing") is False

    def test_typing_requires_auth(self):
        r = requests.post(f"{BASE}/api/messages/typing", json={"to_id": OWNER_ID, "typing": True})
        assert r.status_code in (401, 403)


# ============ Report Chat ============
_report_id_holder = {}


class TestReportChat:
    def test_user_reports_owner(self, user_token):
        r = requests.post(
            f"{BASE}/api/messages/report",
            json={"reported_user_id": OWNER_ID, "reason": "harassment test - iteration9"},
            headers=_h(user_token),
            timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert "id" in data
        _report_id_holder["id"] = data["id"]

    def test_cant_report_self(self, user_token):
        r = requests.post(
            f"{BASE}/api/messages/report",
            json={"reported_user_id": USER_ID, "reason": "self"},
            headers=_h(user_token),
        )
        assert r.status_code == 400


# ============ Admin Reports ============
class TestAdminReports:
    def test_regular_user_cant_list_reports(self, user_token):
        r = requests.get(f"{BASE}/api/admin/messages/reports", headers=_h(user_token))
        assert r.status_code == 403

    def test_admin_list_reports_includes_new(self, owner_token):
        r = requests.get(f"{BASE}/api/admin/messages/reports", headers=_h(owner_token))
        assert r.status_code == 200
        reports = r.json().get("reports", [])
        assert isinstance(reports, list)
        assert any(x.get("id") == _report_id_holder.get("id") for x in reports), "new report should appear in list"

    def test_admin_view_reported_thread(self, owner_token):
        rid = _report_id_holder.get("id")
        assert rid
        r = requests.get(f"{BASE}/api/admin/messages/reports/{rid}/thread", headers=_h(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert "report" in data and "messages" in data
        assert isinstance(data["messages"], list)

    def test_admin_view_nonexistent_report(self, owner_token):
        r = requests.get(f"{BASE}/api/admin/messages/reports/does-not-exist/thread", headers=_h(owner_token))
        assert r.status_code == 404


# ============ TURN config ============
class TestTurnConfig:
    def test_regular_user_cannot_get_turn(self, user_token):
        r = requests.get(f"{BASE}/api/admin/calls/turn-config", headers=_h(user_token))
        assert r.status_code == 403

    def test_admin_set_and_ice_reflects(self, owner_token, user_token):
        # Set custom TURN
        r = requests.post(
            f"{BASE}/api/admin/calls/turn-config",
            json={"urls": "turn:example.com:3478", "username": "user", "credential": "pass"},
            headers=_h(owner_token),
        )
        assert r.status_code == 200 and r.json().get("ok") is True

        # Get should return
        r2 = requests.get(f"{BASE}/api/admin/calls/turn-config", headers=_h(owner_token))
        assert r2.status_code == 200
        cfg = r2.json()
        assert "example.com" in cfg["urls"]

        # ice-config reflects it
        r3 = requests.get(f"{BASE}/api/calls/ice-config", headers=_h(user_token))
        assert r3.status_code == 200
        urls = " ".join(s.get("urls", "") for s in r3.json()["iceServers"])
        assert "example.com" in urls

    def test_clear_reverts_to_openrelay(self, owner_token, user_token):
        r = requests.post(
            f"{BASE}/api/admin/calls/turn-config",
            json={"urls": "", "username": "", "credential": ""},
            headers=_h(owner_token),
        )
        assert r.status_code == 200

        r2 = requests.get(f"{BASE}/api/calls/ice-config", headers=_h(user_token))
        urls = " ".join(s.get("urls", "") for s in r2.json()["iceServers"])
        assert "openrelay.metered.ca" in urls
        assert "example.com" not in urls


# ============ Voice transcode ============
class TestVoiceTranscode:
    def test_webm_opus_transcoded_to_mp3(self, user_token):
        # Create a small webm/opus audio using ffmpeg
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tmp = tf.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                 "-c:a", "libopus", "-b:a", "32k", tmp],
                check=True, capture_output=True,
            )
            with open(tmp, "rb") as f:
                files = {"file": ("note.webm", f, "audio/webm")}
                data = {"kind": "voice"}
                r = requests.post(f"{BASE}/api/messages/upload", files=files, data=data, headers=_h(user_token), timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["url"].endswith(".mp3"), f"URL should be .mp3, got {body['url']}"
            assert body["content_type"] == "audio/mpeg"

            # GET the file
            file_url = f"{BASE}{body['url']}"
            gr = requests.get(file_url, timeout=15)
            assert gr.status_code == 200
            assert gr.headers.get("content-type", "").startswith("audio/mpeg")
            # Validate mp3 magic bytes (ID3 or 0xFFF sync)
            first = gr.content[:3]
            assert first == b"ID3" or (gr.content[0] == 0xFF and (gr.content[1] & 0xE0) == 0xE0), f"not mp3 magic: {first}"
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
