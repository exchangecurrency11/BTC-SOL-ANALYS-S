#!/usr/bin/env python3
"""Reproduce archived Oct 24 BTC/SOL three-stage decision cards.

Only point-in-time snapshots are read. Never imports live candles, never sends
signals or orders. Sparse snapshots CANNOT validate historical trade outcomes.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from signal_decision_v2 import decide_all


def epoch(x):
    return datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()


def audit(archive):
    records = sorted(archive["cases"], key=lambda x: epoch(x["timeUTC"]))
    out = []
    prev = None
    for case in records:
        contiguous = prev and epoch(case["timeUTC"]) - epoch(prev["timeUTC"]) == 3600
        kwargs = ({"previous_market": prev["market"],
                   "previous_structure": prev["structure"]} if contiguous else {})
        decisions = decide_all(case["market"], case["structure"], **kwargs)
        out.append({
            "timeUTC": case["timeUTC"],
            "timeTSI": datetime.fromtimestamp(epoch(case["timeUTC"]),
                                             tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "sourceMarketCommit": case["sourceMarketCommit"],
            "sourceStructureCommit": case["sourceStructureCommit"],
            "hasPreviousHourSnapshot": bool(contiguous),
            "decisions": decisions,
        })
        prev = case
    return {
        "status": "READ_ONLY_HISTORICAL_AUDIT",
        "description": "Directional bias / early watch / entry qualification kept separate",
        "source": "Archived Coinalyze Binance USDT perpetual point-in-time GitHub commits",
        "limitations": [
            "Sparse snapshots; not comprehensive hourly backtest",
            "No entry, stop, target, fill, fees, slippage, funding or real P&L",
            "Watch is not proof of profitable strategy",
            "Not deployed on main branch or linked to live alerts",
        ],
        "samples": out,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="tests/fixtures/oct24_point_in_time_snapshots.json")
    parser.add_argument("--output", default="oct24_signal_v2_audit.json")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = audit(data)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    print("Date/UTC            Pair    4H+Daily direction       Early watch              Entry")
    for sample in result["samples"]:
        for row in sample["decisions"]:
            symbol = row["symbol"].split("USDT")[0]
            print(f'{sample["timeUTC"][:16]:19} {symbol:6} '
                  f'{row["marketDirection"]["label"]:23} '
                  f'{row["earlyAlert"]:24} {row["tradeEntry"]["status"]}')


if __name__ == "__main__":
    main()
