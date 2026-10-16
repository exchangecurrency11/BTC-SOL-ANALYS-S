#!/usr/bin/env python3
"""One-shot, read-only diagnostic. Never changes production market data.

Probes official Binance USD-M futures public GET endpoints from a GitHub runner,
then optionally compares two last fully CLOSED 4H candle closes to Coinalyze.
No API keys, POST requests, retries on access-denied, or auto fallback.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "SOLUSDT")
HEADERS = {"User-Agent": "btc-sol-readonly-data-check/1.0", "Accept": "application/json"}


def get(path, params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(BASE + path + "?" + qs, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            body = response.read(250000)
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return "NETWORK_OR_JSON_ERROR:" + type(exc).__name__, None


def parse_iso_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main():
    try:
        coinalyze = json.loads(Path("market_data.json").read_text(encoding="utf-8"))
        groups = {(r["symbol"], r["interval"]): r for r in coinalyze.get("results", [])}
    except (OSError, ValueError, KeyError):
        groups = {}
        print("Coinalyze snapshot unavailable; Binance connectivity can still be tested.")

    reachable = 0
    for symbol in SYMBOLS:
        status, candles = get("/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": "5"})
        print(f"BINANCE 4H {symbol} HTTP_STATUS={status}")
        if status != 200:
            continue
        if not isinstance(candles, list) or len(candles) < 2:
            print("INVALID_RESPONSE: missing candle rows")
            continue
        reachable += 1
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        closed = [row for row in candles if isinstance(row, list) and len(row) >= 7
                  and int(row[6]) < now_ms - 1000]
        if not closed:
            print("INVALID_RESPONSE: no closed 4h candle")
            continue
        last = closed[-1]
        binance_close = float(last[4])
        closed_at = datetime.fromtimestamp((int(last[6])+1)/1000,timezone.utc)
        print(f"BINANCE 4H {symbol}: last_closed_at_utc={closed_at.isoformat()}, close={binance_close}")
        existing = groups.get((symbol + "_PERP.A", "4hour"))
        if existing and existing.get("status") == "READY":
            prev_close = float(existing["candle"]["close"])
            prev_end = parse_iso_utc(existing["closeTimeUTC"])
            if prev_end != closed_at:
                print(f"NOT_COMPARABLE {symbol}: Coinalyze last close time {prev_end.isoformat()} differs")
            else:
                difference = binance_close - prev_close
                percentage = abs(difference) / max(prev_close, 1e-9) * 100
                print(f"COMPARE {symbol}: coinalyze_close={prev_close} absolute_diff={difference:.8f}, pct={percentage:.6f}%")

    for symbol in SYMBOLS:
        for kind, path in [
            ("MARK_PRICE_FUNDING", "/fapi/v1/premiumIndex"),
            ("OPEN_INTEREST", "/fapi/v1/openInterest"),
        ]:
            status, body = get(path, {"symbol": symbol})
            print(f"BINANCE {kind} {symbol} HTTP_STATUS={status}")
            if status != 200 or not isinstance(body, dict) or body.get("symbol") != symbol:
                continue
            if kind == "OPEN_INTEREST":
                print(f"  OI_contracts={body.get('openInterest')} timestamp_ms={body.get('time')}")
            else:
                print(f"  markPrice={body.get('markPrice')} lastFundingRate={body.get('lastFundingRate')} "
                      f"nextFundingTime_ms={body.get('nextFundingTime')}")

    print(f"RESULT: {reachable}/{len(SYMBOLS)} Binance futures 4H endpoints reachable.")
    if reachable < len(SYMBOLS):
        print("LIMITATION: Do not integrate Binance as live dependency while access is blocked. "
              "Coinalyze pipeline remains unchanged.")


if __name__ == "__main__":
    main()
