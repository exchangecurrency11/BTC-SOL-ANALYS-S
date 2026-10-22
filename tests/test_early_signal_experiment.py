"""Offline regression tests for experimental early-watch logic (no exchange/API)."""
import math
import unittest
from unittest.mock import patch

from early_signal_experiment import evaluate, replay, macd_histogram
from market_structure import analyze

START = 1735689600
HOUR = 3600


def history(n=90):
    candles = []
    for i in range(n):
        close = 100 + 2 * math.sin(i * 0.45)
        op = close - 0.1
        if i == 77:
            op = close + 0.6
        if i == 78:
            op, close = 105.5, 107.5
        if i == 79:
            op, close = 107.5, 107.2
        candles.append({"t": START + i * HOUR, "o": op,
                        "h": max(op, close) + 0.25,
                        "l": min(op, close) - 0.25,
                        "c": close, "v": 3000 if i == 78 else 1000})
    return candles


class TestExperimentalEarlyWatch(unittest.TestCase):
    def test_requires_explicit_closed_time(self):
        rows = history()
        with self.assertRaises(ValueError):
            evaluate(rows, as_of=None)
        with self.assertRaises(ValueError):
            evaluate(rows, as_of=rows[-1]["t"] + HOUR, interval="4hour")

    def test_future_open_candle_does_not_leak(self):
        rows = history(80)
        close = rows[-1]["t"] + HOUR
        base = evaluate(rows, as_of=close)
        future = rows[-1].copy()
        future.update(t=close, o=500, h=600, l=400, c=550)
        next_snapshot = evaluate(rows + [future], as_of=close)
        self.assertEqual(base, next_snapshot)

    def test_early_warning_is_known_at_close_not_open(self):
        rows = history()
        t = rows[-1]["t"]
        close = t + HOUR
        structural_snapshot = {
            "lastCloseTimeUTC": close,
            "structure": [{"event": "CHoCH", "direction": "bearish",
                           "at": t, "brokenLevel": 102.0}],
            "orderBlocks": []
        }
        with patch("early_signal_experiment.analyze", return_value=structural_snapshot):
            result = evaluate(rows, as_of=close)
        self.assertEqual(result["watch"], "WATCH_SHORT")
        self.assertEqual(result["events"][0]["knownAt"], close)
        self.assertEqual(result["events"][0]["kind"], "DIRECTION_CHANGE_WARNING")

    def test_ob_retest_needs_closed_candle_reaction(self):
        rows = history()
        last = rows[-1]
        prev = rows[-2]
        prev.update(o=101.5, c=101.6, h=101.75, l=101.4)
        last.update(o=99.5, c=102.1, h=102.25, l=99.0)
        wick = {"low": 99.0, "high": 101.0}
        zone = {"side": "bullish", "state": "retested",
                "confirmedAt": last["t"] - HOUR, "wick": wick,
                "body": {"low": 99.2, "high": 99.7}}
        analysis = {"lastCloseTimeUTC": last["t"] + HOUR,
                    "structure": [], "orderBlocks": [zone]}
        with patch("early_signal_experiment.analyze", return_value=analysis):
            result = evaluate(rows, as_of=last["t"] + HOUR)
        self.assertEqual(result["watch"], "WATCH_LONG")
        self.assertEqual(result["events"][0]["kind"], "OB_RETEST_RESPONSE")
        last.update(o=102.1, c=99.5, h=102.25, l=99.0)
        with patch("early_signal_experiment.analyze", return_value=analysis):
            result = evaluate(rows, as_of=last["t"] + HOUR)
        self.assertNotIn("OB_RETEST_RESPONSE", [e["kind"] for e in result["events"]])

    def test_invalidation_does_not_invent_reverse_short(self):
        rows = history()
        t = rows[-1]["t"]
        analysis = {"lastCloseTimeUTC": t + HOUR,
                    "structure": [],
                    "orderBlocks": [{"side": "bullish", "state": "invalidated",
                                     "invalidatedAt": t,
                                     "wick": {"low": 98.0, "high": 101.0}}]}
        with patch("early_signal_experiment.analyze", return_value=analysis):
            result = evaluate(rows, as_of=t + HOUR)
        self.assertEqual(result["watch"], "BEKLE")
        self.assertEqual(result["events"][0]["kind"], "OB_INVALIDATED")

    def test_real_structure_events_have_close_confirmation(self):
        rows = history(80)
        close = rows[-1]["t"] + HOUR
        result = analyze(rows, "1hour", close)
        for event in result["structure"]:
            self.assertEqual(event["confirmedAt"], event["at"] + HOUR)
        for zone in result["orderBlocks"]:
            self.assertEqual(zone["breakConfirmedAt"], zone["breakAt"] + HOUR)
            if zone["invalidatedAt"] is not None:
                self.assertEqual(zone["invalidationConfirmedAt"],
                                 zone["invalidatedAt"] + HOUR)
        for gap in result["fvg"]:
            self.assertEqual(gap["confirmedAt"], gap["formedAt"] + HOUR)
            if gap["fullyFilledAt"] is not None:
                self.assertEqual(gap["fullyFilledConfirmedAt"],
                                 gap["fullyFilledAt"] + HOUR)

    def test_macd_only_closed_history(self):
        values = [float(i) for i in range(60)]
        hist, prev = macd_histogram(values)
        self.assertIsInstance(hist, float)
        self.assertIsInstance(prev, float)

    def test_replay_never_sees_future_history(self):
        rows = history(90)
        as_of = rows[79]["t"] + HOUR
        expected = replay(rows[:80], as_of=as_of, lookback=15)
        actual = replay(rows, as_of=as_of, lookback=15)
        self.assertEqual(expected, actual)
        self.assertTrue(all(e["knownAt"] <= as_of for e in actual))


if __name__ == "__main__":
    unittest.main()
