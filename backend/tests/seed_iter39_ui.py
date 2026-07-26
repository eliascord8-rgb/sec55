"""Seed one temporary LiveSubRow for iteration 39 UI automation."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

FRONTEND_ENV = dotenv_values("/app/frontend/.env")
BACKEND_ENV = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FRONTEND_ENV["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
TOKEN_PATH = Path("/app/test_reports/iter39_ui_seed.txt")

session = requests.Session()
captcha = session.get(f"{API}/auth/captcha", timeout=20).json()
question = captcha["question"].replace("What is", "").replace("?", "").strip()
left, operator, right = question.split()
answer = {"+": int(left) + int(right), "-": int(left) - int(right), "*": int(left) * int(right)}[operator]
auth = session.post(
    f"{API}/auth/login",
    json={"identifier": "testbugfix1", "password": "password1", "captcha_id": captcha["id"], "captcha_answer": str(answer)},
    timeout=20,
).json()
uid = auth["user"]["id"]
marker = f"TEST_iter39_ui_{uuid.uuid4().hex[:10]}"
sid = marker
now = datetime.now(timezone.utc)
client = MongoClient(BACKEND_ENV["MONGO_URL"])
db = client[BACKEND_ENV["DB_NAME"]]
db.live_subscriptions.insert_one({
    "id": sid,
    "user_id": uid,
    "username": auth["user"]["username"],
    "tiktok_username": "nonexistentuser99887766",
    "service_id": 7242,
    "service_name": "TEST TikTok Live Views UI",
    "quantity_per_burst": 50,
    "charge_per_burst": 0.01,
    "duration_days": 7,
    "repeat_every_minutes": 2,
    "mode": "live_only",
    "status": "waiting_for_live",
    "total_bursts": 0,
    "total_spent": 0.0,
    "created_at": now.isoformat(),
    "expires_at": (now + timedelta(days=7)).isoformat(),
    "next_check_at": (now + timedelta(minutes=20)).isoformat(),
    "last_check_at": now.isoformat(),
    "test_marker": marker,
})
for index, is_live in enumerate([False, True, False]):
    checked_at = (now - timedelta(minutes=2 - index)).isoformat()
    db.tiktok_live_checks.insert_one({
        "id": f"{marker}-check-{index}",
        "sub_id": sid,
        "user_id": uid,
        "username": auth["user"]["username"],
        "tiktok_username": "nonexistentuser99887766",
        "is_live": is_live,
        "will_fire": is_live,
        "checked_at": checked_at,
        "mode": "live_only",
        "note": "TEST UI check",
    })
TOKEN_PATH.write_text(f"{sid}\n", encoding="utf-8")
print(sid)
client.close()
