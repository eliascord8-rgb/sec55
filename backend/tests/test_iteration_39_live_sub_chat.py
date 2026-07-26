"""Iteration 39 focused tests: Auto-Live offline/history/cancel and public-chat moderation."""
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
CREDENTIALS_PATH = Path("/app/memory/test_credentials.md")
OFFLINE_HANDLE = "nonexistentuser99887766"


def _credentials_for(section_name: str) -> dict:
    content = CREDENTIALS_PATH.read_text(encoding="utf-8")
    section_match = re.search(
        rf"(?ims)^##\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^##\s|\Z)", content
    )
    if not section_match:
        pytest.fail(f"Credential section not found: {section_name}")
    section = section_match.group(1)
    username = re.search(r"(?im)^\s*-\s*Username:\s*(.+?)\s*$", section)
    password = re.search(r"(?im)^\s*-\s*Password:\s*(.+?)\s*$", section)
    if not username or not password:
        pytest.fail(f"Username/password missing in credential section: {section_name}")
    return {"username": username.group(1).strip(), "password": password.group(1).strip()}


def _admin_secret() -> str:
    content = CREDENTIALS_PATH.read_text(encoding="utf-8")
    match = re.search(r'POST /api/admin/login-secret with \{"secret": "([^"]+)"\}', content)
    if not match:
        pytest.fail("Admin secret missing from test credentials")
    return match.group(1)


def _solve_captcha(session: requests.Session) -> tuple[str, str]:
    response = session.get(f"{API}/auth/captcha", timeout=20)
    assert response.status_code == 200, response.text
    data = response.json()
    match = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", data["question"])
    assert match, data
    left, operator, right = int(match.group(1)), match.group(2), int(match.group(3))
    return data["id"], str({"+": left + right, "-": left - right, "*": left * right}[operator])


def _login(session: requests.Session, section_name: str) -> dict:
    credentials = _credentials_for(section_name)
    captcha_id, captcha_answer = _solve_captcha(session)
    response = session.post(
        f"{API}/auth/login",
        json={
            "identifier": credentials["username"],
            "password": credentials["password"],
            "captcha_id": captcha_id,
            "captcha_answer": captcha_answer,
        },
        timeout=20,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("token"), str) and data["token"]
    assert data.get("user", {}).get("username", "").lower() == credentials["username"].lower()
    return data


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
    user_data = _login(http_session, "Regular test user")
    owner_data = _login(http_session, "Owner")
    admin_response = http_session.post(
        f"{API}/admin/login-secret", json={"secret": _admin_secret()}, timeout=20
    )
    assert admin_response.status_code == 200, admin_response.text
    return {
        "user": user_data["user"],
        "user_headers": {"Authorization": f"Bearer {user_data['token']}"},
        "owner": owner_data["user"],
        "owner_headers": {"Authorization": f"Bearer {owner_data['token']}"},
        "admin_headers": {"X-Admin-Token": admin_response.json()["token"]},
    }


@pytest.fixture(scope="module")
def live_sub_context(http_session, mongo_db, auth_context):
    """Create one real API offline subscription against a temporary catalog service."""
    uid = auth_context["user"]["id"]
    marker = f"TEST_iter39_{uuid.uuid4().hex[:10]}"
    service_id = 1_900_000_000 + int(time.time()) % 10_000_000
    mongo_db.curated_services.insert_one({
        "service_id": service_id,
        "name": f"TikTok Live Views {marker}",
        "custom_name": f"TikTok Live Views {marker}",
        "category": "TikTok Live",
        "enabled": True,
        "custom_rate": 10.0,
        "provider_rate": 1.0,
        "min": 1,
        "max": 100,
        "provider_id": f"missing-provider-{marker}",
        "test_marker": marker,
    })
    http_session.post(
        f"{API}/admin/users/{uid}/auto-live",
        headers=auth_context["admin_headers"],
        json={"enabled": True},
        timeout=20,
    )
    balance_response = http_session.get(
        f"{API}/client/balance", headers=auth_context["user_headers"], timeout=20
    )
    assert balance_response.status_code == 200, balance_response.text
    balance = float(balance_response.json()["balance"])
    credit_tx_ids = []
    if balance < 0.02:
        before_ids = {
            d["id"] for d in mongo_db.transactions.find({"user_id": uid, "id": {"$exists": True}}, {"id": 1})
        }
        credit = http_session.post(
            f"{API}/admin/users/{uid}/adjust-balance",
            headers=auth_context["admin_headers"],
            json={"amount": 1.0, "reason": "TEST_iter39_credit", "note": marker},
            timeout=20,
        )
        assert credit.status_code == 200, credit.text
        credit_tx_ids = [
            d["id"] for d in mongo_db.transactions.find(
                {"user_id": uid, "id": {"$nin": list(before_ids)}, "type": "TEST_iter39_credit"}, {"id": 1}
            )
        ]

    balance_before = http_session.get(
        f"{API}/client/balance", headers=auth_context["user_headers"], timeout=20
    ).json()["balance"]
    tx_before = mongo_db.transactions.count_documents({"user_id": uid, "type": "live_sub_burst"})
    orders_before = mongo_db.orders.count_documents({"user_id": uid, "source": "auto_live"})
    response = http_session.post(
        f"{API}/client/live-sub/create",
        headers=auth_context["user_headers"],
        json={
            "service_id": service_id,
            "tiktok_username": OFFLINE_HANDLE,
            "quantity_per_burst": 1,
            "duration_days": 7,
            "repeat_every_minutes": 2,
            "mode": "live_only",
        },
        timeout=50,
    )
    context = {
        "marker": marker,
        "uid": uid,
        "service_id": service_id,
        "response": response,
        "balance_before": balance_before,
        "tx_before": tx_before,
        "orders_before": orders_before,
        "credit_tx_ids": credit_tx_ids,
    }
    if response.status_code == 200:
        context["sid"] = response.json()["subscription"]["id"]
    yield context

    sid = context.get("sid")
    if sid:
        mongo_db.tiktok_live_checks.delete_many({"sub_id": sid})
        mongo_db.live_subscriptions.delete_many({"id": sid})
        mongo_db.orders.delete_many({"subscription_id": sid})
        mongo_db.transactions.delete_many({"live_sub_id": sid})
    mongo_db.live_subscriptions.delete_many({"test_marker": marker})
    mongo_db.curated_services.delete_many({"test_marker": marker})
    if credit_tx_ids:
        mongo_db.transactions.delete_many({"id": {"$in": credit_tx_ids}})


# Offline live_only creation must skip the provider, preserve balance, and log an initial red check.
def test_live_only_offline_create_skips_initial_burst(http_session, mongo_db, auth_context, live_sub_context):
    response = live_sub_context["response"]
    assert response.status_code == 200, response.text
    data = response.json()
    sub = data["subscription"]
    assert data.get("ok") is True
    assert sub["status"] == "waiting_for_live"
    assert sub["total_bursts"] == 0
    assert data.get("first_order_id") is None
    assert data.get("initial_skipped_offline") is True
    balance_after = http_session.get(
        f"{API}/client/balance", headers=auth_context["user_headers"], timeout=20
    ).json()["balance"]
    assert balance_after == pytest.approx(live_sub_context["balance_before"])
    assert mongo_db.transactions.count_documents({"user_id": live_sub_context["uid"], "type": "live_sub_burst"}) == live_sub_context["tx_before"]
    assert mongo_db.orders.count_documents({"user_id": live_sub_context["uid"], "source": "auto_live"}) == live_sub_context["orders_before"]
    check = mongo_db.tiktok_live_checks.find_one({"sub_id": sub["id"], "note": "initial check on create"}, {"_id": 0})
    assert check and check["is_live"] is False
    assert check["will_fire"] is False


# History endpoint returns complete statistics and newest checks first.
def test_live_check_history_stats_and_desc_sort(http_session, mongo_db, auth_context, live_sub_context):
    sid = live_sub_context["sid"]
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    new_time = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    extra = [
        {"id": f"{live_sub_context['marker']}-old", "sub_id": sid, "user_id": live_sub_context["uid"], "tiktok_username": OFFLINE_HANDLE, "is_live": True, "will_fire": True, "checked_at": old_time, "mode": "live_only", "note": "TEST older"},
        {"id": f"{live_sub_context['marker']}-new", "sub_id": sid, "user_id": live_sub_context["uid"], "tiktok_username": OFFLINE_HANDLE, "is_live": False, "will_fire": False, "checked_at": new_time, "mode": "live_only", "note": "TEST newer"},
    ]
    mongo_db.tiktok_live_checks.insert_many(extra)
    response = http_session.get(
        f"{API}/client/live-sub/{sid}/checks", headers=auth_context["user_headers"], timeout=20
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["checks"]) >= 3
    checked_at = [row["checked_at"] for row in data["checks"]]
    assert checked_at == sorted(checked_at, reverse=True)
    assert data["stats"]["total_checks"] == len(data["checks"])
    assert data["stats"]["was_live"] == sum(bool(row["is_live"]) for row in data["checks"])
    assert data["stats"]["was_offline"] == len(data["checks"]) - data["stats"]["was_live"]
    assert data["checks"][0]["id"] == extra[1]["id"]


# Regression: waiting_for_live subscriptions are cancellable, not only active ones.
def test_cancel_waiting_for_live_subscription(http_session, mongo_db, auth_context, live_sub_context):
    sid = live_sub_context["sid"]
    assert mongo_db.live_subscriptions.find_one({"id": sid})["status"] == "waiting_for_live"
    response = http_session.post(
        f"{API}/client/live-sub/{sid}/cancel", headers=auth_context["user_headers"], timeout=20
    )
    assert response.status_code == 200, response.text
    assert response.json().get("ok") is True
    assert mongo_db.live_subscriptions.find_one({"id": sid})["status"] == "cancelled"


# Always mode retains its initial-fire attempt semantics and does not emit removed live_notify chat rows.
def test_always_mode_initial_contract_and_no_live_notify(http_session, mongo_db, auth_context, live_sub_context):
    uid = live_sub_context["uid"]
    before_notify = mongo_db.public_chat.count_documents({"kind": "live_notify"})
    response = http_session.post(
        f"{API}/client/live-sub/create",
        headers=auth_context["user_headers"],
        json={
            "service_id": live_sub_context["service_id"],
            "tiktok_username": OFFLINE_HANDLE,
            "quantity_per_burst": 1,
            "duration_days": 7,
            "repeat_every_minutes": 2,
            "mode": "always",
        },
        timeout=30,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    sid = data["subscription"]["id"]
    try:
        assert data.get("ok") is True
        assert data.get("initial_skipped_offline") is False
        assert data["subscription"]["status"] == "active"
        assert mongo_db.public_chat.count_documents({"kind": "live_notify"}) == before_notify
    finally:
        mongo_db.live_subscriptions.delete_many({"id": sid})
        mongo_db.tiktok_live_checks.delete_many({"sub_id": sid})
        mongo_db.orders.delete_many({"subscription_id": sid})
        mongo_db.transactions.delete_many({"live_sub_id": sid, "user_id": uid})


# Owner /clear N deletes only the N newest rows and inserts the requested system audit message.
def test_owner_clear_n_deletes_only_latest_messages(http_session, mongo_db, auth_context):
    marker = f"TEST_iter39_clear_{uuid.uuid4().hex[:10]}"
    inserted = []
    base_time = datetime.now(timezone.utc)
    for index in range(5):
        doc = {
            "id": f"{marker}-{index}",
            "user_id": auth_context["owner"]["id"],
            "username": auth_context["owner"]["username"],
            "role": "owner",
            "text": f"{marker} message {index}",
            "created_at": (base_time + timedelta(microseconds=index)).isoformat(),
        }
        mongo_db.public_chat.insert_one(doc)
        inserted.append(doc)
    count_before = mongo_db.public_chat.count_documents({})
    response = http_session.post(
        f"{API}/public-chat/send",
        headers=auth_context["owner_headers"],
        json={"text": "/clear 3"},
        timeout=20,
    )
    system_doc = None
    count_after = mongo_db.public_chat.count_documents({})
    if response.status_code == 200:
        system_doc = mongo_db.public_chat.find_one(
            {"kind": "system", "username": auth_context["owner"]["username"], "created_at": {"$gte": base_time.isoformat()}},
            sort=[("created_at", -1)],
        )
    remaining_ids = {
        d["id"] for d in mongo_db.public_chat.find({"id": {"$in": [row["id"] for row in inserted]}}, {"id": 1})
    }
    cleanup_ids = [row["id"] for row in inserted]
    if system_doc:
        cleanup_ids.append(system_doc["id"])
    mongo_db.public_chat.delete_many({"id": {"$in": cleanup_ids}})

    assert response.status_code == 200, response.text
    assert response.json().get("deleted") == 3
    assert count_after == count_before - 2
    assert remaining_ids == {inserted[0]["id"], inserted[1]["id"]}
    assert system_doc is not None
    assert system_doc["text"] == f"Chat cleared by @{auth_context['owner']['username']} (last 3 messages)"


# BetterBot replies once to a regular user's help message and honors its five-minute cooldown.
def test_betterbot_help_reply_and_cooldown(http_session, mongo_db, auth_context):
    uid = auth_context["user"]["id"]
    marker = f"TEST_iter39_help_{uuid.uuid4().hex[:10]}"
    prior_bot_docs = list(mongo_db.public_chat.find({"kind": "bot_help", "reply_to_user_id": uid}))
    mongo_db.public_chat.delete_many({"kind": "bot_help", "reply_to_user_id": uid})
    created_ids = []
    try:
        time.sleep(3.2)
        first = http_session.post(
            f"{API}/public-chat/send",
            headers=auth_context["user_headers"],
            json={"text": f"need help please {marker}"},
            timeout=20,
        )
        assert first.status_code == 200, first.text
        created_ids.append(first.json()["id"])
        first_bots = list(mongo_db.public_chat.find({"kind": "bot_help", "reply_to_user_id": uid}, {"_id": 0}))
        assert len(first_bots) == 1
        created_ids.append(first_bots[0]["id"])
        assert first_bots[0]["username"] == "BetterBot"
        assert first_bots[0]["role"] == "system"
        assert "Live Chat" in first_bots[0]["text"] and "Ticket" in first_bots[0]["text"]

        time.sleep(3.2)
        second = http_session.post(
            f"{API}/public-chat/send",
            headers=auth_context["user_headers"],
            json={"text": f"contact support again {marker}"},
            timeout=20,
        )
        assert second.status_code == 200, second.text
        created_ids.append(second.json()["id"])
        second_bots = list(mongo_db.public_chat.find({"kind": "bot_help", "reply_to_user_id": uid}, {"_id": 0}))
        assert len(second_bots) == 1

        feed = http_session.get(f"{API}/public-chat/messages?limit=200", timeout=20)
        assert feed.status_code == 200, feed.text
        messages = feed.json()["messages"]
        assert any(row.get("id") == first.json()["id"] and marker in row.get("text", "") for row in messages)
        assert any(row.get("id") == first_bots[0]["id"] and row.get("kind") == "bot_help" for row in messages)
    finally:
        mongo_db.public_chat.delete_many({"id": {"$in": created_ids}})
        if prior_bot_docs:
            mongo_db.public_chat.insert_many(prior_bot_docs)
