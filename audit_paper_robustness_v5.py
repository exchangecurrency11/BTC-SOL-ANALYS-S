#!/usr/bin/env python3
"""Audit two-year USD-M paper strategy without re-optimising signal rules.

Reads long_v4_result.json (archive replay). Reprices EXISTING hypothetical
trades under multiple illustrative cost assumptions; no new trading, no orders.
Never interpret an R total as cash P&L or leverage-adjusted real returns.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean

# bps PER SIDE = assumed execution fee + slip, neither verified live charge.
COST_SCENARIOS = {
    "low_3bps_per_side": 3,
    "original_9bps_per_side": 9,
    "moderate_12bps_per_side": 12,
    "stress_25bps_per_side": 25,
}
HOLDOUT_MIN_TRADES = 30


def modeled_net_r(trade, cost_bps_per_side):
    """Notional-cost approximation in units of entry-stop risk R."""
    entry = float(trade["entry"])
    risk = float(trade["risk"])
    gross_r = float(trade["realizedR"])
    if not (math.isfinite(entry) and math.isfinite(risk) and
            math.isfinite(gross_r) and entry > 0 and risk > 0):
        raise ValueError("Invalid hypothetical trade geometry")
    if cost_bps_per_side < 0 or not math.isfinite(cost_bps_per_side):
        raise ValueError("Invalid execution cost assumption")
    return gross_r - 2 * cost_bps_per_side / 10000 * entry / risk


def max_loss_streak(values):
    biggest = current = 0
    for value in values:
        current = current + 1 if value <= 0 else 0
        biggest = max(biggest, current)
    return biggest


def sum_r_drawdown(values):
    """Largest peak-to-trough fall in sequential summed R, NOT account equity."""
    peak = 0.0
    capital = 0.0
    worst = 0.0
    for x in values:
        capital += x
        peak = max(peak, capital)
        worst = max(worst, peak-capital)
    return worst


def summarize(trades, cost_bps):
    ordered = sorted(trades, key=lambda t: (t["entryOpenUTC"], t["watchKnownUTC"]))
    rs = [modeled_net_r(t, cost_bps) for t in ordered]
    n = len(rs)
    if not n:
        return {
            "trades": 0, "wins": 0, "winFraction": None,
            "meanNetR": None, "sumNetRUnits": None,
            "medianNetR": None, "worstTradeR": None,
            "maxConsecutiveNonwinningTrades": 0,
            "maxDrawdownInSequentialRUnits": None,
            "profitFactorR": None,
        }
    sorted_rs = sorted(rs)
    median = ((sorted_rs[n//2-1]+sorted_rs[n//2])/2 if n%2==0 else sorted_rs[n//2])
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    profit_factor = (sum(wins)/-sum(losses) if losses else None)
    return {
        "trades": n,
        "wins": len(wins),
        "winFraction": len(wins)/n,
        "meanNetR": mean(rs),
        "sumNetRUnits": sum(rs),
        "medianNetR": median,
        "worstTradeR": min(rs),
        "maxConsecutiveNonwinningTrades": max_loss_streak(rs),
        "maxDrawdownInSequentialRUnits": sum_r_drawdown(rs),
        "profitFactorR": profit_factor,
    }


def audit(report):
    if report.get("mode") != "PAPER_ONLY_OFFLINE_EXPERIMENT":
        raise ValueError("Unexpected source mode: refuse external or live orders")
    if "2026-04-01" not in report.get("fixedSplitUTC",""):
        raise ValueError("Unrecognised holdout cutoff; do not change retrospectively")
    cutoff = int(datetime.fromisoformat(report["fixedSplitUTC"].replace("Z","+00:00")).timestamp())
    outputs = {}
    for symbol, group in report["results"].items():
        if group.get("status")!="PAPER_BACKTEST_NOT_LIVE":
            outputs[symbol]={"status":"UNAVAILABLE", "reason":group.get("status")}
            continue
        trades=group["trades"]
        if len(trades)!=group["hypotheticalClosedTrades"]:
            raise ValueError("Closed trade count inconsistent")
        cutoff_trades={
            "training": [t for t in trades if t["entryOpenUTC"]<cutoff],
            "holdout": [t for t in trades if t["entryOpenUTC"]>=cutoff],
        }
        breakdown={}
        for period, subset in cutoff_trades.items():
            breakdown[period]={
                scenario: summarize(subset,bps)
                for scenario,bps in COST_SCENARIOS.items()
            }
        side_breakdown={}
        for side in ("bullish","bearish"):
            subset=[t for t in trades if t["side"]==side]
            side_breakdown[side]=summarize(subset,COST_SCENARIOS["original_9bps_per_side"])
        original_holdout=breakdown["holdout"]["original_9bps_per_side"]
        stress_holdout=breakdown["holdout"]["stress_25bps_per_side"]
        blockers=[]
        if original_holdout["trades"]<HOLDOUT_MIN_TRADES:
            blockers.append("Fewer than 30 completed hypothetical holdout trades")
        if original_holdout["meanNetR"] is None or original_holdout["meanNetR"]<=0:
            blockers.append("Holdout original-cost mean R is not positive")
        if stress_holdout["meanNetR"] is None or stress_holdout["meanNetR"]<=0:
            blockers.append("Holdout stressed-cost mean R is not positive")
        blockers += [
            "No order-book depth, funding costs, exchange fills or live forward-test",
            "No position-sizing / full account drawdown model",
        ]
        outputs[symbol]={
            "status":"INSUFFICIENT_EVIDENCE_FOR_LIVE_ENTRY_SIGNAL",
            "alerts":group["alertsCount"],
            "completedHypotheticalTrades":len(trades),
            "breakdown":breakdown,
            "sidesAtOriginalCosts":side_breakdown,
            "holdsOriginalCostProfitable":(original_holdout["meanNetR"] or 0)>0,
            "holdoutHas30Trades":original_holdout["trades"]>=HOLDOUT_MIN_TRADES,
            "deploymentReady":False,
            "blockers":blockers,
        }
    return {
        "mode":"SENSITIVITY_AUDIT_OF_PAPER_BACKTEST",
        "originalSplit":report["fixedSplitUTC"],
        "costs":{name:{"totalExecutionCostBpsPerSide":bps}
                 for name,bps in COST_SCENARIOS.items()},
        "cautions":[
            "Repricing completed hypothetical trades; not a separate backtest",
            "Bootstrap/calibration and true trading profitability not established",
            "Fees and slippage are assumed; funding and gap-through-stop unmodeled",
            "Cumulative sequential R and its drawdown are NOT account equity curves",
            "2026-04 holdout has already been inspected: not an untouched future test",
            "No rule has been modified or fitted to holdout observations",
        ],
        "pairs":outputs,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    source=json.loads(Path(args.input).read_text())
    result=audit(source)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    for symbol, item in result["pairs"].items():
        if item["status"]=="UNAVAILABLE":
            print(symbol,item["status"]);continue
        print(symbol,"ALERTS",item["alerts"],"PAPER_TRADES",item["completedHypotheticalTrades"])
        for part in ("training","holdout"):
            print("  ",part.upper(),*[(
                name.replace("_per_side",""),
                round(entry["meanNetR"],4) if entry["meanNetR"] is not None else None,
                entry["trades"],entry["wins"],
                round(entry["maxDrawdownInSequentialRUnits"],3)
                if entry["maxDrawdownInSequentialRUnits"] is not None else None
            ) for name,entry in item["breakdown"][part].items()])
        print("  DEPLOYMENT",item["deploymentReady"],"BLOCKERS",item["blockers"])


if __name__=="__main__":
    main()
