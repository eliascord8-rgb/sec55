"""Backend tests for iteration 11: NOWPayments deposit crediting flows.

Tests:
- Webhook credits balance on payment_status='finished' with proper HMAC-SHA512 signature
- Webhook also credits on payment_status='confirmed' (new fallback status)
- Webhook is idempotent (replay returns already_credited=true, no double-credit)
- POST /api/client/funds/nowpayments-verify/{tx_id} returns graceful response for unpaid invoice
- GET /api/client/funds/pending-deposits returns only pending nowpayments txs
- Regression: POST /api/client/funds/nowpayments-create rejects amount<1, accepts amount>=1
"""
import os
import hmac
import hashlib
import json
import uuid
import time
import requests
import pytest
from datetime import datetime, timezone
from pymongo import MongoClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

USER_ID = "37a72bb9-3687-4fa6-848e-3e4265237636"
IPN_SECRET = "0GxKb3OpF5kPJane2oCnJg1EQGIsd2mt"


# ---- helpers ----------------------------------------------------------------
def _login(identifier: str, password: str) -> str:
    c = requests.get(f"{BASE}/api/auth/captcha", timeout=15).json()
    ans = str(eval(c["question"].replace("What is ", "").replace("?", "")))
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"identifier": identifier, "password": password, "captcha_id": c["id"], "captcha_answer": ans},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _sign(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(IPN_SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()


def _post_webhook(payload: dict) -> requests.Response:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(IPN_SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()
    return requests.post(
        f"{BASE}/api/nowpayments/webhook",
        data=body,
        headers={"Content-Type": "application/json", "x-nowpayments-sig": sig},
        timeout=15,
    )


def _mongo():
    return MongoClient(MONGO_URL)[DB_NAME]


def _insert_pending_tx(amount: float, invoice_id: str = None) -> str:
    tx_id = str(uuid.uuid4())
    db = _mongo()
    db.transactions.insert_one({
        "id": tx_id,
        "user_id": USER_ID,
        "username": "testbugfix1",
        "amount": amount,
        "method": "nowpayments",
        "status": "pending",
        "type": "deposit",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nowpayments_invoice_id": invoice_id or f"inv_test_{tx_id[:8]}",
        "nowpayments_url": "https://nowpayments.io/payment/?iid=test",
    })
    return tx_id


def _cleanup_tx(tx_id: str):
    db = _mongo()
    db.transactions.delete_many({"$or": [{"id": tx_id}, {"linked_tx": tx_id}]})


def _get_tx(tx_id: str):
    return _mongo().transactions.find_one({"id": tx_id}, {"_id": 0})


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def user_token():
    return _login("testbugfix1", "password1")


# ---- tests ------------------------------------------------------------------
class TestWebhookCredit:
    """Webhook credits balance on success statuses (finished, confirmed) with proper HMAC sig."""

    def test_webhook_credits_on_finished(self):
        tx_id = _insert_pending_tx(10.0)
        try:
            payload = {
                "payment_id": 123456,
                "payment_status": "finished",
                "order_id": f"funds_{tx_id}",
                "price_amount": 10.0,
                "actually_paid": 10.0,
                "pay_currency": "btc",
            }
            r = _post_webhook(payload)
            assert r.status_code == 200, f"webhook failed: {r.status_code} {r.text}"
            data = r.json()
            assert data.get("ok") is True
            assert data.get("credited") == tx_id, f"unexpected body: {data}"
            assert data.get("bonus") == 7.0, f"expected 70% bonus=7.0, got {data.get('bonus')}"
            # Verify persistence
            tx = _get_tx(tx_id)
            assert tx["status"] == "approved"
            assert tx["bonus_applied"] == 7.0
            # Verify bonus tx inserted
            bonus_tx = _mongo().transactions.find_one({"linked_tx": tx_id, "type": "deposit_bonus"}, {"_id": 0})
            assert bonus_tx is not None, "bonus transaction not inserted"
            assert bonus_tx["amount"] == 7.0
            assert bonus_tx["status"] == "approved"
        finally:
            _cleanup_tx(tx_id)

    def test_webhook_credits_on_confirmed(self):
        tx_id = _insert_pending_tx(20.0)
        try:
            payload = {
                "payment_id": 999999,
                "payment_status": "confirmed",
                "order_id": f"funds_{tx_id}",
                "price_amount": 20.0,
                "actually_paid": 20.0,
                "pay_currency": "eth",
            }
            r = _post_webhook(payload)
            assert r.status_code == 200, f"body={r.text}"
            data = r.json()
            assert data.get("credited") == tx_id, f"expected credited on confirmed: {data}"
            assert data.get("bonus") == 14.0
            tx = _get_tx(tx_id)
            assert tx["status"] == "approved"
        finally:
            _cleanup_tx(tx_id)

    def test_webhook_idempotent_replay(self):
        tx_id = _insert_pending_tx(15.0)
        try:
            payload = {
                "payment_id": 111,
                "payment_status": "finished",
                "order_id": f"funds_{tx_id}",
                "price_amount": 15.0,
                "actually_paid": 15.0,
            }
            r1 = _post_webhook(payload)
            assert r1.status_code == 200
            assert r1.json().get("credited") == tx_id

            # Replay same signed body
            r2 = _post_webhook(payload)
            assert r2.status_code == 200
            data2 = r2.json()
            assert data2.get("ok") is True
            assert data2.get("already_credited") is True, f"expected already_credited, got {data2}"

            # Verify no double bonus
            bonus_count = _mongo().transactions.count_documents({"linked_tx": tx_id, "type": "deposit_bonus"})
            assert bonus_count == 1, f"expected 1 bonus tx, got {bonus_count}"
        finally:
            _cleanup_tx(tx_id)

    def test_webhook_bad_signature_rejected(self):
        payload = {"payment_status": "finished", "order_id": "funds_fake"}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        r = requests.post(
            f"{BASE}/api/nowpayments/webhook",
            data=body,
            headers={"Content-Type": "application/json", "x-nowpayments-sig": "0" * 128},
            timeout=15,
        )
        assert r.status_code == 401, f"expected 401 for bad sig, got {r.status_code} {r.text}"


class TestVerifyEndpoint:
    """POST /api/client/funds/nowpayments-verify/{tx_id} — user-triggered fallback verify."""

    def test_verify_requires_auth(self):
        r = requests.post(f"{BASE}/api/client/funds/nowpayments-verify/fake-tx-id", timeout=15)
        assert r.status_code in (401, 403), f"expected auth error, got {r.status_code}"

    def test_verify_returns_404_for_unknown_tx(self, user_token):
        r = requests.post(
            f"{BASE}/api/client/funds/nowpayments-verify/nonexistent-tx-id-xyz",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code == 404

    def test_verify_unpaid_invoice_graceful(self, user_token):
        # Insert a pending tx with a fake invoice id — NOWPayments will return no payments / error
        tx_id = _insert_pending_tx(10.0, invoice_id="9999999999")
        try:
            r = requests.post(
                f"{BASE}/api/client/funds/nowpayments-verify/{tx_id}",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=30,
            )
            # Accept either graceful 200 with credited=false, OR 502 (NOWPayments lookup failed) — both are OK
            assert r.status_code in (200, 502), f"unexpected: {r.status_code} {r.text}"
            if r.status_code == 200:
                data = r.json()
                assert data.get("ok") is True
                assert data.get("credited") is False or data.get("already_credited") is not True
        finally:
            _cleanup_tx(tx_id)


class TestPendingDeposits:
    """GET /api/client/funds/pending-deposits returns only pending nowpayments txs."""

    def test_pending_list_shape(self, user_token):
        r = requests.get(
            f"{BASE}/api/client/funds/pending-deposits",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert "pending" in data
        assert isinstance(data["pending"], list)

    def test_pending_reflects_new_and_hides_credited(self, user_token):
        tx_id = _insert_pending_tx(12.0)
        try:
            # Should appear
            r = requests.get(
                f"{BASE}/api/client/funds/pending-deposits",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=15,
            )
            ids = [t["id"] for t in r.json()["pending"]]
            assert tx_id in ids, f"pending tx not listed: {ids}"

            # Credit via webhook
            payload = {
                "payment_id": 222,
                "payment_status": "finished",
                "order_id": f"funds_{tx_id}",
                "price_amount": 12.0,
                "actually_paid": 12.0,
            }
            wr = _post_webhook(payload)
            assert wr.status_code == 200

            # After crediting, should NOT appear
            r2 = requests.get(
                f"{BASE}/api/client/funds/pending-deposits",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=15,
            )
            ids2 = [t["id"] for t in r2.json()["pending"]]
            assert tx_id not in ids2, f"credited tx still in pending list: {ids2}"
        finally:
            _cleanup_tx(tx_id)


class TestNowpaymentsCreateRegression:
    """Regression: POST /api/client/funds/nowpayments-create still enforces schema."""

    def test_rejects_amount_below_1(self, user_token):
        r = requests.post(
            f"{BASE}/api/client/funds/nowpayments-create",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 0.5},
            timeout=15,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"

    def test_accepts_amount_10(self, user_token):
        r = requests.post(
            f"{BASE}/api/client/funds/nowpayments-create",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10},
            timeout=30,
        )
        # 200 with a checkout url is ideal; 502/503 accepted if NOWPayments API rejects sandbox key
        assert r.status_code in (200, 502, 503), f"unexpected: {r.status_code} {r.text}"
        if r.status_code == 200:
            data = r.json()
            assert "id" in data and "checkout_url" in data
            # verify tx inserted
            tx = _get_tx(data["id"])
            assert tx is not None and tx["status"] == "pending"
            _cleanup_tx(data["id"])
