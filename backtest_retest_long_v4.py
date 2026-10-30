#!/usr/bin/env python3
"""V4 two-year BTC/SOL 1H archive retest backtest. Paper-only; never trades.

STRICT chronological simulation:
 * BOS/indicators/higher-timeframe filter use only CLOSED candles at that hour.
 * A BOS is merely a WATCH. Require a later CLOSED 1H retest/rejection.
 * Hypothetical fill is NEXT candle OPEN, not the signal or retest close.
 * A stop/target collision on one candle resolves pessimistically: stop first.
 * No live orders, no claimed executions, no fitted win probability.
"""
import argparse
from datetime import datetime, timezone
from bisect import bisect_right
import json
import math

from market_structure import analyze, candles_from_history, average_true_range

TF_SECONDS = {"1hour": 3600, "4hour": 14400, "daily": 86400}
PAIRS = ("BTCUSDT_PERP.A", "SOLUSDT_PERP.A")


def ema(prices, length):
    if not prices:
        return None
    k = 2 / (length + 1)
    value = prices[0]
    for c in prices[1:]:
        value = k * c + (1 - k) * value
    return value


def rsi14(prices):
    if len(prices) < 15:
        return None
    gains = [max(prices[i] - prices[i - 1], 0) for i in range(1, 15)]
    losses = [max(prices[i - 1] - prices[i], 0) for i in range(1, 15)]
    avg_up, avg_down = sum(gains)/14, sum(losses)/14
    for i in range(15, len(prices)):
        gain = max(prices[i] - prices[i - 1], 0)
        loss = max(prices[i - 1] - prices[i], 0)
        avg_up = (avg_up * 13 + gain)/14
        avg_down = (avg_down * 13 + loss)/14
    if avg_up == avg_down == 0:
        return 50.0
    return 100.0 if avg_down == 0 else 100 - 100 / (1 + avg_up / avg_down)


def indicators(bars):
    prices = [b["c"] for b in bars]
    if len(prices) < 55:
        return None
    k12, k26, k9 = 2/13, 2/27, 2/10
    f = s = prices[0]
    line_signal = 0.0
    for n, p in enumerate(prices):
        if n:
            f = k12*p + (1-k12)*f
            s = k26*p + (1-k26)*s
        line = f - s
        if n:
            line_signal = k9*line + (1-k9)*line_signal
    return {"EMA20": ema(prices, 20), "EMA50": ema(prices, 50),
            "RSI14": rsi14(prices), "hist": line-line_signal}


def bias(bars):
    ind = indicators(bars)
    if ind is None:
        return "insufficient"
    close = bars[-1]["c"]
    votes = [
        1 if close > ind["EMA20"] else -1 if close < ind["EMA20"] else 0,
        1 if close > ind["EMA50"] else -1 if close < ind["EMA50"] else 0,
        1 if ind["hist"] > 0 else -1 if ind["hist"] < 0 else 0,
        1 if ind["RSI14"] > 50 else -1 if ind["RSI14"] < 50 else 0,
    ]
    n = sum(votes)
    return "bullish" if n >= 3 else "bearish" if n <= -3 else "mixed"


def visible(bars, timestamp, secs):
    return [b for b in bars if b["t"] + secs <= timestamp]


def earliest_stop(side, bos, reaction, atr):
    cushion = 0.1 * atr
    return (max(bos["h"], reaction["h"]) + cushion if side == "bearish"
            else min(bos["l"], reaction["l"]) - cushion)


def reaction_confirmed(side, bar, prev, level):
    touched = bar["l"] <= level <= bar["h"]
    if side == "bearish":
        return (touched and bar["c"] < level and bar["c"] < bar["o"]
                and bar["c"] < prev["c"])
    return (touched and bar["c"] > level and bar["c"] > bar["o"]
            and bar["c"] > prev["c"])


def init_position(pending, entry, ts):
    stop = pending["stop"]
    risk = abs(entry - stop)
    if risk <= 0 or (pending["side"] == "bearish" and stop <= entry) or (
        pending["side"] == "bullish" and stop >= entry
    ):
        return None
    risk_pct = risk / entry
    if not .001 <= risk_pct <= .04:
        return None
    direction = -1 if pending["side"] == "bearish" else 1
    return {**pending, "entry": entry, "entryOpenUTC": ts, "risk": risk,
            "targets": [entry + direction*risk*n for n in (1,2,3)],
            "targetCount": 0, "realizedR": 0.0}


def assess_candle(pos, bar, *, max_hold_bars=24):
    """Stop FIRST if stop and any target are inside the same 1H candle.

    Returns (closed:boolean, exit_reason:str), updates pos in place.
    """
    is_short = pos["side"] == "bearish"
    hit_stop = bar["h"] >= pos["stop"] if is_short else bar["l"] <= pos["stop"]
    if hit_stop:
        pos["realizedR"] -= (3 - pos["targetCount"]) / 3
        return True, "STOP_FIRST_OR_AFTER_TP"
    while pos["targetCount"] < 3:
        level = pos["targets"][pos["targetCount"]]
        hit_tp = bar["l"] <= level if is_short else bar["h"] >= level
        if not hit_tp:
            break
        pos["targetCount"] += 1
        pos["realizedR"] += pos["targetCount"] / 3
    if pos["targetCount"] == 3:
        return True, "TP3_COMPLETE"
    pos["heldBars"] = pos.get("heldBars", 0) + 1
    if pos["heldBars"] >= max_hold_bars:
        sign = -1 if is_short else 1
        mark = sign*(bar["c"] - pos["entry"])/pos["risk"]
        pos["realizedR"] += mark*(3-pos["targetCount"])/3
        return True, "TIME_EXIT_AT_CLOSE"
    return False, ""


def replay_pair(hour_history, four_history, daily_history, *, as_of,
                retest_hours=6, fee_bps=6, slippage_bps=3):
    """Sequential 1H watch -> later retest -> next-open hypothetical trade."""
    bars = candles_from_history(hour_history, "1hour", as_of)
    bars4 = candles_from_history(four_history, "4hour", as_of)
    barsD = candles_from_history(daily_history, "daily", as_of)
    if len(bars) < 80 or len(bars4) < 55 or len(barsD) < 55:
        return {"status": "INSUFFICIENT_HISTORY", "hourCandles": len(bars),
                "fourHourCandles": len(bars4), "dailyCandles": len(barsD)}

    active = None
    pending = None
    position = None
    alerts = []
    trades = []
    no_retest = 0
    rejected_risk = 0
    close4=[b["t"]+14400 for b in bars4]
    closeD=[b["t"]+86400 for b in barsD]
    bias4_cache={}
    biasD_cache={}
    for i in range(79, len(bars)):
        bar = bars[i]
        ts = bar["t"] + 3600
        # Starting the already-confirmed trade at NEXT 1H open.
        if pending is not None:
            position = init_position(pending, bar["o"], bar["t"])
            if position is None:
                rejected_risk += 1
            pending = None
        # Only closed bars are observed for stop/target outcomes.
        if position is not None:
            closed, reason = assess_candle(position, bar)
            if closed:
                # FIXED ASSUMED roundtrip cost, illustrative, NOT exchange fee.
                cost_r = 2*(fee_bps + slippage_bps)/10000*position["entry"]/position["risk"]
                record = {key: position[key] for key in
                          ("side", "watchKnownUTC", "retestKnownUTC", "entryOpenUTC",
                           "entry", "stop", "targets", "risk", "realizedR", "targetCount")}
                record.update(exitKnownUTC=ts, exitReason=reason,
                              feeSlippageAssumptionBpsPerSide=fee_bps+slippage_bps,
                              netRIllustrative=position["realizedR"]-cost_r)
                trades.append(record)
                position = None

        if active is not None and i - active["index"] > retest_hours:
            no_retest += 1
            active = None
        # A retest after a previously confirmed BOS; NO same-bar entry.
        if active is not None and position is None and pending is None:
            if reaction_confirmed(active["side"], bar, bars[i-1], active["level"]):
                atr = average_true_range(bars, i)
                pending = {"side": active["side"], "watchKnownUTC": active["knownUTC"],
                           "retestKnownUTC": ts, "level": active["level"],
                           "stop": earliest_stop(active["side"], active["bosBar"], bar, atr)}
                active = None

        if position is not None or pending is not None:
            continue
        # Filter cheaper indicators and confirmed higher-TF bias FIRST; only
        # then calculate 250-bar structural pivots. Prevent O(N^2) archive replay.
        if i < 249:
            continue
        vol_pct = (bar["v"]/bars[i-1]["v"]-1)*100 if bars[i-1]["v"] else None
        if vol_pct is None or vol_pct < 20:
            continue
        ind = indicators(bars[:i+1])
        if ind is None:
            continue
        if not ((ind["RSI14"] < 50 and ind["hist"] < 0)
                or (ind["RSI14"] > 50 and ind["hist"] > 0)):
            continue

        n4=bisect_right(close4,ts)
        nD=bisect_right(closeD,ts)
        if n4<55 or nD<55:
            continue
        if n4 not in bias4_cache:
            bias4_cache[n4]=bias(bars4[:n4])
        if nD not in biasD_cache:
            biasD_cache[nD]=bias(barsD[:nD])
        tf_bias=[bias4_cache[n4],biasD_cache[nD]]
        if tf_bias[0] != tf_bias[1] or tf_bias[0] not in ("bullish","bearish"):
            continue

        # Match the live market_structure.py 250-bar continuity horizon:
        # last bar is CLOSED before analysis; no price after ts can enter.
        window = bars[i-249:i+1]
        current = analyze(window, "1hour", as_of=ts)
        new_bos = [e for e in current["structure"]
                   if e["event"] == "BOS" and e["at"] + 3600 == ts]
        if not new_bos:
            continue
        for bos in new_bos:
            side = bos["direction"]
            if tf_bias != [side, side]:
                continue
            if side == "bearish" and not (ind["RSI14"] < 50 and ind["hist"] < 0):
                continue
            if side == "bullish" and not (ind["RSI14"] > 50 and ind["hist"] > 0):
                continue
            active = {"index": i, "side": side, "knownUTC": ts,
                      "level": bos["brokenLevel"], "bosBar": bar}
            alerts.append({"knownUTC": ts, "side": side, "BOSLevel": bos["brokenLevel"],
                           "hourClose": bar["c"], "RSI14": ind["RSI14"],
                           "hist": ind["hist"], "volumeChangePct": vol_pct,
                           "higherTimeframes": tf_bias})
            break

    # Unresolved positions are NOT assigned optimistic exits.
    complete = len(trades)
    wins = sum(t["netRIllustrative"] > 0 for t in trades)
    mean_r = sum(t["netRIllustrative"] for t in trades)/complete if complete else None
    return {
        "status": "PAPER_BACKTEST_NOT_LIVE",
        "hourCandles": len(bars), "fourHourCandles": len(bars4),
        "dailyCandles": len(barsD), "alertsCount": len(alerts),
        "alerts": alerts, "retestExpiredCount": no_retest,
        "hypotheticalClosedTrades": complete, "hypotheticalWins": wins,
        "hypotheticalWinRate": wins/complete if complete else None,
        "netRAverageIllustrative": mean_r,
        "riskRuleRejected": rejected_risk,
        "unresolvedPositionExcluded": position is not None,
        "pendingEntryExcluded": pending is not None,
        "trades": trades,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hour", required=True)
    p.add_argument("--four", required=True)
    p.add_argument("--daily", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--as-of", type=int, default=None)
    p.add_argument("--retest-hours", type=int, default=6)
    p.add_argument("--split-utc",default="2026-04-01T00:00:00+00:00")
    args = p.parse_args()
    as_of = args.as_of or int(datetime.now(timezone.utc).timestamp())
    data = {}
    for tf, file in (("1hour", args.hour), ("4hour", args.four), ("daily", args.daily)):
        with open(file, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, list) or {z.get("symbol") for z in d} != set(PAIRS):
            raise ValueError(f"Unexpected {tf} history")
        data[tf] = {x["symbol"]: x["history"] for x in d}
    result = {
        "mode": "PAPER_ONLY_OFFLINE_EXPERIMENT",
        "asOfUTC": datetime.fromtimestamp(as_of,timezone.utc).isoformat(),
        "assumptions": {
            "entry": "NEXT 1H bar open only AFTER separate retest close",
            "stop": "worse BOS/retest wick with 0.1 ATR cushion",
            "TP": "1R / 2R / 3R, one third at each",
            "sameCandle": "stop first if stop and TP reached within same candle",
            "holdingLimit": "24 1H bars; remaining size marked at time-exit close",
            "entryRisk": "0.1–4% of entry, otherwise hypothetical setup rejected",
            "cost": "illustrative 6 bps fee + 3 bps slippage per side",
            "funding": "not modeled",
            "sample": "Binance official USD-M 1H monthly ZIP archives, 4H+1D derived from 1H",
            "limitation": "not exchange execution, no verified profitability",
        },
        "results": {symbol: replay_pair(data["1hour"][symbol], data["4hour"][symbol],
                                        data["daily"][symbol], as_of=as_of,
                                        retest_hours=args.retest_hours)
                    for symbol in PAIRS},
    }
    split=int(datetime.fromisoformat(args.split_utc.replace("Z","+00:00")).timestamp())
    def section(report, low, high):
        events=[e for e in report.get("alerts",[])
                if low<=e["knownUTC"]<high]
        trades=[t for t in report.get("trades",[])
                if low<=t["entryOpenUTC"]<high]
        n=len(trades)
        return {"alerts":len(events),"trades":n,
                "winningHypotheticalTrades":sum(t["netRIllustrative"]>0 for t in trades),
                "winFractionIllustrative":(sum(t["netRIllustrative"]>0 for t in trades)/n
                                         if n else None),
                "meanNetRHypothetical":(sum(t["netRIllustrative"] for t in trades)/n
                                       if n else None)}
    result["fixedSplitUTC"]=args.split_utc
    result["splitNote"]="Historical in-sample before split, HOLDOUT after; no parameter optimisation performed"
    result["segments"]={symbol:{"training":section(report,-float("inf"),split),
                                "holdout":section(report,split,float("inf"))}
                        for symbol,report in result["results"].items()}
    with open(args.output,"w",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,indent=2);f.write("\n")
    for symbol,r in result["results"].items():
        print("  SPLIT",symbol,result["segments"][symbol])
        print(symbol, "status",r["status"],"1Hbars",r.get("hourCandles"),
              "4Hbars",r.get("fourHourCandles"),"DailyBars",r.get("dailyCandles"),
              "alerts",r.get("alertsCount"),"expiredWatches",r.get("retestExpiredCount"),
              "closedTrades",r.get("hypotheticalClosedTrades"),
              "meanNetR",r.get("netRAverageIllustrative"),
              "unresolvedExcluded",r.get("unresolvedPositionExcluded"))
        for event in r.get("alerts",[]):
            when=datetime.fromtimestamp(event["knownUTC"],timezone.utc).isoformat()
            print("  ALERT",when,event["side"],"level",event["BOSLevel"],
                  "close",event["hourClose"],"RSI",round(event["RSI14"],2))
        for trade in r.get("trades",[]):
            known=datetime.fromtimestamp(trade["watchKnownUTC"],timezone.utc).isoformat()
            opened=datetime.fromtimestamp(trade["entryOpenUTC"],timezone.utc).isoformat()
            print("  PAPER TRADE",known,"entry",opened,trade["entry"],
                  "stop",round(trade["stop"],4),"TPs",
                  [round(n,4) for n in trade["targets"]],
                  "exit",trade["exitReason"],"TPcount",trade["targetCount"],
                  "assumedNetR",round(trade["netRIllustrative"],4))
if __name__ == "__main__":
    main()
