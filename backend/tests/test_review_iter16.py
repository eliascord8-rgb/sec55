"""Iteration 16 backend regression tests:
- GET /api/orders/latest-global (public, masked usernames)
- GET /api/messages/thread/{other}?since=<ts> also returns messages where {from_id:me, read_at>since}
"""
import os
import re
import time
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"


def _solve_captcha():
    r = requests.get(f"{API}/auth/captcha", timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    q = d["question"]
    m = re.search(r"(\d+)\s*([+\-])\s*(\d+)", q)
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = a + b if op == "+" else a - b
    return d["id"], str(ans)


def _login(identifier, password):
    cid, ans = _solve_captcha()
    r = requests.post(f"{API}/auth/login", json={
        "identifier": identifier, "password": password,
        "captcha_id": cid, "captcha_answer": ans,
    }, timeout=15)
    assert r.status_code == 200, f"login {identifier} failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


# ---------- TEST 4a: PUBLIC latest-global feed ----------

def test_latest_global_public_no_auth():
    r = requests.get(f"{API}/orders/latest-global", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "orders" in body and isinstance(body["orders"], list)
    assert len(body["orders"]) >= 4, f"expected >=4 seeded orders, got {len(body['orders'])}"
    mask_re = re.compile(r"^[A-Za-z0-9]{1,3}#+([A-Za-z0-9]{1,2})?$")
    for o in body["orders"]:
        u = o.get("username", "")
        assert "#" in u, f"username not masked: {u!r}"
        # Short usernames (len<=3) return like 'a#' which still contains #
        # For longer names, verify the regex
        if len(u) >= 5:
            assert mask_re.match(u), f"mask format bad: {u!r}"


def test_latest_global_expected_masks_present():
    r = requests.get(f"{API}/orders/latest-global", timeout=15).json()
    names = {o["username"] for o in r["orders"]}
    # Must include the seeded testbugfix1 and crypto_king_92 masks
    assert "tes######x1" in names, f"testbugfix1 mask missing; got {names}"
    assert "cry#########92" in names, f"crypto_king_92 mask missing; got {names}"


# ---------- TEST 4b: Read-receipt flip via thread since ----------

def _headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_thread_since_returns_own_msg_after_read():
    tok_a, ua = _login("testbugfix1", "password1")
    tok_b, ub = _login("Balkin", "Dennis123.@@")

    # A sends a message to B
    text = f"regression-flip-{int(time.time())}"
    r = requests.post(f"{API}/messages/send",
                      headers=_headers(tok_a),
                      json={"to_id": ub["id"], "text": text}, timeout=15)
    assert r.status_code == 200, r.text
    sent_msg = r.json()["message"] if "message" in r.json() else r.json()
    # Response format guard
    msg_id = sent_msg.get("id") or sent_msg.get("_id")
    created_at = sent_msg.get("created_at")
    assert created_at, f"no created_at in send response: {sent_msg}"

    # Baseline: A fetches thread with since = created_at → should NOT include the msg
    # (before B reads it, no read_at exists)
    r0 = requests.get(f"{API}/messages/thread/{ub['id']}",
                      headers=_headers(tok_a),
                      params={"since": created_at}, timeout=15)
    assert r0.status_code == 200, r0.text
    ids0 = {m["id"] for m in r0.json()["messages"]}
    assert msg_id not in ids0, "before-read: sender should not receive own msg back"

    # B opens the thread (GET /thread/{a}) — server-side mark-as-read triggers
    r_b = requests.get(f"{API}/messages/thread/{ua['id']}",
                       headers=_headers(tok_b), timeout=15)
    assert r_b.status_code == 200
    # small delay for mongo write consistency
    time.sleep(0.5)

    # A polls again with since=created_at → NOW the message must appear (because read_at > since)
    r1 = requests.get(f"{API}/messages/thread/{ub['id']}",
                      headers=_headers(tok_a),
                      params={"since": created_at}, timeout=15)
    assert r1.status_code == 200, r1.text
    msgs1 = r1.json()["messages"]
    match = [m for m in msgs1 if m["id"] == msg_id]
    assert match, f"after-read: sender poll should include own msg; got ids={[m['id'] for m in msgs1]}"
    assert match[0].get("read_at"), f"msg should have read_at set: {match[0]}"
    assert match[0].get("read") is True, f"msg.read should be True: {match[0]}"


# ---------- TEST 5: Admin toggle ui-config still works ----------

def test_admin_ui_config_toggle():
    r = requests.post(f"{API}/admin/login-secret", json={"secret": "haha123"}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    h = {"X-Admin-Token": tok}
    # Read current
    cur = requests.get(f"{API}/admin/ui-config", headers=h, timeout=15)
    assert cur.status_code == 200, cur.text
    # Toggle ON
    p = requests.post(f"{API}/admin/ui-config", headers=h,
                      json={"use_new_home_layout": True}, timeout=15)
    assert p.status_code == 200, p.text
    # Public read (used by frontend to decide default)
    pub = requests.get(f"{API}/ui-config", timeout=15)
    assert pub.status_code == 200
    assert pub.json().get("use_new_home_layout") is True
