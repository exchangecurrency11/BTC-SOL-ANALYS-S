#!/usr/bin/env python3
"""Build an independent market_structure_data.json from live, CLOSED Coinalyze history.

Reads three history_*.json files downloaded from our Cloudflare Worker and
verifies every symbol/timeframe against existing market_data.json. This is an
additional analysis artifact: publishing market_data.json never depends on it.
"""
from datetime import datetime, timezone
import json
import time

from market_structure import analyze, SECONDS

SYMBOLS = {"BTCUSDT_PERP.A", "SOLUSDT_PERP.A"}
INTERVALS = ("1hour", "4hour", "daily")


def iso(unix_seconds):
    return datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def main():
    now = int(time.time())
    with open("market_data.json", encoding="utf-8") as f:
        published = json.load(f)
    expected = {
        (r["symbol"], r["interval"]): r
        for r in published.get("results", [])
    }
    if published.get("ok") is not True or len(expected) != 6:
        raise ValueError("Existing market_data.json does not contain all six READY groups")

    summaries = []
    for interval in INTERVALS:
        with open(f"history_{interval}.json", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError(f"Unexpected {interval} history shape")
        if {item.get("symbol") for item in payload} != SYMBOLS:
            raise ValueError(f"Unexpected {interval} symbols")
        for item in payload:
            symbol = item["symbol"]
            a = analyze(item.get("history", []), interval, as_of=now)
            expected_close = now // SECONDS[interval] * SECONDS[interval]
            if a["status"] != "READY" or a["closedCandles"] < 250:
                raise ValueError(f"Insufficient closed history for {symbol} {interval}")
            if a["lastCloseTimeUTC"] != expected_close:
                raise ValueError(f"STALE HISTORY {symbol} {interval}")

            existing = expected.get((symbol, interval))
            if not existing or existing.get("status") != "READY":
                raise ValueError(f"Existing market snapshot not READY for {symbol} {interval}")
            last_close = datetime.fromisoformat(
                existing["closeTimeUTC"].replace("Z", "+00:00")
            ).timestamp()
            if int(last_close) != expected_close:
                raise ValueError(f"History differs from published market snapshot for {symbol} {interval}")

            active_obs = [ob for ob in a["orderBlocks"] if ob["state"] != "invalidated"]
            open_fvgs = [gap for gap in a["fvg"] if gap["state"] == "open"]
            summaries.append({
                "symbol": symbol,
                "interval": interval,
                "status": "READY",
                "lastCloseTimeUTC": iso(a["lastCloseTimeUTC"]),
                "closedCandles": a["closedCandles"],
                "structure": a["structure"][-12:],
                "candidateOrderBlocks": active_obs[-12:],
                "recentInvalidatedOrderBlocks": [
                    ob for ob in a["orderBlocks"] if ob["state"] == "invalidated"
                ][-3:],
                "openFVG": open_fvgs[-12:],
                "liquidity": a["liquidity"][-12:],
                "counts": {
                    "activeCandidateOB": len(active_obs),
                    "openFVG": len(open_fvgs),
                    "structureEventsInLookback": len(a["structure"]),
                }
            })
            print(f"VERIFIED {symbol} {interval}: {a['closedCandles']} closed candles; "
                  f"{len(active_obs)} active OB candidates; {len(open_fvgs)} open FVG")

    result = {
        "schemaVersion": 1,
        "source": "Coinalyze (third-party Binance perpetual OHLCV)",
        "method": "Heuristic swing pivots, BOS/CHoCH, three-candle FVG, candidate order blocks. Not confirmed institutional orders; no order-book data.",
        "results": summaries,
    }
    # No current timestamp: an unchanged structure analysis won't create a new commit.
    with open("market_structure_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
