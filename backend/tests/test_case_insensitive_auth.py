"""Tests for case-insensitive username duplicate registration bug fix."""
import os
import re
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://smm-direct-order.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def solve_captcha():
    """Fetch captcha and solve simple math."""
    r = requests.get(f"{API}/auth/captcha", timeout=15)
    assert r.status_code == 200, f"Captcha fetch failed: {r.status_code} {r.text}"
    data = r.json()
    q = data["question"]
    m = re.search(r"(\d+)\s*([+\-*])\s*(\d+)", q)
    assert m, f"Cannot parse captcha: {q}"
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    ans = {"+": a + b, "-": a - b, "*": a * b}[op]
    return data["id"], str(ans)


def register(username, email, password="Password1!"):
    cid, ans = solve_captcha()
    payload = {
        "username": username,
        "email": email,
        "password": password,
        "captcha_id": cid,
        "captcha_answer": ans,
    }
    return requests.post(f"{API}/auth/register", json=payload, timeout=15)


def login(identifier, password):
    cid, ans = solve_captcha()
    payload = {
        "identifier": identifier,
        "password": password,
        "captcha_id": cid,
        "captcha_answer": ans,
    }
    return requests.post(f"{API}/auth/login", json=payload, timeout=15)


@pytest.fixture(scope="module")
def suffix():
    return uuid.uuid4().hex[:8]


class TestCaseInsensitiveRegistration:
    def test_A_reject_case_variants_of_new_user(self, suffix):
        base = f"bugcheckA{suffix}"
        email = f"bugchka_{suffix}@example.com"
        r1 = register(base, email)
        assert r1.status_code == 200, f"First register failed: {r1.status_code} {r1.text}"

        for variant in [base.lower(), base.upper(), base.capitalize()]:
            if variant == base:
                continue
            time.sleep(0.5)
            r = register(variant, f"other_{variant}_{suffix}@example.com")
            assert r.status_code == 400, f"Expected 400 for {variant}, got {r.status_code}: {r.text}"
            assert "already taken" in r.text.lower(), f"Expected 'already taken' msg for {variant}: {r.text}"

    def test_B_login_case_insensitive_same_user_id(self, suffix):
        mixed = f"BugChk{suffix}Xyz"
        pw = "Password1!"
        email = f"bugchkb_{suffix}@example.com"
        r = register(mixed, email, pw)
        assert r.status_code == 200, f"Register failed: {r.text}"

        ids = []
        for variant in [mixed, mixed.lower(), mixed.upper()]:
            time.sleep(0.5)
            resp = login(variant, pw)
            assert resp.status_code == 200, f"Login failed for {variant}: {resp.status_code} {resp.text}"
            body = resp.json()
            assert "token" in body, f"No token in response: {body}"
            assert "user" in body and "id" in body["user"], f"No user.id: {body}"
            ids.append(body["user"]["id"])
        assert len(set(ids)) == 1, f"user.id differs across case variants: {ids}"

    def test_C_reject_case_variant_of_existing_user(self):
        # existing account testbugfix1 (pre-seeded)
        for variant in ["TESTBUGFIX1", "TestBugFix1"]:
            time.sleep(0.5)
            r = register(variant, f"newmail_{variant}_{uuid.uuid4().hex[:6]}@example.com")
            assert r.status_code == 400, f"Expected 400 for {variant}, got {r.status_code}: {r.text}"
            assert "already taken" in r.text.lower() or "already" in r.text.lower(), \
                f"Expected duplicate msg for {variant}: {r.text}"

    def test_D_duplicate_email_still_rejected(self, suffix):
        u1 = f"emailtest1_{suffix}"
        email = f"dupmail_{suffix}@example.com"
        r1 = register(u1, email)
        assert r1.status_code == 200, f"First register failed: {r1.text}"

        time.sleep(0.5)
        u2 = f"emailtest2_{suffix}"
        r2 = register(u2, email.upper())  # same email different case
        assert r2.status_code == 400, f"Expected 400 for dup email, got {r2.status_code}: {r2.text}"
        assert "email" in r2.text.lower(), f"Expected 'email' in msg: {r2.text}"

    def test_E_existing_user_regression_login(self):
        r = login("testbugfix1", "password1")
        assert r.status_code == 200, f"Regression login failed: {r.status_code} {r.text}"
        body = r.json()
        assert "token" in body
