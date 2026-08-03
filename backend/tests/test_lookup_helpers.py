import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "testdb")

from server import _parse_delivery_minutes


class LookupHelpersTests(unittest.TestCase):
    def test_parse_delivery_minutes_handles_hour_and_minute_mix(self):
        self.assertEqual(_parse_delivery_minutes("Delivery in 1 hour 30 minutes"), 90)
        self.assertEqual(_parse_delivery_minutes("Starts in 45 mins"), 45)
        self.assertEqual(_parse_delivery_minutes("1h 15m"), 75)


if __name__ == "__main__":
    unittest.main()
