"""Point-in-time October 24 regression for experimental BTC/SOL decision cards.

Archived source snapshots are taken from real GitHub commits. Tests do not
depend on later prices, live exchange APIs, notification delivery, or orders.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from signal_decision_v2 import decide, decide_all

FIXTURE = Path(__file__).parent / "fixtures" / "oct24_point_in_time_snapshots.json"
SYMBOL_SOL = "SOLUSDT_PERP.A"
SYMBOL_BTC = "BTCUSDT_PERP.A"


def snapshot(label):
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    return next(c for c in cases if label in c["label"])


class TestExperimentalDecisionV2(unittest.TestCase):
    def test_sol_13_bearish_bos_identified_on_time(self):
        prev, current = snapshot("12:00"), snapshot("13:00")
        sol = decide(SYMBOL_SOL, current["market"], current["structure"],
                     previous_market=prev["market"],
                     previous_structure=prev["structure"])
        self.assertEqual(sol["closeTimeUTC"], "2026-10-24T10:00:00.000Z")
        self.assertEqual(sol["lastClosed1H"], 101.38)
        self.assertEqual(sol["marketDirection"]["label"], "SHORT_PRIORITY")
        self.assertEqual(sol["marketDirection"]["fourHour"], "bearish")
        self.assertEqual(sol["marketDirection"]["daily"], "bearish")
        self.assertEqual(sol["earlyAlert"], "EARLY_SHORT_WARNING")
        matches = [e for e in sol["events"] if e["kind"] == "BOS_MOMENTUM_WATCH"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["side"], "bearish")
        self.assertEqual(matches[0]["level"], 101.63)
        self.assertEqual(matches[0]["knownAtUTC"], sol["closeTimeUTC"])
        self.assertAlmostEqual(sol["hourlyIndicators"]["RSI14"], 29.5891)
        self.assertAlmostEqual(sol["hourlyIndicators"]["MACDHistogram"], -0.1217)
        self.assertAlmostEqual(sol["hourlyIndicators"]["volumeChangePct"], 107.9519)
        self.assertTrue(any("oversold" in r for r in sol["riskNotes"]))
        self.assertEqual(sol["tradeEntry"]["status"], "NOT_CONFIRMED")
        self.assertIsNone(sol["tradeEntry"]["entry"])
        self.assertIsNone(sol["tradeEntry"]["stop"])
        self.assertIsNone(sol["tradeEntry"]["TP1"])

    def test_no_future_signal_before_13(self):
        earlier = snapshot("12:00")
        sol = decide(SYMBOL_SOL, earlier["market"], earlier["structure"])
        self.assertEqual(sol["closeTimeUTC"], "2026-10-24T09:00:00.000Z")
        self.assertFalse(any(e.get("level") == 101.63 for e in sol["events"]))

    def test_btc_and_sol_19_breakout_watches(self):
        prev, current = snapshot("18:00"), snapshot("19:00")
        cards = decide_all(current["market"], current["structure"],
                           previous_market=prev["market"],
                           previous_structure=prev["structure"])
        self.assertEqual({s["symbol"] for s in cards}, {SYMBOL_BTC, SYMBOL_SOL})
        by_symbol = {card["symbol"]: card for card in cards}
        for symbol in (SYMBOL_BTC, SYMBOL_SOL):
            card = by_symbol[symbol]
            self.assertEqual(card["earlyAlert"], "EARLY_SHORT_WARNING")
            self.assertEqual(card["tradeEntry"]["status"], "NOT_CONFIRMED")
            self.assertFalse(card["conflictsHigherTimeframe"])
        self.assertEqual(by_symbol[SYMBOL_SOL]["lastClosed1H"], 100.33)

    def test_removed_confirmation_downgrades_bos(self):
        prev, current = snapshot("12:00"), deepcopy(snapshot("13:00"))
        sol = next(z for z in current["market"]["results"]
                   if z["symbol"] == SYMBOL_SOL and z["interval"] == "1hour")
        sol["indicators"]["MACDHistogram"] = 0.1
        result = decide(SYMBOL_SOL, current["market"], current["structure"],
                        previous_market=prev["market"],
                        previous_structure=prev["structure"])
        self.assertNotEqual(result["earlyAlert"], "EARLY_SHORT_WARNING")
        self.assertIn("BOS_NEEDS_CONFIRMATION", [e["kind"] for e in result["events"]])

    def test_structure_timestamp_mismatch_fails_closed(self):
        snap = deepcopy(snapshot("13:00"))
        sol = next(z for z in snap["structure"]["results"]
                   if z["symbol"] == SYMBOL_SOL and z["interval"] == "1hour")
        sol["lastCloseTimeUTC"] = "2026-10-24T09:00:00Z"
        with self.assertRaises(ValueError):
            decide(SYMBOL_SOL, snap["market"], snap["structure"])

    def test_old_higher_timeframe_fails_closed(self):
        snap = deepcopy(snapshot("13:00"))
        sol = next(z for z in snap["market"]["results"]
                   if z["symbol"] == SYMBOL_SOL and z["interval"] == "4hour")
        sol["closeTimeUTC"] = "2026-10-24T04:00:00Z"
        matching = next(z for z in snap["structure"]["results"]
                        if z["symbol"] == SYMBOL_SOL and z["interval"] == "4hour")
        matching["lastCloseTimeUTC"] = "2026-10-24T04:00:00Z"
        with self.assertRaises(ValueError):
            decide(SYMBOL_SOL, snap["market"], snap["structure"])

    def test_future_previous_snapshot_is_rejected(self):
        current, future = snapshot("13:00"), snapshot("19:00")
        with self.assertRaises(ValueError):
            decide(SYMBOL_SOL, current["market"], current["structure"],
                   previous_market=future["market"],
                   previous_structure=future["structure"])

    def test_ob_touch_requires_prior_snapshot_and_closed_reaction(self):
        prev, current = deepcopy(snapshot("18:00")), deepcopy(snapshot("19:00"))
        def ob(retests):
            return {"side": "bearish", "originAt": 1792800000,
                    "confirmedAt": 1792810800, "state": "retested",
                    "wick": {"low": 101.30, "high": 101.45},
                    "body": {"low": 101.34, "high": 101.40},
                    "retests": retests}
        prev_structure = next(z for z in prev["structure"]["results"]
                              if z["symbol"] == SYMBOL_SOL and z["interval"] == "1hour")
        cur_structure = next(z for z in current["structure"]["results"]
                             if z["symbol"] == SYMBOL_SOL and z["interval"] == "1hour")
        prev_structure["candidateOrderBlocks"].append(ob(0))
        cur_structure["candidateOrderBlocks"].append(ob(1))
        with_previous = decide(SYMBOL_SOL, current["market"], current["structure"],
                               previous_market=prev["market"],
                               previous_structure=prev["structure"])
        self.assertIn("OB_RETEST_RESPONSE_WATCH",
                      [e["kind"] for e in with_previous["events"]])
        without_previous = decide(SYMBOL_SOL, current["market"], current["structure"])
        self.assertNotIn("OB_RETEST_RESPONSE_WATCH",
                         [e["kind"] for e in without_previous["events"]])

    def test_no_new_event_does_not_hide_direction(self):
        later = snapshot("23:00")
        sol = decide(SYMBOL_SOL, later["market"], later["structure"])
        self.assertEqual(sol["marketDirection"]["label"], "SHORT_PRIORITY")
        self.assertEqual(sol["earlyAlert"], "NO_NEW_EARLY_TRIGGER")
        self.assertEqual(sol["tradeEntry"]["status"], "NOT_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
