#!/usr/bin/env python3
"""BTC/SOL perpetual market structure detector (stdlib only).

Input is a Coinalyze /v1/ohlcv-history response (list of symbol/history objects).
Timestamps 't' are treated as UTC bar OPEN times; only finished candles are used.
These are heuristic chart-structure zones, not evidence of institutional orders.
"""
import argparse
import json
import math
import time

SECONDS = {"1hour": 3600, "4hour": 14400, "daily": 86400}
ALLOWED = {"BTCUSDT_PERP.A", "SOLUSDT_PERP.A"}


def candles_from_history(records, interval, as_of=None):
    if interval not in SECONDS:
        raise ValueError("Unsupported timeframe")
    if as_of is None:
        as_of = int(time.time())
    seconds = SECONDS[interval]
    rows = []
    for p in records:
        try:
            t = int(p["t"])
            o, h, l, c, v = (float(p[k]) for k in ("o", "h", "l", "c", "v"))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Malformed OHLCV record") from exc
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            raise ValueError("Non-finite OHLCV value")
        if l <= 0 or h < max(o, c) or l > min(o, c) or v < 0:
            raise ValueError("Invalid candle ranges or volume")
        if t % seconds:
            raise ValueError("Misaligned bar open timestamp")
        if t + seconds <= as_of:
            rows.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v})
    rows.sort(key=lambda p: p["t"])
    if len(set(p["t"] for p in rows)) != len(rows):
        raise ValueError("Duplicate OHLCV timestamps")
    return rows


def average_true_range(bars, end, count=14):
    if end < count:
        return None
    vals = []
    for i in range(end - count + 1, end + 1):
        prev_close = bars[i - 1]["c"]
        b = bars[i]
        vals.append(max(b["h"] - b["l"], abs(b["h"] - prev_close), abs(b["l"] - prev_close)))
    return sum(vals) / len(vals)


def _zone_status(zone, bars, start, interval_seconds):
    touches = 0
    active_touch = False
    invalidated_at = None
    for bar in bars[start:]:
        if (zone["side"] == "bullish" and bar["c"] < zone["wick"]["low"]) or (
            zone["side"] == "bearish" and bar["c"] > zone["wick"]["high"]
        ):
            invalidated_at = bar["t"]
            break
        inside = bar["l"] <= zone["wick"]["high"] and bar["h"] >= zone["wick"]["low"]
        if inside and not active_touch:
            touches += 1
        active_touch = inside
    return {"state": "invalidated" if invalidated_at else ("retested" if touches else "fresh"),
            "retests": touches, "invalidatedAt": invalidated_at,
            "invalidationConfirmedAt": invalidated_at + interval_seconds if invalidated_at is not None else None}


def analyze(history, interval, as_of=None, pivot_span=3):
    if pivot_span < 2 or pivot_span > 10:
        raise ValueError("pivot_span must be from 2 to 10")
    bars = candles_from_history(history, interval, as_of)
    output = {"interval": interval, "closedCandles": len(bars),
              "lastCloseTimeUTC": bars[-1]["t"] + SECONDS[interval] if bars else None,
              "fvg": [], "structure": [], "orderBlocks": [], "liquidity": []}
    if len(bars) < 45:
        output["status"] = "INSUFFICIENT_HISTORY"
        return output
    output["status"] = "READY"
    highs, lows = [], []
    used_swing = set()
    bias = None

    for i, b in enumerate(bars):
        atr = average_true_range(bars, i)

        # Three-candle imbalances. Gap is between candle i-2 and candle i.
        if i >= 2 and atr:
            left = bars[i - 2]
            if b["l"] > left["h"] and b["l"] - left["h"] >= .12 * atr:
                zone = {"side": "bullish", "formedAt": b["t"],
                        "confirmedAt": b["t"] + SECONDS[interval],
                        "low": left["h"], "high": b["l"]}
                output["fvg"].append(zone)
            if b["h"] < left["l"] and left["l"] - b["h"] >= .12 * atr:
                zone = {"side": "bearish", "formedAt": b["t"],
                        "confirmedAt": b["t"] + SECONDS[interval],
                        "low": b["h"], "high": left["l"]}
                output["fvg"].append(zone)

        # A pivot becomes knowable only after pivot_span following candles close.
        center = i - pivot_span
        if center >= pivot_span:
            window = bars[center - pivot_span:center + pivot_span + 1]
            p = bars[center]
            if p["h"] == max(x["h"] for x in window) and sum(x["h"] == p["h"] for x in window) == 1:
                highs.append({"price": p["h"], "t": p["t"], "confirmedAt": b["t"] + SECONDS[interval]})
            if p["l"] == min(x["l"] for x in window) and sum(x["l"] == p["l"] for x in window) == 1:
                lows.append({"price": p["l"], "t": p["t"], "confirmedAt": b["t"] + SECONDS[interval]})

        if not atr or i == 0:
            continue
        for direction, swings in (("bullish", highs), ("bearish", lows)):
            if not swings:
                continue
            p = swings[-1]
            key = (direction, p["t"])
            if key in used_swing:
                continue
            crossing = (bars[i - 1]["c"] <= p["price"] < b["c"]) if direction == "bullish" else (
                bars[i - 1]["c"] >= p["price"] > b["c"]
            )
            if not crossing:
                continue
            used_swing.add(key)
            old_bias = bias
            event = "CHoCH" if old_bias and old_bias != direction else "BOS"
            bias = direction
            structure = {"event": event, "direction": direction, "at": b["t"],
                         "confirmedAt": b["t"] + SECONDS[interval],
                         "brokenSwingAt": p["t"], "brokenLevel": p["price"]}
            output["structure"].append(structure)

            # Require a meaningful break and directional move, otherwise omit OB.
            body = abs(b["c"] - b["o"])
            impulse = abs(b["c"] - bars[max(0, i - 3)]["o"])
            if max(body, impulse / 2) < .65 * atr:
                continue
            opposite = [
                j for j in range(max(0, i - 8), i)
                if (bars[j]["c"] < bars[j]["o"] if direction == "bullish"
                    else bars[j]["c"] > bars[j]["o"])
            ]
            if not opposite:
                continue
            j = opposite[-1]
            ob = bars[j]
            avg_vol = sum(x["v"] for x in bars[max(0, i - 20):i]) / min(20, i)
            ratio = b["v"] / avg_vol if avg_vol > 0 else None
            associated = [gap for gap in output["fvg"]
                          if ob["t"] < gap["formedAt"] <= b["t"] and gap["side"] == direction]
            zone = {"side": direction, "event": event, "originAt": ob["t"],
                    "confirmedAt": b["t"] + SECONDS[interval], "breakAt": b["t"],
                    "breakConfirmedAt": b["t"] + SECONDS[interval],
                    "brokenLevel": p["price"],
                    "body": {"low": min(ob["o"], ob["c"]), "high": max(ob["o"], ob["c"])},
                    "wick": {"low": ob["l"], "high": ob["h"]},
                    "volumeRatio": round(ratio, 3) if ratio is not None else None,
                    "fvgConfluence": bool(associated),
                    "note": "Candidate OHLCV order block; not verified institutional orders"}
            zone.update(_zone_status(zone, bars, i + 1, SECONDS[interval]))
            output["orderBlocks"].append(zone)

    # Equal highs/lows: potential resting liquidity, NOT real order-book orders.
    last_atr = average_true_range(bars, len(bars) - 1) or 0
    for label, pivots in (("equal_highs", highs), ("equal_lows", lows)):
        for j in range(1, len(pivots)):
            a, b = pivots[j - 1], pivots[j]
            if b["t"] - a["t"] > SECONDS[interval] * 60:
                continue
            tolerance = max(.0015 * b["price"], .20 * last_atr)
            if abs(a["price"] - b["price"]) <= tolerance:
                output["liquidity"].append({"kind": label, "level": round((a["price"] + b["price"]) / 2, 8),
                                             "firstPivotAt": a["t"], "secondPivotAt": b["t"],
                                             "knownAt": max(a["confirmedAt"], b["confirmedAt"]),
                                             "note": "Potential chart liquidity; not live order-book data"})

    # Full FVG fill is checked only after the gap has formed.
    for gap in output["fvg"]:
        gap["state"] = "open"
        gap["fullyFilledAt"] = None
        gap["fullyFilledConfirmedAt"] = None
        for bar in bars:
            if bar["t"] <= gap["formedAt"]:
                continue
            filled = bar["l"] <= gap["low"] if gap["side"] == "bullish" else bar["h"] >= gap["high"]
            if filled:
                gap["state"] = "filled"
                gap["fullyFilledAt"] = bar["t"]
                gap["fullyFilledConfirmedAt"] = bar["t"] + SECONDS[interval]
                break
    output["structure"] = output["structure"][-20:]
    output["orderBlocks"] = output["orderBlocks"][-24:]
    output["fvg"] = output["fvg"][-30:]
    output["liquidity"] = output["liquidity"][-20:]
    return output


def main():
    cli = argparse.ArgumentParser(description="Detect BTC/SOL OB, BOS, CHoCH, FVG and chart liquidity")
    cli.add_argument("--input", required=True, help="Local Coinalyze OHLCV JSON response")
    cli.add_argument("--interval", choices=list(SECONDS), required=True)
    cli.add_argument("--as-of", type=int, default=None, help="UTC unix seconds; defaults to now")
    cli.add_argument("--output", help="Output JSON path; defaults to stdout")
    args = cli.parse_args()
    with open(args.input, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Expected Coinalyze list [{symbol, history}, ...]")
    results = []
    for item in data:
        if item.get("symbol") not in ALLOWED:
            raise ValueError("Unexpected symbol")
        result = analyze(item.get("history", []), args.interval, args.as_of)
        result["symbol"] = item["symbol"]
        results.append(result)
    if len({r["symbol"] for r in results}) != len(results):
        raise ValueError("Duplicate symbol")
    payload = {"engine": "market_structure_v1", "source": "Coinalyze (third-party Binance perpetual)",
               "results": results}
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
