"""Iteration 40 focused tests: admin alerts, DB manager, Discord manager, NOWPayments signature, TikTok probe."""
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
import requests
from dotenv import dotenv_values

FRONTEND_ENV = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FRONTEND_ENV.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing")
API = f"{BASE_URL}/api"
CREDS_PATH = Path("/app/memory/test_credentials.md")


def _credentials(section_name: str) -> dict:
    content = CREDS_PATH.read_text(encoding="utf-8")
    section_match = re.search(rf"(?ims)^##\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^##\s|\Z)", content)
    if not section_match:
        pytest.fail(f"Credential section missing: {section_name}")
    section = section_match.group(1)
    username = re.search(r"(?im)^\s*-\s*Username:\s*(.+?)\s*$", section)
    password = re.search(r"(?im)^\s*-\s*Password:\s*(.+?)\s*$", section)
    if not username or not password:
        pytest.fail(f"Credentials missing: {section_name}")
    return {"username": username.group(1).strip(), "password": password.group(1).strip()}


def _admin_secret() -> str:
    content = CREDS_PATH.read_text(encoding="utf-8")
    match = re.search(r'POST /api/admin/login-secret with \{"secret": "([^"]+)"\}', content)
    if not match:
        pytest.fail("Admin secret missing")
    return match.group(1)


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data["question"])
    assert match, data
    left, op, right = int(match.group(1)), match.group(2), int(match.group(3))
    answer = {"+": left + right, "-": left - right, "*": left * right}[op]
    return data["id"], str(answer)


@pytest.fixture(scope="module")
def session():
    value = requests.Session()
    value.headers.update({"Content-Type": "application/json"})
    yield value
    value.close()


@pytest.fixture(scope="module")
def contexts(session):
    admin = session.post(f"{API}/admin/login-secret", json={"secret": _admin_secret()}, timeout=20)
    assert admin.status_code == 200, admin.text
    admin_token = admin.json().get("token")
    assert isinstance(admin_token, str) and admin_token

    regular = _credentials("Regular test user")
    captcha_id, captcha_answer = _solve_captcha(session)
    login = session.post(
        f"{API}/auth/login",
        json={
            "identifier": regular["username"],
            "password": regular["password"],
            "captcha_id": captcha_id,
            "captcha_answer": captcha_answer,
        },
        timeout=20,
    )
    assert login.status_code == 200, login.text
    login_data = login.json()
    assert login_data.get("user", {}).get("username") == regular["username"]
    return {
        "admin_headers": {"X-Admin-Token": admin_token},
        "user_headers": {"Authorization": f"Bearer {login_data['token']}"},
        "user": login_data["user"],
    }


def _insert(session, headers, collection: str, doc: dict):
    response = session.post(f"{API}/dbadmin/{collection}/doc", headers=headers, json={"doc": doc}, timeout=20)
    assert response.status_code == 200, response.text
    assert response.json().get("ok") is True


def _delete(session, headers, collection: str, doc_id: str):
    response = session.delete(f"{API}/dbadmin/{collection}/doc/{quote(str(doc_id), safe='')}", headers=headers, timeout=20)
    assert response.status_code in (200, 404), response.text


def _docs(session, headers, collection: str, *, q: str = "", filter_doc: dict | None = None):
    params = {"limit": 100}
    if q:
        params["q"] = q
    if filter_doc is not None:
        params["filter_json"] = json.dumps(filter_doc, separators=(",", ":"))
    response = session.get(f"{API}/dbadmin/{collection}/docs", headers=headers, params=params, timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("docs"), list)
    return data


# Admin alerts and partial-credit workflow must persist all wallet and alert changes.
def test_admin_alert_partial_credit_full_workflow(session, contexts):
    headers = contexts["admin_headers"]
    initial = session.get(f"{API}/admin/alerts", headers=headers, timeout=20)
    assert initial.status_code == 200, initial.text
    assert isinstance(initial.json().get("alerts"), list)

    users = _docs(session, headers, "users", q="testbugfix1")
    matches = [u for u in users["docs"] if u.get("username") == "testbugfix1"]
    assert len(matches) == 1, users
    user_id = matches[0]["id"]
    tx_id = f"test-underpaid-tx1-{uuid.uuid4().hex[:8]}"
    alert_id = f"test-alert-1-{uuid.uuid4().hex[:8]}"
    bonus_ids = []
    try:
        _insert(session, headers, "transactions", {
            "id": tx_id, "user_id": user_id, "username": "testbugfix1", "amount": 100.0,
            "method": "nowpayments", "status": "underpaid", "type": "deposit", "paid_usd": 93.0,
            "missing_usd": 7.0, "created_at": "2026-07-26T20:00:00+00:00",
        })
        _insert(session, headers, "admin_alerts", {
            "id": alert_id, "type": "underpaid_deposit", "status": "open", "tx_id": tx_id,
            "user_id": user_id, "username": "testbugfix1", "invoice_amount": 100.0,
            "paid_usd": 93.0, "missing_usd": 7.0, "created_at": "2026-07-26T20:00:00+00:00",
        })
        alerts = session.get(f"{API}/admin/alerts", headers=headers, timeout=20)
        assert alerts.status_code == 200, alerts.text
        alert = next((a for a in alerts.json()["alerts"] if a.get("id") == alert_id), None)
        assert alert and alert["paid_usd"] == 93.0 and alert["missing_usd"] == 7.0

        credit = session.post(f"{API}/admin/deposits/{tx_id}/credit-partial", headers=headers, json={"amount": 93}, timeout=20)
        assert credit.status_code == 200, credit.text
        assert credit.json().get("ok") is True
        assert credit.json().get("credited") == pytest.approx(93.0)
        assert credit.json().get("bonus") == pytest.approx(65.1)

        tx_docs = _docs(session, headers, "transactions", filter_doc={"id": tx_id})["docs"]
        assert len(tx_docs) == 1
        tx = tx_docs[0]
        assert tx["status"] == "approved" and tx["amount"] == pytest.approx(93.0)
        assert tx["partial_credit"] is True and tx["original_invoice_amount"] == pytest.approx(100.0)

        bonus_docs = _docs(session, headers, "transactions", filter_doc={"linked_tx": tx_id, "type": "deposit_bonus"})["docs"]
        assert len(bonus_docs) == 1
        assert bonus_docs[0]["amount"] == pytest.approx(65.1)
        assert bonus_docs[0]["status"] == "approved"
        bonus_ids = [d["id"] for d in bonus_docs]

        alert_docs = _docs(session, headers, "admin_alerts", filter_doc={"id": alert_id})["docs"]
        assert len(alert_docs) == 1 and alert_docs[0]["status"] == "resolved"
        assert alert_docs[0]["credited_amount"] == pytest.approx(93.0)
    finally:
        for bonus_id in bonus_ids:
            _delete(session, headers, "transactions", bonus_id)
        _delete(session, headers, "transactions", tx_id)
        _delete(session, headers, "admin_alerts", alert_id)


# Dismiss is one-shot and a repeated dismissal must return 404.
def test_admin_alert_dismiss_is_idempotency_guarded(session, contexts):
    headers = contexts["admin_headers"]
    alert_id = f"TEST_iter40_dismiss_{uuid.uuid4().hex}"
    try:
        _insert(session, headers, "admin_alerts", {
            "id": alert_id, "type": "underpaid_deposit", "status": "open", "tx_id": "TEST_none",
            "user_id": contexts["user"]["id"], "username": "testbugfix1", "invoice_amount": 10,
            "paid_usd": 9, "missing_usd": 1, "created_at": "2026-07-26T20:00:00+00:00",
        })
        first = session.post(f"{API}/admin/alerts/{alert_id}/dismiss", headers=headers, timeout=20)
        assert first.status_code == 200 and first.json() == {"ok": True}
        persisted = _docs(session, headers, "admin_alerts", filter_doc={"id": alert_id})["docs"]
        assert len(persisted) == 1 and persisted[0]["status"] == "dismissed"
        second = session.post(f"{API}/admin/alerts/{alert_id}/dismiss", headers=headers, timeout=20)
        assert second.status_code == 404, second.text
        assert "already resolved" in second.json().get("detail", "")
    finally:
        _delete(session, headers, "admin_alerts", alert_id)


# Owner-only generic DB CRUD and destructive-delete guard.
def test_dbmanager_owner_crud_and_authorization(session, contexts):
    headers = contexts["admin_headers"]
    missing = session.get(f"{API}/dbadmin/collections", timeout=20)
    assert missing.status_code in (401, 403), missing.text

    collections = session.get(f"{API}/dbadmin/collections", headers=headers, timeout=20)
    assert collections.status_code == 200, collections.text
    rows = collections.json().get("collections")
    assert isinstance(rows, list) and rows
    assert all(isinstance(c.get("name"), str) and isinstance(c.get("count"), int) for c in rows)

    first_id = f"TEST_iter40_scratch_{uuid.uuid4().hex}"
    second_id = f"TEST_iter40_scratch_{uuid.uuid4().hex}"
    try:
        _insert(session, headers, "test_scratch", {"id": first_id, "name": "TEST_initial", "value": 1})
        created = _docs(session, headers, "test_scratch", filter_doc={"id": first_id})["docs"]
        assert len(created) == 1 and created[0]["value"] == 1

        update = session.put(
            f"{API}/dbadmin/test_scratch/doc/{first_id}", headers=headers,
            json={"doc": {"name": "TEST_updated", "value": 2}}, timeout=20,
        )
        assert update.status_code == 200 and update.json().get("ok") is True
        updated = _docs(session, headers, "test_scratch", filter_doc={"id": first_id})["docs"]
        assert updated[0]["name"] == "TEST_updated" and updated[0]["value"] == 2

        deleted = session.delete(f"{API}/dbadmin/test_scratch/doc/{first_id}", headers=headers, timeout=20)
        assert deleted.status_code == 200 and deleted.json() == {"ok": True}
        assert _docs(session, headers, "test_scratch", filter_doc={"id": first_id})["total"] == 0

        _insert(session, headers, "test_scratch", {"id": first_id, "name": "TEST_bulk"})
        _insert(session, headers, "test_scratch", {"id": second_id, "name": "TEST_bulk"})
        guarded = session.post(
            f"{API}/dbadmin/test_scratch/delete-many", headers=headers,
            json={"filter": {}, "confirm_all": False}, timeout=20,
        )
        assert guarded.status_code == 400, guarded.text
        confirmed = session.post(
            f"{API}/dbadmin/test_scratch/delete-many", headers=headers,
            json={"filter": {}, "confirm_all": True}, timeout=20,
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json().get("deleted", 0) >= 2
        assert _docs(session, headers, "test_scratch")["total"] == 0
    finally:
        _delete(session, headers, "test_scratch", first_id)
        _delete(session, headers, "test_scratch", second_id)


# Discord settings persist while actions requiring a running bot fail safely. Never starts the real bot.
def test_discord_stopped_manager_contract(session, contexts):
    headers = contexts["admin_headers"]
    before = session.get(f"{API}/admin/discord/status", headers=headers, timeout=20)
    assert before.status_code == 200, before.text
    original_words = before.json().get("banned_words", "")
    original_activity = before.json().get("saved_activity_text", "")
    try:
        data = before.json()
        assert data.get("status") == "stopped"
        assert data.get("token_saved") is True

        words = session.post(
            f"{API}/admin/discord/mod-words", headers=headers,
            json={"banned_words": "scamword1, scamword2"}, timeout=20,
        )
        assert words.status_code == 200 and words.json() == {"ok": True}
        status = session.get(f"{API}/admin/discord/status", headers=headers, timeout=20).json()
        assert status["banned_words"] == "scamword1, scamword2"

        activity = session.post(f"{API}/admin/discord/activity", headers=headers, json={"text": "Testing"}, timeout=20)
        assert activity.status_code == 409, activity.text
        assert "not running" in activity.json().get("detail", "").lower()

        dm = session.post(f"{API}/admin/discord/dms/12345/send", headers=headers, json={"text": "hi"}, timeout=20)
        assert dm.status_code == 409, dm.text
        assert "not running" in dm.json().get("detail", "").lower()

        convos = session.get(f"{API}/admin/discord/dms", headers=headers, timeout=20)
        assert convos.status_code == 200, convos.text
        assert convos.json() == {"conversations": []}
    finally:
        session.post(f"{API}/admin/discord/mod-words", headers=headers, json={"banned_words": original_words}, timeout=20)
        session.post(f"{API}/admin/discord/activity", headers=headers, json={"text": original_activity}, timeout=20)


# NOWPayments must reject unsigned webhooks when an IPN secret is configured.
def test_nowpayments_webhook_rejects_missing_signature(session, contexts):
    marker = f"TEST_iter40_webhook_{uuid.uuid4().hex}"
    response = session.post(
        f"{API}/nowpayments/webhook",
        json={"order_id": marker, "payment_status": "finished", "actually_paid": 1}, timeout=20,
    )
    assert response.status_code == 401, response.text
    assert response.json().get("detail") == "Invalid signature"
    # The implementation intentionally logs rejected events; remove this test event.
    events = _docs(session, contexts["admin_headers"], "nowpayments_events", filter_doc={"payload.order_id": marker})["docs"]
    for event in events:
        _delete(session, contexts["admin_headers"], "nowpayments_events", event.get("id") or event.get("_id"))


# Authenticated TikTok debug probe must return a definitive boolean without exceptions.
def test_tiktok_debug_offline_account(session, contexts):
    response = session.get(f"{API}/debug/tiktok-live/tiktok", headers=contexts["user_headers"], timeout=35)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("handle") == "tiktok"
    assert data.get("is_live") is False
    assert isinstance(data.get("is_live"), bool)
