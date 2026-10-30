#!/usr/bin/env python3
"""Download verified Binance USD-M FUTURES 1h monthly klines, resample 4h/1d.

Strictly historical, read-only source (data.binance.vision), NO API KEYS.
No live trading, GitHub branch writes, Cloudflare changes or alert delivery.
Only COMPLETE monthly bundles accepted; a missing ZIP/checksum/1h candle fails.
"""
import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

BASE="https://data.binance.vision/data/futures/um/monthly/klines"
SYMBOLS=("BTCUSDT", "SOLUSDT")
PERIODS={"1hour": 3600, "4hour": 14400, "daily": 86400}
USER_AGENT="BTC-SOL-ANALYS-S-experiment-read-only/1.0"
MAX_ZIP_SIZE=7_000_000


def months_inclusive(start, end):
    sy,sm=(int(v) for v in start.split("-"))
    ey,em=(int(v) for v in end.split("-"))
    if (sy,sm)>(ey,em) or min(sm,em)<1 or max(sm,em)>12:
        raise ValueError("Invalid year-month range")
    return [f"{y:04d}-{m:02d}" for y in range(sy,ey+1)
            for m in range(1,13) if (sy,sm)<=(y,m)<=(ey,em)]


def month_start(ym):
    return int(datetime(int(ym[:4]),int(ym[5:]),1,tzinfo=timezone.utc).timestamp())


def month_end(ym):
    y,m=int(ym[:4]),int(ym[5:])
    return month_start(f"{y+1:04d}-01" if m==12 else f"{y:04d}-{m+1:02d}")


def get(url, max_size=MAX_ZIP_SIZE):
    last=None
    for retry in range(4):
        try:
            req=Request(url,headers={"User-Agent":USER_AGENT})
            with urlopen(req,timeout=35) as res:
                length=res.headers.get("Content-Length")
                if length is not None and int(length)>max_size:
                    raise ValueError("Archive exceeds size limit")
                data=res.read(max_size+1)
                if len(data)>max_size:
                    raise ValueError("Archive exceeds size limit")
                return data
        except (HTTPError,URLError,TimeoutError) as error:
            last=error
            if isinstance(error,HTTPError) and error.code in (400,401,403,404):
                break
            if retry<3: time.sleep(1.5*(retry+1))
    raise RuntimeError(f"Cannot retrieve {url}: {last}")


def parse_zip(zip_bytes, *, symbol, month):
    filename=f"{symbol}-1h-{month}.csv"
    with ZipFile(BytesIO(zip_bytes)) as archive:
        names=[name for name in archive.namelist() if name.endswith(".csv")]
        if len(names)!=1 or names[0].split("/")[-1]!=filename:
            raise ValueError(f"Unexpected ZIP member {names}")
        if archive.getinfo(names[0]).file_size>6_000_000:
            raise ValueError("CSV exceeds uncompressed size limit")
        with archive.open(names[0]) as raw:
            reader=csv.reader(TextIOWrapper(raw,encoding="utf-8-sig"))
            output=[]
            for record in reader:
                if not record: continue
                if record[0].strip().lower() in ("open time","open_time"): continue
                if len(record)<6:
                    raise ValueError("Malformed Binance kline CSV")
                raw_ts=int(record[0])
                # Official UM klines are milliseconds; safely accept us if changed.
                timestamp=(raw_ts//1_000_000 if raw_ts>100_000_000_000_000
                           else raw_ts//1000 if raw_ts>100_000_000_000 else raw_ts)
                if timestamp%3600:
                    raise ValueError("Misaligned 1H open time")
                o,h,l,c,v=(float(x) for x in record[1:6])
                if not (l>0 and l<=min(o,c)<=max(o,c)<=h and v>=0):
                    raise ValueError("Malformed kline OHLCV")
                output.append({"t":timestamp,"o":o,"h":h,"l":l,"c":c,"v":v})
    start,end=month_start(month),month_end(month)
    if len(output)!=(end-start)//3600:
        raise ValueError(f"Missing/extra candles in {symbol} {month}: {len(output)}")
    if any(bar["t"]!=start+i*3600 for i,bar in enumerate(output)):
        raise ValueError(f"Candle gap, duplicate or wrong month: {symbol} {month}")
    return output


def download_month(symbol,month):
    archive_url=f"{BASE}/{symbol}/1h/{symbol}-1h-{month}.zip"
    zip_bytes=get(archive_url)
    checksum=get(archive_url+".CHECKSUM",max_size=2000).decode("utf-8-sig").strip()
    expected=checksum.split()[0].lower()
    if len(expected)!=64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("Malformed Binance archive checksum")
    digest=sha256(zip_bytes).hexdigest()
    if digest!=expected:
        raise ValueError(f"SHA256 checksum mismatch: {symbol} {month}")
    rows=parse_zip(zip_bytes,symbol=symbol,month=month)
    return symbol,month,rows,{"sha256":digest,"url":archive_url,"bars":len(rows)}


def aggregate(rows, seconds):
    if seconds==3600:
        return rows
    batch=seconds//3600
    if len(rows)%batch:
        raise ValueError("Non-full 4H/1D candle at dataset boundary")
    output=[]
    for i in range(0,len(rows),batch):
        chunk=rows[i:i+batch]
        if (chunk[0]["t"]%seconds or len(chunk)!=batch or
            any(b["t"]!=chunk[0]["t"]+j*3600 for j,b in enumerate(chunk))):
            raise ValueError("Cannot aggregate noncontinuous or misaligned candles")
        output.append({
            "t":chunk[0]["t"],
            "o":chunk[0]["o"],
            "h":max(b["h"] for b in chunk),
            "l":min(b["l"] for b in chunk),
            "c":chunk[-1]["c"],
            "v":sum(b["v"] for b in chunk),
        })
    return output


def build(month_data, first, last):
    months=months_inclusive(first,last)
    start,end=month_start(first),month_end(last)
    data={}
    summary={}
    for symbol in SYMBOLS:
        items=[month_data[(symbol,month)] for month in months]
        one=[row for item in items for row in item]
        expected=(end-start)//3600
        if len(one)!=expected or any(row["t"]!=start+i*3600 for i,row in enumerate(one)):
            raise ValueError("Cross-month 1H data gap or duplicate")
        if start%86400 or end%86400:
            raise ValueError("Dataset must start/end on UTC day boundary")
        for tf,secs in PERIODS.items():
            data[(symbol,tf)]=aggregate(one,secs)
        summary[symbol]={tf:len(data[(symbol,tf)]) for tf in PERIODS}
    return data,summary,start,end


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start",default="2024-10")
    parser.add_argument("--end",default="2026-09")
    parser.add_argument("--output-dir",default="binance_history")
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    months=months_inclusive(args.start,args.end)
    if not 1<=len(months)<=36 or not 1<=args.workers<=6:
        parser.error("Choose 1-36 complete months and 1-6 workers")
    if month_end(args.end)>int(time.time()):
        parser.error("Latest month must be fully complete")
    result={}
    manifest=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks={pool.submit(download_month,s,m):(s,m) for s in SYMBOLS for m in months}
        for job in as_completed(tasks):
            symbol,month=tasks[job]
            s,m,rows,proof=job.result()
            result[(s,m)]=rows
            manifest.append({"symbol":s,"month":m,**proof})
            print(f"VERIFIED {symbol} {month}: {len(rows)} 1H candles",flush=True)
    data,counts,start,end=build(result,args.start,args.end)
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    for tf in PERIODS:
        packed=[{"symbol":s+"USDT_PERP.A","history":data[(s,tf)]} for s in SYMBOLS]
        (out/f"history_{tf}.json").write_text(json.dumps(packed,separators=(",",":"))+"\n")
    summary={
        "source":"Binance official data.binance.vision FUTURES/UM monthly 1h klines",
        "firstUTC":datetime.fromtimestamp(start,timezone.utc).isoformat(),
        "endExclusiveUTC":datetime.fromtimestamp(end,timezone.utc).isoformat(),
        "pairCounts":counts,
        "checksumsVerified":len(manifest),
        "inputFiles":sorted(manifest,key=lambda m:(m["symbol"],m["month"])),
        "timeframes":"4H and Daily derived from EXACT 1H Binance futures OHLCV on UTC boundaries",
        "limitations":"Only historical closed candles; not Binance live API, no funding/trade execution",
    }
    (out/"source_manifest.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({k:summary[k] for k in ("firstUTC","endExclusiveUTC","pairCounts","checksumsVerified")},indent=2))


if __name__=="__main__":
    main()
