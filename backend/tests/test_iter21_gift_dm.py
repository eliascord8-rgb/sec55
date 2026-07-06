"""Iter21 — Tip triggers a BetterSocial system DM to the recipient."""
import os
import re
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

CAPTCHA_Q_RE = re.compile(r"(\d+)\s*([+\-])\s*(\d+)")

BALKIN_ID = "4dd02b7a-f869-4642-9304-35e9e66402fc"


def _solve_captcha():
    r = requests.get(f"{BASE_URL}/api/auth/captcha", timeout=15)
    r.raise_for_status()
    j = r.json()
    m = CAPTCHA_Q_RE.search(j["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = a + b if op == "+" else a - b
    return j["id"], str(ans)


def _login(identifier, password):
    cid, ca = _solve_captcha()
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"identifier": identifier, "password": password, "captcha_id": cid, "captcha_answer": ca},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {identifier}: {r.status_code} {r.text}"
    return r.json()["token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _balance(tok):
    r = requests.get(f"{BASE_URL}/api/client/balance", headers=_auth(tok), timeout=15)
    assert r.status_code == 200, f"balance fetch failed: {r.status_code} {r.text}"
    return float(r.json().get("balance", 0.0))


@pytest.fixture(scope="module")
def sender_token():
    return _login("testbugfix1", "password1")


@pytest.fixture(scope="module")
def recipient_token():
    return _login("Balkin", "Dennis123.@@")


def _bot_id():
    bot = db.users.find_one({"username": "BetterSocial"}, {"id": 1})
    return bot["id"] if bot else None


# ------- TEST 1: Tip triggers gift DM with note -------

def test_1_tip_creates_bettersocial_dm_with_note(sender_token, recipient_token):
    # Snapshot recipient unread count before
    r = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=_auth(recipient_token), timeout=15)
    assert r.status_code == 200, r.text
    pre_unread = int(r.json().get("count", r.json().get("unread", 0)))

    # Snapshot balances before
    sender_bal_before = _balance(sender_token)
    recip_bal_before = _balance(recipient_token)

    # Send tip $2.00 with a note
    note = "iter21 gift test"
    r = requests.post(
        f"{BASE_URL}/api/tips/send",
        headers=_auth(sender_token),
        json={"to_user_id": BALKIN_ID, "amount": 2.0, "note": note},
        timeout=15,
    )
    assert r.status_code == 200, f"tip send failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("ok") is True
    assert body.get("amount") == 2.0
    assert body.get("recipient") == "Balkin"

    # Recipient unread-count grew by at least 1
    r = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=_auth(recipient_token), timeout=15)
    assert r.status_code == 200, r.text
    post_unread = int(r.json().get("count", r.json().get("unread", 0)))
    assert post_unread >= pre_unread + 1, f"unread should increase: pre={pre_unread} post={post_unread}"

    # Threads list contains BetterSocial
    r = requests.get(f"{BASE_URL}/api/messages/threads", headers=_auth(recipient_token), timeout=15)
    assert r.status_code == 200, r.text
    threads = r.json()
    if isinstance(threads, dict):
        threads = threads.get("threads", threads.get("items", []))
    assert any((t.get("username") == "BetterSocial") or (t.get("other_username") == "BetterSocial")
               for t in threads), f"BetterSocial not in threads: {threads}"

    # Fetch bot id from mongo
    bot_id = _bot_id()
    assert bot_id, "BetterSocial user must exist in db.users"

    # GET thread with bot as Balkin
    r = requests.get(f"{BASE_URL}/api/messages/thread/{bot_id}", headers=_auth(recipient_token), timeout=15)
    assert r.status_code == 200, r.text
    payload = r.json()
    messages = payload if isinstance(payload, list) else payload.get("messages", payload.get("items", []))
    assert messages, "thread must not be empty"
    last = messages[-1]
    assert last.get("from_username") == "BetterSocial", f"last from={last.get('from_username')}"
    assert last.get("kind") == "tip_notification", f"kind={last.get('kind')}"
    text = last.get("text", "")
    assert "🎁 Gift from user @testbugfix1 : $2.00" in text, f"text={text!r}"
    assert note in text, f"note missing from text={text!r}"

    # Regression: balance movements & shoutbox announce (TEST 5)
    sender_bal_after = _balance(sender_token)
    recip_bal_after = _balance(recipient_token)
    assert round(sender_bal_before - sender_bal_after, 2) == 2.0, \
        f"sender balance should drop by 2.00: {sender_bal_before}->{sender_bal_after}"
    assert round(recip_bal_after - recip_bal_before, 2) == 2.0, \
        f"recipient balance should rise by 2.00: {recip_bal_before}->{recip_bal_after}"

    # Public shoutbox contains tip announcement referencing @Balkin & $2.00
    r = requests.get(f"{BASE_URL}/api/public-chat/messages", timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    msgs = j if isinstance(j, list) else j.get("messages", j.get("items", []))
    found = any(
        m.get("kind") == "tip"
        and m.get("username") == "testbugfix1"
        and "@Balkin" in (m.get("text") or "")
        and "$2.00" in (m.get("text") or "")
        for m in msgs
    )
    assert found, "public shoutbox missing tip announcement"


# ------- TEST 2: Tip without a note -> no 'Note:' line -------

def test_2_tip_without_note_has_no_note_line(sender_token, recipient_token):
    r = requests.post(
        f"{BASE_URL}/api/tips/send",
        headers=_auth(sender_token),
        json={"to_user_id": BALKIN_ID, "amount": 1.25},
        timeout=15,
    )
    assert r.status_code == 200, f"tip send failed: {r.status_code} {r.text}"

    bot_id = _bot_id()
    assert bot_id

    r = requests.get(f"{BASE_URL}/api/messages/thread/{bot_id}", headers=_auth(recipient_token), timeout=15)
    assert r.status_code == 200, r.text
    payload = r.json()
    messages = payload if isinstance(payload, list) else payload.get("messages", payload.get("items", []))
    last = messages[-1]
    text = last.get("text", "")
    assert last.get("kind") == "tip_notification"
    assert text == "🎁 Gift from user @testbugfix1 : $1.25", f"unexpected text={text!r}"
    assert "Note:" not in text, "Note line must be absent when no note provided"


# ------- TEST 3: System bot idempotent (exactly 1 doc) -------

def test_3_system_bot_exactly_one():
    n = db.users.count_documents({"username": "BetterSocial"})
    assert n == 1, f"BetterSocial user must exist exactly once, found {n}"


# ------- TEST 4: System bot cannot log in -------

def test_4_system_bot_cannot_login():
    cid, ca = _solve_captcha()
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"identifier": "BetterSocial", "password": "!disabled",
              "captcha_id": cid, "captcha_answer": ca},
        timeout=15,
    )
    assert r.status_code in (400, 401), f"expected 400/401 for system-bot login, got {r.status_code} {r.text}"
