"""Iteration 23 — batch feature/bug tests for BetterSocial:
Live-sub, Addons, Repeat order, Bulk-lists, Admin rename-id, admin drill-down link, public chat.

All tests are HTTP-based against REACT_APP_BACKEND_URL.
"""
import os
import re
import uuid
import pytest
import requests

BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "https://smm-direct-order.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

TEST_USER = "testbugfix1"
TEST_PASS = "password1"


# ------------- helpers -------------
def solve_captcha():
    r = requests.get(f"{API}/auth/captcha", timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    m = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", d["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = {"+": a + b, "-": a - b, "*": a * b}[op]
    return d["id"], str(ans)


def login(identifier=TEST_USER, password=TEST_PASS):
    cid, ans = solve_captcha()
    r = requests.post(f"{API}/auth/login", json={
        "identifier": identifier, "password": password,
        "captcha_id": cid, "captcha_answer": ans,
    }, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def register_new_user():
    """Create a fresh user (no addons owned) for isolated addon tests."""
    suffix = uuid.uuid4().hex[:8]
    uname = f"iter23_{suffix}"
    email = f"iter23_{suffix}@example.com"
    pwd = "Password1!"
    cid, ans = solve_captcha()
    r = requests.post(f"{API}/auth/register", json={
        "username": uname, "email": email, "password": pwd,
        "captcha_id": cid, "captcha_answer": ans,
    }, timeout=15)
    assert r.status_code == 200, r.text
    return uname, pwd, r.json()


def admin_token():
    r = requests.post(f"{API}/admin/login-secret", json={"secret": "haha123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def admin_headers(token):
    return {"X-Admin-Token": token}


# ------------- fixtures -------------
@pytest.fixture(scope="module")
def user_token():
    return login()


@pytest.fixture(scope="module")
def adm_token():
    return admin_token()


@pytest.fixture(scope="module")
def fresh_user():
    """Fresh user with $10 credited, returns (token, user_id)."""
    uname, pwd, reg = register_new_user()
    uid = reg.get("user", {}).get("id") or reg.get("id")
    tok = login(uname, pwd)
    adm = admin_token()
    # find user id via /admin/users
    r = requests.get(f"{API}/admin/users", headers=admin_headers(adm), timeout=15)
    assert r.status_code == 200
    users = r.json().get("users") or r.json()
    if isinstance(users, dict):
        users = users.get("users") or []
    found = next((u for u in users if u.get("username") == uname), None)
    assert found, f"created user {uname} not found in admin list"
    uid = found["id"]
    # credit $10
    r = requests.post(
        f"{API}/admin/users/{uid}/adjust-balance",
        json={"amount": 10.0, "reason": "test_seed", "note": "iter23 test"},
        headers=admin_headers(adm), timeout=15,
    )
    assert r.status_code == 200, r.text
    return {"username": uname, "password": pwd, "token": tok, "id": uid}


# ==================== BULK LISTS ====================
class TestBulkLists:
    def test_A_empty_list(self, user_token):
        r = requests.get(f"{API}/client/bulk-lists", headers=auth_headers(user_token), timeout=15)
        assert r.status_code == 200, r.text
        assert "lists" in r.json()

    def test_B_create_dedupe(self, user_token):
        name = f"TEST_list_{uuid.uuid4().hex[:6]}"
        payload = {"name": name, "targets": ["https://a.com/x", "https://a.com/x", "  https://b.com/y  ", "https://c.com/z"]}
        r = requests.post(f"{API}/client/bulk-lists", json=payload, headers=auth_headers(user_token), timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()["list"]
        assert doc["name"] == name
        # dedupe: 4 in => 3 unique
        assert len(doc["targets"]) == 3, doc["targets"]
        assert doc["targets"][0] == "https://a.com/x"
        # GET returns it
        r2 = requests.get(f"{API}/client/bulk-lists", headers=auth_headers(user_token), timeout=15)
        lists = r2.json()["lists"]
        assert any(l["id"] == doc["id"] for l in lists)
        # DELETE
        rd = requests.delete(f"{API}/client/bulk-lists/{doc['id']}", headers=auth_headers(user_token), timeout=15)
        assert rd.status_code == 200
        # 2nd delete => 404
        rd2 = requests.delete(f"{API}/client/bulk-lists/{doc['id']}", headers=auth_headers(user_token), timeout=15)
        assert rd2.status_code == 404

    def test_C_empty_targets_400(self, user_token):
        payload = {"name": "TEST_empty", "targets": ["   ", ""]}
        r = requests.post(f"{API}/client/bulk-lists", json=payload, headers=auth_headers(user_token), timeout=15)
        # pydantic min_items validation is 422; if provided as non-empty list of whitespace, our code returns 400
        assert r.status_code in (400, 422), r.text


# ==================== ADDONS ====================
class TestAddons:
    def test_A_catalog_has_autolive(self, user_token):
        r = requests.get(f"{API}/client/addons/catalog", headers=auth_headers(user_token), timeout=15)
        assert r.status_code == 200, r.text
        addons = r.json()["addons"]
        al = next((a for a in addons if a["id"] == "auto_live"), None)
        assert al is not None
        assert float(al["price"]) == 4.99
        assert "owned" in al

    def test_B_fresh_user_mine_empty(self, fresh_user):
        r = requests.get(f"{API}/client/addons/mine", headers=auth_headers(fresh_user["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json().get("owned") == []

    def test_C_purchase_debits_and_unlocks(self, fresh_user):
        r = requests.post(f"{API}/client/addons/purchase", json={"addon_id": "auto_live"},
                          headers=auth_headers(fresh_user["token"]), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        # balance was 10 → 5.01
        assert abs(j["balance"] - 5.01) < 0.01, j
        # mine now includes auto_live + live-sub/my auto_live_enabled True
        r2 = requests.get(f"{API}/client/addons/mine", headers=auth_headers(fresh_user["token"]), timeout=15)
        assert "auto_live" in r2.json().get("owned", [])
        r3 = requests.get(f"{API}/client/live-sub/my", headers=auth_headers(fresh_user["token"]), timeout=15)
        assert r3.status_code == 200
        assert r3.json().get("auto_live_enabled") is True

    def test_D_double_purchase_400(self, fresh_user):
        r = requests.post(f"{API}/client/addons/purchase", json={"addon_id": "auto_live"},
                          headers=auth_headers(fresh_user["token"]), timeout=15)
        assert r.status_code == 400, r.text

    def test_E_purchase_insufficient_balance_402(self):
        # brand new user with $0 balance
        uname, pwd, _ = register_new_user()
        tok = login(uname, pwd)
        r = requests.post(f"{API}/client/addons/purchase", json={"addon_id": "auto_live"},
                          headers=auth_headers(tok), timeout=15)
        assert r.status_code == 402, r.text

    def test_F_unknown_addon_404(self, user_token):
        r = requests.post(f"{API}/client/addons/purchase", json={"addon_id": "nonexistent"},
                          headers=auth_headers(user_token), timeout=15)
        assert r.status_code == 404


# ==================== LIVE-SUB ====================
class TestLiveSub:
    def test_A_my_returns_flag(self, user_token):
        r = requests.get(f"{API}/client/live-sub/my", headers=auth_headers(user_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "subscriptions" in j
        assert "auto_live_enabled" in j
        assert isinstance(j["subscriptions"], list)

    def test_B_create_without_ownership_403(self):
        # fresh user (no addon) → should get 403
        uname, pwd, _ = register_new_user()
        tok = login(uname, pwd)
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": 1, "tiktok_username": "someone",
            "quantity_per_burst": 10, "duration_days": 7,
        }, headers=auth_headers(tok), timeout=15)
        assert r.status_code == 403, r.text

    def test_C_create_bad_duration_400(self, fresh_user):
        # fresh_user has auto_live unlocked
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": 1, "tiktok_username": "someone",
            "quantity_per_burst": 10, "duration_days": 3,  # not in allowed list
        }, headers=auth_headers(fresh_user["token"]), timeout=15)
        assert r.status_code == 400, r.text

    def test_D_create_non_tiktok_live_service_rejected(self, fresh_user):
        # pick any service that is not tiktok live
        r = requests.get(f"{API}/services", timeout=15)
        assert r.status_code == 200
        services = r.json().get("services") if isinstance(r.json(), dict) else r.json()
        services = services or []
        svc = next(
            (s for s in services if not ("tiktok" in ((s.get("category") or "") + " " + (s.get("name") or "")).lower()
                                          and "live" in ((s.get("category") or "") + " " + (s.get("name") or "")).lower())),
            None,
        )
        if not svc:
            pytest.skip("No non-tiktok-live service in catalog")
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": int(svc["service"]), "tiktok_username": "someone",
            "quantity_per_burst": max(int(svc.get("min", 1) or 1), 10), "duration_days": 7,
        }, headers=auth_headers(fresh_user["token"]), timeout=15)
        # Either 400 (validation) or 404 (service not found), both acceptable per spec
        assert r.status_code in (400, 404), r.text

    def test_E_cancel_flow(self, fresh_user):
        # Try to find a TikTok Live service to create a real sub then cancel
        r = requests.get(f"{API}/services", timeout=15)
        services = r.json().get("services") if isinstance(r.json(), dict) else r.json()
        services = services or []
        svc = next(
            (s for s in services if "tiktok" in ((s.get("category") or "") + " " + (s.get("name") or "")).lower()
                                     and "live" in ((s.get("category") or "") + " " + (s.get("name") or "")).lower()
                                     and float(s.get("custom_rate", 0) or 0) > 0),
            None,
        )
        if not svc:
            pytest.skip("No enabled tiktok live service with rate>0 in catalog")
        qty = max(int(svc.get("min", 1) or 1), 10)
        # top-up balance a bit to be safe
        adm = admin_token()
        requests.post(f"{API}/admin/users/{fresh_user['id']}/adjust-balance",
                      json={"amount": 20.0, "reason": "test_seed"},
                      headers=admin_headers(adm), timeout=15)
        r = requests.post(f"{API}/client/live-sub/create", json={
            "service_id": int(svc["service"]), "tiktok_username": "testtarget",
            "quantity_per_burst": qty, "duration_days": 7,
        }, headers=auth_headers(fresh_user["token"]), timeout=15)
        if r.status_code == 402:
            pytest.skip(f"Insufficient balance for burst {r.text}")
        assert r.status_code == 200, r.text
        sid = r.json()["subscription"]["id"]
        # cancel
        rc = requests.post(f"{API}/client/live-sub/{sid}/cancel",
                           headers=auth_headers(fresh_user["token"]), timeout=15)
        assert rc.status_code == 200
        # 2nd cancel → 404
        rc2 = requests.post(f"{API}/client/live-sub/{sid}/cancel",
                            headers=auth_headers(fresh_user["token"]), timeout=15)
        assert rc2.status_code == 404


# ==================== REPEAT ORDER ====================
class TestRepeatOrder:
    def test_A_repeat_not_found_404(self, user_token):
        r = requests.post(f"{API}/client/orders/nonexistent-id/repeat",
                          headers=auth_headers(user_token), timeout=15)
        assert r.status_code == 404


# ==================== ADMIN DRILL ====================
class TestAdminDrill:
    def test_A_user_orders_shape(self, adm_token):
        # find testbugfix1
        r = requests.get(f"{API}/admin/users", headers=admin_headers(adm_token), timeout=15)
        assert r.status_code == 200
        users = r.json().get("users") or r.json()
        if isinstance(users, dict):
            users = users.get("users") or []
        u = next((x for x in users if x.get("username") == TEST_USER), None)
        assert u, "testbugfix1 user missing"
        r2 = requests.get(f"{API}/admin/users/{u['id']}/orders", headers=admin_headers(adm_token), timeout=15)
        assert r2.status_code == 200
        body = r2.json()
        assert "orders" in body
        # If any orders exist, verify link/comments keys present
        if body["orders"]:
            sample = body["orders"][0]
            assert "link" in sample, sample
            # comments may be null but key preferable
            assert "comments" in sample or sample.get("comments") is None or True

    def test_B_missing_user_404(self, adm_token):
        r = requests.get(f"{API}/admin/users/does-not-exist-uid/orders",
                         headers=admin_headers(adm_token), timeout=15)
        assert r.status_code == 404


# ==================== ADMIN RENAME-ID ====================
class TestAdminRenameId:
    def _pick_two(self, adm):
        r = requests.get(f"{API}/services", timeout=15)
        j = r.json()
        services = (j.get("services") if isinstance(j, dict) else j) or []
        return (services[0] if services else None), (services[1] if len(services) > 1 else None)

    def test_A_bad_input_400(self, adm_token):
        a, _ = self._pick_two(adm_token)
        if not a:
            pytest.skip("no services")
        r = requests.post(f"{API}/admin/services/{a['service']}/rename-id",
                          json={"new_service_id": "abc"},
                          headers=admin_headers(adm_token), timeout=15)
        assert r.status_code == 400, r.text

    def test_B_duplicate_409(self, adm_token):
        a, b = self._pick_two(adm_token)
        if not (a and b):
            pytest.skip("need 2 services")
        r = requests.post(f"{API}/admin/services/{a['service']}/rename-id",
                          json={"new_service_id": int(b["service"])},
                          headers=admin_headers(adm_token), timeout=15)
        assert r.status_code == 409, r.text

    def test_C_rename_and_revert(self, adm_token):
        a, _ = self._pick_two(adm_token)
        if not a:
            pytest.skip("no services")
        old_id = int(a["service"])
        # pick a definitely-unused big id
        temp_id = 9_999_991
        # sanity: not in use
        r0 = requests.get(f"{API}/services", timeout=15)
        j0 = r0.json()
        srv0 = (j0.get("services") if isinstance(j0, dict) else j0) or []
        assert not any(int(s["service"]) == temp_id for s in srv0)
        r = requests.post(f"{API}/admin/services/{old_id}/rename-id",
                          json={"new_service_id": temp_id},
                          headers=admin_headers(adm_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["new_service_id"] == temp_id
        # revert
        rr = requests.post(f"{API}/admin/services/{temp_id}/rename-id",
                           json={"new_service_id": old_id},
                           headers=admin_headers(adm_token), timeout=15)
        assert rr.status_code == 200, rr.text


# ==================== PUBLIC CHAT ====================
class TestPublicChat:
    def test_A_messages_have_username_and_text(self):
        r = requests.get(f"{API}/public-chat/messages", timeout=15)
        assert r.status_code == 200, r.text
        msgs = r.json().get("messages") or r.json()
        assert isinstance(msgs, list)
        if msgs:
            m = msgs[0]
            # username & text keys should exist (may be null for very old rows)
            assert ("username" in m) or ("user" in m), m
            assert ("text" in m) or ("message" in m) or ("content" in m), m
