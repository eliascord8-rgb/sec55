"""Backend regression tests for Iteration 4 — AI chat file/image attachments.

Covers:
- POST /api/ai/upload (public) — accept images & docs, reject unsupported mime,
  empty file, and >8MB payloads (413).
- GET /api/ai/uploads/{id} — serves file with correct content-type;
  404 on unknown id; 400 on malformed id.
- POST /api/ai/attach-message (public) — persists user message with attachments[],
  creates assistant ack (status!=human), rejects empty, rejects mismatched session.
- GET /api/ai/admin/sessions/{sid}/messages (admin) — attachments[] intact.
"""

import io
import os
import uuid

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to reading the frontend .env so pytest can be invoked from /app
    try:
        with open("/app/frontend/.env") as f:
            for ln in f:
                if ln.startswith("REACT_APP_BACKEND_URL"):
                    BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass

ADMIN_USER = "Balkin99"
ADMIN_PASS = "Armin1234"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def session_id():
    return f"TEST_sess_{uuid.uuid4().hex[:12]}"


def _png_bytes(size=(8, 8), color=(255, 0, 127)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ---------- /api/ai/upload ----------
class TestUpload:
    def test_upload_png_success(self, api, session_id):
        data = _png_bytes()
        r = api.post(
            f"{BASE_URL}/api/ai/upload",
            data={"session_id": session_id},
            files={"file": ("t.png", data, "image/png")},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("id", "url", "filename", "content_type", "size_bytes", "is_image"):
            assert k in body, f"missing key {k}"
        assert body["content_type"] == "image/png"
        assert body["is_image"] is True
        assert body["size_bytes"] == len(data)
        assert body["url"].endswith(body["id"])
        # Persist id on module for downstream tests
        pytest.uploaded_png_id = body["id"]

    def test_upload_pdf_success(self, api, session_id):
        # minimal valid-ish pdf header
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        r = api.post(
            f"{BASE_URL}/api/ai/upload",
            data={"session_id": session_id},
            files={"file": ("d.pdf", pdf, "application/pdf")},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_image"] is False
        pytest.uploaded_pdf_id = r.json()["id"]

    def test_upload_reject_unsupported_mime(self, api, session_id):
        r = api.post(
            f"{BASE_URL}/api/ai/upload",
            data={"session_id": session_id},
            files={"file": ("clip.mp4", b"\x00\x00\x00 ftypmp42", "video/mp4")},
            timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_upload_reject_empty_file(self, api, session_id):
        r = api.post(
            f"{BASE_URL}/api/ai/upload",
            data={"session_id": session_id},
            files={"file": ("empty.png", b"", "image/png")},
            timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_upload_reject_oversize(self, api, session_id):
        # 8 MB + 1 byte of bogus png-content – mime accepted, size rejected
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (8 * 1024 * 1024)
        r = api.post(
            f"{BASE_URL}/api/ai/upload",
            data={"session_id": session_id},
            files={"file": ("big.png", big, "image/png")},
            timeout=60,
        )
        assert r.status_code == 413, r.text

    def test_upload_missing_session_id(self, api):
        data = _png_bytes()
        # FastAPI Form(...) missing field → 422
        r = api.post(
            f"{BASE_URL}/api/ai/upload",
            files={"file": ("t.png", data, "image/png")},
            timeout=30,
        )
        assert r.status_code in (400, 422), r.text


# ---------- /api/ai/uploads/{id} ----------
class TestFetchUpload:
    def test_fetch_png_returns_bytes(self, api):
        fid = getattr(pytest, "uploaded_png_id", None)
        assert fid, "upload test must run first"
        r = api.get(f"{BASE_URL}/api/ai/uploads/{fid}", timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert len(r.content) > 50  # real png bytes

    def test_fetch_unknown_id_returns_404(self, api):
        r = api.get(f"{BASE_URL}/api/ai/uploads/{'a' * 32}", timeout=30)
        assert r.status_code == 404, r.text

    def test_fetch_malformed_id_returns_400(self, api):
        # uppercase / non-hex → fails the hex regex
        r = api.get(f"{BASE_URL}/api/ai/uploads/NOT_a_valid_id!!", timeout=30)
        assert r.status_code == 400, r.text


# ---------- /api/ai/attach-message ----------
class TestAttachMessage:
    def test_attach_message_persists_and_acks(self, api, session_id, admin_token):
        fid = getattr(pytest, "uploaded_png_id", None)
        assert fid
        r = api.post(
            f"{BASE_URL}/api/ai/attach-message",
            json={"session_id": session_id, "file_ids": [fid], "text": "screenshot fyi"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert len(body["attachments"]) == 1
        assert body["attachments"][0]["id"] == fid

        # Confirm message + attachments via admin endpoint
        r2 = api.get(
            f"{BASE_URL}/api/ai/admin/sessions/{session_id}/messages",
            headers={"x-admin-token": admin_token},
            timeout=30,
        )
        assert r2.status_code == 200, r2.text
        msgs = r2.json() if isinstance(r2.json(), list) else r2.json().get("items") or r2.json().get("messages") or []
        # Unwrap common shapes
        if isinstance(msgs, dict):
            msgs = msgs.get("items") or []
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        assert user_msgs, f"no user msgs in {msgs}"
        last_user = user_msgs[-1]
        assert last_user.get("text") == "screenshot fyi"
        atts = last_user.get("attachments") or []
        assert len(atts) == 1
        assert atts[0]["id"] == fid
        for k in ("filename", "content_type", "size_bytes"):
            assert k in atts[0], f"missing {k}"
        # assistant ack should exist too
        assert any(m.get("role") == "assistant" for m in msgs)

    def test_attach_message_rejects_empty(self, api, session_id):
        r = api.post(
            f"{BASE_URL}/api/ai/attach-message",
            json={"session_id": session_id, "file_ids": [], "text": ""},
            timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_attach_message_rejects_missing_session(self, api):
        r = api.post(
            f"{BASE_URL}/api/ai/attach-message",
            json={"session_id": "", "file_ids": [], "text": "hi"},
            timeout=30,
        )
        assert r.status_code in (400, 422), r.text

    def test_attach_message_rejects_mismatched_session(self, api, session_id):
        # Create a fresh upload bound to session A, try to attach under session B
        fresh_sid = f"TEST_sess_{uuid.uuid4().hex[:12]}"
        up = api.post(
            f"{BASE_URL}/api/ai/upload",
            data={"session_id": fresh_sid},
            files={"file": ("x.png", _png_bytes(), "image/png")},
            timeout=30,
        )
        assert up.status_code == 200
        foreign_id = up.json()["id"]

        # Try to attach foreign file under the original test session
        r = api.post(
            f"{BASE_URL}/api/ai/attach-message",
            json={"session_id": session_id, "file_ids": [foreign_id], "text": ""},
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400 mismatched session, got {r.status_code}: {r.text}"
