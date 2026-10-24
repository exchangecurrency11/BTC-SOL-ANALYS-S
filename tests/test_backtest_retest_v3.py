"""No-lookahead paper entry / stop / TP tests. Deterministic synthetic bars."""
import unittest
from unittest.mock import patch

from backtest_retest_v3 import (
    assess_candle, earliest_stop, init_position, reaction_confirmed, replay_pair,
)

H = 3600
D = 86400
START = 1735689600


def history():
    hourly = []
    for i in range(100):
        o = c = 100.0
        h, l = 100.2, 99.8
        v = 100.0
        if i == 79:
            o, c, h, l, v = 102, 100.8, 102.2, 100.5, 300
        elif i == 80:
            o, c, h, l = 101.1, 100.4, 101.3, 100.1
        elif i == 81:
            o, c, h, l = 100.4, 99.0, 100.5, 97.5
        elif i == 82:
            o, c, h, l = 99.0, 100.0, 103.0, 98.0
        hourly.append(dict(t=START+i*H,o=o,c=c,h=h,l=l,v=v))
    four = [dict(t=START+(i-70)*4*H,o=100.,c=100.,h=100.5,l=99.5,v=100.)
            for i in range(75)]
    daily = [dict(t=START+(i-70)*D,o=100.,c=100.,h=100.5,l=99.5,v=100.)
             for i in range(75)]
    return hourly,four,daily


class V3Tests(unittest.TestCase):
    def test_retest_requires_later_candle_and_reaction(self):
        prev = dict(c=101)
        red = dict(o=101.1,c=100.4,l=100.1,h=101.3)
        self.assertTrue(reaction_confirmed("bearish",red,prev,101))
        self.assertFalse(reaction_confirmed("bearish",red,prev,102))
        self.assertFalse(reaction_confirmed("bullish",red,prev,101))

    def test_stop_first_on_ambiguous_candle(self):
        p = init_position({"side":"bearish","stop":102,"watchKnownUTC":START,
                           "retestKnownUTC":START+H}, 100, START+2*H)
        self.assertIsNotNone(p)
        closed,reason=assess_candle(p,dict(o=100,h=102.5,l=93,c=95))
        self.assertTrue(closed)
        self.assertEqual(reason,"STOP_FIRST_OR_AFTER_TP")
        self.assertEqual(p["targetCount"],0)
        self.assertAlmostEqual(p["realizedR"],-1)

    def test_all_targets_with_no_stop(self):
        p = init_position({"side":"bearish","stop":102,"watchKnownUTC":START,
                           "retestKnownUTC":START+H}, 100, START+2*H)
        closed,reason=assess_candle(p,dict(o=100,h=100,l=93,c=94))
        self.assertTrue(closed)
        self.assertEqual(reason,"TP3_COMPLETE")
        self.assertEqual(p["targetCount"],3)
        self.assertEqual(p["realizedR"],2.0)

    def test_risk_and_direction_safety(self):
        self.assertIsNone(init_position({"side":"bearish","stop":99,
                                         "watchKnownUTC":START,
                                         "retestKnownUTC":START+H},100,START+H))
        self.assertIsNone(init_position({"side":"bullish","stop":105,
                                         "watchKnownUTC":START,
                                         "retestKnownUTC":START+H},100,START+H))
        self.assertIsNone(init_position({"side":"bearish","stop":120,
                                         "watchKnownUTC":START,
                                         "retestKnownUTC":START+H},100,START+H))

    def test_replay_waits_for_retest_and_next_open(self):
        hourly,four,daily=history()
        event_at=hourly[79]["t"]
        def fake_analysis(_, interval, as_of):
            events = ([{"event":"BOS","direction":"bearish","at":event_at,
                       "brokenLevel":101.0}] if as_of==event_at+H else [])
            return {"structure": events}
        fake_ind={"RSI14":35.0,"hist":-1.0}
        with patch("backtest_retest_v3.analyze",side_effect=fake_analysis), \
             patch("backtest_retest_v3.indicators",return_value=fake_ind), \
             patch("backtest_retest_v3.bias",return_value="bearish"):
            report = replay_pair(hourly,four,daily,as_of=START+90*H)
            before = replay_pair(hourly,four,daily,as_of=START+80*H)
        self.assertEqual(before["alertsCount"],1)
        self.assertEqual(before["hypotheticalClosedTrades"],0)
        self.assertEqual(report["alertsCount"],1)
        self.assertEqual(report["hypotheticalClosedTrades"],1)
        trade=report["trades"][0]
        self.assertEqual(trade["watchKnownUTC"],hourly[79]["t"]+H)
        self.assertEqual(trade["retestKnownUTC"],hourly[80]["t"]+H)
        self.assertEqual(trade["entryOpenUTC"],hourly[81]["t"])
        self.assertEqual(trade["entry"],100.4)
        self.assertEqual(trade["exitKnownUTC"],hourly[82]["t"]+H)
        self.assertEqual(trade["targetCount"],1)
        self.assertEqual(trade["exitReason"],"STOP_FIRST_OR_AFTER_TP")
        self.assertLess(trade["netRIllustrative"],trade["realizedR"])

    def test_no_premature_higher_tf_future(self):
        hourly,four,daily=history()
        with patch("backtest_retest_v3.analyze",
                   return_value={"structure":[]}) as mock:
            replay_pair(hourly,four,daily,as_of=START+80*H)
        self.assertEqual(mock.call_count,1)


if __name__=="__main__":
    unittest.main()
