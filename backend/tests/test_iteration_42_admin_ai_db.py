"""Iteration 42 focused tests: sports removal, DB protections/backups, AI support, live-sub cancellation and chat."""
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

FRONTEND_ENV = dotenv_values("/app/frontend/.env")
BACKEND_ENV = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FRONTEND_ENV.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing")
API = f"{BASE_URL}/api"
CREDS_PATH = Path("/app/memory/test_credentials.md")


def _credentials(section_name: str) -> dict:
    if not CREDS_PATH.exists():
        pytest.skip("Missing /app/memory/test_credentials.md")
    content = CREDS_PATH.read_text(encoding="utf-8")
    section_match = re.search(rf"(?ims)^##\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^##\s|\Z)", content)
    if not section_match:
        pytest.skip(f"Credential section missing: {section_name}")
    section = section_match.group(1)
    username = re.search(r"(?im)^\s*-\s*Username:\s*(.+?)\s*$", section)
    password = re.search(r"(?im)^\s*-\s*Password:\s*(.+?)\s*$", section)
    if not username or not password:
        pytest.skip(f"Credentials missing: {section_name}")
    return {"username": username.group(1).strip(), "password": password.group(1).strip()}


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data["question"])
    assert match, data
    left, operator, right = int(match.group(1)), match.group(2), int(match.group(3))
    answer = {"+": left + right, "-": left - right, "*": left * right}[operator]
    return data["id"], str(answer)


def _login(session: requests.Session, section_name: str) -> dict:
    creds = _credentials(section_name)
    captcha_id, captcha_answer = _solve_captcha(session)
    response = session.post(
        f"{API}/auth/login",
        json={
            "identifier": creds["username"],
            "password": creds["password"],
            "captcha_id": captcha_id,
            "captcha_answer": captcha_answer,
        },
        timeout=30,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("token"), str) and data["token"]
    assert data.get("user", {}).get("username", "").lower() == creds["username"].lower()
    return data


def _docs(session: requests.Session, headers: dict, collection: str, filter_doc: dict | None = None) -> list:
    params = {"limit": 100}
    if filter_doc is not None:
        import json
        params["filter_json"] = json.dumps(filter_doc, separators=(",", ":"))
    response = session.get(f"{API}/dbadmin/{collection}/docs", headers=headers, params=params, timeout=30)
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("docs"), list)
    return data["docs"]


def _insert(session: requests.Session, headers: dict, collection: str, doc: dict) -> None:
    response = session.post(f"{API}/dbadmin/{collection}/doc", headers=headers, json={"doc": doc}, timeout=30)
    assert response.status_code == 200, response.text
    assert response.json().get("ok") is True


def _delete_many(session: requests.Session, headers: dict, collection: str, filter_doc: dict) -> None:
    session.post(
        f"{API}/dbadmin/{collection}/delete-many",
        headers=headers,
        json={"filter": filter_doc, "confirm_all": False},
        timeout=30,
    )


@pytest.fixture(scope="module")
def http_session():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(BACKEND_ENV["MONGO_URL"], serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    yield client[BACKEND_ENV["DB_NAME"]]
    client.close()


@pytest.fixture(scope="module")
def auth_context(http_session):
    user = _login(http_session, "Regular test user")
    owner = _login(http_session, "Owner")
    dbmanager = _login(http_session, "DB Manager owner")
    elevated = http_session.post(
        f"{API}/admin/session-from-user",
        headers={"Authorization": f"Bearer {dbmanager['token']}"},
        timeout=30,
    )
    assert elevated.status_code == 200, elevated.text
    elevation = elevated.json()
    assert elevation.get("role") == "owner"
    assert elevation.get("username", "").lower() == "dbmanager"
    assert isinstance(elevation.get("token"), str) and elevation["token"]
    return {
        "user": user["user"],
        "user_headers": {"Authorization": f"Bearer {user['token']}"},
        "owner": owner["user"],
        "owner_headers": {"Authorization": f"Bearer {owner['token']}"},
        "dbmanager": dbmanager["user"],
        "admin_token": elevation["token"],
        "admin_headers": {"X-Admin-Token": elevation["token"]},
    }


# Sports must be disabled in the feature contract.
def test_sports_feature_disabled(http_session):
    response = http_session.get(f"{API}/features", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("features", {}).get("sports") is False


# Removed sports APIs should no longer be routable.
def test_sports_api_routes_removed(http_session):
    for path in ("/sports/livescores", "/sports/upcoming", "/sports/leagues"):
        response = http_session.get(f"{API}{path}", timeout=30)
        assert response.status_code == 404, f"{path} remains active: {response.status_code} {response.text[:300]}"


# Dedicated DB-manager owner login must elevate and access the collection inventory.
def test_dbmanager_dedicated_login_and_collections(http_session, auth_context, mongo_db):
    response = http_session.get(f"{API}/dbadmin/collections", headers=auth_context["admin_headers"], timeout=30)
    assert response.status_code == 200, response.text
    rows = response.json().get("collections")
    assert isinstance(rows, list) and any(row.get("name") == "users" for row in rows)
    dbm = mongo_db.users.find_one({"id": auth_context["dbmanager"]["id"]})
    assert dbm and isinstance(dbm.get("password_hash"), str)
    assert dbm["password_hash"].startswith("$2b$")


# Users collection is immutable to destructive DB-manager operations.
def test_dbmanager_users_delete_guards(http_session, auth_context):
    headers = auth_context["admin_headers"]
    single = http_session.delete(f"{API}/dbadmin/users/doc/does-not-matter", headers=headers, timeout=20)
    assert single.status_code == 403, single.text
    assert "protected" in single.json().get("detail", "").lower()
    bulk = http_session.post(
        f"{API}/dbadmin/users/delete-many",
        headers=headers,
        json={"filter": {}, "confirm_all": True},
        timeout=20,
    )
    assert bulk.status_code == 403, bulk.text
    assert "protected" in bulk.json().get("detail", "").lower()


# DB-manager user edits may persist safe notes but must ignore balance changes.
def test_dbmanager_user_balance_field_guard(http_session, auth_context, mongo_db):
    headers = auth_context["admin_headers"]
    uid = auth_context["user"]["id"]
    original = mongo_db.users.find_one({"id": uid})
    assert original
    had_note = "note" in original
    original_note = original.get("note")
    original_balance = original.get("balance")
    try:
        response = http_session.put(
            f"{API}/dbadmin/users/doc/{quote(uid, safe='')}",
            headers=headers,
            json={"doc": {"balance": 99999, "note": "TEST_iter42_safe_note"}},
            timeout=30,
        )
        assert response.status_code == 200, response.text
        assert response.json().get("ok") is True
        persisted = mongo_db.users.find_one({"id": uid})
        assert persisted.get("balance") == original_balance
        assert persisted.get("note") == "TEST_iter42_safe_note"
    finally:
        if had_note:
            mongo_db.users.update_one({"id": uid}, {"$set": {"note": original_note}})
        else:
            mongo_db.users.update_one({"id": uid}, {"$unset": {"note": ""}})


# Manual backup lifecycle: create, list, query-token download, and delete.
def test_db_backup_full_lifecycle(http_session, auth_context, mongo_db):
    headers = auth_context["admin_headers"]
    created = http_session.post(f"{API}/admin/db-backups/run", headers=headers, json={}, timeout=120)
    assert created.status_code == 200, created.text
    snapshot = created.json()
    name = snapshot.get("name")
    assert isinstance(name, str) and name.startswith("backup_") and name.endswith(".json.gz")
    assert snapshot.get("size", 0) > 0
    assert snapshot.get("collections", 0) > 0
    assert snapshot.get("docs", 0) > 0
    try:
        listed = http_session.get(f"{API}/admin/db-backups", headers=headers, timeout=30)
        assert listed.status_code == 200, listed.text
        data = listed.json()
        assert data.get("next_run_hours") == 6
        assert any(row.get("name") == name for row in data.get("backups", []))
        download = http_session.get(
            f"{API}/admin/db-backups/{quote(name, safe='')}/download",
            params={"t": auth_context["admin_token"]},
            timeout=60,
        )
        assert download.status_code == 200, download.text[:300]
        assert download.headers.get("content-type", "").startswith("application/gzip")
        assert len(download.content) == snapshot["size"]
    finally:
        deleted = http_session.delete(f"{API}/admin/db-backups/{quote(name, safe='')}", headers=headers, timeout=30)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json().get("deleted") == name
        mongo_db.db_backups.delete_many({"name": name})
    after = http_session.get(f"{API}/admin/db-backups", headers=headers, timeout=30).json()
    assert not any(row.get("name") == name for row in after.get("backups", []))


# Admin cancellation must cancel, refund, open a ticket, and log AI/admin action history.
def test_admin_live_subscription_cancel_workflow(http_session, auth_context, mongo_db):
    headers = auth_context["admin_headers"]
    user_headers = auth_context["user_headers"]
    uid = auth_context["user"]["id"]
    marker = f"TEST_iter42_sub_{uuid.uuid4().hex}"
    spend_id = f"{marker}_spend"
    now = datetime.now(timezone.utc).isoformat()
    _insert(http_session, headers, "live_subscriptions", {
        "id": marker,
        "user_id": uid,
        "username": auth_context["user"]["username"],
        "tiktok_username": "test_iter42_handle",
        "service_id": 424242,
        "service_name": "TEST Iter42 Live Views",
        "status": "waiting_for_live",
        "total_spent": 1.25,
        "created_at": now,
    })
    _insert(http_session, headers, "transactions", {
        "id": spend_id,
        "user_id": uid,
        "username": auth_context["user"]["username"],
        "amount": -1.25,
        "method": "balance",
        "status": "approved",
        "type": "live_sub_burst",
        "live_sub_id": marker,
        "created_at": now,
    })
    ticket_id = None
    try:
        before = http_session.get(f"{API}/client/balance", headers=user_headers, timeout=20).json()["balance"]
        listed = http_session.get(f"{API}/admin/live-subs", headers=headers, params={"q": "test_iter42_handle"}, timeout=30)
        assert listed.status_code == 200, listed.text
        assert any(row.get("id") == marker and row.get("status") == "waiting_for_live" for row in listed.json().get("subs", []))
        cancelled = http_session.post(
            f"{API}/admin/live-subs/{marker}/cancel",
            headers=headers,
            json={"refund_amount": 1.25, "reason": "TEST iteration 42 admin cancellation", "open_ticket": True},
            timeout=40,
        )
        assert cancelled.status_code == 200, cancelled.text
        result = cancelled.json()
        ticket_id = result.get("ticket_id")
        assert result.get("ok") is True and result.get("cancelled") == marker
        assert result.get("refunded") == pytest.approx(1.25)
        assert isinstance(ticket_id, str) and ticket_id
        after_balance = http_session.get(f"{API}/client/balance", headers=user_headers, timeout=20).json()["balance"]
        assert after_balance == pytest.approx(before + 1.25)
        persisted = mongo_db.live_subscriptions.find_one({"id": marker})
        assert persisted and persisted.get("status") == "cancelled" and persisted.get("cancelled_by") == "admin"
        tickets = http_session.get(f"{API}/admin/tickets", headers=headers, timeout=30)
        assert tickets.status_code == 200, tickets.text
        assert any(t.get("id") == ticket_id and t.get("user_id") == uid for t in tickets.json().get("tickets", []))
        actions = http_session.get(f"{API}/admin/ai-actions", headers=headers, timeout=30)
        assert actions.status_code == 200, actions.text
        assert any(a.get("kind") == "admin_cancel_sub" and a.get("target_id") == marker and a.get("ticket_id") == ticket_id for a in actions.json().get("actions", []))
    finally:
        if ticket_id:
            http_session.delete(f"{API}/admin/tickets/{ticket_id}", headers=headers, timeout=30)
        mongo_db.live_subscriptions.delete_many({"id": marker})
        mongo_db.transactions.delete_many({"$or": [{"id": spend_id}, {"target_id": marker}]})
        mongo_db.ai_actions.delete_many({"$or": [{"target_id": marker}, {"ticket_id": ticket_id}]})


# AI support asynchronously writes a staff reply and matching action-history row.
def test_ai_ticket_auto_reply_and_action_history(http_session, auth_context, mongo_db):
    marker = f"TEST_iter42_ticket_{uuid.uuid4().hex[:10]}"
    created = http_session.post(
        f"{API}/client/tickets",
        headers=auth_context["user_headers"],
        json={"subject": marker, "message": "Hello, please briefly explain how to open a normal support request."},
        timeout=30,
    )
    assert created.status_code == 200, created.text
    ticket_id = created.json().get("id")
    assert isinstance(ticket_id, str) and ticket_id
    try:
        messages = []
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(5)
            detail = http_session.get(f"{API}/client/tickets/{ticket_id}", headers=auth_context["user_headers"], timeout=30)
            assert detail.status_code == 200, detail.text
            messages = detail.json().get("messages", [])
            if any(m.get("author_name") == "BS Assistant (AI)" and m.get("is_ai") is True for m in messages):
                break
        ai_message = next((m for m in messages if m.get("author_name") == "BS Assistant (AI)" and m.get("is_ai") is True), None)
        assert ai_message and isinstance(ai_message.get("message"), str) and ai_message["message"].strip()
        actions = http_session.get(f"{API}/admin/ai-actions", headers=auth_context["admin_headers"], timeout=30)
        assert actions.status_code == 200, actions.text
        assert any(a.get("kind") == "ticket_reply" and a.get("ticket_id") == ticket_id for a in actions.json().get("actions", []))
    finally:
        http_session.delete(f"{API}/admin/tickets/{ticket_id}", headers=auth_context["admin_headers"], timeout=30)
        mongo_db.ai_actions.delete_many({"ticket_id": ticket_id})


# Signed-in AI chat remains connected to the configured LLM.
def test_signed_in_ai_chat_nonempty_reply(http_session, auth_context, mongo_db):
    username = auth_context["user"]["username"].lower()
    sid = f"ai-user-{username}"
    prior = mongo_db.ai_sessions.find_one({"session_id": sid})
    mongo_db.ai_sessions.update_one(
        {"session_id": sid},
        {"$set": {"status": "ai", "needs_handover": False, "identified": True, "identified_as": auth_context["user"]["username"], "identified_user_id": auth_context["user"]["id"]}},
        upsert=True,
    )
    marker = f"TEST_iter42_ai_{uuid.uuid4().hex[:8]}"
    try:
        response = http_session.post(
            f"{API}/ai/chat",
            headers=auth_context["user_headers"],
            json={"session_id": marker, "messages": [{"role": "user", "text": f"Hello {marker}. In one short sentence, what can Better Social help me buy?"}]},
            timeout=90,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data.get("reply"), str) and data["reply"].strip()
        assert data.get("session_id") == sid
    finally:
        mongo_db.ai_chat_messages.delete_many({"session_id": sid, "text": {"$regex": marker}})
        if prior is None:
            mongo_db.ai_sessions.delete_one({"session_id": sid})
        else:
            mongo_db.ai_sessions.replace_one({"session_id": sid}, prior, upsert=True)


# Authenticated public-chat send must persist and appear in the public feed.
def test_public_chat_send_and_read(http_session, auth_context, mongo_db):
    marker = f"TEST_iter42_chat_{uuid.uuid4().hex[:10]}"
    time.sleep(3.2)
    sent = http_session.post(
        f"{API}/public-chat/send",
        headers=auth_context["user_headers"],
        json={"text": marker},
        timeout=30,
    )
    assert sent.status_code == 200, sent.text
    message_id = sent.json().get("id")
    assert sent.json().get("ok") is True and message_id
    try:
        feed = http_session.get(f"{API}/public-chat/messages", params={"limit": 100}, timeout=30)
        assert feed.status_code == 200, feed.text
        match = next((m for m in feed.json().get("messages", []) if m.get("id") == message_id), None)
        assert match and match.get("text") == marker
        assert match.get("username") == auth_context["user"]["username"]
    finally:
        mongo_db.public_chat.delete_many({"id": message_id})


# Deleting transaction history must not change the user's usable balance.
def test_dbmanager_transaction_delete_many_preserves_wallet_balance(http_session, auth_context):
    headers = auth_context["admin_headers"]
    user_headers = auth_context["user_headers"]
    uid = auth_context["user"]["id"]
    marker = f"TEST_iter42_tx_{uuid.uuid4().hex}"
    _insert(http_session, headers, "transactions", {
        "id": marker,
        "user_id": uid,
        "username": auth_context["user"]["username"],
        "amount": 0.37,
        "method": "admin",
        "status": "approved",
        "type": "TEST_iter42_balance_guard",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    balance_before_delete = http_session.get(f"{API}/client/balance", headers=user_headers, timeout=20).json()["balance"]
    deleted = http_session.post(
        f"{API}/dbadmin/transactions/delete-many",
        headers=headers,
        json={"filter": {"id": marker}, "confirm_all": True},
        timeout=30,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json().get("deleted") == 1
    assert _docs(http_session, headers, "transactions", {"id": marker}) == []
    balance_after_delete = http_session.get(f"{API}/client/balance", headers=user_headers, timeout=20).json()["balance"]
    assert balance_after_delete == pytest.approx(balance_before_delete), (
        f"Deleting transaction history changed wallet balance from {balance_before_delete} to {balance_after_delete}"
    )
