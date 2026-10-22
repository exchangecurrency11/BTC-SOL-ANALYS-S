#!/usr/bin/env python3
"""Read-only 1H historical early-watch replay for BTC and SOL perpetual.

Reads an archived Coinalyze /history?interval=1hour response. Does NOT place
trades, imply fills, compute profit/win rate, or persist a live signal.
"""
import argparse
from datetime import datetime, timezone
import json
import time

from early_signal_experiment import evaluate, replay
from market_structure import candles_from_history

SYMBOLS = {"BTCUSDT_PERP.A", "SOLUSDT_PERP.A"}
HOUR = 3600


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def generate(payload, *, as_of, lookback):
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("Expected two Coinalyze symbol histories")
    if {r.get("symbol") for r in payload} != SYMBOLS:
        raise ValueError("Unexpected symbols")
    groups = []
    for item in payload:
        symbol = item["symbol"]
        bars = candles_from_history(item["history"], "1hour", as_of=as_of)
        if len(bars) < 45:
            groups.append({"symbol": symbol, "status": "INSUFFICIENT_HISTORY"})
            continue
        last_close = bars[-1]["t"] + HOUR
        observations = replay(item["history"], as_of=last_close, lookback=lookback)
        snapshot = evaluate(item["history"], as_of=last_close)
        groups.append({
            "symbol": symbol,
            "status": "READY",
            "closedCandles": len(bars),
            "lastCloseTimeUTC": iso(last_close),
            "lastPrice": bars[-1]["c"],
            "currentExperimentalWatch": snapshot["watch"],
            "events": [{**event, "knownAtUTC": iso(event["knownAt"])}
                       for event in observations],
            "eventsCount": len(observations),
        })
    return {
        "mode": "HISTORICAL_PAPER_TEST_ONLY",
        "source": "Coinalyze third-party closed Binance perpetual OHLCV",
        "asOfUTC": iso(as_of),
        "parameters": {"lookbackHours": lookback},
        "limitations": [
            "No proven edge, no profit estimates, no win rate",
            "Retests/wicks not executable fills; no intrabar order of events",
            "Not adjusted for spreads, fees, slippage, funding, or order-book",
            "1H early watch lacks integrated 4H/Daily trading confirmation",
        ],
        "results": groups,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--lookback", type=int, default=168)
    p.add_argument("--as-of", type=int, default=None)
    args = p.parse_args()
    if not 1 <= args.lookback <= 300:
        p.error("lookback must be 1–300 hours")
    with open(args.input, encoding="utf-8") as f:
        payload = json.load(f)
    now = int(time.time()) if args.as_of is None else args.as_of
    result = generate(payload, as_of=now, lookback=args.lookback)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for group in result["results"]:
        print(group["symbol"], group["status"], "events", group.get("eventsCount", 0),
              "watch", group.get("currentExperimentalWatch", "n/a"))


if __name__ == "__main__":
    main()
