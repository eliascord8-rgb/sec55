"""Iteration 19 regression: tips must not consume the shoutbox 3s rate-limit slot.

Scenario:
  1. Login as testbugfix1.
  2. Send a tip to Balkin -> 200.
  3. Immediately send a normal shoutbox message -> 200 (regression: was 429).
  4. Immediately send another normal shoutbox message -> 429 (regular rate-limit still applies).
  5. Sleep 4s, send a normal shoutbox message -> 200.
  6. Two tips in a row within <3s -> both 200 (tips don't set the rate window).
"""
import os
import re
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE}/api"
CAPTCHA_RE = re.compile(r"(\d+)\s*([+\-])\s*(\d+)")

BALKIN_ID = "4dd02b7a-f869-4642-9304-35e9e66402fc"


def _solve_captcha():
    r = requests.get(f"{API}/auth/captcha", timeout=10)
    r.raise_for_status()
    j = r.json()
    m = CAPTCHA_RE.search(j["question"])
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = a + b if op == "+" else a - b
    return j["id"], str(ans)


def _login(username, password):
    cid, cans = _solve_captcha()
    r = requests.post(f"{API}/auth/login", json={
        "identifier": username, "password": password,
        "captcha_id": cid, "captcha_answer": cans,
    }, timeout=10)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def token():
    tok, u = _login("testbugfix1", "password1")
    return tok, u


def _wait_for_rate_clear(tok):
    """Ensure we start each test class fresh (no lingering rate window)."""
    time.sleep(4)


class TestTipRateBypass:
    def test_tip_then_normal_msg_not_ratelimited(self, token):
        """CORE regression: tip should NOT block a normal message that follows."""
        tok, _ = token
        _wait_for_rate_clear(tok)

        # 1. Send tip
        r_tip = requests.post(f"{API}/tips/send", headers=_auth(tok),
                              json={"to_user_id": BALKIN_ID, "amount": 0.5,
                                    "note": "iter19 test"}, timeout=10)
        assert r_tip.status_code == 200, f"tip failed: {r_tip.status_code} {r_tip.text}"
        assert r_tip.json().get("ok") is True

        # 2. Immediate normal msg (< 100ms later) — must be 200
        r_msg = requests.post(f"{API}/public-chat/send", headers=_auth(tok),
                              json={"text": "iter19 post-tip normal msg"}, timeout=10)
        assert r_msg.status_code == 200, (
            f"REGRESSION: tip consumed the rate slot — normal msg got {r_msg.status_code}: {r_msg.text}"
        )

        # 3. Immediate 2nd normal msg — must be 429 (regular rate-limit still applies)
        r_msg2 = requests.post(f"{API}/public-chat/send", headers=_auth(tok),
                               json={"text": "iter19 second normal msg"}, timeout=10)
        assert r_msg2.status_code == 429, (
            f"expected 429 on consecutive normal msg, got {r_msg2.status_code}: {r_msg2.text}"
        )
        assert "slow down" in r_msg2.json().get("detail", "").lower()

    def test_rate_limit_clears_after_wait(self, token):
        """After ~4s, user can send a normal message again."""
        tok, _ = token
        # Previous test left a normal msg in the last few seconds. Wait to clear.
        time.sleep(4)
        r = requests.post(f"{API}/public-chat/send", headers=_auth(tok),
                          json={"text": "iter19 after-wait msg"}, timeout=10)
        assert r.status_code == 200, f"expected 200 after wait, got {r.status_code}: {r.text}"

    def test_two_tips_within_3s_both_succeed(self, token):
        """Tips must NOT set the rate window — two tips in <3s should both succeed."""
        tok, _ = token
        _wait_for_rate_clear(tok)

        r1 = requests.post(f"{API}/tips/send", headers=_auth(tok),
                           json={"to_user_id": BALKIN_ID, "amount": 0.5,
                                 "note": "iter19 tip A"}, timeout=10)
        assert r1.status_code == 200, f"tip #1 failed: {r1.text}"

        r2 = requests.post(f"{API}/tips/send", headers=_auth(tok),
                           json={"to_user_id": BALKIN_ID, "amount": 0.5,
                                 "note": "iter19 tip B"}, timeout=10)
        assert r2.status_code == 200, f"tip #2 failed within 3s: {r2.status_code} {r2.text}"

    def test_tip_after_normal_msg_still_works(self, token):
        """A tip should succeed even if a normal msg was just sent (tips are exempt)."""
        tok, _ = token
        _wait_for_rate_clear(tok)

        r_msg = requests.post(f"{API}/public-chat/send", headers=_auth(tok),
                              json={"text": "iter19 pre-tip normal msg"}, timeout=10)
        assert r_msg.status_code == 200, r_msg.text

        # Immediate tip — tips don't check the shoutbox rate window
        r_tip = requests.post(f"{API}/tips/send", headers=_auth(tok),
                              json={"to_user_id": BALKIN_ID, "amount": 0.5,
                                    "note": "iter19 tip after msg"}, timeout=10)
        assert r_tip.status_code == 200, f"tip after normal msg failed: {r_tip.text}"
