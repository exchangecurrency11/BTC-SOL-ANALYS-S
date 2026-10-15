"""Download closed 4-hour BTCUSDT and SOLUSDT candles from Binance USDT-M Futures.

Public market data only. No Binance account or API key is required.
Run: python fetch_data.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://fapi.binance.com/fapi/v1/klines"
SYMBOLS = ("BTCUSDT", "SOLUSDT")
INTERVAL = "4h"
LIMIT = 20
OUTPUT_FILE = Path("data/market_data.json")


def utc_iso(timestamp_ms):
    return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).isoformat()


def get_closed_candles(symbol):
    query = urlencode({"symbol": symbol, "interval": INTERVAL, "limit": LIMIT})
    request = Request(f"{API_URL}?{query}", headers={"User-Agent": "MarketDataResearch/1.0"})

    with urlopen(request, timeout=30) as response:
        rows = json.load(response)

    if not isinstance(rows, list):
        raise ValueError(f"Unexpected Binance response for {symbol}: {rows}")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed_rows = [row for row in rows if int(row[6]) < now_ms]
    if not closed_rows:
        raise ValueError(f"No completed {INTERVAL} candles found for {symbol}.")

    return [
        {
            "open_time_utc": utc_iso(row[0]),
            "close_time_utc": utc_iso(row[6]),
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume_base_asset": row[5],
            "volume_quote_asset": row[7],
            "number_of_trades": row[8],
        }
        for row in closed_rows
    ]


def main():
    result = {
        "source": "Binance USDT-M Futures /fapi/v1/klines (not spot)",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "interval": INTERVAL,
        "symbols": {},
    }

    for symbol in SYMBOLS:
        candles = get_closed_candles(symbol)
        result["symbols"][symbol] = candles
        latest = candles[-1]
        print(f"{symbol}: last CLOSED 4H candle close={latest['close']} USDT, time={latest['close_time_utc']}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
