import re
from typing import Any, Dict, Optional


def normalize_provider_services_payload(payload: Optional[Any]) -> list[Dict[str, Any]]:
    """Return a flat list of provider service objects from common wrapper shapes."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("services", "data", "items", "result", "list", "response", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = normalize_provider_services_payload(value)
                if nested:
                    return nested
        if any(isinstance(payload.get(k), (int, float, str)) for k in ("service", "service_id", "id", "name", "rate", "min", "max")):
            return [payload]
    return []


def _normalize_unit_minutes(value: int, unit: str) -> Optional[int]:
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return value
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return value * 60
    if unit in {"d", "day", "days"}:
        return value * 60 * 24
    return None


def parse_delivery_minutes(text: str) -> Optional[int]:
    """Try to extract a delivery time (in minutes) from a free-form description."""
    if not text:
        return None
    text = str(text).strip()
    if not text:
        return None
    t = text.lower()

    if re.search(r"\binstant\b|\bnow\b", t):
        return 0

    m = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)\s*(?:and\s*)?(\d+)\s*(?:m|min|mins|minute|minutes)", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    m = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)", t)
    if m:
        return int(m.group(1)) * 60

    m = re.search(r"(\d+)\s*(m|min|mins|minute|minutes)", t)
    if m:
        return int(m.group(1))

    m = re.search(r"(\d+)\s*(m|min|mins|minute|minutes)\s*(?:and\s*)?(\d+)\s*(h|hr|hrs|hour|hours)", t)
    if m:
        return int(m.group(1)) + int(m.group(2)) * 60

    m = re.search(r"(\d+)\s*(min|minute|minutes|hour|hr|hrs|hours|day|d)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        return _normalize_unit_minutes(n, unit)

    m = re.search(r"(\d+)\s*-\s*(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|d|day|days)", t)
    if m:
        hi = int(m.group(2))
        unit = m.group(3)
        return _normalize_unit_minutes(hi, unit)

    m = re.search(r"(\d+)\s*(?:k|k\w*)\s*(?:/|per)\s*(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|d|day|days)", t)
    if m:
        return _normalize_unit_minutes(int(m.group(2)), m.group(3))

    return None


def extract_provider_delivery_minutes(payload: Optional[Any]) -> Optional[int]:
    """Extract a delivery minute value from provider service payloads, including nested wrappers."""
    if payload is None:
        return None

    if isinstance(payload, str):
        return parse_delivery_minutes(payload)

    if isinstance(payload, list):
        for item in payload:
            parsed = extract_provider_delivery_minutes(item)
            if parsed is not None:
                return parsed
        return None

    if isinstance(payload, dict):
        for field in ("delivery_minutes", "delivery_time", "average_time", "avg_time", "average", "speed", "delivery", "expected_time", "start_time", "start", "time", "description", "minutes", "estimated_time", "name"):
            if field not in payload:
                continue
            value = payload.get(field)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    continue
                if text.lower() in {"none", "null", "n/a", "na"}:
                    continue
                parsed = parse_delivery_minutes(text)
                if parsed is not None:
                    return parsed

        for key, value in payload.items():
            if key.lower() in {"service", "service_id", "id", "name", "rate", "min", "max", "category", "type", "provider"}:
                continue
            if isinstance(value, (dict, list)):
                parsed = extract_provider_delivery_minutes(value)
                if parsed is not None:
                    return parsed

    return None


async def refresh_catalog_delivery_minutes(db, fetch_services_fn, provider_id=None, cache=None, cache_ttl_seconds=90):
    """Refresh delivery_minutes from the SMM provider for existing curated services."""
    if cache is not None:
        key = provider_id or "__default__"
        import time
        now = time.time()
        last = cache.get(key)
        if last and now - last < cache_ttl_seconds:
            return 0

    try:
        data = await fetch_services_fn()
    except Exception:
        return 0

    if not isinstance(data, list):
        return 0

    updated = 0
    for item in data:
        try:
            sid = int(item.get("service"))
        except (TypeError, ValueError):
            continue
        delivery = extract_provider_delivery_minutes(item)
        if delivery is None:
            continue
        # Skip services where an admin manually set the average time — don't let
        # the provider's auto-parsed value stomp a deliberate override.
        res = await db.curated_services.update_many(
            {"service_id": sid, "delivery_minutes_manual": {"$ne": True}},
            {"$set": {"delivery_minutes": delivery}},
        )
        updated += int(res.matched_count or 0)

    if cache is not None:
        import time
        cache[provider_id or "__default__"] = time.time()
    return updated
