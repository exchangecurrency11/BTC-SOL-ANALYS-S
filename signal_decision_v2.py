#!/usr/bin/env python3
"""Experimental 1H decision-card engine. Closed OHLCV only; never trades.

Separates HIGHER TIMEFRAME DIRECTION, EARLY TECHNICAL ALERT and UNCONFIRMED
TRADE ENTRY. Reads point-in-time GitHub snapshots; never looks ahead.
Coinalyze OB, BOS, CHoCH are heuristic, not verified institutional orders.
"""
from datetime import datetime, timezone, timedelta

HOUR = 3600
TF_SECONDS = {"1hour": 3600, "4hour": 14400, "daily": 86400}


def epoch(iso):
    if not isinstance(iso, str):
        raise ValueError("UTC ISO timestamp required")
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.utcoffset() != timedelta(0):
        raise ValueError("UTC timestamp required")
    return int(t.timestamp())


def _groups(payload):
    out = {}
    for row in payload.get("results", []):
        key = (row.get("symbol"), row.get("interval"))
        if key in out:
            raise ValueError("Duplicate symbol and interval")
        out[key] = row
    return out


def _bias(candle, ind):
    """Four transparent votes; no curve-fit, score is NOT win probability."""
    c = candle["close"]
    votes = []
    for ema in ("EMA20", "EMA50"):
        threshold = ind[ema]
        votes.append(1 if c > threshold else (-1 if c < threshold else 0))
    hist = ind["MACDHistogram"]
    votes.append(1 if hist > 0 else (-1 if hist < 0 else 0))
    rsi = ind["RSI14"]
    votes.append(1 if rsi > 50 else (-1 if rsi < 50 else 0))
    score = sum(votes)
    return "bullish" if score >= 3 else ("bearish" if score <= -3 else "mixed"), score


def _market_direction(four, daily):
    a, score4 = _bias(four["candle"], four["indicators"])
    b, scoreD = _bias(daily["candle"], daily["indicators"])
    if a == b == "bearish":
        direction = "SHORT_PRIORITY"
    elif a == b == "bullish":
        direction = "LONG_PRIORITY"
    elif a == "bearish":
        direction = "SHORT_LEAN_4H"
    elif a == "bullish":
        direction = "LONG_LEAN_4H"
    else:
        direction = "MIXED"
    return {"label": direction, "fourHour": a, "daily": b,
            "votes4H": score4, "votesDaily": scoreD}


def _rows_from_snapshots(symbol, market, structure):
    mg = _groups(market)
    sg = _groups(structure)
    result = {}
    for tf, seconds in TF_SECONDS.items():
        key = (symbol, tf)
        m, s = mg.get(key), sg.get(key)
        if not m or not s:
            raise ValueError("Missing market/structure group " + str(key))
        if m["status"] != "READY" or s["status"] != "READY":
            raise ValueError("Market/structure not READY")
        if epoch(m["closeTimeUTC"]) != epoch(s["lastCloseTimeUTC"]):
            raise ValueError("Market and structure timestamps disagree")
        result[tf] = (m, s)
    target = epoch(result["1hour"][0]["closeTimeUTC"])
    for tf, seconds in (("4hour", 14400), ("daily", 86400)):
        lag = target - epoch(result[tf][0]["closeTimeUTC"])
        if not 0 <= lag < seconds:
            raise ValueError("Stale or future higher-timeframe candle: " + tf)
    if "checkedAtUTC" in market and epoch(market["checkedAtUTC"]) < target:
        raise ValueError("Snapshot checked before selected candle closed")
    return result, target


def _ob_id(z):
    return (z.get("side"), z.get("originAt"), z.get("confirmedAt"),
            z["wick"]["low"], z["wick"]["high"])


def _ob_response(current, previous, zone):
    # A complete hourly PREVIOUS snapshot is necessary to prove a NEW retest.
    if not previous:
        return False
    prev_market, prev_zone = previous
    if prev_zone is None or prev_zone["state"] == "invalidated":
        return False
    if int(zone["confirmedAt"]) > epoch(prev_market["closeTimeUTC"]):
        return False
    if zone["retests"] <= prev_zone["retests"]:
        return False
    bar = current["candle"]
    prev_close = prev_market["candle"]["close"]
    lo, hi = zone["wick"]["low"], zone["wick"]["high"]
    if bar["low"] > hi or bar["high"] < lo:
        return False
    if zone["side"] == "bullish":
        return (bar["close"] > bar["open"] and bar["close"] > prev_close
                and bar["close"] >= zone["body"]["high"])
    return (bar["close"] < bar["open"] and bar["close"] < prev_close
            and bar["close"] <= zone["body"]["low"])


def decide(symbol, market, structure, *, previous_market=None,
           previous_structure=None):
    """One decision snapshot. No prices or events from later candle closes.

    Previous snapshots are required as a PAIR and must be exactly one 1H bar
    earlier; otherwise the engine refuses to infer a 'new' OB retest.
    """
    groups, target = _rows_from_snapshots(symbol, market, structure)
    hour, hour_s = groups["1hour"]
    direction = _market_direction(groups["4hour"][0], groups["daily"][0])
    prev_m = prev_s = None
    if (previous_market is None) != (previous_structure is None):
        raise ValueError("Previous market and structure required together")
    if previous_market is not None:
        prev_g, prev_time = _rows_from_snapshots(symbol, previous_market,
                                                previous_structure)
        if target - prev_time != HOUR:
            raise ValueError("Previous snapshots must precede by exactly one hour")
        prev_m, prev_s = prev_g["1hour"]

    ind = hour["indicators"]
    bar = hour["candle"]
    events = []
    for item in hour_s.get("structure", []):
        # Legacy 'at' is the OPEN of the breaking candle, not signal time.
        if int(item["at"]) + HOUR != target:
            continue
        side = item["direction"]
        if item["event"] == "CHoCH":
            events.append({"kind": "DIRECTION_CHANGE_WATCH", "side": side,
                           "level": item["brokenLevel"], "knownAtUTC": hour["closeTimeUTC"]})
        elif item["event"] == "BOS":
            vol_pct = bar["volumeChangePct"]
            hist = ind["MACDHistogram"]
            rsi = ind["RSI14"]
            aligned = ((hist < 0 and rsi < 50) if side == "bearish"
                       else (hist > 0 and rsi > 50))
            volume_ok = vol_pct >= 20
            events.append({"kind": "BOS_MOMENTUM_WATCH" if aligned and volume_ok
                           else "BOS_NEEDS_CONFIRMATION",
                           "side": side, "level": item["brokenLevel"],
                           "macdAligned": aligned, "volumeStrengthened": volume_ok,
                           "knownAtUTC": hour["closeTimeUTC"]})

    # OB cancellations become observable at the invalidating candle CLOSE.
    for z in hour_s.get("recentInvalidatedOrderBlocks", []):
        if z.get("invalidatedAt") is not None and int(z["invalidatedAt"]) + HOUR == target:
            events.append({"kind": "OB_INVALIDATED", "side": z["side"],
                           "zone": z["wick"], "knownAtUTC": hour["closeTimeUTC"]})

    if prev_s is not None:
        historical_obs = {_ob_id(z): z for z in prev_s.get("candidateOrderBlocks", [])}
        for z in hour_s.get("candidateOrderBlocks", []):
            if z["state"] == "invalidated":
                continue
            if _ob_response(hour, (prev_m, historical_obs.get(_ob_id(z))), z):
                events.append({"kind": "OB_RETEST_RESPONSE_WATCH", "side": z["side"],
                               "zone": z["wick"], "knownAtUTC": hour["closeTimeUTC"]})

    candidate_kinds = {"DIRECTION_CHANGE_WATCH", "BOS_MOMENTUM_WATCH",
                       "OB_RETEST_RESPONSE_WATCH"}
    active = {e["side"] for e in events if e["kind"] in candidate_kinds}
    if len(active) > 1:
        early = "CONFLICTING_WARNINGS"
    elif active == {"bearish"}:
        early = "EARLY_SHORT_WARNING"
    elif active == {"bullish"}:
        early = "EARLY_LONG_WARNING"
    elif any(e["kind"] == "OB_INVALIDATED" for e in events):
        early = "SCENARIO_CANCELLED"
    elif any(e["kind"] == "BOS_NEEDS_CONFIRMATION" for e in events):
        early = "BOS_UNCONFIRMED"
    else:
        early = "NO_NEW_EARLY_TRIGGER"

    opposed = ((early == "EARLY_LONG_WARNING" and direction["label"].startswith("SHORT"))
               or (early == "EARLY_SHORT_WARNING" and direction["label"].startswith("LONG")))
    risks = []
    if ind["RSI14"] <= 30:
        risks.append("RSI <= 30: oversold; short chasing may be risky")
    if ind["RSI14"] >= 70:
        risks.append("RSI >= 70: overbought; long chasing may be risky")
    if opposed:
        risks.append("1H watch conflicts with 4H/1D directional bias")

    return {
        "symbol": symbol,
        "closeTimeUTC": hour["closeTimeUTC"],
        "lastClosed1H": bar["close"],
        "marketDirection": direction,
        "earlyAlert": early,
        "events": events,
        "conflictsHigherTimeframe": opposed,
        "hourlyIndicators": {
            "RSI14": ind["RSI14"],
            "MACDHistogram": ind["MACDHistogram"],
            "volumeChangePct": bar["volumeChangePct"],
        },
        "tradeEntry": {
            "status": "NOT_CONFIRMED",
            "entry": None, "stop": None, "TP1": None, "TP2": None, "TP3": None,
            "riskReward": None,
            "missing": ["predefined entry/retest/fill and stop/TP criteria",
                        "out-of-sample results and costs (fees/slippage/funding)"],
        },
        "riskNotes": risks,
        "mode": "EXPERIMENTAL_PAPER_WATCH_NO_ORDERS",
    }


def decide_all(market, structure, *, previous_market=None, previous_structure=None):
    return [decide(symbol, market, structure, previous_market=previous_market,
                   previous_structure=previous_structure)
            for symbol in ("BTCUSDT_PERP.A", "SOLUSDT_PERP.A")]
