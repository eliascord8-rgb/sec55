import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discord_bot import DiscordBotManager


def test_detects_german_and_english_messages():
    mgr = DiscordBotManager()
    assert mgr._detect_language("Hallo, bitte erstelle ein Ticket für mich") == "de"
    assert mgr._detect_language("I want to buy followers for my account") == "en"


def test_builds_helpful_personalised_reply():
    mgr = DiscordBotManager()
    reply = mgr._build_reply_text("Bitte erstelle ein Ticket für mich", "Alice")
    assert "Alice" in reply
    assert "ticket" in reply.lower()

    reply_en = mgr._build_reply_text("I want to buy followers", "Bob")
    assert "Bob" in reply_en
    assert "buy" in reply_en.lower() or "order" in reply_en.lower()


def test_flag_spam_like_messages_for_auto_moderation():
    mgr = DiscordBotManager()
    assert mgr._should_auto_moderate("BUY BUY BUY BUY BUY") is True
    assert mgr._should_auto_moderate("AAAAAAAAAAAAAAAA") is True
    assert mgr._should_auto_moderate("Hello, I need help with my order") is False


def test_message_id_deduplication_blocks_repeats_within_ttl():
    mgr = DiscordBotManager()
    assert mgr._should_process_message_id("abc123") is True
    assert mgr._should_process_message_id("abc123") is False
    assert mgr._should_process_message_id("def456") is True


def test_command_only_mode_blocks_normal_messages_but_allows_commands():
    mgr = DiscordBotManager()
    mgr.command_only = True
    assert mgr._should_auto_reply("hello there") is False
    assert mgr._should_auto_reply("%ping") is True
    assert mgr._should_auto_reply("!ticket please") is True


def test_close_commands_are_recognized_for_ticket_channels():
    mgr = DiscordBotManager()
    assert mgr._is_close_command("%close") is True
    assert mgr._is_close_command("!close") is True
    assert mgr._is_close_command("close") is False
