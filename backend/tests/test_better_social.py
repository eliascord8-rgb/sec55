"""Backend tests for Better Social SMM landing app."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to reading from frontend/.env directly when env var not exported
    from pathlib import Path
    env_path = Path("/app/frontend/.env")
    for line in env_path.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(f"{API}/admin/login", json={"username": "DEMO", "password": "DEMO"})
    assert r.status_code == 200, r.text
    token = r.json().get("token")
    assert token
    return token


# --- Public services endpoint (smmcost.com proxy) ---
class TestServices:
    def test_root(self, session):
        r = session.get(f"{API}/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_services_list(self, session):
        r = session.get(f"{API}/services", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "services" in data
        assert isinstance(data["services"], list)
        assert len(data["services"]) > 0
        sample = data["services"][0]
        # smmcost service object has at least service id, name, rate
        assert "service" in sample or "name" in sample


# --- Admin auth ---
class TestAdminAuth:
    def test_login_success(self, session):
        r = session.post(f"{API}/admin/login", json={"username": "DEMO", "password": "DEMO"})
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_wrong(self, session):
        r = session.post(f"{API}/admin/login", json={"username": "x", "password": "y"})
        assert r.status_code == 401

    def test_admin_orders_no_token(self, session):
        r = session.get(f"{API}/admin/orders")
        assert r.status_code == 401

    def test_admin_orders_invalid_token(self, session):
        r = session.get(f"{API}/admin/orders", headers={"X-Admin-Token": "bogus"})
        assert r.status_code == 401

    def test_admin_coupons_no_token(self, session):
        r = session.get(f"{API}/admin/coupons")
        assert r.status_code == 401

    def test_admin_cp_config_no_token(self, session):
        r = session.get(f"{API}/admin/coinpayments-config")
        assert r.status_code == 401


# --- Coupons ---
class TestCoupons:
    def test_create_coupon_and_list(self, session, admin_token):
        headers = {"X-Admin-Token": admin_token}
        r = session.post(f"{API}/admin/coupons", json={"amount": 25.5, "note": "TEST_coupon"}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["amount"] == 25.5
        assert body["balance"] == 25.5
        code = body["code"]
        assert code.startswith("BS-") and len(code) == 17  # BS-XXXX-XXXX-XXXX
        # Verify listing contains it
        r2 = session.get(f"{API}/admin/coupons", headers=headers)
        assert r2.status_code == 200
        codes = [c["code"] for c in r2.json()["coupons"]]
        assert code in codes
        # check public lookup
        r3 = session.post(f"{API}/coupon/check", json={"code": code})
        assert r3.status_code == 200
        assert r3.json()["balance"] == 25.5

    def test_create_coupon_invalid_amount(self, session, admin_token):
        r = session.post(f"{API}/admin/coupons", json={"amount": 0}, headers={"X-Admin-Token": admin_token})
        assert r.status_code == 400

    def test_check_invalid_coupon(self, session):
        r = session.post(f"{API}/coupon/check", json={"code": "BS-FAKE-CODE-XXXX"})
        assert r.status_code == 404

    def test_check_empty_coupon(self, session):
        r = session.post(f"{API}/coupon/check", json={"code": ""})
        assert r.status_code == 400


# --- Checkout ---
class TestCheckout:
    @pytest.fixture(scope="class")
    def fresh_coupon(self, session, admin_token):
        r = session.post(
            f"{API}/admin/coupons",
            json={"amount": 100, "note": "TEST_checkout"},
            headers={"X-Admin-Token": admin_token},
        )
        assert r.status_code == 200
        return r.json()["code"]

    def test_checkout_invalid_coupon(self, session):
        payload = {
            "service_id": 1,
            "link": "https://instagram.com/test",
            "quantity": 100,
            "payment_method": "coupon",
            "coupon_code": "BS-NOPE-NOPE-NOPE",
            "price_usd": 1.0,
        }
        r = session.post(f"{API}/checkout", json=payload)
        assert r.status_code == 404

    def test_checkout_insufficient_balance(self, session, admin_token):
        # tiny coupon
        c = session.post(
            f"{API}/admin/coupons",
            json={"amount": 0.01, "note": "TEST_small"},
            headers={"X-Admin-Token": admin_token},
        ).json()["code"]
        payload = {
            "service_id": 1,
            "link": "https://instagram.com/test",
            "quantity": 100,
            "payment_method": "coupon",
            "coupon_code": c,
            "price_usd": 5.0,
        }
        r = session.post(f"{API}/checkout", json=payload)
        assert r.status_code == 400
        assert "Insufficient" in r.json()["detail"]

    def test_checkout_balance_deduction_correctness(self, session, fresh_coupon):
        """Verify balance deducted ONLY on SMM success; NOT deducted on SMM failure."""
        svc = session.get(f"{API}/services", timeout=60).json()["services"]
        sid = next((int(s["service"]) for s in svc if "service" in s), None)
        assert sid is not None

        before = session.post(f"{API}/coupon/check", json={"code": fresh_coupon}).json()["balance"]
        price = 1.0
        payload = {
            "service_id": sid,
            "link": "https://instagram.com/testuser_bs",
            "quantity": 100,
            "payment_method": "coupon",
            "coupon_code": fresh_coupon,
            "price_usd": price,
        }
        r = session.post(
            f"{API}/checkout", json=payload, timeout=60,
            headers={"X-Forwarded-For": "9.9.9.9"},
        )
        after = session.post(f"{API}/coupon/check", json={"code": fresh_coupon}).json()["balance"]

        if r.status_code == 200:
            body = r.json()
            assert body["status"] == "success"
            assert body.get("smm_order_id") is not None
            assert abs((before - after) - price) < 1e-6, \
                f"Expected deduction of {price}; before={before} after={after}"
        elif r.status_code in (400, 502):
            # SMM error -> balance must NOT be deducted
            assert after == before, f"Balance deducted on SMM failure! before={before} after={after}"
        else:
            pytest.fail(f"Unexpected status: {r.status_code} body={r.text}")

    def test_orders_have_ip_after_real_checkout(self, session, admin_token):
        """If any orders exist, verify ip and core fields are populated."""
        orders = session.get(
            f"{API}/admin/orders", headers={"X-Admin-Token": admin_token}
        ).json()["orders"]
        if not orders:
            pytest.skip("No orders to validate")
        o = orders[0]
        assert "_id" not in o
        assert o.get("ip"), f"IP missing on order: {o}"
        assert o.get("id")
        assert o.get("payment_method") in ("coupon", "coinpayments")

    def test_checkout_coinpayments_not_configured(self, session, admin_token):
        # Ensure coinpayments config absent — clear via direct DB would require backend call.
        # If config exists from a prior test, this may not be 400. So we only test if not configured.
        cfg = session.get(f"{API}/admin/coinpayments-config", headers={"X-Admin-Token": admin_token}).json()
        if cfg.get("configured"):
            pytest.skip("CoinPayments already configured; skipping not-configured test")
        payload = {
            "service_id": 1,
            "link": "https://instagram.com/x",
            "quantity": 100,
            "payment_method": "coinpayments",
            "price_usd": 5.0,
        }
        r = session.post(f"{API}/checkout", json=payload)
        assert r.status_code == 400
        assert "not configured" in r.json()["detail"].lower()

    def test_checkout_invalid_method(self, session):
        payload = {
            "service_id": 1,
            "link": "https://instagram.com/x",
            "quantity": 100,
            "payment_method": "bogus",
            "price_usd": 5.0,
        }
        r = session.post(f"{API}/checkout", json=payload)
        assert r.status_code == 400


# --- CoinPayments config ---
class TestCoinPaymentsConfig:
    def test_set_and_get_masked(self, session, admin_token):
        headers = {"X-Admin-Token": admin_token}
        cfg = {
            "public_key": "pubkey_TEST",
            "private_key": "privatekey_TEST_1234",
            "ipn_secret": "ipn_TEST_5678",
            "merchant_id": "merch_TEST",
        }
        r = session.post(f"{API}/admin/coinpayments-config", json=cfg, headers=headers)
        assert r.status_code == 200
        assert r.json()["configured"] is True

        r2 = session.get(f"{API}/admin/coinpayments-config", headers=headers)
        assert r2.status_code == 200
        body = r2.json()
        assert body["configured"] is True
        assert body["public_key"] == "pubkey_TEST"
        assert body["merchant_id"] == "merch_TEST"
        assert body["private_key_masked"].endswith("1234")
        assert body["private_key_masked"].startswith("*")
        assert "privatekey" not in body["private_key_masked"]
        assert body["ipn_secret_masked"].endswith("5678")


# --- Admin orders + IP capture ---
class TestAdminOrders:
    def test_orders_list_and_ip_captured(self, session, admin_token):
        # First trigger a failed checkout that doesn't insert (SMM fails -> no insert).
        # So instead test list endpoint structure.
        # Generate a coupon, attempt checkout that yields insufficient balance -> not inserted either.
        # The only insertion path is successful SMM order or pending coinpayments.
        # We verify endpoint shape is correct.
        r = session.get(
            f"{API}/admin/orders",
            headers={"X-Admin-Token": admin_token, "X-Forwarded-For": "1.2.3.4"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "orders" in body
        assert isinstance(body["orders"], list)
        # If any orders exist, ensure no _id leak and ip key present
        for o in body["orders"]:
            assert "_id" not in o
            assert "ip" in o
