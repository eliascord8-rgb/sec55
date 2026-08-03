import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import _auto_approve_orders_enabled, _default_order_status


def test_auto_approval_toggle_defaults_to_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_ORDERS", "true")
    assert _auto_approve_orders_enabled() is True
    assert _default_order_status(is_manual=False) == "approved"


def test_auto_approval_toggle_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_ORDERS", "false")
    assert _auto_approve_orders_enabled() is False
    assert _default_order_status(is_manual=False) == "Pending"
