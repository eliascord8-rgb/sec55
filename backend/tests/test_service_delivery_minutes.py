import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service_catalog import extract_provider_delivery_minutes, parse_delivery_minutes, refresh_catalog_delivery_minutes


def test_parse_delivery_minutes_handles_common_formats():
    assert parse_delivery_minutes("Start time: 0-1H") == 60
    assert parse_delivery_minutes("Speed: 1k/24h") == 1440
    assert parse_delivery_minutes("5 min start") == 5
    assert parse_delivery_minutes("1 hour 30 minutes") == 90
    assert parse_delivery_minutes("1h 15m") == 75
    assert parse_delivery_minutes("10-30 mins") == 30
    assert parse_delivery_minutes("~2 hours") == 120
    assert parse_delivery_minutes("Instant") == 0


def test_extract_provider_delivery_minutes_reads_common_fields():
    payload = {"average_time": "30 mins", "description": "Fast delivery"}
    assert extract_provider_delivery_minutes(payload) == 30

    payload2 = {"delivery": "1h 10m"}
    assert extract_provider_delivery_minutes(payload2) == 70


class FakeCollection:
    def __init__(self):
        self.updated = []

    async def update_many(self, query, update):
        self.updated.append((query, update))
        return type("Result", (), {"matched_count": 1})()


class FakeDb:
    def __init__(self):
        self.curated_services = FakeCollection()


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get_services(self):
        self.calls.append("called")
        return [{"service": 42, "average_time": "45 mins"}]


async def _run_refresh_test():
    db = FakeDb()
    client = FakeClient()
    updated = await refresh_catalog_delivery_minutes(db, client.get_services, provider_id="prov-1", cache={})
    assert updated == 1
    assert db.curated_services.updated[0][1]["$set"]["delivery_minutes"] == 45


def test_refresh_catalog_delivery_minutes_updates_matching_services():
    import asyncio
    asyncio.run(_run_refresh_test())
