#!/usr/bin/env python3
"""Forensic audit of closed-paper trades after October archive extension.

DESCRIPTIVE associations only. These subgroups are NOT causal mechanisms,
out-of-sample parameter performance, or independent live trade recommendations.
Uses only alert fields available at alert close, and existing paper-trade results.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from statistics import mean

from audit_paper_robustness_v5 import modeled_net_r

APRIL=int(datetime(2026,4,1,tzinfo=timezone.utc).timestamp())
OCTOBER=int(datetime(2026,10,1,tzinfo=timezone.utc).timestamp())


def classify(alert,trade):
    rsi=float(alert["RSI14"])
    vol=float(alert["volumeChangePct"])
    side=trade["side"]
    if side!=alert["side"]:
        raise ValueError("Trade direction differs from its historical warning")
    if trade["watchKnownUTC"]!=alert["knownUTC"]:
        raise ValueError("Mismatched event timestamp")
    lag=(trade["retestKnownUTC"]-trade["watchKnownUTC"])/3600
    if not 0<lag<=6:
        raise ValueError("Unexpected future/early retest")
    return {
        "extremeRSI": rsi<=30 if side=="bearish" else rsi>=70,
        "RSIAtWarning":rsi,
        "volumeChangePctAtWarning":vol,
        "volumeBand": "20-49%" if vol<50 else "50-99%" if vol<100 else "100%+",
        "retestDelayHours":lag,
        "retestDelayBand":"1-2h" if lag<=2 else "3-6h",
        "stopDistancePercent":100*float(trade["risk"])/float(trade["entry"]),
        "stopWidthBand":"<1%" if trade["risk"]/trade["entry"]<.01 else "1-4%",
        "direction":side,
        "firstTargetBeforeStop":int(trade["targetCount"])>0,
        "failedBeforeTP1":trade["exitReason"]=="STOP_FIRST_OR_AFTER_TP" and int(trade["targetCount"])==0,
        "stopAfterPartialTP":trade["exitReason"]=="STOP_FIRST_OR_AFTER_TP" and int(trade["targetCount"])>0,
        "exitReason":trade["exitReason"],
    }


def group_summary(records):
    if not records:
        return {"trades":0,"positiveAfterAssumedFees":0,"meanNetR":None,"stopsBeforeTP1":0}
    return {
        "trades":len(records),
        "positiveAfterAssumedFees":sum(r["netR"]>0 for r in records),
        "meanNetR":mean(r["netR"] for r in records),
        "stopsBeforeTP1":sum(r["features"]["failedBeforeTP1"] for r in records),
    }


def audit(report):
    if report.get("mode")!="PAPER_ONLY_OFFLINE_EXPERIMENT":
        raise ValueError("Paper backtest results required")
    output={}
    for symbol,item in report["results"].items():
        if item.get("status")!="PAPER_BACKTEST_NOT_LIVE":
            raise ValueError(f"Unready symbol {symbol}")
        alerts={a["knownUTC"]:a for a in item["alerts"]}
        unique=set()
        records=[]
        for trade in item["trades"]:
            key=trade["watchKnownUTC"]
            if key not in alerts:
                raise ValueError("Trade has no prior on-time early warning")
            if trade["entryOpenUTC"]<=trade["retestKnownUTC"]-1:
                raise ValueError("Future or same-bar hypothetical fill")
            ident=(key,trade["entryOpenUTC"])
            if ident in unique:
                raise ValueError("Duplicate hypothetical trade")
            unique.add(ident)
            features=classify(alerts[key],trade)
            r=modeled_net_r(trade,9)
            records.append({
                "warningUTC":datetime.fromtimestamp(key,timezone.utc).isoformat(),
                "entryUTC":datetime.fromtimestamp(trade["entryOpenUTC"],timezone.utc).isoformat(),
                "entryOpenUTC":trade["entryOpenUTC"],
                "netR":r,
                "features":features,
            })
        groups={
            "period":{
                "earlierTraining":lambda r:r["entryOpenUTC"]<APRIL,
                "priorSixMonthsAprSep":lambda r:APRIL<=r["entryOpenUTC"]<OCTOBER,
                "OctoberNewDiagnostic":lambda r:r["entryOpenUTC"]>=OCTOBER,
            },
            "direction":{
                "long":lambda r:r["features"]["direction"]=="bullish",
                "short":lambda r:r["features"]["direction"]=="bearish",
            },
            "extremeRSI":{
                "extremeAtWarning":lambda r:r["features"]["extremeRSI"],
                "notExtremeAtWarning":lambda r:not r["features"]["extremeRSI"],
            },
            "volumeAtWarning":{
                "20-49%":lambda r:r["features"]["volumeBand"]=="20-49%",
                "50-99%":lambda r:r["features"]["volumeBand"]=="50-99%",
                "100%+":lambda r:r["features"]["volumeBand"]=="100%+",
            },
            "retestDelay":{
                "1-2h":lambda r:r["features"]["retestDelayBand"]=="1-2h",
                "3-6h":lambda r:r["features"]["retestDelayBand"]=="3-6h",
            },
            "stopDistance":{
                "<1%":lambda r:r["features"]["stopWidthBand"]=="<1%",
                "1-4%":lambda r:r["features"]["stopWidthBand"]=="1-4%",
            },
        }
        dimensions={name:{label:group_summary([r for r in records if fn(r)])
                          for label,fn in filters.items()}
                    for name,filters in groups.items()}
        losses=[r for r in records if r["netR"]<=0]
        output[symbol]={
            "numberAlerts":item["alertsCount"],
            "paperTrades":len(records),
            "paperLosingTrades":len(losses),
            "stopsBeforeTP1":sum(r["features"]["failedBeforeTP1"] for r in records),
            "stopsAfterPartialTP":sum(r["features"]["stopAfterPartialTP"] for r in records),
            "paperTradesNotProfit":group_summary(losses),
            "subgroupsObservedAssociationsOnly":dimensions,
            "paperTradeDetails":records,
        }
    return {
        "mode":"DESCRIPTIVE_PAPER_TRADE_FORENSICS_V6",
        "rulesUnchanged":True,
        "costPerSideAssumedBps":9,
        "sourceLimitations":[
            "No intrabar path, liquidity, orderbook, funding or actual fills",
            "RSI and volume are known at BOS close only, NOT causal false-breakout explanations",
            "A TP not reached before stop is an outcome, not direct proof of fake BOS",
            "RSI/volume/lag subgroup figures are POST-HOC and must not guide live entry",
            "Skipped trades would alter later available signals; subgroup exclusion is not a valid strategy backtest",
            "April-Sep results previously inspected; October is supplementary historical diagnostic, not live forward-test",
        ],
        "results":output,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    result=audit(json.loads(Path(args.input).read_text()))
    Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    for symbol,data in result["results"].items():
        print(symbol,"ALERTS",data["numberAlerts"],"PAPER_TRADES",data["paperTrades"],
              "LOSERS",data["paperLosingTrades"],"STOP_BEFORE_TP1",data["stopsBeforeTP1"])
        for name in ("period","direction","extremeRSI","volumeAtWarning","retestDelay","stopDistance"):
            print(" ",name,{key:{k:round(v,3) if isinstance(v,float) else v for k,v in stats.items()}
                              for key,stats in data["subgroupsObservedAssociationsOnly"][name].items()})


if __name__=="__main__":
    main()
