#!/usr/bin/env python3
"""Extend verified Binance USD-M monthly archive with COMPLETE October UTC daily ZIPs.

Paper-only experimental test. Never mixes unfinished 2026-10-30 UTC candles,
never overwrites the original 24-month archive, never places exchange orders.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO,TextIOWrapper
import csv
import json
from pathlib import Path
import time
from zipfile import ZipFile

from download_binance_um_history import get, SYMBOLS, PERIODS, aggregate

DAILY_BASE="https://data.binance.vision/data/futures/um/daily/klines"


def day_bound(day):
    d=date.fromisoformat(day)
    start=int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp())
    return start,start+86400


def days_inclusive(start,end):
    d0=date.fromisoformat(start)
    d1=date.fromisoformat(end)
    if d0>d1 or (d1-d0).days>40:
        raise ValueError("Invalid UTC day range: max 41 days")
    return [(d0+timedelta(days=i)).isoformat() for i in range((d1-d0).days+1)]


def parse_daily_zip(zip_bytes, symbol, day):
    filename=f"{symbol}-1h-{day}.csv"
    with ZipFile(BytesIO(zip_bytes)) as zipfile:
        names=[name for name in zipfile.namelist() if name.endswith(".csv")]
        if len(names)!=1 or names[0].split("/")[-1]!=filename:
            raise ValueError(f"Unexpected ZIP member: {names}")
        if zipfile.getinfo(names[0]).file_size>500_000:
            raise ValueError("Daily CSV too big")
        with zipfile.open(names[0]) as handle:
            rows=[]
            reader=csv.reader(TextIOWrapper(handle,encoding="utf-8-sig"))
            for parts in reader:
                if not parts: continue
                if parts[0].lower() in ("open time","open_time"): continue
                if len(parts)<6: raise ValueError("Malformed Binance CSV")
                raw_ts=int(parts[0])
                t=raw_ts//1_000_000 if raw_ts>100_000_000_000_000 else raw_ts//1000 if raw_ts>100_000_000_000 else raw_ts
                o,h,l,c,v=map(float,parts[1:6])
                if not (l>0 and l<=min(o,c)<=max(o,c)<=h and v>=0):
                    raise ValueError("Malformed OHLCV")
                rows.append({"t":t,"o":o,"h":h,"l":l,"c":c,"v":v})
    start,_=day_bound(day)
    if len(rows)!=24 or any(b["t"]!=start+i*3600 for i,b in enumerate(rows)):
        raise ValueError(f"Missing, duplicate, incomplete or misaligned UTC day: {symbol} {day}")
    return rows


def download_day(symbol,day):
    url=f"{DAILY_BASE}/{symbol}/1h/{symbol}-1h-{day}.zip"
    archive=get(url,max_size=600_000)
    checksum=get(url+".CHECKSUM",max_size=2000).decode("utf-8-sig").strip().split()[0].lower()
    if len(checksum)!=64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Invalid daily checksum")
    digest=sha256(archive).hexdigest()
    if digest!=checksum:
        raise ValueError(f"Binance SHA256 daily mismatch: {symbol} {day}")
    return symbol,day,parse_daily_zip(archive,symbol,day),{"symbol":symbol,"date":day,"url":url,"sha256":digest,"bars":24}


def append_histories(original,extra_rows,dates):
    """Validate EXACT continuity, existing immutable base, 1H -> 4H/1D resample."""
    base={item["symbol"]:item["history"] for item in original}
    if set(base)!={s+"_PERP.A" for s in SYMBOLS}:
        raise ValueError("Original 1H archive symbols incorrect")
    result={}
    for symbol in SYMBOLS:
        raw=base[symbol+"_PERP.A"]
        if not raw or any(raw[i]["t"]+3600!=raw[i+1]["t"] for i in range(len(raw)-1)):
            raise ValueError("Original 1H gap")
        after=[bar for d in dates for bar in extra_rows[(symbol,d)]]
        if raw[-1]["t"]+3600!=after[0]["t"]:
            raise ValueError("Archive-to-current day gap / overlap")
        combined=raw+after
        if any(combined[i]["t"]+3600!=combined[i+1]["t"] for i in range(len(combined)-1)):
            raise ValueError("October gaps or duplicates")
        for tf,seconds in PERIODS.items():
            result[(symbol,tf)]=aggregate(combined,seconds)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-dir",required=True)
    p.add_argument("--output-dir",required=True)
    p.add_argument("--first-day",default="2026-10-01")
    p.add_argument("--last-day",default="2026-10-29")
    p.add_argument("--workers",type=int,default=4)
    args=p.parse_args()
    dates=days_inclusive(args.first_day,args.last_day)
    _,end=day_bound(dates[-1])
    if end>int(time.time()):
        p.error("Refuse not-yet-closed UTC day")
    if not 1<=args.workers<=6:
        p.error("Choose between 1 and 6 download workers")
    base_dir=Path(args.base_dir)
    base=json.loads((base_dir/"history_1hour.json").read_text())
    original_manifest=json.loads((base_dir/"source_manifest.json").read_text())
    if original_manifest.get("endExclusiveUTC")!=datetime.fromtimestamp(day_bound(dates[0])[0],timezone.utc).isoformat():
        raise ValueError("Original monthly archive end and new daily start mismatch")
    results={}
    audit=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        requests=[pool.submit(download_day,s,day) for s in SYMBOLS for day in dates]
        for future in as_completed(requests):
            symbol,day,rows,meta=future.result()
            results[(symbol,day)]=rows
            audit.append(meta)
            print("VERIFIED DAILY",symbol,day,len(rows),flush=True)
    data=append_histories(base,results,dates)
    output=Path(args.output_dir)
    output.mkdir(parents=True,exist_ok=True)
    counts={}
    for tf in PERIODS:
        records=[]
        for symbol in SYMBOLS:
            records.append({"symbol":symbol+"_PERP.A","history":data[(symbol,tf)]})
            counts.setdefault(symbol,{})[tf]=len(data[(symbol,tf)])
        (output/f"history_{tf}.json").write_text(json.dumps(records,separators=(",",":"))+"\n")
    manifest={
        "source":"Binance USD-M Futures archive MONTHLY + daily 1h ZIP with SHA256",
        "baseMonthlyManifest":original_manifest,
        "additionalDailyZipFilesVerified":len(audit),
        "additionalDailyFiles":sorted(audit,key=lambda item:(item["symbol"],item["date"])),
        "endExclusiveUTC":datetime.fromtimestamp(end,timezone.utc).isoformat(),
        "counts":counts,
        "caveat":"Only completed UTC days; data differ from Coinalyze live feed; not live market",
    }
    (output/"extended_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("OCTOBER EXTENDED",json.dumps({"endExclusiveUTC":manifest["endExclusiveUTC"],
                                      "additionalDailyZipFilesVerified":len(audit),
                                      "counts":counts}),flush=True)


if __name__=="__main__":
    main()
