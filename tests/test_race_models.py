import unittest
from datetime import datetime, timezone

from race_models import utc_now_iso


class RaceModelsTests(unittest.TestCase):
    def test_utc_now_iso_is_utc_with_z_suffix(self) -> None:
        stamp = utc_now_iso()
        self.assertTrue(stamp.endswith("Z"))
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        self.assertEqual(parsed.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
