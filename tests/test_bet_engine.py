import json
import unittest
from pathlib import Path

from bet_engine import RiskCaps, generate_bet_decision


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "bet_library.json").read_text(encoding="utf-8"))


def make_race_state() -> dict:
    return {
        "tick_ts_utc": "2026-03-01T17:22:13Z",
        "flag_status": "GREEN",
        "cooldown_state": {
            "last_neutralization": "NONE",
            "seconds_since_green_from_yellow_or_vsc": None,
            "seconds_since_safety_car_restart": None,
        },
        "active_events": [
            {
                "event_id": "evt_20260301_9001",
                "event_type": "RETIREMENT",
                "severity": "CRITICAL",
                "confidence": 0.99,
                "timestamp_s": 101.0,
            }
        ],
    }


def make_market_quote(**overrides: dict) -> dict:
    quote = {
        "market_id": "mkt_driver_retirement_77",
        "market_type": "DRIVER_RETIREMENT",
        "is_live": True,
        "implied_probability": 0.46,
        "quote_age_s": 2.5,
        "liquidity_usd": 5000.0,
    }
    quote.update(overrides)
    return quote


def decide_with_quote(quote: dict) -> dict:
    return generate_bet_decision(
        race_state=make_race_state(),
        market_quotes=[quote],
        model_probability=0.67,
        decision_confidence=0.89,
        risk=RiskCaps(bankroll_usd=1000.0),
        policy=POLICY,
        event_context={"retirement_confirmed": True},
    )


class BetEngineMarketDataValidationTests(unittest.TestCase):
    def test_missing_implied_probability_returns_no_bet(self) -> None:
        quote = make_market_quote()
        del quote["implied_probability"]

        decision = decide_with_quote(quote)

        self.assertEqual(decision["action"], "NO_BET")
        self.assertEqual(decision["reason"], "Market implied probability missing/invalid")

    def test_invalid_implied_probability_string_or_range_returns_no_bet(self) -> None:
        invalid_values = ["abc", 1.25]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                decision = decide_with_quote(make_market_quote(implied_probability=invalid))
                self.assertEqual(decision["action"], "NO_BET")
                self.assertEqual(decision["reason"], "Market implied probability missing/invalid")

    def test_is_live_false_string_is_not_tradable(self) -> None:
        decision = decide_with_quote(make_market_quote(is_live="false"))

        self.assertEqual(decision["action"], "NO_BET")
        self.assertIn("No live candidate market available", decision["reason"])

    def test_missing_quote_age_returns_no_bet(self) -> None:
        quote = make_market_quote()
        del quote["quote_age_s"]

        decision = decide_with_quote(quote)

        self.assertEqual(decision["action"], "NO_BET")
        self.assertEqual(decision["reason"], "Quote age missing/invalid")

    def test_none_quote_age_does_not_crash_and_returns_no_bet(self) -> None:
        decision = decide_with_quote(make_market_quote(quote_age_s=None))

        self.assertEqual(decision["action"], "NO_BET")
        self.assertEqual(decision["reason"], "Quote age missing/invalid")

    def test_missing_liquidity_returns_no_bet(self) -> None:
        quote = make_market_quote()
        del quote["liquidity_usd"]

        decision = decide_with_quote(quote)

        self.assertEqual(decision["action"], "NO_BET")
        self.assertEqual(decision["reason"], "Market liquidity missing/invalid")

    def test_valid_quote_still_places_bet(self) -> None:
        decision = decide_with_quote(make_market_quote())

        self.assertEqual(decision["action"], "PLACE_BET")
        self.assertEqual(decision["side"], "YES")
        self.assertGreater(decision["size_usd"], 0)


if __name__ == "__main__":
    unittest.main()
