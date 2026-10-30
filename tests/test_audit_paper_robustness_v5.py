"""Offline regression checks for paper robustness audit; never place orders."""
import unittest
from audit_paper_robustness_v5 import audit, modeled_net_r, summarize, max_loss_streak, sum_r_drawdown


def trade(entry_open, gross_r, side="bearish", risk=2):
    return {"watchKnownUTC":entry_open-7200,"entryOpenUTC":entry_open,
            "entry":100,"risk":risk,"realizedR":gross_r,"side":side}


class TestPaperRobustnessAudit(unittest.TestCase):
    def test_cost_repricing_is_consistent_and_monotonic(self):
        t=trade(10_000,2)
        self.assertAlmostEqual(modeled_net_r(t,9),1.91)
        self.assertAlmostEqual(modeled_net_r(t,25),1.75)
        self.assertGreater(modeled_net_r(t,3),modeled_net_r(t,25))

    def test_nan_invalid_risk_rejected(self):
        with self.assertRaises(ValueError):
            modeled_net_r(trade(10_000,1,risk=0),9)
        with self.assertRaises(ValueError):
            modeled_net_r(trade(10_000,1),-1)

    def test_drawdown_and_losing_streak(self):
        seq=[1,-1,-2,2,-1,-1]
        self.assertEqual(max_loss_streak(seq),2)
        self.assertEqual(sum_r_drawdown(seq),3)

    def test_no_trades_has_null_metrics(self):
        s=summarize([],9)
        self.assertEqual(s["trades"],0)
        self.assertIsNone(s["meanNetR"])
        self.assertIsNone(s["winFraction"])

    def test_train_holdout_are_fixed_and_low_n_not_deployable(self):
        cutoff=1775001600 # 2026-04-01 00:00 UTC
        trades=[trade(cutoff-3600,1),trade(cutoff+3600,2)]
        payload={"mode":"PAPER_ONLY_OFFLINE_EXPERIMENT",
                 "fixedSplitUTC":"2026-04-01T00:00:00+00:00",
                 "results":{"SOLUSDT_PERP.A":{
                     "status":"PAPER_BACKTEST_NOT_LIVE","alertsCount":3,
                     "trades":trades,"hypotheticalClosedTrades":2}}}
        report=audit(payload)["pairs"]["SOLUSDT_PERP.A"]
        self.assertFalse(report["deploymentReady"])
        self.assertEqual(report["breakdown"]["training"]["original_9bps_per_side"]["trades"],1)
        self.assertEqual(report["breakdown"]["holdout"]["original_9bps_per_side"]["trades"],1)
        self.assertFalse(report["holdoutHas30Trades"])

    def test_bad_origin_rejected(self):
        with self.assertRaises(ValueError):
            audit({"mode":"LIVE_TRADING","fixedSplitUTC":"2026-04-01T00:00:00Z",
                   "results":{}})


if __name__=="__main__":
    unittest.main()
