"""Regression tests for market_structure.py (no network calls, no credentials)."""
import math
import unittest

from market_structure import analyze, candles_from_history

START = 1735689600  # 2025-01-01 00:00:00 UTC
HOUR = 3600


def fixture():
    rows = []
    for i in range(80):
        close = 100 + 2 * math.sin(i * .45)
        op = close - .1
        if i == 77:
            op = close + .6  # last down candle before breakout
        if i == 78:
            op, close = 105.5, 107.5  # large displacement / BOS
        if i == 79:
            op, close = 107.5, 107.2
        high = max(op, close) + .25
        low = min(op, close) - .25
        rows.append({"t": START + i * HOUR, "o": op, "h": high,
                     "l": low, "c": close, "v": 3000 if i == 78 else 1000})
    return rows


class TestClosedBarMarketStructure(unittest.TestCase):
    def test_rejects_current_open_candle(self):
        rows = fixture()
        close_of_last = rows[-1]["t"] + HOUR
        base = analyze(rows, "1hour", close_of_last)
        future = rows[-1].copy()
        future["t"] += HOUR
        future["o"] = 500
        future["h"] = 600
        future["l"] = 400
        future["c"] = 550
        after = analyze(rows + [future], "1hour", close_of_last)
        self.assertEqual(base, after)
        self.assertEqual(after["closedCandles"], 80)

    def test_structural_break_and_ob(self):
        rows = fixture()
        result = analyze(rows, "1hour", rows[-1]["t"] + HOUR)
        self.assertEqual(result["status"], "READY")
        bullish_breaks = [x for x in result["structure"]
                          if x["direction"] == "bullish" and x["at"] == rows[78]["t"]]
        self.assertTrue(bullish_breaks, result["structure"])
        candidates = [x for x in result["orderBlocks"]
                      if x["side"] == "bullish" and x["breakAt"] == rows[78]["t"]]
        self.assertTrue(candidates, result["orderBlocks"])
        self.assertEqual(candidates[-1]["originAt"], rows[77]["t"])
        self.assertIn(candidates[-1]["state"], ("fresh", "retested", "invalidated"))

    def test_fvg_uses_three_closed_bars(self):
        rows = fixture()
        result = analyze(rows, "1hour", rows[-1]["t"] + HOUR)
        gaps = [x for x in result["fvg"]
                if x["side"] == "bullish" and x["formedAt"] == rows[78]["t"]]
        self.assertTrue(gaps)
        self.assertGreater(gaps[-1]["high"], gaps[-1]["low"])

    def test_short_history_stays_non_signaling(self):
        rows = fixture()[:20]
        result = analyze(rows, "1hour", rows[-1]["t"] + HOUR)
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(result["orderBlocks"], [])

    def test_bad_prices_and_duplicates_fail(self):
        rows = fixture()
        with self.assertRaises(ValueError):
            candles_from_history(rows + [rows[-1]], "1hour", rows[-1]["t"] + HOUR)
        bad = [r.copy() for r in rows]
        bad[3]["h"] = bad[3]["l"] - 1
        with self.assertRaises(ValueError):
            candles_from_history(bad, "1hour", rows[-1]["t"] + HOUR)
        bad[3]["h"] = float("nan")
        with self.assertRaises(ValueError):
            candles_from_history(bad, "1hour", rows[-1]["t"] + HOUR)


if __name__ == "__main__":
    unittest.main()
