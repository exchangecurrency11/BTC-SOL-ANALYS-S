#!/usr/bin/env python3
"""Experimental 1H BTC/SOL early-watch detector. NO trade execution.

This module never emits executable orders. It runs ONLY on fully closed OHLCV.
Order blocks are heuristic zones from market_structure.py, not verified orders.
Signal labels describe watch candidates, not statistically validated entries.
"""
from market_structure import (
    analyze, candles_from_history, average_true_range, SECONDS,
)

MIN_BARS = 45


def macd_histogram(closes):
    """EMA(12)-EMA(26) minus signal EMA(9), computed on closed history."""
    if len(closes) < 35:
        return None, None

    def ema(values, length):
        alpha = 2 / (length + 1)
        output = [values[0]]
        for value in values[1:]:
            output.append(alpha * value + (1 - alpha) * output[-1])
        return output

    fast = ema(closes, 12)
    slow = ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    signal = ema(macd, 9)
    histogram = [a - b for a, b in zip(macd, signal)]
    return histogram[-1], histogram[-2]


def _touches(bar, wick):
    return bar["l"] <= wick["high"] and bar["h"] >= wick["low"]


def evaluate(history, *, as_of, interval="1hour"):
    """Evaluate the latest closed bar, with no access to future observations.

    Historical timestamps ending in 'At' may refer to bar OPEN in v1 data.
    Every emitted event uses closeTimeUTC (Unix seconds) as its earliest
    knowable time, even if the legacy source has an earlier 'at' timestamp.
    """
    if interval != "1hour":
        raise ValueError("Only 1hour early-watch experiments are supported")
    if as_of is None:
        raise ValueError("Explicit as_of timestamp is required")

    bars = candles_from_history(history, interval, as_of=as_of)
    base = {"status": "INSUFFICIENT_HISTORY", "closeTimeUTC": None,
            "events": [], "watch": "BEKLE", "note": "Experimental; not a trade signal"}
    if len(bars) < MIN_BARS:
        return base

    last, prev = bars[-1], bars[-2]
    close_time = last["t"] + SECONDS[interval]
    result = analyze(history, interval, as_of=close_time)
    if result["lastCloseTimeUTC"] != close_time:
        raise ValueError("Source and analysis close time mismatch")

    hist, prev_hist = macd_histogram([b["c"] for b in bars])
    prev20 = bars[-21:-1]
    average_volume = sum(b["v"] for b in prev20) / len(prev20)
    vol_ratio = last["v"] / average_volume if average_volume else None
    atr = average_true_range(bars, len(bars) - 1)
    events = []

    def record(kind, side, **extras):
        events.append({"kind": kind, "side": side, "knownAt": close_time, **extras})

    # A CHoCH is a change-of-direction warning, never an instant market order.
    for item in result["structure"]:
        if item["at"] == last["t"] and item["event"] == "CHoCH":
            record("DIRECTION_CHANGE_WARNING", item["direction"],
                   brokenLevel=item["brokenLevel"])

    # An OB invalidation is a reason to CANCEL that side's previous watch.
    for zone in result["orderBlocks"]:
        if zone["state"] == "invalidated" and zone["invalidatedAt"] == last["t"]:
            record("OB_INVALIDATED", zone["side"],
                   zoneLow=zone["wick"]["low"], zoneHigh=zone["wick"]["high"])

    # Fresh touch AFTER the break was confirmed, followed by a closed-bar
    # rejection away from the OB body. A wick-only touch never suffices.
    for zone in result["orderBlocks"]:
        if zone["state"] == "invalidated":
            continue
        if zone["confirmedAt"] > last["t"]:
            continue
        if not _touches(last, zone["wick"]) or _touches(prev, zone["wick"]):
            continue
        direction = zone["side"]
        if direction == "bullish":
            reacted = (last["c"] > last["o"] and last["c"] > prev["c"]
                       and last["c"] >= zone["body"]["high"])
        else:
            reacted = (last["c"] < last["o"] and last["c"] < prev["c"]
                       and last["c"] <= zone["body"]["low"])
        if reacted:
            record("OB_RETEST_RESPONSE", direction,
                   zoneLow=zone["wick"]["low"], zoneHigh=zone["wick"]["high"])

    # Experimental 1H momentum breakout watch: newly confirmed BOS, rising
    # volume, and matching MACD histogram. Retest is NOT assumed.
    for item in result["structure"]:
        if item["at"] != last["t"] or item["event"] != "BOS":
            continue
        side = item["direction"]
        bullish = side == "bullish"
        hist_ok = (hist is not None and prev_hist is not None and
                   (hist > 0 and hist > prev_hist if bullish
                    else hist < 0 and hist < prev_hist))
        volume_ok = vol_ratio is not None and vol_ratio >= 1.2
        if hist_ok and volume_ok:
            record("BREAKOUT_WATCH", side, brokenLevel=item["brokenLevel"],
                   volumeRatio=round(vol_ratio, 3))

    # This is a WARNING priority, not an entry, and not a backtested edge.
    directions = [e["side"] for e in events if e["kind"] in
                  ("DIRECTION_CHANGE_WARNING", "OB_RETEST_RESPONSE", "BREAKOUT_WATCH")]
    if "bearish" in directions and "bullish" in directions:
        watch = "CONFLICT"
    elif "bearish" in directions:
        watch = "WATCH_SHORT"
    elif "bullish" in directions:
        watch = "WATCH_LONG"
    else:
        watch = "BEKLE"

    return {"status": "READY", "closeTimeUTC": close_time,
            "lastClose": last["c"], "ATR14": round(atr, 8) if atr is not None else None,
            "macdHistogram": round(hist, 8) if hist is not None else None,
            "volumeRatio": round(vol_ratio, 3) if vol_ratio is not None else None,
            "events": events, "watch": watch,
            "note": "Paper test only; stop, TP and fills unvalidated; no orders"}


def replay(history, *, as_of, lookback=168):
    """Time-correct snapshot replay. No fitted parameters or P&L claims."""
    bars = candles_from_history(history, "1hour", as_of=as_of)
    if len(bars) < MIN_BARS:
        return []
    start = max(MIN_BARS - 1, len(bars) - lookback)
    observations = []
    active_watch = None
    for idx in range(start, len(bars)):
        last_close = bars[idx]["t"] + SECONDS["1hour"]
        snapshot = evaluate(bars[:idx + 1], as_of=last_close)
        events = snapshot["events"]
        # A CHoCH in the opposite direction or an OB invalidation cancels
        # an existing watch; it never automatically opens a reverse trade.
        for event in events:
            cancelled = ((event["kind"] == "OB_INVALIDATED" and
                          active_watch == event["side"]) or
                         (event["kind"] == "DIRECTION_CHANGE_WARNING" and
                          active_watch is not None and event["side"] != active_watch))
            if cancelled:
                observations.append({"knownAt": last_close, "kind": "CANCEL_WATCH",
                                     "side": active_watch, "reason": event["kind"]})
                active_watch = None
        if snapshot["watch"] in ("WATCH_LONG", "WATCH_SHORT"):
            next_watch = "bullish" if snapshot["watch"] == "WATCH_LONG" else "bearish"
            if active_watch != next_watch:
                active_watch = next_watch
                observations.append({"knownAt": last_close,
                                     "kind": snapshot["watch"],
                                     "side": active_watch,
                                     "triggerEvents": [e["kind"] for e in events],
                                     "close": snapshot["lastClose"]})
    return observations
