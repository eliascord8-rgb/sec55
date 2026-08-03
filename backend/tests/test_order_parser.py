import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "auth_and_chat.py"
spec = importlib.util.spec_from_file_location("auth_and_chat", MODULE_PATH)
auth_and_chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth_and_chat)


def test_tiktok_likes_detection():
    parsed = auth_and_chat.parse_order_request_text("%buy 1000 tiktok likes @username")
    assert parsed is not None
    assert parsed["platform"] == "tiktok"
    assert parsed["service"] == "likes"
    assert parsed["quantity"] == 1000
    assert parsed["target"] == "@username"


def test_instagram_followers_detection():
    parsed = auth_and_chat.parse_order_request_text("%kaufen 500 instagram followers")
    assert parsed is not None
    assert parsed["platform"] == "instagram"
    assert parsed["service"] == "followers"
    assert parsed["quantity"] == 500


def test_custom_comments_detection():
    parsed = auth_and_chat.parse_order_request_text("buy tiktok custom comments for username")
    assert parsed is not None
    assert parsed["platform"] == "tiktok"
    assert parsed["service"] == "comments"
    assert parsed["custom_comments"] is True


def test_buy_command_reply_is_multilingual():
    reply_en = auth_and_chat.build_order_support_reply("%buy 1000 tiktok likes @username")
    assert reply_en is not None
    assert "Order help" in reply_en or "order" in reply_en.lower()
    assert "%buy" in reply_en

    reply_de = auth_and_chat.build_order_support_reply("%kaufen 500 instagram followers")
    assert reply_de is not None
    assert "Bestellhilfe" in reply_de or "bestell" in reply_de.lower()
    assert "%kaufen" in reply_de
