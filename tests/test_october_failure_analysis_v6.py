"""Offline regression tests for October extension and descriptive loss grouping."""
import unittest
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime,timezone

from extend_binance_archive_october_v6 import (
    days_inclusive, day_bound, parse_daily_zip,append_histories,
)
from analyze_failure_patterns_v6 import audit, classify

BASE_TIME=int(datetime(2026,10,1,tzinfo=timezone.utc).timestamp())


def raw_daily(symbol="BTCUSDT", day="2026-10-01", missing=-1):
    start,_=day_bound(day)
    bytes_io=BytesIO()
    with ZipFile(bytes_io,"w") as z:
        content=[]
        for n in range(24):
            if n==missing: continue
            t=start+n*3600
            content.append(f"{t*1000},100,103,99,102,15,0,0,0,0,0,0")
        z.writestr(f"{symbol}-1h-{day}.csv","\n".join(content))
    return bytes_io.getvalue()


def record(t):
    return {"t":t,"o":100,"h":101,"l":99,"c":100,"v":20}


def paper(known,entry,side="bearish"):
    stop=102 if side=="bearish" else 98
    return {"watchKnownUTC":known,"retestKnownUTC":entry,"entryOpenUTC":entry,
            "entry":100,"risk":2,"realizedR":-1,"stop":stop,"side":side,
            "targetCount":0,"exitReason":"STOP_FIRST_OR_AFTER_TP"}


class TestOctoberAndFailurePatterns(unittest.TestCase):
    def test_valid_daily_24_complete_1h(self):
        bars=parse_daily_zip(raw_daily(),"BTCUSDT","2026-10-01")
        self.assertEqual(len(bars),24)
        self.assertEqual(bars[0]["t"],BASE_TIME)
        self.assertEqual(bars[-1]["t"],BASE_TIME+23*3600)

    def test_partial_daily_fails(self):
        with self.assertRaises(ValueError):
            parse_daily_zip(raw_daily(missing=5),"BTCUSDT","2026-10-01")

    def test_wrong_symbol_archive_rejected(self):
        with self.assertRaises(ValueError):
            parse_daily_zip(raw_daily(),"SOLUSDT","2026-10-01")

    def test_days_inclusive_and_invalid_order(self):
        self.assertEqual(days_inclusive("2026-10-01","2026-10-03"),
                         ["2026-10-01","2026-10-02","2026-10-03"])
        with self.assertRaises(ValueError):
            days_inclusive("2026-10-03","2026-10-01")

    def test_append_exact_monthly_to_daily_continuity(self):
        base_start=BASE_TIME-24*3600
        originals=[{"symbol":s+"_PERP.A",
                    "history":[record(base_start+i*3600) for i in range(24)]}
                   for s in ("BTCUSDT","SOLUSDT")]
        daily={(s,"2026-10-01"):[record(BASE_TIME+i*3600) for i in range(24)]
               for s in ("BTCUSDT","SOLUSDT")}
        joined=append_histories(originals,daily,["2026-10-01"])
        self.assertEqual(len(joined[("BTCUSDT","1hour")]),48)
        self.assertEqual(len(joined[("SOLUSDT","4hour")]),12)
        self.assertEqual(len(joined[("BTCUSDT","daily")]),2)
        bad={(s,"2026-10-01"):[record(BASE_TIME+3600+i*3600) for i in range(24)]
             for s in ("BTCUSDT","SOLUSDT")}
        with self.assertRaises(ValueError):
            append_histories(originals,bad,["2026-10-01"])

    def test_classification_only_uses_bos_known_features(self):
        known=BASE_TIME
        t=paper(known,known+2*3600)
        a={"knownUTC":known,"side":"bearish","RSI14":24.0,"volumeChangePct":110.0}
        features=classify(a,t)
        self.assertTrue(features["extremeRSI"])
        self.assertEqual(features["volumeBand"],"100%+")
        self.assertEqual(features["retestDelayBand"],"1-2h")
        self.assertTrue(features["failedBeforeTP1"])

    def test_missing_warning_refuses_trade(self):
        known=BASE_TIME
        src={"mode":"PAPER_ONLY_OFFLINE_EXPERIMENT",
             "results":{"BTCUSDT_PERP.A":{"status":"PAPER_BACKTEST_NOT_LIVE",
                      "alertsCount":0,"alerts":[],"trades":[paper(known,known+7200)]}}}
        with self.assertRaises(ValueError):
            audit(src)

    def test_no_paper_trades_safe(self):
        src={"mode":"PAPER_ONLY_OFFLINE_EXPERIMENT",
             "results":{"BTCUSDT_PERP.A":{"status":"PAPER_BACKTEST_NOT_LIVE",
                      "alertsCount":0,"alerts":[],"trades":[]}}}
        out=audit(src)["results"]["BTCUSDT_PERP.A"]
        self.assertEqual(out["paperTrades"],0)
        self.assertIsNone(out["subgroupsObservedAssociationsOnly"]["extremeRSI"]
                          ["extremeAtWarning"]["meanNetR"])


if __name__=="__main__":
    unittest.main()
